"""フキダシの配置の下書きを計算する（純粋な層）。

作品やページ YAML を知らない。入力はコマの枠（ピクセル）と、台詞ごとの種類・文字数・文字の大きさ。
出力はフキダシの枠・文字の範囲・しっぽ（ピクセル）。正規化と .bubbles.yaml への書き出しはつなぎの層が行う。

置き方（下書き。仕上げは編集ソフトで動かす前提）:
- 各コマの枠の上側に、右から左へ並べる（日本の漫画の読み順）。入りきらなければ下の段へ
- 大きさは縦書きで収まるように決める（1列の高さはコマの高さの 50% まで。超える分は列を増やす）
- それでもコマに入りきらないときは、文字の大きさを 85% ずつ 50% まで下げて詰め直す
- しっぽはコマの中央やや下へ向ける（話者の位置は分からないため）
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence

Box = tuple[int, int, int, int]

# 文字の範囲がフキダシの何割か（楕円 75%・四角 84%）。写植（novel_manga_assemble_psd.text_box）も同じ比を使う
TEXT_RATIO = {"speech": 0.75, "thought": 0.75, "narration": 0.84, "sfx": 1.0}
FRAME_FROM_TEXT = {kind: 1 / ratio for kind, ratio in TEXT_RATIO.items()}
WITH_TAIL = {"speech", "thought"}
# 1列の高さの上限（コマの高さに対する比）
COLUMN_LIMIT = 0.50


@dataclass(frozen=True)
class DraftText:
    text_id: str
    bubble_type: str  # speech / thought / narration / sfx
    chars: int
    font_px: float


@dataclass
class DraftBubble:
    text_id: str
    bubble_type: str
    frame: Box
    text: Box
    tail: list[tuple[int, int]] | None = None
    allow_overlap: bool = False


@dataclass
class PanelDraft:
    bubbles: list[DraftBubble] = field(default_factory=list)
    scale: float = 1.0
    fitted: bool = True


def _text_size(item: DraftText, scale: float, column_limit: float) -> tuple[float, float]:
    font = item.font_px * scale
    chars = max(1, item.chars)
    per_column = max(1, math.floor(column_limit / (font * 1.05)))
    columns = math.ceil(chars / per_column)
    rows = min(chars, per_column)
    return columns * font * 1.25 + font * 0.3, rows * font * 1.05 + font * 0.3


def _layout(frame: Box, items: Sequence[DraftText], scale: float) -> list[Box] | None:
    left, top, right, bottom = frame
    width, height = right - left, bottom - top
    margin = max(4, round(min(width, height) * 0.04))
    gap = margin
    column_limit = height * COLUMN_LIMIT
    boxes: list[Box] = []
    x_right = right - margin
    y = top + margin
    row_height = 0.0
    row_count = 0
    for item in items:
        text_w, text_h = _text_size(item, scale, column_limit)
        factor = FRAME_FROM_TEXT[item.bubble_type]
        w, h = text_w * factor, text_h * factor
        if w > width - 2 * margin or h > height - 2 * margin:
            return None
        if row_count and x_right - w < left + margin:
            y += row_height + gap
            x_right = right - margin
            row_height = 0.0
            row_count = 0
        if y + h > bottom - margin:
            return None
        boxes.append((round(x_right - w), round(y), round(x_right), round(y + h)))
        x_right -= w + gap
        row_height = max(row_height, h)
        row_count += 1
    return boxes


def _inner_text_box(frame: Box, bubble_type: str) -> Box:
    left, top, right, bottom = frame
    ratio = 1 / FRAME_FROM_TEXT[bubble_type]
    cx, cy = (left + right) / 2, (top + bottom) / 2
    half_w, half_h = (right - left) * ratio / 2, (bottom - top) * ratio / 2
    # 丸めで外へはみ出さないよう、内側へ寄せて丸める
    return (math.ceil(cx - half_w), math.ceil(cy - half_h), math.floor(cx + half_w), math.floor(cy + half_h))


def _tail(frame: Box, panel: Box) -> list[tuple[int, int]]:
    left, top, right, bottom = frame
    p_left, p_top, p_right, p_bottom = panel
    cx = (left + right) / 2
    base_y = bottom - (bottom - top) * 0.15
    half = (right - left) * 0.08
    target_x = (p_left + p_right) / 2
    target_y = p_top + (p_bottom - p_top) * 0.62
    dx, dy = target_x - cx, target_y - base_y
    if dy < (bottom - top) * 0.2:  # フキダシがコマの下寄りのときは真下へ
        dx, dy = 0.0, 1.0
    length = math.hypot(dx, dy) or 1.0
    reach = max((bottom - top) * 0.45, 12)
    tip_x = cx + dx / length * reach
    tip_y = bottom + dy / length * reach * 0.8
    tip_x = min(max(tip_x, p_left + 2), p_right - 2)
    tip_y = min(max(tip_y, p_top + 2), p_bottom - 2)
    return [(round(cx - half), round(base_y)), (round(tip_x), round(tip_y)), (round(cx + half), round(base_y))]


def draft_panel(frame: Box, items: Sequence[DraftText], min_scale: float = 0.5) -> PanelDraft:
    """1コマ分のフキダシを並べる。入りきらなければ文字を小さくして詰め直す。"""
    if not items:
        return PanelDraft()
    scale = 1.0
    boxes = _layout(frame, items, scale)
    while boxes is None and scale * 0.85 >= min_scale:
        scale *= 0.85
        boxes = _layout(frame, items, scale)
    fitted = boxes is not None
    if boxes is None:
        # それでも入らないときは最小の大きさで上から重ねて置き、重なりを許す（編集ソフトで直す前提）
        scale = min_scale
        left, top, right, bottom = frame
        boxes = []
        for index, item in enumerate(items):
            text_w, text_h = _text_size(item, scale, (bottom - top) * COLUMN_LIMIT)
            factor = FRAME_FROM_TEXT[item.bubble_type]
            w = min(text_w * factor, right - left - 8)
            h = min(text_h * factor, bottom - top - 8)
            offset = index * 6
            boxes.append((round(right - 4 - w - offset), round(top + 4 + offset), round(right - 4 - offset), round(top + 4 + offset + h)))
    bubbles = []
    for item, box in zip(items, boxes):
        bubbles.append(
            DraftBubble(
                text_id=item.text_id,
                bubble_type=item.bubble_type,
                frame=box,
                text=_inner_text_box(box, item.bubble_type),
                tail=_tail(box, frame) if item.bubble_type in WITH_TAIL else None,
                allow_overlap=not fitted,
            )
        )
    return PanelDraft(bubbles=bubbles, scale=scale, fitted=fitted)
