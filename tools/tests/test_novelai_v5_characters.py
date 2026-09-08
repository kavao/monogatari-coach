"""NovelAI V5 Phase 3: pipe → char_captions と座標のオプトイン。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from image_provider_generate import (  # noqa: E402
    _novelai_parse_center,
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
    "default_use_coords": False,
    "default_split_pipe_characters": False,
}


PIPE_PROMPT = "classroom | 1girl, red hair | 1boy, blue hair"


def _merged(overrides: dict | None = None) -> dict:
    params = {"prompt": PIPE_PROMPT, "negative_prompt": "user_neg"}
    if overrides:
        params.update(overrides)
    return merge_provider_defaults("novelai", NOVELAI_CFG, params)


def test_default_keeps_pipe_in_base() -> None:
    merged = _merged({"model": "v5-full"})
    payload = build_novelai_payload(merged, seed_for_request=1)
    caption = payload["parameters"]["v4_prompt"]["caption"]
    assert payload["parameters"]["characterPrompts"] == []
    assert caption["char_captions"] == []
    assert "|" in payload["input"]
    assert payload["input"].startswith("classroom, very aesthetic")
    assert "1girl, red hair" in payload["input"]
    assert payload["parameters"]["use_coords"] is False


def test_split_pipe_to_char_captions() -> None:
    merged = _merged({"model": "v5-full", "split_pipe_characters": True})
    payload = build_novelai_payload(merged, seed_for_request=1)
    caption = payload["parameters"]["v4_prompt"]["caption"]
    assert caption["base_caption"] == (
        "classroom, very aesthetic, masterpiece, no text"
    )
    assert "|" not in caption["base_caption"]
    assert payload["input"] == caption["base_caption"]
    assert [c["char_caption"] for c in caption["char_captions"]] == [
        "1girl, red hair",
        "1boy, blue hair",
    ]
    assert payload["parameters"]["v4_prompt"]["use_coords"] is False
    for item in caption["char_captions"]:
        assert item["centers"] == [{"x": 0.5, "y": 0.5}]
    prompts = payload["parameters"]["characterPrompts"]
    assert [p["prompt"] for p in prompts] == [
        "1girl, red hair",
        "1boy, blue hair",
    ]
    assert prompts[0]["center"] == {"x": 0.5, "y": 0.5}


def test_centers_enable_use_coords() -> None:
    merged = _merged(
        {
            "model": "v5-full",
            "split_pipe_characters": True,
            "centers": [{"x": 0.2, "y": 0.5}, {"x": 0.8, "y": 0.5}],
        }
    )
    payload = build_novelai_payload(merged, seed_for_request=1)
    assert payload["parameters"]["use_coords"] is True
    assert payload["parameters"]["v4_prompt"]["use_coords"] is True
    centers = [
        c["centers"][0]
        for c in payload["parameters"]["v4_prompt"]["caption"]["char_captions"]
    ]
    assert centers == [{"x": 0.2, "y": 0.5}, {"x": 0.8, "y": 0.5}]


def test_use_coords_false_keeps_centers() -> None:
    merged = _merged(
        {
            "model": "v5-full",
            "split_pipe_characters": True,
            "centers": [{"x": 0.2, "y": 0.4}, {"x": 0.8, "y": 0.4}],
            "use_coords": False,
        }
    )
    payload = build_novelai_payload(merged, seed_for_request=1)
    assert payload["parameters"]["use_coords"] is False
    assert payload["parameters"]["v4_prompt"]["use_coords"] is False
    first = payload["parameters"]["v4_prompt"]["caption"]["char_captions"][0]
    assert first["centers"] == [{"x": 0.2, "y": 0.4}]


def test_centers_count_mismatch() -> None:
    merged = _merged(
        {
            "model": "v5-full",
            "split_pipe_characters": True,
            "centers": [{"x": 0.2, "y": 0.5}],
        }
    )
    with pytest.raises(ValueError, match="centers"):
        build_novelai_payload(merged, seed_for_request=1)


def test_grid_center_presets() -> None:
    assert _novelai_parse_center("C3") == {"x": 0.5, "y": 0.5}
    assert _novelai_parse_center("c3") == {"x": 0.5, "y": 0.5}
    assert _novelai_parse_center("A1") == {"x": 0.1, "y": 0.1}
    assert _novelai_parse_center("E5") == {"x": 0.9, "y": 0.9}


def test_invalid_center_range() -> None:
    with pytest.raises(ValueError, match="0"):
        _novelai_parse_center({"x": 1.5, "y": 0.5})


def test_invalid_grid_token() -> None:
    with pytest.raises(ValueError, match="A1"):
        _novelai_parse_center("F9")


def test_explicit_character_prompts() -> None:
    merged = _merged(
        {
            "model": "v5-full",
            "prompt": "classroom interior",
            "character_prompts": [
                {"prompt": "1girl, red hair", "center": "B2", "uc": "bad hands"},
                {"prompt": "1boy, blue hair", "center": [0.8, 0.4]},
            ],
        }
    )
    payload = build_novelai_payload(merged, seed_for_request=1)
    caption = payload["parameters"]["v4_prompt"]["caption"]
    assert caption["base_caption"].startswith("classroom interior, very aesthetic")
    assert "|" not in payload["input"]
    chars = caption["char_captions"]
    assert chars[0]["centers"][0] == {"x": 0.3, "y": 0.3}
    assert chars[1]["centers"][0] == {"x": 0.8, "y": 0.4}
    neg = payload["parameters"]["v4_negative_prompt"]["caption"]["char_captions"]
    assert neg[0]["char_caption"] == "bad hands"
    assert neg[1]["char_caption"] == ""
    assert payload["parameters"]["use_coords"] is True
    assert payload["parameters"]["characterPrompts"][0]["uc"] == "bad hands"


def test_character_prompts_win_over_pipe_right() -> None:
    merged = _merged(
        {
            "model": "v5-full",
            "prompt": "classroom | ignored girl | ignored boy",
            "split_pipe_characters": True,
            "character_prompts": [{"prompt": "1girl, explicit"}],
        }
    )
    payload = build_novelai_payload(merged, seed_for_request=1)
    chars = payload["parameters"]["v4_prompt"]["caption"]["char_captions"]
    assert [c["char_caption"] for c in chars] == ["1girl, explicit"]
    assert payload["parameters"]["v4_prompt"]["caption"]["base_caption"].startswith(
        "classroom,"
    )


def test_character_prompts_rejects_non_list() -> None:
    with pytest.raises(ValueError, match="character_prompts"):
        _merged({"character_prompts": "1girl"})


def test_cli_dry_run_chars_fixture(capsys: pytest.CaptureFixture[str]) -> None:
    fixture = ROOT / "tools" / "fixtures" / "novelai_v5_chars_params.example.json"
    rc = main(["--params", str(fixture), "--dry-run"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    params = data["payload"]["parameters"]
    caption = params["v4_prompt"]["caption"]
    assert data["payload"]["model"] == "nai-diffusion-5-full"
    assert "|" not in caption["base_caption"]
    assert caption["base_caption"].startswith("classroom interior")
    assert [c["char_caption"] for c in caption["char_captions"]] == [
        "1girl, red hair, school uniform",
        "1boy, blue hair, school uniform",
    ]
    assert caption["char_captions"][0]["centers"] == [{"x": 0.3, "y": 0.5}]
    assert params["use_coords"] is True
    assert params["v4_prompt"]["use_coords"] is True
    assert len(params["characterPrompts"]) == 2
