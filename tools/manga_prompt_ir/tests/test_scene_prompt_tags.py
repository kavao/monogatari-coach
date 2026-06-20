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
    cam = {"angle": "high angle", "angle_en": "low angle", "shot_size": "medium shot"}
    assert camera_tag_tokens(cam) == ["low angle", "medium shot"]


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
