from __future__ import annotations

import json
from dataclasses import dataclass, field

from ..schemas.character import CharacterPrompt
from ..schemas.manga_page import MangaPagePrompt, Panel, StructuredText


@dataclass(frozen=True)
class RenderedPrompt:
    prompt: str
    tags: list[str] = field(default_factory=list)
    negative_tags: list[str] = field(default_factory=list)
    text_elements: list[dict[str, str | int]] = field(default_factory=list)


def render_page_prompt(
    page: MangaPagePrompt,
    characters: dict[str, CharacterPrompt] | None = None,
) -> RenderedPrompt:
    characters = characters or {}
    tags = _unique(page.manga.genre_tags + page.manga.visual_tags)
    negative_tags = list(page.technical.negative_tags)
    instruction = page.render_instruction
    parts = [
        instruction.prompt_header or instruction.task,
        f"panel policy: {instruction.panel_policy}" if instruction.panel_policy else "",
        f"character policy: {instruction.character_policy}" if instruction.character_policy else "",
        f"text policy: {instruction.text_policy}" if instruction.text_policy else "",
        f"output policy: {instruction.output_policy}" if instruction.output_policy else "",
        *[f"note: {note}" for note in instruction.notes],
        f"{page.meta.intent}, {page.meta.reading_order.value}, aspect ratio {page.meta.aspect_ratio}",
        _scene_to_text(page.scene),
        f"style: {', '.join(tags)}" if tags else "",
        f"layout: {page.manga.panel_layout}" if page.manga.panel_layout else "",
        f"text policy: {page.manga.text_policy}",
        "lettering: "
        f"{page.manga.lettering.direction} Japanese writing, "
        f"base font size {page.manga.lettering.base_font_size}, "
        f"{page.manga.lettering.size_policy}",
    ]

    panel_parts: list[str] = []
    for panel in page.panels:
        panel_parts.append(_panel_to_text(panel, characters))
        tags.extend(panel.prompt_tags)
        for subject in panel.subjects:
            snapshot = _subject_snapshot(page, subject, characters)
            if snapshot:
                tags.extend(snapshot.fixed_tags)
                tags.extend(snapshot.variant_tags)
            elif subject.character_id and subject.character_id in characters:
                character = characters[subject.character_id]
                tags.extend(_subject_character_tags(character, subject))
                negative_tags.extend(character.negative_tags)

    prompt = "\n".join([part for part in parts if part] + panel_parts)
    return RenderedPrompt(
        prompt=prompt,
        tags=_unique(tags),
        negative_tags=_unique(negative_tags),
        text_elements=extract_text_elements(page),
    )


def extract_text_elements(page: MangaPagePrompt) -> list[dict[str, str | int]]:
    elements: list[dict[str, str | int]] = []
    for panel in page.panels:
        for item in panel.text.dialogue:
            element = {
                "panel_id": panel.panel_id,
                "type": "dialogue",
                "speaker": item.speaker,
                "content": item.content,
                "placement": _placement_text(item.placement),
                "writing_direction": item.writing_direction or page.manga.lettering.direction,
            }
            if item.text_id:
                element["text_id"] = item.text_id
            elements.append(element)
        for item in panel.text.monologue:
            elements.append(
                _structured_text_element(
                    panel.panel_id,
                    "monologue",
                    item,
                    default_direction=page.manga.lettering.direction,
                )
            )
        for item in panel.text.narration:
            elements.append(
                _structured_text_element(
                    panel.panel_id,
                    "narration",
                    item,
                    default_direction=page.manga.lettering.direction,
                )
            )
        for item in panel.text.sfx:
            element = {
                "panel_id": panel.panel_id,
                "type": "sfx",
                "content": item.content,
                "placement": _placement_text(item.placement),
                "meaning": item.meaning or "",
                "writing_direction": item.writing_direction or page.manga.lettering.direction,
            }
            if item.text_id:
                element["text_id"] = item.text_id
            elements.append(element)
    return elements


def _structured_text_content(item: str | StructuredText) -> str:
    return item.content if isinstance(item, StructuredText) else item


def _placement_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value.model_dump(), ensure_ascii=False, sort_keys=True)


def _structured_text_element(
    panel_id: int,
    kind: str,
    item: str | StructuredText,
    *,
    default_direction: str,
) -> dict[str, str | int]:
    element: dict[str, str | int] = {
        "panel_id": panel_id,
        "type": kind,
        "content": _structured_text_content(item),
    }
    if isinstance(item, StructuredText):
        if item.text_id:
            element["text_id"] = item.text_id
        if item.placement is not None:
            element["placement"] = _placement_text(item.placement)
        element["writing_direction"] = item.writing_direction or default_direction
    return element


def _scene_to_text(scene) -> str:
    bits = [scene.location, scene.time_of_day, scene.weather, scene.era, scene.background_notes]
    return "scene: " + ", ".join(str(bit) for bit in bits if bit)


def _panel_to_text(panel: Panel, characters: dict[str, CharacterPrompt]) -> str:
    subject_parts: list[str] = []
    for subject in panel.subjects:
        label = subject.description
        if subject.character_id and subject.character_id in characters:
            character = characters[subject.character_id]
            label = f"{character.name_en or character.name} ({subject.description})"
        details = [
            label,
            subject.pose_action,
            subject.expression,
            subject.position.value,
        ]
        subject_parts.append(", ".join(str(item) for item in details if item))

    scene_text = _scene_to_text(panel.scene) if panel.scene else ""
    composition = ", ".join(
        str(item)
        for item in [
            panel.composition.framing,
            panel.composition.layout,
            panel.composition.focus,
            panel.composition.perspective,
            panel.camera.angle,
            panel.camera.shot_size,
            panel.lighting.quality,
        ]
        if item
    )
    return (
        f"panel {panel.panel_id}: {panel.summary}\n"
        f"- subjects: {'; '.join(subject_parts)}\n"
        f"- {scene_text}\n"
        f"- composition: {composition}\n"
        f"- mood: {', '.join(panel.mood_atmosphere)}"
    )


def _subject_snapshot(page: MangaPagePrompt, subject, characters: dict[str, CharacterPrompt]):
    if not subject.character_id:
        return None
    variant_id = _subject_variant_id(subject)
    fallback = None
    character = characters.get(subject.character_id)
    require_exact = character is not None and character.schema_version == "1.1"
    for snapshot in page.character_snapshots:
        if snapshot.character_id != subject.character_id:
            continue
        if snapshot.selected_variant_id == variant_id:
            return snapshot
        if snapshot.selected_variant_id is None:
            fallback = snapshot
    if require_exact:
        raise ValueError(
            f"snapshot が (character_id, selected_variant_id) と一致しません: "
            f"{subject.character_id}/{variant_id}"
        )
    return fallback


def _subject_variant_id(subject) -> str | None:
    declared = [
        str(value).strip()
        for value in (subject.prompt_variant_id, subject.costume_variant, subject.variant_id)
        if value and str(value).strip()
    ]
    unique = list(dict.fromkeys(declared))
    if len(unique) > 1:
        raise ValueError(
            "prompt_variant_id / costume_variant / variant_id が食い違っています: "
            + ", ".join(unique)
        )
    return unique[0] if unique else None


def _subject_character_tags(character: CharacterPrompt, subject) -> list[str]:
    variant_id = _subject_variant_id(subject)
    return character.variant_danbooru_tags(variant_id)


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))
