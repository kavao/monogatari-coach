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
        (work / name).write_text(_DUMMY_CONTENT, encoding="utf-8")
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
