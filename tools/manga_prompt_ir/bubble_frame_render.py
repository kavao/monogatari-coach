"""Draw local speech/narration frames onto a clean PNG.

The renderer is provider-agnostic. Choosing bubble_frame_mode=local at a
compiler entry is a separate gate (NovelAI + page_render_plan).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from manga_prompt_ir.bubble_geometry import (
    BubbleGeometryError,
    project_bubble_design,
)
from manga_prompt_ir.page_edit import sha256_file
from manga_prompt_ir.schemas.manga_page import MangaPagePrompt

FILL = (255, 255, 255)
OUTLINE = (0, 0, 0)
STROKE = 3


def _as_box(rect_px: list[int]) -> tuple[int, int, int, int]:
    left, top, right, bottom = (int(value) for value in rect_px)
    if right <= left or bottom <= top:
        raise BubbleGeometryError("枠矩形の幅または高さが0です")
    return left, top, right, bottom


def _draw_tail(draw: ImageDraw.ImageDraw, points: list[list[int]]) -> None:
    xy = [(int(point[0]), int(point[1])) for point in points]
    if len(xy) < 3:
        raise BubbleGeometryError("tail は3点以上必要です")
    draw.polygon(xy, fill=FILL, outline=OUTLINE)
    for start, end in zip(xy, xy[1:] + xy[:1]):
        draw.line([start, end], fill=OUTLINE, width=STROKE)


def _draw_speech(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int]) -> None:
    draw.ellipse(box, fill=FILL, outline=OUTLINE, width=STROKE)


def _draw_narration(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int]) -> None:
    left, top, right, bottom = box
    radius = max(8, min(right - left, bottom - top) // 8)
    draw.rounded_rectangle(box, radius=radius, fill=FILL, outline=OUTLINE, width=STROKE)


def _draw_thought(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int]) -> None:
    # The optional tail points carry the connection to the character.
    draw.ellipse(box, fill=FILL, outline=OUTLINE, width=STROKE)


def _require_png_path(path: Path, *, role: str) -> None:
    if path.suffix.lower() != ".png":
        raise BubbleGeometryError(f"{role} は PNG に限定します: {path.name}")


def render_local_bubble_frames(
    page: dict[str, Any] | MangaPagePrompt,
    data: dict[str, Any],
    *,
    image_path: str | Path,
    out_path: str | Path,
    source_generation: dict[str, Any],
) -> dict[str, Any]:
    source = Path(image_path).expanduser().resolve()
    destination = Path(out_path).expanduser().resolve()
    _require_png_path(source, role="入力画像")
    _require_png_path(destination, role="出力先")
    if not source.is_file():
        raise BubbleGeometryError(f"入力画像が見つかりません: {source}")
    if destination == source:
        raise BubbleGeometryError("local frame は入力 PNG を上書きしません")

    source_digest = sha256_file(source)
    with Image.open(source) as opened:
        if str(opened.format or "").upper() != "PNG":
            raise BubbleGeometryError(
                f"入力画像は PNG である必要があります: format={opened.format}"
            )
        working = opened.convert("RGB")
    projected = project_bubble_design(
        page,
        data,
        image_size=working.size,
        source_generation=source_generation,
        image_path=source,
    )
    draw = ImageDraw.Draw(working)
    bubbles = projected["bubbles"]
    visible_frame_count = 0
    for bubble in bubbles:
        bubble_type = bubble["bubble_type"]
        # Sound effects use a text rectangle but no visible balloon.  They
        # stay in the projected/actual record for the lettering pass.
        if bubble_type == "sfx":
            continue
        tail = bubble.get("tail_px")
        if tail:
            _draw_tail(draw, tail)
        box = _as_box(bubble["frame_rect_px"])
        if bubble_type == "speech":
            _draw_speech(draw, box)
        elif bubble_type == "narration":
            _draw_narration(draw, box)
        elif bubble_type == "thought":
            _draw_thought(draw, box)
        else:
            raise BubbleGeometryError(f"未対応の bubble_type です: {bubble_type}")
        visible_frame_count += 1

    destination.parent.mkdir(parents=True, exist_ok=True)
    working.save(destination, format="PNG")
    after_source = sha256_file(source)
    if after_source != source_digest:
        raise BubbleGeometryError("入力 PNG が枠描画中に変わりました")
    output_digest = sha256_file(destination)
    if visible_frame_count and output_digest == source_digest:
        raise BubbleGeometryError("枠が描画されていません")
    if len(bubbles) != len(projected["texts"]):
        raise BubbleGeometryError("frame 件数と text 件数が一致しません")
    return {
        "complete": True,
        "bubble_frame_mode": "local",
        "text_mode": "none",
        "bubbles_suppressed": True,
        "path": str(destination),
        "frame_count": visible_frame_count,
        "text_count": len(bubbles),
        "source_sha256": source_digest,
        "output_sha256": output_digest,
        "bubbles": [
            {
                "text_id": item["text_id"],
                "panel_id": item["panel_id"],
                "bubble_type": item["bubble_type"],
                "frame_rect_px": item["frame_rect_px"],
            }
            for item in bubbles
        ],
    }
