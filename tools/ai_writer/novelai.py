"""NovelAI テキスト API の最小クライアント（Phase 0 Spike 用）。

通信先と形式は公式仕様が未公開のため、SillyTavern の実装から得た推測値を置く。
Spike の実測で確かめ、Capability Profile に ``verified`` として記録する。

- GLM-4.6 / Xialong: ``POST https://text.novelai.net/oa/v1/chat/completions``（OpenAI 互換 SSE）
- 認証: ``Authorization: Bearer <NOVELAI_ACCESS_TOKEN>``
- 契約確認: ``GET https://image.novelai.net/user/subscription``

トークンは表示・保存しない。
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from collections.abc import Iterable, Iterator
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

TEXT_HOST = "https://text.novelai.net"
IMAGE_HOST = "https://image.novelai.net"
CHAT_PATH = "/oa/v1/chat/completions"
COMPLETIONS_PATH = "/oa/v1/completions"
SUBSCRIPTION_URL = f"{IMAGE_HOST}/user/subscription"
TOKEN_ENV = "NOVELAI_ACCESS_TOKEN"

CHAT_MODELS = ("glm-4-6", "xialong-v1")
DONE = "[DONE]"


class TokenMissingError(RuntimeError):
    """トークン未設定。値そのものはメッセージに含めない。"""


def load_token(repo_root: Path) -> str:
    """環境変数または ``.env`` から NovelAI トークンを読む。"""
    from image_provider_generate import load_dotenv, resolve_env_value

    token = resolve_env_value(TOKEN_ENV, load_dotenv(repo_root / ".env"))
    if not token:
        raise TokenMissingError(f"{TOKEN_ENV} が未設定です（.env を確認してください）")
    return token


def load_request_headers(repo_root: Path) -> dict[str, str]:
    """画像生成と共用の ``config/image_generation.json`` からブラウザ相当ヘッダを読む。

    Cloudflare が Python urllib の既定 User-Agent を 1010 で拒否するため必要。
    """
    path = repo_root / "config" / "image_generation.json"
    if not path.is_file():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    headers = ((raw.get("providers") or {}).get("novelai") or {}).get("default_request_headers") or {}
    return {str(k): str(v) for k, v in headers.items() if v is not None}


def build_chat_body(
    model: str,
    messages: list[dict[str, str]],
    *,
    max_tokens: int,
    stream: bool = True,
    sampling: dict[str, Any] | None = None,
    stop: list[str] | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "stream": stream,
    }
    if sampling:
        body.update(sampling)
    if stop:
        body["stop"] = stop
    return body


def build_completions_body(
    model: str,
    prompt: str,
    *,
    max_tokens: int,
    stream: bool = True,
    sampling: dict[str, Any] | None = None,
    stop: list[str] | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "max_tokens": max_tokens,
        "stream": stream,
    }
    if sampling:
        body.update(sampling)
    if stop:
        body["stop"] = stop
    return body


def redacted_headers() -> dict[str, str]:
    return {"Content-Type": "application/json", "Authorization": "Bearer ***"}


def iter_sse_payloads(lines: Iterable[bytes | str]) -> Iterator[dict[str, Any] | str]:
    """SSE の ``data:`` 行を JSON（または ``[DONE]``）として順に返す。

    JSON として読めない行は ``{"_unparsed": 行}`` として返し、捨てない。
    """
    for raw in lines:
        line = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
        line = line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[len("data:"):].strip()
        if not payload:
            continue
        if payload == DONE:
            yield DONE
            continue
        try:
            yield json.loads(payload)
        except json.JSONDecodeError:
            yield {"_unparsed": payload}


def delta_text(event: dict[str, Any]) -> str:
    """chat の ``delta.content`` と completions の ``text`` の両方から本文片を取る。"""
    choices = event.get("choices") or []
    if not choices:
        return ""
    choice = choices[0]
    delta = choice.get("delta") or {}
    return delta.get("content") or choice.get("text") or ""


def chunk_token_count(event: dict[str, Any]) -> int:
    """チャンクの ``choices[0].token_ids`` の数。終端トークンだけのチャンク（本文なし）は数えない。"""
    choices = event.get("choices") or []
    if not choices:
        return 0
    ids = choices[0].get("token_ids") or []
    if not delta_text(event) and choices[0].get("finish_reason") == "stop":
        return 0
    return len(ids)


@dataclass
class CallResult:
    url: str
    status: int | None = None
    ok: bool = False
    text: str = ""
    events: int = 0
    done_seen: bool = False
    finish_reason: str | None = None
    usage: dict[str, Any] | None = None
    first_chunk_sec: float | None = None
    total_sec: float | None = None
    cancelled: bool = False
    error: str | None = None
    response_headers: dict[str, str] = field(default_factory=dict)
    output_tokens: int = 0
    """各チャンクの ``choices[0].token_ids`` の合計。ストリームでは usage が返らないため、これを出力トークン数とする。"""
    first_event: Any = None
    last_event: Any = None
    raw_json: Any = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_KEEP_HEADERS = ("content-type", "x-ratelimit-limit", "x-ratelimit-remaining", "x-ratelimit-reset", "retry-after")


def _pick_headers(headers: Any) -> dict[str, str]:
    return {k: headers[k] for k in _KEEP_HEADERS if headers.get(k) is not None}


def _request(url: str, token: str, body: dict[str, Any] | None, method: str,
             headers: dict[str, str] | None, accept: str) -> urllib.request.Request:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", accept)
    req.add_header("Authorization", f"Bearer {token}")
    return req


def _read_error(e: urllib.error.HTTPError) -> str:
    try:
        return e.read().decode("utf-8", errors="replace")[:2000]
    except Exception:  # noqa: BLE001
        return ""


def call_json(url: str, token: str, body: dict[str, Any] | None = None, *, method: str = "POST",
              headers: dict[str, str] | None = None, timeout: float = 120.0) -> CallResult:
    """非ストリームの呼び出し。応答 JSON をそのまま ``raw_json`` に残す。"""
    result = CallResult(url=url)
    start = time.monotonic()
    try:
        with urllib.request.urlopen(_request(url, token, body, method, headers, "application/json, */*"), timeout=timeout) as resp:
            result.status = resp.status
            result.response_headers = _pick_headers(resp.headers)
            raw = resp.read().decode("utf-8", errors="replace")
        try:
            result.raw_json = json.loads(raw)
        except json.JSONDecodeError:
            result.raw_json = {"_unparsed": raw[:2000]}
        if isinstance(result.raw_json, dict):
            choices = result.raw_json.get("choices") or []
            if choices:
                choice = choices[0]
                message = choice.get("message") or {}
                result.text = message.get("content") or choice.get("text") or ""
                result.finish_reason = choice.get("finish_reason")
            result.usage = result.raw_json.get("usage")
        result.ok = True
    except urllib.error.HTTPError as e:
        result.status = e.code
        result.error = _read_error(e)
    except urllib.error.URLError as e:
        result.error = f"URLError: {e.reason}"
    result.total_sec = round(time.monotonic() - start, 3)
    return result


def call_stream(
    url: str,
    token: str,
    body: dict[str, Any],
    *,
    headers: dict[str, str] | None = None,
    timeout: float = 180.0,
    cancel_after_chars: int | None = None,
) -> CallResult:
    """SSE で受け取り、本文片をつなぐ。``cancel_after_chars`` に達したら接続を閉じる。"""
    result = CallResult(url=url)
    start = time.monotonic()
    try:
        with urllib.request.urlopen(_request(url, token, body, "POST", headers, "text/event-stream"), timeout=timeout) as resp:
            result.status = resp.status
            result.response_headers = _pick_headers(resp.headers)
            for event in iter_sse_payloads(resp):
                if event == DONE:
                    result.done_seen = True
                    break
                assert isinstance(event, dict)
                result.events += 1
                if result.first_event is None:
                    result.first_event = event
                    result.first_chunk_sec = round(time.monotonic() - start, 3)
                result.last_event = event
                result.text += delta_text(event)
                result.output_tokens += chunk_token_count(event)
                choices = event.get("choices") or []
                if choices and choices[0].get("finish_reason"):
                    result.finish_reason = choices[0]["finish_reason"]
                if event.get("usage"):
                    result.usage = event["usage"]
                if cancel_after_chars is not None and len(result.text) >= cancel_after_chars:
                    result.cancelled = True
                    break
        result.ok = True
    except urllib.error.HTTPError as e:
        result.status = e.code
        result.error = _read_error(e)
    except urllib.error.URLError as e:
        result.error = f"URLError: {e.reason}"
    except TimeoutError:
        result.error = "timeout"
    result.total_sec = round(time.monotonic() - start, 3)
    return result
