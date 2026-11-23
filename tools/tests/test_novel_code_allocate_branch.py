#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""改訂枝（051a_タイトル）の名前解析・採番・検証。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import novel_code_allocate as nca  # noqa: E402
import novel_onboard  # noqa: E402


def _config(code: str, extra: str = "") -> str:
    return (
        "## 基本情報\n\n| 項目 | 内容 |\n|------|------|\n"
        f"| novel_ID | {code} |\n{extra}"
    )


def _make(novels: Path, name: str, config: str) -> Path:
    work = novels / name
    work.mkdir(parents=True)
    (work / "config.md").write_text(config, encoding="utf-8")
    return work


@pytest.mark.parametrize(
    ("name", "code", "branch", "title"),
    [
        ("051_タイトル", 51, None, "タイトル"),
        ("051a_タイトル", 51, "a", "タイトル"),
        ("051z_a_b", 51, "z", "a_b"),
        ("000_old_man_next_door's_cake", 0, None, "old_man_next_door's_cake"),
        ("051_a_タイトル", 51, None, "a_タイトル"),
    ],
)
def test_parse_folder_name(name: str, code: int, branch: str | None, title: str) -> None:
    parsed = nca.parse_folder_name(name)
    assert parsed is not None
    assert (parsed.code, parsed.branch, parsed.title) == (code, branch, title)


@pytest.mark.parametrize("name", ["051ab_タイトル", "051A_タイトル", "abc_タイトル", "051"])
def test_parse_folder_name_rejects(name: str) -> None:
    assert nca.parse_folder_name(name) is None


def test_label_keeps_zero_padding() -> None:
    assert nca.parse_folder_name("051a_x").label == "051a"
    assert nca.parse_folder_name("051_x").label == "051"


def test_scan_branch_is_not_duplicate_and_does_not_consume_next(tmp_path: Path) -> None:
    novels = tmp_path / "novels"
    _make(novels, "051_元", _config("051"))
    _make(novels, "051a_元", _config("051"))
    _make(novels, "051ab_悪い", _config("051"))
    _make(novels, "052b_孤児", _config("052"))

    data = nca.scan_novels(novels)

    assert data["duplicates"] == []
    assert data["next_code"] == 53
    assert data["invalid_branch"] == ["051ab_悪い"]
    assert data["unmatched"] == []
    assert data["orphan_branches"] == ["052b_孤児"]


def test_scan_same_code_same_branch_is_duplicate(tmp_path: Path) -> None:
    novels = tmp_path / "novels"
    _make(novels, "051_元", _config("051"))
    _make(novels, "051_別", _config("051"))
    data = nca.scan_novels(novels)
    assert data["duplicates"] == [
        {"code": 51, "branch": None, "folders": ["051_元", "051_別"]}
    ]


def _branch_config(**over: str) -> str:
    rows = {"branch": "a", "parent_ID": "051", "branch_reason": "revision"}
    rows.update(over)
    extra = "".join(f"| {k} | {v} |\n" for k, v in rows.items() if v is not None)
    return _config("051", extra)


def test_verify_branch_ok(tmp_path: Path) -> None:
    novels = tmp_path / "novels"
    _make(novels, "051_元", _config("051"))
    work = _make(novels, "051a_元", _branch_config())

    r = nca.verify_work_dir(work)

    assert r["ok"], r["issues"]
    assert r["label"] == "051a"
    assert r["parent_folders"] == ["051_元"]


def test_verify_trunk_still_ok(tmp_path: Path) -> None:
    novels = tmp_path / "novels"
    work = _make(novels, "051_元", _config("051"))
    assert nca.verify_work_dir(work)["ok"]


@pytest.mark.parametrize(
    ("over", "needle"),
    [
        ({"branch": "b"}, "branch (b)"),
        ({"parent_ID": None}, "parent_ID がありません"),
        ({"parent_ID": "050"}, "parent_ID (050)"),
        ({"branch_reason": None}, "branch_reason"),
        ({"branch_reason": "other"}, "未知の値"),
    ],
)
def test_verify_branch_issues(tmp_path: Path, over: dict, needle: str) -> None:
    novels = tmp_path / "novels"
    _make(novels, "051_元", _config("051"))
    work = _make(novels, "051a_元", _branch_config(**over))
    r = nca.verify_work_dir(work)
    assert not r["ok"]
    assert any(needle in i for i in r["issues"]), r["issues"]


def test_verify_branch_without_trunk(tmp_path: Path) -> None:
    novels = tmp_path / "novels"
    work = _make(novels, "051a_元", _branch_config())
    r = nca.verify_work_dir(work)
    assert not r["ok"]
    assert any("元フォルダ" in i for i in r["issues"])


def test_verify_trunk_with_branch_row_fails(tmp_path: Path) -> None:
    novels = tmp_path / "novels"
    work = _make(novels, "051_元", _config("051", "| branch | a |\n"))
    r = nca.verify_work_dir(work)
    assert not r["ok"]


def test_verify_invalid_branch_name(tmp_path: Path) -> None:
    novels = tmp_path / "novels"
    work = _make(novels, "051ab_元", _config("051"))
    r = nca.verify_work_dir(work)
    assert any("枝が規則外" in i for i in r["issues"])


def test_onboard_refuses_new_branch_folder(tmp_path: Path, monkeypatch, capsys) -> None:
    (tmp_path / "novels" / "051_元").mkdir(parents=True)
    monkeypatch.setattr(novel_onboard, "repo_root", lambda: tmp_path)

    assert novel_onboard.main(["novels/051a_元", "--dry-run"]) == 2

    assert "novel_branch.py fork" in capsys.readouterr().err
    assert not (tmp_path / "novels" / "051a_元").exists()


def test_onboard_by_title_skips_branch_in_numbering(tmp_path: Path, monkeypatch, capsys) -> None:
    novels = tmp_path / "novels"
    _make(novels, "051_元", _config("051"))
    _make(novels, "051a_元", _branch_config())
    monkeypatch.setattr(novel_onboard, "repo_root", lambda: tmp_path)

    assert novel_onboard.main(["新作", "--dry-run"]) == 0
    assert "052_新作" in capsys.readouterr().out


def test_project_check_bootstrap_refuses_new_branch(tmp_path: Path, capsys) -> None:
    from novel_project_check import main

    (tmp_path / "051_元").mkdir()
    assert main([str(tmp_path / "051a_元"), "--bootstrap"]) == 2
    assert "改訂枝" in capsys.readouterr().err
    assert not (tmp_path / "051a_元").exists()


def test_compare_work_code_accepts_branch(tmp_path: Path) -> None:
    from ai_writer.compare import work_code

    assert work_code(tmp_path / "051a_元") == "051a"
    assert work_code(tmp_path / "051_元") == "051"
