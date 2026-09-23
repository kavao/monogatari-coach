from __future__ import annotations

import sys
from pathlib import Path

_TOOLS_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_TOOLS_ROOT))

from manga_prompt_ir.scene_prompt import (
    camera_tag_tokens,
    composition_tag_tokens,
    subject_situational_tag_tokens,
    subject_tag_line_token,
)
from image_provider_novel_manga_batch import yaml_panel_tags


def test_composition_prefers_en_and_drops_cjk_legacy() -> None:
    comp = {
        "framing": "medium shot",
        "framing_en": "wide shot",
        "focus": "光る画面",
        "focus_en": "glowing phone screen",
    }
    assert composition_tag_tokens(comp) == ["wide shot", "glowing phone screen"]


def test_composition_allows_ascii_only_legacy() -> None:
    comp = {"framing": "medium shot", "focus": "phone screen glow"}
    assert composition_tag_tokens(comp) == ["medium shot", "phone screen glow"]


def test_camera_uses_en_only_when_set() -> None:
    cam = {
        "angle": "high angle",
        "angle_en": "low angle",
        "shot_size": "medium shot",
        "view_en": "solo face",
    }
    assert camera_tag_tokens(cam) == ["low angle", "medium shot", "solo face"]


def test_camera_uses_english_legacy_view_when_view_en_is_empty() -> None:
    assert camera_tag_tokens({"view": "two faces"}) == ["two faces"]


def test_yaml_panel_tags_keeps_legacy_pov_when_view_en_is_empty() -> None:
    panel = {
        "prompt_tags": ["pov"],
        "camera": {"view_en": ""},
        "subjects": [],
    }
    page = {"manga": {}, "scene": {}, "panels": [panel]}

    tags = yaml_panel_tags(page, panel, {})

    assert tags.count("pov") == 1


def test_yaml_panel_tags_emits_view_pov_once_without_prompt_tag() -> None:
    panel = {
        "prompt_tags": [],
        "camera": {"view_en": "pov"},
        "subjects": [],
    }
    page = {"manga": {}, "scene": {}, "panels": [panel]}

    tags = yaml_panel_tags(page, panel, {})

    assert tags.count("pov") == 1


def test_subject_no_japanese_description_in_tag_token() -> None:
    assert subject_tag_line_token({"description": "机の上のカップ"}) == "subject"
    assert (
        subject_tag_line_token({"description_en": "coffee mug on desk", "description": "机の上"})
        == "coffee mug on desk"
    )


def test_subject_situational_prefers_en() -> None:
    sub = {
        "pose_action": "走る",
        "pose_action_en": "running toward door",
        "expression": "泣き顔",
        "expression_en": "tearful face",
        "position": "foreground",
    }
    assert subject_situational_tag_tokens(sub) == [
        "running toward door",
        "tearful face",
        "foreground",
    ]
