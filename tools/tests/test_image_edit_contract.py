from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from image_edit.contracts import ImageEditRequest  # noqa: E402
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
