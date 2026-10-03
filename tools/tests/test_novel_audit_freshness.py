#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import novel_audit_freshness as naf  # noqa: E402


def _make_novel(tmp_path: Path) -> Path:
    novel = tmp_path / "999_テスト"
    novel.mkdir()
    (novel / "character.md").write_text("# 人物\n- **名前**: 太郎\n", encoding="utf-8")
    (novel / "world.md").write_text("# 世界\n王都がある。\n", encoding="utf-8")
    (novel / "design_specification.md").write_text("# 設計\n第1章: 太郎が王都へ行く。\n", encoding="utf-8")
    return novel


def _write_audit(novel: Path, stamp: str, *, scope: str = "design", hashes: dict[str, str] | None = None) -> Path:
    reader = novel / "_reader"
    reader.mkdir(exist_ok=True)
    hashes = naf.current_hashes(novel) if hashes is None else hashes
    body = "\n".join(
        [
            "# Consistency Audit",
            "",
            "- 種別: Consistency Audit",
            f"- scope: {scope}",
            "- 起動: user",
            naf.render_hash_lines(hashes),
            "",
            "| 資料 | 箇所 | 内容 | 判定 |",
        ]
    )
    path = reader / f"consistency_design_{stamp}.md"
    path.write_text(body + "\n", encoding="utf-8")
    return path


def test_unaudited_when_no_design_audit(tmp_path: Path) -> None:
    novel = _make_novel(tmp_path)
    result = naf.check_freshness(novel)
    assert result.status == "unaudited"
    assert result.exit_code == 1


def test_fresh_after_audit(tmp_path: Path) -> None:
    novel = _make_novel(tmp_path)
    _write_audit(novel, "20261004_1000")
    result = naf.check_freshness(novel)
    assert result.status == "fresh"
    assert result.exit_code == 0
    assert result.audit_file == "_reader/consistency_design_20261004_1000.md"


def test_stale_after_setting_change(tmp_path: Path) -> None:
    novel = _make_novel(tmp_path)
    _write_audit(novel, "20261004_1000")
    (novel / "world.md").write_text("# 世界\n王都と港町がある。\n", encoding="utf-8")
    result = naf.check_freshness(novel)
    assert result.status == "stale"
    assert result.changed == ["world.md"]
    assert result.exit_code == 1


def test_line_ending_change_is_not_stale(tmp_path: Path) -> None:
    novel = _make_novel(tmp_path)
    _write_audit(novel, "20261004_1000")
    path = novel / "character.md"
    lf = path.read_bytes().replace(b"\r\n", b"\n")
    path.write_bytes(lf)
    assert naf.check_freshness(novel).status == "fresh"
    path.write_bytes(lf.replace(b"\n", b"\r\n"))
    assert naf.check_freshness(novel).status == "fresh"


def test_latest_audit_by_timestamp_is_used(tmp_path: Path) -> None:
    novel = _make_novel(tmp_path)
    old = naf.current_hashes(novel)
    _write_audit(novel, "20261004_0900", hashes=old)
    (novel / "world.md").write_text("# 世界\n変更後。\n", encoding="utf-8")
    _write_audit(novel, "20261004_1100")
    result = naf.check_freshness(novel)
    assert result.status == "fresh"
    assert result.audit_file.endswith("20261004_1100.md")


def test_text_and_legacy_files_are_not_baselines(tmp_path: Path) -> None:
    novel = _make_novel(tmp_path)
    reader = novel / "_reader"
    reader.mkdir()
    (reader / "consistency_20261001.md").write_text("- scope: design\n", encoding="utf-8")
    (reader / "consistency_text_20261004_1000.md").write_text("- scope: text\n", encoding="utf-8")
    assert naf.check_freshness(novel).status == "unaudited"


def test_scope_mismatch_warns_and_header_wins(tmp_path: Path) -> None:
    novel = _make_novel(tmp_path)
    _write_audit(novel, "20261004_1000", scope="text")
    result = naf.check_freshness(novel)
    assert result.status == "unaudited"
    assert any("冒頭の scope は text" in w for w in result.warnings)


def test_missing_hash_lines_are_stale_with_warning(tmp_path: Path) -> None:
    novel = _make_novel(tmp_path)
    reader = novel / "_reader"
    reader.mkdir()
    (reader / "consistency_design_20261004_1000.md").write_text("- scope: design\n", encoding="utf-8")
    result = naf.check_freshness(novel)
    assert result.status == "stale"
    assert any("設定ハッシュがありません" in w for w in result.warnings)


def test_missing_setting_file_is_error(tmp_path: Path) -> None:
    novel = _make_novel(tmp_path)
    (novel / "world.md").unlink()
    result = naf.check_freshness(novel)
    assert result.status == "error"
    assert result.exit_code == 2


def test_cli_hash_then_check_json(tmp_path: Path, capsys) -> None:
    novel = _make_novel(tmp_path)
    assert naf.main(["hash", str(novel)]) == 0
    lines = capsys.readouterr().out
    assert lines.startswith("- 設定ハッシュ:")
    assert "character.md: sha256:" in lines

    reader = novel / "_reader"
    reader.mkdir()
    (reader / "consistency_design_20261004_1000.md").write_text(
        "- scope: design\n" + lines, encoding="utf-8"
    )
    assert naf.main(["check", str(novel), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "fresh"
