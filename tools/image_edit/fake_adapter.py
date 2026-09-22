"""Offline adapters used to test the common image-edit contract."""

from __future__ import annotations

from typing import Any

from .contracts import (
    EditExecutionPlan,
    EditResult,
    ImageEditRequest,
    validate_ordered_image_inputs,
)


class FakeAdapter:
    """A deterministic adapter with configurable transport shape.

    It never performs I/O. ``transport='multipart'`` proves the common layer
    does not require base64 JSON before an adapter chooses its own transport.
    """

    name = "fake"

    def __init__(self, *, transport: str = "json", max_inputs: int = 1) -> None:
        if transport not in {"json", "multipart"}:
            raise ValueError("fake transport must be json or multipart")
        if max_inputs < 1:
            raise ValueError("fake max_inputs must be positive")
        self.transport = transport
        self.max_inputs = max_inputs

    def capabilities(self, model: str, operation: str) -> dict[str, Any]:
        return {
            "model": model,
            "operation": operation,
            "input_images": self.max_inputs,
            "multi_image_editing": self.max_inputs > 1,
            "reference_guided_generation": self.max_inputs > 1,
            "reference_contract_version": "1.1",
            "style_references": True,
            "strength": False,
            "noise": False,
            "seed": False,
            "transport": self.transport,
        }

    def validate(self, request: ImageEditRequest) -> None:
        if request.provider != self.name:
            raise ValueError(f"fake adapter received provider={request.provider!r}")
        if request.operation != "image_to_image":
            raise ValueError("fake adapter supports image_to_image only")
        if len(request.source_images) != 1:
            raise ValueError("fake adapter requires exactly one source image")
        if request.ordered_image_inputs:
            validate_ordered_image_inputs(
                request.ordered_image_inputs,
                max_images=self.max_inputs,
            )
        elif request.style_references:
            # Legacy requests did not carry an explicit order.  Keep them
            # valid, but the new restyle planner always emits the ordered form.
            if len(request.style_references) + 1 > self.max_inputs:
                raise ValueError("fake adapterの画像入力件数上限を超えています")
        unsupported = {
            key
            for key in ("seed", "strength", "noise")
            if key in request.provider_options
        }
        if unsupported:
            raise ValueError(
                "fake adapter does not support: " + ", ".join(sorted(unsupported))
            )

    def prepare(self, request: ImageEditRequest) -> EditExecutionPlan:
        self.validate(request)
        return EditExecutionPlan(
            request=request,
            transport=self.transport,
            payload={
                "operation": request.operation,
                "instruction": request.instruction,
                "source_images": list(request.source_images),
                "style_references": list(request.style_references),
                "ordered_image_inputs": list(request.ordered_image_inputs),
                "reference_guided_generation": request.reference_guided_generation,
            },
            network_allowed=False,
        )

    def execute(self, plan: EditExecutionPlan) -> dict[str, Any]:
        if plan.network_allowed:
            raise ValueError("fake adapter refuses network execution")
        return {"status": "success", "transport": plan.transport}

    def normalize_result(self, response: Any) -> EditResult:
        if not isinstance(response, dict):
            raise ValueError("fake response must be an object")
        return EditResult(
            status=str(response.get("status", "unknown")),
            provider=self.name,
            details={"transport": response.get("transport", self.transport)},
        )
