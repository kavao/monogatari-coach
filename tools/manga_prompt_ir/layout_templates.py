"""コマ割りの型ライブラリ（data/panel_layout_templates.yaml）と、型からの layout_geometry 生成。

型の slots は読み順（右上から左下）に並ぶ。panels[] の k 番目のコマは slots の k 番目に入るので、
読み順を守る限りコマと枠を入れ替える余地はない。重いコマを大きい枠に置く調整は「型の選び方」で行う:

1. 必須: 最も重いコマの枠が、ほかのどのコマの枠より小さくない型だけを残す（見せゴマが最大）。
   満たす型が無いときは ``mismatch=True`` で当てはまり度が最良の型を返す（CLI は既定で書き込まない）。
2. 重みと面積の逆転（重いコマの枠が軽いコマの枠より小さい組）の数が最少の型に絞る。
3. 直前のページと同じ型を除き（候補がそれしか無いときは残す）、2ページ前と同じ型は重みを半分にする。
4. 型の ``weight`` に ``suits``（向く拍子）とページの beat_type の一致数を掛け、シード固定で抽選する。

当てはまり度（fit）は、重みと面積の内積を最良の並びでの内積で割った値（0〜1）で、表示用。
型を当てるときは、矩形と一緒に manga.panel_layout と各コマの composition.layout / layout_en も
型の文章に書き換える（文章と矩形の食い違いを残さない）。
"""

from __future__ import annotations

import copy
import hashlib
import random
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Sequence

import yaml

from .beat_type import load_beat_type_vocab
from .schemas.manga_page import GeometryRect, _rectangles_overlap

_TEMPLATES_PATH = Path(__file__).resolve().parent / "data" / "panel_layout_templates.yaml"
_SIZE_CLASSES = {"splash", "large", "medium", "small", "inset"}
AREA_EPSILON = 0.01
DEFAULT_PANEL_WEIGHT = 2


class LayoutTemplateError(ValueError):
    """型ライブラリの不整合、または型を選べないページ。"""


@dataclass(frozen=True)
class LayoutSlot:
    rect: GeometryRect
    size_class: str
    layout_ja: str
    layout_en: str

    @property
    def area(self) -> float:
        return self.rect.w * self.rect.h


@dataclass(frozen=True)
class LayoutTemplate:
    template_id: str
    label_ja: str
    panel_layout_ja: str
    panel_count: int
    weight: float
    suits: tuple[str, ...]
    gutter: float
    bleed: bool
    slots: tuple[LayoutSlot, ...]


@dataclass(frozen=True)
class LayoutChoice:
    template: LayoutTemplate
    fit: float
    panel_weights: tuple[float, ...]
    candidates: tuple[str, ...]
    inversions: int
    mismatch: bool

    def layout_geometry(self, panel_ids: Sequence[int]) -> dict[str, Any]:
        return {
            "panels": [
                {"panel_id": int(panel_id), "rect": dict(slot.rect.model_dump())}
                for panel_id, slot in zip(panel_ids, self.template.slots)
            ]
        }


def _parse_template(raw: dict[str, Any], beat_ids: set[str]) -> LayoutTemplate:
    template_id = str(raw.get("template_id") or "").strip()
    if not template_id:
        raise LayoutTemplateError("template_id が空の型があります")
    slots: list[LayoutSlot] = []
    for index, slot in enumerate(raw.get("slots") or [], start=1):
        try:
            rect = GeometryRect.model_validate(slot.get("rect") or {})
        except ValueError as exc:
            raise LayoutTemplateError(f"{template_id}: slot {index} の矩形が不正です: {exc}") from exc
        size_class = str(slot.get("size_class") or "")
        if size_class not in _SIZE_CLASSES:
            raise LayoutTemplateError(f"{template_id}: slot {index} の size_class が不正です: {size_class!r}")
        layout_ja = str(slot.get("layout_ja") or "").strip()
        layout_en = str(slot.get("layout_en") or "").strip()
        if not layout_ja or not layout_en:
            raise LayoutTemplateError(f"{template_id}: slot {index} に layout_ja / layout_en がありません")
        slots.append(LayoutSlot(rect=rect, size_class=size_class, layout_ja=layout_ja, layout_en=layout_en))
    panel_count = int(raw.get("panel_count") or 0)
    if panel_count != len(slots) or panel_count < 1:
        raise LayoutTemplateError(
            f"{template_id}: panel_count={panel_count} と slots の数 {len(slots)} が一致しません"
        )
    for i, left in enumerate(slots):
        for right in slots[i + 1 :]:
            if _rectangles_overlap(left.rect, right.rect):
                raise LayoutTemplateError(f"{template_id}: 枠が重なっています")
    suits = tuple(str(item) for item in raw.get("suits") or [])
    unknown = sorted(set(suits) - beat_ids)
    if unknown:
        raise LayoutTemplateError(f"{template_id}: suits に beat_type の語彙外があります: {unknown}")
    panel_layout_ja = str(raw.get("panel_layout_ja") or "").strip()
    if not panel_layout_ja:
        raise LayoutTemplateError(f"{template_id}: panel_layout_ja がありません")
    weight = float(raw.get("weight", 1.0))
    if weight <= 0:
        raise LayoutTemplateError(f"{template_id}: weight は正の数にしてください")
    return LayoutTemplate(
        template_id=template_id,
        label_ja=str(raw.get("label_ja") or ""),
        panel_layout_ja=panel_layout_ja,
        panel_count=panel_count,
        weight=weight,
        suits=suits,
        gutter=float(raw.get("gutter", 0.0)),
        bleed=bool(raw.get("bleed", False)),
        slots=tuple(slots),
    )


@lru_cache(maxsize=1)
def load_layout_templates() -> dict[str, LayoutTemplate]:
    """型を読み込み、自己検証して template_id → 型を返す。"""
    data = yaml.safe_load(_TEMPLATES_PATH.read_text(encoding="utf-8")) or {}
    beat_ids = set(load_beat_type_vocab())
    templates: dict[str, LayoutTemplate] = {}
    for raw in data.get("templates") or []:
        template = _parse_template(raw, beat_ids)
        if template.template_id in templates:
            raise LayoutTemplateError(f"template_id が重複しています: {template.template_id}")
        templates[template.template_id] = template
    return templates


def panel_weights(panels: Sequence[Any]) -> tuple[float, ...]:
    """コマの重み。weight があればそれ、無ければ beat_type の既定、どちらも無ければ 2。"""
    vocab = load_beat_type_vocab()
    weights: list[float] = []
    for panel in panels:
        weight = _get(panel, "weight")
        if weight is None:
            beat = _get(panel, "beat_type")
            weight = (vocab.get(str(beat)) or {}).get("default_weight") if beat else None
        weights.append(float(weight if weight is not None else DEFAULT_PANEL_WEIGHT))
    return tuple(weights)


def template_fit(template: LayoutTemplate, weights: Sequence[float]) -> float:
    """重みと面積の並びの当てはまり度（1.0 が最良）。"""
    areas = [slot.area for slot in template.slots]
    actual = sum(w * a for w, a in zip(weights, areas))
    best = sum(w * a for w, a in zip(sorted(weights), sorted(areas)))
    return 1.0 if best <= 0 else actual / best


def heaviest_is_largest(template: LayoutTemplate, weights: Sequence[float]) -> bool:
    """最も重いコマの枠が、ほかのどのコマの枠より小さくないか（全コマ同じ重みなら常に真）。"""
    top = max(weights)
    areas = [slot.area for slot in template.slots]
    heavy = [a for w, a in zip(weights, areas) if w == top]
    light = [a for w, a in zip(weights, areas) if w != top]
    return not light or min(heavy) >= max(light) - AREA_EPSILON


def weight_area_inversions(template: LayoutTemplate, weights: Sequence[float]) -> int:
    """重いコマの枠が軽いコマの枠より小さい組の数。"""
    areas = [slot.area for slot in template.slots]
    count = 0
    for i in range(len(weights)):
        for j in range(len(weights)):
            if weights[i] > weights[j] and areas[i] < areas[j] - AREA_EPSILON:
                count += 1
    return count


def choose_layout_template(
    panels: Sequence[Any],
    *,
    previous_template_ids: Sequence[str] = (),
    seed: str | int = 0,
) -> LayoutChoice:
    """ページのコマから型を1つ選ぶ。同じ入力とシードなら同じ型を返す。"""
    count = len(panels)
    templates = [t for t in load_layout_templates().values() if t.panel_count == count]
    if not templates:
        raise LayoutTemplateError(f"{count}コマの型がありません（型は1〜5コマ）")
    weights = panel_weights(panels)
    fits = {t.template_id: template_fit(t, weights) for t in templates}
    inversions = {t.template_id: weight_area_inversions(t, weights) for t in templates}
    ok = [t for t in templates if heaviest_is_largest(t, weights)]
    mismatch = not ok
    if mismatch:
        best_fit = max(fits.values())
        candidates = [t for t in templates if fits[t.template_id] == best_fit]
    else:
        fewest = min(inversions[t.template_id] for t in ok)
        candidates = [t for t in ok if inversions[t.template_id] == fewest]

    # 並びは「…, 2ページ前, 直前」。型の無いページは空文字で位置を保つ。
    previous = [str(item or "") for item in previous_template_ids]
    last = previous[-1] if previous else ""
    before_last = previous[-2] if len(previous) >= 2 else ""
    if last and any(t.template_id != last for t in candidates):
        candidates = [t for t in candidates if t.template_id != last]

    beats = [str(b) for b in (_get(panel, "beat_type") for panel in panels) if b]
    scored: list[tuple[LayoutTemplate, float]] = []
    for template in candidates:
        score = template.weight * (1 + sum(1 for beat in beats if beat in template.suits))
        if before_last and template.template_id == before_last:
            score *= 0.5
        scored.append((template, score))

    digest = hashlib.sha256(f"{seed}|{count}|{','.join(previous)}".encode("utf-8")).hexdigest()
    rng = random.Random(int(digest[:16], 16))
    total = sum(score for _t, score in scored)
    pick = rng.uniform(0, total)
    chosen = scored[-1][0]
    for template, score in scored:
        pick -= score
        if pick <= 0:
            chosen = template
            break
    return LayoutChoice(
        template=chosen,
        fit=fits[chosen.template_id],
        panel_weights=weights,
        candidates=tuple(t.template_id for t, _score in scored),
        inversions=inversions[chosen.template_id],
        mismatch=mismatch,
    )


def apply_layout_choice(page: dict[str, Any], choice: LayoutChoice) -> dict[str, Any]:
    """型の矩形・型 ID と、コマ割りの文章（panel_layout / composition.layout / layout_en）を当てた新しいページを返す。"""
    new_page = copy.deepcopy(page)
    panels = [panel for panel in new_page.get("panels") or [] if isinstance(panel, dict)]
    if len(panels) != choice.template.panel_count:
        raise LayoutTemplateError(
            f"{choice.template.template_id} は{choice.template.panel_count}コマの型ですが、ページは{len(panels)}コマです"
        )
    manga = new_page.setdefault("manga", {})
    manga["layout_template_id"] = choice.template.template_id
    manga["panel_layout"] = choice.template.panel_layout_ja
    for panel, slot in zip(panels, choice.template.slots):
        composition = panel.get("composition")
        if not isinstance(composition, dict):
            composition = {}
            panel["composition"] = composition
        composition["layout"] = slot.layout_ja
        composition["layout_en"] = slot.layout_en
    new_page["layout_geometry"] = choice.layout_geometry([int(panel["panel_id"]) for panel in panels])
    return new_page


def _get(obj: Any, key: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)
