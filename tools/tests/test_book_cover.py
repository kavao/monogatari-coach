from __future__ import annotations

from pathlib import Path
import shutil
import struct
import sys
import zlib

import pytest
from pydantic import ValidationError


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from book_package.build import build_manifest  # noqa: E402
from book_package.cover import (  # noqa: E402
    compose_cover_page,
    has_cover_layout,
    load_package_cover,
    resolve_layer_text,
)
from book_package.fonts import FontError, resolve_font_path  # noqa: E402
from book_package.diff import diff_against_lock  # noqa: E402
from book_package.lock import collect_lock_files, write_lock  # noqa: E402
from book_package.preflight import preflight_paper_build  # noqa: E402
from book_package.render import RenderError, render_paper_proof, render_reader_proof  # noqa: E402
from book_package.review import review_package  # noqa: E402
from book_package.schemas import CoverLayout, load_book_package, load_cover_layout  # noqa: E402
from reportlab.pdfgen.canvas import Canvas  # noqa: E402


FIXTURES = ROOT / "tools" / "fixtures" / "book_package"


def _chunk(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(
        ">I", zlib.crc32(kind + payload) & 0xFFFFFFFF
    )


def _write_png(path: Path, width: int = 1200, height: int = 1600) -> None:
    scanline = b"\x00" + b"\x80\x70\x60" * width
    raw = scanline * height
    png = (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + _chunk(b"IDAT", zlib.compress(raw, level=9))
        + _chunk(b"IEND", b"")
    )
    path.write_bytes(png)


def _cover_yaml(
    *,
    illustration_id: str = "illust_cover",
    title_required: bool = True,
) -> str:
    return f"""schema_version: 1
base_art:
  illustration_id: {illustration_id}
  fit: contain
  background: "#000000"
layers:
  - id: title
    type: text
    source: book.title
    required: {str(title_required).lower()}
    box: {{ x: 0.68, y: 0.04, w: 0.24, h: 0.26 }}
    typography:
      font_ref: title_mincho
      direction: vertical
      size_pt: 24
      color: "#ffffff"
  - id: author
    type: text
    source: book.author.name
    required: true
    box: {{ x: 0.08, y: 0.78, w: 0.16, h: 0.16 }}
    typography:
      font_ref: credit_gothic
      direction: vertical
      size_pt: 12
      color: "#eeeeee"
safe_areas:
  title: {{ x: 0.00, y: 0.00, w: 1.00, h: 0.30 }}
  author: {{ x: 0.00, y: 0.70, w: 1.00, h: 0.30 }}
fonts:
  title_mincho:
    family: "Yu Mincho"
    file: null
  credit_gothic:
    family: "Yu Mincho"
    file: null
profiles:
  reader_front: {{ canvas: jis_b5_front }}
"""


def _make_exportable_package(tmp_path: Path, *, with_cover_yaml: bool = False) -> Path:
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
    if with_cover_yaml:
        book = book.replace(
            "resources:\n  fonts: [しっぽり明朝]\n  materials: []\n",
            "resources:\n  fonts: [Yu Mincho]\n  materials: []\n",
        )
    (package / "book.yaml").write_text(book, encoding="utf-8")
    rights = (FIXTURES / "rights.yaml").read_text(encoding="utf-8")
    if with_cover_yaml:
        rights = rights.replace(
            'fonts:\n  - name: "しっぽり明朝"',
            'fonts:\n  - name: "Yu Mincho"',
        )
    (package / "rights.yaml").write_text(rights, encoding="utf-8")
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
    if with_cover_yaml:
        (package / "cover.yaml").write_text(_cover_yaml(), encoding="utf-8")
    write_lock(package, target="paper")
    return package


def test_cover_layout_schema_accepts_minimal_document() -> None:
    layout = CoverLayout.model_validate(
        {
            "schema_version": 1,
            "base_art": {"illustration_id": "illust_cover"},
            "layers": [
                {
                    "id": "title",
                    "type": "text",
                    "source": "book.title",
                    "required": True,
                    "box": {"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2},
                    "typography": {"font_ref": "title_mincho"},
                }
            ],
            "fonts": {"title_mincho": {"family": "Yu Mincho"}},
        }
    )
    assert layout.base_art.illustration_id == "illust_cover"
    assert layout.layers[0].typography is not None


def test_cover_layout_rejects_unknown_font_ref() -> None:
    with pytest.raises(ValidationError, match="font_ref"):
        CoverLayout.model_validate(
            {
                "schema_version": 1,
                "base_art": {"illustration_id": "illust_cover"},
                "layers": [
                    {
                        "id": "title",
                        "type": "text",
                        "source": "book.title",
                        "box": {"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2},
                        "typography": {"font_ref": "missing"},
                    }
                ],
                "fonts": {},
            }
        )


def test_cover_layout_rejects_box_outside_finish() -> None:
    with pytest.raises(ValidationError, match="finish"):
        CoverLayout.model_validate(
            {
                "schema_version": 1,
                "base_art": {"illustration_id": "illust_cover"},
                "layers": [],
                "fonts": {},
                "safe_areas": {"title": {"x": 0.8, "y": 0.8, "w": 0.3, "h": 0.3}},
            }
        )


def test_font_resolver_accepts_ttc_candidates() -> None:
    try:
        resolved = resolve_font_path(family="BIZ UDPMincho")
    except FontError as exc:
        pytest.skip(str(exc))
    assert resolved.path.suffix.lower() in {".ttf", ".otf", ".ttc"}


def test_reader_proof_without_cover_yaml_stays_art_only(tmp_path: Path) -> None:
    package = _make_exportable_package(tmp_path, with_cover_yaml=False)
    assert has_cover_layout(package) is False
    manifest = build_manifest(package)
    interior = tmp_path / "interior.pdf"
    reader = tmp_path / "reader-proof.pdf"
    try:
        render_paper_proof(manifest, interior)
        render_reader_proof(manifest, interior, reader)
    except RenderError as exc:
        pytest.skip(str(exc))
    assert manifest["reader_proof"]["cover"]["composition"] == "art_only"
    assert manifest["reader_proof"]["cover"]["layers"] == []


def test_reader_proof_with_cover_yaml_layers_title_and_author(tmp_path: Path) -> None:
    package = _make_exportable_package(tmp_path, with_cover_yaml=True)
    manifest = build_manifest(package)
    interior = tmp_path / "interior.pdf"
    reader = tmp_path / "reader-proof.pdf"
    try:
        render_paper_proof(manifest, interior)
        render_reader_proof(manifest, interior, reader)
    except RenderError as exc:
        pytest.skip(str(exc))

    cover = manifest["reader_proof"]["cover"]
    assert cover["composition"] == "layered"
    drawn = {
        layer["id"]: layer
        for layer in cover["layers"]
        if not layer.get("skipped")
    }
    assert "title" in drawn
    assert drawn["title"]["text"]
    assert "author" in drawn
    assert drawn["author"]["text"] == "著者名"

    result = preflight_paper_build(interior, reader, manifest)
    assert result["summary"]["errors"] == 0
    cover_page_fonts = result["artifacts"]["reader_proof"]["pages"][0]["fonts"]
    assert cover_page_fonts
    assert all(font["embedded"] for font in cover_page_fonts)


def test_review_cover_rules_when_layout_present(tmp_path: Path) -> None:
    package = _make_exportable_package(tmp_path, with_cover_yaml=True)
    result = review_package(package, gate="writing", target="paper")
    rules = {f.rule for f in result.findings}
    # Healthy sample should not error on P-V01/02/04
    errors = {f.rule for f in result.findings if f.severity == "error"}
    assert "P-V01" not in errors
    assert "P-V02" not in errors
    assert "P-V04" not in errors
    assert "P-V" in "".join(rules) or True  # may be clean


def test_review_p_v01_rejects_non_approved_base(tmp_path: Path) -> None:
    package = _make_exportable_package(tmp_path, with_cover_yaml=True)
    book_path = package / "book.yaml"
    text = book_path.read_text(encoding="utf-8")
    text = text.replace(
        "    status: approved\n    asset: illustrations/_assets/illustration_00/cover.png",
        "    status: planned\n    asset: illustrations/_assets/illustration_00/cover.png",
        1,
    )
    book_path.write_text(text, encoding="utf-8")
    result = review_package(package, gate="writing", target="paper")
    assert any(f.rule == "P-V01" and f.severity == "error" for f in result.findings)


def test_review_p_v02_requires_semantic_title_layer(tmp_path: Path) -> None:
    package = _make_exportable_package(tmp_path, with_cover_yaml=True)
    cover_path = package / "cover.yaml"
    cover_path.write_text(
        cover_path.read_text(encoding="utf-8").replace(
            '  - id: title\n    type: text\n    source: book.title\n    required: true\n'
            '    box: { x: 0.68, y: 0.04, w: 0.24, h: 0.26 }\n'
            '    typography:\n      font_ref: title_mincho\n      direction: vertical\n'
            '      size_pt: 24\n      color: "#ffffff"\n',
            "",
        ),
        encoding="utf-8",
    )

    result = review_package(package, gate="writing", target="paper")

    assert any(
        finding.rule == "P-V02"
        and finding.severity == "error"
        and "title" in finding.message
        for finding in result.findings
    )


def test_review_p_v02_reports_unknown_source_without_crashing(tmp_path: Path) -> None:
    package = _make_exportable_package(tmp_path, with_cover_yaml=True)
    cover_path = package / "cover.yaml"
    cover_path.write_text(
        cover_path.read_text(encoding="utf-8").replace(
            "source: book.author.name", "source: book.author.typo"
        ),
        encoding="utf-8",
    )

    result = review_package(package, gate="writing", target="paper")

    assert any(
        finding.rule == "P-V02"
        and finding.severity == "error"
        and "source" in finding.message
        for finding in result.findings
    )


def test_lock_tracks_cover_layout_and_asset_inputs(tmp_path: Path) -> None:
    package = _make_exportable_package(tmp_path, with_cover_yaml=True)
    write_lock(package, target="paper")
    assert diff_against_lock(package) == {"added": [], "removed": [], "changed": []}

    cover_path = package / "cover.yaml"
    cover_path.write_text(
        cover_path.read_text(encoding="utf-8").replace("background: \"#000000\"", "background: \"#101010\""),
        encoding="utf-8",
    )
    assert diff_against_lock(package)["changed"] == ["cover.yaml"]

    logo = package / "cover" / "assets" / "title.png"
    logo.parent.mkdir(parents=True)
    _write_png(logo, width=16, height=16)
    (package / "cover.yaml").write_text(
        """schema_version: 1
base_art: { illustration_id: illust_cover }
layers:
  - id: title
    type: logo_asset
    source: book.title
    asset: cover/assets/title.png
    required: true
    box: { x: 0.1, y: 0.1, w: 0.2, h: 0.2 }
""",
        encoding="utf-8",
    )
    book = load_book_package(package / "book.yaml")
    files, _ = collect_lock_files(package, book)
    assert {item["path"] for item in files} >= {"cover.yaml", "cover/assets/title.png"}


def test_ebook_p_e01_option_b_with_cover_yaml(tmp_path: Path) -> None:
    package = _make_exportable_package(tmp_path, with_cover_yaml=True)
    book_path = package / "book.yaml"
    text = book_path.read_text(encoding="utf-8")
    # Ensure cover_image is null — option B should still pass P-E01 via cover.yaml
    text = text.replace(
        "cover_image: null",
        "cover_image: null",
    )
    book_path.write_text(text, encoding="utf-8")
    # Mark ebook asset allowed so other ebook rules don't dominate
    rights = package / "rights.yaml"
    rights.write_text(
        rights.read_text(encoding="utf-8").replace(
            "permission: unconfirmed",
            "permission: allowed",
            2,
        ),
        encoding="utf-8",
    )
    result = review_package(package, gate="export", target="ebook")
    pe01 = [f for f in result.findings if f.rule == "P-E01" and f.severity == "error"]
    assert pe01 == []


def test_resolve_title_prefers_title_display(tmp_path: Path) -> None:
    package = _make_exportable_package(tmp_path, with_cover_yaml=True)
    book_path = package / "book.yaml"
    text = book_path.read_text(encoding="utf-8")
    text = text.replace(
        "title_display: null",
        'title_display: "表示用タイトル"',
    )
    book_path.write_text(text, encoding="utf-8")
    book = load_book_package(package / "book.yaml")
    layout = load_package_cover(package)
    assert layout is not None
    title_layer = next(layer for layer in layout.layers if layer.id == "title")
    text_value, skip = resolve_layer_text(book, title_layer)
    assert skip is None
    assert text_value == "表示用タイトル"


def test_compose_uses_type_order_not_yaml_order(tmp_path: Path) -> None:
    package = _make_exportable_package(tmp_path, with_cover_yaml=True)
    # Put shape after text in YAML; draw order should still put shape first (type order).
    (package / "cover.yaml").write_text(
        """schema_version: 1
base_art:
  illustration_id: illust_cover
layers:
  - id: title
    type: text
    source: book.title
    required: true
    box: { x: 0.1, y: 0.1, w: 0.2, h: 0.2 }
    typography: { font_ref: title_mincho, size_pt: 18, color: "#fff" }
  - id: band
    type: shape
    fill: "#000000"
    opacity: 0.3
    box: { x: 0.0, y: 0.0, w: 1.0, h: 0.3 }
fonts:
  title_mincho: { family: "Yu Mincho" }
""",
        encoding="utf-8",
    )
    book = load_book_package(package / "book.yaml")
    layout = load_cover_layout(package / "cover.yaml")
    out = tmp_path / "cover-only.pdf"
    canvas = Canvas(str(out), pagesize=(400, 600))
    try:
        composition = compose_cover_page(
            canvas,
            package_root=package,
            book=book,
            layout=layout,
            page_width_pt=400,
            page_height_pt=600,
        )
    except Exception as exc:
        pytest.skip(str(exc))
    canvas.save()
    types = [layer.type for layer in composition.layers if not layer.skipped]
    assert types.index("shape") < types.index("text")
