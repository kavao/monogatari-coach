from __future__ import annotations

from enum import Enum
import re
from typing import Any, Literal

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

    intent: Literal["manga_page", "manga_panel", "illustration"]
    reading_order: ReadingOrder = ReadingOrder.rtl
    aspect_ratio: str = "2:3"
    page_count: int = 1
    source_text: str | None = None
    source_anchor: str | None = None
    illustration_type: str | None = None


class LetteringStyle(BaseModel):
    """Page-level lettering defaults used by the local lettering pass."""

    model_config = ConfigDict(extra="forbid")

    direction: Literal["vertical", "horizontal"] = "vertical"
    base_font_size: int = Field(default=30, ge=12, le=512)
    size_policy: Literal["uniform_then_shrink"] = "uniform_then_shrink"


class MangaStyle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    genre_tags: list[str] = Field(default_factory=list)
    visual_tags: list[str] = Field(default_factory=list)
    line_art: str | None = None
    screentone: str | None = None
    panel_layout: str | None = None
    text_policy: str = "Japanese text must be legible"
    lettering: LetteringStyle = Field(default_factory=LetteringStyle)


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
    text_mode: Literal["generate", "letter_later", "none"] | None = None
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

    subject_id: str | None = None
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


_CJK_RE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]")


def _requires_english(value: str | None) -> bool:
    return bool(value and _CJK_RE.search(value))


def _raw_text_policy_mode(value: Any) -> str | None:
    text = str(value or "").strip().lower()
    if not text:
        return None
    modes: set[str] = set()
    if any(token in text for token in ("no text", "without text", "文字なし", "文字を描かない")):
        modes.add("none")
    if any(token in text for token in ("letter later", "lettering later", "後載せ", "空吹き出し")):
        modes.add("letter_later")
    if any(
        token in text
        for token in (
            "legible",
            "readable",
            "render text",
            "日本語",
            "可読",
            "正確な文言",
            "文字を入れ",
            "文字を描",
        )
    ):
        modes.add("generate")
    if len(modes) > 1:
        raise ValueError("text_policyが複数の文字方針に衝突しています")
    return next(iter(modes), None)


class Dramaturgy(BaseModel):
    """Optional 1.1 page/panel intent; English is required for Japanese prose."""

    model_config = ConfigDict(extra="forbid")

    role: str | None = None
    purpose: str | None = None
    purpose_en: str | None = None
    emotional_arc: str | None = None
    emotional_arc_en: str | None = None
    relation_to_previous: str | None = None
    relation_to_previous_en: str | None = None

    @model_validator(mode="after")
    def english_fields_pair(self) -> "Dramaturgy":
        for label, value, english in (
            ("purpose", self.purpose, self.purpose_en),
            ("emotional_arc", self.emotional_arc, self.emotional_arc_en),
            ("relation_to_previous", self.relation_to_previous, self.relation_to_previous_en),
        ):
            if _requires_english(value) and not english:
                raise ValueError(f"dramaturgy.{label} に日本語を記載した場合は {label}_en が必須です")
        return self


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
    view: str | None = None
    view_en: str | None = None


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
    text_id: str | None = None
    bubble_type: str | None = None
    placement: str | TextPlacement | None = None
    writing_direction: Literal["horizontal", "vertical"] | None = None


class SoundEffect(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str
    text_id: str | None = None
    placement: str | TextPlacement | None = None
    writing_direction: Literal["horizontal", "vertical"] | None = None
    style: str | None = None
    meaning: str | None = None


class TextPlacement(BaseModel):
    """Optional normalized placement used by schema 1.1 text entries."""

    model_config = ConfigDict(extra="forbid")

    x: float | None = None
    y: float | None = None
    w: float | None = None
    h: float | None = None
    anchor: str | None = None
    writing_direction: Literal["horizontal", "vertical"] | None = None

    @model_validator(mode="after")
    def normalized_bounds(self) -> "TextPlacement":
        values = {"x": self.x, "y": self.y, "w": self.w, "h": self.h}
        if any(value is not None and not 0.0 <= value <= 1.0 for value in values.values()):
            raise ValueError("text placementのx/y/w/hは0〜1の範囲です")
        if self.w is not None and self.w <= 0:
            raise ValueError("text placementのwは0より大きくしてください")
        if self.h is not None and self.h <= 0:
            raise ValueError("text placementのhは0より大きくしてください")
        if self.x is not None and self.w is not None and self.x + self.w > 1:
            raise ValueError("text placementのx+wは1以下です")
        if self.y is not None and self.h is not None and self.y + self.h > 1:
            raise ValueError("text placementのy+hは1以下です")
        return self


class StructuredText(BaseModel):
    """Structured form for legacy narration/monologue strings."""

    model_config = ConfigDict(extra="forbid")

    text_id: str | None = None
    content: str
    placement: str | TextPlacement | None = None
    writing_direction: Literal["horizontal", "vertical"] | None = None


class PanelText(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dialogue: list[Dialogue] = Field(default_factory=list)
    narration: list[str | StructuredText] = Field(default_factory=list)
    monologue: list[str | StructuredText] = Field(default_factory=list)
    sfx: list[SoundEffect] = Field(default_factory=list)


class Panel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    panel_id: int
    summary: str
    # コマ要約の英語（エージェント同時翻訳が主経路。任意で novel_manga_panel_summary_en.py）。NovelAI step1-panels でタグと併用。
    summary_en: str | None = None
    # 翻訳元の summary 原文（鮮度チェック用）。エージェントまたは翻訳ツールが summary と同値で更新する。
    summary_en_source: str | None = None
    # ページ生成（互換 Step2 行）向け。未設定なら summary を代用（tools: panel_step2_description）
    step2_summary: str | None = None
    scene: Scene | None = None
    subjects: list[Subject]
    dramaturgy: Dramaturgy | None = None
    background_density: str | None = None
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


class GeometryRect(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x: float
    y: float
    w: float
    h: float

    @model_validator(mode="after")
    def normalized_bounds(self) -> "GeometryRect":
        values = {"x": self.x, "y": self.y, "w": self.w, "h": self.h}
        if any(not 0.0 <= value <= 1.0 for value in values.values()):
            raise ValueError("layout_geometryのx/y/w/hは0〜1の範囲です")
        if self.w <= 0 or self.h <= 0:
            raise ValueError("layout_geometryのw/hは0より大きくしてください")
        if self.x + self.w > 1 or self.y + self.h > 1:
            raise ValueError("layout_geometryの矩形がページ範囲を超えています")
        return self


class LayoutPanel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    panel_id: int
    rect: GeometryRect


class LayoutGeometry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    panels: list[LayoutPanel]


class ContinuityTrack(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity_id: str
    panel_id: int
    state: str
    intentional_change: bool = False
    change_note: str | None = None


class AssetReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_id: str
    role: str
    path: str | None = None
    character_id: str | None = None
    variant_id: str | None = None
    concept_id: str | None = None


class MangaPagePrompt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0", "1.1"] = "1.0"
    meta: MangaMeta
    render_instruction: RenderInstruction = Field(default_factory=RenderInstruction)
    manga: MangaStyle
    scene: Scene
    dramaturgy: Dramaturgy | None = None
    layout_geometry: LayoutGeometry | None = None
    continuity_tracks: list[ContinuityTrack] = Field(default_factory=list)
    asset_references: list[AssetReference] = Field(default_factory=list)
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

    @model_validator(mode="after")
    def apply_lettering_defaults(self) -> "MangaPagePrompt":
        """Resolve omitted per-item directions from the page lettering style."""
        direction = self.manga.lettering.direction
        for panel in self.panels:
            for item in panel.text.dialogue:
                if item.writing_direction is None:
                    item.writing_direction = direction
            for item in panel.text.sfx:
                if item.writing_direction is None:
                    item.writing_direction = direction
            for collection in (panel.text.monologue, panel.text.narration):
                for item in collection:
                    if isinstance(item, StructuredText) and item.writing_direction is None:
                        item.writing_direction = direction
        return self

    @model_validator(mode="before")
    @classmethod
    def keep_schema_1_0_closed(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        schema_version = str(value.get("schema_version", "1.0"))
        if schema_version == "1.1":
            instruction = value.get("render_instruction")
            manga = value.get("manga")
            declared: list[tuple[str, str]] = []
            if isinstance(manga, dict) and "text_policy" in manga:
                kind = _raw_text_policy_mode(manga.get("text_policy"))
                if kind:
                    declared.append(("manga.text_policy", kind))
            if isinstance(instruction, dict) and "text_policy" in instruction:
                kind = _raw_text_policy_mode(instruction.get("text_policy"))
                if kind:
                    declared.append(("render_instruction.text_policy", kind))
            kinds = {kind for _path, kind in declared}
            if len(kinds) > 1:
                detail = ", ".join(f"{path}={kind}" for path, kind in declared)
                raise ValueError(f"text_policyが衝突しています: {detail}")
            requested = instruction.get("text_mode") if isinstance(instruction, dict) else None
            if requested and kinds and next(iter(kinds)) != requested:
                detail = ", ".join(f"{path}={kind}" for path, kind in declared)
                raise ValueError(f"text_mode={requested!r}とtext_policyが衝突しています: {detail}")
            return value
        if schema_version != "1.0":
            return value
        versioned_keys = {
            "dramaturgy",
            "layout_geometry",
            "continuity_tracks",
            "asset_references",
            "text_mode",
            "subject_id",
            "background_density",
            "text_id",
            "lettering",
        }

        def find_key(node: Any, path: str = "") -> str | None:
            if isinstance(node, dict):
                for key, child in node.items():
                    if key in versioned_keys:
                        return f"{path}/{key}" if path else str(key)
                    found = find_key(child, f"{path}/{key}" if path else str(key))
                    if found:
                        return found
            elif isinstance(node, list):
                for index, child in enumerate(node):
                    found = find_key(child, f"{path}/{index}")
                    if found:
                        return found
            return None

        found = find_key(value)
        if found:
            raise ValueError(f"schema 1.0ではschema 1.1項目を使用できません: {found}")
        return value

    @model_validator(mode="after")
    def validate_schema_1_1_references(self) -> "MangaPagePrompt":
        if self.schema_version == "1.0":
            return self

        panel_ids = [panel.panel_id for panel in self.panels]
        if len(panel_ids) != len(set(panel_ids)):
            raise ValueError("schema 1.1ではpanel_idはページ内で一意でなければなりません")

        subject_ids: list[str] = []
        text_ids: list[str] = []
        for panel in self.panels:
            for subject in panel.subjects:
                if subject.subject_id:
                    subject_ids.append(subject.subject_id)
            for item in panel.text.dialogue + panel.text.sfx:
                if item.text_id:
                    text_ids.append(item.text_id)
            for items in (panel.text.narration, panel.text.monologue):
                for item in items:
                    if isinstance(item, StructuredText) and item.text_id:
                        text_ids.append(item.text_id)
        if len(subject_ids) != len(set(subject_ids)):
            raise ValueError("schema 1.1ではsubject_idはページ内で一意でなければなりません")
        if len(text_ids) != len(set(text_ids)):
            raise ValueError("schema 1.1ではtext_idはページ内で一意でなければなりません")

        if self.layout_geometry is not None:
            geometry_ids = [item.panel_id for item in self.layout_geometry.panels]
            unknown = sorted(set(geometry_ids) - set(panel_ids))
            missing = sorted(set(panel_ids) - set(geometry_ids))
            if unknown:
                raise ValueError(f"layout_geometryに未知のpanel_idがあります: {unknown}")
            if missing:
                raise ValueError(f"layout_geometryに未定義のpanel_idがあります: {missing}")
            if len(geometry_ids) != len(set(geometry_ids)):
                raise ValueError("layout_geometryのpanel_idは一意でなければなりません")
            if geometry_ids != panel_ids:
                raise ValueError(
                    "layout_geometryのpanels順は既存panels順と一致させ、"
                    "第二の読み順を保存しないでください"
                )
            for index, left in enumerate(self.layout_geometry.panels):
                for right in self.layout_geometry.panels[index + 1 :]:
                    if _rectangles_overlap(left.rect, right.rect):
                        raise ValueError(
                            "layout_geometryの矩形が重複しています: "
                            f"panel_id={left.panel_id} と panel_id={right.panel_id}"
                        )

        if self.continuity_tracks:
            unknown_track_panels = sorted(
                {track.panel_id for track in self.continuity_tracks} - set(panel_ids)
            )
            if unknown_track_panels:
                raise ValueError(
                    f"continuity_tracksに未知のpanel_idがあります: {unknown_track_panels}"
                )
        if len(self.asset_references) != len({ref.asset_id for ref in self.asset_references}):
            raise ValueError("schema 1.1ではasset_idはページ内で一意でなければなりません")

        known_character_ids = set(self.character_ids)
        known_character_ids.update(
            subject.character_id
            for panel in self.panels
            for subject in panel.subjects
            if subject.character_id
        )
        known_character_ids.update(snapshot.character_id for snapshot in self.character_snapshots)

        known_variant_ids: dict[str, set[str]] = {}
        for panel in self.panels:
            for subject in panel.subjects:
                if not subject.character_id:
                    continue
                selected_variant = next(
                    (
                        value
                        for value in (
                            subject.prompt_variant_id,
                            subject.costume_variant,
                            subject.variant_id,
                        )
                        if value
                    ),
                    None,
                )
                if selected_variant:
                    known_variant_ids.setdefault(subject.character_id, set()).add(selected_variant)
        for snapshot in self.character_snapshots:
            if snapshot.selected_variant_id:
                known_variant_ids.setdefault(snapshot.character_id, set()).add(
                    snapshot.selected_variant_id
                )

        known_concept_ids = {concept.concept_id for concept in self.background_concepts}
        for reference in self.asset_references:
            if reference.character_id and reference.character_id not in known_character_ids:
                raise ValueError(
                    "asset_referencesに未知のcharacter_idがあります: "
                    f"{reference.character_id}"
                )
            if reference.variant_id:
                if not reference.character_id:
                    raise ValueError(
                        "asset_referencesのvariant_idにはcharacter_idが必要です: "
                        f"{reference.variant_id}"
                    )
                if reference.variant_id not in known_variant_ids.get(reference.character_id, set()):
                    raise ValueError(
                        "asset_referencesにページ内で解決できないvariant_idがあります: "
                        f"{reference.character_id}/{reference.variant_id}"
                    )
            if reference.concept_id and reference.concept_id not in known_concept_ids:
                raise ValueError(
                    "asset_referencesに未知のconcept_idがあります: "
                    f"{reference.concept_id}"
                )
        return self


def _rectangles_overlap(left: GeometryRect, right: GeometryRect) -> bool:
    horizontal = min(left.x + left.w, right.x + right.w) - max(left.x, right.x)
    vertical = min(left.y + left.h, right.y + right.h) - max(left.y, right.y)
    return horizontal > 0 and vertical > 0
