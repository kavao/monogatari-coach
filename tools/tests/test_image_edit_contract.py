from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from image_edit.contracts import (  # noqa: E402
    ImageEditRequest,
    validate_ordered_image_inputs,
)
from image_edit.fake_adapter import FakeAdapter  # noqa: E402


def _request(**options: object) -> ImageEditRequest:
    return ImageEditRequest(
        schema_version="1.0",
        operation="image_to_image",
        intent="restyle",
        provider="fake",
        model="fake-v1",
        source_images=({"path": "source.png", "sha256": "abc"},),
        instruction="keep composition",
        provider_options=dict(options),
    )


def test_fake_adapter_rejects_unsupported_seed_before_execution() -> None:
    adapter = FakeAdapter()
    with pytest.raises(ValueError, match="seed"):
        adapter.prepare(_request(seed=1))


def test_fake_multipart_adapter_dry_run_does_not_require_base64() -> None:
    adapter = FakeAdapter(transport="multipart")
    plan = adapter.prepare(_request())
    assert plan.transport == "multipart"
    assert plan.network_allowed is False
    assert "base64" not in str(plan.payload)
    result = adapter.normalize_result(adapter.execute(plan))
    assert result.status == "success"
    assert result.details["transport"] == "multipart"


def test_common_contract_preserves_multiple_role_order_without_io() -> None:
    records = validate_ordered_image_inputs(
        [
            {"order": 1, "role": "layout", "path": "name.png", "sha256": "a" * 64},
            {
                "order": 2,
                "role": "character",
                "path": "hero.png",
                "sha256": "b" * 64,
                "character_id": "hero",
                "variant_id": "battle",
            },
        ],
        max_images=5,
    )
    adapter = FakeAdapter(max_inputs=5)
    request = _request()
    request = ImageEditRequest(
        **{
            **request.__dict__,
            "ordered_image_inputs": tuple(records),
            "reference_guided_generation": True,
        }
    )
    plan = adapter.prepare(request)
    assert [item["role"] for item in plan.payload["ordered_image_inputs"]] == [
        "layout",
        "character",
    ]
    assert [item["order"] for item in plan.payload["ordered_image_inputs"]] == [1, 2]


def test_common_contract_rejects_noncontiguous_attachment_order() -> None:
    with pytest.raises(ValueError, match="連番"):
        validate_ordered_image_inputs(
            [
                {"order": 2, "role": "layout", "path": "name.png", "sha256": "a" * 64},
            ]
        )
