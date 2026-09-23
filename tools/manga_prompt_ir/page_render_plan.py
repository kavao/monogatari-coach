"""Schema 1.0/1.1 manga page compiler contract.

The page compiler is deliberately opt-in.  It consumes schema 1.0/1.1 page
mappings and produces a provider-facing plan without writing back to the IR.
Image attachments and name-board images are represented explicitly. They are
resolved and sent only by provider bridges that advertise the common
reference contract; legacy paths remain unchanged.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image

try:
    from image_edit.contracts import (
        REFERENCE_CONTRACT_VERSION,
        validate_ordered_image_inputs,
    )
except ModuleNotFoundError:  # pragma: no cover - package import fallback
    from tools.image_edit.contracts import (  # type: ignore[no-redef]
        REFERENCE_CONTRACT_VERSION,
        validate_ordered_image_inputs,
    )

from .prompt_formatters import (
    INLINE_DO_NOT_INCLUDE,
    MANGA_PAGE_INSTRUCTION,
    NATIVE_NEGATIVE,
    PromptBundle,
    character_snapshot_map,
    format_manga_page_prompt,
    image_panel_label,
)
from .schemas.manga_page import MangaPagePrompt
from .character_visual_page import (
    CharacterVisualPageError,
    rebuild_resolved_snapshots,
    validate_page_character_visual,
)
from .character_visual_resolver import (
    VisualResolverError,
    is_character_schema_1_1,
    resolve_character_visual,
)
from .renderer_capabilities import (
    BUBBLE_FRAME_MODES,
    RendererCapabilityError,
    lookup_renderer_capability,
    resolve_renderer_capability_key,
)
from .text_ids import assigned_text_id


PAGE_COMPILER = "page_render_plan"
PAGE_COMPILER_VERSION = "1.0"
TEXT_MODES = ("generate", "letter_later", "none")
SUPPORTED_PROVIDERS = frozenset(
    {"novelai", "openai", "openrouter", "grok", "grok_pro"}
)
PAGE_PANEL_OUTLINE_LIMIT = 12
CHARACTER_FIXED_TAG_LIMIT = 64
NOVELAI_CHARACTER_SLOT_LIMIT = 22
NOVELAI_GENERATE_BUBBLE_TAGS = "text, speech bubble"
NOVELAI_TEXT_LIMITS = {
    "curated": 374,
    "full": 750,
}

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
    bubble_frame_mode: str = "provider"
    capability_key: str = ""
    declared_text_policies: list[dict[str, str | None]] = field(default_factory=list)
    text_manifest: list[dict[str, Any]] = field(default_factory=list)
    character_slots: list[dict[str, Any]] = field(default_factory=list)
    page_context: list[str] = field(default_factory=list)
    ordered_image_inputs: list[dict[str, Any]] = field(default_factory=list)
    name_images: list[dict[str, Any]] = field(default_factory=list)
    reference_contract_version: str = REFERENCE_CONTRACT_VERSION
    unsupported: list[str] = field(default_factory=list)
    effective_settings: dict[str, Any] = field(default_factory=dict)
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
            "text_policy": self.text_policy,
            "bubble_frame_mode": self.bubble_frame_mode,
            "capability_key": self.capability_key,
            "declared_text_policies": list(self.declared_text_policies),
            "text_manifest_count": len(self.text_manifest),
            "character_slot_count": len(self.character_slots),
            "character_slots": copy.deepcopy(self.character_slots),
            "page_context": list(self.page_context),
            "ordered_image_inputs": copy.deepcopy(self.ordered_image_inputs),
            "name_images": copy.deepcopy(self.name_images),
            "reference_contract_version": self.reference_contract_version,
            "unsupported": list(self.unsupported),
            "effective_settings": dict(self.effective_settings),
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


def page_yaml_text_mode(page: dict[str, Any]) -> str | None:
    """Return an explicit YAML text_mode, or None when the page omitted the key."""
    found: list[tuple[str, str]] = []
    manga = page.get("manga")
    instruction = page.get("render_instruction")
    for obj, key in ((manga, "manga.text_mode"), (instruction, "render_instruction.text_mode")):
        if not isinstance(obj, dict) or "text_mode" not in obj:
            continue
        value = str(obj.get("text_mode") or "").strip()
        if not value:
            continue
        if value not in TEXT_MODES:
            raise PageRenderPlanError(
                f"{key} は generate / letter_later / none のいずれかです: {value!r}"
            )
        found.append((key, value))
    modes = {mode for _key, mode in found}
    if len(modes) > 1:
        detail = ", ".join(f"{key}={mode}" for key, mode in found)
        raise PageRenderPlanError(f"text_mode が衝突しています: {detail}")
    return next(iter(modes)) if modes else None


def resolve_text_mode(page: dict[str, Any], requested: str | None = None) -> tuple[str, str, list[str]]:
    """Resolve mode and policy while distinguishing omitted from explicit YAML keys.

    CLI ``requested`` wins over YAML ``text_mode``. YAML ``text_mode`` wins over
    classified ``text_policy``. Omitted keys fall back to generate.
    """
    if requested is not None and requested not in TEXT_MODES:
        raise PageRenderPlanError(
            f"text_mode は generate / letter_later / none のいずれかです: {requested!r}"
        )
    yaml_mode = page_yaml_text_mode(page)
    declared = explicit_text_policies(page)
    classified: list[tuple[str, str]] = []
    warnings: list[str] = []
    for key, value in declared:
        kind = _policy_class(value)
        if kind == "conflict":
            raise PageRenderPlanError(f"{key} の text_policy が複数の文字方針に衝突しています")
        if kind:
            classified.append((key, kind))

    kinds = {kind for _key, kind in classified}
    if len(kinds) > 1:
        detail = ", ".join(f"{key}={kind}" for key, kind in classified)
        raise PageRenderPlanError(f"text_policy が衝突しています: {detail}")
    policy_mode = next(iter(kinds)) if kinds else None
    if yaml_mode and policy_mode and yaml_mode != policy_mode:
        detail = ", ".join(f"{key}={kind}" for key, kind in classified)
        raise PageRenderPlanError(
            f"text_mode={yaml_mode!r} と text_policy が衝突しています: {detail}"
        )

    mode = requested or yaml_mode or policy_mode or "generate"
    if requested and policy_mode and policy_mode != requested:
        detail = ", ".join(f"{key}={kind}" for key, kind in classified)
        raise PageRenderPlanError(f"text_mode={requested!r} と text_policy が衝突しています: {detail}")

    if not declared:
        warnings.append("text_policy is omitted; the selected text_mode policy replaces the model default")
    elif not classified:
        warnings.append(
            "text_policy is explicit but not classifiable; the selected text_mode policy is used"
        )
    policies = {
        "generate": (
            "Render the exact Japanese dialogue, narration, monologue, and sound effects as legible text. "
            "Only those specified lines may appear as lettering. "
            "Do not render panel numbers, panel IDs, sequence numbers, or labels."
        ),
        "letter_later": "Leave clear empty balloons and text areas; do not render dialogue, narration, monologue, or sound effects.",
        "none": "Do not render text or lettering; preserve the composition and acting space for a text-free image.",
    }
    return mode, policies[mode], warnings


def _lettering_style(page: dict[str, Any]) -> dict[str, Any]:
    manga = page.get("manga") if isinstance(page.get("manga"), dict) else {}
    style = manga.get("lettering") if isinstance(manga, dict) else {}
    if not isinstance(style, dict):
        style = {}
    direction = str(style.get("direction") or "vertical").strip().lower()
    if direction not in {"vertical", "horizontal"}:
        direction = "vertical"
    try:
        base_font_size = int(style.get("base_font_size", 30))
    except (TypeError, ValueError):
        base_font_size = 30
    return {
        "direction": direction,
        "base_font_size": base_font_size,
        "size_policy": str(style.get("size_policy") or "uniform_then_shrink"),
    }


def _text_writing_direction(item: Any, default: str) -> str:
    if isinstance(item, dict):
        value = str(item.get("writing_direction") or "").strip().lower()
        if value in {"vertical", "horizontal"}:
            return value
        placement = item.get("placement")
        if isinstance(placement, dict):
            value = str(placement.get("writing_direction") or "").strip().lower()
            if value in {"vertical", "horizontal"}:
                return value
    return default


def build_text_manifest(page: dict[str, Any], page_hash: str) -> list[dict[str, Any]]:
    manifest: list[dict[str, Any]] = []
    default_direction = _lettering_style(page)["direction"]
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
                    "text_id": assigned_text_id(
                        item, panel_id=panel_id, kind=kind, index=index
                    ),
                    "panel_id": panel_id,
                    "type": kind,
                    "speaker": str(speaker) if speaker is not None else "",
                    "content": str(content),
                    "bubble_type": str(bubble_type) if bubble_type is not None else "",
                    "placement": str(placement) if placement is not None else "",
                    "writing_direction": _text_writing_direction(item, default_direction),
                }
                if meaning is not None:
                    entry["meaning"] = str(meaning)
                manifest.append(entry)
    return manifest


def _strip_text_lines(prompt: str, manifest: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for line in prompt.splitlines():
        if _is_structured_text_line(line):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def _strip_text_content(prompt: str, manifest: list[dict[str, Any]]) -> str:
    """Remove structured text lines from a non-generating page prompt.

    Do not substring-replace content in summaries or free-form instructions:
    a short sfx can occur inside an unrelated word and a dialogue quote can be
    part of a meaningful summary.  Such unstructured remnants are left for the
    warning below so a human can decide whether to rewrite the source text.
    """
    del manifest  # The line labels define the safe-to-remove structured region.
    return "\n".join(
        line for line in prompt.splitlines() if not _is_structured_text_line(line)
    ).strip()


def _strip_page_japanese_gloss_lines(prompt: str) -> str:
    """Remove legacy human-readable Japanese gloss lines from provider prompts."""
    had_trailing_newline = prompt.endswith("\n")
    cleaned = "\n".join(
        line
        for line in prompt.splitlines()
        if not line.strip().startswith("- 日本語訳:")
    ).strip()
    return cleaned + ("\n" if had_trailing_newline else "")


def _remove_visible_reading_order_hints(prompt: str) -> str:
    """Keep panel-order data out of Grok's visible drawing instructions."""
    kept: list[str] = []
    for line in prompt.splitlines():
        stripped = line.strip()
        if not stripped:
            kept.append(line)
            continue
        if any(
            phrase in stripped.lower()
            for phrase in ("右から左", "左から右", "読み順", "reading order")
        ):
            line = re.sub(
                r"[、,]?\s*読み順(?:は|:)\s*"
                r"(?:right_to_left|left_to_right|右から左|左から右)[。.]?",
                "",
                line,
                flags=re.IGNORECASE,
            ).strip()
            if not line or any(
                phrase in line.lower()
                for phrase in ("右から左", "左から右", "読み順", "reading order")
            ):
                continue
        kept.append(line)
    return "\n".join(kept).strip()


def _is_structured_text_line(line: str) -> bool:
    return any(line.strip().startswith(label) for label in _TEXT_LINE_LABELS)


def _novelai_dialogue_text_block(manifest: list[dict[str, Any]]) -> str:
    """NovelAI の Text: には台詞本文だけを置く。"""
    lines = ["Text:"]
    for item in manifest:
        if item.get("type") != "dialogue":
            continue
        content = str(item.get("content") or "").strip()
        if content:
            lines.append(content)
    if len(lines) == 1:
        return "Text:\n"
    return "\n".join(lines)


def _text_block(manifest: list[dict[str, Any]]) -> str:
    """Render the exact text manifest as the final page-prompt section."""
    if not manifest:
        # Keep the compiler-owned marker even when there is no dialogue.  The
        # NovelAI adapter uses this marker to keep quality suffixes before the
        # text section rather than rejecting an otherwise valid empty manifest.
        return "Text:\n"
    lines = ["Text:"]
    for item in manifest:
        attributes: list[str] = []
        if item.get("speaker"):
            attributes.append(f"speaker={item['speaker']}")
        if item.get("bubble_type"):
            attributes.append(f"bubble_type={item['bubble_type']}")
        if item.get("placement"):
            attributes.append(f"placement={item['placement']}")
        if item.get("meaning"):
            attributes.append(f"meaning={item['meaning']}")
        context = f" ({', '.join(attributes)})" if attributes else ""
        lines.append(
            f"- panel {item.get('panel_id')} {item.get('type')}{context}: "
            f"{item.get('content', '')}"
        )
    return "\n".join(lines)


def _text_speaker_display_name(page: dict[str, Any], speaker: Any) -> str:
    """Resolve a speaker to a provider-safe display name, never an internal ID."""
    speaker_id = str(speaker or "").strip()
    if not speaker_id:
        return ""
    for snapshot in page.get("character_snapshots") or []:
        if not isinstance(snapshot, dict):
            continue
        if str(snapshot.get("character_id") or "").strip() != speaker_id:
            continue
        for key in ("name_en", "name"):
            display_name = str(snapshot.get(key) or "").strip()
            if display_name:
                return display_name
    return ""


def _letter_later_text_layout_block(
    page: dict[str, Any], manifest: list[dict[str, Any]]
) -> str:
    """Describe empty text-region cardinality without sending text content."""
    if not manifest:
        return ""

    panels = [panel for panel in page.get("panels") or [] if isinstance(panel, dict)]
    by_panel: dict[Any, list[dict[str, Any]]] = {}
    for item in manifest:
        by_panel.setdefault(item.get("panel_id"), []).append(item)

    lettering = _lettering_style(page)
    lines = [
        "Text Layout (structural; no lettering):",
        "- baseline lettering direction: "
        f"{lettering['direction']} Japanese writing; keep each bubble clear for post-processing.",
    ]
    emitted = False
    for ordinal, panel in enumerate(panels, start=1):
        panel_id = panel.get("panel_id")
        items = by_panel.get(panel_id, [])
        if not items:
            continue
        emitted = True
        label = image_panel_label(panel, ordinal)
        all_dialogue = all(item.get("type") == "dialogue" for item in items)
        region_name = "empty speech bubble" if all_dialogue else "empty text region"
        count = len(items)
        region_name = region_name if count == 1 else f"{region_name}s"
        speaker_names = [
            _text_speaker_display_name(page, item.get("speaker"))
            for item in items
        ]
        speaker_names = [name for name in speaker_names if name]
        speaker_suffix = (
            f"; assigned speaker(s): {', '.join(speaker_names)}"
            if speaker_names
            else ""
        )
        directions = sorted(
            {
                str(item.get("writing_direction") or lettering["direction"])
                for item in items
            }
        )
        direction_suffix = f"; lettering direction: {', '.join(directions)}"
        lines.append(
            f"- {label}: exactly {count} {region_name}{speaker_suffix}"
            f"{direction_suffix}."
        )
    if not emitted:
        return ""
    lines.append(
        "- Do not add any additional speech bubbles, thought bubbles, "
        "narration boxes, captions, or sound-effect lettering."
    )
    return "\n".join(lines)


_DRAMATURGY_ROLE_LABELS = {
    "setup": "Setup",
    "establishing": "Establishing",
    "introduction": "Introduction",
    "development": "Development",
    "turn": "Turn",
    "turning_point": "Turning point",
    "reversal": "Reversal",
    "reveal": "Reveal",
    "reaction": "Reaction",
    "climax": "Climax",
    "resolution": "Resolution",
    "transition": "Transition",
    "callback": "Callback",
    "breath": "Breath",
}


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _unique_strings(values: list[Any]) -> list[str]:
    return list(
        dict.fromkeys(
            str(value).strip()
            for value in values
            if value is not None and str(value).strip()
        )
    )


def _english_value(data: Any, key: str) -> str | None:
    if not isinstance(data, dict):
        return None
    value = data.get(f"{key}_en")
    return str(value).strip() if value is not None and str(value).strip() else None


def _role_label(value: Any) -> str | None:
    if value is None or not str(value).strip():
        return None
    raw = str(value).strip()
    return _DRAMATURGY_ROLE_LABELS.get(raw.lower(), raw)


def _subject_slot_id(
    page_hash: str,
    panel_id: Any,
    subject: dict[str, Any],
    subject_index: int,
) -> str:
    subject_id = subject.get("subject_id")
    if subject_id:
        return str(subject_id)
    return f"ir{page_hash[:12]}-p{panel_id}-s{subject_index:02d}"


def _layout_center_map(page: dict[str, Any]) -> dict[Any, dict[str, float]]:
    geometry = page.get("layout_geometry")
    if not isinstance(geometry, dict):
        return {}
    centers: dict[Any, dict[str, float]] = {}
    for item in _as_list(geometry.get("panels")):
        if not isinstance(item, dict):
            continue
        rect = item.get("rect")
        if not isinstance(rect, dict):
            continue
        try:
            centers[item.get("panel_id")] = {
                "x": float(rect["x"]) + float(rect["w"]) / 2,
                "y": float(rect["y"]) + float(rect["h"]) / 2,
            }
        except (KeyError, TypeError, ValueError):
            continue
    return centers


def _clamp_unit(value: float) -> float:
    return min(1.0, max(0.0, value))


def _panel_rect(page: dict[str, Any], panel_id: Any) -> dict[str, float] | None:
    geometry = page.get("layout_geometry")
    if not isinstance(geometry, dict):
        return None
    for item in _as_list(geometry.get("panels")):
        if not isinstance(item, dict) or item.get("panel_id") != panel_id:
            continue
        rect = item.get("rect")
        if not isinstance(rect, dict):
            return None
        try:
            return {
                "x": float(rect["x"]),
                "y": float(rect["y"]),
                "w": float(rect["w"]),
                "h": float(rect["h"]),
            }
        except (KeyError, TypeError, ValueError):
            return None
    return None


def _spread_centers(rect: dict[str, float] | None, count: int) -> list[dict[str, float]]:
    """Place co-present characters at different points inside one panel."""
    if count < 1:
        return []
    if rect is None:
        if count == 1:
            return [{"x": 0.5, "y": 0.5}]
        return [
            {"x": _clamp_unit((index + 1) / (count + 1)), "y": 0.5}
            for index in range(count)
        ]
    cy = _clamp_unit(rect["y"] + rect["h"] / 2)
    if count == 1:
        return [{"x": _clamp_unit(rect["x"] + rect["w"] / 2), "y": cy}]
    return [
        {
            "x": _clamp_unit(rect["x"] + rect["w"] * (index + 1) / (count + 1)),
            "y": cy,
        }
        for index in range(count)
    ]


def _slot_variant_id(subject: dict[str, Any], snapshot: dict[str, Any]) -> str | None:
    declared = [
        str(value)
        for value in (
            subject.get("prompt_variant_id"),
            subject.get("costume_variant"),
            subject.get("variant_id"),
        )
        if value
    ]
    unique = list(dict.fromkeys(declared))
    if len(unique) > 1:
        raise PageRenderPlanError(
            "prompt_variant_id / costume_variant / variant_id が食い違っています: "
            + ", ".join(unique)
        )
    if unique:
        return unique[0]
    selected = snapshot.get("selected_variant_id")
    return str(selected) if selected else None


def _slot_appearance_tags(
    snapshot: dict[str, Any],
    character: dict[str, Any] | None,
    variant_ids: list[str],
) -> list[str]:
    snapshot_tags = _unique_strings(
        [
            *_as_list(snapshot.get("fixed_tags")),
            *_as_list(snapshot.get("variant_tags")),
        ]
    )
    if snapshot_tags:
        return snapshot_tags
    if not character:
        return []
    if is_character_schema_1_1(character):
        unique_variants = list(dict.fromkeys(str(item) for item in variant_ids if item))
        if len(unique_variants) != 1:
            raise PageRenderPlanError(
                "1.1 キャラクターは variant_id の完全一致が必要です"
            )
        try:
            return resolve_character_visual(character, unique_variants[0]).danbooru_tags
        except VisualResolverError as exc:
            raise PageRenderPlanError(str(exc)) from exc
    from manga_prompt_ir.character_fixed_tags import (
        base_fixed_tags_from,
        resolve_variant_danbooru_tags,
    )

    unique_variants = list(dict.fromkeys(variant_ids))
    if len(unique_variants) == 1:
        return resolve_variant_danbooru_tags(character, unique_variants[0])
    return base_fixed_tags_from(character)


def _speaker_keys(
    character_id: str,
    snapshot: dict[str, Any],
    character: dict[str, Any] | None,
) -> set[str]:
    values = [character_id]
    for source in (snapshot, character or {}):
        for key in ("name", "name_en", "name_ja", "display_name"):
            raw = source.get(key) if isinstance(source, dict) else None
            if raw is not None and str(raw).strip():
                values.append(str(raw).strip())
    return {value for value in values if value}


def _panel_text_items(panel: dict[str, Any], kind: str) -> list[tuple[str | None, str, str]]:
    text = panel.get("text") or {}
    if not isinstance(text, dict):
        return []
    items: list[tuple[str | None, str, str]] = []
    for item in _as_list(text.get(kind)):
        if isinstance(item, dict):
            content = str(item.get("content") or item.get("text") or "").strip()
            speaker = item.get("speaker", item.get("character_id"))
            bubble_type = str(item.get("bubble_type") or "")
        else:
            content = str(item).strip()
            speaker = None
            bubble_type = ""
        if not content:
            continue
        speaker_text = str(speaker).strip() if speaker is not None and str(speaker).strip() else None
        items.append((speaker_text, content, bubble_type))
    return items


def _with_novelai_generate_bubble_tags(prompt: str) -> str:
    """Attach T1-style page tags. NovelAI generate only; not for Grok/GPT."""
    body = prompt.rstrip()
    lowered = body.lower()
    if "speech bubble" in lowered:
        return body
    return f"{body}\n{NOVELAI_GENERATE_BUBBLE_TAGS}"


def _bubble_phrase(
    kind: str,
    content: str,
    bubble_type: str,
    *,
    text_mode: str,
) -> str | None:
    if text_mode == "none":
        return None
    if kind == "sfx":
        if text_mode != "generate":
            return None
        return f"擬音「{content}」"
    thought = kind == "monologue" or "thought" in bubble_type.lower() or "雲" in bubble_type
    label = "thought cloud" if thought else "白い吹き出し"
    if text_mode != "generate":
        return label
    return f"{label}「{content}」"


def _line_belongs_to_speaker(
    speaker: str | None,
    keys: set[str],
    *,
    sole_character: bool,
) -> bool:
    if speaker is None:
        return sole_character
    return speaker in keys


def _strip_lines_containing(prompt: str, contents: set[str]) -> str:
    """Drop structured text lines whose wording was moved into a character slot."""
    kept: list[str] = []
    for line in prompt.splitlines():
        if _is_structured_text_line(line) and any(content and content in line for content in contents):
            continue
        kept.append(line)
    return "\n".join(kept).strip()


def build_novelai_character_slots(
    page: dict[str, Any],
    page_hash: str | None = None,
    *,
    enforce_limit: bool = True,
    characters: dict[str, dict[str, Any]] | None = None,
    text_mode: str = "generate",
    attach_novelai_bubbles: bool = False,
) -> list[dict[str, Any]]:
    """Build one V5 character slot per person in a panel.

    The same person in three panels becomes three slots. Each slot carries
    that panel's appearance, pose, one center, and the speaker's balloon.
    """
    if str(page.get("schema_version", "1.0")) != "1.1":
        return []
    page_hash = page_hash or canonical_page_hash(page)
    snapshots = character_snapshot_map(page)
    characters = characters or {}
    slots: list[dict[str, Any]] = []
    for ordinal, panel in enumerate(_as_list(page.get("panels")), start=1):
        if not isinstance(panel, dict):
            continue
        panel_id = panel.get("panel_id")
        panel_negative = _unique_strings(_as_list(panel.get("negative_tags")))
        omitted_negative = set(_unique_strings(_as_list(panel.get("omit_negative_tags"))))
        panel_uc = ", ".join(value for value in panel_negative if value not in omitted_negative)
        indexed_subjects = [
            (index, subject)
            for index, subject in enumerate(_as_list(panel.get("subjects")), start=1)
            if isinstance(subject, dict)
        ]
        char_subjects = [
            (index, subject)
            for index, subject in indexed_subjects
            if subject.get("character_id")
        ]
        if not char_subjects:
            continue
        sole_character = len(char_subjects) == 1
        points = _spread_centers(_panel_rect(page, panel_id), len(char_subjects))
        sfx_items = _panel_text_items(panel, "sfx")
        for slot_offset, ((subject_index, subject), point) in enumerate(
            zip(char_subjects, points, strict=True)
        ):
            character_id = str(subject["character_id"])
            snapshot = snapshots.get(character_id, {})
            character = characters.get(character_id)
            variant_id = _slot_variant_id(subject, snapshot)
            tags = _slot_appearance_tags(
                snapshot,
                character if isinstance(character, dict) else None,
                [variant_id] if variant_id else [],
            )
            keys = _speaker_keys(
                character_id,
                snapshot,
                character if isinstance(character, dict) else None,
            )
            phrases: list[str] = []
            rendered: list[str] = []
            for kind in ("dialogue", "monologue"):
                for speaker, content, bubble_type in _panel_text_items(panel, kind):
                    if not _line_belongs_to_speaker(speaker, keys, sole_character=sole_character):
                        continue
                    if attach_novelai_bubbles:
                        phrase = _bubble_phrase(kind, content, bubble_type, text_mode=text_mode)
                        if phrase:
                            phrases.append(phrase)
                    if text_mode == "generate":
                        rendered.append(content)
            if slot_offset == 0:
                for _speaker, content, bubble_type in sfx_items:
                    if attach_novelai_bubbles:
                        phrase = _bubble_phrase("sfx", content, bubble_type, text_mode=text_mode)
                        if phrase:
                            phrases.append(phrase)
                    if text_mode == "generate":
                        rendered.append(content)
            pose = _english_value(subject, "pose_action") or str(subject.get("pose_action") or "").strip()
            expression = _english_value(subject, "expression") or str(subject.get("expression") or "").strip()
            pieces = [f"{ordinal}コマ目"]
            if tags:
                pieces.append(", ".join(tags))
            if pose:
                pieces.append(pose)
            if expression:
                pieces.append(expression)
            pieces.extend(phrases)
            slots.append(
                {
                    "slot_id": _subject_slot_id(page_hash, panel_id, subject, subject_index),
                    "character_id": character_id,
                    "panel_id": panel_id,
                    "subject_index": subject_index,
                    "variant_id": variant_id,
                    "prompt": ", ".join(pieces),
                    "uc": panel_uc,
                    "center": point,
                    "centers": [point],
                    "center_source": "layout_geometry",
                    "rendered_contents": rendered,
                }
            )
    if enforce_limit and len(slots) > NOVELAI_CHARACTER_SLOT_LIMIT:
        raise PageRenderPlanError(
            "schema 1.1のNovelAI character_prompts件数が上限を超えています: "
            f"{len(slots)} > {NOVELAI_CHARACTER_SLOT_LIMIT}（slotを省略しません）"
        )
    return slots


_IMAGE_ID_NAMES = (
    r"panel_id|slot_id|subject_id|asset_id|character_id|variant_id|text_id"
)
# Japanese letters are Unicode word characters, so \b does not split のpanel_idを.
_IMAGE_ID_ASSIGNMENT_RE = re.compile(
    rf"(?<![A-Za-z0-9_])(?:{_IMAGE_ID_NAMES}|entity_id)(?![A-Za-z0-9_])\s*="
)
_IMAGE_ID_WORD_RE = re.compile(
    rf"(?<![A-Za-z0-9_])(?:{_IMAGE_ID_NAMES})(?![A-Za-z0-9_])"
)
_IMAGE_VARIANT_SUFFIX_RE = re.compile(r" / \d{3}_[A-Za-z0-9_]+")
_IMAGE_BOUNDARY_NEGATIVE = (
    "panel numbers, panel IDs, sequence numbers, labels, "
    "captions other than specified dialogue"
)


def _without_negative_token(negative: str, token: str) -> str:
    parts = [part.strip() for part in re.split(r"[,、]", negative) if part.strip()]
    return ", ".join(part for part in parts if part.lower() != token.lower())


def _visible_subject_name(page: dict[str, Any], subject: dict[str, Any]) -> str:
    character_id = str(subject.get("character_id") or "")
    snapshot = character_snapshot_map(page).get(character_id, {})
    for source in (snapshot, subject):
        for key in ("name_en", "name", "display_name"):
            value = source.get(key)
            if value:
                return str(value)
    description = subject.get("description_en") or subject.get("description")
    if description:
        return str(description)
    return "figure"


def _enrich_image_character_snapshots(
    page: dict[str, Any],
    characters: dict[str, dict[str, Any]] | None,
) -> None:
    """Copy resolved appearance tags onto the image-prompt copy. YAML stays unchanged."""
    if not characters:
        return
    snapshots = page.get("character_snapshots")
    if not isinstance(snapshots, list):
        return
    by_id = {
        str(item.get("character_id")): item
        for item in snapshots
        if isinstance(item, dict) and item.get("character_id")
    }
    variants_by_id: dict[str, list[str]] = {}
    for panel in _as_list(page.get("panels")):
        if not isinstance(panel, dict):
            continue
        for subject in _as_list(panel.get("subjects")):
            if not isinstance(subject, dict) or not subject.get("character_id"):
                continue
            character_id = str(subject["character_id"])
            variant_id = _slot_variant_id(subject, by_id.get(character_id, {}))
            if variant_id:
                variants_by_id.setdefault(character_id, []).append(variant_id)
    for character_id, character in characters.items():
        snapshot = by_id.get(str(character_id))
        if not isinstance(snapshot, dict):
            continue
        if is_character_schema_1_1(character):
            continue
        if _unique_strings(
            [*_as_list(snapshot.get("fixed_tags")), *_as_list(snapshot.get("variant_tags"))]
        ):
            continue
        tags = _slot_appearance_tags(
            snapshot,
            character,
            variants_by_id.get(str(character_id), []),
        )
        if tags:
            snapshot["fixed_tags"] = tags


def scrub_image_prompt_identifiers(prompt: str, page: dict[str, Any]) -> str:
    """Remove non-visual identifiers from the string sent to an image model."""
    panels = [panel for panel in _as_list(page.get("panels")) if isinstance(panel, dict)]
    replacements = []
    for ordinal, panel in enumerate(panels, start=1):
        panel_id = panel.get("panel_id")
        if panel_id is None or str(panel_id).strip() == "":
            continue
        replacements.append((str(panel_id), image_panel_label(panel, ordinal)))
    replacements.sort(key=lambda item: len(item[0]), reverse=True)
    for panel_id, label in replacements:
        prompt = prompt.replace(f"コマ{panel_id}:", f"{label}:")
        prompt = prompt.replace(f"コマ{panel_id}：", f"{label}：")
        prompt = prompt.replace(f"Panel {panel_id}:", f"{label}:")
        prompt = prompt.replace(f"panel {panel_id}:", f"{label}:")
        prompt = prompt.replace(f"panel_id={panel_id}", label)
    kept: list[str] = []
    for line in prompt.splitlines():
        if _IMAGE_ID_ASSIGNMENT_RE.search(line):
            continue
        if _IMAGE_ID_WORD_RE.search(line):
            stripped = line.lstrip()
            indent = line[: len(line) - len(stripped)]
            bullet = "- " if stripped.startswith("- ") else ""
            if "character_id" in line or "variant_id" in line:
                kept.append(f"{indent}{bullet}人物の見た目と衣装を保つ。識別子は描かない。")
            else:
                kept.append(f"{indent}{bullet}指定されたコマの内容と読み順を保つ。識別子は描かない。")
            continue
        kept.append(line)
    deduped: list[str] = []
    for line in kept:
        if deduped and deduped[-1] == line and "識別子は描かない" in line:
            continue
        deduped.append(line)
    trailing_newline = "\n" if prompt.endswith("\n") else ""
    return _IMAGE_VARIANT_SUFFIX_RE.sub("", "\n".join(deduped)) + trailing_newline


def schema_1_1_prompt_context(
    page: dict[str, Any],
    *,
    page_hash: str | None = None,
    character_slots: list[dict[str, Any]] | None = None,
    image_inputs: list[dict[str, Any]] | None = None,
    for_image: bool = False,
) -> list[str]:
    """Return prompt-facing schema 1.1 context without Japanese fallback.

    Japanese editorial fields remain available in the IR and export, but the
    compiler-facing English clauses use only their explicit ``*_en`` values.
    """
    if str(page.get("schema_version", "1.0")) != "1.1":
        return []
    page_hash = page_hash or canonical_page_hash(page)
    lines: list[str] = ["Structured schema 1.1 context:"]
    lettering = _lettering_style(page)
    lines.extend(
        [
            "Lettering Style:",
            f"- baseline_direction={lettering['direction']}; "
            f"base_font_size={lettering['base_font_size']}; "
            f"size_policy={lettering['size_policy']} (post-processing)",
        ]
    )
    dramaturgy = page.get("dramaturgy")
    if isinstance(dramaturgy, dict):
        page_lines: list[str] = []
        for label, key in (
            ("purpose", "purpose"),
            ("emotional arc", "emotional_arc"),
            ("relation to previous", "relation_to_previous"),
        ):
            value = _english_value(dramaturgy, key)
            if value:
                page_lines.append(f"- {label}: {value}")
        role = _role_label(dramaturgy.get("role"))
        if role:
            page_lines.append(f"- role: {role}")
        if page_lines:
            lines.append("Page Purpose and Dramaturgy:")
            lines.extend(page_lines)

    slots_by_key = {
        (slot.get("panel_id"), slot.get("subject_index")): slot
        for slot in (character_slots or [])
    }
    slot_lines: list[str] = []
    panel_lines: list[str] = []
    label_by_panel_id: dict[Any, str] = {}
    ordinal = 0
    for panel in _as_list(page.get("panels")):
        if not isinstance(panel, dict):
            continue
        ordinal += 1
        panel_id = panel.get("panel_id")
        position = image_panel_label(panel, ordinal)
        label_by_panel_id[panel_id] = position
        panel_dramaturgy = panel.get("dramaturgy")
        panel_values: list[str] = []
        if isinstance(panel_dramaturgy, dict):
            role = _role_label(panel_dramaturgy.get("role"))
            if role:
                panel_values.append(f"role={role}")
            for label, key in (
                ("purpose", "purpose"),
                ("relation_to_previous", "relation_to_previous"),
            ):
                value = _english_value(panel_dramaturgy, key)
                if value:
                    panel_values.append(f"{label}={value}")
        if panel.get("background_density"):
            panel_values.append(f"background_density={panel['background_density']}")
        if panel_values:
            heading = position if for_image else f"panel {panel_id}"
            panel_lines.append(f"- {heading}: " + "; ".join(panel_values))
        for subject_index, subject in enumerate(_as_list(panel.get("subjects")), start=1):
            if not isinstance(subject, dict):
                continue
            if for_image:
                values = [position, _visible_subject_name(page, subject)]
                for label, key in (
                    ("action", "pose_action_en"),
                    ("expression", "expression_en"),
                    ("position", "position"),
                ):
                    value = subject.get(key)
                    if value:
                        values.append(f"{label}={value}")
                slot_lines.append("- " + "; ".join(values))
                continue
            subject_key = (panel_id, subject_index)
            native = slots_by_key.get(subject_key)
            slot_id = (
                native.get("slot_id")
                if native
                else _subject_slot_id(page_hash, panel_id, subject, subject_index)
            )
            values = [
                f"slot_id={slot_id}",
                f"panel_id={panel_id}",
            ]
            for label, key in (
                ("subject_id", "subject_id"),
                ("character_id", "character_id"),
                ("variant_id", "variant_id"),
                ("action", "pose_action_en"),
                ("expression", "expression_en"),
                ("position", "position"),
            ):
                value = subject.get(key)
                if value:
                    values.append(f"{label}={value}")
            slot_lines.append("- " + "; ".join(values))
    if panel_lines:
        lines.append("Panel Dramaturgy and Background Density:")
        lines.extend(panel_lines)
    if slot_lines:
        lines.append("Character Slots:")
        lines.extend(slot_lines)

    continuity_lines = []
    for track in _as_list(page.get("continuity_tracks")):
        if not isinstance(track, dict):
            continue
        if for_image:
            position = label_by_panel_id.get(track.get("panel_id"), "panel")
            values = [position, f"state={track.get('state')}"]
        else:
            values = [
                f"entity_id={track.get('entity_id')}",
                f"panel_id={track.get('panel_id')}",
                f"state={track.get('state')}",
            ]
        if track.get("intentional_change"):
            values.append("intentional_change=true")
        if track.get("change_note"):
            values.append(f"change_note={track['change_note']}")
        continuity_lines.append("- " + "; ".join(values))
    if continuity_lines:
        lines.append("Continuity Tracks:")
        lines.extend(continuity_lines)

    geometry_lines = []
    geometry = page.get("layout_geometry")
    for item in _as_list(geometry.get("panels") if isinstance(geometry, dict) else None):
        if not isinstance(item, dict) or not isinstance(item.get("rect"), dict):
            continue
        rect = item["rect"]
        if for_image:
            position = label_by_panel_id.get(item.get("panel_id"), "panel")
            geometry_lines.append(f"- {position}")
        else:
            geometry_lines.append(
                f"- panel {item.get('panel_id')}: rect="
                f"({rect.get('x')}, {rect.get('y')}, {rect.get('w')}, {rect.get('h')})"
            )
    if geometry_lines:
        lines.append("Layout Geometry:")
        lines.extend(geometry_lines)

    image_by_asset = {
        item.get("asset_id"): item
        for item in (image_inputs or [])
        if item.get("asset_id")
    }
    asset_lines = []
    for asset in _as_list(page.get("asset_references")):
        if not isinstance(asset, dict):
            continue
        attached = image_by_asset.get(asset.get("asset_id"))
        if for_image:
            if not attached:
                continue
            asset_lines.append(
                f"- image {attached['order']}: role={attached['role']}; "
                f"attachment=image {attached['order']} ({attached['role']})"
            )
            continue
        linked = next(
            (
                f"{label}={asset[label]}"
                for label in ("character_id", "variant_id", "concept_id")
                if asset.get(label)
            ),
            "",
        )
        suffix = f"; {linked}" if linked else ""
        attachment = (
            f"attachment=image {attached['order']} ({attached['role']})"
            if attached
            else "attachment=not_requested"
        )
        asset_lines.append(
            f"- asset_id={asset.get('asset_id')}; role={asset.get('role')}"
            f"{suffix}; {attachment}"
        )
    if asset_lines:
        lines.append("Asset References (ordered attachments when a path is supplied):")
        lines.extend(asset_lines)
    return lines if len(lines) > 1 else []


def _novelai_text_limit(model: str | None) -> tuple[str, int]:
    model_text = str(model or "nai-diffusion-5-full").lower()
    profile = "curated" if "curated" in model_text else "full"
    return profile, NOVELAI_TEXT_LIMITS[profile]


def _validate_novelai_text_limit(
    manifest: list[dict[str, Any]],
    *,
    model: str | None,
) -> tuple[str, int]:
    profile, limit = _novelai_text_limit(model)
    text_block = _novelai_dialogue_text_block(manifest)
    count = len(text_block)
    if count > limit:
        raise PageRenderPlanError(
            "NovelAI Textブロックの文字数がモデル上限を超えています: "
            f"{count} > {limit} ({profile})（文字を省略しません）"
        )
    return profile, limit


def _validate_page_compiler_limits(page: dict[str, Any]) -> None:
    """Reject formatter truncation that would silently lose page information."""
    panels = [panel for panel in page.get("panels") or [] if isinstance(panel, dict)]
    if len(panels) > PAGE_PANEL_OUTLINE_LIMIT:
        raise PageRenderPlanError(
            "PageRenderPlan のPanel Outline件数が上限を超えています: "
            f"{len(panels)} > {PAGE_PANEL_OUTLINE_LIMIT}（panelを省略しません）"
        )

    for snapshot in page.get("character_snapshots") or []:
        if not isinstance(snapshot, dict):
            continue
        fixed_tags = [tag for tag in snapshot.get("fixed_tags") or [] if tag]
        if len(fixed_tags) > CHARACTER_FIXED_TAG_LIMIT:
            character_id = snapshot.get("character_id") or snapshot.get("name") or "unknown"
            raise PageRenderPlanError(
                "PageRenderPlan のcharacter_line固定タグ件数が上限を超えています: "
                f"character={character_id!r}, {len(fixed_tags)} > "
                f"{CHARACTER_FIXED_TAG_LIMIT}（タグを省略しません）"
            )


def _page_image_reference_records(
    page: dict[str, Any],
    *,
    asset_base_dir: Path | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Resolve path-bearing asset references in declared YAML order.

    An asset without ``path`` is an ID-only semantic reference and is not an
    attachment request. A supplied path is explicit: missing or unreadable
    files stop compilation instead of being silently omitted.
    """
    ordered: list[dict[str, Any]] = []
    for asset in _as_list(page.get("asset_references")):
        if not isinstance(asset, dict) or not str(asset.get("path") or "").strip():
            continue
        raw_path = Path(str(asset["path"]).strip()).expanduser()
        if not raw_path.is_absolute():
            if asset_base_dir is None:
                raise PageRenderPlanError(
                    "asset_references.pathが相対パスですがasset_base_dirがありません: "
                    f"{raw_path}"
                )
            raw_path = asset_base_dir / raw_path
        resolved = raw_path.resolve()
        if not resolved.is_file():
            raise PageRenderPlanError(
                f"asset_referencesの参照画像が見つかりません: {resolved}"
            )
        try:
            raw = resolved.read_bytes()
            with Image.open(resolved) as image:
                image.verify()
            with Image.open(resolved) as image:
                dimensions = [int(image.width), int(image.height)]
        except Exception as exc:
            raise PageRenderPlanError(
                f"asset_referencesの参照画像を読めません: {resolved}: {exc}"
            ) from exc
        record: dict[str, Any] = {
            "asset_id": str(asset.get("asset_id") or ""),
            "role": str(asset.get("role") or "reference").strip().lower(),
            "path": str(resolved),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "order": len(ordered) + 1,
            "dimensions": dimensions,
        }
        for key in ("character_id", "variant_id", "concept_id"):
            if asset.get(key):
                record[key] = str(asset[key])
        ordered.append(record)
    try:
        ordered = validate_ordered_image_inputs(
            ordered,
            label="PageRenderPlan.ordered_image_inputs",
        )
    except ValueError as exc:
        raise PageRenderPlanError(str(exc)) from exc
    name_images = [
        item for item in ordered if item.get("role") in {"layout", "name"}
    ]
    return ordered, name_images


def _provider_label(provider: str) -> str:
    return {
        "novelai": "NovelAI page compiler",
        "openai": "GPT Image page compiler",
        "openrouter": "OpenRouter Image API page compiler",
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
    bubble_frame_mode: str | None = None,
    resolved_model: str | None = None,
    resolved_profile: str | None = None,
    novelai_model: str | None = None,
    openrouter_model: str | None = None,
    openrouter_profile: str | None = None,
    asset_base_dir: str | Path | None = None,
    characters: dict[str, dict[str, Any]] | None = None,
) -> PageRenderPlan:
    """Compile a schema 1.0/1.1 page without changing the source mapping."""
    if source not in {"step1-pages", "step2-pages"}:
        raise PageRenderPlanError(f"PageRenderPlan はページ生成専用です: source={source}")
    if provider not in SUPPORTED_PROVIDERS:
        raise PageRenderPlanError(
            f"provider={provider} はページcompiler未対応です（Forgeはlegacy）"
        )
    frame_mode = str(bubble_frame_mode or "provider").strip()
    if frame_mode not in BUBBLE_FRAME_MODES:
        raise PageRenderPlanError(
            f"bubble_frame_mode は provider / local です: {bubble_frame_mode!r}"
        )
    model_id = str(
        resolved_model or novelai_model or openrouter_model or ""
    ).strip()
    profile_id = str(resolved_profile or openrouter_profile or "").strip() or None
    try:
        capability_key = resolve_renderer_capability_key(
            provider=provider,
            model=model_id or None,
            profile=profile_id,
        )
        capability = lookup_renderer_capability(capability_key)
    except RendererCapabilityError as exc:
        raise PageRenderPlanError(str(exc)) from exc
    if frame_mode == "local":
        if provider != "novelai":
            raise PageRenderPlanError(
                "bubble_frame_mode=local は NovelAI の page_render_plan 入口でのみ選べます"
            )
        if not capability.get("postprocess_recommended"):
            raise PageRenderPlanError(
                f"bubble_frame_mode=local は postprocess_recommended のレンダラだけです: {capability_key}"
            )
        if text_mode in {"letter_later", "generate"}:
            raise PageRenderPlanError(
                "bubble_frame_mode=local は text_mode=letter_later / generate と併用できません"
            )
        text_mode = "none"
    declared_schema = page.get("schema_version", "1.0")
    if declared_schema not in {"1.0", "1.1"}:
        raise PageRenderPlanError(
            f"PageRenderPlan はschema 1.0 / 1.1のみ対応します: {declared_schema!r}"
        )
    try:
        MangaPagePrompt.model_validate(page)
    except ValueError as exc:
        raise PageRenderPlanError(f"ページIRの検証に失敗しました: {exc}") from exc
    try:
        validate_page_character_visual(page, characters)
    except CharacterVisualPageError as exc:
        raise PageRenderPlanError(str(exc)) from exc
    _validate_page_compiler_limits(page)

    render_page = copy.deepcopy(page)
    rebuild_resolved_snapshots(render_page, characters)

    base_dir = Path(asset_base_dir).expanduser().resolve() if asset_base_dir else None
    ordered_image_inputs, name_images = _page_image_reference_records(
        page,
        asset_base_dir=base_dir,
    )
    page_hash = canonical_page_hash(page)
    if provider == "novelai" and text_mode is None:
        # T1: 話者 slot に白い吹き出し「台詞」を割り当てる。空泡の letter_later は明示時。
        text_mode = "generate"
    mode, policy, policy_warnings = resolve_text_mode(page, text_mode)
    manifest = build_text_manifest(page, page_hash)
    character_slots = build_novelai_character_slots(
        render_page,
        page_hash,
        enforce_limit=provider == "novelai",
        characters=characters,
        text_mode=mode,
        attach_novelai_bubbles=provider == "novelai",
    )
    page_context = schema_1_1_prompt_context(
        render_page,
        page_hash=page_hash,
        character_slots=character_slots,
        image_inputs=ordered_image_inputs,
    )
    image_context = (
        []
        if provider == "novelai"
        else schema_1_1_prompt_context(
            render_page,
            page_hash=page_hash,
            character_slots=character_slots,
            image_inputs=ordered_image_inputs,
            for_image=True,
        )
    )
    prompt_source = existing_prompt.strip()
    grok_layout_constraint = provider in {"grok", "grok_pro"}
    if grok_layout_constraint:
        prompt_source = _remove_visible_reading_order_hints(prompt_source)
    if mode in {"letter_later", "none"}:
        prompt_source = _strip_text_lines(prompt_source, manifest)
    if mode == "letter_later":
        text_layout = _letter_later_text_layout_block(page, manifest)
        if text_layout:
            prompt_source = f"{prompt_source}\n\n{text_layout}"
    if provider == "novelai":
        # 英語のページ説明を前に重ねない。コマ指示と文字方針だけを送る。
        placed = {
            str(content)
            for slot in character_slots
            for content in (slot.get("rendered_contents") or [])
            if content
        }
        if placed:
            prompt_source = _strip_lines_containing(prompt_source, placed)
        prompt_source = f"{prompt_source}\n\nEffective text mode: {mode}.\n{policy}"
        if mode == "generate":
            prompt_source = _with_novelai_generate_bubble_tags(prompt_source)
        bundle = PromptBundle(
            prompt=prompt_source,
            negative_prompt=negative_prompt,
            formatter=MANGA_PAGE_INSTRUCTION,
            negative_mode=NATIVE_NEGATIVE,
        )
    else:
        prompt_source = (
            f"{_provider_label(provider)}.\n\n{prompt_source}\n\n"
            f"Effective text mode: {mode}.\n{policy}"
        )
        if image_context:
            prompt_source = "\n".join(image_context) + "\n\n" + prompt_source
        page_for_format = render_page
        _enrich_image_character_snapshots(page_for_format, characters)
        instruction = page_for_format.setdefault("render_instruction", {})
        if isinstance(instruction, dict):
            instruction["text_policy"] = policy
        sent_negative = negative_prompt
        if mode == "generate":
            sent_negative = _without_negative_token(sent_negative, "text")
        sent_negative = ", ".join(
            part for part in (sent_negative, _IMAGE_BOUNDARY_NEGATIVE) if part
        )
        bundle = format_manga_page_prompt(
            page_for_format,
            source=source,
            existing_prompt=prompt_source,
            negative_prompt=sent_negative,
            formatter=MANGA_PAGE_INSTRUCTION,
            include_character_variant_tags=provider not in {"grok", "grok_pro"},
            compact_character_visual=provider in {"grok", "grok_pro"},
            include_character_subject_notes=provider not in {"grok", "grok_pro"},
            reading_order_as_layout_constraint=grok_layout_constraint,
        )
    unsupported: list[str] = []
    if not ordered_image_inputs and provider != "openrouter":
        # Keep the P1 audit wording for the original bridges. OpenRouter's
        # page bridge is now available; an empty list there simply means that
        # this page declared no attachments.
        unsupported = [
            "ordered image inputs are unsupported in P1; not sent",
            "name image is unsupported in P1; not sent",
        ]
    elif provider == "novelai" and ordered_image_inputs:
        unsupported = [
            "role-based page image inputs are not supported by the NovelAI page bridge; send rejected",
        ]
    compiled_prompt = bundle.prompt
    if mode in {"letter_later", "none"}:
        compiled_prompt = _strip_text_content(compiled_prompt, manifest)
    elif provider == "novelai" and character_slots:
        # 台詞は各枠の白い吹き出しに入っている。ページ末尾の Text: は付けない。
        pass
    elif provider == "novelai":
        compiled_prompt = f"{compiled_prompt}\n\n{_novelai_dialogue_text_block(manifest)}"
    else:
        compiled_prompt = f"{compiled_prompt}\n\n{_text_block(manifest)}"
    if provider in {"novelai", "grok", "grok_pro"}:
        compiled_prompt = _strip_page_japanese_gloss_lines(compiled_prompt)
    compiled_prompt = scrub_image_prompt_identifiers(compiled_prompt, page)
    warnings = list(policy_warnings)
    effective_settings: dict[str, Any] = {
        "text_mode": mode,
        "bubble_frame_mode": frame_mode,
        "capability_key": capability_key,
        "resolved_model": model_id or None,
        "resolved_profile": profile_id,
        "bubbles_suppressed": frame_mode == "local" and mode == "none",
        "capability": {
            "supports_native_bubbles": capability.get("supports_native_bubbles"),
            "postprocess_recommended": capability.get("postprocess_recommended"),
            "provisional": capability.get("provisional"),
        },
        "lettering_style": _lettering_style(page),
        "image_reference_contract": {
            "version": REFERENCE_CONTRACT_VERSION,
            "ordered_count": len(ordered_image_inputs),
            "name_image_count": len(name_images),
            "reference_guided_generation": bool(ordered_image_inputs),
            "attachment_order": [item["order"] for item in ordered_image_inputs],
        },
    }
    if declared_schema == "1.1":
        effective_settings["schema_1_1_context"] = "common_prompt_sections"
        effective_settings["character_slot_count"] = len(character_slots)
        if provider == "novelai" and mode == "generate" and not character_slots:
            profile, text_limit = _validate_novelai_text_limit(
                manifest,
                model=novelai_model,
            )
            effective_settings["novelai_text_limit"] = {
                "model": novelai_model or "nai-diffusion-5-full",
                "profile": profile,
                "characters": text_limit,
            }
    if provider == "novelai" and mode == "generate" and character_slots:
        effective_settings["quality_text_policy"] = "dialogue_in_character_slots"
        warnings.append(
            "NovelAI dialogue is written into per-panel character slots as 白い吹き出し; "
            "Text: is not appended"
        )
    elif provider == "novelai" and mode == "generate":
        effective_settings["quality_text_policy"] = (
            "preserve_text_block; visual_quality_suffix_may_contain_no_text"
        )
        warnings.append(
            "NovelAI quality suffix may contain `no text`; it is kept in the visual "
            "prefix while the compiler-owned Text: block remains authoritative"
        )
    elif provider == "novelai":
        effective_settings["quality_text_policy"] = "no_text_suffix_allowed"
    else:
        effective_settings["quality_text_policy"] = "provider_default"
    if mode in {"letter_later", "none"} and any(
        str(item.get("content") or "") in compiled_prompt for item in manifest
    ):
        warnings.append("text content remains in the compiled prompt; manual cleanup is required")

    declared_records = [
        {
            "path": key,
            "value": value,
            "classified_as": _policy_class(value),
        }
        for key, value in explicit_text_policies(page)
    ]

    return PageRenderPlan(
        schema_version=str(declared_schema),
        compiler_version=PAGE_COMPILER_VERSION,
        page_hash=page_hash,
        source_mode=source,
        provider=provider,
        prompt=compiled_prompt,
        negative_prompt=bundle.negative_prompt,
        formatter=bundle.formatter,
        negative_mode=bundle.negative_mode,
        text_mode=mode,
        text_policy=policy,
        bubble_frame_mode=frame_mode,
        capability_key=capability_key,
        declared_text_policies=declared_records,
        text_manifest=manifest,
        character_slots=character_slots,
        page_context=page_context,
        ordered_image_inputs=ordered_image_inputs,
        name_images=name_images,
        reference_contract_version=REFERENCE_CONTRACT_VERSION,
        unsupported=unsupported,
        effective_settings=effective_settings,
        warnings=warnings,
    )
