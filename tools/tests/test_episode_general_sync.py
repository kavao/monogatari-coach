"""Tests for _how_to/tools/episode_json_sync and episode_general_sync."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOW_TO_TOOLS = ROOT / "_how_to" / "tools"
sys.path.insert(0, str(HOW_TO_TOOLS))

from episode_json_sync.hooks import build_hooks_section, parse_hooks_md  # noqa: E402
from episode_general_sync import sync_general_json  # noqa: E402

FIXTURE_MD = ROOT / "tools" / "fixtures" / "episode_hooks" / "sample_hooks.md"
EXAMPLE_HOOKS = ROOT / "_how_to.example" / "episode" / "general" / "episode_hooks.md"


def test_parse_hooks_md_fixture():
    subs = parse_hooks_md(FIXTURE_MD)
    assert set(subs) == {"テスト軸A", "テスト軸B"}
    assert subs["テスト軸A"]["解説"] == "軸Aの解説文です。"
    assert len(subs["テスト軸A"]["内訳"]) == 2
    assert subs["テスト軸A"]["内訳"][0]["シチュエーション"] == "シチュエーションA1"
    assert subs["テスト軸A"]["内訳"][0]["説明"] == "説明A1"
    assert subs["テスト軸A"]["内訳"][1]["シチュエーション"] == "シチュエーションA2"
    assert "説明" not in subs["テスト軸A"]["内訳"][1]


def test_build_hooks_section():
    subs = parse_hooks_md(FIXTURE_MD)
    section = build_hooks_section(subcategories=subs, overview="overview text")
    assert section["大分類解説"] == "overview text"
    assert "テスト軸A" in section["サブカテゴリ"]


def test_example_hooks_md_minimum_counts():
    subs = parse_hooks_md(EXAMPLE_HOOKS)
    assert len(subs) >= 4
    for key in ("帰省と身寄せ", "依頼と訪問", "違和感と発見", "異界の兆し"):
        assert key in subs
        assert len(subs[key]["内訳"]) >= 8


def test_sync_general_json_dry_run(tmp_path: Path):
    hooks = tmp_path / "episode_hooks.md"
    hooks.write_text(
        "## 単軸\n\n- 一件目 — 補足\n",
        encoding="utf-8",
    )
    out_json = tmp_path / "episode_general.json"
    out_json.write_text('{"進行パターン": {"内訳": []}}', encoding="utf-8")

    data = sync_general_json(tmp_path, out_json, dry_run=True)
    assert data["_meta"]["schema_version"] == "1.1"
    hook = data["冒頭フック"]
    assert hook["サブカテゴリ"]["単軸"]["内訳"][0]["シチュエーション"] == "一件目"
    assert "probability_note" in data["_meta"]

    # dry-run must not write
    raw = json.loads(out_json.read_text(encoding="utf-8"))
    assert "冒頭フック" not in raw