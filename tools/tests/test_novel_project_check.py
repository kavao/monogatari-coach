#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from novel_project_check import check_novel_project  # noqa: E402

_REQUIRED_FILES = (
    "proposal.md",
    "design_specification.md",
    "config.md",
    "character.md",
    "world.md",
    "_meta.md",
)

_MIN_BYTES = 48
_DUMMY_CONTENT = "x" * _MIN_BYTES

_VALID_CHARACTER_MD = """# 登場人物

## テスト太郎（てすと たろう）
- **名前**: テスト太郎
- **身長**: 約170cm
- **外見**: 黒髪で普通の体格の青年。目は茶色で穏やかな印象を与える。
- **外見の個性**:
  - 黒髪と茶色の瞳で、穏やかな第一印象を与える
  - 慎重な態度と、観察する前に一度目を細める癖
  - 古い町並みに馴染む、地味めの服装の好み
- **性格**: 慎重で観察力があり、信頼した相手には少し冗談を見せる。
- **一人称**: 僕
- **口調**: 丁寧で落ち着いた話し方。「そうかも」「確かめたい」がよく出る。
- **目標**: 町の古い噂の正体を確かめたい。
"""


def _make_valid_project(tmp_path: Path) -> Path:
    """_meta.yaml なしで readiness check が通る最小作品フォルダを作る。"""
    work = tmp_path / "001_test_novel"
    work.mkdir()
    # config.md は novel_code_allocate.verify_work_dir に通るよう novel_ID を入れる
    (work / "config.md").write_text(
        "novel_ID: 001\n" + _DUMMY_CONTENT, encoding="utf-8"
    )
    for name in _REQUIRED_FILES:
        if name == "config.md":
            continue
        content = _VALID_CHARACTER_MD if name == "character.md" else _DUMMY_CONTENT
        (work / name).write_text(content, encoding="utf-8")
    (work / "_novel_text").mkdir()
    (work / "_reader").mkdir()
    return work


def test_meta_yaml_absent_does_not_fail_default_check(tmp_path: Path) -> None:
    """_meta.yaml がなくても通常 readiness check は _meta.yaml 理由では落ちない。"""
    work = _make_valid_project(tmp_path)
    assert not (work / "_meta.yaml").exists()

    result = check_novel_project(
        work,
        min_file_bytes=_MIN_BYTES,
        require_tag_md=False,
        require_manga_dir=False,
        require_meta_yaml=False,
    )
    meta_yaml_issues = [i for i in result["issues"] if "_meta.yaml" in i]
    assert meta_yaml_issues == [], f"_meta.yaml 由来のエラーが出ている: {meta_yaml_issues}"
    assert result["optional"]["meta_yaml_exists"] is False


def test_require_meta_yaml_fails_when_absent(tmp_path: Path) -> None:
    """--require-meta-yaml 指定時、_meta.yaml がなければ NG になる。"""
    work = _make_valid_project(tmp_path)

    result = check_novel_project(
        work,
        min_file_bytes=_MIN_BYTES,
        require_tag_md=False,
        require_manga_dir=False,
        require_meta_yaml=True,
    )
    assert result["ok"] is False
    assert any("_meta.yaml" in i for i in result["issues"])


def test_require_meta_yaml_passes_when_present(tmp_path: Path) -> None:
    """--require-meta-yaml 指定時、_meta.yaml があれば OK になる。"""
    work = _make_valid_project(tmp_path)
    (work / "_meta.yaml").write_text(_DUMMY_CONTENT, encoding="utf-8")

    result = check_novel_project(
        work,
        min_file_bytes=_MIN_BYTES,
        require_tag_md=False,
        require_manga_dir=False,
        require_meta_yaml=True,
    )
    meta_yaml_issues = [i for i in result["issues"] if "_meta.yaml" in i]
    assert meta_yaml_issues == [], f"_meta.yaml 由来のエラーが残っている: {meta_yaml_issues}"
    assert result["optional"]["meta_yaml_exists"] is True


def test_require_illustration_plan_fails_without_chapter_plan(tmp_path: Path) -> None:
    work = _make_valid_project(tmp_path)
    result = check_novel_project(
        work,
        min_file_bytes=_MIN_BYTES,
        require_tag_md=False,
        require_manga_dir=False,
        require_illustration_plan=True,
    )
    assert result["ok"] is False
    assert any("chapter_plan.md" in i for i in result["issues"])


def _illustration_plan_issues(issues: list[str]) -> list[str]:
    return [i for i in issues if "illustrations/plans/" in i]


def test_require_illustration_plan_passes_with_chapter_plan(tmp_path: Path) -> None:
    work = _make_valid_project(tmp_path)
    plans = work / "illustrations" / "plans"
    plans.mkdir(parents=True)
    (plans / "chapter_plan.md").write_text(_DUMMY_CONTENT, encoding="utf-8")

    result = check_novel_project(
        work,
        min_file_bytes=_MIN_BYTES,
        require_tag_md=False,
        require_manga_dir=False,
        require_illustration_plan=True,
    )
    assert _illustration_plan_issues(result["issues"]) == []
    assert result["optional"]["illustration_plan"]["chapter_plan_ok"] is True


def test_require_illustration_plan_requires_cover_when_illustration_00_yaml(tmp_path: Path) -> None:
    work = _make_valid_project(tmp_path)
    plans = work / "illustrations" / "plans"
    pages = work / "illustrations" / "pages"
    plans.mkdir(parents=True)
    pages.mkdir(parents=True)
    (plans / "chapter_plan.md").write_text(_DUMMY_CONTENT, encoding="utf-8")
    (pages / "illustration_00_p01.yaml").write_text("meta:\n  intent: illustration\n", encoding="utf-8")

    result = check_novel_project(
        work,
        min_file_bytes=_MIN_BYTES,
        require_tag_md=False,
        require_manga_dir=False,
        require_illustration_plan=True,
    )
    assert result["ok"] is False
    assert any("cover_plan.md" in i for i in result["issues"])

    (plans / "cover_plan.md").write_text(_DUMMY_CONTENT, encoding="utf-8")
    result2 = check_novel_project(
        work,
        min_file_bytes=_MIN_BYTES,
        require_tag_md=False,
        require_manga_dir=False,
        require_illustration_plan=True,
    )
    assert _illustration_plan_issues(result2["issues"]) == []
    assert result2["optional"]["illustration_plan"]["cover_plan_ok"] is True


def test_character_structure_checked_by_default(tmp_path: Path) -> None:
    """既定では character.md 構造 lint が走り、不正な character.md では NG。"""
    work = _make_valid_project(tmp_path)
    (work / "character.md").write_text(_DUMMY_CONTENT, encoding="utf-8")

    result = check_novel_project(
        work,
        min_file_bytes=_MIN_BYTES,
        require_tag_md=False,
        require_manga_dir=False,
    )
    ch = result["optional"].get("character_structure") or {}
    assert ch != {}
    assert ch.get("profile") == "plan"
    assert result["ok"] is False
    assert any("character.md" in i for i in result["issues"])


def test_no_character_structure_skips_lint(tmp_path: Path) -> None:
    """require_character_structure=False で構造 lint をスキップできる。"""
    work = _make_valid_project(tmp_path)
    (work / "character.md").write_text(_DUMMY_CONTENT, encoding="utf-8")

    result = check_novel_project(
        work,
        min_file_bytes=_MIN_BYTES,
        require_tag_md=False,
        require_manga_dir=False,
        require_character_structure=False,
    )
    assert "character_structure" not in result["optional"]
    char_issues = [i for i in result["issues"] if "character.md" in i and "構造" in i]
    assert char_issues == []


def _write_design_schedule(work: Path, schedule_lines: str) -> None:
    """design_specification.md に汎用的な執筆スケジュール節を書き込む。"""
    (work / "design_specification.md").write_text(
        "# 設計書\n\n## 執筆スケジュール\n" + schedule_lines + "\n",
        encoding="utf-8",
    )


def _write_chapter(work: Path, filename: str) -> None:
    (work / "_novel_text" / filename).write_text(_DUMMY_CONTENT, encoding="utf-8")


def test_story_sync_warns_when_chapter_written_but_schedule_not_started(tmp_path: Path) -> None:
    """本文があるのにスケジュールが未着手なら WARNING（既定では NG にしない）。"""
    work = _make_valid_project(tmp_path)
    _write_design_schedule(work, "- 第1章：完了\n- 第2章：未着手")
    _write_chapter(work, "novel_text01.md")
    _write_chapter(work, "novel_text02.md")

    result = check_novel_project(
        work,
        min_file_bytes=_MIN_BYTES,
        require_tag_md=False,
        require_manga_dir=False,
        require_character_structure=False,
        check_story_sync=True,
    )
    # WARNING は issues（NG）に入れない
    assert not any("本文・設計書同期" in i for i in result["issues"])
    warns = result["warnings"]
    assert any("第2章" in w and "未着手" in w for w in warns)
    assert not any("第1章" in w for w in warns)
    assert result["optional"]["story_sync"]["ok"] is False


def test_story_sync_strict_marks_ng(tmp_path: Path) -> None:
    """--strict-story-sync 相当では食い違いを NG（失敗）扱いにする。"""
    work = _make_valid_project(tmp_path)
    _write_design_schedule(work, "- 第1章：未着手")
    _write_chapter(work, "novel_text01.md")

    result = check_novel_project(
        work,
        min_file_bytes=_MIN_BYTES,
        require_tag_md=False,
        require_manga_dir=False,
        require_character_structure=False,
        check_story_sync=True,
        strict_story_sync=True,
    )
    assert result["ok"] is False
    assert any("本文・設計書同期" in i for i in result["issues"])


def test_story_sync_warns_when_split_files_missing_in_design(tmp_path: Path) -> None:
    """前後半（項）ファイルがあるのに設計書に分割記載がなければ WARNING。"""
    work = _make_valid_project(tmp_path)
    _write_design_schedule(work, "- 第1章：完了")
    _write_chapter(work, "novel_text01_1.md")
    _write_chapter(work, "novel_text01_2.md")

    result = check_novel_project(
        work,
        min_file_bytes=_MIN_BYTES,
        require_tag_md=False,
        require_manga_dir=False,
        require_character_structure=False,
        check_story_sync=True,
    )
    assert any("分割" in w for w in result["warnings"])


def test_story_sync_no_warning_when_synced(tmp_path: Path) -> None:
    """スケジュールが本文の実在状況と整合していれば WARNING は出ない。"""
    work = _make_valid_project(tmp_path)
    _write_design_schedule(work, "- 第1章（前半・後半に分割）：完了")
    _write_chapter(work, "novel_text01_1.md")
    _write_chapter(work, "novel_text01_2.md")

    result = check_novel_project(
        work,
        min_file_bytes=_MIN_BYTES,
        require_tag_md=False,
        require_manga_dir=False,
        require_character_structure=False,
        check_story_sync=True,
    )
    sync = result["optional"]["story_sync"]
    assert sync["ok"] is True
    assert sync["warnings"] == []


def test_story_sync_skipped_when_no_text_files(tmp_path: Path) -> None:
    """本文ファイルが無ければ同期チェックはスキップ扱い（WARNING なし）。"""
    work = _make_valid_project(tmp_path)
    _write_design_schedule(work, "- 第1章：未着手")

    result = check_novel_project(
        work,
        min_file_bytes=_MIN_BYTES,
        require_tag_md=False,
        require_manga_dir=False,
        require_character_structure=False,
        check_story_sync=True,
    )
    assert result["warnings"] == []
    assert result["optional"]["story_sync"]["ok"] is True
