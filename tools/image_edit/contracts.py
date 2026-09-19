"""Small provider-independent contracts for image edit operations."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class ImageEditRequest:
    schema_version: str
    operation: str
    intent: str
    provider: str
    model: str
    source_images: tuple[dict[str, Any], ...]
    instruction: str
    style_references: tuple[dict[str, Any], ...] = ()
    size_policy: dict[str, Any] = field(default_factory=dict)
    output_dir: str = ""
    provider_options: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EditExecutionPlan:
    request: ImageEditRequest
    transport: str
    payload: dict[str, Any]
    network_allowed: bool = False


@dataclass(frozen=True)
class EditResult:
    status: str
    provider: str
    outputs: tuple[dict[str, Any], ...] = ()
    details: dict[str, Any] = field(default_factory=dict)


class ImageEditAdapter(Protocol):
    """Provider adapter boundary; adapters own transport differences."""

    name: str

    def capabilities(self, model: str, operation: str) -> dict[str, Any]: ...

    def validate(self, request: ImageEditRequest) -> None: ...

    def prepare(self, request: ImageEditRequest) -> EditExecutionPlan: ...

    def execute(self, plan: EditExecutionPlan) -> Any: ...

    def normalize_result(self, response: Any) -> EditResult: ...
