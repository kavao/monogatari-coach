"""「別の展開を見る」の入力組立（探索機能の計画 ``20261009_ai_writer_creative_exploration.md`` §3、E1）。

- chat で、守ること・自由にしてよいこと・本文を短い区画に分けて渡し、候補の本文だけを返させる（§3.3）。
- 1 要求で 1 候補。複数候補を 1 要求で列挙させない。前の候補を次の要求に混ぜない。
- GLM-4.6 と Xialong に同じ入力を渡す（共通条件）。モデル固有の調整は、共通条件の結果を残してから版を分けて加える。
- 新しい人物・過去・世界の仕組みは足してよいが、確定設定ではなく「追加候補」として扱う（§3.2）。

版を変えたら ``EXPLORE_RENDERER_VERSION`` を上げる。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .prompt_renderer import OUTPUT_CHARS_PER_TOKEN, SYSTEM, ExploreBranchInput, RenderedPrompt
from .provider import GenerationRequest

EXPLORE_OPERATION = "explore_branch"
EXPLORE_RENDERER_VERSION = "exp-r1"
EXPLORE_HEADROOM = 1.6  # Directed Continue と同じ余裕（共通条件の出発点）
DEFAULT_FREE = ("分岐点から先の行動、会話、選択、結末",)
ALWAYS_FIXED = "本文にすでに書かれた出来事と、人物どうしの関係"


def render_explore(data: ExploreBranchInput, model: str, *, sampling: Mapping[str, Any],
                   stop: tuple[str, ...] = ()) -> RenderedPrompt:
    if not data.text.strip():
        raise ValueError("分岐の本文が空")
    fixed = (ALWAYS_FIXED, *data.fixed)
    free = data.free or DEFAULT_FREE
    lines = [
        f"次の小説本文の続きとして、この先の展開の一案を約{data.target_chars}字で書いてください。"
        "続きの本文だけを出力し、案の説明や見出しは書かないでください。",
        "",
        "守ること:",
        *(f"- {f}" for f in fixed),
        "",
        "自由にしてよいこと:",
        *(f"- {f}" for f in free),
        "",
        "新しい人物・過去の出来事・世界の仕組みを足してもよいが、本文と「守ること」に矛盾させない。",
    ]
    if data.end_condition:
        lines.append(f"終わる位置: {data.end_condition}。そこで書くのをやめる")
    lines += ["", "本文:", data.text]
    max_tokens = int(data.target_chars * EXPLORE_HEADROOM / OUTPUT_CHARS_PER_TOKEN)
    req = GenerationRequest(model=model, endpoint="chat", max_tokens=max_tokens, sampling=dict(sampling), stop=stop,
                            messages=({"role": "system", "content": SYSTEM}, {"role": "user", "content": "\n".join(lines)}))
    return RenderedPrompt(EXPLORE_OPERATION, req, version=EXPLORE_RENDERER_VERSION,
                          params={"target_chars": data.target_chars, "resolved_max_tokens": max_tokens,
                                  "fixed_count": len(fixed), "free_count": len(free),
                                  "end_condition": bool(data.end_condition)})
