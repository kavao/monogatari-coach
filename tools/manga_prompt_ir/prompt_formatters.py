from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


TAG_CSV = "tag_csv"
NOVELAI_PIPE = "novelai_pipe"
NATURAL_SECTIONS = "natural_sections"
MANGA_PAGE_INSTRUCTION = "manga_page_instruction"
BACKGROUND_BRIEF = "background_brief"

NATIVE_NEGATIVE = "native"
INLINE_DO_NOT_INCLUDE = "inline_do_not_include"

VALID_FORMATTERS = {
    TAG_CSV,
    NOVELAI_PIPE,
    NATURAL_SECTIONS,
    MANGA_PAGE_INSTRUCTION,
    BACKGROUND_BRIEF,
}


@dataclass(frozen=True)
class PromptBundle:
    prompt: str
    negative_prompt: str
    formatter: str
    negative_mode: str


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def split_prompt_fragments(value: Any) -> list[str]:
    parts: list[str] = []
    for item in as_list(value):
        if item is None:
            continue
        parts.extend(part.strip() for part in str(item).split(",") if part.strip())
    return unique(parts)


def bullet_lines(values: list[str], *, limit: int | None = None) -> list[str]:
    items = values[:limit] if limit is not None else values
    return [f"- {item}" for item in items if item]


def named_section(title: str, lines: list[str]) -> str:
    clean = [line for line in lines if str(line).strip()]
    if not clean:
        return ""
    return title + ":\n" + "\n".join(clean)


def text_from_map(data: dict[str, Any], keys: tuple[str, ...]) -> list[str]:
    lines: list[str] = []
    for key in keys:
        value = data.get(key)
        if value:
            lines.append(str(value))
    return lines


def character_snapshot_map(page: dict[str, Any]) -> dict[str, dict[str, Any]]:
    snapshots: dict[str, dict[str, Any]] = {}
    for snapshot in as_list(page.get("character_snapshots")):
        if not isinstance(snapshot, dict):
            continue
        cid = snapshot.get("character_id")
        if cid:
            snapshots[str(cid)] = snapshot
    return snapshots


def character_line(
    snapshot: dict[str, Any],
    *,
    subject_notes: list[str] | None = None,
) -> str:
    name = str(
        snapshot.get("name_en")
        or snapshot.get("name")
        or snapshot.get("character_id")
        or "character"
    )
    details: list[str] = []
    for key in ("appearance_summary", "costume_summary"):
        value = snapshot.get(key)
        if value:
            details.append(str(value))
    fixed = [str(x) for x in as_list(snapshot.get("fixed_tags")) if x]
    if fixed:
        details.append(", ".join(fixed[:12]))
    if subject_notes:
        details.extend(subject_notes)
    return f"- {name}: " + "; ".join(details)


def subject_notes(subject: dict[str, Any]) -> list[str]:
    notes: list[str] = []
    for label, key in (
        ("role", "description_en"),
        ("action", "pose_action_en"),
        ("expression", "expression_en"),
        ("position", "position"),
    ):
        value = subject.get(key)
        if value:
            notes.append(f"{label}: {value}")
    return notes


def do_not_include_lines(
    page: dict[str, Any],
    negative_prompt: str,
) -> list[str]:
    instruction = page.get("render_instruction") or {}
    directives = instruction.get("user_directives") or {}
    defaults = directives.get("defaults") or {}
    items: list[str] = []
    items.extend(split_prompt_fragments(negative_prompt))
    items.extend(str(x) for x in as_list(defaults.get("omit_prompt_tags")) if x)
    for snapshot in as_list(page.get("character_snapshots")):
        if isinstance(snapshot, dict):
            items.extend(str(x) for x in as_list(snapshot.get("do_not_change")) if x)
    return bullet_lines(unique(items), limit=24)


def illustration_header(page: dict[str, Any]) -> str:
    meta = page.get("meta") or {}
    kind = str(meta.get("illustration_type") or "").lower()
    if kind == "cover":
        return "Draw one vertical Japanese light novel cover illustration."
    if kind == "chapter_illustration":
        return "Draw one polished chapter illustration for a Japanese light novel."
    return "Draw one polished anime-style illustration."


def illustration_composition_lines(page: dict[str, Any]) -> list[str]:
    manga = page.get("manga") or {}
    scene = page.get("scene") or {}
    lines: list[str] = []
    panel_layout = manga.get("panel_layout")
    if panel_layout:
        lines.append(f"- Layout: {panel_layout}")
    location = scene.get("location_en") or scene.get("location")
    time_of_day = scene.get("time_of_day_en") or scene.get("time_of_day")
    if location or time_of_day:
        lines.append(f"- Setting: {location or 'unspecified'} / {time_of_day or 'unspecified'}")
    background = scene.get("background_notes_en") or scene.get("background_notes")
    if background:
        lines.append(f"- Background: {background}")
    for panel in as_list(page.get("panels")):
        if not isinstance(panel, dict):
            continue
        comp = panel.get("composition") or {}
        summary = panel.get("summary")
        if summary:
            lines.append(f"- Scene: {summary}")
        lines.extend(
            f"- {line}" for line in text_from_map(
                comp,
                ("framing_en", "layout_en", "focus_en", "perspective_en"),
            )
        )
    return lines


def illustration_character_lines(page: dict[str, Any]) -> list[str]:
    snapshots = character_snapshot_map(page)
    lines: list[str] = []
    used: set[str] = set()
    for panel in as_list(page.get("panels")):
        if not isinstance(panel, dict):
            continue
        for subject in as_list(panel.get("subjects")):
            if not isinstance(subject, dict):
                continue
            cid = str(subject.get("character_id") or "")
            snapshot = snapshots.get(cid)
            notes = subject_notes(subject)
            if snapshot:
                key = cid or str(snapshot.get("name_en") or snapshot.get("name"))
                if key in used:
                    continue
                used.add(key)
                lines.append(character_line(snapshot, subject_notes=notes))
            elif notes:
                lines.append("- " + "; ".join(notes))
    for cid, snapshot in snapshots.items():
        if cid not in used:
            lines.append(character_line(snapshot))
    return lines


def illustration_cell_lines(page: dict[str, Any]) -> list[str]:
    panels = [p for p in as_list(page.get("panels")) if isinstance(p, dict)]
    if len(panels) <= 1:
        return []
    lines: list[str] = []
    for panel in panels:
        pid = panel.get("panel_id", len(lines) + 1)
        summary = panel.get("summary")
        lines.append(f"- Cell {pid}: {summary or 'composition cell'}")
        comp = panel.get("composition") or {}
        focus = comp.get("focus_en") or comp.get("focus")
        if focus:
            lines.append(f"  - Focus: {focus}")
    return lines


def illustration_lighting_lines(page: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for panel in as_list(page.get("panels")):
        if not isinstance(panel, dict):
            continue
        lighting = panel.get("lighting") or {}
        lines.extend(
            f"- {line}" for line in text_from_map(
                lighting,
                ("direction_en", "quality_en", "mood_effect_en"),
            )
        )
        mood = panel.get("mood_atmosphere_en") or panel.get("mood_atmosphere")
        if mood:
            lines.append("- Mood: " + ", ".join(str(x) for x in as_list(mood) if x))
    return unique(lines)


def format_illustration_prompt(
    page: dict[str, Any],
    *,
    tag_prompt: str,
    negative_prompt: str,
    formatter: str,
    style_prefix: str = "",
) -> PromptBundle:
    if formatter not in VALID_FORMATTERS:
        raise ValueError(f"unknown prompt formatter: {formatter}")
    if formatter == TAG_CSV:
        return PromptBundle(
            prompt=style_prefix + tag_prompt,
            negative_prompt=negative_prompt,
            formatter=formatter,
            negative_mode=NATIVE_NEGATIVE,
        )

    prompt_parts: list[str] = [illustration_header(page)]
    instruction = page.get("render_instruction") or {}
    header = instruction.get("prompt_header")
    if header:
        prompt_parts.append(str(header))
    prompt_parts.append(named_section("Composition", illustration_composition_lines(page)))
    cells = illustration_cell_lines(page)
    if cells:
        prompt_parts.append(named_section("Composition Cells", cells))
    prompt_parts.append(named_section("Characters", illustration_character_lines(page)))
    prompt_parts.append(named_section("Lighting and Mood", illustration_lighting_lines(page)))
    tag_hints = split_prompt_fragments(tag_prompt)
    if tag_hints:
        prompt_parts.append(named_section("Visual Tag Hints", bullet_lines(tag_hints, limit=36)))
    prompt_parts.append(named_section("Do not include", do_not_include_lines(page, negative_prompt)))

    prompt = "\n\n".join(part for part in prompt_parts if part)
    return PromptBundle(
        prompt=prompt,
        negative_prompt="",
        formatter=formatter,
        negative_mode=INLINE_DO_NOT_INCLUDE,
    )


def manga_page_header(source: str) -> str:
    if source == "step1-pages":
        return (
            "Create one complete Japanese manga page from detailed panel instructions. "
            "Preserve each panel's role, character action, expression, background, and composition."
        )
    return (
        "Create one complete Japanese manga page from layout and scene instructions. "
        "Prioritize readable panel flow, stable characters, and a finished page composition."
    )


def manga_page_layout_lines(page: dict[str, Any], source: str) -> list[str]:
    meta = page.get("meta") or {}
    manga = page.get("manga") or {}
    panels = [panel for panel in as_list(page.get("panels")) if isinstance(panel, dict)]
    lines: list[str] = []
    lines.append(f"- Source: {source}")
    if panels:
        lines.append(f"- Panel count: {len(panels)}")
    reading_order = meta.get("reading_order")
    if reading_order:
        lines.append(f"- Reading order: {reading_order}")
    panel_layout = manga.get("panel_layout")
    if panel_layout:
        lines.append(f"- Page layout: {panel_layout}")
    color_mode = manga.get("color_mode")
    if color_mode:
        lines.append(f"- Color mode: {color_mode}")
    return lines


def manga_page_text_policy_lines(page: dict[str, Any]) -> list[str]:
    instruction = page.get("render_instruction") or {}
    lines: list[str] = []
    for key in ("text_policy", "output_policy", "panel_policy"):
        value = instruction.get(key)
        if value:
            lines.append(f"- {value}")
    return lines


def manga_page_panel_outline_lines(page: dict[str, Any], *, limit: int = 12) -> list[str]:
    lines: list[str] = []
    for panel in [p for p in as_list(page.get("panels")) if isinstance(p, dict)][:limit]:
        pid = panel.get("panel_id", len(lines) + 1)
        summary = panel.get("summary") or panel.get("translation") or "panel"
        lines.append(f"- Panel {pid}: {summary}")
        comp = panel.get("composition") or {}
        focus = comp.get("focus_en") or comp.get("focus")
        if focus:
            lines.append(f"  - Focus: {focus}")
    return lines


def format_manga_page_prompt(
    page: dict[str, Any],
    *,
    source: str,
    existing_prompt: str,
    negative_prompt: str,
    formatter: str,
) -> PromptBundle:
    if formatter not in VALID_FORMATTERS:
        raise ValueError(f"unknown prompt formatter: {formatter}")
    if formatter != MANGA_PAGE_INSTRUCTION:
        return PromptBundle(
            prompt=existing_prompt,
            negative_prompt=negative_prompt,
            formatter=formatter,
            negative_mode=NATIVE_NEGATIVE,
        )

    prompt_parts: list[str] = [
        manga_page_header(source),
        named_section("Page Structure", manga_page_layout_lines(page, source)),
        named_section("Panel Outline", manga_page_panel_outline_lines(page)),
        named_section("Character Anchors", illustration_character_lines(page)),
        named_section("Text and Output Policy", manga_page_text_policy_lines(page)),
        named_section("Do not include", do_not_include_lines(page, negative_prompt)),
        "Source Page Instructions:\n" + existing_prompt.strip(),
    ]
    prompt = "\n\n".join(part for part in prompt_parts if part)
    return PromptBundle(
        prompt=prompt,
        negative_prompt="",
        formatter=formatter,
        negative_mode=INLINE_DO_NOT_INCLUDE,
    )


def manga_panel_header() -> str:
    return (
        "Draw one polished Japanese manga panel. "
        "Preserve the described subject, action, expression, camera, background, and mood."
    )


def manga_panel_context_lines(page: dict[str, Any], panel: dict[str, Any]) -> list[str]:
    meta = page.get("meta") or {}
    manga = page.get("manga") or {}
    scene = page.get("scene") or {}
    lines: list[str] = []
    panel_id = panel.get("panel_id")
    if panel_id:
        lines.append(f"- Panel ID: {panel_id}")
    summary = panel.get("summary") or panel.get("translation")
    if summary:
        lines.append(f"- Scene: {summary}")
    panel_layout = manga.get("panel_layout")
    if panel_layout:
        lines.append(f"- Parent page layout: {panel_layout}")
    reading_order = meta.get("reading_order")
    if reading_order:
        lines.append(f"- Parent page reading order: {reading_order}")
    location = scene.get("location_en") or scene.get("location")
    time_of_day = scene.get("time_of_day_en") or scene.get("time_of_day")
    if location or time_of_day:
        lines.append(f"- Setting: {location or 'unspecified'} / {time_of_day or 'unspecified'}")
    background = scene.get("background_notes_en") or scene.get("background_notes")
    if background:
        lines.append(f"- Background: {background}")
    return lines


def manga_panel_character_lines(page: dict[str, Any], panel: dict[str, Any]) -> list[str]:
    snapshots = character_snapshot_map(page)
    lines: list[str] = []
    for subject in as_list(panel.get("subjects")):
        if not isinstance(subject, dict):
            continue
        cid = str(subject.get("character_id") or "")
        snapshot = snapshots.get(cid)
        notes = subject_notes(subject)
        if snapshot:
            lines.append(character_line(snapshot, subject_notes=notes))
        elif notes:
            lines.append("- " + "; ".join(notes))
        else:
            desc = subject.get("description_en") or subject.get("description")
            if desc:
                lines.append(f"- {desc}")
    return lines


def manga_panel_composition_lines(panel: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    comp = panel.get("composition") or {}
    camera = panel.get("camera") or {}
    for label, value in (
        ("Layout", comp.get("layout_en") or comp.get("layout")),
        ("Framing", comp.get("framing_en") or comp.get("framing")),
        ("Focus", comp.get("focus_en") or comp.get("focus")),
        ("Perspective", comp.get("perspective_en") or comp.get("perspective")),
        ("Camera", camera.get("angle_en") or camera.get("angle")),
    ):
        if value:
            lines.append(f"- {label}: {value}")
    return lines


def manga_panel_lighting_lines(panel: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    lighting = panel.get("lighting") or {}
    for label, value in (
        ("Direction", lighting.get("direction_en") or lighting.get("direction")),
        ("Quality", lighting.get("quality_en") or lighting.get("quality")),
        ("Mood effect", lighting.get("mood_effect_en") or lighting.get("mood_effect")),
    ):
        if value:
            lines.append(f"- {label}: {value}")
    mood = panel.get("mood_atmosphere_en") or panel.get("mood_atmosphere")
    if mood:
        lines.append("- Mood: " + ", ".join(str(x) for x in as_list(mood) if x))
    return lines


def manga_panel_text_lines(panel: dict[str, Any]) -> list[str]:
    text = panel.get("text") or {}
    if not isinstance(text, dict):
        return []
    lines: list[str] = []
    for key in ("dialogue", "monologue", "narration", "sfx"):
        for item in as_list(text.get(key)):
            if isinstance(item, dict):
                content = item.get("text") or item.get("content")
                speaker = item.get("speaker") or item.get("character_id")
                if content and speaker:
                    lines.append(f"- {key}: {speaker}: {content}")
                elif content:
                    lines.append(f"- {key}: {content}")
            elif item:
                lines.append(f"- {key}: {item}")
    return lines


def background_brief_header() -> str:
    return (
        "Draw a background reference image for Japanese manga production. "
        "Do not make people or character close-ups the main subject."
    )


def background_environment_lines(
    concept: dict[str, Any],
    *,
    page_num: int,
    scene_location: str,
    scene_time: str,
    scene_background_notes: str,
) -> list[str]:
    title = str(concept.get("title") or concept.get("concept_id") or "")
    description = str(concept.get("description") or "")
    prompt = str(concept.get("prompt") or description)
    lines: list[str] = []
    if title:
        lines.append(f"- Page {page_num} / {title}")
    if scene_location or scene_time:
        lines.append(
            f"- Setting: {scene_location or 'unspecified'} / "
            f"{scene_time or 'unspecified'}"
        )
    if scene_background_notes:
        lines.append(f"- Shared background: {scene_background_notes}")
    if description:
        lines.append(f"- Scene note: {description}")
    if prompt:
        lines.append(f"- Visual direction: {prompt}")
    usage = concept.get("usage")
    if usage:
        lines.append(f"- Intended use: {usage}")
    return lines


def background_camera_lines(concept: dict[str, Any]) -> list[str]:
    concept_id = str(concept.get("concept_id") or "").lower()
    lines: list[str] = []
    for keyword, label in (
        ("establishing", "establishing wide shot"),
        ("wide", "wide environmental shot"),
        ("close", "close background detail"),
        ("reverse", "reverse angle"),
        ("overhead", "overhead / top-down view"),
    ):
        if keyword in concept_id:
            lines.append(f"- Shot type: {label}")
    provider_hint = concept.get("provider_hint")
    if provider_hint:
        lines.append(f"- Provider note: {provider_hint}")
    return lines


def background_lighting_lines(page: dict[str, Any], concept: dict[str, Any]) -> list[str]:
    scene = page.get("scene") or {}
    lines: list[str] = []
    for label, key in (
        ("Lighting", "lighting_en"),
        ("Lighting", "lighting"),
        ("Atmosphere", "atmosphere_en"),
        ("Atmosphere", "atmosphere"),
    ):
        value = scene.get(key)
        if value:
            lines.append(f"- {label}: {value}")
    prompt = str(concept.get("prompt") or "")
    lowered = prompt.lower()
    for token, label in (
        ("midnight", "night lighting"),
        ("night", "night lighting"),
        ("glow", "localized glow"),
        ("sunlight", "daylight"),
        ("backlight", "backlight"),
    ):
        if token in lowered:
            lines.append(f"- Light cue: {label}")
    return unique(lines)


def background_mood_lines(concept: dict[str, Any]) -> list[str]:
    description = str(concept.get("description") or "")
    if not description:
        return []
    return [f"- Mood: {description}"]


def background_exclude_people_lines() -> list[str]:
    return bullet_lines(
        [
            "no people in foreground",
            "no character close-up",
            "no human figures as main subject",
            "environment and spatial design only",
        ]
    )


def background_do_not_include_lines(
    page: dict[str, Any],
    concept: dict[str, Any],
    negative_prompt: str,
) -> list[str]:
    items: list[str] = []
    items.extend(split_prompt_fragments(negative_prompt))
    items.extend(str(x) for x in as_list(concept.get("negative_tags")) if x)
    items.extend(
        [
            "people",
            "character",
            "portrait",
            "crowd",
        ]
    )
    instruction = page.get("render_instruction") or {}
    directives = instruction.get("user_directives") or {}
    defaults = directives.get("defaults") or {}
    items.extend(str(x) for x in as_list(defaults.get("omit_prompt_tags")) if x)
    return bullet_lines(unique(items), limit=24)


def format_background_prompt(
    page: dict[str, Any],
    concept: dict[str, Any],
    *,
    page_num: int,
    scene_location: str,
    scene_time: str,
    scene_background_notes: str,
    legacy_prompt: str,
    negative_prompt: str,
    formatter: str,
) -> PromptBundle:
    if formatter not in VALID_FORMATTERS:
        raise ValueError(f"unknown prompt formatter: {formatter}")
    if formatter != BACKGROUND_BRIEF:
        return PromptBundle(
            prompt=legacy_prompt,
            negative_prompt=negative_prompt,
            formatter=formatter,
            negative_mode=NATIVE_NEGATIVE,
        )

    prompt_parts: list[str] = [
        background_brief_header(),
        named_section(
            "Environment",
            background_environment_lines(
                concept,
                page_num=page_num,
                scene_location=scene_location,
                scene_time=scene_time,
                scene_background_notes=scene_background_notes,
            ),
        ),
        named_section("Camera", background_camera_lines(concept)),
        named_section("Lighting", background_lighting_lines(page, concept)),
        named_section("Mood", background_mood_lines(concept)),
        named_section("Exclude people", background_exclude_people_lines()),
        named_section(
            "Do not include",
            background_do_not_include_lines(page, concept, negative_prompt),
        ),
    ]
    prompt = "\n\n".join(part for part in prompt_parts if part)
    return PromptBundle(
        prompt=prompt,
        negative_prompt="",
        formatter=formatter,
        negative_mode=INLINE_DO_NOT_INCLUDE,
    )


def format_manga_panel_prompt(
    page: dict[str, Any],
    panel: dict[str, Any],
    *,
    tag_prompt: str,
    negative_prompt: str,
    formatter: str,
    style_prefix: str = "",
) -> PromptBundle:
    if formatter not in VALID_FORMATTERS:
        raise ValueError(f"unknown prompt formatter: {formatter}")
    if formatter in {TAG_CSV, NOVELAI_PIPE}:
        return PromptBundle(
            prompt=style_prefix + tag_prompt,
            negative_prompt=negative_prompt,
            formatter=formatter,
            negative_mode=NATIVE_NEGATIVE,
        )
    if formatter != NATURAL_SECTIONS:
        return PromptBundle(
            prompt=style_prefix + tag_prompt,
            negative_prompt=negative_prompt,
            formatter=formatter,
            negative_mode=NATIVE_NEGATIVE,
        )

    prompt_parts: list[str] = [
        manga_panel_header(),
        named_section("Panel Context", manga_panel_context_lines(page, panel)),
        named_section("Characters", manga_panel_character_lines(page, panel)),
        named_section("Composition", manga_panel_composition_lines(panel)),
        named_section("Lighting and Mood", manga_panel_lighting_lines(panel)),
        named_section("Text Elements", manga_panel_text_lines(panel)),
    ]
    tag_hints = split_prompt_fragments(tag_prompt.replace("|", ","))
    if tag_hints:
        prompt_parts.append(named_section("Visual Tag Hints", bullet_lines(tag_hints, limit=36)))
    prompt_parts.append(named_section("Do not include", do_not_include_lines(page, negative_prompt)))

    prompt = "\n\n".join(part for part in prompt_parts if part)
    return PromptBundle(
        prompt=prompt,
        negative_prompt="",
        formatter=formatter,
        negative_mode=INLINE_DO_NOT_INCLUDE,
    )


def default_formatter_for_provider(provider: str, source: str) -> str:
    if provider == "novelai":
        return NOVELAI_PIPE if source == "step1-panels" else TAG_CSV
    if provider in {"grok", "grok_pro", "openai", "openrouter"}:
        if source in {"step1-pages", "step2-pages"}:
            return MANGA_PAGE_INSTRUCTION
        if source == "background-concepts":
            return BACKGROUND_BRIEF
        return NATURAL_SECTIONS
    return TAG_CSV


def resolve_prompt_formatter(
    provider: str,
    source: str,
    *,
    provider_cfg: dict[str, Any] | None = None,
    cli_formatter: str | None = None,
) -> str:
    if cli_formatter:
        if cli_formatter not in VALID_FORMATTERS:
            raise ValueError(f"unknown prompt formatter: {cli_formatter}")
        return cli_formatter

    cfg = (provider_cfg or {}).get("prompt_formatter")
    if isinstance(cfg, dict):
        value = cfg.get(source, cfg.get("default"))
        if value:
            value_s = str(value)
            if value_s not in VALID_FORMATTERS:
                raise ValueError(f"unknown prompt formatter in config: {value_s}")
            return value_s

    return default_formatter_for_provider(provider, source)


def provider_config_from_root(root: Path, provider: str) -> dict[str, Any]:
    config_path = root / "config" / "image_generation.json"
    if not config_path.is_file():
        return {}
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    providers = raw.get("providers") if isinstance(raw, dict) else None
    if not isinstance(providers, dict):
        return {}
    cfg = providers.get(provider)
    return cfg if isinstance(cfg, dict) else {}
