"""NovelAI テキスト Provider（計画書 §2、Phase 1）。

Provider は通信だけを受け持ち、文章操作の意味論（Continue / Expand など）や整形は持たない。

- ``stream(request)`` は ``Generation`` を返す。本文片を順に受け取り、``cancel()`` で途中で止められる。
- ``generate(request)`` はストリームを最後まで読んで ``GenerationResult`` を返す
  （NovelAI の非ストリーム応答は本文が空になるため、内部では常にストリームを使う）。
- ``cancel(generation)`` は別スレッドからでも呼べる。止めた時点までの本文は ``status = "incomplete"`` で残す（§46）。
- 同時生成は 1 アカウント 1 本まで（Phase 0 実測）。プロセス内はアカウントごとのスロットで直列にし、
  ほかのプロセスや Web UI と重なったときの 429「Concurrent generation is locked」は待って送り直す。
- 送る前に Capability Profile で、モデル・エンドポイント・文脈上限（入力の推定＋max_tokens）を確かめる。

トークンは表示・保存しない（``preview`` と ``repr`` では伏せる）。
"""

from __future__ import annotations

import hashlib
import inspect
import threading
import time
import uuid
from collections.abc import Callable, Generator, Iterator, Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from . import novelai as nai
from .profiles import CapabilityProfile, EndpointKind, load_profiles
from .transport import StreamHandle, Transport, TransportError, UrllibTransport

Status = Literal["complete", "incomplete", "error"]
CONCURRENCY_LOCKED = 429


class ProviderError(RuntimeError):
    """送る前に分かる誤り（未知のモデル、文脈上限の超過など）。"""


class ContextLimitError(ProviderError):
    pass


class ConcurrencyBusyError(ProviderError):
    """同時生成のスロットを待ち時間内に取れなかった。"""


@dataclass(frozen=True)
class GenerationRequest:
    model: str
    endpoint: EndpointKind
    max_tokens: int
    messages: tuple[Mapping[str, str], ...] | None = None
    prompt: str | None = None
    sampling: Mapping[str, Any] = field(default_factory=dict)
    stop: tuple[str, ...] = ()

    def body(self) -> dict[str, Any]:
        if self.endpoint == "chat":
            return nai.build_chat_body(self.model, [dict(m) for m in self.messages or ()], max_tokens=self.max_tokens,
                                       sampling=dict(self.sampling), stop=list(self.stop) or None)
        return nai.build_completions_body(self.model, self.prompt or "", max_tokens=self.max_tokens,
                                          sampling=dict(self.sampling), stop=list(self.stop) or None)

    def input_text(self) -> str:
        if self.endpoint == "chat":
            return "\n".join(m.get("content", "") for m in self.messages or ())
        return self.prompt or ""


@dataclass(frozen=True)
class StreamChunk:
    text: str
    tokens: int


@dataclass
class GenerationResult:
    generation_id: str
    model: str
    status: Status
    text: str = ""
    output_tokens: int = 0
    finish_reason: str | None = None
    cancelled: bool = False
    error: str | None = None
    http_status: int | None = None
    attempts: int = 0
    first_chunk_sec: float | None = None
    total_sec: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TokenEstimate:
    tokens: int
    method: Literal["benchmark_estimate"]
    chars_per_token: float


# ---- 同時生成のスロット ------------------------------------------------------

_SLOTS: dict[str, threading.BoundedSemaphore] = {}
_SLOTS_LOCK = threading.Lock()


def account_slot(token: str, size: int) -> threading.BoundedSemaphore:
    """アカウント（トークン）ごとに 1 つのスロット。同じプロセスの Provider 間で共有する。"""
    key = hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]
    with _SLOTS_LOCK:
        if key not in _SLOTS:
            _SLOTS[key] = threading.BoundedSemaphore(size)
        return _SLOTS[key]


# ---- 生成 1 本 -----------------------------------------------------------------

class Generation:
    """ストリーム生成 1 本。反復で本文片を受け取り、``cancel()`` で止め、``result()`` で結果を得る。

    ``with`` で使うと、読み切らずに抜けたときはキャンセルしてスロットを返す。
    """

    def __init__(self, generation_id: str, model: str, handle: StreamHandle, release: Callable[[], None],
                 attempts: int, started: float) -> None:
        self.id = generation_id
        self.model = model
        self._handle = handle
        self._release = release
        self._released = False
        self._lock = threading.Lock()
        self._cancel = threading.Event()
        self._started = started
        self._text: list[str] = []
        self._tokens = 0
        self._finish_reason: str | None = None
        self._done = False
        self._finished = False
        self._error: str | None = None
        self._first_chunk: float | None = None
        self._ended: float | None = None
        self._attempts = attempts
        self._gen: Generator[StreamChunk, None, None] | None = None

    # 反復 ----------------------------------------------------------------
    def __iter__(self) -> Iterator[StreamChunk]:
        # 読み取りは 1 本だけ。途中で for を抜けても、次の反復や result() は続きから読む。
        if self._gen is None:
            self._gen = self._run()
        return self._gen

    def _run(self) -> Generator[StreamChunk, None, None]:
        try:
            for event in nai.iter_sse_payloads(self._lines()):
                if self._cancel.is_set():
                    break
                if event == nai.DONE:
                    self._done = True
                    break
                assert isinstance(event, dict)
                text = nai.delta_text(event)
                tokens = nai.chunk_token_count(event)
                choices = event.get("choices") or []
                if choices and choices[0].get("finish_reason"):
                    self._finish_reason = choices[0]["finish_reason"]
                if text or tokens:
                    if self._first_chunk is None:
                        self._first_chunk = time.monotonic()
                    self._text.append(text)
                    self._tokens += tokens
                    yield StreamChunk(text, tokens)
        except Exception as e:  # noqa: BLE001 - 切断やキャンセルでの読み取り失敗。本文は残す
            if not self._cancel.is_set():
                self._error = f"{type(e).__name__}: {e}"
        finally:
            self._finish()

    def _lines(self) -> Iterator[bytes]:
        for line in self._handle:
            if self._cancel.is_set():
                return
            yield line

    # 停止と後始末 --------------------------------------------------------
    def cancel(self) -> None:
        """どのスレッドからでも呼べる。読み取り中の接続を閉じ、ここまでの本文を残す。"""
        self._cancel.set()
        self._handle.close()
        gen = self._gen
        if gen is not None:
            if inspect.getgeneratorstate(gen) == inspect.GEN_RUNNING:
                return  # 別スレッドで読み取り中。接続を閉じたので、そちらが抜けて後始末する
            try:
                gen.close()  # 止まっている読み取りを閉じ、finally でスロットを返す
            except ValueError:  # 確認の直後に別スレッドが読み始めた
                return
        self._finish()

    def _finish(self) -> None:
        with self._lock:
            if self._finished:
                return
            self._finished = True
            self._ended = time.monotonic()
            self._handle.close()
            if not self._released:
                self._released = True
                self._release()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def result(self) -> GenerationResult:
        """結果を返す。まだ読み終えていなければ最後まで読む。"""
        if not self._finished:
            for _ in iter(self):
                pass
        if self._cancel.is_set():
            status: Status = "incomplete"
        elif self._error:
            status = "incomplete" if self._text else "error"
        elif self._done or self._finish_reason:
            status = "complete"
        else:
            status = "incomplete"  # 終端なしで切れた
        ended = self._ended or time.monotonic()
        return GenerationResult(
            generation_id=self.id, model=self.model, status=status, text="".join(self._text),
            output_tokens=self._tokens, finish_reason=self._finish_reason, cancelled=self._cancel.is_set(),
            error=self._error, http_status=200, attempts=self._attempts,
            first_chunk_sec=round(self._first_chunk - self._started, 3) if self._first_chunk else None,
            total_sec=round(ended - self._started, 3))

    def __enter__(self) -> Generation:
        return self

    def __exit__(self, *exc: object) -> None:
        if not self._finished:
            self.cancel()


# ---- Provider ------------------------------------------------------------------

class NovelAIProvider:
    name = "novelai"

    def __init__(self, token: str, *, profiles: dict[str, CapabilityProfile] | None = None,
                 headers: Mapping[str, str] | None = None, transport: Transport | None = None,
                 slot: threading.BoundedSemaphore | None = None, acquire_timeout: float = 120.0,
                 retry_429: int = 3, retry_wait: float = 2.0, timeout: float = 180.0,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        if not token:
            raise ProviderError("トークンが空")
        self._token = token
        self.profiles = profiles if profiles is not None else load_profiles()
        self._headers = dict(headers or {})
        self._transport = transport or UrllibTransport()
        size = min((p.concurrency for p in self.profiles.values()), default=1)
        self._slot = slot or account_slot(token, size)
        self.acquire_timeout = acquire_timeout
        self.retry_429 = retry_429
        self.retry_wait = retry_wait
        self.timeout = timeout
        self._sleep = sleep

    @classmethod
    def from_repo(cls, repo_root: Path, **kwargs: Any) -> NovelAIProvider:
        return cls(nai.load_token(repo_root), headers=nai.load_request_headers(repo_root), **kwargs)

    def __repr__(self) -> str:
        return f"NovelAIProvider(models={self.list_models()}, token=***)"

    # §2 の口 ---------------------------------------------------------------
    def list_models(self) -> list[str]:
        return sorted(self.profiles)

    def count_tokens(self, text: str, model: str, *, conservative: bool = True) -> TokenEstimate:
        """ベンチマーク実測の文字数/トークン比から推定する（§12 の第3優先）。

        ``conservative`` なら p10（1 トークンあたりの字数が少ない側＝トークン数を多めに見積もる）を使う。
        """
        profile = self._profile(model)
        ratio = profile.chars_per_token("p10" if conservative else "median") or profile.chars_per_token("median") or 1.0
        return TokenEstimate(tokens=int(len(text) / ratio) + 1, method="benchmark_estimate", chars_per_token=ratio)

    def check(self, request: GenerationRequest) -> None:
        """送る前の検査。問題があれば ``ProviderError`` を投げる。"""
        profile = self._profile(request.model)
        profile.endpoint(request.endpoint)
        if request.max_tokens <= 0:
            raise ProviderError("max_tokens は 1 以上")
        if request.endpoint == "chat" and not request.messages:
            raise ProviderError("chat には messages が要る")
        if request.endpoint == "completions" and not request.prompt:
            raise ProviderError("completions には prompt が要る")
        limit = profile.context_limit_tokens
        if limit is not None:
            estimate = self.count_tokens(request.input_text(), request.model).tokens
            if estimate + request.max_tokens > limit:
                raise ContextLimitError(
                    f"入力の推定 {estimate} + max_tokens {request.max_tokens} が文脈上限 {limit} を超える")

    def preview(self, request: GenerationRequest) -> dict[str, Any]:
        """dry-run 用。送る内容をトークンを伏せて返す。"""
        self.check(request)
        return {"method": "POST", "url": self._profile(request.model).endpoint(request.endpoint),
                "headers": {**self._headers, **self._fixed_headers(), "Authorization": "Bearer ***"},
                "body": request.body()}

    def stream(self, request: GenerationRequest) -> Generation:
        self.check(request)
        url = self._profile(request.model).endpoint(request.endpoint)
        headers = {**self._headers, **self._fixed_headers(), "Authorization": f"Bearer {self._token}"}
        if not self._slot.acquire(timeout=self.acquire_timeout):
            raise ConcurrencyBusyError(f"同時生成のスロットを {self.acquire_timeout} 秒以内に取れなかった")
        started = time.monotonic()
        attempts = 0
        try:
            while True:
                attempts += 1
                try:
                    handle = self._transport.open_stream(url, headers, request.body(), self.timeout)
                    break
                except TransportError as e:
                    if e.status == CONCURRENCY_LOCKED and attempts <= self.retry_429:
                        self._sleep(self.retry_wait * attempts)
                        continue
                    e.attempts = attempts
                    raise
        except BaseException:
            self._slot.release()
            raise
        return Generation(uuid.uuid4().hex, request.model, handle, self._slot.release, attempts, started)

    def generate(self, request: GenerationRequest) -> GenerationResult:
        """最後まで読んだ結果を返す。HTTP の誤りは ``status = "error"`` の結果にする。"""
        try:
            gen = self.stream(request)
        except TransportError as e:
            return GenerationResult(generation_id=uuid.uuid4().hex, model=request.model, status="error",
                                    error=e.body[:2000], http_status=e.status, attempts=e.attempts)
        with gen:
            return gen.result()

    def cancel(self, generation: Generation) -> None:
        generation.cancel()

    # 内部 -------------------------------------------------------------------
    def _profile(self, model: str) -> CapabilityProfile:
        if model not in self.profiles:
            raise ProviderError(f"未知のモデル {model}（{', '.join(self.list_models())}）")
        return self.profiles[model]

    @staticmethod
    def _fixed_headers() -> dict[str, str]:
        return {"Content-Type": "application/json", "Accept": "text/event-stream"}
