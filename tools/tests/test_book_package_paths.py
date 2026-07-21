from __future__ import annotations

from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from book_package.paths import (  # noqa: E402
    PackagePathError,
    iter_book_file_references,
    normalize_package_path,
    resolve_package_path,
)
from book_package.schemas import load_book_package  # noqa: E402


FIXTURES = ROOT / "tools" / "fixtures" / "book_package"


def test_normalize_package_path_requires_portable_relative_path() -> None:
    assert normalize_package_path("_novel_text/novel_text01.md") == (
        "_novel_text/novel_text01.md"
    )
    for unsafe in (
        "../other.md",
        "./book.yaml",
        "/tmp/book.yaml",
        "C:/book.yaml",
        "a\\b.md",
    ):
        with pytest.raises(PackagePathError):
            normalize_package_path(unsafe)


def test_resolve_package_path_stays_in_package_root(tmp_path: Path) -> None:
    root = tmp_path / "novel"
    root.mkdir()
    target = resolve_package_path(root, "_novel_text/novel_text01.md")
    assert target == root / "_novel_text" / "novel_text01.md"


def test_iter_book_file_references_includes_matter_and_assets() -> None:
    book = load_book_package(FIXTURES / "book.yaml")
    book.illustrations[0].asset = "illustrations/_assets/illustration_00/cover.png"
    book.export.ebook.cover_image = (
        "illustrations/_assets/illustration_00/cover_ebook.jpg"
    )

    references = dict(iter_book_file_references(book))
    assert references["manuscript.frontmatter.characters.1"] == (
        "book_matter/frontmatter/characters.md"
    )
    assert references["manuscript.chapters.ch01.1"] == "_novel_text/novel_text01.md"
    assert references["illustrations.illust_cover.asset"].endswith("cover.png")
    assert references["export.ebook.cover_image"].endswith("cover_ebook.jpg")


def test_loader_rejects_unsafe_declared_path(tmp_path: Path) -> None:
    book_yaml = tmp_path / "book.yaml"
    book_yaml.write_text(
        """
schema_version: 2
book:
  title: t
  author: {name: a}
format:
  primary: paperback
  writing_direction: vertical
  binding: right
  trim_size: 文庫
manuscript:
  chapters:
    - id: ch01
      title: 第一章
      file: ../outside.md
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(PackagePathError, match="manuscript.chapters.ch01.1"):
        load_book_package(book_yaml)
