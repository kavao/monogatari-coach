"""PromptRenderer（計画書 §4、Phase 1）。操作の入力から Provider への ``GenerationRequest`` を組み立てる。

文面と出力上限は Phase 0 日本語 Benchmark（``bench.py``）と同じにして、測った条件を本実装へそのまま持ち込む。
変えるときは ``RENDERER_VERSION`` を上げ、Benchmark で効果を確かめてからにする
（例: Directed Continue の字数不足への対処は Phase 1 の別項目で比べる）。

- ``continue``: completions に本文だけを渡す（指示なしの素の続き）
- ``directed_continue``: chat に Beat Contract・既知の事実・本文を渡す
- ``expand_insertion``: chat に挿入位置の印を付けた本文を渡し、挟む文だけを書かせる

GLM-4.6 と Xialong は Phase 0 で同じ入力を使って比べた。モデルごとの調整は、共通条件の結果を残したうえで
版を分けて加える（探索機能の計画 §3.3 と同じ方針）。

版の履歴:
- ``nai-r1``: Phase 0 Benchmark と同一。
- ``nai-r2``（2026-10-09）: Directed Continue の指示字数をモデル別の倍率で解決する。GLM-4.6 は 1.5 倍
  （字数不足の比較実験の条件 B: 目標 400 字に対し「約 600 字」と指示し、max_tokens 738）。契約の目標字数は
  書き換えず、達成判定は契約の値で行う。Xialong と Continue / Expand は nai-r1 と同じ要求のまま。
  根拠: ``_workingspace/ai_writer/phase1_length/20261009_024321/findings.md``、``review_codex.md``。
  目標 400 字以外での 1.5 倍は暫定（未検証）。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .provider import GenerationRequest

RENDERER_VERSION = "nai-r2"
SYSTEM = "あなたは日本語の小説家です。指示された本文だけを出力し、前置き・説明・見出し・区切り記号は書きません。"
GAP_MARK = "【ここに挿入】"
# 出力上限の換算に使う字数/トークン比。Phase 0 Benchmark と同じ値（実測 median 1.223 より少し大きい）に保ち、
# 測った条件とずらさない。上限は目安であり、字数そのものは Completion Controller（Phase 2）で扱う。
OUTPUT_CHARS_PER_TOKEN = 1.3
CONTINUE_CHARS = 400
DIRECTED_HEADROOM = 1.6
# Directed Continue の指示字数の倍率（モデル別）。載っていないモデルは 1.0（nai-r1 と同じ要求）。
DIRECTED_INSTRUCTION_MULTIPLIER: dict[str, float] = {"glm-4-6": 1.5}
EXPAND_CHARS = 80
EXPAND_HEADROOM = 2.0


@dataclass(frozen=True)
class BeatContract:
    objective: str
    end_condition: str
    target_chars: int
    must_include: tuple[str, ...] = ()
    must_not: tuple[str, ...] = ()


@dataclass(frozen=True)
class ContinueInput:
    text: str
    target_chars: int = CONTINUE_CHARS


@dataclass(frozen=True)
class DirectedContinueInput:
    text: str
    contract: BeatContract
    canon_facts: tuple[str, ...] = ()
    instruction_multiplier: float | None = None
    """指示字数の倍率を明示する（実験用）。None ならモデル別の既定（``DIRECTED_INSTRUCTION_MULTIPLIER``）。
    倍率はここか既定のどちらか一方だけを使い、重ねて掛けない。"""


@dataclass(frozen=True)
class ExpandInsertionInput:
    before: str
    after: str
    target_chars: int = EXPAND_CHARS

    @property
    def marked(self) -> str:
        return self.before + GAP_MARK + self.after


@dataclass(frozen=True)
class ExploreBranchInput:
    """「別の展開を見る」（探索機能 E1）の入力。組み立ては ``exploration_prompts.render_explore`` が受け持つ。

    ``fixed`` は守ること（既に起きた出来事・固定の外見・人物関係・世界の条件）、``free`` は自由に変えてよい未来の要素。
    ``end_condition`` は指定があるときだけ必須（探索では未指定を許す）。字数は 1 回の生成量の目安。
    """

    text: str
    fixed: tuple[str, ...] = ()
    free: tuple[str, ...] = ()
    end_condition: str | None = None
    target_chars: int = 400


OperationInput = ContinueInput | DirectedContinueInput | ExpandInsertionInput | ExploreBranchInput
INPUT_TYPES: dict[str, type] = {
    "continue": ContinueInput,
    "directed_continue": DirectedContinueInput,
    "expand_insertion": ExpandInsertionInput,
}


@dataclass(frozen=True)
class RenderedPrompt:
    operation: str
    request: GenerationRequest
    version: str = RENDERER_VERSION
    notes: tuple[str, ...] = field(default_factory=tuple)
    params: dict[str, Any] = field(default_factory=dict)
    """解決した生成の目安（契約の目標字数、指示字数、倍率と出典、出力上限）。記録に残して版の比較に使う。"""


def _tokens(chars: float) -> int:
    return int(chars / OUTPUT_CHARS_PER_TOKEN)


def _chat(model: str, user: str, max_tokens: int, sampling: Mapping[str, Any], stop: tuple[str, ...]) -> GenerationRequest:
    return GenerationRequest(model=model, endpoint="chat", max_tokens=max_tokens, sampling=dict(sampling), stop=stop,
                             messages=({"role": "system", "content": SYSTEM}, {"role": "user", "content": user}))


def render(operation: str, data: OperationInput, model: str, *, sampling: Mapping[str, Any],
           stop: tuple[str, ...] = ()) -> RenderedPrompt:
    """``operation`` に合う入力から要求を組み立てる。入力の型が操作と合わなければ ``TypeError``。"""
    expected = INPUT_TYPES.get(operation)
    if expected is None:
        raise ValueError(f"PromptRenderer {RENDERER_VERSION} はこの操作を扱わない: {operation}")
    if not isinstance(data, expected):
        raise TypeError(f"{operation} の入力は {expected.__name__}（{type(data).__name__} が来た）")

    if isinstance(data, ContinueInput):
        if not data.text.strip():
            raise ValueError("continue の本文が空")
        req = GenerationRequest(model=model, endpoint="completions", max_tokens=_tokens(data.target_chars),
                                sampling=dict(sampling), stop=stop, prompt=data.text)
        return RenderedPrompt(operation, req, params={"target_chars": data.target_chars, "resolved_max_tokens": req.max_tokens})

    if isinstance(data, DirectedContinueInput):
        c = data.contract
        if data.instruction_multiplier is not None:
            multiplier, source = data.instruction_multiplier, "explicit"
        else:
            multiplier, source = DIRECTED_INSTRUCTION_MULTIPLIER.get(model, 1.0), "model_default"
        instruction_chars = int(c.target_chars * multiplier)
        user = (
            f"次の小説本文の続きを、約{instruction_chars}字で書いてください。続きの本文だけを出力してください。\n\n"
            "この場面の契約:\n"
            f"- 目的: {c.objective}\n"
            f"- 必ず含める: {'、'.join(c.must_include)}\n"
            f"- してはいけない: {'、'.join(c.must_not)}\n"
            f"- 終わる位置: {c.end_condition}。そこで書くのをやめる\n"
            "- 登場人物と設定は、本文と次の事実に合わせる:\n"
            + "".join(f"  - {f}\n" for f in data.canon_facts)
            + "\n本文:\n" + data.text
        )
        req = _chat(model, user, _tokens(instruction_chars * DIRECTED_HEADROOM), sampling, stop)
        return RenderedPrompt(operation, req, params={
            "target_chars": c.target_chars, "instruction_chars": instruction_chars,
            "instruction_multiplier": multiplier, "multiplier_source": source, "resolved_max_tokens": req.max_tokens})

    assert isinstance(data, ExpandInsertionInput)  # INPUT_TYPES で操作と入力の型の一致を確かめ済み
    if GAP_MARK in data.before or GAP_MARK in data.after:
        raise ValueError(f"本文に挿入位置の印 {GAP_MARK} がすでに含まれている")
    user = (
        f"次の小説本文の{GAP_MARK}の位置に入れる文を、{data.target_chars}字ほど（1〜3文）で書いてください。"
        "挿入する文だけを出力してください。\n\n"
        "条件:\n"
        "- 新しい出来事、新しい人物、新しい場所、新しい事実を足さない。\n"
        "- 足してよいのは、情景、感情、動作の細部だけ。\n"
        "- 前後の文を繰り返したり、先の展開を書いたりしない。\n"
        "\n本文:\n" + data.marked
    )
    req = _chat(model, user, _tokens(data.target_chars * EXPAND_HEADROOM), sampling, stop)
    return RenderedPrompt(operation, req, params={"target_chars": data.target_chars, "resolved_max_tokens": req.max_tokens})
