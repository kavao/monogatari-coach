"""METRON V1 の回帰観測値。判定や修復の可否には使わない。"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field

from .models import BeatPlan, MetricsDocument, StrictModel
from .storage import atomic_write_model


class RegressionObservation(StrictModel):
    run: int = Field(ge=1)
    beat_coverage_ratio: float = Field(ge=0, le=1)
    mean_budget_ratio: float | None = Field(default=None, ge=0)
    overall_budget_ratio: float | None = Field(default=None, ge=0)
    head_tail_ratio: float | None = Field(default=None, ge=0)
    finish_reason: str | None = None


def build_regression_observation(
    metrics: MetricsDocument,
    beat_plan: BeatPlan,
) -> RegressionObservation:
    plan_ids = {beat.id for beat in beat_plan.beats}
    measured_ids = {item.id for item in metrics.metrics.beats}
    coverage = len(plan_ids & measured_ids) / len(plan_ids)
    ratios = [
        item.budget_ratio
        for item in metrics.metrics.beats
        if item.id in plan_ids
    ]
    return RegressionObservation(
        run=metrics.metrics.run,
        beat_coverage_ratio=coverage,
        mean_budget_ratio=sum(ratios) / len(ratios) if ratios else None,
        overall_budget_ratio=metrics.metrics.scene.overall_budget_ratio,
        head_tail_ratio=metrics.metrics.scene.head_tail_ratio,
        finish_reason=metrics.metrics.finish_reason,
    )


def write_regression(path: str | Path, observation: RegressionObservation) -> None:
    atomic_write_model(path, observation)
