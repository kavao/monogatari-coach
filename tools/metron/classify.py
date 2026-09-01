"""METRON V1 の失敗クラス判定と生成粒度計画。"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field

from .calibrate import ModelCalibration
from .models import Beat, BeatMetrics, BeatPlan, Failure, MetricsDocument, SpansDocument, StrictModel
from .storage import load_yaml


_TRUNCATION_REASONS = frozenset({"max_tokens", "length"})


class CalibrationNotReady(ValueError):
    """V1 判定に必要な承認済みキャリブレーションが無い。"""


class Finding(StrictModel):
    failure: Failure
    beat_id: str | None = None
    observed: float | None = None
    threshold: float | None = None
    auto_repair: bool
    reason: str = Field(min_length=1)


class ClassificationResult(StrictModel):
    run: int = Field(ge=1)
    findings: list[Finding] = Field(default_factory=list)

    @property
    def repair_findings(self) -> list[Finding]:
        return [finding for finding in self.findings if finding.auto_repair]


class GenerationCall(StrictModel):
    """1 回の生成に渡す Beat のまとまり。本文生成そのものは担当しない。"""

    id: str = Field(min_length=1)
    beat_ids: list[str] = Field(min_length=1)
    isolated: bool = False
    previous_context_required: bool = False


def load_model_calibration(path: str | Path, model_id: str) -> ModelCalibration:
    data = load_yaml(path)
    models = data.get("models")
    if not isinstance(models, dict):
        raise CalibrationNotReady("config must contain a models mapping")
    raw = models.get(model_id)
    if not isinstance(raw, dict):
        raise CalibrationNotReady(f"no calibration for model {model_id!r}")
    return require_calibration(ModelCalibration.model_validate(raw))


def require_calibration(calibration: ModelCalibration) -> ModelCalibration:
    required = (
        "reliable_span_chars",
        "missing_span_ratio",
        "beat_thin_ratio",
        "ending_rush_threshold",
        "too_short_ratio",
    )
    if not calibration.calibrated:
        raise CalibrationNotReady("model calibration is not approved")
    if calibration.calibrated_at is None or calibration.samples < 1:
        raise CalibrationNotReady(
            "approved calibration must include calibrated_at and a positive sample count"
        )
    missing = [name for name in required if getattr(calibration, name) is None]
    if missing:
        raise CalibrationNotReady(
            "calibration is missing required values: " + ", ".join(missing)
        )
    if calibration.missing_span_ratio == calibration.beat_thin_ratio:
        raise CalibrationNotReady(
            "missing_span_ratio and beat_thin_ratio must be independent values"
        )
    return calibration


def structural_budget_ratio(item: BeatMetrics, beat: Beat) -> float:
    """段落・会話の下限に対する充足率。文字数比（TooShort）とは混ぜない。"""

    para_low, _ = beat.budget.paragraphs
    dlg_low, _ = beat.budget.dialogue_turns
    ratios: list[float] = []
    if para_low:
        ratios.append(item.paragraphs / para_low)
    if dlg_low:
        ratios.append(item.dialogue_turns / dlg_low)
    return min(ratios) if ratios else 1.0


def _span_counts(spans: SpansDocument | None) -> dict[str, int]:
    if spans is None:
        return {}
    counts: dict[str, int] = {}
    for span in spans.spans:
        counts[span.beat] = counts.get(span.beat, 0) + 1
    return counts


def classify_metrics(
    metrics: MetricsDocument,
    beat_plan: BeatPlan,
    calibration: ModelCalibration,
    *,
    spans: SpansDocument | None = None,
) -> ClassificationResult:
    """metrics を V1 の判定へ変換する。

    ``sensory``、``interiority``、``summary_markers``、および未計測の
    ``new_facts`` は BeatThin の判定根拠に使わない。
    """

    thresholds = require_calibration(calibration)
    payload = metrics.metrics
    findings: list[Finding] = []
    truncated = payload.finish_reason in _TRUNCATION_REASONS
    if truncated:
        findings.append(
            Finding(
                failure=Failure.GENERATION_TRUNCATED,
                auto_repair=False,
                reason=(
                    f"finish_reason={payload.finish_reason!r}; "
                    "density and total-length findings are suppressed"
                ),
            )
        )

    by_id = {item.id: item for item in payload.beats}
    plan_by_id = {beat.id: beat for beat in beat_plan.beats}
    span_counts = _span_counts(spans)
    missing_threshold = thresholds.missing_span_ratio
    thin_threshold = thresholds.beat_thin_ratio
    assert missing_threshold is not None
    assert thin_threshold is not None

    for beat in beat_plan.beats:
        item = by_id.get(beat.id)
        count = span_counts.get(beat.id, 0)
        missing = item is None or (spans is not None and count != 1)
        observed_chars = 0 if item is None else item.chars
        if not missing and observed_chars < missing_threshold * beat.budget.chars_hint:
            missing = True
        if missing:
            findings.append(
                Finding(
                    failure=Failure.BEAT_MISSING,
                    beat_id=beat.id,
                    observed=float(observed_chars),
                    threshold=missing_threshold * beat.budget.chars_hint,
                    auto_repair=True,
                    reason="marker/span is missing, duplicated, or below the calibrated span floor",
                )
            )
        if item is None or truncated:
            continue

        thin_reasons: list[str] = []
        observed_structural = structural_budget_ratio(item, beat)
        if observed_structural < thin_threshold:
            thin_reasons.append("budget_ratio")
        lower_paragraphs, _ = beat.budget.paragraphs
        lower_dialogue, _ = beat.budget.dialogue_turns
        if item.paragraphs < lower_paragraphs:
            thin_reasons.append("paragraphs")
        if item.dialogue_turns < lower_dialogue:
            thin_reasons.append("dialogue_turns")
        if thin_reasons:
            findings.append(
                Finding(
                    failure=Failure.BEAT_THIN,
                    beat_id=beat.id,
                    observed=observed_structural,
                    threshold=thin_threshold,
                    auto_repair=True,
                    reason="structural budget under target: " + ", ".join(thin_reasons),
                )
            )
        if item.chars < beat.budget.chars_hint:
            findings.append(
                Finding(
                    failure=Failure.TOO_SHORT,
                    beat_id=beat.id,
                    observed=float(item.chars),
                    threshold=float(beat.budget.chars_hint),
                    auto_repair=True,
                    reason="beat is below the chars_hint length floor; deepen nuance",
                )
            )

    if not truncated:
        ending_threshold = thresholds.ending_rush_threshold
        assert ending_threshold is not None
        scene_floor = beat_plan.generation.chars_floor
        if payload.scene.coverage and payload.scene.chars < scene_floor:
            findings.append(
                Finding(
                    failure=Failure.TOO_SHORT,
                    observed=float(payload.scene.chars),
                    threshold=float(scene_floor),
                    auto_repair=True,
                    reason="scene is below the chars_floor; deepen nuance without changing events",
                )
            )
        if (
            payload.scene.head_tail_ratio is not None
            and payload.scene.head_tail_ratio < ending_threshold
        ):
            findings.append(
                Finding(
                    failure=Failure.ENDING_RUSH,
                    observed=payload.scene.head_tail_ratio,
                    threshold=ending_threshold,
                    auto_repair=True,
                    reason="tail Beat density is below the calibrated ending threshold",
                )
            )

    # Detect a malformed metrics document early in caller-facing results rather
    # than silently treating an unknown Beat as a valid plan item.
    unknown = sorted(set(by_id) - set(plan_by_id))
    for beat_id in unknown:
        findings.append(
            Finding(
                failure=Failure.BEAT_MISSING,
                beat_id=beat_id,
                auto_repair=False,
                reason="metrics contains a Beat not present in BeatPlan",
            )
        )
    return ClassificationResult(run=payload.run, findings=findings)


def resolve_granularity(
    beat_plan: BeatPlan,
    calibration: ModelCalibration,
) -> Literal["scene", "beat"]:
    """明示指定を優先し、auto は reliable span を超えた時だけ分割する。"""

    if beat_plan.generation.granularity == "scene":
        return "scene"
    if beat_plan.generation.granularity == "beat":
        return "beat"
    thresholds = require_calibration(calibration)
    assert thresholds.reliable_span_chars is not None
    total_hint = sum(beat.budget.chars_hint for beat in beat_plan.beats)
    return "beat" if total_hint > thresholds.reliable_span_chars else "scene"


def _is_independent(beat_index: int, beat_plan: BeatPlan) -> bool:
    beat = beat_plan.beats[beat_index]
    is_final_hook = (
        beat_index == len(beat_plan.beats) - 1 and beat.type == "hook"
    )
    return beat.isolated or beat.weight == "heavy" or is_final_hook


def plan_generation_calls(
    beat_plan: BeatPlan,
    calibration: ModelCalibration,
) -> tuple[Literal["scene", "beat"], list[GenerationCall]]:
    """生成単位を計画する。実際の provider 呼び出しはこの関数の責務外。"""

    effective = resolve_granularity(beat_plan, calibration)
    if effective == "beat":
        return effective, [
            GenerationCall(
                id=f"beat:{beat.id}",
                beat_ids=[beat.id],
                isolated=_is_independent(index, beat_plan),
                previous_context_required=index > 0,
            )
            for index, beat in enumerate(beat_plan.beats)
        ]

    calls: list[GenerationCall] = []
    ordinary: list[str] = []
    for index, beat in enumerate(beat_plan.beats):
        if _is_independent(index, beat_plan):
            if ordinary:
                calls.append(
                    GenerationCall(
                        id="scene:" + ",".join(ordinary),
                        beat_ids=ordinary,
                    )
                )
                ordinary = []
            calls.append(
                GenerationCall(
                    id=f"beat:{beat.id}",
                    beat_ids=[beat.id],
                    isolated=True,
                    previous_context_required=index > 0,
                )
            )
        else:
            ordinary.append(beat.id)
    if ordinary:
        calls.append(
            GenerationCall(id="scene:" + ",".join(ordinary), beat_ids=ordinary)
        )
    return effective, calls
