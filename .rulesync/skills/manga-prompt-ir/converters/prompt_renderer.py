from __future__ import annotations

from dataclasses import dataclass, field

from schemas.character import CharacterPrompt
from schemas.manga_page import MangaPagePrompt, Panel


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
    parts = [
        f"{page.meta.intent}, {page.meta.reading_order.value}, aspect ratio {page.meta.aspect_ratio}",
        _scene_to_text(page.scene),
        f"style: {', '.join(tags)}" if tags else "",
        f"layout: {page.manga.panel_layout}" if page.manga.panel_layout else "",
        f"text policy: {page.manga.text_policy}",
    ]

    panel_parts: list[str] = []
    for panel in page.panels:
        panel_parts.append(_panel_to_text(panel, characters))
        for subject in panel.subjects:
            if subject.character_id and subject.character_id in characters:
                character = characters[subject.character_id]
                tags.extend(character.fixed_prompt_tags())
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
            elements.append(
                {
                    "panel_id": panel.panel_id,
                    "type": "dialogue",
                    "speaker": item.speaker,
                    "content": item.content,
                    "placement": item.placement or "",
                }
            )
        for item in panel.text.monologue:
            elements.append({"panel_id": panel.panel_id, "type": "monologue", "content": item})
        for item in panel.text.narration:
            elements.append({"panel_id": panel.panel_id, "type": "narration", "content": item})
        for item in panel.text.sfx:
            elements.append(
                {
                    "panel_id": panel.panel_id,
                    "type": "sfx",
                    "content": item.content,
                    "placement": item.placement or "",
                    "meaning": item.meaning or "",
                }
            )
    return elements


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


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))
