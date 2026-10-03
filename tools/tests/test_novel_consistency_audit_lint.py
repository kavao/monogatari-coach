#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import novel_consistency_audit_lint as lint  # noqa: E402

HASHES = "\n".join(
    [
        "- 設定ハッシュ:",
        "  - character.md: sha256:" + "a" * 64,
        "  - world.md: sha256:" + "b" * 64,
        "  - design_specification.md: sha256:" + "c" * 64,
    ]
)


def _doc(*, scope: str = "design", counts: str = "矛盾 1 / 要確認 1 / 軽微 0", combo: str = "| 人物×世界 | 5 | 2 |",
         rows: str | None = None, hashes: bool = True, extra: str = "") -> str:
    rows = rows if rows is not None else "\n".join(
        [
            "| 資料 | 箇所 | 内容 | 判定 | 余地 |",
            "|------|------|------|------|------|",
            "| a | b | c | 矛盾 | |",
            "| a | b | c | 要確認 | 読める |",
        ]
    )
    return "\n".join(
        [
            "# 監査",
            "",
            "- 種別: Consistency Audit",
            f"- scope: {scope}",
            "- 起動: user",
            HASHES if hashes else "",
            f"- 件数: {counts}",
            "",
            "## 確認した組み合わせ",
            "",
            "| 組み合わせ | 確認した項目数 | 指摘数 |",
            "|------------|----------------|--------|",
            combo,
            "",
            "## 矛盾・不整合の一覧",
            "",
            rows,
            extra,
        ]
    )


NAME = "consistency_design_20261004_1000.md"


def test_ok() -> None:
    result = lint.lint_text(_doc(), NAME)
    assert result.errors == []
    assert result.table_counts == {"矛盾": 1, "要確認": 1, "軽微": 0}


def test_header_count_mismatch_is_reported() -> None:
    result = lint.lint_text(_doc(counts="矛盾 1 / 要確認 2 / 軽微 0", combo="| x | 5 | 3 |"), NAME)
    assert any("要確認" in e and "一致しない" in e for e in result.errors)


def test_combination_total_mismatch_is_reported() -> None:
    result = lint.lint_text(_doc(combo="| x | 5 | 5 |"), NAME)
    assert any("組み合わせ表" in e for e in result.errors)


def test_scope_mismatch_with_filename() -> None:
    result = lint.lint_text(_doc(scope="text"), NAME)
    assert any("scope" in e for e in result.errors)


def test_design_requires_hashes() -> None:
    result = lint.lint_text(_doc(hashes=False), NAME)
    assert any("ハッシュ" in e for e in result.errors)


def test_text_scope_does_not_require_hashes() -> None:
    result = lint.lint_text(_doc(scope="text", hashes=False), "consistency_text_20261004_1000.md")
    assert result.errors == []


def test_previous_judgment_rows_are_not_counted() -> None:
    extra = "\n".join(
        [
            "## 前回指摘の解消確認",
            "| 指摘 | 前回の判定 | 根拠 |",
            "|------|------------|------|",
            "| x | 前回: 矛盾 | 直した |",
        ]
    )
    result = lint.lint_text(_doc(extra=extra), NAME)
    assert result.errors == []


def test_reaudit_section_counts_only_after_heading() -> None:
    extra = "\n".join(
        [
            "## 再監査",
            "| 資料 | 箇所 | 内容 | 判定 | 余地 |",
            "|------|------|------|------|------|",
            "| a | b | c | 要確認 | 読める |",
        ]
    )
    doc = _doc(counts="矛盾 1→0 / 要確認 1 / 軽微 0", combo="| x | 5 | 1 |", extra=extra)
    result = lint.lint_text(doc, NAME)
    assert result.header_counts == {"矛盾": 0, "要確認": 1, "軽微": 0}
    assert result.errors == []


def test_missing_combination_section() -> None:
    doc = _doc().replace("## 確認した組み合わせ", "## 別の節")
    result = lint.lint_text(doc, NAME)
    assert any("確認した組み合わせ" in e for e in result.errors)


def test_cli_on_folder(tmp_path: Path, capsys) -> None:
    reader = tmp_path / "_reader"
    reader.mkdir()
    (reader / NAME).write_text(_doc(), encoding="utf-8")
    (reader / "consistency_20261001.md").write_text("旧形式", encoding="utf-8")
    assert lint.main([str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "[OK] " + NAME in out
    assert "consistency_20261001.md" not in out
