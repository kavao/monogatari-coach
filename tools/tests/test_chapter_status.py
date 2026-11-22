#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""章末ステータス（CHAPTER_STATUS）の共通処理と、字数・句読点・lint の除外。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import chapter_status as cs  # noqa: E402
from novel_char_count import count_chars  # noqa: E402
from novel_punctuation_metrics import extract_body  # noqa: E402


def _config(rows: str) -> str:
    return "# 作品\n\n## 基本情報\n\n| 項目 | 値 |\n|---|---|\n" + rows + "\n"


BODY = "　朝の道を歩いた。\n\n　風が冷たかった。\n"
BLOCK = "<!-- status:begin -->\n【告】体力が上がりました。\n<!-- status:end -->\n"
CHAPTER = BODY + "\n" + BLOCK


# ── config.md ─────────────────────────────


def test_missing_row_is_synopsis() -> None:
    config = cs.parse_chapter_status(_config("| 作品名 | 試し |"))
    assert config.mode is cs.ChapterStatusMode.SYNOPSIS
    assert config.style is None
    assert config.source == "implicit:no-row"


def test_text_with_style() -> None:
    config = cs.parse_chapter_status(
        _config("| CHAPTER_STATUS | TEXT |\n| CHAPTER_STATUS_STYLE | notice_log |")
    )
    assert config.mode is cs.ChapterStatusMode.TEXT
    assert config.style == "notice_log"


@pytest.mark.parametrize(
    "rows",
    [
        "| CHAPTER_STATUS | ON |",
        "| CHAPTER_STATUS | TEXT |",
        "| CHAPTER_STATUS | SYNOPSIS |\n| CHAPTER_STATUS_STYLE | diff |",
        "| CHAPTER_STATUS | TEXT |\n| CHAPTER_STATUS_STYLE | unknown |",
        "| CHAPTER_STATUS | OFF |\n| CHAPTER_STATUS | TEXT |",
        "| chapter_status | OFF |",
    ],
)
def test_config_errors(rows: str) -> None:
    with pytest.raises(cs.ChapterStatusConfigError):
        cs.parse_chapter_status(_config(rows))


def test_missing_config_file(tmp_path: Path) -> None:
    config = cs.load_chapter_status(tmp_path / "config.md")
    assert config.mode is cs.ChapterStatusMode.SYNOPSIS


# ── ブロックの検出と除外 ─────────────────────────────


def test_scan_finds_block_and_lines() -> None:
    text = BODY + "<!-- status:line -->《告知》門が開いた。\n" + "\n" + BLOCK
    result = cs.scan(text)
    assert len(result.blocks) == 1
    assert result.blocks[0].content == "【告】体力が上がりました。\n"
    assert result.line_marks == (4,)
    assert result.errors == ()


def test_scan_reports_unclosed_and_stray() -> None:
    assert cs.scan("<!-- status:begin -->\nx\n").errors
    assert cs.scan("x\n<!-- status:end -->\n").errors


def test_body_end_excludes_blank_line_before_block() -> None:
    body, tail = cs.split_body_and_tail(CHAPTER)
    assert body == BODY
    assert tail.startswith("\n<!-- status:begin -->")


def test_body_end_without_block_is_end_of_text() -> None:
    assert cs.body_end(BODY) == len(BODY)


def test_strip_for_measure_removes_block_and_marked_lines() -> None:
    text = BODY + "<!-- status:line -->《告知》門が開いた。\n\n" + BLOCK
    stripped = cs.strip_for_measure(text)
    assert "告" not in stripped
    assert "風が冷たかった。" in stripped


def test_unmark_keeps_content() -> None:
    text = BODY + "<!-- status:line -->《告知》門が開いた。\n\n" + BLOCK
    out = cs.unmark_for_output(text)
    assert "status:" not in out
    assert "《告知》門が開いた。" in out
    assert "【告】体力が上がりました。" in out


def test_replace_block_adds_replaces_and_removes() -> None:
    added = cs.replace_block(BODY, "A")
    assert added == BODY + "\n" + cs.render_block("A")
    replaced = cs.replace_block(added, "B")
    assert replaced == BODY + "\n" + cs.render_block("B")
    removed = cs.replace_block(replaced, None)
    assert removed == BODY


def test_replace_block_refuses_text_after_block() -> None:
    with pytest.raises(ValueError):
        cs.replace_block(CHAPTER + "　あとがき。\n", "B")


def test_legacy_blocks() -> None:
    text = BODY + "\n---\n**ボディーの変化・経験ログ**\n- ミミ：変化した。\n"
    assert cs.find_legacy_blocks(text) == [6]
    assert cs.find_legacy_blocks("#### ■高瀬 陽一（最終ステータス）\n") == [1]
    assert cs.find_legacy_blocks(CHAPTER) == []


# ── 本文内の通知の定義 ─────────────────────────────


NOTICE = """# ステータス表示

## 本文内の通知

| 項目 | 内容 |
|---|---|
| 使うか | 使う |
| 主体 | 世界の声 |
| 出方 | 頭の中に声が響く |
| 届く範囲 | 本人だけ |
| きっかけ | 獲得・進化 |
| やりとり | 告げるだけ |
| 置き方 | 地の文に織り込む |
| 書式 | 二重山括弧で囲む |
| 括弧 | 《》 |
| 頻度の方針 | 転機だけ |

## 台帳
"""


def test_notice_definition_usable() -> None:
    notice = cs.parse_notice_definition(NOTICE)
    assert notice.usable
    assert notice.brackets == (("《", "》"),)


def test_notice_definition_missing_items_is_not_usable() -> None:
    notice = cs.parse_notice_definition(NOTICE.replace("| 主体 | 世界の声 |", "| 主体 | |"))
    assert notice.enabled
    assert not notice.usable
    assert "主体" in notice.missing


# ── 字数・句読点 ─────────────────────────────


def test_char_count_excludes_block_by_default() -> None:
    assert count_chars(CHAPTER, strip_fm=False) == count_chars(BODY, strip_fm=False)
    assert count_chars(CHAPTER, strip_fm=False, include_status=True) > count_chars(
        BODY, strip_fm=False
    )


def test_punctuation_body_excludes_block() -> None:
    assert "体力" not in extract_body(CHAPTER)


# ── lint ─────────────────────────────


def _lint(tmp_path: Path, text: str, notice: str | None = None) -> list[str]:
    from novel_text_rewrite_lint import (
        _compile,
        build_all_rules,
        lint_file,
        load_yaml,
        resolve_profile,
    )

    work = tmp_path / "novels" / "001_test"
    (work / "_novel_text").mkdir(parents=True, exist_ok=True)
    (work / cs.STATUS_DISPLAY_NAME).unlink(missing_ok=True)
    if notice is not None:
        (work / cs.STATUS_DISPLAY_NAME).write_text(notice, encoding="utf-8")
    target = work / "_novel_text" / "novel_text01.md"
    target.write_text(text, encoding="utf-8")
    config = load_yaml(ROOT / "_how_to.example" / "novel_text_rewrite_rules.yaml")
    all_rules = build_all_rules(config)
    rules = [all_rules[rid] for rid in resolve_profile(config, "status")]
    skip = [_compile(p) for p in config["defaults"]["skip_line_patterns"]]
    return [
        issue.rule_id
        for issue in lint_file(target, active_rules=rules, skip_patterns=skip, allowlist=[],
                               rel_path="novel_text01.md")
    ]


def test_lint_flags_number_in_prose_but_not_in_block(tmp_path: Path) -> None:
    text = "　好感度が25/100になった。\n\n<!-- status:begin -->\n好感度 25/100\n<!-- status:end -->\n"
    assert _lint(tmp_path, text) == ["status_number_in_prose"]


def test_lint_skips_defined_bracketed_notice(tmp_path: Path) -> None:
    text = "　声が響いた。《レベル3に上がりました》\n"
    assert _lint(tmp_path, text, NOTICE) == []
    assert _lint(tmp_path, text) == ["status_number_in_prose"]


# ── 新規作品の config・Web 投稿稿 ─────────────────────────────


def test_initial_config_writes_synopsis_row() -> None:
    from inspection_bootstrap import initial_config_text

    config = cs.parse_chapter_status(initial_config_text(1, "試し"))
    assert config.mode is cs.ChapterStatusMode.SYNOPSIS
    assert cs.MODE_KEY in config.explicit


def test_web_export_unmarks_and_does_not_overwrite(tmp_path: Path) -> None:
    from datetime import datetime

    from novel_web_export import export_work

    work = tmp_path / "001_test"
    (work / "_novel_text").mkdir(parents=True)
    source = work / "_novel_text" / "novel_text01.md"
    source.write_text(CHAPTER, encoding="utf-8")

    first = export_work(work)
    out = (work / "_novel_text_re" / "novel_text01.md").read_text(encoding="utf-8")
    assert first["written"] == ["novel_text01.md"]
    assert "status:" not in out and "【告】体力が上がりました。" in out
    assert source.read_text(encoding="utf-8") == CHAPTER

    second = export_work(work)
    assert second["skipped_existing"] == ["novel_text01.md"]

    third = export_work(work, overwrite=True, now=datetime(2026, 11, 21, 12, 0, 0))
    assert third["backed_up"] == ["_novel_text_re/_old/20261121_120000/novel_text01.md"]


def test_web_export_refuses_broken_markers(tmp_path: Path) -> None:
    from novel_web_export import export_work

    work = tmp_path / "001_test"
    (work / "_novel_text").mkdir(parents=True)
    (work / "_novel_text" / "novel_text01.md").write_text(BODY + "<!-- status:begin -->\n", encoding="utf-8")
    result = export_work(work)
    assert not result["ok"]
    assert not (work / "_novel_text_re" / "novel_text01.md").exists()


# ── novel_project_check ─────────────────────────────


def _work(tmp_path: Path, rows: str, text: str) -> Path:
    work = tmp_path / "001_test"
    (work / "_novel_text").mkdir(parents=True)
    (work / "config.md").write_text(_config(rows), encoding="utf-8")
    (work / "_novel_text" / "novel_text01.md").write_text(text, encoding="utf-8")
    return work


def test_project_check_legacy_info_and_mode_warning(tmp_path: Path) -> None:
    from novel_project_check import _check_chapter_status

    legacy = BODY + "\n---\n**ボディーの変化・経験ログ**\n- ミミ：変化した。\n"
    result = _check_chapter_status(_work(tmp_path / "a", "| 作品名 | 試し |", legacy))
    assert result["ok"] and result["mode"] == "SYNOPSIS"
    assert result["legacy"] == ["novel_text01.md:6"] and result["infos"]

    result = _check_chapter_status(_work(tmp_path / "b", "| CHAPTER_STATUS | OFF |", CHAPTER))
    assert any("章末ブロックがあります" in w for w in result["warnings"])


def test_project_check_text_needs_status_display_and_valid_row(tmp_path: Path) -> None:
    from novel_project_check import _check_chapter_status

    rows = "| CHAPTER_STATUS | TEXT |\n| CHAPTER_STATUS_STYLE | notice_log |"
    result = _check_chapter_status(_work(tmp_path / "a", rows, CHAPTER))
    assert any("status_display.md がありません" in w for w in result["warnings"])

    result = _check_chapter_status(_work(tmp_path / "b", "| CHAPTER_STATUS | TEXT |", CHAPTER))
    assert not result["ok"]
