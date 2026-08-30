"""Beat予算をWriter向けのプロンプトへ変換する。"""

from __future__ import annotations

from .models import Beat, BeatBudget, PromptBudget


def to_prompt_budget(budget: BeatBudget) -> PromptBudget:
    """検査専用の ``chars_hint`` を除いた予算境界を作る。"""

    return PromptBudget(
        paragraphs=budget.paragraphs,
        dialogue_turns=budget.dialogue_turns,
        sensory=budget.sensory,
        interiority=budget.interiority,
        new_facts=budget.new_facts,
    )


def _range_text(value: tuple[int, int | None]) -> str:
    lower, upper = value
    return f"{lower}〜{upper if upper is not None else '上限なし'}"


def build_beat_prompt(
    beat: Beat,
    *,
    previous_context: str | None = None,
) -> str:
    """Beatの意図と離散要素予算だけを含むWriter向け指示を作る。"""

    budget = to_prompt_budget(beat.budget)
    lines = [
        f"Beat {beat.id} を執筆する。",
        f"種別: {beat.type}",
        f"意図: {beat.intent}",
        f"重要度: {beat.weight}",
        f"本文段落数: {_range_text(budget.paragraphs)}",
        f"会話の往復数: {_range_text(budget.dialogue_turns)}",
        f"感覚描写: 少なくとも {budget.sensory} 箇所",
        f"内面描写: 少なくとも {budget.interiority} 箇所",
        "Beatの冒頭で状況を再説明せず、直前の文脈から続ける。",
        "指定した出来事と結末を変更しない。",
    ]
    if budget.new_facts > 0:
        lines.extend(
            [
                f"新規事実を {budget.new_facts} 件導入する。意図した新規事実ごとに、本文中へ <!--fact:<id>--> を1つ置く。",
                "factマーカーは検査用のゼロ幅コメントであり、読者向けの文字として書かない。",
            ]
        )
    if previous_context:
        lines.extend(
            [
                "直前Beatの末尾文脈（ここから直結して続ける）:",
                previous_context,
            ]
        )
    lines.extend(
        [
            "次の形式でBeatマーカーを含めて出力する:",
            f"<!--beat:{beat.id}-->",
            "（本文）",
            f"<!--/beat:{beat.id}-->",
        ]
    )
    return "\n".join(lines)
