"""CHRONOS の永続データモデル。

Pydantic モデルを実行時の契約とし、YAML は ``storage.py`` 経由で保存する。
必須は Event の ``id`` と ``title`` のみ。日付は省略できる（原則 A）。
追加フィールドは省略可能で、schema: 1 の既存入力を受け付ける。
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from re import fullmatch
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator


_EVENT_ID_PATTERN = r"^EVT-\d{4,}$"
_CHARACTER_ID_PATTERN = r"^CHR-[A-Za-z0-9_-]+$"
_LOCATION_ID_PATTERN = r"^LOC-[A-Za-z0-9_-]+$"
# METRON の scene.id（chNN-MMM）と計画書の SCN-XXXX の両方を受け付ける。
_SCENE_ID_PATTERN = r"^(SCN-\d{4,}|ch\d{2,}-\d{3,})$"
_RULE_ID_PATTERN = r"^CHR\d{3}$"
_DIMENSION_NAME_PATTERN = r"^[A-Za-z][A-Za-z0-9_]*$"

SCHEMA_VERSION = 1


class StrictModel(BaseModel):
    """未知キーを黙って捨てず、契約の typo を検出する基底モデル。"""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=True,
        populate_by_name=True,
    )


class EventType(str, Enum):
    INCIDENT = "incident"
    DISCOVERY = "discovery"
    DECISION = "decision"
    STATE_CHANGE = "state_change"
    MEETING = "meeting"
    DEATH = "death"
    BIRTH = "birth"


class Origin(str, Enum):
    EXTRACTED = "extracted"
    AUTHORED = "authored"


class ReviewStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class SceneMode(str, Enum):
    PRESENT = "present"
    FLASHBACK = "flashback"
    DREAM = "dream"
    DOCUMENT = "document"
    TESTIMONY = "testimony"


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"
    OFF = "off"


class DimensionType(str, Enum):
    ENUM = "enum"
    BOOL = "bool"
    LOC_REF = "loc_ref"


class Canon(str, Enum):
    ILLUSTRATION = "illustration"
    WORLD = "world"
    TEXT = "text"


class StateAt(str, Enum):
    BEFORE = "before"
    AFTER = "after"


RULE_SEVERITY_DEFAULTS: dict[str, Severity] = {
    "CHR001": Severity.ERROR,
    "CHR010": Severity.ERROR,
    "CHR011": Severity.WARNING,
    "CHR012": Severity.OFF,
    "CHR013": Severity.ERROR,
}


class IgnoreRule(StrictModel):
    rule: str = Field(pattern=_RULE_ID_PATTERN)
    reason: str = Field(min_length=1)


class ChronosMeta(StrictModel):
    ignore: list[IgnoreRule] = Field(default_factory=list)


class TimeOffset(StrictModel):
    """相対オフセット。P0 では ``from`` を順序制約（after）としてだけ使う。"""

    from_event: str = Field(alias="from", pattern=_EVENT_ID_PATTERN)
    min: str | None = None
    max: str | None = None


class EventTime(StrictModel):
    earliest: str | None = None
    latest: str | None = None
    after: list[str] = Field(default_factory=list)
    before: list[str] = Field(default_factory=list)
    offset: TimeOffset | None = None

    @field_validator("after", "before")
    @classmethod
    def _event_ids(cls, value: list[str]) -> list[str]:
        for item in value:
            if not _matches(_EVENT_ID_PATTERN, item):
                raise ValueError(f"invalid event id: {item}")
        return value


class IllustrationRef(StrictModel):
    path: str = Field(min_length=1)
    character_id: str = Field(min_length=1)
    state_at: StateAt = StateAt.AFTER

    @field_validator("path")
    @classmethod
    def _illustration_path(cls, value: str) -> str:
        normalized = value.replace("\\", "/").strip()
        if not normalized:
            raise ValueError("illustration path must not be empty")
        if normalized.startswith("/") or (len(normalized) >= 2 and normalized[1] == ":"):
            raise ValueError("illustration path must be work-root relative")
        parts = Path(normalized).parts
        if ".." in parts:
            raise ValueError("illustration path must not contain '..'")
        if not normalized.startswith("illustrations/pages/"):
            raise ValueError("illustration path must be under illustrations/pages/")
        if not normalized.endswith(".yaml"):
            raise ValueError("illustration path must end with .yaml")
        if Path(normalized).name.startswith("."):
            raise ValueError("illustration path must not be a hidden file")
        return normalized


class EventSource(StrictModel):
    scene: str | None = Field(default=None, pattern=_SCENE_ID_PATTERN)
    span: tuple[int, int] | None = None
    digest: str | None = None
    illustrations: list[IllustrationRef] | None = None

    @field_validator("illustrations", mode="before")
    @classmethod
    def _empty_illustrations(cls, value: object) -> object:
        if value == []:
            return None
        return value

    @model_validator(mode="after")
    def _span_order(self) -> EventSource:
        if self.span is not None and self.span[1] < self.span[0]:
            raise ValueError("source.span must be a half-open interval [start, end)")
        return self


class Event(StrictModel):
    id: str = Field(pattern=_EVENT_ID_PATTERN)
    title: str = Field(min_length=1)
    type: EventType | None = None
    actors: list[str] = Field(default_factory=list)
    location: str | None = Field(default=None, pattern=_LOCATION_ID_PATTERN)
    time: EventTime | None = None
    causes: list[str] = Field(default_factory=list)
    effects: list[str] = Field(default_factory=list)
    origin: Origin = Origin.AUTHORED
    source: EventSource | None = None
    review: ReviewStatus = ReviewStatus.APPROVED
    locked_fields: list[str] = Field(default_factory=list)
    effects_on: dict[str, dict[str, Any]] | None = None
    chronos: ChronosMeta | None = None

    @field_validator("actors")
    @classmethod
    def _actor_ids(cls, value: list[str]) -> list[str]:
        for item in value:
            if not _matches(_CHARACTER_ID_PATTERN, item):
                raise ValueError(f"invalid character id: {item}")
        return value

    @field_validator("causes", "effects")
    @classmethod
    def _related_event_ids(cls, value: list[str]) -> list[str]:
        for item in value:
            if not _matches(_EVENT_ID_PATTERN, item):
                raise ValueError(f"invalid event id: {item}")
        return value

    @field_validator("effects_on", mode="before")
    @classmethod
    def _effects_on_shape(cls, value: object) -> object:
        if value == {}:
            return None
        if value is None:
            return None
        if not isinstance(value, dict):
            raise ValueError("effects_on must be a mapping of character id to dimension diffs")
        for actor, diffs in value.items():
            if not isinstance(actor, str) or not _matches(_CHARACTER_ID_PATTERN, actor):
                raise ValueError(f"invalid character id in effects_on: {actor}")
            if not isinstance(diffs, dict):
                raise ValueError(f"effects_on.{actor} must be a mapping")
            if any(item is None for item in diffs.values()):
                raise ValueError(f"effects_on.{actor} values cannot be null")
        return value

    def ignored_rules(self) -> set[str]:
        if self.chronos is None:
            return set()
        return {item.rule for item in self.chronos.ignore}


class EventFile(StrictModel):
    events: list[Event] = Field(default_factory=list)


class Character(StrictModel):
    id: str = Field(pattern=_CHARACTER_ID_PATTERN)
    name: str = Field(min_length=1)
    initial_state: dict[str, Any] | None = None

    @field_validator("initial_state", mode="before")
    @classmethod
    def _initial_state_shape(cls, value: object) -> object:
        if value == {}:
            return None
        if value is None:
            return None
        if not isinstance(value, dict):
            raise ValueError("initial_state must be a mapping")
        if any(item is None for item in value.values()):
            raise ValueError("initial_state values cannot be null")
        return value


class Location(StrictModel):
    id: str = Field(pattern=_LOCATION_ID_PATTERN)
    name: str = Field(min_length=1)


class CharacterFile(StrictModel):
    characters: list[Character] = Field(default_factory=list)


class LocationFile(StrictModel):
    locations: list[Location] = Field(default_factory=list)


class Scene(StrictModel):
    id: str = Field(pattern=_SCENE_ID_PATTERN)
    chapter: int | None = Field(default=None, ge=1)
    order: int | None = Field(default=None, ge=1)
    mode: SceneMode = SceneMode.PRESENT
    refs: list[str] = Field(default_factory=list)
    char_offset: int | None = Field(default=None, ge=0)
    metron_scene_id: str | None = Field(default=None, pattern=r"^ch\d{2,}-\d{3,}$")

    @field_validator("refs")
    @classmethod
    def _ref_event_ids(cls, value: list[str]) -> list[str]:
        for item in value:
            if not _matches(_EVENT_ID_PATTERN, item):
                raise ValueError(f"invalid event id: {item}")
        return value


class SceneFile(StrictModel):
    scenes: list[Scene] = Field(default_factory=list)


class TravelRule(StrictModel):
    """P1 用。P0 では読み込んで保持するだけ。"""

    from_location: str = Field(alias="from", pattern=_LOCATION_ID_PATTERN)
    to: str = Field(pattern=_LOCATION_ID_PATTERN)
    min: str = Field(min_length=1)


class DimensionSpec(StrictModel):
    type: DimensionType
    values: list[str] | None = None
    default: StrictBool | str | None = None
    canon: Canon = Canon.WORLD

    @field_validator("default", mode="before")
    @classmethod
    def _reject_numeric_default(cls, value: object) -> object:
        if isinstance(value, bool) or value is None:
            return value
        if isinstance(value, int):
            raise ValueError("default must be a boolean or string, not an integer")
        return value

    @model_validator(mode="after")
    def _shape(self) -> DimensionSpec:
        if "default" in self.model_fields_set and self.default is None:
            raise ValueError("default cannot be null; omit the key instead")
        if self.type is DimensionType.ENUM:
            if not self.values:
                raise ValueError("enum dimension requires non-empty values")
            if any(not item for item in self.values):
                raise ValueError("enum values must be non-empty strings")
            if len(self.values) != len(set(self.values)):
                raise ValueError("enum values must be unique")
            if self.default is not None:
                if not isinstance(self.default, str) or self.default not in self.values:
                    raise ValueError("enum default must be one of values")
        else:
            if self.values is not None:
                raise ValueError("values are only allowed on enum dimensions")
        if self.type is DimensionType.BOOL and self.default is not None:
            if not isinstance(self.default, bool):
                raise ValueError("bool default must be a boolean")
        if self.type is DimensionType.LOC_REF and self.default is not None:
            if not isinstance(self.default, str) or not _matches(_LOCATION_ID_PATTERN, self.default):
                raise ValueError("loc_ref default must be a LOC-* id")
        return self


class TransitionRule(StrictModel):
    dimension: str = Field(min_length=1)
    from_value: StrictBool | str = Field(alias="from")
    to: StrictBool | str

    @field_validator("from_value", "to", mode="before")
    @classmethod
    def _reject_numeric_endpoint(cls, value: object) -> object:
        if isinstance(value, bool):
            return value
        if isinstance(value, int):
            raise ValueError("transition endpoints must be boolean or string, not an integer")
        return value


class IllustrationBind(StrictModel):
    actor: str = Field(pattern=_CHARACTER_ID_PATTERN)
    character_id: str = Field(min_length=1)
    dimension: str = Field(min_length=1)
    value: str = Field(min_length=1)
    variant_ids: list[str] = Field(min_length=1)

    @field_validator("variant_ids")
    @classmethod
    def _variant_ids(cls, value: list[str]) -> list[str]:
        if any(not item for item in value):
            raise ValueError("variant_ids must be non-empty strings")
        if len(value) != len(set(value)):
            raise ValueError("variant_ids must be unique")
        return value


class CharacterStateConfig(StrictModel):
    dimensions: dict[str, DimensionSpec] = Field(default_factory=dict)
    transitions: list[TransitionRule] = Field(default_factory=list)
    illustration_bind: list[IllustrationBind] = Field(default_factory=list)

    @field_validator("dimensions")
    @classmethod
    def _dimension_names(cls, value: dict[str, DimensionSpec]) -> dict[str, DimensionSpec]:
        for name in value:
            if not _matches(_DIMENSION_NAME_PATTERN, name):
                raise ValueError(f"invalid dimension name: {name}")
        return value


class ChronosConfig(StrictModel):
    schema_version: int = Field(default=SCHEMA_VERSION, alias="schema")
    rules: dict[str, Severity] = Field(default_factory=dict)
    travel: list[TravelRule] = Field(default_factory=list)
    disclosure_distance_threshold: int = Field(default=40000, ge=1)
    character_state: CharacterStateConfig | None = None

    @field_validator("rules")
    @classmethod
    def _rule_keys(cls, value: dict[str, Severity]) -> dict[str, Severity]:
        for key in value:
            if not _matches(_RULE_ID_PATTERN, key):
                raise ValueError(f"invalid rule id: {key}")
        return value

    def severity_for(self, rule_id: str, default: Severity | None = None) -> Severity:
        if rule_id in self.rules:
            return self.rules[rule_id]
        if default is not None:
            return default
        return RULE_SEVERITY_DEFAULTS.get(rule_id, Severity.ERROR)

    def state_enabled(self) -> bool:
        return self.character_state is not None and bool(self.character_state.dimensions)


class Finding(StrictModel):
    rule: str = Field(pattern=_RULE_ID_PATTERN)
    severity: Severity
    message: str = Field(min_length=1)
    events: list[str] = Field(default_factory=list)


def _matches(pattern: str, value: str) -> bool:
    return fullmatch(pattern, value) is not None


def is_character_id(value: str) -> bool:
    return _matches(_CHARACTER_ID_PATTERN, value)


def is_location_id(value: str) -> bool:
    return _matches(_LOCATION_ID_PATTERN, value)
