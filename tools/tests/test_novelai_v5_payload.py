"""NovelAI V5 の alias・v4_prompt・品質接尾辞・UC・opt-in パラメータ。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from image_provider_generate import (  # noqa: E402
    _novelai_augment_prompt,
    _novelai_combine_uc,
    _novelai_is_v5_model,
    _novelai_uses_v4_condition,
    build_novelai_payload,
    main,
    merge_provider_defaults,
)

NOVELAI_CFG = {
    "default_model": "nai-diffusion-5-full",
    "model_aliases": {
        "v5-full": "nai-diffusion-5-full",
        "v5-curated": "nai-diffusion-5-curated",
    },
    "default_width": 1024,
    "default_height": 1024,
    "default_steps": 28,
    "default_cfg_scale": 6.5,
    "default_sampler_name": "k_euler_ancestral",
    "default_uc_preset": 4,
    "default_quality_toggle": True,
    "default_params_version": 3,
}


def _merged(overrides: dict | None = None) -> dict:
    params = {"prompt": "1girl, standing", "negative_prompt": "user_neg"}
    if overrides:
        params.update(overrides)
    return merge_provider_defaults("novelai", NOVELAI_CFG, params)


def test_v5_alias_resolves_to_full_id() -> None:
    merged = _merged({"model": "v5-full"})
    assert merged["model"] == "nai-diffusion-5-full"


def test_v5_curated_alias_resolves() -> None:
    merged = _merged({"model": "v5-curated"})
    assert merged["model"] == "nai-diffusion-5-curated"


def test_default_model_is_v5() -> None:
    merged = _merged()
    assert merged["model"] == "nai-diffusion-5-full"


def test_config_default_model_is_v5_full() -> None:
    cfg = json.loads(
        (ROOT / "config" / "image_generation.json").read_text(encoding="utf-8")
    )
    novelai = cfg["providers"]["novelai"]
    assert novelai["default_model"] == "nai-diffusion-5-full"
    assert novelai["vibe_model"] == "nai-diffusion-4-5-full"


def test_v5_uses_v4_condition() -> None:
    assert _novelai_uses_v4_condition("nai-diffusion-5-full")
    assert _novelai_uses_v4_condition("nai-diffusion-5-curated")
    assert _novelai_uses_v4_condition("nai-diffusion-5-full-inpainting")
    assert _novelai_uses_v4_condition("nai-diffusion-4-5-full")
    assert not _novelai_uses_v4_condition("nai-diffusion-3")
    assert not _novelai_uses_v4_condition("nai-diffusion-5")
    assert not _novelai_uses_v4_condition("nai-diffusion-50")
    assert not _novelai_uses_v4_condition("nai-diffusion-5-experimental")
    assert not _novelai_uses_v4_condition("prefix-nai-diffusion-5-full")


def test_is_v5_model_includes_inpainting() -> None:
    assert _novelai_is_v5_model("nai-diffusion-5-full")
    assert _novelai_is_v5_model("nai-diffusion-5-curated")
    assert _novelai_is_v5_model("nai-diffusion-5-full-inpainting")
    assert _novelai_is_v5_model("nai-diffusion-5-curated-inpainting")
    assert not _novelai_is_v5_model("nai-diffusion-4-5-full")
    assert not _novelai_is_v5_model("nai-diffusion-5")


def test_v5_quality_suffix_standard_has_no_location() -> None:
    text = _novelai_augment_prompt("nai-diffusion-5-full", "1girl")
    assert text == "1girl, very aesthetic, masterpiece, no text"
    assert "location" not in text


def test_v5_quality_suffix_light() -> None:
    text = _novelai_augment_prompt(
        "nai-diffusion-5-curated", "1girl", quality_preset="light"
    )
    assert text == "1girl, very aesthetic, amazing quality, no text"


def test_quality_toggle_false_skips_suffix() -> None:
    text = _novelai_augment_prompt(
        "nai-diffusion-5-full", "1girl, 「hello」", quality_toggle=False
    )
    assert text == "1girl, 「hello」"


def test_v45_quality_suffix_unchanged() -> None:
    text = _novelai_augment_prompt("nai-diffusion-4-5-full", "1girl")
    assert text == "1girl, location, very aesthetic, masterpiece, no text"


def test_v5_light_uc_differs_from_v45() -> None:
    v5 = _novelai_combine_uc("nai-diffusion-5-full", 5, "")
    v45 = _novelai_combine_uc("nai-diffusion-4-5-full", 5, "")
    assert "0::ai-generated::" in v5
    assert "sepia" in v5
    assert v5 != v45


def test_v5_heavy_uc_matches_v45_full() -> None:
    v5 = _novelai_combine_uc("nai-diffusion-5-full", 4, "")
    v45 = _novelai_combine_uc("nai-diffusion-4-5-full", 4, "")
    assert v5 == v45


def test_v5_payload_includes_v4_prompt() -> None:
    merged = _merged({"model": "v5-full", "uc_preset": 4})
    payload = build_novelai_payload(merged, seed_for_request=1)
    assert payload["model"] == "nai-diffusion-5-full"
    assert "v4_prompt" in payload["parameters"]
    caption = payload["parameters"]["v4_prompt"]["caption"]["base_caption"]
    assert caption.startswith("1girl, standing, very aesthetic, masterpiece, no text")
    assert "location" not in caption
    assert payload["parameters"]["params_version"] == 3
    assert "straight_alpha" not in payload["parameters"]


def test_v5_opt_in_alpha_flags() -> None:
    merged = _merged(
        {
            "model": "v5-full",
            "straight_alpha": True,
            "tag_hint_transparent_background": True,
        }
    )
    payload = build_novelai_payload(merged, seed_for_request=2)
    params = payload["parameters"]
    assert params["straight_alpha"] is True
    assert params["tag_hint_transparent_background"] is True
    assert "upscaled_enhance" not in params


def test_upscaled_enhance_rejected_on_generate() -> None:
    merged = _merged({"model": "v5-full", "upscaled_enhance": True})
    with pytest.raises(ValueError, match="img2img"):
        build_novelai_payload(merged, seed_for_request=3)


def test_upscaled_enhance_allowed_on_img2img() -> None:
    merged = _merged(
        {"model": "v5-full", "action": "img2img", "upscaled_enhance": True}
    )
    payload = build_novelai_payload(merged, seed_for_request=4)
    assert payload["parameters"]["upscaled_enhance"] is True


def test_quality_preset_rejects_unknown() -> None:
    with pytest.raises(ValueError, match="quality_preset"):
        _merged({"quality_preset": "ultra"})


def test_v5_example_fixture_dry_run_shape() -> None:
    fixture = ROOT / "tools" / "fixtures" / "novelai_v5_params.example.json"
    raw = json.loads(fixture.read_text(encoding="utf-8"))
    cfg_path = ROOT / "config" / "image_generation.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    provider_cfg = cfg["providers"]["novelai"]
    merged = merge_provider_defaults("novelai", provider_cfg, raw)
    assert merged["model"] == "nai-diffusion-5-full"
    payload = build_novelai_payload(merged, seed_for_request=int(raw["seed"]))
    assert payload["model"] == "nai-diffusion-5-full"
    assert payload["parameters"]["v4_prompt"]["caption"]["base_caption"]


def test_cli_dry_run_v5_fixture(capsys: pytest.CaptureFixture[str]) -> None:
    fixture = ROOT / "tools" / "fixtures" / "novelai_v5_params.example.json"
    rc = main(["--params", str(fixture), "--dry-run"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["provider"] == "novelai"
    assert data["url"].endswith("/ai/generate-image")
    assert data["payload"]["model"] == "nai-diffusion-5-full"
    params = data["payload"]["parameters"]
    assert "v4_prompt" in params
    assert "v4_negative_prompt" in params
    assert "location" not in params["v4_prompt"]["caption"]["base_caption"]
    assert "straight_alpha" not in params


def test_cli_dry_run_default_example_is_v5(capsys: pytest.CaptureFixture[str]) -> None:
    fixture = ROOT / "tools" / "fixtures" / "novelai_params.example.json"
    rc = main(["--params", str(fixture), "--dry-run"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["payload"]["model"] == "nai-diffusion-5-full"
    caption = data["payload"]["parameters"]["v4_prompt"]["caption"]["base_caption"]
    assert "very aesthetic" in caption
    assert "location" not in caption


def test_cli_dry_run_v5_opt_in_fixture(capsys: pytest.CaptureFixture[str]) -> None:
    fixture = ROOT / "tools" / "fixtures" / "novelai_v5_optin_params.example.json"
    rc = main(["--params", str(fixture), "--dry-run"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    params = data["payload"]["parameters"]
    assert data["payload"]["model"] == "nai-diffusion-5-full"
    assert params["straight_alpha"] is True
    assert params["tag_hint_transparent_background"] is True
    assert "upscaled_enhance" not in params
    assert "v4_prompt" in params
