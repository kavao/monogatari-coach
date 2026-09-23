"""Render a geometry-only manga name image without changing the page IR.

The output is deliberately a derived asset.  Panel order comes from
``layout_geometry.panels`` (which is schema-validated against ``panels``), and
no reading order is inferred from coordinates.  The numbered proof is for
people; the unnumbered PNG is the model reference input.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from .schemas.manga_page import MangaPagePrompt


class NameRenderError(ValueError):
    """Raised when a page has no valid rectangular name geometry."""


def render_name_image(
    page: dict[str, Any],
    output_path: str | Path,
    *,
    numbered: bool = False,
    canvas_size: tuple[int, int] = (1024, 1536),
) -> dict[str, Any]:
    """Write one derived name PNG and return its redacted manifest record."""
    try:
        model = MangaPagePrompt.model_validate(page)
    except ValueError as exc:
        raise NameRenderError(f"ネーム画像のページ検証に失敗しました: {exc}") from exc
    if model.layout_geometry is None or not model.layout_geometry.panels:
        raise NameRenderError("ネーム画像にはlayout_geometry.panelsが必要です")
    if canvas_size[0] < 64 or canvas_size[1] < 64:
        raise NameRenderError("ネーム画像のcanvas_sizeが小さすぎます")

    image = Image.new("RGB", canvas_size, "white")
    draw = ImageDraw.Draw(image)
    width, height = canvas_size
    for index, geometry in enumerate(model.layout_geometry.panels, start=1):
        rect = geometry.rect
        left = round(rect.x * width)
        top = round(rect.y * height)
        right = round((rect.x + rect.w) * width)
        bottom = round((rect.y + rect.h) * height)
        draw.rectangle((left, top, right, bottom), outline="black", width=4)
        if numbered:
            draw.text((left + 8, top + 8), str(geometry.panel_id), fill="black")

    target = Path(output_path).expanduser().resolve()
    if target.suffix.lower() != ".png" or target.name in {".", ".."}:
        raise NameRenderError("ネーム画像の出力先はPNGファイルで指定してください")
    target.parent.mkdir(parents=True, exist_ok=True)
    image.save(target, format="PNG")
    raw = target.read_bytes()
    return {
        "path": str(target),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "dimensions": [width, height],
        "kind": "numbered_name_proof" if numbered else "model_name_input",
        "panel_ids": [item.panel_id for item in model.layout_geometry.panels],
    }


def render_name_assets(
    page: dict[str, Any],
    output_dir: str | Path,
    *,
    prefix: str,
) -> dict[str, dict[str, Any]]:
    """Render the human proof and model input variants side by side."""
    safe_prefix = str(prefix).strip()
    if not safe_prefix or Path(safe_prefix).name != safe_prefix:
        raise NameRenderError("ネーム画像prefixは単純な名前で指定してください")
    directory = Path(output_dir).expanduser().resolve()
    return {
        "numbered": render_name_image(
            page,
            directory / f"{safe_prefix}_name_numbered.png",
            numbered=True,
        ),
        "model": render_name_image(
            page,
            directory / f"{safe_prefix}_name.png",
            numbered=False,
        ),
    }
