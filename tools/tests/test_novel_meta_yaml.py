# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_TOOLS_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_TOOLS_ROOT))

from novel_meta_yaml import (  # noqa: E402
    load_meta_yaml,
    resolve_meta_path,
    resolve_novelai_portion,
)


def test_resolve_meta_path_novel_relative(tmp_path: Path) -> None:
    novel = tmp_path / "novel"
    novel.mkdir()
    bundle = novel / "references" / "novelai" / "a.naiv4vibebundle"
    bundle.parent.mkdir(parents=True)
    bundle.write_bytes(b"x")
    root = tmp_path / "repo"
    root.mkdir()
    got = resolve_meta_path(
        "references/novelai/a.naiv4vibebundle", novel_dir=novel, root=root
    )
    assert got == bundle.resolve()


def test_resolve_meta_path_how_to_root(tmp_path: Path) -> None:
    novel = tmp_path / "novel"
    novel.mkdir()
    root = tmp_path / "repo"
    how = root / "_how_to" / "image_refs" / "novelai"
    how.mkdir(parents=True)
    bundle = how / "flat.naiv4vibebundle"
    bundle.write_bytes(b"x")
    got = resolve_meta_path(
        "_how_to/image_refs/novelai/flat.naiv4vibebundle",
        novel_dir=novel,
        root=root,
    )
    assert got == bundle.resolve()


def test_resolve_novelai_portion_default_and_fallback(tmp_path: Path) -> None:
    novel = tmp_path / "novel"
    novel.mkdir()
    root = tmp_path / "repo"
    cross = root / "_how_to" / "image_refs" / "novelai"
    cross.mkdir(parents=True)
    flat = cross / "flat.naiv4vibebundle"
    flat.write_bytes(b"x")

    (novel / "_meta.yaml").write_text(
        """
version: 1
novelai:
  portion_default: missing_work
  portion_fallback: cross_flat
  portions:
    missing_work:
      path: references/novelai/missing.naiv4vibebundle
      strength: 0.7
    cross_flat:
      path: _how_to/image_refs/novelai/flat.naiv4vibebundle
      strength: 0.6
      information_extracted: 1.0
      label: flat
""".strip(),
        encoding="utf-8",
    )

    portion = resolve_novelai_portion(novel, root)
    assert portion is not None
    assert portion.id == "cross_flat"
    assert portion.paths == [flat.resolve().as_posix()]
    assert portion.strength == 0.6
    assert portion.label == "flat"


def test_resolve_novelai_portion_explicit_id(tmp_path: Path) -> None:
    novel = tmp_path / "novel"
    novel.mkdir()
    root = tmp_path / "repo"
    b = novel / "references" / "novelai" / "work.naiv4vibebundle"
    b.parent.mkdir(parents=True)
    b.write_bytes(b"x")

    (novel / "_meta.yaml").write_text(
        """
version: 1
novelai:
  portion_default: cross_flat
  portions:
    work_only:
      path: references/novelai/work.naiv4vibebundle
      strength: 0.55
""".strip(),
        encoding="utf-8",
    )

    portion = resolve_novelai_portion(novel, root, portion_id="work_only")
    assert portion is not None
    assert portion.id == "work_only"
    assert portion.strength == 0.55


def test_load_meta_yaml_missing(tmp_path: Path) -> None:
    assert load_meta_yaml(tmp_path) is None
