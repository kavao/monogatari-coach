#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import novel_proper_noun_lint as npl  # noqa: E402


def _write(novel: Path, name: str, text: str) -> None:
    (novel / name).write_text(text, encoding="utf-8")


def _base(tmp_path: Path) -> Path:
    novel = tmp_path / "999_固有名詞"
    novel.mkdir()
    _write(
        novel,
        "character.md",
        "# 登場人物プロフィール\n\n"
        "## 松下 稔（まつした みのる）\n"
        "- **名前**: 松下 稔（まつした みのる）\n"
        "- **呼び方**: 英を「英」と呼ぶ。オズワルド等には使わない。\n",
    )
    _write(
        novel,
        "world.md",
        "# world.md\n\n"
        "## 1. 世界観概要\n"
        "- **世界名**: 塩灯市（しおとういち）と、その直下の灯穴坑\n\n"
        "### 2.1 塩灯市\n"
        "- 門の周囲。\n\n"
        "## 7. 用語\n"
        "| 用語 | 意味 |\n"
        "|------|------|\n"
        "| 上昇税 | 深度の代償 |\n"
        "| 赤筋菌 | 五層の主採集物 |\n",
    )
    return novel


def test_clean_design_exits_zero(tmp_path: Path) -> None:
    novel = _base(tmp_path)
    _write(
        novel,
        "design_specification.md",
        "# 設計\n\n"
        "```mermaid\n"
        "flowchart TD\n"
        "    subgraph 塩灯市\n"
        "        Mino[松下 稔<br/>鍋師]\n"
        "        Market[塩灯市の相場]\n"
        "        Tax[上昇税]\n"
        "        Gate[地上の門]\n"
        "    end\n"
        "```\n",
    )
    result = npl.lint_novel(novel)
    assert result.exit_code == 0
    assert result.findings == []


def test_unknown_mermaid_person_is_finding(tmp_path: Path) -> None:
    novel = _base(tmp_path)
    _write(
        novel,
        "design_specification.md",
        "```mermaid\n"
        "graph TD\n"
        '    Oswald["オズワルド・クローネン<br/>査察官"]\n'
        "```\n",
    )
    result = npl.lint_novel(novel)
    assert result.exit_code == 1
    assert any("オズワルド" in f.text for f in result.findings)


def test_yobikata_is_not_a_definition(tmp_path: Path) -> None:
    novel = _base(tmp_path)
    _write(
        novel,
        "design_specification.md",
        "```mermaid\n"
        "graph TD\n"
        "    X[オズワルド・クローネン]\n"
        "```\n",
    )
    texts = [f.text for f in npl.lint_novel(novel).findings]
    assert any("オズワルド" in t for t in texts)


def test_spaced_name_in_chapter_plot(tmp_path: Path) -> None:
    novel = _base(tmp_path)
    _write(novel, "design_specification.md", "1. 原 章子が秤を置く。\n")
    result = npl.lint_novel(novel)
    assert result.exit_code == 1
    assert any(f.text == "原 章子" for f in result.findings)


def test_annotated_place_without_world_def(tmp_path: Path) -> None:
    novel = _base(tmp_path)
    _write(
        novel,
        "design_specification.md",
        "舞台は霧門街（きりもんがい）である。\n",
    )
    result = npl.lint_novel(novel)
    assert any("霧門街" in f.text for f in result.findings)


def test_defined_reading_is_ok(tmp_path: Path) -> None:
    novel = _base(tmp_path)
    _write(
        novel,
        "design_specification.md",
        "松下 稔（まつした みのる）が鍋を掛ける。\n",
    )
    assert npl.lint_novel(novel).exit_code == 0


def test_missing_character_is_error(tmp_path: Path) -> None:
    novel = tmp_path / "998_欠"
    novel.mkdir()
    _write(novel, "world.md", "# 世界\n")
    result = npl.lint_novel(novel)
    assert result.exit_code == 2
    assert result.error and "character.md" in result.error


def test_proposal_is_scanned_config_is_not(tmp_path: Path) -> None:
    novel = _base(tmp_path)
    _write(novel, "design_specification.md", "# 設計\n稔が火を見る。\n")
    _write(novel, "proposal.md", "1. 原 章子が窓口になる。\n")
    _write(novel, "config.md", "原 章子はキーワードではない。\n")
    result = npl.lint_novel(novel)
    assert "proposal.md" in result.scanned
    assert "config.md" not in result.scanned
    assert any(f.source_file == "proposal.md" and f.text == "原 章子" for f in result.findings)


def test_latin_alias_from_heading_covers_mermaid(tmp_path: Path) -> None:
    novel = _base(tmp_path)
    _write(
        novel,
        "character.md",
        "# 登場人物プロフィール\n\n"
        "## エイダン（えいだん / Aydan）\n"
        "- **名前**: エイダン（前世：相沢 瑛士 / あいざわ えいじ）\n",
    )
    _write(
        novel,
        "design_specification.md",
        "```mermaid\n"
        "graph TD\n"
        '    Aydan["エイダン（相沢瑛士）<br>技師"]\n'
        "```\n",
    )
    assert npl.lint_novel(novel).exit_code == 0


def test_json_shape(tmp_path: Path) -> None:
    novel = _base(tmp_path)
    _write(novel, "design_specification.md", "# 設計\n")
    code = npl.main([str(novel), "--json"])
    assert code == 0


def test_cli_json_findings(tmp_path: Path, capsys) -> None:
    novel = _base(tmp_path)
    _write(novel, "design_specification.md", "1. 原 章子が秤を置く。\n")
    code = npl.main([str(novel), "--json"])
    assert code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["exit_code"] == 1
    assert payload["findings"][0]["text"] == "原 章子"
