from __future__ import annotations

import hashlib
import base64
import json
import sys
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from image_provider_generate import (  # noqa: E402
    build_grok_payload,
    build_openai_payload,
    build_openrouter_payload,
    load_root_config,
    main as provider_main,
    merge_provider_defaults,
    resolve_openai_size,
    save_openai_response,
    save_openrouter_image_api_response,
)


def _reference(path: Path, *, order: int, role: str) -> dict[str, object]:
    return {
        "order": order,
        "role": role,
        "path": str(path),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "asset_id": f"asset-{order}",
    }


def test_grok_payload_keeps_declared_order_and_role_mapping(tmp_path: Path) -> None:
    first = tmp_path / "name.png"
    second = tmp_path / "hero.png"
    Image.new("RGB", (64, 64), (10, 20, 30)).save(first)
    Image.new("RGB", (64, 64), (40, 50, 60)).save(second)
    config = load_root_config(ROOT / "config" / "image_generation.json")
    merged = merge_provider_defaults(
        "grok",
        config["providers"]["grok"],
        {
            "prompt": "Use image 1 as layout and image 2 as character reference.",
            "output_dir": "outputs",
            "image_inputs": [
                _reference(first, order=1, role="layout"),
                _reference(second, order=2, role="character"),
            ],
        },
        root=ROOT,
    )
    payload = build_grok_payload(merged)
    assert [item["type"] for item in payload["images"]] == [
        "image_url",
        "image_url",
    ]
    assert all(item["url"].startswith("data:image/png;base64,") for item in payload["images"])
    assert [item["order"] for item in merged["image_inputs"]] == [1, 2]


def test_grok_rejects_six_inputs_before_payload_build(tmp_path: Path) -> None:
    image = tmp_path / "ref.png"
    Image.new("RGB", (32, 32), (1, 2, 3)).save(image)
    config = load_root_config(ROOT / "config" / "image_generation.json")
    refs = [_reference(image, order=index, role="reference") for index in range(1, 7)]
    with pytest.raises(ValueError, match="上限"):
        merge_provider_defaults(
            "grok",
            config["providers"]["grok"],
            {"prompt": "refs", "output_dir": "outputs", "image_inputs": refs},
            root=ROOT,
        )


def test_openai_edit_payload_keeps_paths_out_of_provider_json_body(tmp_path: Path) -> None:
    image = tmp_path / "layout.png"
    Image.new("RGB", (64, 64), (1, 2, 3)).save(image)
    config = load_root_config(ROOT / "config" / "image_generation.json")
    merged = merge_provider_defaults(
        "openai",
        config["providers"]["openai"],
        {
            "prompt": "Use image 1 as the name layout.",
            "output_dir": "outputs",
            "image_inputs": [_reference(image, order=1, role="layout")],
        },
        root=ROOT,
    )
    payload = build_openai_payload(merged)
    assert payload["image_inputs"][0]["role"] == "layout"
    assert payload["image_inputs"][0]["sha256"] == merged["image_inputs"][0]["sha256"]
    assert "image" not in payload


def test_openai_image_response_saves_response_model(tmp_path: Path) -> None:
    image_path = tmp_path / "fixture.png"
    Image.effect_noise((256, 256), 30).convert("RGB").save(image_path)
    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    saved = save_openai_response(
        resp={
            "model": "gpt-image-2",
            "data": [{"b64_json": encoded}],
        },
        merged={"file_prefix": "manga_01_p01", "prompt": "page"},
        payload={"model": "gpt-image-2"},
        provider_cfg={"min_png_bytes": 1},
        out_dir=out_dir,
        timeout=5,
    )

    metadata = json.loads(Path(saved[0]["json"]).read_text(encoding="utf-8"))
    assert metadata["response_model"] == "gpt-image-2"
    assert metadata["response_item"]["b64_json"].startswith("<redacted base64")
    assert encoded not in metadata["response_item"]["b64_json"]
    assert "response_key_outline" not in metadata


def test_openai_image_response_keeps_null_model_and_key_outline(tmp_path: Path) -> None:
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40
    encoded = base64.b64encode(png).decode("ascii")

    saved = save_openai_response(
        resp={"data": [{"b64_json": encoded}], "usage": {"total_tokens": 1}},
        merged={"file_prefix": "manga_01_p01", "prompt": "page"},
        payload={},
        provider_cfg={"min_png_bytes": 1},
        out_dir=tmp_path,
        timeout=5,
    )

    metadata = json.loads(Path(saved[0]["json"]).read_text(encoding="utf-8"))
    assert metadata["response_model"] is None
    outline = "\n".join(metadata["response_key_outline"])
    assert "data[].b64_json:" in outline
    assert encoded not in outline


def test_openai_default_model_is_gpt_image_2() -> None:
    config = load_root_config(ROOT / "config" / "image_generation.json")
    merged = merge_provider_defaults(
        "openai",
        config["providers"]["openai"],
        {"prompt": "Generate a page.", "output_dir": "outputs"},
        root=ROOT,
    )

    payload = build_openai_payload(merged)

    assert config["providers"]["openai"]["default_model"] == "gpt-image-2"
    assert merged["model"] == "gpt-image-2"
    assert payload["model"] == "gpt-image-2"
    assert payload["size"] == "1024x1024"
    assert payload["quality"] == "high"


def test_openai_legacy_model_remains_explicitly_selectable() -> None:
    config = load_root_config(ROOT / "config" / "image_generation.json")
    merged = merge_provider_defaults(
        "openai",
        config["providers"]["openai"],
        {
            "model": "gpt-image-1.5",
            "prompt": "Generate a legacy comparison image.",
            "output_dir": "outputs",
        },
        root=ROOT,
    )

    assert merged["model"] == "gpt-image-1.5"


def test_openai_manga_portrait_preset_resolves_to_portrait_size() -> None:
    config = load_root_config(ROOT / "config" / "image_generation.json")
    provider_cfg = config["providers"]["openai"]
    merged = merge_provider_defaults(
        "openai",
        provider_cfg,
        {
            "prompt": "Generate a portrait manga page.",
            "output_dir": "outputs",
            "aspect_ratio_preset": "manga_b5_portrait",
        },
        root=ROOT,
    )

    payload = build_openai_payload(merged)

    assert resolve_openai_size(provider_cfg, {"aspect_ratio_preset": "story_vertical"}) == "864x1536"
    assert resolve_openai_size(provider_cfg, {"aspect_ratio_preset": "3:4"}) == "1024x1344"
    assert merged["size"] == "1024x1536"
    assert merged["width"] == 1024
    assert merged["height"] == 1536
    assert payload["size"] == "1024x1536"


def test_openai_explicit_size_overrides_aspect_preset() -> None:
    config = load_root_config(ROOT / "config" / "image_generation.json")
    merged = merge_provider_defaults(
        "openai",
        config["providers"]["openai"],
        {
            "prompt": "Generate a custom-size manga page.",
            "output_dir": "outputs",
            "aspect_ratio_preset": "manga_b5_portrait",
            "size": "1536x1024",
        },
        root=ROOT,
    )

    assert merged["size"] == "1536x1024"
    assert merged["width"] == 1536
    assert merged["height"] == 1024


def test_openai_unknown_aspect_preset_stops_before_payload() -> None:
    config = load_root_config(ROOT / "config" / "image_generation.json")
    with pytest.raises(ValueError, match="aspect_ratio_preset"):
        merge_provider_defaults(
            "openai",
            config["providers"]["openai"],
            {
                "prompt": "page",
                "output_dir": "outputs",
                "aspect_ratio_preset": "not-a-ratio",
            },
            root=ROOT,
        )


@pytest.mark.parametrize(
    ("size", "message"),
    [("1024x1025", "16px"), ("4000x1024", "3840px")],
)
def test_openai_invalid_size_stops_before_payload(size: str, message: str) -> None:
    config = load_root_config(ROOT / "config" / "image_generation.json")
    with pytest.raises(ValueError, match=message):
        merge_provider_defaults(
            "openai",
            config["providers"]["openai"],
            {"prompt": "page", "output_dir": "outputs", "size": size},
            root=ROOT,
        )


def test_openrouter_page_payload_uses_images_api_and_declared_reference_order(
    tmp_path: Path,
) -> None:
    first = tmp_path / "name.png"
    second = tmp_path / "hero.png"
    Image.new("RGB", (64, 64), (10, 20, 30)).save(first)
    Image.new("RGB", (64, 64), (40, 50, 60)).save(second)
    config = load_root_config(ROOT / "config" / "image_generation.json")
    merged = merge_provider_defaults(
        "openrouter",
        config["providers"]["openrouter"],
        {
            "prompt": "Generate the complete page.",
            "output_dir": "outputs",
            "metadata": {"page_render_plan": {"compiler_version": "1.0"}},
            "image_inputs": [
                _reference(first, order=1, role="layout"),
                _reference(second, order=2, role="character"),
            ],
            "resolution": "2k",
            "aspect_ratio_preset": "manga_b5_portrait",
        },
        root=ROOT,
    )

    payload = build_openrouter_payload(merged)

    assert payload["model"] == "google/gemini-3.1-flash-image"
    assert payload["resolution"] == "2K"
    assert payload["aspect_ratio"] == "3:4"
    assert [item["type"] for item in payload["input_references"]] == [
        "image_url",
        "image_url",
    ]
    assert all(
        item["image_url"]["url"].startswith("data:image/png;base64,")
        for item in payload["input_references"]
    )
    assert "messages" not in payload


def test_openrouter_gpt_image_profile_uses_quality_not_resolution() -> None:
    config = load_root_config(ROOT / "config" / "image_generation.json")
    merged = merge_provider_defaults(
        "openrouter",
        config["providers"]["openrouter"],
        {
            "model": "gpt_image_2",
            "prompt": "Generate a complete page.",
            "output_dir": "outputs",
            "metadata": {"page_render_plan": {"compiler_version": "1.0"}},
            "quality": "high",
            "aspect_ratio_preset": "manga_b5_portrait",
        },
        root=ROOT,
    )

    payload = build_openrouter_payload(merged)

    assert merged["model"] == "openai/gpt-image-2"
    assert merged["openrouter_image_profile"]["profile_id"] == "gpt_image_2"
    assert payload["quality"] == "high"
    assert "resolution" not in payload
    assert payload["provider"] == {
        "only": ["openai"],
        "allow_fallbacks": False,
    }


def test_openrouter_nano_banana_2_alias_resolves_to_current_model() -> None:
    config = load_root_config(ROOT / "config" / "image_generation.json")
    merged = merge_provider_defaults(
        "openrouter",
        config["providers"]["openrouter"],
        {
            "model": "nano_banana_2",
            "prompt": "Generate a page.",
            "output_dir": "outputs",
            "metadata": {"page_render_plan": {"compiler_version": "1.0"}},
        },
        root=ROOT,
    )

    assert merged["model"] == "google/gemini-3.1-flash-image"
    assert merged["openrouter_image_profile"]["profile_id"] == "nano_banana_2"
    assert merged["image_size"] == "2K"


def test_openrouter_gpt_image_rejects_resolution_parameter() -> None:
    config = load_root_config(ROOT / "config" / "image_generation.json")
    with pytest.raises(ValueError, match="resolution/image_size"):
        merge_provider_defaults(
            "openrouter",
            config["providers"]["openrouter"],
            {
                "model": "gpt_image_2",
                "prompt": "page",
                "output_dir": "outputs",
                "metadata": {"page_render_plan": {"compiler_version": "1.0"}},
                "resolution": "2K",
            },
            root=ROOT,
        )


def test_openrouter_unknown_page_model_profile_stops_before_payload() -> None:
    config = load_root_config(ROOT / "config" / "image_generation.json")
    with pytest.raises(ValueError, match="model profile"):
        merge_provider_defaults(
            "openrouter",
            config["providers"]["openrouter"],
            {
                "model": "openai/unknown-image-model",
                "prompt": "page",
                "output_dir": "outputs",
                "metadata": {"page_render_plan": {"compiler_version": "1.0"}},
            },
            root=ROOT,
        )


def test_openrouter_page_dry_run_rejects_non_image_reference_mime(tmp_path: Path) -> None:
    reference_path = tmp_path / "reference.txt"
    reference_path.write_text("not an image", encoding="utf-8")
    config = load_root_config(ROOT / "config" / "image_generation.json")
    with pytest.raises(ValueError, match="MIME type"):
        merge_provider_defaults(
            "openrouter",
            config["providers"]["openrouter"],
            {
                "prompt": "page",
                "output_dir": "outputs",
                "metadata": {"page_render_plan": {"compiler_version": "1.0"}},
                "image_inputs": [_reference(reference_path, order=1, role="layout")],
            },
            root=ROOT,
        )


def test_openrouter_profiles_enforce_reference_and_output_limits(tmp_path: Path) -> None:
    image = tmp_path / "ref.png"
    Image.new("RGB", (32, 32), (1, 2, 3)).save(image)
    config = load_root_config(ROOT / "config" / "image_generation.json")
    refs = [_reference(image, order=index, role="reference") for index in range(1, 16)]

    with pytest.raises(ValueError, match="上限"):
        merge_provider_defaults(
            "openrouter",
            config["providers"]["openrouter"],
            {
                "model": "nano_banana_2",
                "prompt": "page",
                "output_dir": "outputs",
                "metadata": {"page_render_plan": {"compiler_version": "1.0"}},
                "image_inputs": refs,
            },
            root=ROOT,
        )

    with pytest.raises(ValueError, match="画像枚数"):
        merge_provider_defaults(
            "openrouter",
            config["providers"]["openrouter"],
            {
                "model": "gpt_image_2",
                "prompt": "page",
                "output_dir": "outputs",
                "count": 11,
                "metadata": {"page_render_plan": {"compiler_version": "1.0"}},
            },
            root=ROOT,
        )


def test_openrouter_legacy_payload_stays_chat_completion_shape() -> None:
    config = load_root_config(ROOT / "config" / "image_generation.json")
    merged = merge_provider_defaults(
        "openrouter",
        config["providers"]["openrouter"],
        {"prompt": "legacy", "output_dir": "outputs"},
        root=ROOT,
    )

    payload = build_openrouter_payload(merged)

    assert payload["messages"] == [{"role": "user", "content": "legacy"}]
    assert payload["modalities"] == ["image", "text"]
    assert "input_references" not in payload


def test_openrouter_legacy_reference_inputs_are_rejected_before_send(
    tmp_path: Path,
) -> None:
    image = tmp_path / "ref.png"
    Image.new("RGB", (32, 32), (1, 2, 3)).save(image)
    config = load_root_config(ROOT / "config" / "image_generation.json")

    with pytest.raises(ValueError, match="PageRenderPlan"):
        merge_provider_defaults(
            "openrouter",
            config["providers"]["openrouter"],
            {
                "prompt": "legacy",
                "output_dir": "outputs",
                "image_inputs": [_reference(image, order=1, role="layout")],
            },
            root=ROOT,
        )


def test_openrouter_page_reference_hash_mismatch_stops_before_payload(
    tmp_path: Path,
) -> None:
    image = tmp_path / "ref.png"
    Image.new("RGB", (32, 32), (1, 2, 3)).save(image)
    config = load_root_config(ROOT / "config" / "image_generation.json")
    reference = _reference(image, order=1, role="layout")
    reference["sha256"] = "0" * 64

    with pytest.raises(ValueError, match="hash"):
        merge_provider_defaults(
            "openrouter",
            config["providers"]["openrouter"],
            {
                "prompt": "page",
                "output_dir": "outputs",
                "metadata": {"page_render_plan": {"compiler_version": "1.0"}},
                "image_inputs": [reference],
            },
            root=ROOT,
        )


def test_openrouter_page_dry_run_selects_images_endpoint(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    params_path = tmp_path / "params.json"
    params_path.write_text(
        json.dumps(
            {
                "provider": "openrouter",
                "prompt": "page",
                "output_dir": str(tmp_path / "out"),
                "metadata": {"page_render_plan": {"compiler_version": "1.0"}},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    rc = provider_main(["--params", str(params_path), "--dry-run"])

    captured = capsys.readouterr()
    assert rc == 0
    assert "https://openrouter.ai/api/v1/images" in captured.out
    assert "/chat/completions" not in captured.out


def test_openrouter_image_api_response_is_saved_with_response_model(tmp_path: Path) -> None:
    image_path = tmp_path / "fixture.png"
    Image.effect_noise((256, 256), 30).convert("RGB").save(image_path)
    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    merged = {
        "file_prefix": "manga_01_p01",
        "prompt": "page",
        "metadata": {"page_render_plan": {"compiler_version": "1.0"}},
    }
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    saved = save_openrouter_image_api_response(
        resp={
            "model": "google/gemini-3.1-flash-image",
            "data": [{"b64_json": encoded, "media_type": "image/png"}],
        },
        merged=merged,
        payload={
            "model": "google/gemini-3.1-flash-image",
            "input_references": [
                {"image_url": {"url": f"data:image/png;base64,{encoded}"}}
            ],
        },
        provider_cfg={"min_png_bytes": 1},
        out_dir=out_dir,
        timeout=5,
    )

    assert len(saved) == 1
    metadata = json.loads(Path(saved[0]["json"]).read_text(encoding="utf-8"))
    assert metadata["transport"] == "images"
    assert metadata["response_model"] == "google/gemini-3.1-flash-image"
    assert metadata["response_item"]["b64_json"].startswith("<redacted base64")
    redacted_reference = metadata["openrouter_payload_request"]["input_references"][0]
    assert redacted_reference["image_url"]["url"].startswith("data:image/png;base64,")
    assert encoded not in redacted_reference["image_url"]["url"]
    assert Path(saved[0]["png"]).is_file()


def test_openrouter_image_api_response_normalizes_missing_model_and_writes_outline(
    tmp_path: Path,
) -> None:
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40
    encoded = base64.b64encode(png).decode("ascii")

    saved = save_openrouter_image_api_response(
        resp={"model": "", "data": [{"b64_json": encoded}], "usage": {"cost": 1}},
        merged={
            "file_prefix": "manga_01_p01",
            "prompt": "page",
            "metadata": {"page_render_plan": {"compiler_version": "1.0"}},
        },
        payload={},
        provider_cfg={"min_png_bytes": 1},
        out_dir=tmp_path,
        timeout=5,
    )

    metadata = json.loads(Path(saved[0]["json"]).read_text(encoding="utf-8"))
    assert metadata["response_model"] is None
    outline = "\n".join(metadata["response_key_outline"])
    assert "data[].b64_json:" in outline
    assert encoded not in outline
