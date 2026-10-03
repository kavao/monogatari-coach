"""コマの枠の縦横比から、コマ単体を生成するときのサイズを選ぶ（計画 20260930_manga-panel-assembly-psd の C9）。

枠の比率は、取り込み（novel_manga_assemble_psd.py）と同じ B5 基準で計算する（C2 案a）。
ページ YAML の meta.aspect_ratio（2:3）は使わない。取り込みと生成の基準をそろえるため。

NovelAI のサイズの選び方は2通り（設定で切り替える。未確認の C9 に合わせる）:
- presets: 用意したサイズ（既定は 1024×1024・832×1216・1216×832）から、比率が最も近いものを選ぶ
- pixel_budget: 画素数の上限の中で、比率に合わせて幅・高さを計算する（64 の倍数）

この層は作品やページ YAML を知らない（C10 の純粋な層に置ける）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

B5_MM = (182, 257)

DEFAULT_PRESETS: tuple[tuple[int, int], ...] = ((1024, 1024), (832, 1216), (1216, 832))
# pixel_budget で「ほぼ同じ比率」とみなす差（対数。0.03 ≒ 3%）。この範囲なら画素数の大きいサイズを選ぶ
RATIO_TOLERANCE = 0.03


class FrameAspectError(ValueError):
    """枠や設定からサイズを決められないとき。"""


def frame_ratio(rect: Mapping[str, float], paper_mm: tuple[int, int] = B5_MM) -> float:
    """正規化矩形（0〜1）の、用紙上での横÷縦の比。"""
    w = float(rect["w"])
    h = float(rect["h"])
    if w <= 0 or h <= 0:
        raise FrameAspectError(f"枠の大きさが不正です: {dict(rect)}")
    return (w * paper_mm[0]) / (h * paper_mm[1])


@dataclass(frozen=True)
class NovelAISizePolicy:
    mode: str = "presets"
    presets: tuple[tuple[int, int], ...] = DEFAULT_PRESETS
    max_pixels: int = 1_048_576
    multiple: int = 64
    min_side: int = 512
    max_side: int = 1728

    @classmethod
    def from_config(cls, raw: Mapping[str, Any] | None) -> "NovelAISizePolicy":
        if not raw:
            return cls()
        mode = str(raw.get("mode", "presets"))
        if mode not in {"presets", "pixel_budget"}:
            raise FrameAspectError(f"panel_frame_sizes.mode は presets / pixel_budget のどちらかです: {mode!r}")
        presets_raw = raw.get("presets") or DEFAULT_PRESETS
        presets = tuple((int(w), int(h)) for w, h in presets_raw)
        policy = cls(
            mode=mode,
            presets=presets,
            max_pixels=int(raw.get("max_pixels", 1_048_576)),
            multiple=int(raw.get("multiple", 64)),
            min_side=int(raw.get("min_side", 512)),
            max_side=int(raw.get("max_side", 1728)),
        )
        for w, h in policy.presets:
            if w * h > policy.max_pixels:
                raise FrameAspectError(f"presets の {w}x{h} が画素数の上限 {policy.max_pixels} を超えています")
        return policy


def _log_distance(a: float, b: float) -> float:
    return abs(math.log(a) - math.log(b))


def choose_novelai_size(ratio: float, policy: NovelAISizePolicy) -> tuple[int, int]:
    """枠の比率（横÷縦）に合う NovelAI の幅・高さを返す。"""
    if ratio <= 0:
        raise FrameAspectError(f"比率が不正です: {ratio}")
    if policy.mode == "presets":
        return min(policy.presets, key=lambda size: _log_distance(size[0] / size[1], ratio))
    return _pixel_budget_size(ratio, policy)


def _pixel_budget_size(ratio: float, policy: NovelAISizePolicy) -> tuple[int, int]:
    step = policy.multiple
    lo = max(step, policy.min_side - policy.min_side % step)
    hi = policy.max_side - policy.max_side % step
    # 比率の上限・下限（各辺の最小・最大で決まる）で打ち切る
    max_ratio = hi / lo
    clamped = min(max(ratio, 1 / max_ratio), max_ratio)
    candidates = [
        (width, height)
        for width in range(lo, hi + 1, step)
        for height in range(lo, hi + 1, step)
        if width * height <= policy.max_pixels
    ]
    if not candidates:
        raise FrameAspectError("画素数の上限と各辺の範囲に収まるサイズがありません")
    closest = min(_log_distance(w / h, clamped) for w, h in candidates)
    # 枠の比率から RATIO_TOLERANCE 以内のサイズのうち画素数が最大のもの。
    # 範囲内に候補が無い（細長すぎる）ときは、最も近い比率のものだけを候補にする
    limit = max(closest, RATIO_TOLERANCE)
    near = [(w, h) for w, h in candidates if _log_distance(w / h, clamped) <= limit]
    return max(near, key=lambda size: (size[0] * size[1], -_log_distance(size[0] / size[1], clamped)))


def frame_sizes_for_page(
    geometry_panels: Sequence[Mapping[str, Any]],
    panel_ids: Sequence[int],
    policy: NovelAISizePolicy,
    paper_mm: tuple[int, int] = B5_MM,
) -> list[dict[str, Any]]:
    """ページのコマごとに、枠の比率と要求サイズを返す。layout_geometry とコマを panel_id で照合する。"""
    by_id = {int(item["panel_id"]): item for item in geometry_panels}
    missing = [pid for pid in panel_ids if int(pid) not in by_id]
    if missing:
        raise FrameAspectError(f"layout_geometry に無いコマがあります: panel_id={missing}")
    out = []
    for pid in panel_ids:
        ratio = frame_ratio(by_id[int(pid)]["rect"], paper_mm)
        width, height = choose_novelai_size(ratio, policy)
        out.append(
            {
                "panel_id": int(pid),
                "frame_ratio": round(ratio, 4),
                "requested_size": [width, height],
                "requested_ratio": round(width / height, 4),
                "mode": policy.mode,
            }
        )
    return out
