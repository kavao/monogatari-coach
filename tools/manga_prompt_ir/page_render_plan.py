"""Schema 1.0 manga page compiler contract.

The page compiler is deliberately opt-in.  It consumes the existing 1.0 page
mapping and produces a provider-facing plan without writing back to the IR.
Image attachments and name-board images are represented explicitly, but remain
unsupported in P1; callers must show that they are empty and unsent.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .prompt_formatters import (
    INLINE_DO_NOT_INCLUDE,
    MANGA_PAGE_INSTRUCTION,
    format_manga_page_prompt,
)


PAGE_COMPILER = "page_render_plan"
PAGE_COMPILER_VERSION = "1.0"
TEXT_MODES = ("generate", "letter_later", "none")
SUPPORTED_PROVIDERS = frozenset({"novelai", "openai", "grok", "grok_pro"})

_TEXT_LINE_LABELS = (
    "- セリフ:",
    "- モノローグ:",
    "- ナレーション:",
    "- 効果音:",
    "- dialogue:",
    "- monologue:",
    "- narration:",
    "- sfx:",
)
_NO_TEXT_RE = re.compile(
    r"(?:no\s+text|without\s+text|文字(?:を|は)?(?:描か|入れ|なし)|文字なし|文字を描画しない)",
    re.IGNORECASE,
)
_LETTER_LATER_RE = re.compile(
    r"(?:letter\s*later|lettering\s*later|後載せ|後で(?:文字|写植)|別(?:処理|工程)|空吹き出し|empty\s+(?:speech\s+)?balloon)",
    re.IGNORECASE,
)
_GENERATE_RE = re.compile(
    r"(?:legible|readable|render(?:ed|ing)?\s+(?:the\s+)?text|正確な文言|日本語(?:文字)?(?:を|は)?(?:描画|可読)|文字を入れ|台詞を描)",
    re.IGNORECASE,
)


class PageRenderPlanError(ValueError):
    """Raised when a page cannot be compiled without silently dropping data."""


@dataclass(frozen=True)
class PageRenderPlan:
    schema_version: str
    compiler_version: str
    page_hash: str
    source_mode: str
    provider: str
    prompt: str
    negative_prompt: str
    formatter: str
    negative_mode: str
    text_mode: str
    text_policy: str
    text_manifest: list[dict[str, Any]] = field(default_factory=list)
    ordered_image_inputs: list[dict[str, Any]] = field(default_factory=list)
    name_images: list[dict[str, Any]] = field(default_factory=list)
    unsupported: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def metadata(self) -> dict[str, Any]:
        """Small provider metadata; the full plan is written as a manifest."""
        return {
            "schema_version": self.schema_version,
            "compiler_version": self.compiler_version,
            "page_hash": self.page_hash,
            "source_mode": self.source_mode,
            "provider": self.provider,
            "formatter": self.formatter,
            "negative_mode": self.negative_mode,
            "text_mode": self.text_mode,
            "text_manifest_count": len(self.text_manifest),
            "ordered_image_inputs": [],
            "name_images": [],
            "unsupported": list(self.unsupported),
            "warnings": list(self.warnings),
        }

    def write_manifest(self, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


def canonical_page_hash(page: dict[str, Any]) -> str:
    payload = json.dumps(page, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _policy_class(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    has_none = bool(_NO_TEXT_RE.search(text))
    has_letter = bool(_LETTER_LATER_RE.search(text))
    has_generate = bool(_GENERATE_RE.search(text))
    if has_none and (has_letter or has_generate):
        return "conflict"
    if has_letter and has_generate:
        return "conflict"
    if has_none:
        return "none"
    if has_letter:
        return "letter_later"
    if has_generate:
        return "generate"
    return None


def explicit_text_policies(page: dict[str, Any]) -> list[tuple[str, str]]:
    policies: list[tuple[str, str]] = []
    manga = page.get("manga")
    if isinstance(manga, dict) and "text_policy" in manga and str(manga.get("text_policy") or "").strip():
        policies.append(("manga.text_policy", str(manga["text_policy"])))
    instruction = page.get("render_instruction")
    if isinstance(instruction, dict) and "text_policy" in instruction and str(instruction.get("text_policy") or "").strip():
        policies.append(("render_instruction.text_policy", str(instruction["text_policy"])))
    return policies


def resolve_text_mode(page: dict[str, Any], requested: str | None = None) -> tuple[str, str, list[str]]:
    """Resolve mode and policy while distinguishing omitted from explicit YAML keys."""
    if requested is not None and requested not in TEXT_MODES:
        raise PageRenderPlanError(
            f"text_mode は generate / letter_later / none のいずれかです: {requested!r}"
        )
    classified: list[tuple[str, str]] = []
    warnings: list[str] = []
    for key, value in explicit_text_policies(page):
        kind = _policy_class(value)
        if kind == "conflict":
            raise PageRenderPlanError(f"{key} の text_policy が複数の文字方針に衝突しています")
        if kind:
            classified.append((key, kind))

    kinds = {kind for _key, kind in classified}
    if len(kinds) > 1:
        detail = ", ".join(f"{key}={kind}" for key, kind in classified)
        raise PageRenderPlanError(f"text_policy が衝突しています: {detail}")

    mode = requested or (next(iter(kinds)) if kinds else "generate")
    if requested and kinds and next(iter(kinds)) != requested:
        detail = ", ".join(f"{key}={kind}" for key, kind in classified)
        raise PageRenderPlanError(f"text_mode={requested!r} と text_policy が衝突しています: {detail}")

    if not classified:
        warnings.append("text_policy is omitted; the selected text_mode policy replaces the model default")
    policies = {
        "generate": "Render the exact Japanese dialogue, narration, monologue, and sound effects as legible text.",
        "letter_later": "Leave clear empty balloons and text areas; do not render dialogue, narration, monologue, or sound effects.",
        "none": "Do not render text or lettering; preserve the composition and acting space for a text-free image.",
    }
    return mode, policies[mode], warnings


def build_text_manifest(page: dict[str, Any], page_hash: str) -> list[dict[str, Any]]:
    manifest: list[dict[str, Any]] = []
    for panel in page.get("panels") or []:
        if not isinstance(panel, dict):
            continue
        panel_id = panel.get("panel_id")
        text = panel.get("text") or {}
        if not isinstance(text, dict):
            continue
        for kind in ("dialogue", "monologue", "narration", "sfx"):
            for index, item in enumerate(text.get(kind) or [], start=1):
                if isinstance(item, dict):
                    content = item.get("content", item.get("text", ""))
                    speaker = item.get("speaker", item.get("character_id"))
                    bubble_type = item.get("bubble_type")
                    placement = item.get("placement")
                    meaning = item.get("meaning")
                else:
                    content = item
                    speaker = None
                    bubble_type = None
                    placement = None
                    meaning = None
                if content is None or not str(content).strip():
                    continue
                entry: dict[str, Any] = {
                    "text_id": f"{page_hash[:12]}-p{panel_id}-{kind}-{index}",
                    "panel_id": panel_id,
                    "type": kind,
                    "speaker": str(speaker) if speaker is not None else "",
                    "content": str(content),
                    "bubble_type": str(bubble_type) if bubble_type is not None else "",
                    "placement": str(placement) if placement is not None else "",
                    "writing_direction": "horizontal",
                }
                if meaning is not None:
                    entry["meaning"] = str(meaning)
                manifest.append(entry)
    return manifest


def _strip_text_lines(prompt: str, manifest: list[dict[str, Any]]) -> str:
    contents = [str(item.get("content") or "") for item in manifest if item.get("content")]
    lines: list[str] = []
    for line in prompt.splitlines():
        if any(line.strip().startswith(label) for label in _TEXT_LINE_LABELS):
            continue
        if any(content in line for content in contents):
            line = line
            for content in contents:
                if content:
                    line = line.replace(content, "")
        lines.append(line)
    return "\n".join(lines).strip()


def _provider_label(provider: str) -> str:
    return {
        "novelai": "NovelAI page compiler",
        "openai": "GPT Image page compiler",
        "grok": "Grok page compiler",
        "grok_pro": "Grok page compiler",
    }.get(provider, f"{provider} page compiler")


def compile_page_render_plan(
    page: dict[str, Any],
    *,
    source: str,
    provider: str,
    existing_prompt: str,
    negative_prompt: str,
    text_mode: str | None = None,
) -> PageRenderPlan:
    """Compile a schema 1.0 page without changing the source mapping."""
    if source not in {"step1-pages", "step2-pages"}:
        raise PageRenderPlanError(f"PageRenderPlan はページ生成専用です: source={source}")
    if provider not in SUPPORTED_PROVIDERS:
        raise PageRenderPlanError(
            f"provider={provider} はP1のページcompiler未対応です（Forge/OpenRouterはlegacy）"
        )
    declared_schema = page.get("schema_version", "1.0")
    if declared_schema != "1.0":
        raise PageRenderPlanError(f"P1のページcompilerはschema 1.0のみ対応します: {declared_schema!r}")

    page_hash = canonical_page_hash(page)
    mode, policy, policy_warnings = resolve_text_mode(page, text_mode)
    manifest = build_text_manifest(page, page_hash)
    prompt_source = existing_prompt.strip()
    if mode in {"letter_later", "none"}:
        prompt_source = _strip_text_lines(prompt_source, manifest)
    prompt_source = (
        f"{_provider_label(provider)}.\n\n{prompt_source}\n\n"
        f"Effective text mode: {mode}.\n{policy}"
    )

    page_for_format = copy.deepcopy(page)
    instruction = page_for_format.setdefault("render_instruction", {})
    if isinstance(instruction, dict):
        instruction["text_policy"] = policy
    bundle = format_manga_page_prompt(
        page_for_format,
        source=source,
        existing_prompt=prompt_source,
        negative_prompt=negative_prompt,
        formatter=MANGA_PAGE_INSTRUCTION,
    )
    unsupported = [
        "ordered image inputs are unsupported in P1; not sent",
        "name image is unsupported in P1; not sent",
    ]
    warnings = list(policy_warnings)
    if mode in {"letter_later", "none"} and any(
        str(item.get("content") or "") in bundle.prompt for item in manifest
    ):
        warnings.append("text content remains in the compiled prompt; manual cleanup is required")

    return PageRenderPlan(
        schema_version="1.0",
        compiler_version=PAGE_COMPILER_VERSION,
        page_hash=page_hash,
        source_mode=source,
        provider=provider,
        prompt=bundle.prompt,
        negative_prompt=bundle.negative_prompt,
        formatter=bundle.formatter,
        negative_mode=bundle.negative_mode,
        text_mode=mode,
        text_policy=policy,
        text_manifest=manifest,
        ordered_image_inputs=[],
        name_images=[],
        unsupported=unsupported,
        warnings=warnings,
    )

