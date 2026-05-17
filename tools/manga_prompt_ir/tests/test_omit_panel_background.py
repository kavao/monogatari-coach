from __future__ import annotations

import sys
from pathlib import Path

import pytest

_TOOLS_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_TOOLS_ROOT))

from image_provider_novel_manga_batch import (  # noqa: E402
    apply_omit_panel_background_tags,
    is_background_prompt_tag,
    yaml_panel_tags,
)


def test_is_background_prompt_tag_detects_bathroom_tokens() -> None:
    assert is_background_prompt_tag("cream_beige_tiles")
    assert is_background_prompt_tag("bathroom")
    assert not is_background_prompt_tag("close-up")
    assert not is_background_prompt_tag("blushing")


def test_apply_omit_panel_background_adds_simple_background() -> None:
    out = apply_omit_panel_background_tags(["bathroom", "steam", "blushing"])
    assert "bathroom" not in out
    assert "steam" not in out
    assert "blushing" in out
    assert "simple_background" in out


def test_yaml_panel_tags_omit_panel_background_skips_scene() -> None:
    page = {
        "scene": {
            "location_en": "Tōdō family bathroom",
            "background_notes_en": "cream-beige tiles, white bathtub",
            "time_of_day_en": "night",
        },
        "manga": {"genre_tags": ["manga"], "background_tags": ["interior"]},
        "panels": [],
    }
    panel = {
        "prompt_tags": ["bathroom", "steam", "surprised"],
        "lighting": {"quality": "warm amber glow"},
        "camera": {"shot_size": "medium shot"},
    }
    characters: dict = {}
    with_bg = yaml_panel_tags(
        page, panel, characters, single_panel=True, omit_panel_background=False
    )
    without_bg = yaml_panel_tags(
        page, panel, characters, single_panel=True, omit_panel_background=True
    )
    assert "Tōdō family bathroom" in with_bg or any(
        "bathroom" in t.lower() for t in with_bg
    )
    assert not any(is_background_prompt_tag(t) for t in without_bg)
    assert "simple_background" in without_bg
    assert "surprised" in without_bg
    assert "medium shot" in without_bg


def test_omit_background_keeps_summary_en_context() -> None:
    page = {
        "scene": {"location_en": "bathroom", "background_notes_en": "tiles"},
        "manga": {},
        "panels": [],
    }
    panel = {
        "summary_en": "Miu opens the door while Yuma soaks.",
        "prompt_tags": ["bathroom", "surprised"],
    }
    tags = yaml_panel_tags(
        page,
        panel,
        {},
        single_panel=True,
        omit_panel_background=True,
        include_panel_summary=True,
    )
    joined = ", ".join(tags)
    assert "Miu opens the door" in joined
    assert "simple_background" in joined
    assert "bathroom" not in joined
