"""Core Writer（Phase 1）。Router → PromptRenderer → Provider → 後処理 →（任意で）Minimum Guard を 1 本の生成としてまとめる。

- ``plan()``: dry-run。送る内容（トークンは伏せる）と経路・版を返し、通信しない。
- ``run()``: 最後まで生成して整形した結果を返す。
- ``start()``: 本文片を順に受け取り、``cancel()`` で途中で止められるセッションを返す。止めた結果も
  ``generation.status = "incomplete"`` として生出力ごと残す（§46）。

結果の ``record()`` は生出力・整形後の本文・切り落とした範囲と理由・経路・各版を持ち、
Generation Manifest（§48）と探索機能の候補保存の素材にする。採用や正本への書込みはここでは行わない。
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import asdict, dataclass
from typing import Any

from .guard import GuardReport, MinimumGuard
from .postprocess import POSTPROCESS_VERSION, CleanResult, clean_for
from .prompt_renderer import OperationInput, RenderedPrompt, render
from .provider import Generation, GenerationResult, NovelAIProvider, StreamChunk, TokenEstimate
from .transport import TransportError
from .router import OperationRouter, Route, SamplingName


@dataclass
class WriterOutput:
    route: Route
    rendered: RenderedPrompt
    request_preview: dict[str, Any]
    generation: GenerationResult
    cleaned: CleanResult
    guard: GuardReport | None = None
    data: OperationInput | None = None
    context_tokens: TokenEstimate | None = None

    @property
    def text(self) -> str:
        return self.cleaned.text

    def record(self) -> dict[str, Any]:
        """保存用の辞書。トークンは含まない（``request_preview`` は伏せた形）。"""
        return {
            "operation": self.route.operation,
            "model": self.route.model,
            "route_reason": self.route.reason,
            "profile_revision": self.route.profile_revision,
            "sampling": {"name": self.route.sampling.name, "values": self.route.sampling.values,
                         "verified": self.route.sampling.verified},
            "renderer_version": self.rendered.version,
            "render_params": dict(self.rendered.params),
            "postprocess_version": self.cleaned.version,
            "request": self.request_preview,
            "generation": self.generation.to_dict(),
            "raw_text": self.generation.text,
            "text": self.cleaned.text,
            "removals": [asdict(r) for r in self.cleaned.removals],
            "review": [asdict(r) for r in self.cleaned.review],
            "flags": self.cleaned.flags,
            "guard": self.guard.to_dict() if self.guard else None,
            "context_tokens": asdict(self.context_tokens) if self.context_tokens else None,
        }


class WriterSession:
    """``start()`` が返す生成 1 本。反復で本文片を受け取り、``finish()`` で整形済みの結果を得る。"""

    def __init__(self, route: Route, rendered: RenderedPrompt, preview: dict[str, Any], generation: Generation,
                 data: OperationInput, guard: MinimumGuard | None = None,
                 context_tokens: TokenEstimate | None = None) -> None:
        self.route = route
        self.rendered = rendered
        self._preview = preview
        self.generation = generation
        self._data = data
        self._guard = guard
        self._context_tokens = context_tokens

    def __iter__(self) -> Iterator[StreamChunk]:
        return iter(self.generation)

    def cancel(self) -> None:
        self.generation.cancel()

    def finish(self) -> WriterOutput:
        result = self.generation.result()
        cleaned = clean_for(self.route.operation, result.text)
        report = self._guard.check(cleaned.text, self._data, self.rendered) if self._guard else None
        return WriterOutput(self.route, self.rendered, self._preview, result, cleaned, report, self._data,
                            self._context_tokens)

    def __enter__(self) -> WriterSession:
        return self

    def __exit__(self, *exc: object) -> None:
        self.generation.__exit__(*exc)


class CoreWriter:
    def __init__(self, provider: NovelAIProvider, router: OperationRouter | None = None,
                 guard: MinimumGuard | None = None) -> None:
        self.provider = provider
        self.router = router or OperationRouter(provider.profiles)
        self.guard = guard

    def _prepare(self, operation: str, data: OperationInput, model: str | None, sampling: SamplingName,
                 stop: tuple[str, ...]) -> tuple[Route, RenderedPrompt, dict[str, Any]]:
        route = self.router.resolve(operation, model=model, sampling=sampling)
        rendered = render(operation, data, route.model, sampling=route.sampling.values, stop=stop)
        if rendered.request.endpoint != route.endpoint:
            raise AssertionError(f"Router と PromptRenderer のエンドポイントが食い違う: {route.endpoint} / {rendered.request.endpoint}")
        return route, rendered, self.provider.preview(rendered.request)

    def _estimate(self, rendered: RenderedPrompt) -> TokenEstimate:
        """入力のトークン数の推定（ベンチマーク実測の p10 で多めに見積もる。Manifest の Context token count）。"""
        return self.provider.count_tokens(rendered.request.input_text(), rendered.request.model)

    def plan(self, operation: str, data: OperationInput, *, model: str | None = None,
             sampling: SamplingName = "stable", stop: tuple[str, ...] = ()) -> dict[str, Any]:
        route, rendered, preview = self._prepare(operation, data, model, sampling, stop)
        return {"operation": operation, "model": route.model, "route_reason": route.reason,
                "sampling": route.sampling.name, "sampling_verified": route.sampling.verified,
                "renderer_version": rendered.version, "postprocess_version": POSTPROCESS_VERSION, "request": preview}

    def start(self, operation: str, data: OperationInput, *, model: str | None = None,
              sampling: SamplingName = "stable", stop: tuple[str, ...] = ()) -> WriterSession:
        route, rendered, preview = self._prepare(operation, data, model, sampling, stop)
        return WriterSession(route, rendered, preview, self.provider.stream(rendered.request), data, self.guard,
                             self._estimate(rendered))

    def run(self, operation: str, data: OperationInput, *, model: str | None = None,
            sampling: SamplingName = "stable", stop: tuple[str, ...] = ()) -> WriterOutput:
        """最後まで生成する。HTTP の誤りは例外にせず ``generation.status = "error"`` の結果で返す。"""
        route, rendered, preview = self._prepare(operation, data, model, sampling, stop)
        try:
            generation = self.provider.stream(rendered.request)
        except TransportError as e:
            failed = GenerationResult(generation_id="", model=route.model, status="error", error=e.body[:2000],
                                      http_status=e.status, attempts=e.attempts)
            return WriterOutput(route, rendered, preview, failed, clean_for(operation, ""), None, data, self._estimate(rendered))
        with WriterSession(route, rendered, preview, generation, data, self.guard, self._estimate(rendered)) as session:
            return session.finish()
