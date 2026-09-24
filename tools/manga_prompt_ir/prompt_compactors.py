"""Provider-neutral prompt compaction for manga page IR.

This module deliberately stops at a fact-oriented intermediate result.  It
does not know about NovelAI prompt syntax, character slots, UC, or provider
byte limits.  Provider adapters can render the same result into their own
request shape without rewriting the YAML IR.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from .character_fixed_tags import base_fixed_tags_from
from .character_visual_resolver import (
    VisualResolverError,
    is_character_schema_1_1,
    resolve_character_visual,
)
from .scene_prompt import (
    camera_tag_tokens,
    composition_layout_tag_token,
    composition_tag_tokens,
    lighting_tag_tokens,
    panel_mood_atmosphere_tag_tokens,
    scene_prompt_background_notes,
    scene_prompt_location_time_weather,
    subject_situational_tag_tokens,
    subject_tag_line_token,
)


# The initial dictionary is intentionally empty.  An alias is only safe after
# the spelling is confirmed against the project's actual IR and provider tag
# vocabulary.
SAFE_ALIASES: dict[str, str] = {}


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _clean(value: Any) -> str:
    return str(value or "").strip()


def normalize_tag(value: Any) -> str:
    raw = _clean(value)
    return SAFE_ALIASES.get(raw, raw)


def normalize_tags(values: Iterable[Any]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        tag = normalize_tag(value)
        if not tag or tag in seen:
            continue
        seen.add(tag)
        result.append(tag)
    return tuple(result)


@dataclass(frozen=True)
class CharacterAnchor:
    character_id: str
    tags: tuple[str, ...]
    protected_tags: tuple[str, ...] = ()
    do_not_change: tuple[str, ...] = ()


@dataclass(frozen=True)
class VariantAnchor:
    character_id: str
    selected_variant_id: str
    tags: tuple[str, ...]


@dataclass(frozen=True)
class PanelDelta:
    panel_id: str
    subject_index: int | None
    tags: tuple[str, ...]


@dataclass(frozen=True)
class PanelOutline:
    panel_id: str
    text: str


@dataclass(frozen=True)
class PanelVisual:
    panel_id: str
    tags: tuple[str, ...]
    text: str = ""


@dataclass(frozen=True)
class PanelSubject:
    panel_id: str
    subject_index: int
    character_id: str | None
    variant_id: str | None
    text: str


@dataclass(frozen=True)
class TextRecord:
    text_id: str
    panel_id: str
    type: str
    content: str
    speaker: str | None = None
    placement: str | None = None
    bubble_type: str | None = None
    meaning: str | None = None
    writing_direction: str | None = None

    @classmethod
    def from_mapping(cls, item: dict[str, Any], *, fallback_id: str) -> "TextRecord":
        return cls(
            text_id=_clean(item.get("text_id")) or fallback_id,
            panel_id=_clean(item.get("panel_id")),
            type=_clean(item.get("type")) or "unknown",
            content=_clean(item.get("content") or item.get("text")),
            speaker=_clean(item.get("speaker") or item.get("character_id")) or None,
            placement=_clean(item.get("placement")) or None,
            bubble_type=_clean(item.get("bubble_type")) or None,
            meaning=_clean(item.get("meaning")) or None,
            writing_direction=_clean(item.get("writing_direction")) or None,
        )


@dataclass(frozen=True)
class RemovedTag:
    tag: str
    source: str
    reason: str
    panel_id: str | None = None
    subject_index: int | None = None


@dataclass(frozen=True)
class PromptCompactionResult:
    page_common_tags: tuple[str, ...]
    character_anchors: tuple[CharacterAnchor, ...]
    variant_anchors: tuple[VariantAnchor, ...]
    panel_deltas: tuple[PanelDelta, ...]
    panel_outlines: tuple[PanelOutline, ...]
    panel_visuals: tuple[PanelVisual, ...]
    text_manifest: tuple[TextRecord, ...]
    negative_tags: tuple[str, ...]
    removed_occurrences: tuple[RemovedTag, ...]
    warnings: tuple[str, ...]
    page_structure: tuple[str, ...] = ()
    page_policy: tuple[str, ...] = ()
    panel_subjects: tuple[PanelSubject, ...] = ()
    style_helper: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "page_common_tags": list(self.page_common_tags),
            "character_anchors": [
                {
                    "character_id": item.character_id,
                    "tags": list(item.tags),
                    "protected_tags": list(item.protected_tags),
                    "do_not_change": list(item.do_not_change),
                }
                for item in self.character_anchors
            ],
            "variant_anchors": [
                {
                    "character_id": item.character_id,
                    "selected_variant_id": item.selected_variant_id,
                    "tags": list(item.tags),
                }
                for item in self.variant_anchors
            ],
            "panel_deltas": [
                {
                    "panel_id": item.panel_id,
                    "subject_index": item.subject_index,
                    "tags": list(item.tags),
                }
                for item in self.panel_deltas
            ],
            "panel_outlines": [
                {"panel_id": item.panel_id, "text": item.text}
                for item in self.panel_outlines
            ],
            "panel_visuals": [
                {
                    "panel_id": item.panel_id,
                    "tags": list(item.tags),
                    "text": item.text,
                }
                for item in self.panel_visuals
            ],
            "text_manifest": [
                {
                    "text_id": item.text_id,
                    "panel_id": item.panel_id,
                    "type": item.type,
                    "content": item.content,
                    "speaker": item.speaker,
                    "placement": item.placement,
                    "bubble_type": item.bubble_type,
                    "meaning": item.meaning,
                    "writing_direction": item.writing_direction,
                }
                for item in self.text_manifest
            ],
            "negative_tags": list(self.negative_tags),
            "removed_occurrences": [
                {
                    "tag": item.tag,
                    "source": item.source,
                    "reason": item.reason,
                    "panel_id": item.panel_id,
                    "subject_index": item.subject_index,
                }
                for item in self.removed_occurrences
            ],
            "warnings": list(self.warnings),
            "page_structure": list(self.page_structure),
            "page_policy": list(self.page_policy),
            "panel_subjects": [
                {
                    "panel_id": item.panel_id,
                    "subject_index": item.subject_index,
                    "character_id": item.character_id,
                    "variant_id": item.variant_id,
                    "text": item.text,
                }
                for item in self.panel_subjects
            ],
            "style_helper": self.style_helper,
        }


def _subject_variant_id(subject: dict[str, Any], snapshot: dict[str, Any] | None) -> str | None:
    values = [
        _clean(subject.get(key))
        for key in ("prompt_variant_id", "costume_variant", "variant_id")
        if _clean(subject.get(key))
    ]
    unique = list(dict.fromkeys(values))
    if len(unique) > 1:
        raise ValueError(
            "prompt_variant_id / costume_variant / variant_id が食い違っています: "
            + ", ".join(unique)
        )
    if unique:
        return unique[0]
    selected = _clean((snapshot or {}).get("selected_variant_id"))
    return selected or None


def _snapshot_map(page: dict[str, Any]) -> dict[tuple[str, str | None], dict[str, Any]]:
    result: dict[tuple[str, str | None], dict[str, Any]] = {}
    for item in _as_list(page.get("character_snapshots")):
        if not isinstance(item, dict) or not _clean(item.get("character_id")):
            continue
        cid = _clean(item.get("character_id"))
        vid = _clean(item.get("selected_variant_id")) or None
        result[(cid, vid)] = item
        result.setdefault((cid, None), item)
    return result


def _character_tag_groups(
    character_id: str,
    variant_id: str | None,
    snapshot: dict[str, Any] | None,
    character: dict[str, Any] | None,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """Return fixed, selected variant, and do-not-change facts separately."""
    if snapshot is not None:
        fixed = normalize_tags(_as_list(snapshot.get("fixed_tags")))
        variant = normalize_tags(_as_list(snapshot.get("variant_tags")))
        protected = normalize_tags(fixed)
        do_not_change = normalize_tags(_as_list(snapshot.get("do_not_change")))
        if fixed or variant or do_not_change:
            return fixed, variant, tuple([*protected, *do_not_change])
    if not character:
        return (), (), ()
    try:
        if is_character_schema_1_1(character):
            visual = resolve_character_visual(character, variant_id)
            fixed = normalize_tags(visual.identity_tags)
            variant = normalize_tags([*visual.costume_tags, *visual.state_tags])
        else:
            fixed = normalize_tags(base_fixed_tags_from(character))
            variant_item = next(
                (
                    item
                    for item in _as_list(character.get("prompt_variants"))
                    if isinstance(item, dict)
                    and _clean(item.get("variant_id")) == (variant_id or "")
                ),
                None,
            )
            variant = normalize_tags(
                _as_list((variant_item or {}).get("danbooru_tags"))
            )
    except VisualResolverError as exc:
        raise ValueError(str(exc)) from exc
    rules = character.get("manga_rules") or {}
    do_not_change = normalize_tags(_as_list(rules.get("do_not_change")))
    return fixed, variant, tuple([*fixed, *do_not_change])


def _page_common_candidates(page: dict[str, Any]) -> tuple[str, ...]:
    manga = page.get("manga") or {}
    scene = page.get("scene") or {}
    palette = page.get("color_palette") or {}
    instruction = page.get("render_instruction") or {}
    directives = instruction.get("user_directives") if isinstance(instruction, dict) else {}
    defaults = directives.get("defaults") if isinstance(directives, dict) else {}
    values: list[str] = []
    values.extend(_as_list(manga.get("genre_tags")))
    values.extend(_as_list(manga.get("visual_tags")))
    values.extend(_as_list(manga.get("background_tags")))
    if isinstance(palette, dict):
        values.append(palette.get("mode"))
    location, time_of_day, weather = scene_prompt_location_time_weather(scene)
    values.extend([location, time_of_day, weather])
    notes = scene_prompt_background_notes(scene)
    if notes:
        values.extend(part.strip() for part in notes.split(","))
    if isinstance(defaults, dict):
        values.extend(_as_list(defaults.get("required_prompt_tags")))
    return normalize_tags(values)


def _panel_local_tags(panel: dict[str, Any]) -> tuple[str, ...]:
    scene = panel.get("scene") or {}
    composition = panel.get("composition") or {}
    camera = panel.get("camera") or {}
    lighting = panel.get("lighting") or {}
    values: list[str] = []
    values.extend(_as_list(panel.get("prompt_tags")))
    values.extend(composition_layout_tag_token(composition, single_panel=False))
    values.extend(composition_tag_tokens(composition))
    values.extend(camera_tag_tokens(camera))
    values.extend(lighting_tag_tokens(lighting))
    values.extend(panel_mood_atmosphere_tag_tokens(panel))
    if scene:
        values.extend(comma_parts(scene_prompt_background_notes(scene)))
    return normalize_tags(values)


def comma_parts(value: Any) -> list[str]:
    return [part.strip() for part in str(value or "").split(",") if part.strip()]


def _subject_text(subject: dict[str, Any], character_id: str | None, variant_id: str | None) -> str:
    values = [
        _clean(subject.get("description_en") or subject.get("description") or subject.get("type")),
        _clean(subject.get("pose_action_en") or subject.get("pose_action")),
        _clean(subject.get("expression_en") or subject.get("expression")),
        _clean(subject.get("position")),
    ]
    if character_id:
        values.insert(0, character_id)
    if variant_id:
        values.append(f"variant={variant_id}")
    return "; ".join(value for value in values if value)


def _build_text_records(page: dict[str, Any]) -> tuple[TextRecord, ...]:
    records: list[TextRecord] = []
    for panel in _as_list(page.get("panels")):
        if not isinstance(panel, dict):
            continue
        panel_id = _clean(panel.get("panel_id"))
        text = panel.get("text") or {}
        if not isinstance(text, dict):
            continue
        for kind in ("dialogue", "monologue", "narration", "sfx"):
            for index, raw in enumerate(_as_list(text.get(kind)), start=1):
                if isinstance(raw, dict):
                    content = _clean(raw.get("content") or raw.get("text"))
                    speaker = _clean(raw.get("speaker") or raw.get("character_id")) or None
                    placement = _clean(raw.get("placement")) or None
                    bubble_type = _clean(raw.get("bubble_type")) or None
                    meaning = _clean(raw.get("meaning")) or None
                    writing_direction = _clean(raw.get("writing_direction")) or None
                    text_id = _clean(raw.get("text_id"))
                else:
                    content = _clean(raw)
                    speaker = placement = bubble_type = meaning = writing_direction = text_id = None
                if content:
                    records.append(
                        TextRecord(
                            text_id=text_id or f"p{panel_id}-{kind}-{index:02d}",
                            panel_id=panel_id,
                            type=kind,
                            content=content,
                            speaker=speaker,
                            placement=placement,
                            bubble_type=bubble_type,
                            meaning=meaning,
                            writing_direction=writing_direction,
                        )
                    )
    return tuple(records)


def _coerce_text_manifest(
    page: dict[str, Any], text_manifest: Iterable[dict[str, Any]] | None
) -> tuple[TextRecord, ...]:
    if text_manifest is None:
        return _build_text_records(page)
    records: list[TextRecord] = []
    for index, item in enumerate(text_manifest, start=1):
        if isinstance(item, dict):
            records.append(TextRecord.from_mapping(item, fallback_id=f"text-{index:03d}"))
    return tuple(records)


def _page_policy(page: dict[str, Any]) -> tuple[str, ...]:
    instruction = page.get("render_instruction") or {}
    if not isinstance(instruction, dict):
        return ()
    values: list[str] = []
    for key in ("task", "prompt_header", "panel_policy", "character_policy", "text_policy", "output_policy"):
        value = _clean(instruction.get(key))
        if value:
            values.append(value)
    values.extend(_clean(value) for value in _as_list(instruction.get("notes")) if _clean(value))
    return tuple(dict.fromkeys(values))


def _page_structure(page: dict[str, Any]) -> tuple[str, ...]:
    meta = page.get("meta") or {}
    manga = page.get("manga") or {}
    panels = [item for item in _as_list(page.get("panels")) if isinstance(item, dict)]
    values = [
        f"reading_order={_clean(meta.get('reading_order')) or 'right_to_left'}",
        f"panel_count={len(panels)}",
        f"panel_layout={_clean(manga.get('panel_layout'))}",
    ]
    return tuple(value for value in values if not value.endswith("="))


def compact_page_prompt(
    page: dict[str, Any],
    *,
    source: str,
    characters: dict[str, dict[str, Any]] | None = None,
    text_manifest: Iterable[dict[str, Any]] | None = None,
    style_helper: str | None = None,
    negative_prompt: str = "",
    mode: str = "safe",
) -> PromptCompactionResult:
    """Classify and compact a page without rendering a provider prompt.

    ``mode`` controls only whether fixed character anchors are expected to be
    repeated by a renderer.  The common result always retains the anchors;
    ``promote-fixed`` is a NovelAI policy choice, not a destructive IR edit.
    """
    if source not in {"step1-pages", "step2-pages"}:
        raise ValueError(f"ページコンパクタはページ生成専用です: source={source}")
    if mode not in {"safe", "promote-fixed"}:
        raise ValueError(f"未対応のprompt compaction modeです: {mode!r}")
    characters = characters or {}
    snapshots = _snapshot_map(page)
    panels = [item for item in _as_list(page.get("panels")) if isinstance(item, dict)]

    page_candidates = _page_common_candidates(page)
    defaults = (page.get("render_instruction") or {}).get("user_directives") or {}
    defaults = defaults.get("defaults") if isinstance(defaults, dict) else {}
    default_omit = set(normalize_tags(_as_list((defaults or {}).get("omit_prompt_tags"))))
    panel_omits = {
        _clean(panel.get("panel_id")): set(normalize_tags(_as_list(panel.get("omit_prompt_tags"))))
        for panel in panels
    }
    page_common: list[str] = []
    for tag in page_candidates:
        if tag in default_omit or any(tag in omit for omit in panel_omits.values()):
            continue
        page_common.append(tag)
    page_common_set = set(page_common)

    character_groups: dict[str, tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]] = {}
    variant_groups: dict[tuple[str, str], tuple[str, ...]] = {}
    fixed_signatures: dict[str, set[tuple[str, ...]]] = {}
    subject_context: dict[tuple[str, int], tuple[str, str | None, tuple[str, ...], tuple[str, ...]]] = {}
    for panel in panels:
        panel_id = _clean(panel.get("panel_id"))
        for index, subject in enumerate(_as_list(panel.get("subjects")), start=1):
            if not isinstance(subject, dict) or not _clean(subject.get("character_id")):
                continue
            cid = _clean(subject.get("character_id"))
            snapshot = snapshots.get((cid, _clean(subject.get("variant_id")) or None)) or snapshots.get((cid, None))
            vid = _subject_variant_id(subject, snapshot)
            groups = _character_tag_groups(cid, vid, snapshot, characters.get(cid))
            character_groups.setdefault(cid, groups)
            fixed_signatures.setdefault(cid, set()).add(tuple(sorted(groups[0])))
            if len(fixed_signatures[cid]) > 1:
                raise ValueError(
                    f"character_id={cid} のvariant間で固定タグ集合が一致しません。"
                    "和集合へ昇格せず、variant定義を修正してください"
                )
            if vid:
                variant_groups[(cid, vid)] = groups[1]
            subject_context[(panel_id, index)] = (cid, vid, groups[0], groups[1])

    character_anchors = tuple(
        CharacterAnchor(
            character_id=cid,
            tags=groups[0],
            protected_tags=groups[0],
            do_not_change=tuple(tag for tag in groups[2] if tag not in groups[0]),
        )
        for cid, groups in character_groups.items()
        if groups[0] or groups[2]
    )
    variant_anchors = tuple(
        VariantAnchor(character_id=cid, selected_variant_id=vid, tags=tags)
        for (cid, vid), tags in variant_groups.items()
    )

    removed: list[RemovedTag] = []
    panel_deltas: list[PanelDelta] = []
    panel_outlines: list[PanelOutline] = []
    panel_visuals: list[PanelVisual] = []
    panel_subjects: list[PanelSubject] = []
    for panel in panels:
        panel_id = _clean(panel.get("panel_id"))
        summary_key = "step2_summary" if source == "step2-pages" else "summary"
        outline = _clean(panel.get(summary_key) or panel.get("summary"))
        if outline:
            panel_outlines.append(PanelOutline(panel_id, outline))

        visual_tags = list(_panel_local_tags(panel))
        visual_text = "; ".join(
            value
            for value in (
                _clean((panel.get("composition") or {}).get("framing_en") or (panel.get("composition") or {}).get("framing")),
                _clean((panel.get("camera") or {}).get("shot_size_en") or (panel.get("camera") or {}).get("shot_size")),
                _clean((panel.get("composition") or {}).get("focus_en") or (panel.get("composition") or {}).get("focus")),
            )
            if value
        )
        panel_visuals.append(PanelVisual(panel_id, normalize_tags(visual_tags), visual_text))

        for index, subject in enumerate(_as_list(panel.get("subjects")), start=1):
            if not isinstance(subject, dict):
                continue
            cid = _clean(subject.get("character_id")) or None
            snapshot = snapshots.get((cid or "", _clean(subject.get("variant_id")) or None)) or snapshots.get((cid or "", None))
            vid = _subject_variant_id(subject, snapshot) if cid else None
            panel_subjects.append(
                PanelSubject(panel_id, index, cid, vid, _subject_text(subject, cid, vid))
            )

        omit = default_omit | panel_omits.get(panel_id, set())
        raw_tags: list[tuple[str, str, int | None]] = []
        for tag in page_candidates:
            if tag not in omit:
                raw_tags.append((tag, "page", None))
        for tag in _panel_local_tags(panel):
            raw_tags.append((tag, "panel", None))
        for index, subject in enumerate(_as_list(panel.get("subjects")), start=1):
            if not isinstance(subject, dict):
                continue
            cid = _clean(subject.get("character_id"))
            if cid:
                context = subject_context.get((panel_id, index))
                if context:
                    for tag in (*context[2], *context[3]):
                        raw_tags.append((tag, "character", index))
            else:
                raw_tags.append((subject_tag_line_token(subject), "subject", index))
            for tag in subject_situational_tag_tokens(subject):
                raw_tags.append((tag, "subject", index))
        delta_by_target: dict[int | None, list[str]] = {}
        seen_by_target: dict[int | None, set[str]] = {}
        target_order: list[int | None] = []
        for tag, origin, subject_index in raw_tags:
            if subject_index not in target_order:
                target_order.append(subject_index)
            delta = delta_by_target.setdefault(subject_index, [])
            seen = seen_by_target.setdefault(subject_index, set())
            normalized = normalize_tag(tag)
            if not normalized or normalized in omit:
                if normalized:
                    removed.append(RemovedTag(normalized, origin, "omit_prompt_tags", panel_id, subject_index))
                continue
            if normalized in page_common_set:
                removed.append(RemovedTag(normalized, origin, "page_common", panel_id, subject_index))
                continue
            context = subject_context.get((panel_id, subject_index or 0))
            fixed_tags = set(context[2]) if context else set()
            variant_tags = set(context[3]) if context else set()
            matched_anchor = origin == "character" and normalized in fixed_tags
            if matched_anchor:
                removed.append(RemovedTag(normalized, origin, "character_anchor", panel_id, subject_index))
                continue
            matched_variant = origin == "character" and normalized in variant_tags
            if matched_variant:
                removed.append(RemovedTag(normalized, origin, "variant_anchor", panel_id, subject_index))
                continue
            if normalized in seen:
                removed.append(RemovedTag(normalized, origin, "duplicate", panel_id, subject_index))
                continue
            seen.add(normalized)
            delta.append(normalized)
        if not target_order:
            target_order.append(None)
        panel_deltas.extend(
            PanelDelta(panel_id, target, tuple(delta_by_target.get(target, ())))
            for target in target_order
        )

    technical = page.get("technical") or {}
    negative_values: list[Any] = _as_list(technical.get("negative_tags"))
    for panel in panels:
        negative_values.extend(_as_list(panel.get("negative_tags")))
    negative_tags = normalize_tags([*negative_values, *str(negative_prompt).split(",")])
    warnings: list[str] = []
    if any(not item.tags for item in panel_deltas):
        warnings.append("空のPanel DeltaはPanel Outline/Subjects/Visualで内容を保持しています")
    return PromptCompactionResult(
        page_common_tags=tuple(page_common),
        character_anchors=character_anchors,
        variant_anchors=variant_anchors,
        panel_deltas=tuple(panel_deltas),
        panel_outlines=tuple(panel_outlines),
        panel_visuals=tuple(panel_visuals),
        text_manifest=_coerce_text_manifest(page, text_manifest),
        negative_tags=negative_tags,
        removed_occurrences=tuple(removed),
        warnings=tuple(warnings),
        page_structure=_page_structure(page),
        page_policy=_page_policy(page),
        panel_subjects=tuple(panel_subjects),
        style_helper=_clean(style_helper),
    )


def compact_page_for_provider(
    page: dict[str, Any],
    *,
    provider: str = "novelai",
    source: str = "step1-pages",
    **kwargs: Any,
) -> PromptCompactionResult:
    """Compatibility entry point for provider routing layers.

    The core remains provider-neutral; the provider argument is accepted here
    only so a caller can route through one common entry point before choosing a
    renderer.  Provider-specific validation belongs to the adapter.
    """
    del provider
    return compact_page_prompt(page, source=source, **kwargs)
