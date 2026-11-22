"""紙書籍：章末ステータスのブロックを kind: status / status_line で渡し、最終の PDF まで描く（P5 ④）。"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from book_package.build import BuildError, _blocks_from_text, build_manifest  # noqa: E402
from book_package.lock import write_lock  # noqa: E402
from book_package.preflight import preflight_paper_pdf  # noqa: E402
from book_package.render import RenderError, render_paper_proof  # noqa: E402
from test_book_export import _make_exportable_package  # noqa: E402

CHAPTER = (
    "# 第一章\n\n<!-- scene: ch01-003 -->\n\n本文です。\n\n"
    "<!-- status:line -->《灯台の声》潮読みを得た\n\n"
    "続きの本文です。\n\n"
    "<!-- status:begin -->\n《記録》灯台の声より通知\n・夜目が第二段階に至った\n<!-- status:end -->\n"
)


def test_blocks_split_status_and_drop_markers() -> None:
    blocks = _blocks_from_text(CHAPTER)
    kinds = [block["kind"] for block in blocks]
    assert kinds == ["heading", "paragraph", "status_line", "paragraph", "status"]
    assert blocks[2]["text"] == "《灯台の声》潮読みを得た"
    assert blocks[4]["text"] == "《記録》灯台の声より通知\n・夜目が第二段階に至った"
    assert all("status:" not in block.get("text", "") for block in blocks)


def test_unclosed_status_block_is_build_error() -> None:
    with pytest.raises(BuildError):
        _blocks_from_text("本文。\n<!-- status:begin -->\nx\n")


def test_pdf_shows_status_content_without_markers(tmp_path: Path) -> None:
    from pypdf import PdfReader

    package = _make_exportable_package(tmp_path)
    (package / "_novel_text" / "novel_text01.md").write_text(CHAPTER, encoding="utf-8")
    write_lock(package, target="paper")
    manifest = build_manifest(package)
    pdf_path = tmp_path / "interior.pdf"
    try:
        render_paper_proof(manifest, pdf_path)
    except RenderError as exc:
        pytest.skip(str(exc))

    assert preflight_paper_pdf(pdf_path, manifest)["summary"]["errors"] == 0
    text = re.sub(r"\s+", "", "".join(page.extract_text() or "" for page in PdfReader(str(pdf_path)).pages))
    assert "status" not in text
    for expected in ("潮読みを得た", "灯台の声より通知", "夜目が第二段階に至った", "続きの本文です"):
        assert expected in text, expected


def test_status_rules_never_sit_alone_on_a_page(tmp_path: Path) -> None:
    """どの列の位置からブロックを始めても、罫だけのページができず、罫が下端まで伸びない。"""

    from book_package.render import _VerticalProof

    manifest = {
        "profile": {"width_mm": 105, "height_mm": 148,
                    "margins_mm": {"top": 15, "bottom": 15, "outer": 12, "inner": 12}},
        "package": {"title": "t", "author": {"name": "a"}},
    }
    text = "《記録》灯台の声より通知\n・技能「潮読み」を得た\n・夜目が第二段階に至った"
    for start in range(0, 30):
        proof = _VerticalProof(tmp_path / f"p{start}.pdf", manifest, "Helvetica")
        events: list[tuple[int, str, float]] = []
        draw_glyph = proof._draw_glyph

        def glyph(g: str, proof=proof, draw_glyph=draw_glyph) -> None:
            draw_glyph(g)
            events.append((proof.page_number, "glyph", 0.0))

        line = proof.canvas.line

        def ruled(x1, y1, x2, y2, proof=proof, line=line) -> None:
            line(x1, y1, x2, y2)
            events.append((proof.page_number, "rule", y1 - y2))

        proof._draw_glyph = glyph  # type: ignore[method-assign]
        proof.canvas.line = ruled  # type: ignore[method-assign]
        proof._begin_page(kind="content")
        for _ in range(start):
            proof._next_column()
        proof.status(text)
        rules = [e for e in events if e[1] == "rule"]
        assert len(rules) == 2
        for page, _, length in rules:
            assert any(e[0] == page and e[1] == "glyph" for e in events), (start, page)
            assert length < proof.top - proof.bottom
