"""METRON の永続データモデル。

Pydantic モデルを実行時の契約とし、YAML は ``storage.py`` 経由で保存する。
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


_SCENE_ID_PATTERN = r"^ch\d{2,}-\d{3,}$"
_BEAT_ID_PATTERN = r"^[A-Za-z][A-Za-z0-9_-]*$"

DEFAULT_SCENE_CHARS_FLOOR = 4000
INSTRUCTION_OVERSHOOT = 1.15


def instruction_target_chars(
    floor: int,
    *,
    overshoot: float = INSTRUCTION_OVERSHOOT,
) -> int:
    """検査の床より多めの指示目標を返す。生成は控えめで足りなくなるため。"""

    if floor < 1:
        raise ValueError("floor must be positive")
    if overshoot < 1:
        raise ValueError("overshoot must be at least 1")
    return max(floor, round(floor * overshoot))


class StrictModel(BaseModel):
    """未知キーを黙って捨てず、契約の typo を検出する基底モデル。"""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=True,
    )


class NarrativeDistance(str, Enum):
    CLOSE = "close"
    MEDIUM = "medium"
    SUMMARY = "summary"


class Failure(str, Enum):
    BEAT_MISSING = "BeatMissing"
    BEAT_THIN = "BeatThin"
    SUMMARY_COLLAPSE = "SummaryCollapse"
    ENDING_RUSH = "EndingRush"
    TOO_SHORT = "TooShort"
    GENERATION_TRUNCATED = "GenerationTruncated"
    POV_DRIFT = "POVDrift"
    CONTINUITY_ERROR = "ContinuityError"


class SceneState(StrictModel):
    location: str | None = None
    action: str | None = None
    emotion: str | None = None


class SceneDefinition(StrictModel):
    id: str = Field(pattern=_SCENE_ID_PATTERN)
    pov: str = Field(min_length=1)
    narrative_distance: NarrativeDistance = NarrativeDistance.CLOSE
    chronos_span: tuple[str, str] | None = None
    start_state: SceneState | None = None
    end_state: SceneState | None = None
    forbidden: list[str] = Field(default_factory=list)


class SceneContract(StrictModel):
    scene: SceneDefinition


class BeatBudget(StrictModel):
    paragraphs: tuple[int, int | None]
    dialogue_turns: tuple[int, int | None]
    sensory: int = Field(ge=0)
    interiority: int = Field(ge=0)
    new_facts: int = Field(ge=0)
    chars_hint: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_ranges(self) -> "BeatBudget":
        for lower, upper in (self.paragraphs, self.dialogue_turns):
            if lower < 0 or (upper is not None and upper < lower):
                raise ValueError("budget range must be non-negative and ordered")
        return self


class PromptBudget(StrictModel):
    """Writer に渡す離散要素予算と分量の床・指示目標。"""

    paragraphs: tuple[int, int | None]
    dialogue_turns: tuple[int, int | None]
    sensory: int = Field(ge=0)
    interiority: int = Field(ge=0)
    new_facts: int = Field(ge=0)
    chars_floor: int = Field(gt=0)
    chars_instruction: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_instruction_at_least_floor(self) -> "PromptBudget":
        if self.chars_instruction < self.chars_floor:
            raise ValueError("chars_instruction must be at least chars_floor")
        return self


class Beat(StrictModel):
    id: str = Field(pattern=_BEAT_ID_PATTERN)
    type: Literal["action", "dialogue", "discovery", "hook", "transition"]
    intent: str = Field(min_length=1)
    weight: Literal["light", "normal", "heavy"] = "normal"
    isolated: bool = False
    budget: BeatBudget


class GenerationSpec(StrictModel):
    granularity: Literal["scene", "beat", "auto"] = "auto"
    chars_floor: int = Field(default=DEFAULT_SCENE_CHARS_FLOOR, ge=1)


class BeatPlan(StrictModel):
    generation: GenerationSpec = Field(default_factory=GenerationSpec)
    beats: list[Beat] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_ids(self) -> "BeatPlan":
        ids = [beat.id for beat in self.beats]
        if len(ids) != len(set(ids)):
            raise ValueError("Beat IDs must be unique")
        return self


class GeneratorInfo(StrictModel):
    model: str = Field(min_length=1)
    granularity: Literal["scene", "beat", "auto"]
    temperature: float | None = None


class SpanRecord(StrictModel):
    beat: str = Field(pattern=_BEAT_ID_PATTERN)
    start: int = Field(ge=0)
    end: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_interval(self) -> "SpanRecord":
        if self.end < self.start:
            raise ValueError("span end must be greater than or equal to start")
        return self


class SpansDocument(StrictModel):
    run: int = Field(ge=1)
    generator: GeneratorInfo | None = None
    spans: list[SpanRecord] = Field(default_factory=list)
    missing_markers: list[str] = Field(default_factory=list)
    parse_errors: list[str] = Field(default_factory=list)
    fact_annotations: dict[str, list[str]] = Field(default_factory=dict)


class BeatMetrics(StrictModel):
    id: str = Field(pattern=_BEAT_ID_PATTERN)
    chars: int = Field(ge=0)
    budget_ratio: float = Field(ge=0)
    paragraphs: int = Field(ge=0)
    dialogue_turns: int = Field(ge=0)
    sensory: int = Field(ge=0)
    interiority: int = Field(ge=0)
    new_facts: int | None = Field(default=None, ge=0)
    new_facts_source: Literal["annotation", "unmeasured"] = "unmeasured"
    measurement_methods: dict[str, str] = Field(default_factory=dict)
    summary_markers: list[str] = Field(default_factory=list)
    time_density: float | None = None


class SceneMetrics(StrictModel):
    chars: int = Field(ge=0)
    overall_budget_ratio: float | None = Field(default=None, ge=0)
    head_tail_ratio: float | None = Field(default=None, ge=0)
    coverage: bool


class MetricsPayload(StrictModel):
    run: int = Field(ge=1)
    finish_reason: str | None = None
    beats: list[BeatMetrics] = Field(default_factory=list)
    scene: SceneMetrics


class MetricsDocument(StrictModel):
    metrics: MetricsPayload
