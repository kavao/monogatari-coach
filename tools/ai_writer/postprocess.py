"""生成出力の後処理（Phase 1）。切り落とした範囲と理由を残し、原文の意味と位置の対応を失わない。

Phase 0 で観測した余計な出力（作品タグ・自己評価・解説・別の話・英語の分析・中国語訳など）を、
本文の後ろに続く「区切り」で見つけて切る。どこまで切るかは操作ごとの方針（``CleanPolicy``）で決める。

- ``expand_insertion``: 挿入は 1〜3 文なので、最初の段落だけを採る（Expand 比較で確定）。
- ``continue`` / ``directed_continue``: 区切り以降を切る。``***`` は場面転換として本文に使われうるが、
  通常執筆の 1 回の生成では場面の終わりとして切る。
- 探索（別計画 ``20261009_ai_writer_creative_exploration.md`` §6.3）では複数段落が正当で、
  ``***`` の扱いも目的で変わるため、``scene_break="review"`` で切らずにレビュー対象として残せる。

範囲は生出力（``raw``）の文字位置（Python の str の添字＝NFC 前のコードポイント）で記録する。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

POSTPROCESS_VERSION = "pp-1"

# 行頭に来たら、そこから後ろは本文ではないとみなす区切り（Phase 0 の観測から）
_META_MARKERS: tuple[tuple[str, str], ...] = (
    (r"-{3,}\s*$", "区切り線 ---"),
    (r"【(?:解説|中文翻译|翻訳)】", "解説・翻訳の見出し"),
    (r"\[", "角括弧の注記（作品タグ・自己評価など）"),
    (r"書き手の意図", "書き手の意図"),
    (r"解説[:：]", "解説"),
)
_SCENE_BREAK = r"\*{3,}\s*$"
_SENTENCE_END = "。！？」』…"

Reason = Literal["leading_space", "trailer", "scene_break", "expand_first_paragraph", "partial_tail", "trailing_space"]


@dataclass(frozen=True)
class Removal:
    start: int
    end: int
    reason: Reason
    detail: str = ""


@dataclass(frozen=True)
class CleanPolicy:
    first_paragraph_only: bool = False
    scene_break: Literal["cut", "review"] = "cut"
    trim_partial_tail: bool = True


POLICIES: dict[str, CleanPolicy] = {
    "continue": CleanPolicy(),
    "directed_continue": CleanPolicy(),
    "expand_insertion": CleanPolicy(first_paragraph_only=True),
    # 探索では複数段落が正当。*** は場面転換として使われうるので切らずにレビューへ回す（探索計画 §6.3）
    "explore_branch": CleanPolicy(scene_break="review"),
}


@dataclass
class CleanResult:
    text: str
    removals: list[Removal] = field(default_factory=list)
    review: list[Removal] = field(default_factory=list)
    """切らずに人の確認へ回した箇所（``scene_break="review"`` のときの ``***`` など）。"""
    flags: list[str] = field(default_factory=list)
    version: str = POSTPROCESS_VERSION

    @property
    def removed_chars(self) -> int:
        return sum(r.end - r.start for r in self.removals if r.reason not in ("leading_space", "trailing_space"))


def _line_starts(text: str) -> list[int]:
    return [0] + [m.end() for m in re.finditer(r"\n", text)]


def _first_marker(raw: str, begin: int, patterns: tuple[tuple[str, str], ...]) -> tuple[int, str] | None:
    for start in _line_starts(raw):
        if start < begin:
            continue
        nl = raw.find("\n", start)
        line = raw[start: nl if nl != -1 else len(raw)].lstrip(" \t　")
        for pattern, label in patterns:
            if re.match(pattern, line):
                return start, label
    return None


def clean(raw: str, policy: CleanPolicy) -> CleanResult:
    """``raw`` から本文を取り出す。``removals`` は ``raw`` 上の範囲で、重ならず昇順。"""
    removals: list[Removal] = []
    review: list[Removal] = []
    start = len(raw) - len(raw.lstrip("\n \t"))
    if start:
        removals.append(Removal(0, start, "leading_space"))
    end = len(raw)

    markers = _META_MARKERS + (((_SCENE_BREAK, "場面転換 ***"),) if policy.scene_break == "cut" else ())
    hit = _first_marker(raw, start, markers)
    if hit:
        pos, label = hit
        removals.append(Removal(pos, end, "scene_break" if label.startswith("場面転換") else "trailer", label))
        end = pos
    if policy.scene_break == "review":
        for m in re.finditer(r"(?m)^[ \t　]*\*{3,}[ \t]*$", raw[start:end]):
            review.append(Removal(start + m.start(), start + m.end(), "scene_break", "場面転換 ***（要確認）"))

    if policy.first_paragraph_only:
        nl = raw.find("\n", start, end)
        if nl != -1 and raw[nl:end].strip():
            removals.append(Removal(nl, end, "expand_first_paragraph", "2 段落目以降"))
            end = nl

    # 空白だけの応答では先頭の除去が全体を覆うので、末尾の除去を開始位置より前へ戻さない（範囲を重ねない）
    body_end = max(start, len(raw[:end].rstrip()))
    if body_end < end:
        removals.append(Removal(body_end, end, "trailing_space"))
        end = body_end

    if policy.trim_partial_tail and end > start and raw[end - 1] not in _SENTENCE_END:
        cut = max(raw.rfind(c, start, end) for c in _SENTENCE_END)
        if cut >= start:
            removals.append(Removal(cut + 1, end, "partial_tail", "途中で切れた末尾の文"))
            end = cut + 1

    text = raw[start:end]
    flags = []
    if "**" in text:
        flags.append("markdown_bold")
    if "　　" in text:
        flags.append("fullwidth_space_break")  # GLM-4.6 の completions で段落区切りが全角空白 2 つになる
    removals.sort(key=lambda r: r.start)
    return CleanResult(text=text, removals=_check_disjoint(removals), review=review, flags=flags)


def _check_disjoint(removals: list[Removal]) -> list[Removal]:
    """切り落とした範囲が重ならないことを確かめる。"""
    for a, b in zip(removals, removals[1:]):
        if a.end > b.start:
            raise AssertionError(f"切り落とし範囲が重なる: {a} {b}")
    return removals


def clean_for(operation: str, raw: str) -> CleanResult:
    if operation not in POLICIES:
        raise KeyError(f"後処理の方針がない操作: {operation}")
    return clean(raw, POLICIES[operation])
