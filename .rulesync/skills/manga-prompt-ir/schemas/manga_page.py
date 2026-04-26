from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ReadingOrder(str, Enum):
    rtl = "right_to_left"
    ltr = "left_to_right"


class Position(str, Enum):
    foreground = "foreground"
    midground = "midground"
    background = "background"


class MangaMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: Literal["manga_page", "manga_panel"]
    reading_order: ReadingOrder = ReadingOrder.rtl
    aspect_ratio: str = "2:3"
    page_count: int = 1


class MangaStyle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    genre_tags: list[str] = Field(default_factory=list)
    visual_tags: list[str] = Field(default_factory=list)
    line_art: str | None = None
    screentone: str | None = None
    panel_layout: str | None = None
    text_policy: str = "Japanese text must be legible"


class Scene(BaseModel):
    model_config = ConfigDict(extra="forbid")

    location: str
    time_of_day: str | None = None
    weather: str | None = None
    era: str | None = None
    background_notes: str | None = None


class Subject(BaseModel):
    model_config = ConfigDict(extra="forbid")

    character_id: str | None = None
    description: str
    type: str = "human"
    pose_action: str | None = None
    position: Position = Position.midground
    expression: str | None = None


class Composition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    framing: str | None = None
    layout: str | None = None
    focus: str | None = None
    perspective: str | None = None


class Camera(BaseModel):
    model_config = ConfigDict(extra="forbid")

    angle: str | None = None
    lens: str | None = None
    depth_of_field: str | None = None
    shot_size: str | None = None


class Lighting(BaseModel):
    model_config = ConfigDict(extra="forbid")

    direction: str | None = None
    quality: str | None = None
    mood_effect: str | None = None


class Dialogue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    speaker: str
    content: str
    bubble_type: str | None = None
    placement: str | None = None


class SoundEffect(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str
    placement: str | None = None
    style: str | None = None
    meaning: str | None = None


class PanelText(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dialogue: list[Dialogue] = Field(default_factory=list)
    narration: list[str] = Field(default_factory=list)
    monologue: list[str] = Field(default_factory=list)
    sfx: list[SoundEffect] = Field(default_factory=list)


class Panel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    panel_id: int
    summary: str
    scene: Scene | None = None
    subjects: list[Subject]
    composition: Composition = Field(default_factory=Composition)
    camera: Camera = Field(default_factory=Camera)
    lighting: Lighting = Field(default_factory=Lighting)
    text: PanelText = Field(default_factory=PanelText)
    mood_atmosphere: list[str] = Field(default_factory=list)
    prompt_tags: list[str] = Field(default_factory=list)
    translation: str | None = None
    continuity_notes: str | None = None

    @field_validator("subjects")
    @classmethod
    def require_subjects(cls, value: list[Subject]) -> list[Subject]:
        if not value:
            raise ValueError("panel must contain at least one subject")
        return value


class ColorPalette(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["monochrome", "limited_color", "full_color"] = "monochrome"
    colors: list[str] = Field(default_factory=list)


class Technical(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resolution: str | None = None
    quality_level: str = "high"
    negative_tags: list[str] = Field(default_factory=list)


class MangaPagePrompt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    meta: MangaMeta
    manga: MangaStyle
    scene: Scene
    character_ids: list[str] = Field(default_factory=list)
    panels: list[Panel]
    color_palette: ColorPalette = Field(default_factory=ColorPalette)
    technical: Technical = Field(default_factory=Technical)

    @field_validator("panels")
    @classmethod
    def require_panels(cls, value: list[Panel]) -> list[Panel]:
        if not value:
            raise ValueError("manga page must contain at least one panel")
        return value
