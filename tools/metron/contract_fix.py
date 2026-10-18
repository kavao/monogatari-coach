"""契約修正の再生成（D16b）。場面契約・設計に合わせて指定 Beat を書き直す。

規定量調整とは別の操作で、分量の保証は旧 Beat の字数ではなく Beat の床（chars_hint）で行う。
契約を変える操作なので、採用には著者確認を要する（writing_bridge 側で強制する）。
provider は呼ばない。
"""

from __future__ import annotations

from collections.abc import Callable
import unicodedata

from pydantic import Field

from .calibrate import ModelCalibration
from .models import BeatPlan, MetricsDocument, SpansDocument, StrictModel

CONTRACT_FIX_TOKEN = "__contract_fix__"
MAX_ATTEMPTS = 2


class ContractFixSpec(StrictModel):
    beat_ids: list[str] = Field(min_length=1)
    instruction: str = Field(min_length=1)


def build_contract_fix_prompt(beat, current_text: str, *, instruction: str,
                              previous_context: str) -> str:
    from .prompt import build_beat_prompt

    return "\n".join([
        build_beat_prompt(beat, previous_context=previous_context or None),
        "",
        "契約修正の再生成: 次の指示に合わせて、この Beat を書き直す。",
        instruction,
        f"長さは Beat の下限 {beat.budget.chars_hint}字以上（旧稿の字数には縛られない）。",
        "指示に無い出来事・人物・過去を足さない。前後の Beat とのつながりを保つ。",
        "現在の Beat 本文（契約に合わない稿）:",
        current_text,
    ])


def validate_contract_fix(original: str, candidate: str, *, floor: int) -> str | None:
    """形の検査。契約に合っているかは著者確認で決める。"""

    from .length import beat_chars

    clean = unicodedata.normalize("NFC", candidate).strip()
    if not clean:
        return "candidate is empty"
    if clean == unicodedata.normalize("NFC", original).strip():
        return "candidate is identical to the original"
    if beat_chars(clean) < floor:
        return f"candidate is below the beat floor {floor}"
    return None


def contract_fix_impl(
    metrics: MetricsDocument,
    beat_plan: BeatPlan,
    calibration: ModelCalibration,
    *,
    clean_text: str,
    spans: SpansDocument,
    spec: ContractFixSpec,
    dispatch: Callable[[str, str | None, str], str],
    checkpoint: Callable[[dict[str, str]], None] | None = None,
):
    from .analyze import analyze_marked_text
    from .classify import classify_metrics
    from .repair import (
        SceneRepairResult, _previous_text, _text_by_beat, assemble_beat_texts,
        marked_text_for_measurement, strip_generation_markers,
    )

    classification = classify_metrics(metrics, beat_plan, calibration, spans=spans)
    texts = _text_by_beat(clean_text, beat_plan, spans)
    if checkpoint:
        checkpoint(dict(texts))
    index_of = {beat.id: position for position, beat in enumerate(beat_plan.beats)}
    by_id = {beat.id: beat for beat in beat_plan.beats}
    regenerated: list[str] = []
    escalated: set[str] = set()
    notes: list[str] = []
    for beat_id in spec.beat_ids:
        accepted = False
        for _ in range(MAX_ATTEMPTS):
            prompt = build_contract_fix_prompt(
                by_id[beat_id], texts[beat_id], instruction=spec.instruction,
                previous_context=_previous_text(index_of[beat_id], beat_plan, texts))
            if checkpoint:
                checkpoint(dict(texts))
            candidate = dispatch("regenerate", beat_id, prompt)
            if candidate.strip():
                texts[beat_id] = strip_generation_markers(candidate)
                regenerated.append(beat_id)
                accepted = True
                break
        if not accepted:
            escalated.add(CONTRACT_FIX_TOKEN)
            notes.append(f"CONTRACT_FIX_NOT_ACCEPTED: {beat_id}")
    if regenerated:
        notes.append("CONTRACT_FIX_DONE: " + ", ".join(regenerated))
    from .length import assembled_chars

    scene_chars = assembled_chars(beat_plan, texts)
    if scene_chars < beat_plan.generation.chars_floor:
        # Beat の床を満たしても場面の床を割ることがある。候補は残し、完了にしない。
        escalated.add(CONTRACT_FIX_TOKEN)
        notes.append(f"CONTRACT_FIX_SCENE_FLOOR: scene has {scene_chars} chars, "
                     f"below the floor {beat_plan.generation.chars_floor}")
    if checkpoint:
        checkpoint(dict(texts))
    verification = analyze_marked_text(
        marked_text_for_measurement(beat_plan, texts), beat_plan, run=metrics.metrics.run + 1)
    return SceneRepairResult(
        classification=classification, beat_texts=texts,
        final_text=assemble_beat_texts(beat_plan, texts), expansions={},
        regenerated_beats=tuple(regenerated), seam_correction_applied=False,
        escalated_beats=tuple(sorted(escalated)), notes=tuple(notes),
        verification_metrics=verification.metrics,
        verification_classification=classify_metrics(
            verification.metrics, beat_plan, calibration, spans=verification.spans),
    )
