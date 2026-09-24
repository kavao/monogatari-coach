"""Local page crop/composite and lettering helpers for P5.

Design geometry from layout_geometry is always tagged ``design_projected``.
Actual balloon or panel rectangles must carry the source image SHA-256 and are
never inferred from the IR.  Hash mismatch refuses reuse.  Composite results
are incomplete unless pixels outside the edited rect are unchanged.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from .schemas.manga_page import MangaPagePrompt
from .text_ids import assigned_text_id


class PageEditError(ValueError):
    """Raised when crop, composite, or lettering cannot finish honestly."""


def sha256_file(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require_matching_source_sha256(record: dict[str, Any], image_path: str | Path) -> str:
    """Refuse geometry that was measured against a different image."""
    path = Path(image_path).expanduser().resolve()
    if not path.is_file():
        raise PageEditError(f"参照画像が見つかりません: {path}")
    actual_sha = sha256_file(path)
    declared = str(record.get("source_sha256") or "").strip().lower()
    if len(declared) != 64:
        raise PageEditError("actual_geometryにsource_sha256がありません")
    if declared != actual_sha:
        raise PageEditError(
            "画像hashが変わったため古いactual_geometryは再利用できません"
        )
    return actual_sha


def _pixel_rect(rect: Any, width: int, height: int) -> tuple[int, int, int, int]:
    left = round(float(rect.x) * width)
    top = round(float(rect.y) * height)
    right = round((float(rect.x) + float(rect.w)) * width)
    bottom = round((float(rect.y) + float(rect.h)) * height)
    if right <= left or bottom <= top:
        raise PageEditError("矩形の幅または高さが0です")
    return left, top, right, bottom


def project_design_geometry(
    page: dict[str, Any],
    *,
    image_size: tuple[int, int],
) -> dict[str, Any]:
    """Map IR layout_geometry onto pixel rects without calling them actual."""
    model = MangaPagePrompt.model_validate(page)
    if model.layout_geometry is None or not model.layout_geometry.panels:
        raise PageEditError("layout_geometry.panelsが必要です")
    width, height = image_size
    if width < 1 or height < 1:
        raise PageEditError("画像サイズが不正です")
    panels = []
    for item in model.layout_geometry.panels:
        left, top, right, bottom = _pixel_rect(item.rect, width, height)
        panels.append(
            {
                "panel_id": item.panel_id,
                "kind": "design_projected",
                "rect_px": [left, top, right, bottom],
            }
        )
    return {
        "kind": "design_projected",
        "image_size": [width, height],
        "panels": panels,
    }


def bind_actual_geometry(
    record: dict[str, Any],
    *,
    image_path: str | Path,
    page: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Accept only actual rects that still match the source image hash."""
    path = Path(image_path).expanduser().resolve()
    if not path.is_file():
        raise PageEditError(f"参照画像が見つかりません: {path}")
    if record.get("kind") == "design_projected":
        raise PageEditError("design_projectedをactual_geometryとして使えません")
    actual_sha = require_matching_source_sha256(record, path)
    panels = record.get("panels")
    if not isinstance(panels, list) or not panels:
        raise PageEditError("actual_geometry.panelsが空です")
    with Image.open(path) as image:
        width, height = image.size
    bound_panels = []
    for index, item in enumerate(panels, start=1):
        if not isinstance(item, dict):
            raise PageEditError(f"actual_geometry.panels[{index}]がobjectではありません")
        bound_panels.append(
            {
                "panel_id": int(item["panel_id"]),
                "kind": "actual",
                "rect_px": _validate_rect_px(
                    item.get("rect_px"),
                    width,
                    height,
                    label=f"actual_geometry.panels[{index}]",
                ),
            }
        )
    texts = record.get("texts") or []
    if not isinstance(texts, list):
        raise PageEditError("actual_geometry.textsは配列である必要があります")
    bound_texts = []
    seen_text_ids: set[str] = set()
    for index, item in enumerate(texts, start=1):
        if not isinstance(item, dict):
            raise PageEditError(f"actual_geometry.texts[{index}]がobjectではありません")
        text_id = str(item.get("text_id") or "").strip()
        if not text_id:
            raise PageEditError(f"actual_geometry.texts[{index}]にtext_idがありません")
        if text_id in seen_text_ids:
            raise PageEditError(f"actual_geometry.texts の text_id が重複しています: {text_id}")
        seen_text_ids.add(text_id)
        bound_texts.append(
            {
                "text_id": text_id,
                "panel_id": int(item["panel_id"]) if item.get("panel_id") is not None else None,
                "kind": "actual",
                "rect_px": _validate_rect_px(
                    item.get("rect_px"),
                    width,
                    height,
                    label=f"actual_geometry.texts[{index}]",
                ),
            }
        )
    if page is not None:
        _reject_unknown_or_mismatched_texts(page, bound_texts)
    return {
        "kind": "actual",
        "source_sha256": actual_sha,
        "image_path": str(path),
        "image_size": [width, height],
        "panels": bound_panels,
        "texts": bound_texts,
        "reviewer": str(record.get("reviewer") or ""),
        "review_note": str(record.get("review_note") or ""),
    }


def _page_text_index(page: dict[str, Any]) -> dict[str, int]:
    model = MangaPagePrompt.model_validate(page)
    index: dict[str, int] = {}
    for panel in model.panels:
        for kind in ("dialogue", "sfx", "monologue", "narration"):
            items = getattr(panel.text, kind)
            for offset, item in enumerate(items, start=1):
                content = str(getattr(item, "content", item) or "").strip()
                if not content:
                    continue
                text_id = assigned_text_id(
                    item, panel_id=panel.panel_id, kind=kind, index=offset
                )
                index[text_id] = int(panel.panel_id)
    return index


def _reject_unknown_or_mismatched_texts(
    page: dict[str, Any],
    bound_texts: list[dict[str, Any]],
) -> None:
    index = _page_text_index(page)
    for item in bound_texts:
        text_id = str(item["text_id"])
        if text_id not in index:
            raise PageEditError(f"未知の text_id です: {text_id}")
        panel_id = item.get("panel_id")
        if panel_id is not None and int(panel_id) != int(index[text_id]):
            raise PageEditError(
                f"panel_id が一致しません: {text_id} "
                f"geometry={panel_id} page={index[text_id]}"
            )


def _validate_rect_px(
    rect: Any,
    width: int,
    height: int,
    *,
    label: str,
) -> list[int]:
    if not (isinstance(rect, list) and len(rect) == 4):
        raise PageEditError(f"{label}にrect_pxがありません")
    left, top, right, bottom = (int(value) for value in rect)
    if left < 0 or top < 0 or right > width or bottom > height or right <= left or bottom <= top:
        raise PageEditError(f"{label}のrect_pxが画像範囲外です")
    return [left, top, right, bottom]


def _panel_rect(geometry: dict[str, Any], panel_id: int) -> tuple[int, int, int, int]:
    for item in geometry.get("panels") or []:
        if int(item.get("panel_id")) == int(panel_id):
            rect = item["rect_px"]
            return int(rect[0]), int(rect[1]), int(rect[2]), int(rect[3])
    raise PageEditError(f"panel_id={panel_id}の矩形がありません")


def crop_panel(
    image_path: str | Path,
    geometry: dict[str, Any],
    panel_id: int,
    output_path: str | Path,
) -> dict[str, Any]:
    path = Path(image_path).expanduser().resolve()
    left, top, right, bottom = _panel_rect(geometry, panel_id)
    with Image.open(path) as image:
        cropped = image.crop((left, top, right, bottom))
        target = Path(output_path).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        cropped.save(target)
    return {
        "path": str(target),
        "panel_id": int(panel_id),
        "kind": geometry.get("kind"),
        "rect_px": [left, top, right, bottom],
        "sha256": sha256_file(target),
    }


def composite_panel(
    page_image_path: str | Path,
    panel_image_path: str | Path,
    geometry: dict[str, Any],
    panel_id: int,
    output_path: str | Path,
) -> dict[str, Any]:
    page_path = Path(page_image_path).expanduser().resolve()
    panel_path = Path(panel_image_path).expanduser().resolve()
    left, top, right, bottom = _panel_rect(geometry, panel_id)
    with Image.open(page_path) as page:
        original = page.convert("RGB")
        composed = original.copy()
        with Image.open(panel_path) as panel:
            fitted = panel.convert("RGB").resize((right - left, bottom - top))
            composed.paste(fitted, (left, top))
        blanked_original = original.copy()
        blanked_composed = composed.copy()
        blanked_original.paste((0, 0, 0), (left, top, right, bottom))
        blanked_composed.paste((0, 0, 0), (left, top, right, bottom))
        outside_ok = blanked_original.tobytes() == blanked_composed.tobytes()
        target = Path(output_path).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        composed.save(target)
    return {
        "path": str(target),
        "panel_id": int(panel_id),
        "kind": geometry.get("kind"),
        "outside_pixels_unchanged": outside_ok,
        "complete": outside_ok,
        "sha256": sha256_file(target),
    }


# No provider has a confirmed region-edit API in this repository. Local mask
# composite is the supported path. Naming a provider here refuses the send.
_REGION_EDIT_PROVIDERS: frozenset[str] = frozenset()


def refuse_region_edit_provider(provider: str) -> None:
    """Stop before a provider send. Web region selection is not an API."""
    name = str(provider or "").strip().lower()
    if name not in _REGION_EDIT_PROVIDERS:
        raise PageEditError(f"{name or provider} は region_edit に未対応です")


def composite_masked_region(
    page_image_path: str | Path,
    replacement_image_path: str | Path,
    mask_image_path: str | Path,
    output_path: str | Path,
    *,
    source_sha256: str,
) -> dict[str, Any]:
    """Paste replacement pixels where the mask is non-zero.

    The mask and both images must share the page size. Mask value 0 keeps the
    source pixel. Completion requires those kept pixels to match the source
    after the file is written. ``source_sha256`` must match the page file.
    """
    declared = str(source_sha256 or "").strip().lower()
    if len(declared) != 64:
        raise PageEditError("region_editにsource_sha256がありません")
    page_path = Path(page_image_path).expanduser().resolve()
    actual = sha256_file(page_path)
    if declared != actual:
        raise PageEditError("画像hashが変わったため古いregion_editは再利用できません")
    replacement_path = Path(replacement_image_path).expanduser().resolve()
    mask_path = Path(mask_image_path).expanduser().resolve()
    with Image.open(page_path) as page_image, Image.open(replacement_path) as replacement_image, Image.open(mask_path) as mask_image:
        source = page_image.convert("RGB")
        replacement = replacement_image.convert("RGB")
        mask = mask_image.convert("L")
    if replacement.size != source.size or mask.size != source.size:
        raise PageEditError("ページ・差し替え・maskの寸法が一致しません")
    width, height = source.size
    composed = source.copy()
    src_px = source.load()
    rep_px = replacement.load()
    out_px = composed.load()
    assert src_px is not None and rep_px is not None and out_px is not None
    mask_values = mask.tobytes()  # mode "L": one byte per pixel, row-major
    for y in range(height):
        for x in range(width):
            if mask_values[y * width + x] > 0:
                out_px[x, y] = rep_px[x, y]
    target = Path(output_path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    composed.save(target)
    with Image.open(target) as saved_image:
        saved = saved_image.convert("RGB")
    if saved.size != source.size:
        raise PageEditError("書き出した画像の寸法が元ページと一致しません")
    saved_px = saved.load()
    assert saved_px is not None
    outside_ok = True
    changed = 0
    for y in range(height):
        for x in range(width):
            if mask_values[y * width + x] == 0:
                if saved_px[x, y] != src_px[x, y]:
                    outside_ok = False
            elif saved_px[x, y] != src_px[x, y]:
                changed += 1
    return {
        "path": str(target),
        "kind": "region_edit",
        "source_sha256": actual,
        "changed_pixels": changed,
        "outside_pixels_unchanged": outside_ok,
        "complete": outside_ok,
        "sha256": sha256_file(target),
    }


def _load_font(font_path: str | Path | None, size: int) -> ImageFont.FreeTypeFont:
    if font_path is None:
        raise PageEditError("写植フォントが指定されていません")
    path = Path(font_path).expanduser().resolve()
    if not path.is_file():
        raise PageEditError(f"写植フォントが見つかりません: {path}")
    try:
        return ImageFont.truetype(str(path), size=size)
    except OSError as exc:
        raise PageEditError(f"写植フォントを開けません: {path}") from exc


def _collect_page_text(model: MangaPagePrompt) -> list[tuple[str, str, str]]:
    items: list[tuple[str, str, str]] = []
    default_direction = model.manga.lettering.direction
    for panel in model.panels:
        for kind in ("dialogue", "sfx", "monologue", "narration"):
            for index, item in enumerate(getattr(panel.text, kind), start=1):
                content = str(getattr(item, "content", item) or "").strip()
                if not content:
                    continue
                direction = getattr(item, "writing_direction", None) or default_direction
                items.append(
                    (
                        assigned_text_id(
                            item, panel_id=panel.panel_id, kind=kind, index=index
                        ),
                        content,
                        direction,
                    )
                )
    return items


_LINE_GAP = 4
_RECT_PAD = 6

# Pillow の通常描画は OpenType の縦組み機能を自動適用しないため、
# 縦書きで向き・位置が変わる約物は Unicode の縦組み用字形へ変換する。
# IR の content は変更せず、ローカル写植時の描画文字列だけに適用する。
_VERTICAL_PRESENTATION_TRANSLATION = str.maketrans(
    {
        "、": "︑",
        "。": "︒",
        "，": "︐",
        "．": "︒",
        "：": "︓",
        "；": "︔",
        "！": "︕",
        "…": "︙",
        "‥": "︰",
        "―": "︱",
        "—": "︱",
        "–": "︱",
        "（": "︵",
        "）": "︶",
        "(": "︵",
        ")": "︶",
        "｛": "︷",
        "｝": "︸",
        "{": "︷",
        "}": "︸",
        "〔": "︹",
        "〕": "︺",
        "【": "︻",
        "】": "︼",
        "〈": "︿",
        "〉": "﹀",
        "《": "︽",
        "》": "︾",
        "「": "﹁",
        "」": "﹂",
        "『": "﹃",
        "』": "﹄",
        "［": "﹇",
        "］": "﹈",
        "[": "﹇",
        "]": "﹈",
    }
)


def _verticalize_text(content: str) -> str:
    """Return the drawing form for Japanese vertical writing."""
    return str(content).translate(_VERTICAL_PRESENTATION_TRANSLATION)


def _line_ink(draw: ImageDraw.ImageDraw, line: str, font: ImageFont.FreeTypeFont) -> tuple[int, int, int, int]:
    """Glyph bounds at the draw origin. Top bearing is included so height matches the pixels."""
    x0, y0, x1, y1 = draw.textbbox((0, 0), line, font=font)
    return int(x0), int(y0), int(x1), int(y1)


def _block_metrics(
    draw: ImageDraw.ImageDraw,
    lines: list[str],
    font: ImageFont.FreeTypeFont,
) -> tuple[int, int]:
    width_used = 0
    heights: list[int] = []
    for line in lines:
        x0, y0, x1, y1 = _line_ink(draw, line, font)
        width_used = max(width_used, x1 - x0)
        heights.append(y1 - y0)
    total_h = sum(heights) + max(0, len(lines) - 1) * _LINE_GAP
    return width_used, total_h


def _vertical_layout(
    draw: ImageDraw.ImageDraw,
    content: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
    max_height: int,
) -> tuple[list[str], int, int] | None:
    """Return right-to-left columns for Japanese vertical writing."""
    chars = [
        char
        for char in _verticalize_text(content).replace("\n", "")
        if char != "\r"
    ]
    if not chars:
        chars = [""]
    glyph_sizes = []
    for char in chars:
        x0, y0, x1, y1 = _line_ink(draw, char, font)
        glyph_sizes.append((max(1, x1 - x0), max(1, y1 - y0)))
    cell_width = max(width for width, _height in glyph_sizes)
    cell_height = max(height for _width, height in glyph_sizes)
    rows = max(1, (max_height + _LINE_GAP) // (cell_height + _LINE_GAP))
    columns = (len(chars) + rows - 1) // rows
    used_width = columns * cell_width + max(0, columns - 1) * _LINE_GAP
    used_height = min(rows, len(chars)) * cell_height + max(0, min(rows, len(chars)) - 1) * _LINE_GAP
    if used_width > max_width or used_height > max_height:
        return None
    return ["".join(chars[index : index + rows]) for index in range(0, len(chars), rows)], used_width, used_height


def _layout_metrics(
    draw: ImageDraw.ImageDraw,
    lines: list[str],
    font: ImageFont.FreeTypeFont,
    direction: str,
) -> tuple[int, int]:
    if direction == "vertical":
        glyph_sizes = []
        for column in lines:
            for char in column:
                x0, y0, x1, y1 = _line_ink(draw, char, font)
                glyph_sizes.append((max(1, x1 - x0), max(1, y1 - y0)))
        if not glyph_sizes:
            return 1, 1
        cell_width = max(width for width, _height in glyph_sizes)
        cell_height = max(height for _width, height in glyph_sizes)
        max_rows = max(len(column) for column in lines)
        return (
            len(lines) * cell_width + max(0, len(lines) - 1) * _LINE_GAP,
            max_rows * cell_height + max(0, max_rows - 1) * _LINE_GAP,
        )
    return _block_metrics(draw, lines, font)


def _fit_text(
    draw: ImageDraw.ImageDraw,
    content: str,
    rect: tuple[int, int, int, int],
    font_path: Path,
    *,
    max_size: int,
    size_ratio: float = 1.0,
    direction: str = "horizontal",
) -> tuple[ImageFont.FreeTypeFont, list[str], tuple[int, int, int, int]] | None:
    left, top, right, bottom = rect
    max_width = max(1, right - left - _RECT_PAD * 2)
    max_height = max(1, bottom - top - _RECT_PAD * 2)
    for size in range(max_size, 11, -1):
        font = _load_font(font_path, size)
        if direction == "vertical":
            vertical = _vertical_layout(draw, content, font, max_width, max_height)
            if vertical is None:
                continue
            lines, width_used, total_h = vertical
        else:
            lines = _wrap_lines(draw, content, font, max_width)
            width_used, total_h = _block_metrics(draw, lines, font)
        if width_used <= max_width and total_h <= max_height:
            draw_size = max(12, int(round(size * size_ratio)))
            if draw_size != size:
                font = _load_font(font_path, draw_size)
                width_used, total_h = _layout_metrics(draw, lines, font, direction)
            return font, lines, (left + _RECT_PAD, top + _RECT_PAD, left + _RECT_PAD + width_used, top + _RECT_PAD + total_h)
    return None


def _wrap_lines(
    draw: ImageDraw.ImageDraw,
    content: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
) -> list[str]:
    text = str(content).replace("\n", "")
    if not text:
        return [""]
    lines: list[str] = []
    current = ""
    for char in text:
        trial = current + char
        box = draw.textbbox((0, 0), trial, font=font)
        if current and (box[2] - box[0]) > max_width:
            lines.append(current)
            current = char
        else:
            current = trial
    if current:
        lines.append(current)
    return lines


def _draw_vertical_layout(
    canvas: Image.Image,
    rect: tuple[int, int, int, int],
    lines: list[str],
    font: ImageFont.FreeTypeFont,
    used_w: int,
    used_h: int,
    vertical_scale: float,
) -> tuple[int, int]:
    """Draw columns from right to left and return the placed origin."""
    layer = Image.new("L", (max(1, used_w), max(1, used_h)), 0)
    layer_draw = ImageDraw.Draw(layer)
    glyph_sizes = []
    for column in lines:
        for char in column:
            x0, y0, x1, y1 = _line_ink(layer_draw, char, font)
            glyph_sizes.append((max(1, x1 - x0), max(1, y1 - y0)))
    cell_width = max(width for width, _height in glyph_sizes)
    cell_height = max(height for _width, height in glyph_sizes)
    for column_index, column in enumerate(lines):
        x_cell = used_w - cell_width - column_index * (cell_width + _LINE_GAP)
        for row_index, char in enumerate(column):
            x0, y0, x1, y1 = _line_ink(layer_draw, char, font)
            glyph_width = x1 - x0
            glyph_height = y1 - y0
            x = x_cell + (cell_width - glyph_width) // 2 - x0
            y = row_index * (cell_height + _LINE_GAP) + (cell_height - glyph_height) // 2 - y0
            layer_draw.text((x, y), char, fill=255, font=font)
    scaled_h = max(1, int(round(used_h * vertical_scale)))
    if scaled_h != used_h:
        layer = layer.resize((used_w, scaled_h), Image.Resampling.LANCZOS)
    start_x = rect[0] + (rect[2] - rect[0] - used_w) // 2
    start_y = rect[1] + (rect[3] - rect[1] - scaled_h) // 2
    ink = Image.new("RGB", (used_w, scaled_h), (0, 0, 0))
    canvas.paste(ink, (start_x, start_y), layer)
    return start_x, start_y


def letter_page(
    page: dict[str, Any],
    image_path: str | Path,
    output_path: str | Path,
    *,
    font_path: str | Path,
    geometry: dict[str, Any],
    font_size: int | None = None,
    size_ratio: float = 1.0,
    vertical_scale: float = 1.0,
) -> dict[str, Any]:
    """Draw IR text into known rects. Unplaced or overflowing items stay incomplete.

    size_ratio scales the largest size that fits the rect. 1 keeps that size.
    Line breaks stay those of the full fit, so a smaller ratio does not reflow.
    vertical_scale stretches only the block height after fitting. 1 leaves the glyphs square.
    """
    if geometry.get("kind") != "actual":
        raise PageEditError("design_projectedでは写植できません")
    require_matching_source_sha256(geometry, image_path)
    if not 0 < size_ratio <= 1:
        raise PageEditError("size_ratio は 0 より大きく 1 以下です")
    if vertical_scale <= 0:
        raise PageEditError("vertical_scale は 0 より大きい値です")
    model = MangaPagePrompt.model_validate(page)
    font_size = font_size or model.manga.lettering.base_font_size
    if font_size < 12:
        raise PageEditError("font_size は12以上です")
    path = Path(image_path).expanduser().resolve()
    font_file = Path(font_path).expanduser().resolve()
    _load_font(font_file, font_size)
    with Image.open(path) as image:
        canvas = image.convert("RGB").copy()
    draw = ImageDraw.Draw(canvas)
    placed: list[dict[str, Any]] = []
    unplaced: list[str] = []
    overflow: list[str] = []
    page_texts = _collect_page_text(model)
    actual_texts = {
        str(item.get("text_id")): item
        for item in (geometry.get("texts") or [])
        if isinstance(item, dict) and item.get("text_id")
    }
    for text_id, content, direction in page_texts:
        record = actual_texts.get(text_id)
        if record is None:
            unplaced.append(text_id)
            continue
        rx0, ry0, rx1, ry1 = (int(value) for value in record["rect_px"])
        rect = (rx0, ry0, rx1, ry1)
        fitted = _fit_text(
            draw,
            content,
            rect,
            font_file,
            max_size=font_size,
            size_ratio=size_ratio,
            direction=direction,
        )
        if fitted is None:
            overflow.append(text_id)
            continue
        font, lines, box = fitted
        used_w = box[2] - box[0]
        used_h = box[3] - box[1]
        scaled_h = max(1, int(round(used_h * vertical_scale)))
        if used_w > rect[2] - rect[0] or scaled_h > rect[3] - rect[1]:
            overflow.append(text_id)
            continue
        if direction == "vertical":
            start_x, start_y = _draw_vertical_layout(
                canvas,
                rect,
                lines,
                font,
                used_w,
                used_h,
                vertical_scale,
            )
        elif vertical_scale == 1:
            start_x = rect[0] + max(_RECT_PAD, (rect[2] - rect[0] - used_w) // 2)
            start_y = rect[1] + max(_RECT_PAD, (rect[3] - rect[1] - used_h) // 2)
            cursor_y = start_y
            for line in lines:
                x0, y0, x1, y1 = _line_ink(draw, line, font)
                line_w = x1 - x0
                draw.text(
                    (start_x + max(0, (used_w - line_w) // 2) - x0, cursor_y - y0),
                    line,
                    fill="black",
                    font=font,
                )
                cursor_y += (y1 - y0) + _LINE_GAP
        else:
            layer = Image.new("L", (max(1, used_w), max(1, used_h)), 0)
            layer_draw = ImageDraw.Draw(layer)
            cursor_y = 0
            for line in lines:
                x0, y0, x1, y1 = _line_ink(layer_draw, line, font)
                line_w = x1 - x0
                layer_draw.text(
                    (max(0, (used_w - line_w) // 2) - x0, cursor_y - y0),
                    line,
                    fill=255,
                    font=font,
                )
                cursor_y += (y1 - y0) + _LINE_GAP
            stretched = layer.resize((used_w, scaled_h), Image.Resampling.LANCZOS)
            ink = Image.new("RGBA", (used_w, scaled_h), (0, 0, 0, 255))
            start_x = rect[0] + (rect[2] - rect[0] - used_w) // 2
            start_y = rect[1] + (rect[3] - rect[1] - scaled_h) // 2
            canvas.paste(ink, (start_x, start_y), stretched)
        placed.append(
            {
                "text_id": text_id,
                "font_size": getattr(font, "size", None),
                "writing_direction": direction,
                "rendered_content": (
                    _verticalize_text(content)
                    if direction == "vertical"
                    else content
                ),
                "vertical_scale": vertical_scale,
                "box_px": [start_x, start_y, start_x + used_w, start_y + scaled_h],
                "rect_px": list(rect),
            }
        )

    target = Path(output_path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(target)
    complete = not unplaced and not overflow
    return {
        "path": str(target),
        "sha256": sha256_file(target),
        "placed": placed,
        "unplaced": unplaced,
        "overflow": overflow,
        "complete": complete,
        "kind": geometry.get("kind"),
    }


def write_json(path: str | Path, payload: dict[str, Any]) -> None:
    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
