#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from novel_char_count import count_chars  # noqa: E402
from novel_meta_char_table import (  # noqa: E402
    cmd_check,
    format_table,
    main,
    measure_chapters,
    parse_table_rows,
)

_META_HEAD = """# I. 内部メタ情報

## 1. 執筆フェーズ・ステータス
- **次回のタスク**: 続き

"""


def _write_chapter(work: Path, name: str, body: str) -> int:
    path = work / "_novel_text" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return count_chars(body, strip_fm=True)


def _write_meta(work: Path, table: str) -> None:
    (work / "_meta.md").write_text(_META_HEAD + table + "\n## 2. 次節\n", encoding="utf-8")


def test_check_skips_when_table_missing(tmp_path: Path) -> None:
    work = tmp_path / "001_no_table"
    work.mkdir()
    (work / "_meta.md").write_text(_META_HEAD + "## 2. 次節\n", encoding="utf-8")
    _write_chapter(work, "novel_text01.md", "あいう")
    assert cmd_check(work) == 0


def test_check_skips_when_meta_missing(tmp_path: Path) -> None:
    work = tmp_path / "001_no_meta"
    work.mkdir()
    assert cmd_check(work) == 0


def test_check_matches_measured_rows(tmp_path: Path) -> None:
    work = tmp_path / "001_ok"
    work.mkdir()
    count0 = _write_chapter(work, "novel_text00.md", "プロローグ本文")
    count1 = _write_chapter(work, "novel_text01.md", "第一章の本文です")
    table = format_table(
        measure_chapters(work),
        statuses={0: "清書中", 1: "初稿"},
        measured_on="2026-10-05",
    )
    _write_meta(work, table)
    assert cmd_check(work) == 0
    parsed, total = parse_table_rows(table)
    assert parsed == {0: count0, 1: count1}
    assert total == count0 + count1


def test_check_fails_when_count_drifts(tmp_path: Path) -> None:
    work = tmp_path / "001_drift"
    work.mkdir()
    _write_chapter(work, "novel_text01.md", "正しい本文")
    _write_meta(
        work,
        """### 章別文字数
| 章 | 本文 | 実文字数 | 状態 | 計測 |
|---|---|---:|---|---|
| 第1章 | novel_text01 | 1 | 初稿 | 2026-10-05 |
| 合計 | — | 1 | — | 2026-10-05 |
""",
    )
    assert cmd_check(work) == 1


def test_render_picks_up_added_chapter(tmp_path: Path, capsys) -> None:
    work = tmp_path / "001_add"
    work.mkdir()
    _write_chapter(work, "novel_text01.md", "第一章")
    _write_meta(
        work,
        format_table(
            measure_chapters(work),
            statuses={1: "清書中"},
            measured_on="2026-10-05",
        ),
    )
    _write_chapter(work, "novel_text02.md", "第二章を足した")
    assert main(["render", str(work), "--measured-on", "2026-10-05"]) == 0
    out = capsys.readouterr().out
    assert "第1章" in out
    assert "第2章" in out
    assert "清書中" in out
    assert "初稿" in out


def test_render_groups_subparts(tmp_path: Path) -> None:
    work = tmp_path / "001_parts"
    work.mkdir()
    _write_chapter(work, "novel_text01_1.md", "前半")
    _write_chapter(work, "novel_text01_2.md", "後半です")
    rows = measure_chapters(work)
    assert len(rows) == 1
    assert rows[0]["chapter"] == 1
    assert rows[0]["body"] == "novel_text01_*"
    assert int(rows[0]["chars"]) == count_chars("前半", strip_fm=True) + count_chars(
        "後半です", strip_fm=True
    )
