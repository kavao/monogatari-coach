"""CHRONOS の永続データモデル。

Pydantic モデルを実行時の契約とし、YAML は ``storage.py`` 経由で保存する。
必須は Event の ``id`` と ``title`` のみ。日付は省略できる（原則 A）。
"""

from __future__ import annotations

from enum import Enum
from re import fullmatch

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


_EVENT_ID_PATTERN = r"^EVT-\d{4,}$"
_CHARACTER_ID_PATTERN = r"^CHR-[A-Za-z0-9_-]+$"
_LOCATION_ID_PATTERN = r"^LOC-[A-Za-z0-9_-]+$"
# METRON の scene.id（chNN-MMM）と計画書の SCN-XXXX の両方を受け付ける。
_SCENE_ID_PATTERN = r"^(SCN-\d{4,}|ch\d{2,}-\d{3,})$"
_RULE_ID_PATTERN = r"^CHR\d{3}$"

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


class EventSource(StrictModel):
    scene: str | None = Field(default=None, pattern=_SCENE_ID_PATTERN)
    span: tuple[int, int] | None = None
    digest: str | None = None

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

    def ignored_rules(self) -> set[str]:
        if self.chronos is None:
            return set()
        return {item.rule for item in self.chronos.ignore}


class EventFile(StrictModel):
    events: list[Event] = Field(default_factory=list)


class Character(StrictModel):
    id: str = Field(pattern=_CHARACTER_ID_PATTERN)
    name: str = Field(min_length=1)


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


class ChronosConfig(StrictModel):
    schema_version: int = Field(default=SCHEMA_VERSION, alias="schema")
    rules: dict[str, Severity] = Field(default_factory=dict)
    travel: list[TravelRule] = Field(default_factory=list)
    disclosure_distance_threshold: int = Field(default=40000, ge=1)

    @field_validator("rules")
    @classmethod
    def _rule_keys(cls, value: dict[str, Severity]) -> dict[str, Severity]:
        for key in value:
            if not _matches(_RULE_ID_PATTERN, key):
                raise ValueError(f"invalid rule id: {key}")
        return value

    def severity_for(self, rule_id: str, default: Severity = Severity.ERROR) -> Severity:
        return self.rules.get(rule_id, default)


class Finding(StrictModel):
    rule: str = Field(pattern=_RULE_ID_PATTERN)
    severity: Severity
    message: str = Field(min_length=1)
    events: list[str] = Field(default_factory=list)


def _matches(pattern: str, value: str) -> bool:
    return fullmatch(pattern, value) is not None
