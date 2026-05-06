from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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


class TagPolicy(BaseModel):
    """`prompt_tags` への必須追加・除外の指示。

    ページ全体の既定値（`UserDirectives.defaults`）と、コマごとの上書き
    （`Panel.required_prompt_tags` / `Panel.omit_prompt_tags`）の両方で同じ
    意味を持たせるため、ここでは「ポジ側 prompt_tags のみ」を扱う。
    negative 側はコマ単位の `Panel.negative_tags` / `omit_negative_tags` を
    既存どおり用い、ここでは触らない。
    """

    model_config = ConfigDict(extra="forbid")

    required_prompt_tags: list[str] = Field(default_factory=list)
    omit_prompt_tags: list[str] = Field(default_factory=list)


class UserDirectives(BaseModel):
    """ページ単位のユーザ指示の正本。

    品質修正・再生成のときに「指示の軸」がぶれないよう、ページごとの
    自由記述（`page_notes`）と、全コマへ波及させるタグ既定（`defaults`）を
    まとめてここで保持する。
    """

    model_config = ConfigDict(extra="forbid")

    page_notes: list[str] = Field(default_factory=list)
    defaults: TagPolicy = Field(default_factory=TagPolicy)


class RenderInstruction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task: str = "Create one complete manga page from this YAML."
    prompt_header: str | None = None
    panel_policy: str | None = None
    character_policy: str | None = None
    text_policy: str | None = None
    output_policy: str | None = None
    notes: list[str] = Field(default_factory=list)
    user_directives: UserDirectives = Field(default_factory=UserDirectives)


class Scene(BaseModel):
    model_config = ConfigDict(extra="forbid")

    location: str
    time_of_day: str | None = None
    weather: str | None = None
    era: str | None = None
    background_notes: str | None = None
    # txt2img / タグ行は *_en のみ使用（scene_prompt）。日本語キーは編集用。
    location_en: str | None = None
    time_of_day_en: str | None = None
    weather_en: str | None = None
    background_notes_en: str | None = None

    @staticmethod
    def _has_text(value: str | None) -> bool:
        return bool(value and str(value).strip())

    @model_validator(mode="after")
    def english_prompt_fields_required(self) -> Scene:
        """タグ・バッチで日本語にフォールバックしないため、英語フィールドを検証する。"""
        if not self._has_text(self.location_en):
            raise ValueError(
                "scene.location_en は必須です（非空）。txt2img 用タグは location にフォールバックしません。"
            )
        if self._has_text(self.background_notes) and not self._has_text(self.background_notes_en):
            raise ValueError(
                "scene.background_notes を書いた場合は scene.background_notes_en も必須です。"
            )
        if self._has_text(self.time_of_day) and not self._has_text(self.time_of_day_en):
            raise ValueError(
                "scene.time_of_day を書いた場合は scene.time_of_day_en も必須です。"
            )
        if self._has_text(self.weather) and not self._has_text(self.weather_en):
            raise ValueError(
                "scene.weather を書いた場合は scene.weather_en も必須です。"
            )
        return self


class BackgroundConcept(BaseModel):
    model_config = ConfigDict(extra="forbid")

    concept_id: str
    title: str
    description: str
    prompt: str
    negative_tags: list[str] = Field(default_factory=list)
    provider_hint: str | None = "grok"
    usage: str | None = None


class Subject(BaseModel):
    model_config = ConfigDict(extra="forbid")

    character_id: str | None = None
    variant_id: str | None = None
    prompt_variant_id: str | None = None
    costume_variant: str | None = None
    description: str
    description_en: str | None = None
    tag_token: str | None = None
    type: str = "human"
    pose_action: str | None = None
    pose_action_en: str | None = None
    position: Position = Position.midground
    expression: str | None = None
    expression_en: str | None = None


class CharacterSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    character_id: str
    name: str | None = None
    name_en: str | None = None
    selected_variant_id: str | None = None
    appearance_summary: str | None = None
    costume_summary: str | None = None
    fixed_tags: list[str] = Field(default_factory=list)
    variant_tags: list[str] = Field(default_factory=list)
    do_not_change: list[str] = Field(default_factory=list)


class Composition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    framing: str | None = None
    framing_en: str | None = None
    layout: str | None = None
    layout_en: str | None = None
    focus: str | None = None
    focus_en: str | None = None
    perspective: str | None = None
    perspective_en: str | None = None


class Camera(BaseModel):
    model_config = ConfigDict(extra="forbid")

    angle: str | None = None
    angle_en: str | None = None
    lens: str | None = None
    lens_en: str | None = None
    depth_of_field: str | None = None
    depth_of_field_en: str | None = None
    shot_size: str | None = None
    shot_size_en: str | None = None


class Lighting(BaseModel):
    model_config = ConfigDict(extra="forbid")

    direction: str | None = None
    direction_en: str | None = None
    quality: str | None = None
    quality_en: str | None = None
    mood_effect: str | None = None
    mood_effect_en: str | None = None


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
    # ページ生成（互換 Step2 行）向け。未設定なら summary を代用（tools: panel_step2_description）
    step2_summary: str | None = None
    scene: Scene | None = None
    subjects: list[Subject]
    composition: Composition = Field(default_factory=Composition)
    camera: Camera = Field(default_factory=Camera)
    lighting: Lighting = Field(default_factory=Lighting)
    text: PanelText = Field(default_factory=PanelText)
    mood_atmosphere: list[str] = Field(default_factory=list)
    mood_atmosphere_en: list[str] = Field(default_factory=list)
    prompt_tags: list[str] = Field(default_factory=list)
    # ページ単位の `render_instruction.user_directives.defaults` と合算され、
    # 最終タグ列で「必ず含める」「必ず除外する」を強制適用するためのコマ別上書き。
    required_prompt_tags: list[str] = Field(default_factory=list)
    omit_prompt_tags: list[str] = Field(default_factory=list)
    # step1-panels（コマ単位 txt2img）向け。technical.negative_tags と CLI の共通ネガに加え、コマ別で増減する。
    negative_tags: list[str] = Field(default_factory=list)
    omit_negative_tags: list[str] = Field(default_factory=list)
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
    render_instruction: RenderInstruction = Field(default_factory=RenderInstruction)
    manga: MangaStyle
    scene: Scene
    character_ids: list[str] = Field(default_factory=list)
    character_snapshots: list[CharacterSnapshot] = Field(default_factory=list)
    background_concepts: list[BackgroundConcept] = Field(default_factory=list)
    panels: list[Panel]
    color_palette: ColorPalette = Field(default_factory=ColorPalette)
    technical: Technical = Field(default_factory=Technical)

    @field_validator("panels")
    @classmethod
    def require_panels(cls, value: list[Panel]) -> list[Panel]:
        if not value:
            raise ValueError("manga page must contain at least one panel")
        return value
