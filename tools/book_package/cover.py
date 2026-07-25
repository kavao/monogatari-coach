"""Cover layer composition for reader proof / ebook front / future wrap covers.

``book.yaml`` owns bibliography and display flags; ``cover.yaml`` owns placement.
When ``cover.yaml`` is absent, callers keep the legacy art-only front page.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
import struct
from typing import Any

from reportlab.lib.colors import Color, HexColor, white
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas

from .fonts import FontError, register_named_fonts
from .paths import resolve_package_path
from .schemas import (
    BookPackage,
    CoverBox,
    CoverLayout,
    CoverLayer,
    Illustration,
    load_book_package,
    load_cover_layout,
)

# Keep independent of build.py to avoid review → cover → build → review cycles.
POINTS_PER_MM = 72.0 / 25.4


def _png_dimensions(path: Path) -> tuple[int, int]:
    with path.open("rb") as handle:
        header = handle.read(24)
    if header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        raise CoverComposeError(f"PNG ファイルではありません: {path}")
    return struct.unpack(">II", header[16:24])


class CoverComposeError(ValueError):
    """Cover layout cannot be composed into a page."""


# Draw order is by type, not YAML order (plan §5.1).
_LAYER_DRAW_ORDER = {
    "shape": 10,
    "logo_asset": 20,
    "image": 30,
    "text": 40,
    "barcode": 50,
}

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


@dataclass
class PlacedLayer:
    id: str
    type: str
    text: str | None
    box: dict[str, float]
    font_ref: str | None = None
    required: bool = False
    skipped: bool = False
    skip_reason: str | None = None


@dataclass
class CoverComposition:
    """Result of resolving + drawing one front cover page."""

    layout: CoverLayout
    base_illustration_id: str
    base_asset: str
    source_width_px: int
    source_height_px: int
    draw_width_pt: float
    draw_height_pt: float
    page_width_pt: float
    page_height_pt: float
    layers: list[PlacedLayer] = field(default_factory=list)
    fonts: dict[str, str] = field(default_factory=dict)  # font_ref → path
    used_text: bool = False

    def to_manifest_cover(self) -> dict[str, Any]:
        safe_areas = {
            name: {"x": box.x, "y": box.y, "w": box.w, "h": box.h}
            for name, box in self.layout.safe_areas.items()
        }
        return {
            "id": self.base_illustration_id,
            "asset": self.base_asset,
            "page": 1,
            "source_width_px": self.source_width_px,
            "source_height_px": self.source_height_px,
            "draw_width_pt": round(self.draw_width_pt, 3),
            "draw_height_pt": round(self.draw_height_pt, 3),
            "layers": [
                {
                    "id": layer.id,
                    "type": layer.type,
                    "text": layer.text,
                    "box": layer.box,
                    "font_ref": layer.font_ref,
                    "required": layer.required,
                    "skipped": layer.skipped,
                    "skip_reason": layer.skip_reason,
                }
                for layer in self.layers
            ],
            "safe_areas": safe_areas,
            "fonts": dict(self.fonts),
            "composition": "layered" if self.layout else "art_only",
        }


def cover_yaml_path(package_root: str | Path) -> Path:
    return Path(package_root).resolve() / "cover.yaml"


def has_cover_layout(package_root: str | Path) -> bool:
    return cover_yaml_path(package_root).is_file()


def load_package_cover(package_root: str | Path) -> CoverLayout | None:
    path = cover_yaml_path(package_root)
    if not path.is_file():
        return None
    return load_cover_layout(path)


def _resolve_source(book: BookPackage, source: str) -> str | None:
    """Resolve a dotted source path against book.yaml fields."""

    # Prefer display overrides for the common title path.
    if source == "book.title":
        display = book.cover.front.title_display
        return display if display else book.book.title
    if source == "cover.front.title_display":
        return book.cover.front.title_display or book.book.title
    if source == "book.subtitle":
        return book.book.subtitle
    if source == "book.author.name":
        return book.book.author.name
    if source == "book.illustrator.name":
        if book.book.illustrator is None:
            return None
        return book.book.illustrator.name
    if source == "book.volume":
        return str(book.book.volume) if book.book.volume is not None else None
    if source == "sales.catch_copy":
        return book.sales.catch_copy
    if source == "sales.description":
        return book.sales.description
    if source == "cover.back.blurb":
        return book.cover.back.blurb
    if source == "cover.back.isbn":
        return book.cover.back.isbn
    raise CoverComposeError(f"未知の source です: {source}")


def _layer_display_gate(book: BookPackage, layer: CoverLayer) -> str | None:
    """Return a skip reason when book.yaml display flags suppress the layer."""

    source = layer.source or ""
    if source in {"book.author.name"} or layer.id in {"author", "credit_author"}:
        if not book.cover.front.credit_author:
            return "cover.front.credit_author が false"
    if source in {"book.illustrator.name"} or layer.id in {
        "illustrator",
        "credit_illustrator",
    }:
        if not book.cover.front.credit_illustrator:
            return "cover.front.credit_illustrator が false"
    if source == "book.volume" and book.book.volume == 1:
        # Single-volume works should not print "1" as a volume badge by default.
        return "volume=1 の単巻は表1へ出さない"
    return None


def resolve_layer_text(book: BookPackage, layer: CoverLayer) -> tuple[str | None, str | None]:
    """Return ``(text, skip_reason)``. skip_reason set means the layer is omitted."""

    gate = _layer_display_gate(book, layer)
    if gate is not None:
        return None, gate
    if layer.value is not None:
        text = layer.value.strip()
        if not text:
            return None, "value が空"
        return text, None
    if layer.source is None:
        return None, "source / value がありません"
    text = _resolve_source(book, layer.source)
    if text is None or not str(text).strip():
        if layer.required:
            return None, f"必須 source {layer.source} が解決できません"
        return None, f"source {layer.source} が空のため省略"
    return str(text).strip(), None


def _parse_color(value: str) -> Color:
    raw = value.strip()
    if raw.startswith("#"):
        return HexColor(raw)
    # named minimal set
    if raw.lower() in {"white", "#fff", "#ffffff"}:
        return white
    return HexColor(raw) if raw.startswith("#") else HexColor("#ffffff")


def _box_to_points(
    box: CoverBox | Mapping[str, float], page_width: float, page_height: float
) -> tuple[float, float, float, float]:
    """Convert normalized top-left box to reportlab left/bottom/width/height points."""

    if isinstance(box, CoverBox):
        x_n, y_n, w_n, h_n = float(box.x), float(box.y), float(box.w), float(box.h)
    else:
        x_n, y_n, w_n, h_n = float(box["x"]), float(box["y"]), float(box["w"]), float(box["h"])
    x = x_n * page_width
    w = w_n * page_width
    h = h_n * page_height
    # top-left y_n → bottom y for reportlab
    y = page_height - (y_n + h_n) * page_height
    return x, y, w, h


def _find_cover_illustration(
    book: BookPackage, illustration_id: str
) -> Illustration:
    matches = [item for item in book.illustrations if item.id == illustration_id]
    if not matches:
        raise CoverComposeError(
            f"base_art.illustration_id が book.yaml にありません: {illustration_id}"
        )
    item = matches[0]
    if item.type != "cover":
        raise CoverComposeError(
            f"base_art.illustration_id は type=cover である必要があります: {illustration_id}"
        )
    if item.status != "approved":
        raise CoverComposeError(
            f"base_art は approved である必要があります: {illustration_id} ({item.status})"
        )
    if not item.asset:
        raise CoverComposeError(f"base_art の asset がありません: {illustration_id}")
    return item


def _draw_base_art(
    canvas: Canvas,
    asset_path: Path,
    *,
    page_width: float,
    page_height: float,
    fit: str,
    background: str,
    source_width: int,
    source_height: int,
) -> tuple[float, float]:
    canvas.setFillColor(_parse_color(background))
    canvas.rect(0, 0, page_width, page_height, fill=1, stroke=0)
    if fit == "cover":
        scale = max(page_width / source_width, page_height / source_height)
    else:
        scale = min(page_width / source_width, page_height / source_height)
    draw_width = source_width * scale
    draw_height = source_height * scale
    canvas.drawImage(
        ImageReader(str(asset_path)),
        (page_width - draw_width) / 2,
        (page_height - draw_height) / 2,
        width=draw_width,
        height=draw_height,
        mask="auto",
    )
    return draw_width, draw_height


def _draw_text_layer(
    canvas: Canvas,
    *,
    text: str,
    box: Any,
    page_width: float,
    page_height: float,
    face_name: str,
    size_pt: float,
    direction: str,
    tracking: float,
    color: str,
) -> None:
    x, y, w, h = _box_to_points(box, page_width, page_height)
    canvas.setFillColor(_parse_color(color))
    canvas.setFont(face_name, size_pt)
    pitch = size_pt * (1.0 + tracking)

    if direction == "vertical":
        # Start near the horizontal center of the box, top glyph first.
        cursor_x = x + w / 2
        cursor_y = y + h - size_pt * 0.85
        for glyph in text:
            if cursor_y < y:
                break
            displayed = glyph.translate(_VERTICAL_FORMS)
            canvas.drawCentredString(cursor_x, cursor_y, displayed)
            cursor_y -= pitch
    else:
        cursor_x = x
        # Vertically center the baseline within the box (credits sit better on the floor band).
        cursor_y = y + max((h - size_pt) / 2.0, 0.0)
        # Simple left-to-right; wrap is out of scope for C1 titles/credits.
        canvas.drawString(cursor_x, cursor_y, text)


def _draw_shape_layer(
    canvas: Canvas,
    *,
    box: Any,
    page_width: float,
    page_height: float,
    fill: str,
    opacity: float | None,
) -> None:
    x, y, w, h = _box_to_points(box, page_width, page_height)
    color = _parse_color(fill)
    if opacity is not None:
        color = Color(color.red, color.green, color.blue, alpha=opacity)
    canvas.setFillColor(color)
    canvas.rect(x, y, w, h, fill=1, stroke=0)


def compose_cover_page(
    canvas: Canvas,
    *,
    package_root: Path,
    book: BookPackage,
    layout: CoverLayout,
    page_width_pt: float,
    page_height_pt: float,
) -> CoverComposition:
    """Draw base art + layers onto ``canvas`` (does not call showPage/save)."""

    illustration = _find_cover_illustration(book, layout.base_art.illustration_id)
    asset_path = resolve_package_path(package_root, illustration.asset or "")
    if not asset_path.is_file():
        raise CoverComposeError(f"表紙 asset がありません: {asset_path}")
    source_width, source_height = _png_dimensions(asset_path)

    font_specs = {
        ref: {
            "family": face.family,
            "file": face.file,
            "subfont_index": face.subfont_index,
        }
        for ref, face in layout.fonts.items()
    }
    try:
        resolved_fonts = register_named_fonts(font_specs, package_root=package_root)
    except FontError as exc:
        raise CoverComposeError(str(exc)) from exc

    draw_width, draw_height = _draw_base_art(
        canvas,
        asset_path,
        page_width=page_width_pt,
        page_height=page_height_pt,
        fit=layout.base_art.fit,
        background=layout.base_art.background,
        source_width=source_width,
        source_height=source_height,
    )

    ordered = sorted(
        layout.layers,
        key=lambda layer: (_LAYER_DRAW_ORDER.get(layer.type, 99), layer.id),
    )
    placed: list[PlacedLayer] = []
    used_text = False

    for layer in ordered:
        box_dict = {
            "x": layer.box.x,
            "y": layer.box.y,
            "w": layer.box.w,
            "h": layer.box.h,
        }
        if layer.type == "text":
            text, skip_reason = resolve_layer_text(book, layer)
            if skip_reason is not None:
                soft_skip = skip_reason.startswith("cover.front.") or skip_reason.startswith(
                    "volume="
                )
                if layer.required and not soft_skip:
                    raise CoverComposeError(
                        f"必須レイヤー {layer.id} を解決できません: {skip_reason}"
                    )
                placed.append(
                    PlacedLayer(
                        id=layer.id,
                        type=layer.type,
                        text=None,
                        box=box_dict,
                        font_ref=layer.typography.font_ref if layer.typography else None,
                        required=layer.required,
                        skipped=True,
                        skip_reason=skip_reason,
                    )
                )
                continue
            assert layer.typography is not None and text is not None
            face = f"MonocriCover_{layer.typography.font_ref}"
            _draw_text_layer(
                canvas,
                text=text,
                box=layer.box,
                page_width=page_width_pt,
                page_height=page_height_pt,
                face_name=face,
                size_pt=layer.typography.size_pt,
                direction=layer.typography.direction,
                tracking=layer.typography.tracking,
                color=layer.typography.color,
            )
            used_text = True
            placed.append(
                PlacedLayer(
                    id=layer.id,
                    type=layer.type,
                    text=text,
                    box=box_dict,
                    font_ref=layer.typography.font_ref,
                    required=layer.required,
                )
            )
        elif layer.type == "shape":
            _draw_shape_layer(
                canvas,
                box=layer.box,
                page_width=page_width_pt,
                page_height=page_height_pt,
                fill=layer.fill or "#000000",
                opacity=layer.opacity,
            )
            placed.append(
                PlacedLayer(
                    id=layer.id,
                    type=layer.type,
                    text=None,
                    box=box_dict,
                    required=layer.required,
                )
            )
        elif layer.type in {"logo_asset", "image", "barcode"}:
            # C1: accept schema and reserve placement; drawing deferred if asset missing
            # is an error for required layers.
            if not layer.asset:
                raise CoverComposeError(f"レイヤー {layer.id} に asset がありません。")
            asset = resolve_package_path(package_root, layer.asset)
            if not asset.is_file():
                if layer.required:
                    raise CoverComposeError(f"レイヤー {layer.id} の asset がありません: {asset}")
                placed.append(
                    PlacedLayer(
                        id=layer.id,
                        type=layer.type,
                        text=None,
                        box=box_dict,
                        required=layer.required,
                        skipped=True,
                        skip_reason="asset 不在",
                    )
                )
                continue
            x, y, w, h = _box_to_points(layer.box, page_width_pt, page_height_pt)
            canvas.drawImage(
                ImageReader(str(asset)),
                x,
                y,
                width=w,
                height=h,
                preserveAspectRatio=True,
                mask="auto",
            )
            placed.append(
                PlacedLayer(
                    id=layer.id,
                    type=layer.type,
                    text=None,
                    box=box_dict,
                    required=layer.required,
                )
            )
        else:  # pragma: no cover - schema restricts types
            raise CoverComposeError(f"未知のレイヤータイプです: {layer.type}")

    return CoverComposition(
        layout=layout,
        base_illustration_id=illustration.id,
        base_asset=illustration.asset or "",
        source_width_px=source_width,
        source_height_px=source_height,
        draw_width_pt=draw_width,
        draw_height_pt=draw_height,
        page_width_pt=page_width_pt,
        page_height_pt=page_height_pt,
        layers=placed,
        fonts={ref: str(face.path) for ref, face in resolved_fonts.items()},
        used_text=used_text,
    )


def page_size_from_profile_mm(width_mm: float, height_mm: float) -> tuple[float, float]:
    return width_mm * POINTS_PER_MM, height_mm * POINTS_PER_MM


def load_book_and_cover(
    package_root: str | Path,
) -> tuple[Path, BookPackage, CoverLayout | None]:
    root = Path(package_root).resolve()
    book = load_book_package(root / "book.yaml")
    layout = load_package_cover(root)
    return root, book, layout


def layer_box_within_safe_area(
    layer_box: dict[str, float], safe: dict[str, float], *, epsilon: float = 1e-6
) -> bool:
    """True when layer_box is fully inside safe (normalized coords)."""

    return (
        layer_box["x"] + epsilon >= safe["x"]
        and layer_box["y"] + epsilon >= safe["y"]
        and layer_box["x"] + layer_box["w"] <= safe["x"] + safe["w"] + epsilon
        and layer_box["y"] + layer_box["h"] <= safe["y"] + safe["h"] + epsilon
    )


def required_layers_safe(
    composition: CoverComposition,
) -> list[tuple[str, str]]:
    """Return ``(layer_id, message)`` for required layers that leave finish/safe areas."""

    problems: list[tuple[str, str]] = []
    safe_areas = {
        name: {"x": box.x, "y": box.y, "w": box.w, "h": box.h}
        for name, box in composition.layout.safe_areas.items()
    }
    for layer in composition.layers:
        if layer.skipped or not layer.required:
            continue
        box = layer.box
        if (
            box["x"] < -1e-9
            or box["y"] < -1e-9
            or box["x"] + box["w"] > 1.0 + 1e-9
            or box["y"] + box["h"] > 1.0 + 1e-9
        ):
            problems.append((layer.id, "仕上がり領域（0–1）をはみ出しています"))
            continue
        if layer.id in safe_areas and not layer_box_within_safe_area(box, safe_areas[layer.id]):
            problems.append(
                (layer.id, f"safe_areas.{layer.id} の外に配置されています")
            )
    return problems
