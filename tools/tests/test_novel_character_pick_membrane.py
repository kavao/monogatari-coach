#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import random
import sys
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOWTO_TOOLS = ROOT / "_how_to" / "tools"
MATURE_JSON = ROOT / "_how_to" / "episode" / "mature" / "episode_mature.json"

pytestmark = pytest.mark.skipif(
    not (HOWTO_TOOLS / "novel_character_pick.py").is_file(),
    reason="_how_to/tools/novel_character_pick.py が無い",
)

sys.path.insert(0, str(HOWTO_TOOLS))
sys.path.insert(0, str(ROOT / "tools"))

from novel_character_pick import pick_label, pick_unused_membrane  # noqa: E402


def _sample_mature() -> dict:
    return {
        "未使用膜": {
            "膜の状態": {
                "内訳": [{"タイプ": "無傷で残存", "相対確率": 1.0}],
            },
            "形状": {
                "内訳": [
                    {"タイプ": "半月状未使用膜", "相対確率": 0.0},
                    {"タイプ": "輪状未使用膜", "相対確率": 0.0},
                    {"タイプ": "膜状未使用膜", "相対確率": 0.0},
                    {"タイプ": "小孔性未使用膜", "相対確率": 0.0},
                    {"タイプ": "筋状未使用膜", "相対確率": 1.0},
                ]
            },
            "残存度": {
                "内訳": [{"タイプ": "はっきり残っている", "相対確率": 1.0}],
            },
            "破綻後の様子": {
                "内訳": [{"タイプ": "索状・不規則な跡が複数", "相対確率": 1.0}],
            },
            "若妖精": {
                "内訳": [
                    {
                        "タイプ": "無傷で残存・はっきり（芽生〜双葉寄り）。半月または輪状",
                        "相対確率": 1.0,
                    }
                ]
            },
        }
    }


def test_fairy_intact_uses_shape_weights_not_bundled_crescent_or_annular() -> None:
    mature = _sample_mature()
    picked = pick_label(mature, "未使用膜", "若妖精", random.Random(0))
    assert picked is not None
    assert picked["形状"]["hint"] == "筋状未使用膜"
    assert "半月または輪状" not in picked["hint"]
    assert "残存度" not in picked
    assert "はっきり" in picked["膜の状態"]["hint"]


def test_young_intact_still_picks_remaining() -> None:
    mature = _sample_mature()
    picked = pick_label(mature, "未使用膜", "若者", random.Random(0))
    assert picked is not None
    assert picked["形状"]["hint"] == "筋状未使用膜"
    assert picked["残存度"]["hint"] == "はっきり残っている"


def test_fairy_post_break_picks_aftermath() -> None:
    mature = _sample_mature()
    mature["未使用膜"]["若妖精"]["内訳"] = [
        {"タイプ": "部分的破綻・痕跡あり（青葉〜実りで稀〜あり）", "相対確率": 1.0}
    ]
    picked = pick_unused_membrane(mature, random.Random(1), "若妖精")
    assert picked is not None
    assert "形状" not in picked
    assert picked["破綻後の様子"]["hint"] == "索状・不規則な跡が複数"


@pytest.mark.skipif(not MATURE_JSON.is_file(), reason="episode_mature.json が無い")
def test_live_fairy_intact_can_draw_rare_shapes() -> None:
    from novel_character_pick import load_mature

    mature = load_mature(MATURE_JSON)
    shapes = Counter()
    intact = 0
    for seed in range(800):
        picked = pick_label(mature, "未使用膜", "若妖精", random.Random(seed))
        assert picked is not None
        assert "半月または輪状" not in picked["hint"]
        shape = (picked.get("形状") or {}).get("hint")
        if shape:
            intact += 1
            shapes[shape] += 1
    assert intact > 0
    assert "筋状未使用膜" in shapes
    assert "膜状未使用膜" in shapes
    assert "半月状未使用膜" in shapes
    assert "輪状未使用膜" in shapes
