from __future__ import annotations

from pathlib import Path
import shutil
import struct
import sys
import zlib

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from book_package.build import BuildError, build_manifest  # noqa: E402
from book_package.lock import write_lock  # noqa: E402
from book_package.preflight import preflight_paper_pdf  # noqa: E402
from book_package.render import RenderError, render_paper_proof  # noqa: E402


FIXTURES = ROOT / "tools" / "fixtures" / "book_package"


def _chunk(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(
        ">I", zlib.crc32(kind + payload) & 0xFFFFFFFF
    )


def _write_png(path: Path, width: int = 1200, height: int = 1600) -> None:
    """Write a flat opaque PNG using only the standard library."""

    scanline = b"\x00" + b"\x80\x70\x60" * width
    raw = scanline * height
    png = (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + _chunk(b"IDAT", zlib.compress(raw, level=9))
        + _chunk(b"IEND", b"")
    )
    path.write_bytes(png)


def _make_exportable_package(tmp_path: Path) -> Path:
    package = tmp_path / "001_test"
    package.mkdir()
    book = (FIXTURES / "book.yaml").read_text(encoding="utf-8")
    book = book.replace("publish_date: null", "publish_date: 2026-09-13")
    book = book.replace("publisher: null", 'publisher: "サークル名"')
    book = book.replace("contact: null", 'contact: "contact@example.com"')
    book = book.replace(
        "    status: planned\n    asset: null\n  - id: illust_001",
        "    status: approved\n    asset: illustrations/_assets/illustration_00/cover.png\n  - id: illust_001",
        1,
    )
    (package / "book.yaml").write_text(book, encoding="utf-8")
    shutil.copy(FIXTURES / "rights.yaml", package / "rights.yaml")
    (package / "book_matter" / "frontmatter").mkdir(parents=True)
    (package / "book_matter" / "backmatter").mkdir(parents=True)
    (package / "_novel_text").mkdir()
    asset_dir = package / "illustrations" / "_assets" / "illustration_00"
    asset_dir.mkdir(parents=True)
    _write_png(asset_dir / "cover.png")
    (package / "book_matter" / "frontmatter" / "characters.md").write_text(
        "# 登場人物\n\n<!-- illustration: illust_cover -->\n\n紹介文。\n",
        encoding="utf-8",
    )
    (package / "book_matter" / "backmatter" / "afterword.md").write_text(
        "# あとがき\n\nおわり。\n", encoding="utf-8"
    )
    (package / "_novel_text" / "novel_text01.md").write_text(
        "# 第一章\n\n<!-- scene: ch01-003 -->\n\n本文です。\n",
        encoding="utf-8",
    )
    write_lock(package, target="paper")
    return package


def test_manifest_requires_clean_paper_lock(tmp_path: Path) -> None:
    package = _make_exportable_package(tmp_path)
    (package / "_novel_text" / "novel_text01.md").write_text(
        "# 第一章\n\n<!-- scene: ch01-003 -->\n\n改稿本文。\n",
        encoding="utf-8",
    )

    with pytest.raises(BuildError, match="変わっています"):
        build_manifest(package)


def test_exported_proof_has_b5_pages_embedded_font_and_odd_starts(tmp_path: Path) -> None:
    package = _make_exportable_package(tmp_path)
    manifest = build_manifest(package)
    pdf_path = tmp_path / "interior.pdf"
    try:
        render_paper_proof(manifest, pdf_path)
    except RenderError as exc:
        pytest.skip(str(exc))

    result = preflight_paper_pdf(pdf_path, manifest)

    assert result["summary"]["errors"] == 0
    assert result["conformance"] == "proof"
    assert manifest["entries"][0]["start_page"] % 2 == 1
    assert manifest["entries"][1]["start_page"] % 2 == 1
    assert manifest["placements"][0]["effective_dpi"] >= 250
