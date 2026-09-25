from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class NormalizedRect(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x: float
    y: float
    width: float
    height: float

    @model_validator(mode="after")
    def normalized_bounds(self) -> "NormalizedRect":
        values = {"x": self.x, "y": self.y, "width": self.width, "height": self.height}
        if any(not 0.0 <= value <= 1.0 for value in values.values()):
            raise ValueError("吹き出し矩形は 0.0〜1.0 です")
        if self.width <= 0 or self.height <= 0:
            raise ValueError("吹き出し矩形の幅と高さは 0 より大きくしてください")
        if self.x + self.width > 1.0 or self.y + self.height > 1.0:
            raise ValueError("吹き出し矩形がページ範囲を超えています")
        return self

    def right(self) -> float:
        return self.x + self.width

    def bottom(self) -> float:
        return self.y + self.height

    def contains(self, inner: "NormalizedRect") -> bool:
        return (
            inner.x >= self.x
            and inner.y >= self.y
            and inner.right() <= self.right()
            and inner.bottom() <= self.bottom()
        )

    def overlaps(self, other: "NormalizedRect") -> bool:
        return not (
            self.right() <= other.x
            or other.right() <= self.x
            or self.bottom() <= other.y
            or other.bottom() <= self.y
        )


class BubbleTail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    points: list[list[float]] = Field(min_length=3)

    @model_validator(mode="after")
    def normalized_points(self) -> "BubbleTail":
        for index, point in enumerate(self.points, start=1):
            if len(point) != 2:
                raise ValueError(f"tail.points[{index}] は [x, y] です")
            x, y = point
            if not 0.0 <= float(x) <= 1.0 or not 0.0 <= float(y) <= 1.0:
                raise ValueError(f"tail.points[{index}] は 0.0〜1.0 です")
        return self


class DesignBubble(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text_id: str
    panel_id: int
    # ``sfx`` has a text rectangle but no visible balloon. It remains in
    # this document so the later lettering pass uses the same coordinate
    # contract as dialogue, narration, and monologue.
    bubble_type: Literal["speech", "narration", "thought", "sfx"]
    frame_rect: NormalizedRect
    text_rect: NormalizedRect
    tail: BubbleTail | None = None
    allow_overlap: bool = False

    @model_validator(mode="after")
    def text_inside_frame(self) -> "DesignBubble":
        if not self.frame_rect.contains(self.text_rect):
            raise ValueError(f"text_rect が frame_rect の内側にありません: {self.text_id}")
        return self


class BubbleDesignDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["design_projected"]
    coordinate_space: Literal["normalized"]
    bubbles: list[DesignBubble]

    @model_validator(mode="after")
    def unique_and_overlap(self) -> "BubbleDesignDocument":
        seen: set[str] = set()
        for bubble in self.bubbles:
            if bubble.text_id in seen:
                raise ValueError(f"bubbles の text_id が重複しています: {bubble.text_id}")
            seen.add(bubble.text_id)
        for left_index, left in enumerate(self.bubbles):
            for right in self.bubbles[left_index + 1 :]:
                if not left.frame_rect.overlaps(right.frame_rect):
                    continue
                if left.allow_overlap and right.allow_overlap:
                    continue
                raise ValueError(
                    "吹き出し枠が重なっています。"
                    f"明示の allow_overlap が両方に必要です: {left.text_id}/{right.text_id}"
                )
        return self
