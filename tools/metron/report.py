"""V0の著者向けmetricsレポート。自動修復やLLM呼び出しは行わない。"""

from __future__ import annotations

from pathlib import Path

from .models import BeatPlan, MetricsDocument
from .storage import atomic_write_text


def _ratio_text(value: float | None) -> str:
    return "未算出" if value is None else f"{value:.2f}"


def _range_status(actual: int, expected: tuple[int, int | None], label: str) -> str | None:
    lower, upper = expected
    if actual < lower:
        return f"{label} {actual}（下限 {lower} 未達）"
    if upper is not None and actual > upper:
        return f"{label} {actual}（上限 {upper} 超過）"
    return None


def render_report(metrics: MetricsDocument, beat_plan: BeatPlan) -> str:
    payload = metrics.metrics
    beat_by_id = {beat.id: beat for beat in beat_plan.beats}
    lines = [
        f"# METRON V0 レポート（run {payload.run:03d}）",
        "",
        "> V0 は観測と指摘のみを行い、失敗クラスの確定・本文修復・再生成は行わない。",
        "",
        "## 場面集計",
        "",
        f"- 本文文字数: {payload.scene.chars}",
        f"- 全体比（本文 / 全 Beat の `chars_hint` 合計）: {_ratio_text(payload.scene.overall_budget_ratio)}",
        f"- Beat coverage: {'充足' if payload.scene.coverage else '未充足'}",
        f"- `head_tail_ratio`: {_ratio_text(payload.scene.head_tail_ratio)}",
    ]
    if payload.scene.head_tail_ratio is not None:
        lines.append(
            f"- 観測: 末尾2 Beatの密度は先頭2 Beatの {_ratio_text(payload.scene.head_tail_ratio)} 倍"
        )
    else:
        lines.append("- 観測: Beat数不足または先頭群ゼロのため、終盤減衰比は算出しない")
    if payload.finish_reason is not None:
        lines.append(f"- finish_reason: `{payload.finish_reason}`")
        if payload.finish_reason in {"max_tokens", "length"}:
            lines.append("- 観測: GenerationTruncated。密度・総量の判定根拠から除外する")

    lines.extend(["", "## Beat別指摘", ""])
    for item in payload.beats:
        beat = beat_by_id.get(item.id)
        if beat is None:
            lines.extend([f"### {item.id}", "", "- 計画に存在しないmetrics項目", ""])
            continue
        findings: list[str] = [
            f"- 文字数: {item.chars}（budget ratio: {_ratio_text(item.budget_ratio)}）",
            f"- 段落: {item.paragraphs} / 会話往復: {item.dialogue_turns}",
            f"- 感覚描写: {item.sensory} / 内面描写: {item.interiority}",
        ]
        paragraph_status = _range_status(
            item.paragraphs, beat.budget.paragraphs, "段落予算"
        )
        dialogue_status = _range_status(
            item.dialogue_turns, beat.budget.dialogue_turns, "会話予算"
        )
        if paragraph_status:
            findings.append(f"- 観測: {paragraph_status}")
        if dialogue_status:
            findings.append(f"- 観測: {dialogue_status}")
        if item.summary_markers:
            findings.append(
                f"- 補助指標（要約標識）: {', '.join(item.summary_markers)}"
            )
        if item.new_facts is None:
            findings.append("- 新規事実: 未計測（factアノテーションなし）")
        else:
            findings.append(f"- 新規事実アノテーション: {item.new_facts}件")
        lines.extend([f"### {item.id}: {beat.intent}", "", *findings, ""])

    return "\n".join(lines).rstrip() + "\n"


def write_report(path: str | Path, metrics: MetricsDocument, beat_plan: BeatPlan) -> None:
    target = Path(path)
    if target.exists():
        raise FileExistsError(f"report already exists and will not be overwritten: {target}")
    atomic_write_text(target, render_report(metrics, beat_plan))
