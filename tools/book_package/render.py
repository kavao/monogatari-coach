"""Minimal Japanese vertical-writing proof renderer for the paper build manifest."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
from typing import Any

from pypdf import PdfReader, PdfWriter
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas

from .build import POINTS_PER_MM


class RenderError(ValueError):
    """A build manifest could not be rendered into a proof PDF."""


_FONT_CANDIDATES = (
    Path(r"C:\Windows\Fonts\yumin.ttf"),
    Path(r"C:\Windows\Fonts\NotoSerifJP-VF.ttf"),
    Path(r"C:\Windows\Fonts\BIZ-UDMinchoM.ttc"),
)

_VERTICAL_FORMS = str.maketrans(
    {
        "、": "︑",
        "。": "︒",
        "「": "﹁",
        "」": "﹂",
        "『": "﹃",
        "』": "﹄",
        "（": "︵",
        "）": "︶",
        "［": "﹇",
        "］": "﹈",
        "｛": "︷",
        "｝": "︸",
        "…": "︙",
        "‥": "︰",
        "―": "︱",
        "—": "︱",
        "ー": "丨",
    }
)


def find_proof_font() -> Path:
    """Return a local Japanese TTF usable for a proof build."""

    configured = os.environ.get("MONOCRI_BOOK_FONT")
    if configured:
        selected = Path(configured).expanduser()
        if selected.is_file() and selected.suffix.lower() == ".ttf":
            return selected
        raise RenderError(
            "MONOCRI_BOOK_FONT は存在する .ttf の絶対パスで指定してください: "
            f"{selected}"
        )
    for candidate in _FONT_CANDIDATES:
        if candidate.is_file() and candidate.suffix.lower() == ".ttf":
            return candidate
    raise RenderError(
        "日本語 proof 用 TrueType フォントが見つかりません。"
        " MONOCRI_BOOK_FONT に .ttf の絶対パスを指定してください。"
    )


def _register_proof_font() -> tuple[str, Path]:
    font_path = find_proof_font()
    font_name = "MonocriProofMincho"
    if font_name not in pdfmetrics.getRegisteredFontNames():
        try:
            pdfmetrics.registerFont(TTFont(font_name, str(font_path), subfontIndex=0))
        except (OSError, ValueError) as exc:
            raise RenderError(f"proof フォントを登録できません: {font_path}: {exc}") from exc
    return font_name, font_path


def _png_dimensions(manifest: dict[str, Any], illustration_id: str) -> tuple[int, int]:
    for illustration in manifest["illustrations"]:
        if illustration["id"] == illustration_id:
            return int(illustration["width_px"]), int(illustration["height_px"])
    raise RenderError(f"manifest に挿絵 {illustration_id} がありません。")


def _asset_path(manifest: dict[str, Any], illustration_id: str) -> Path:
    root = Path(manifest["package"]["root"])
    for illustration in manifest["illustrations"]:
        if illustration["id"] == illustration_id:
            return root / illustration["asset"]
    raise RenderError(f"manifest に挿絵 {illustration_id} がありません。")


def _cover_illustration(manifest: dict[str, Any]) -> dict[str, Any]:
    """Return the one approved cover asset resolved in the build manifest."""

    covers = [item for item in manifest["illustrations"] if item["type"] == "cover"]
    if not covers:
        raise RenderError("閲覧用 proof に必要な approved の表紙 asset がありません。")
    if len(covers) != 1:
        raise RenderError("閲覧用 proof の表紙は1点だけ指定してください。")
    return covers[0]


class _VerticalProof:
    """Small right-to-left column flow engine for a deterministic proof PDF."""

    def __init__(self, output: Path, manifest: dict[str, Any], font_name: str) -> None:
        profile = manifest["profile"]
        self.width = float(profile["width_mm"]) * POINTS_PER_MM
        self.height = float(profile["height_mm"]) * POINTS_PER_MM
        self.canvas = Canvas(
            str(output),
            pagesize=(self.width, self.height),
            pageCompression=1,
            invariant=1,
            pdfVersion=(1, 4),
            initialFontName=font_name,  # type: ignore[reportArgumentType]
            initialFontSize=10.0,
        )
        self.canvas.setTitle(manifest["package"]["title"])
        self.canvas.setAuthor(manifest["package"]["author"]["name"])
        self.canvas.setCreator("Monogatari Coach paper proof renderer")
        self.font_name = font_name
        margins = profile["margins_mm"]
        self.top = self.height - float(margins["top"]) * POINTS_PER_MM
        self.bottom = float(margins["bottom"]) * POINTS_PER_MM
        self.right = self.width - float(margins["outer"]) * POINTS_PER_MM
        self.left = float(margins["inner"]) * POINTS_PER_MM
        self.font_size = 10.0
        self.glyph_pitch = 13.0
        self.column_pitch = 14.0
        self.page_number = 0
        self.column_x = self.right
        self.cursor_y = self.top
        self.current_page: dict[str, Any] | None = None
        self.pages: list[dict[str, Any]] = []

    def _begin_page(self, *, kind: str, entry_id: str | None = None) -> None:
        self.page_number += 1
        self.column_x = self.right
        self.cursor_y = self.top
        self.current_page = {
            "number": self.page_number,
            "kind": kind,
            "entry_id": entry_id,
            "illustrations": [],
            "has_visible_content": False,
        }
        self.canvas.setFont(self.font_name, self.font_size)

    def _finish_page(self) -> None:
        if self.current_page is None:
            return
        if self.current_page["has_visible_content"]:
            self.canvas.setFont(self.font_name, 8.0)
            self.canvas.drawCentredString(self.width / 2, 18.0, str(self.page_number))
        self.pages.append(self.current_page)
        self.canvas.showPage()
        self.current_page = None

    def _new_flow_page(self) -> None:
        self._finish_page()
        self._begin_page(kind="content")

    def start_entry(self, entry: dict[str, Any]) -> None:
        if self.current_page is not None:
            self._finish_page()
        self._begin_page(kind="section", entry_id=entry["id"])
        if entry["start_page_policy"] == "odd_page" and self.page_number % 2 == 0:
            current = self.current_page
            if current is None:  # pragma: no cover - _begin_page invariant
                raise RenderError("空白ページを開始できません。")
            current["kind"] = "blank"
            self._finish_page()
            self._begin_page(kind="section", entry_id=entry["id"])
        entry["start_page"] = self.page_number

    def _next_column(self) -> None:
        self.column_x -= self.column_pitch
        self.cursor_y = self.top
        if self.column_x < self.left:
            self._new_flow_page()

    def _draw_glyph(self, glyph: str) -> None:
        if self.current_page is None:  # pragma: no cover - internal invariant
            raise RenderError("描画ページが開始されていません。")
        if self.cursor_y - self.glyph_pitch < self.bottom:
            self._next_column()
        displayed = glyph.translate(_VERTICAL_FORMS)
        self.canvas.drawCentredString(self.column_x, self.cursor_y - self.font_size * 0.33, displayed)
        self.cursor_y -= self.glyph_pitch
        self.current_page["has_visible_content"] = True

    def paragraph(self, text: str) -> None:
        for line_index, line in enumerate(text.splitlines()):
            for glyph in line:
                self._draw_glyph(glyph)
            if line_index < len(text.splitlines()) - 1:
                self._next_column()
        self._next_column()

    def heading(self, text: str) -> None:
        previous_size = self.font_size
        previous_pitch = self.glyph_pitch
        previous_column = self.column_pitch
        self.font_size = 16.0
        self.glyph_pitch = 20.0
        self.column_pitch = 22.0
        self.canvas.setFont(self.font_name, self.font_size)
        for glyph in text:
            self._draw_glyph(glyph)
        self._next_column()
        self.font_size = previous_size
        self.glyph_pitch = previous_pitch
        self.column_pitch = previous_column
        self.canvas.setFont(self.font_name, self.font_size)

    def rule(self) -> None:
        self._next_column()

    def illustration(self, manifest: dict[str, Any], illustration_id: str) -> None:
        if self.current_page is not None and self.current_page["has_visible_content"]:
            self._finish_page()
            self._begin_page(kind="illustration")
        if self.current_page is None:
            self._begin_page(kind="illustration")
        current = self.current_page
        if current is None:  # pragma: no cover - _begin_page invariant
            raise RenderError("挿絵ページを開始できません。")
        asset = _asset_path(manifest, illustration_id)
        width_px, height_px = _png_dimensions(manifest, illustration_id)
        if width_px <= 0 or height_px <= 0:
            raise RenderError(f"挿絵 {illustration_id} の PNG 寸法を取得できません。")
        max_width = min(300.0, self.right - self.left)
        max_height = self.top - self.bottom - 36.0
        aspect = height_px / width_px
        draw_width = min(max_width, max_height / aspect)
        draw_height = draw_width * aspect
        x = (self.width - draw_width) / 2
        y = (self.height - draw_height) / 2 + 8.0
        self.canvas.drawImage(
            ImageReader(str(asset)),
            x,
            y,
            width=draw_width,
            height=draw_height,
            preserveAspectRatio=True,
            mask="auto",
        )
        current["illustrations"].append(
            {
                "id": illustration_id,
                "asset": asset.relative_to(Path(manifest["package"]["root"])).as_posix(),
                "draw_width_pt": round(draw_width, 3),
                "draw_height_pt": round(draw_height, 3),
                "source_width_px": width_px,
                "source_height_px": height_px,
            }
        )
        current["has_visible_content"] = True
        self._finish_page()
        self._begin_page(kind="content")

    def finish(self) -> list[dict[str, Any]]:
        self._finish_page()
        self.canvas.save()
        return self.pages


def render_paper_proof(manifest: dict[str, Any], output: Path) -> dict[str, Any]:
    """Render one JIS B5 vertical-writing interior proof and return page metadata."""

    if manifest["target"] != "paper":
        raise RenderError(f"paper proof 以外は未対応です: {manifest['target']}")
    font_name, font_path = _register_proof_font()
    output.parent.mkdir(parents=True, exist_ok=True)
    renderer = _VerticalProof(output, manifest, font_name)
    for entry in manifest["entries"]:
        renderer.start_entry(entry)
        for source in entry["files"]:
            for block in source["blocks"]:
                kind = block["kind"]
                if kind == "paragraph":
                    renderer.paragraph(block["text"])
                elif kind == "heading":
                    renderer.heading(block["text"])
                elif kind == "rule":
                    renderer.rule()
                elif kind == "illustration":
                    renderer.illustration(manifest, block["illustration_id"])
                else:  # pragma: no cover - manifest builder owns the block vocabulary
                    raise RenderError(f"未知の本文ブロックです: {kind}")
    pages = renderer.finish()
    placements = [
        {"illustration_id": item["id"], "page": page["number"], **item}
        for page in pages
        for item in page["illustrations"]
    ]
    manifest["placements"] = placements
    manifest["render"] = {
        "output": output.name,
        "page_count": len(pages),
        "pages": pages,
        "font": {
            "name": font_name,
            "path": str(font_path),
            "embedded": True,
            "purpose": "local proof only; confirm production font licensing before print submission",
        },
    }
    return manifest["render"]


def render_reader_proof(
    manifest: dict[str, Any], interior_pdf: Path, output: Path
) -> dict[str, Any]:
    """Create a reader-facing PDF with the approved cover before the interior proof.

    This deliberately emits a single front-cover page only. A printer-ready wrap
    cover (front, spine, and back) depends on printer specifications and is not
    inferred by the local proof renderer.
    """

    if manifest["target"] != "paper":
        raise RenderError(f"paper proof 以外は未対応です: {manifest['target']}")
    if not interior_pdf.is_file():
        raise RenderError(f"本文 proof PDF がありません: {interior_pdf}")

    cover = _cover_illustration(manifest)
    cover_asset = _asset_path(manifest, str(cover["id"]))
    if not cover_asset.is_file():  # pragma: no cover - manifest build validates this
        raise RenderError(f"表紙 asset がありません: {cover_asset}")
    source_width = int(cover["width_px"])
    source_height = int(cover["height_px"])
    if source_width <= 0 or source_height <= 0:
        raise RenderError(f"表紙 asset の寸法を取得できません: {cover_asset}")

    profile = manifest["profile"]
    width = float(profile["width_mm"]) * POINTS_PER_MM
    height = float(profile["height_mm"]) * POINTS_PER_MM
    font_name, _ = _register_proof_font()
    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(
        mode="wb", suffix=".pdf", prefix=f".{output.stem}-cover-", dir=output.parent, delete=False
    ) as temporary:
        cover_page_pdf = Path(temporary.name)

    try:
        canvas = Canvas(
            str(cover_page_pdf),
            pagesize=(width, height),
            pageCompression=1,
            invariant=1,
            pdfVersion=(1, 4),
            initialFontName=font_name,  # type: ignore[reportArgumentType]
            initialFontSize=10.0,
        )
        canvas.setTitle(manifest["package"]["title"])
        canvas.setAuthor(manifest["package"]["author"]["name"])
        canvas.setCreator("Monogatari Coach reader proof renderer")
        scale = min(width / source_width, height / source_height)
        draw_width = source_width * scale
        draw_height = source_height * scale
        canvas.drawImage(
            ImageReader(str(cover_asset)),
            (width - draw_width) / 2,
            (height - draw_height) / 2,
            width=draw_width,
            height=draw_height,
            mask="auto",
        )
        canvas.showPage()
        canvas.save()

        writer = PdfWriter()
        writer.append(str(cover_page_pdf))
        writer.append(str(interior_pdf))
        writer.add_metadata(
            {
                "/Title": manifest["package"]["title"],
                "/Author": manifest["package"]["author"]["name"],
                "/Creator": "Monogatari Coach reader proof renderer",
            }
        )
        with output.open("wb") as stream:
            writer.write(stream)
    except OSError as exc:
        raise RenderError(f"閲覧用 proof PDF を生成できません: {exc}") from exc
    finally:
        cover_page_pdf.unlink(missing_ok=True)

    page_count = len(PdfReader(str(output), strict=True).pages)
    manifest["reader_proof"] = {
        "output": output.name,
        "page_count": page_count,
        "cover": {
            "id": cover["id"],
            "asset": cover["asset"],
            "page": 1,
            "source_width_px": source_width,
            "source_height_px": source_height,
            "draw_width_pt": round(draw_width, 3),
            "draw_height_pt": round(draw_height, 3),
        },
        "purpose": "reader preview only; not a printer-ready wrap cover",
    }
    return manifest["reader_proof"]
