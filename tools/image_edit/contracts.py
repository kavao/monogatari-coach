"""Small provider-independent contracts for image edit operations.

The contract deliberately carries image *identity* and ordering, but never
loads image bytes.  Provider adapters decide how a verified path is uploaded
or encoded.  This keeps dry-runs safe and prevents a prompt from claiming an
attachment that was not actually prepared for the request.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


REFERENCE_CONTRACT_VERSION = "1.1"
IMAGE_REFERENCE_ROLES = frozenset(
    {
        "source",
        "character",
        "costume",
        "location",
        "prop",
        "layout",
        "name",
        "style",
        "reference",
    }
)


def validate_ordered_image_inputs(
    records: Any,
    *,
    label: str = "ordered_image_inputs",
    max_images: int | None = None,
) -> list[dict[str, Any]]:
    """Validate the common ordered attachment contract without doing I/O.

    The path and SHA-256 are checked for presence here.  Callers that are
    about to send must additionally re-stat and re-hash the files, since a
    dry-run manifest can become stale.
    """
    if not isinstance(records, (list, tuple)):
        raise ValueError(f"{label} は配列である必要があります")
    if max_images is not None and len(records) > max_images:
        raise ValueError(
            f"{label} がprovider上限を超えています: {len(records)} > {max_images}"
        )
    out: list[dict[str, Any]] = []
    orders: list[int] = []
    for index, raw in enumerate(records, start=1):
        if not isinstance(raw, dict):
            raise ValueError(f"{label}[{index}] はobjectである必要があります")
        role = str(raw.get("role") or "").strip().lower()
        if role not in IMAGE_REFERENCE_ROLES:
            raise ValueError(
                f"{label}[{index}] のroleが未対応です: {role!r}"
            )
        path = str(raw.get("path") or "").strip()
        if not path:
            raise ValueError(f"{label}[{index}] にpathがありません")
        sha256 = str(raw.get("sha256") or "").strip().lower()
        if len(sha256) != 64 or any(ch not in "0123456789abcdef" for ch in sha256):
            raise ValueError(f"{label}[{index}] のsha256が不正です")
        order = raw.get("order", index)
        if isinstance(order, bool):
            raise ValueError(f"{label}[{index}] のorderが不正です")
        try:
            order_int = int(order)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{label}[{index}] のorderが不正です") from exc
        if order_int < 1 or order_int in orders:
            raise ValueError(f"{label}[{index}] のorderが重複または不正です")
        orders.append(order_int)
        normalized = dict(raw)
        normalized["role"] = role
        normalized["path"] = path
        normalized["sha256"] = sha256
        normalized["order"] = order_int
        out.append(normalized)
    if sorted(orders) != list(range(1, len(out) + 1)):
        raise ValueError(f"{label} のorderは1からの連番である必要があります")
    return out


def validate_reference_contract(
    *,
    source_images: Any,
    style_references: Any,
    ordered_image_inputs: Any,
) -> list[dict[str, Any]]:
    """Validate that legacy fields and the new ordered list agree."""
    ordered = validate_ordered_image_inputs(
        ordered_image_inputs,
        label="ordered_image_inputs",
    )
    if not ordered or ordered[0].get("role") != "source":
        raise ValueError("ordered_image_inputsの先頭はrole=sourceである必要があります")
    if isinstance(source_images, (list, tuple)) and source_images:
        source_path = str(source_images[0].get("path") or "")
        if source_path != str(ordered[0].get("path") or ""):
            raise ValueError("source_imagesとordered_image_inputsの先頭pathが一致しません")
    if not isinstance(style_references, (list, tuple)):
        raise ValueError("style_referencesは配列である必要があります")
    expected_style_paths = [str(item.get("path") or "") for item in style_references]
    actual_reference_paths = [str(item.get("path") or "") for item in ordered[1:]]
    if expected_style_paths != actual_reference_paths:
        raise ValueError(
            "style_referencesとordered_image_inputsの参照順・件数が一致しません"
        )
    return ordered


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
    ordered_image_inputs: tuple[dict[str, Any], ...] = ()
    reference_contract_version: str = REFERENCE_CONTRACT_VERSION
    reference_guided_generation: bool = False
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
