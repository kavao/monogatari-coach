"""writing_bridge schema 1。既存 METRON / CHRONOS モデルへキーを足さない。"""

from __future__ import annotations

from enum import Enum
from typing import Any

from re import fullmatch

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


SCHEMA = 1
SCENE_ID = r"^ch\d{2,}-\d{3,}$"
REQUEST_ID = r"^WRQ-\d{4,}$"
RUN_ID = r"^run-\d{4,}$"
JOB_ID = r"^JOB-\d{4,}$"
EVENT_ID = r"^EVT-\d{4,}$"
ACTOR_ID = r"^CHR-[A-Za-z0-9_-]+$"
BEAT_ID = r"^[A-Za-z][A-Za-z0-9_-]*$"
LOCATION_ID = r"^LOC-[A-Za-z0-9_-]+$"
HASH = r"^sha256:[0-9a-f]{64}$"


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=True,
        populate_by_name=True,
    )


class RequestKind(str, Enum):
    NEW = "new"
    APPEND = "append"
    LOCAL_EXPAND = "local_expand"
    REFINE = "refine"


class StateAt(str, Enum):
    BEFORE = "before"
    AFTER = "after"


class Confirmation(str, Enum):
    MATCH = "match"
    MISMATCH = "mismatch"
    ABSENT = "absent"
    UNCLEAR = "unclear"
    UNRECORDED = "unrecorded"


class ItemStatus(str, Enum):
    SUCCESS = "success"
    FINDINGS = "findings"
    SKIPPED = "skipped"
    UNRESOLVED = "unresolved"
    FAILED = "failed"


class LinksStatus(str, Enum):
    ADOPTED = "adopted"
    CANDIDATE = "candidate"
    CONFLICT = "conflict"


class Recorder(str, Enum):
    AGENT = "agent"
    AUTHOR = "author"
    TOOL = "tool"


class SelectorKind(str, Enum):
    HEADING = "heading"
    HTML_COMMENT = "html_comment"
    OFFSET = "offset"


class JournalAction(str, Enum):
    PREPARE = "prepare"
    REQUEST = "request"
    RECEIVE = "receive"
    VALIDATE = "validate"
    INSPECT = "inspect"
    SELECT = "select"
    PUBLISH = "publish"
    REPAIR_BEGIN = "repair_begin"
    REPAIR_NEXT = "repair_next"
    REPAIR_SUBMIT = "repair_submit"


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class FlagValue(str, Enum):
    ON = "ON"
    OFF = "OFF"


class Selector(StrictModel):
    kind: SelectorKind
    value: str = Field(min_length=1)


class TargetSpec(StrictModel):
    text_path: str = Field(min_length=1)
    selector: Selector | None = None
    base_raw_sha256: str = Field(pattern=HASH)
    base_text_sha256: str = Field(pattern=HASH)
    base_exists: bool = True


class ModelRef(StrictModel):
    id: str = Field(min_length=1)
    calibrated: bool


class Permissions(StrictModel):
    draft: bool
    repair: bool
    publish: bool
    event_patch: bool


class FlagPair(StrictModel):
    metron: FlagValue
    chronos: FlagValue


class RequestDocument(StrictModel):
    schema_version: int = Field(alias="schema")
    request_id: str = Field(pattern=REQUEST_ID)
    run_id: str = Field(pattern=RUN_ID)
    work_rel: str = Field(min_length=1)
    scene_id: str = Field(pattern=SCENE_ID)
    request_kind: RequestKind
    target: TargetSpec
    model: ModelRef
    permissions: Permissions
    flags: FlagPair

    @field_validator("schema_version")
    @classmethod
    def _schema(cls, value: int) -> int:
        if value != SCHEMA:
            raise ValueError("unsupported schema")
        return value


class LinkItem(StrictModel):
    beat_id: str | None = Field(default=None, pattern=BEAT_ID)
    event_id: str = Field(pattern=EVENT_ID)
    state_at: StateAt
    actors: list[str] = Field(min_length=1)
    note: str | None = None

    @field_validator("actors")
    @classmethod
    def _actors(cls, value: list[str]) -> list[str]:
        for item in value:
            if not fullmatch(ACTOR_ID, item):
                raise ValueError(f"invalid actor id: {item}")
        return value


class LinksDocument(StrictModel):
    schema_version: int = Field(alias="schema")
    scene_id: str = Field(pattern=SCENE_ID)
    text_path: str = Field(min_length=1)
    selector: Selector
    text_sha256: str = Field(pattern=HASH)
    status: LinksStatus
    created_by: Recorder
    adopted_by: Recorder
    items: list[LinkItem] = Field(default_factory=list)

    @field_validator("schema_version")
    @classmethod
    def _schema(cls, value: int) -> int:
        if value != SCHEMA:
            raise ValueError("unsupported schema")
        return value


class ExpectedCheck(StrictModel):
    event_id: str = Field(pattern=EVENT_ID)
    actor_id: str = Field(pattern=ACTOR_ID)
    dimension: str = Field(min_length=1)
    state_at: StateAt
    expected_value: Any


class InputHash(StrictModel):
    path: str = Field(min_length=1)
    raw_sha256: str = Field(pattern=HASH)


class ContextDocument(StrictModel):
    schema_version: int = Field(alias="schema")
    request_id: str = Field(pattern=REQUEST_ID)
    run_id: str = Field(pattern=RUN_ID)
    input_hashes: list[InputHash]
    expected_checks: list[ExpectedCheck] = Field(default_factory=list)
    beats: list[dict[str, Any]] = Field(default_factory=list)
    forbidden: list[str] = Field(default_factory=list)
    instruction_chars: int | None = None
    states: list[dict[str, Any]] = Field(default_factory=list)
    unresolved: list[dict[str, Any]] = Field(default_factory=list)
    prose_start_end: dict[str, Any] | None = None

    @field_validator("schema_version")
    @classmethod
    def _schema(cls, value: int) -> int:
        if value != SCHEMA:
            raise ValueError("unsupported schema")
        return value


class ObservationItem(StrictModel):
    event_id: str = Field(pattern=EVENT_ID)
    actor_id: str = Field(pattern=ACTOR_ID)
    dimension: str = Field(min_length=1)
    value: Any
    state_at: StateAt
    quote: str
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    range_sha256: str = Field(pattern=HASH)
    recorder: Recorder
    confirmation: Confirmation

    @model_validator(mode="after")
    def _span(self) -> "ObservationItem":
        if self.end < self.start:
            raise ValueError("end must be >= start")
        return self


class ObservationsDocument(StrictModel):
    schema_version: int = Field(alias="schema")
    request_id: str = Field(pattern=REQUEST_ID)
    text_sha256: str = Field(pattern=HASH)
    expected_total: int = Field(ge=0)
    items: list[ObservationItem] = Field(default_factory=list)

    @field_validator("schema_version")
    @classmethod
    def _schema(cls, value: int) -> int:
        if value != SCHEMA:
            raise ValueError("unsupported schema")
        return value


class ReportFinding(StrictModel):
    code: str | None = None
    note: str = Field(min_length=1)


class ReportDocument(StrictModel):
    schema_version: int = Field(alias="schema")
    request_id: str = Field(pattern=REQUEST_ID)
    run_id: str = Field(pattern=RUN_ID)
    target_text_sha256: str = Field(pattern=HASH)
    text_save: ItemStatus
    metron: ItemStatus
    chronos_registered: ItemStatus
    text_state: ItemStatus
    findings: list[ReportFinding] = Field(default_factory=list)
    repair_history: list[dict[str, Any]] = Field(default_factory=list)
    open_issues: list[dict[str, Any]] = Field(default_factory=list)

    @field_validator("schema_version")
    @classmethod
    def _schema(cls, value: int) -> int:
        if value != SCHEMA:
            raise ValueError("unsupported schema")
        return value


class JournalEntry(StrictModel):
    schema_version: int = Field(alias="schema")
    at: str = Field(min_length=1)
    action: JournalAction
    run_id: str = Field(pattern=RUN_ID)
    request_id: str | None = Field(default=None, pattern=REQUEST_ID)
    job_id: str | None = Field(default=None, pattern=JOB_ID)
    hashes: dict[str, str] | None = None
    note: str | None = None

    @field_validator("schema_version")
    @classmethod
    def _schema(cls, value: int) -> int:
        if value != SCHEMA:
            raise ValueError("unsupported schema")
        return value


class ArtifactRef(StrictModel):
    path: str = Field(min_length=1)
    raw_sha256: str = Field(pattern=HASH)


class GenerationProvenance(StrictModel):
    candidate_raw_sha256: str = Field(pattern=HASH)
    finish_reason: str | None = None
    model_id: str | None = None


class ArtifactRefsDocument(StrictModel):
    schema_version: int = Field(alias="schema")
    request_id: str = Field(pattern=REQUEST_ID)
    model: ModelRef
    metron: dict[str, ArtifactRef] | None = None
    candidate: ArtifactRef | None = None
    candidates: list[ArtifactRef] = Field(default_factory=list)
    generation: GenerationProvenance | None = None

    @field_validator("schema_version")
    @classmethod
    def _schema(cls, value: int) -> int:
        if value != SCHEMA:
            raise ValueError("unsupported schema")
        return value
