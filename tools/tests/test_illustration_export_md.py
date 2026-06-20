#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from novel_prompt_ir_export_md import (  # noqa: E402
    group_illustration_pages,
    illustration_asset_stem,
    render_illustration_md,
)


def test_illustration_asset_stem() -> None:
    assert illustration_asset_stem(Path("illustration_01_p01.yaml")) == "illustration_01"
    assert illustration_asset_stem(Path("illustration_00_p02.yaml")) == "illustration_00"


def test_group_illustration_pages_sorts_by_filename() -> None:
    pages = [
        (Path("illustration_01_p02.yaml"), {"panels": []}),
        (Path("illustration_01_p01.yaml"), {"panels": []}),
    ]
    grouped = group_illustration_pages(pages)
    assert list(grouped.keys()) == ["illustration_01"]
    names = [p.name for p, _ in grouped["illustration_01"] if p]
    assert names == ["illustration_01_p01.yaml", "illustration_01_p02.yaml"]


def test_render_illustration_md_includes_header_and_tags() -> None:
    page = {
        "meta": {"intent": "illustration", "source_anchor": "novel_text01"},
        "manga": {"panel_layout": "枠線なし"},
        "scene": {"location": "部屋", "time_of_day": "朝"},
        "render_instruction": {"task": "章末尾挿絵"},
        "panels": [
            {
                "panel_id": 1,
                "summary": "テスト概要",
                "subjects": [],
                "composition": {},
                "camera": {},
                "prompt_tags": ["1girl", "morning light"],
            }
        ],
        "technical": {"negative_tags": ["bad anatomy"]},
    }
    md = render_illustration_md(
        [(Path("illustrations/pages/illustration_01_p01.yaml"), page)],
        {},
        title="挿絵 illustration_01",
    )
    assert "illustration-prompt-ir互換ヘッダ" in md
    assert "illustration_01_p01.yaml" in md
    assert "Danbooru Tags" in md
    assert "1girl" in md
    assert "bad_anatomy" in md
