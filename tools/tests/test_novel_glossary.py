#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import novel_glossary as ng  # noqa: E402
import novel_proper_noun_lint as npl  # noqa: E402

HEADER = "| 用語ID | 正式名称 | 種別 | 定義・適用範囲 | 許容表記・略称 | 避ける表記 | 備考 |\n|---|---|---|---|---|---|---|\n"

WORLD = (
    "# 世界観\n\n"
    "## 社会\n\n村の鍛冶場は親方が仕切る。\n\n"
    "## 用語\n\n"
    + HEADER
    + "| term_001 | 火継ぎ | 技術 | 親方の炉の火を弟子の炉へ移す作業 | ― | 火魔法、点火術 | |\n"
    "| term_002 | 炉札 | 物 | 火継ぎを済ませた炉に下げる木札 | 札（炉札と分かるとき） | 免許、火継 | |\n"
    "\n## 用語（承認待ち）\n\n"
    + HEADER
    + "| term_p001 | 火見 | 行為 | 火継ぎのあと炉の色を見張ること | ― | ― | 第2章で初出 |\n"
)


def _work(tmp_path: Path, world: str = WORLD, text: str = "") -> Path:
    work = tmp_path / "999_鍛冶"
    (work / "_novel_text").mkdir(parents=True)
    (work / "world.md").write_text(world, encoding="utf-8")
    (work / "character.md").write_text("# 登場人物\n\n## 親方\n", encoding="utf-8")
    if text:
        (work / "_novel_text" / "novel_text01.md").write_text(text, encoding="utf-8")
    return work


def _codes(glossary: ng.Glossary) -> list[str]:
    return [i.code for i in glossary.issues]


# ── 読込 ─────────────────────────────────────────────────────────────


def test_standard_form_reads_columns_by_name_and_splits_pending() -> None:
    glossary = ng.parse_glossary(WORLD)

    assert glossary.form == ng.STANDARD
    assert [t.name for t in glossary.by_section(ng.FORMAL)] == ["火継ぎ", "炉札"]
    assert [t.name for t in glossary.by_section(ng.PENDING)] == ["火見"]
    assert glossary.terms[1].allowed == ["札"]  # 括弧書きの注記を外す
    assert glossary.terms[0].avoid == ["火魔法", "点火術"]
    assert [t.name for t in glossary.defined_terms()] == ["火継ぎ", "炉札"]
    assert glossary.issues == []


def test_reordered_columns_are_read_by_header_name() -> None:
    world = (
        "## 用語\n\n| 正式名称 | 定義・適用範囲 | 種別 | 用語ID |\n|---|---|---|---|\n"
        "| 火継ぎ | 火を移す作業 | 技術 | term_001 |\n"
    )
    term = ng.parse_glossary(world).terms[0]

    assert (term.name, term.term_id, term.kind) == ("火継ぎ", "term_001", "技術")


def test_heading_yougo_with_bullets_is_legacy() -> None:
    world = "## 用語\n- **火継ぎ**: 火を移す作業\n- 炉札 / 札板: 木の札\n- **火見:** 見張ること\n"

    glossary = ng.parse_glossary(world)

    assert glossary.form == ng.LEGACY
    assert [t.name for t in glossary.terms] == ["火継ぎ", "炉札", "札板", "火見"]
    assert all(t.definition for t in glossary.terms)


def test_legacy_two_column_table_and_subheadings() -> None:
    world = (
        "## 7. 用語\n| 用語 | 意味 |\n|------|------|\n| 塩灯市 | 門の周囲の市場都市 |\n\n"
        "## 4. 特殊用語\n\n### 合身同調の加護\n- 主人公だけが持つ力。\n"
    )

    glossary = ng.parse_glossary(world)

    assert glossary.form == ng.LEGACY
    assert [(t.name, bool(t.definition)) for t in glossary.terms] == [("塩灯市", True), ("合身同調の加護", True)]


def test_missing_glossary_is_error_not_zero() -> None:
    glossary = ng.parse_glossary("# 世界観\n\n## 地理\n川がある。\n")

    assert glossary.form == ng.MISSING
    assert _codes(glossary) == ["no_glossary"]


# ── 構造の検査 ───────────────────────────────────────────────────────


def test_structure_errors_and_warnings() -> None:
    world = (
        "## 用語\n\n" + HEADER
        + "| term_001 | 火継ぎ | 技術 | 火を移す | 火渡し | ― | |\n"
        "| term_001 | 炉札 | 魔法 | 木札 | 火渡し | 火継ぎ | |\n"
        "| term_003 | 鞴番 | 役職 | | ― | ― | |\n"
        "\n## 用語（承認待ち）\n\n" + HEADER
        + "| term_9 | 火継ぎ | 技術 | 重複 | ― | ― | |\n"
    )

    codes = _codes(ng.parse_glossary(world))

    assert "duplicate_id" in codes
    assert "unknown_kind" in codes
    assert "shared_alias" in codes
    assert "avoid_conflict" in codes  # 炉札の避ける表記が、火継ぎの正式名称と同じ
    assert "empty_definition" in codes
    assert "pending_duplicates_formal" in codes
    assert "id_pattern" in codes  # 承認待ちは term_pNNN


def test_missing_kind_column_warns_once() -> None:
    world = (
        "## 用語\n\n| 用語ID | 正式名称 | 定義・適用範囲 |\n|---|---|---|\n"
        "| term_001 | 火継ぎ | 火を移す |\n| term_002 | 炉札 | 木札 |\n"
    )

    codes = _codes(ng.parse_glossary(world))

    assert codes.count("missing_column") == 1
    assert "missing_kind" not in codes


def test_pending_only_is_error() -> None:
    world = "## 用語（承認待ち）\n\n" + HEADER + "| term_p001 | 火見 | 行為 | 見張る | ― | ― | |\n"

    assert "no_formal" in _codes(ng.parse_glossary(world))


# ── 表記の照合 ───────────────────────────────────────────────────────


def test_avoid_hit_is_reported_but_not_inside_registered_word(tmp_path: Path) -> None:
    text = "# 第1章\n\n　火継ぎを終えた。\n　火魔法で炉が燃えた。\n　火継の儀は無い。\n"
    report = ng.check_novel(_work(tmp_path, text=text))

    hits = [(h.line, h.text, h.term_id) for h in report.avoid_hits]

    assert (4, "火魔法", "term_001") in hits
    assert (5, "火継", "term_002") in hits  # 「火継ぎ」の一部ではない出現だけ
    assert all(line != 3 for line, _, _ in hits)


def test_glossary_section_itself_is_not_scanned(tmp_path: Path) -> None:
    report = ng.check_novel(_work(tmp_path))

    assert report.avoid_hits == []  # 避ける表記の列に並べた語は数えない


def test_usage_counts_declared_words_and_skips_one_char_aliases(tmp_path: Path) -> None:
    text = "# 第1章\n\n　火見のあいだ、札を見た。炉札を下げた。\n"
    report = ng.check_novel(_work(tmp_path, text=text))

    assert report.usage["term_p001"]["_novel_text/novel_text01.md"] == 1
    assert report.usage["term_002"]["_novel_text/novel_text01.md"] == 1  # 1文字の「札」は数えない


def test_katakana_candidates_are_optional(tmp_path: Path) -> None:
    text = "# 第1章\n\n　親方はフレアストーンを炉に置いた。\n"
    work = _work(tmp_path, text=text)

    assert ng.check_novel(work).katakana == []
    found = ng.check_novel(work, katakana=True).katakana
    assert [(c.text, c.line, c.in_setting) for c in found] == [("フレアストーン", 3, False)]


# ── CLI ──────────────────────────────────────────────────────────────


def test_cli_exit_codes_and_json(tmp_path: Path, capsys) -> None:
    work = _work(tmp_path, text="# 第1章\n\n　火魔法を使った。\n")

    assert ng.main([str(work)]) == 0
    capsys.readouterr()
    assert ng.main([str(work), "--strict", "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["form"] == ng.STANDARD
    assert payload["avoid_hits"][0]["text"] == "火魔法"
    assert "world.md#用語" in payload["hashes"]
    assert ng.main([str(tmp_path / "none")]) == 2


def test_cli_does_not_write_files(tmp_path: Path) -> None:
    work = _work(tmp_path, text="# 第1章\n\n　火魔法を使った。\n")
    before = {p: p.read_bytes() for p in work.rglob("*") if p.is_file()}

    ng.main([str(work), "--katakana"])

    assert {p: p.read_bytes() for p in work.rglob("*") if p.is_file()} == before


# ── novel_proper_noun_lint との接続 ─────────────────────────────────


def test_proper_noun_lint_reads_names_not_ids_and_skips_pending() -> None:
    records = npl.parse_world_defs(WORLD)
    aliases = {a for r in records for a in r.aliases}

    assert {"火継ぎ", "炉札"} <= aliases
    assert not {"term_001", "用語ID", "火見"} & aliases
