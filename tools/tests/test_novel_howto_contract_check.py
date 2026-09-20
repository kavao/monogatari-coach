#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
import sys

sys.path.insert(0, str(ROOT / "tools"))

from novel_howto_contract_check import (  # noqa: E402
    check_meta,
    check_novel,
    main,
    normalize_recorded_path,
)


def test_normalize_prefixes() -> None:
    rel, warns = normalize_recorded_path("`_how_to/naming.md`（タイトル）")
    assert rel == "naming.md"
    assert warns == []
    rel, warns = normalize_recorded_path("how_to/naming.md")
    assert rel == "naming.md"
    assert any("how_to/" in w for w in warns)
    rel, warns = normalize_recorded_path("episode/general/episode_hooks.md")
    assert rel == "episode/general/episode_hooks.md"
    assert any("プレフィックス" in w for w in warns)


def _write_catalog(root: Path) -> None:
    leaf = root / "_how_to.example" / "naming.md"
    leaf.parent.mkdir(parents=True)
    leaf.write_text("# naming\n", encoding="utf-8")


def test_new_format_present(tmp_path: Path) -> None:
    _write_catalog(tmp_path)
    meta = """## 3.5 Plan Mode Gate B 記録
- **創作技法契約**:
  - **selected**:
    - relative_id: naming.md
      - standard_path: _how_to.example/naming.md
      - working_path: (なし)
  - **not_applicable**:
    - genre/* （因習村は使わない）
"""
    result = check_meta(meta, tmp_path)
    assert result.format == "new"
    assert [leaf.relative_id for leaf in result.selected] == ["naming.md"]
    assert result.required_missing == []
    assert result.present == ["naming.md"]


def test_new_format_missing_is_required_missing(tmp_path: Path) -> None:
    tmp_path.joinpath("_how_to.example").mkdir()
    meta = """## 3.5 Plan Mode Gate B 記録
- **創作技法契約**:
  - **selected**:
    - relative_id: missing_leaf.md
"""
    result = check_meta(meta, tmp_path)
    assert result.required_missing == ["missing_leaf.md"]


def test_legacy_does_not_rewrite(tmp_path: Path) -> None:
    _write_catalog(tmp_path)
    novel = tmp_path / "109_x"
    novel.mkdir()
    original = """## 3.5 Plan Mode Gate B 記録
- **読んだ _how_to**:
  - `_how_to/_index.md`（必読選定）
  - `_how_to.example/naming.md`
  - 非該当: `genre/*`（使わない）
- **発動したユーザスキル**:
  - x
"""
    meta = novel / "_meta.md"
    meta.write_text(original, encoding="utf-8")
    result = check_novel(novel, root=tmp_path)
    assert result.format == "legacy"
    assert any("grandfather" in w for w in result.warnings)
    assert any(leaf.index_like for leaf in result.selected)
    assert "naming.md" in result.present
    assert result.required_missing == []
    assert result.not_applicable
    assert "genre/*" in result.not_applicable[0]
    assert result.as_dict()["selected_count"] == 1
    assert meta.read_text(encoding="utf-8") == original


def test_strict_exit_on_missing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    novel = tmp_path / "001_x"
    novel.mkdir()
    novel.joinpath("_meta.md").write_text(
        """## 3.5 Plan Mode Gate B 記録
- **創作技法契約**:
  - **selected**:
    - relative_id: no_such.md
""",
        encoding="utf-8",
    )
    tmp_path.joinpath("_how_to.example").mkdir()
    code = main([str(novel), "--repo-root", str(tmp_path), "--strict", "--json"])
    assert code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["required_missing"] == ["no_such.md"]


def test_reject_parent_traversal(tmp_path: Path) -> None:
    _write_catalog(tmp_path)
    secret = tmp_path / "secret.md"
    secret.write_text("nope\n", encoding="utf-8")
    meta = """## 3.5 Plan Mode Gate B 記録
- **創作技法契約**:
  - **selected**:
    - relative_id: naming.md
      - working_path: _how_to/../secret.md
"""
    result = check_meta(meta, tmp_path)
    assert result.errors
    assert any(".." in e or "拒否" in e for e in result.errors)
    assert result.present == []
    assert "naming.md" not in result.present


def test_reject_absolute_path(tmp_path: Path) -> None:
    _write_catalog(tmp_path)
    meta = f"""## 3.5 Plan Mode Gate B 記録
- **創作技法契約**:
  - **selected**:
    - relative_id: naming.md
      - standard_path: {(tmp_path / "_how_to.example" / "naming.md").resolve().as_posix()}
"""
    result = check_meta(meta, tmp_path)
    assert result.errors
    assert any("拒否" in e or "許可ルート" in e for e in result.errors)


def test_path_mismatch_relative_id(tmp_path: Path) -> None:
    other = tmp_path / "_how_to.example" / "other.md"
    other.parent.mkdir(parents=True)
    other.write_text("# other\n", encoding="utf-8")
    (tmp_path / "_how_to.example" / "naming.md").write_text("# naming\n", encoding="utf-8")
    meta = """## 3.5 Plan Mode Gate B 記録
- **創作技法契約**:
  - **selected**:
    - relative_id: naming.md
      - standard_path: _how_to.example/other.md
"""
    result = check_meta(meta, tmp_path)
    assert any("不一致" in e for e in result.errors)
    assert "naming.md" not in result.present


def test_working_path_preferred_when_recorded(tmp_path: Path) -> None:
    example = tmp_path / "_how_to.example" / "naming.md"
    example.parent.mkdir(parents=True)
    example.write_text("STANDARD\n", encoding="utf-8")
    working = tmp_path / "_how_to" / "naming.md"
    working.parent.mkdir(parents=True)
    working.write_text("WORKING\n", encoding="utf-8")
    meta = """## 3.5 Plan Mode Gate B 記録
- **創作技法契約**:
  - **selected**:
    - relative_id: naming.md
      - standard_path: _how_to.example/naming.md
      - working_path: _how_to/naming.md
"""
    result = check_meta(meta, tmp_path)
    assert result.errors == []
    assert result.present == ["naming.md"]
    assert result.selected[0].effective_path
    assert Path(result.selected[0].effective_path).read_text(encoding="utf-8") == "WORKING\n"


def test_new_format_index_is_error_not_leaf(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    idx = tmp_path / "_how_to.example" / "_index.md"
    idx.parent.mkdir(parents=True)
    idx.write_text("# index\n", encoding="utf-8")
    (tmp_path / "_how_to.example" / "naming.md").write_text("# naming\n", encoding="utf-8")
    novel = tmp_path / "002_x"
    novel.mkdir()
    novel.joinpath("_meta.md").write_text(
        """## 3.5 Plan Mode Gate B 記録
- **創作技法契約**:
  - **selected**:
    - relative_id: _index.md
    - relative_id: naming.md
      - standard_path: _how_to.example/naming.md
""",
        encoding="utf-8",
    )
    result = check_novel(novel, root=tmp_path)
    assert result.format == "new"
    assert result.as_dict()["selected_count"] == 1
    assert result.present == ["naming.md"]
    assert any("索引" in e for e in result.errors)
    code = main([str(novel), "--repo-root", str(tmp_path), "--strict", "--json"])
    assert code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["selected_count"] == 1
    assert payload["errors"]


def test_pack_expands_leaves(tmp_path: Path) -> None:
    example = tmp_path / "_how_to.example"
    packs = example / "howto_packs"
    packs.mkdir(parents=True)
    for name in ("naming.md", "novelcore.md", "novel_structure.md"):
        (example / name).write_text(f"# {name}\n", encoding="utf-8")
    packs.joinpath("general.yaml").write_text(
        "pack_id: general\nleaves:\n  - novelcore.md\n  - naming.md\n  - novel_structure.md\n",
        encoding="utf-8",
    )
    meta = """## 3.5 Plan Mode Gate B 記録
- **創作技法契約**:
  - **pack_id**: general
  - **selected**:
"""
    result = check_meta(meta, tmp_path)
    assert result.errors == []
    assert result.pack_id == "general"
    assert sorted(result.present) == ["naming.md", "novel_structure.md", "novelcore.md"]
    assert result.leaf_count() == 3


def test_pack_working_yaml_preferred(tmp_path: Path) -> None:
    example = tmp_path / "_how_to.example"
    example.mkdir()
    (example / "naming.md").write_text("S\n", encoding="utf-8")
    (example / "novelcore.md").write_text("C\n", encoding="utf-8")
    (example / "howto_packs").mkdir()
    (example / "howto_packs" / "general.yaml").write_text(
        "pack_id: general\nleaves:\n  - naming.md\n  - novelcore.md\n",
        encoding="utf-8",
    )
    working = tmp_path / "_how_to" / "howto_packs"
    working.mkdir(parents=True)
    working.joinpath("general.yaml").write_text(
        "pack_id: general\nleaves:\n  - naming.md\n",
        encoding="utf-8",
    )
    meta = """## 3.5 Plan Mode Gate B 記録
- **創作技法契約**:
  - **pack_id**: general
"""
    result = check_meta(meta, tmp_path)
    assert result.present == ["naming.md"]
    assert "_how_to/howto_packs/general.yaml" in result.pack_path.replace("\\", "/")


def test_unknown_pack_is_error(tmp_path: Path) -> None:
    tmp_path.joinpath("_how_to.example").mkdir()
    meta = """## 3.5 Plan Mode Gate B 記録
- **創作技法契約**:
  - **pack_id**: missing_pack
"""
    result = check_meta(meta, tmp_path)
    assert any("パックが無い" in e for e in result.errors)


def test_pack_exclude_and_add(tmp_path: Path) -> None:
    example = tmp_path / "_how_to.example"
    packs = example / "howto_packs"
    packs.mkdir(parents=True)
    (example / "naming.md").write_text("# n\n", encoding="utf-8")
    (example / "novelcore.md").write_text("# c\n", encoding="utf-8")
    (example / "world_wear.md").write_text("# w\n", encoding="utf-8")
    packs.joinpath("general.yaml").write_text(
        "pack_id: general\nleaves:\n  - novelcore.md\n  - naming.md\n",
        encoding="utf-8",
    )
    meta = """## 3.5 Plan Mode Gate B 記録
- **創作技法契約**:
  - **pack_id**: general
  - **pack_exclude**:
    - naming.md
  - **pack_add**:
    - relative_id: world_wear.md
"""
    result = check_meta(meta, tmp_path)
    assert sorted(result.present) == ["novelcore.md", "world_wear.md"]
    assert "naming.md" not in result.present


def test_pack_missing_leaf_is_required_missing_strict(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    example = tmp_path / "_how_to.example"
    packs = example / "howto_packs"
    packs.mkdir(parents=True)
    (example / "naming.md").write_text("# n\n", encoding="utf-8")
    packs.joinpath("general.yaml").write_text(
        "pack_id: general\nleaves:\n  - naming.md\n  - novelcore.md\n",
        encoding="utf-8",
    )
    novel = tmp_path / "003_x"
    novel.mkdir()
    novel.joinpath("_meta.md").write_text(
        """## 3.5 Plan Mode Gate B 記録
- **創作技法契約**:
  - **pack_id**: general
""",
        encoding="utf-8",
    )
    result = check_meta(novel.joinpath("_meta.md").read_text(encoding="utf-8"), tmp_path)
    assert result.present == ["naming.md"]
    assert result.required_missing == ["novelcore.md"]
    assert "novelcore.md" not in result.present
    code = main([str(novel), "--repo-root", str(tmp_path), "--strict", "--json"])
    assert code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["required_missing"] == ["novelcore.md"]
    assert payload["present"] == ["naming.md"]


def test_broken_pack_yaml_is_error_not_traceback(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    example = tmp_path / "_how_to.example"
    packs = example / "howto_packs"
    packs.mkdir(parents=True)
    packs.joinpath("general.yaml").write_text("pack_id: general\nleaves: [\n", encoding="utf-8")
    novel = tmp_path / "004_x"
    novel.mkdir()
    novel.joinpath("_meta.md").write_text(
        """## 3.5 Plan Mode Gate B 記録
- **創作技法契約**:
  - **pack_id**: general
""",
        encoding="utf-8",
    )
    result = check_meta(novel.joinpath("_meta.md").read_text(encoding="utf-8"), tmp_path)
    assert any("パック YAML が不正" in e for e in result.errors)
    code = main([str(novel), "--repo-root", str(tmp_path), "--strict", "--json"])
    assert code == 1
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["errors"]
    assert "Traceback" not in captured.out
    assert "Traceback" not in captured.err

