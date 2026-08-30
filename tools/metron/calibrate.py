"""V0のローカル・キャリブレーション集計とdry-run計画。"""

from __future__ import annotations

from datetime import date
from math import floor
from pathlib import Path
from typing import Any

from pydantic import Field

from .models import StrictModel
from .storage import atomic_write_text, load_yaml
import yaml


class CalibrationSample(StrictModel):
    model: str = Field(min_length=1)
    chars_hint: int = Field(gt=0)
    observed_chars: int = Field(ge=0)
    # coverage が成立した Beat の実測スパン比。BeatThin 用の budget_ratios
    # と混ぜず、極端に短いスパンの床を別統計として集計する。
    span_ratios: list[float] = Field(default_factory=list)
    budget_ratios: list[float] = Field(default_factory=list)
    head_tail_ratio: float | None = Field(default=None, ge=0)
    scene_ratio: float | None = Field(default=None, ge=0)
    finish_reason: str | None = None


class CalibrationSamples(StrictModel):
    samples: list[CalibrationSample] = Field(min_length=1)


class ModelCalibration(StrictModel):
    calibrated: bool = False
    calibrated_at: date | None = None
    reliable_span_chars: int | None = Field(default=None, ge=1)
    missing_span_ratio: float | None = Field(default=None, ge=0)
    beat_thin_ratio: float | None = Field(default=None, ge=0)
    ending_rush_threshold: float | None = Field(default=None, ge=0)
    too_short_ratio: float | None = Field(default=None, ge=0)
    expand_retention_threshold: float | None = Field(default=None, ge=0, le=1)
    samples: int = Field(default=0, ge=0)


def load_samples(path: str | Path) -> CalibrationSamples:
    return CalibrationSamples.model_validate(load_yaml(path))


def _lower_quartile(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, floor((len(ordered) - 1) * 0.25))]


def _reliable_span(samples: list[CalibrationSample]) -> int | None:
    ordered = sorted(samples, key=lambda item: item.chars_hint)
    if len(ordered) < 2:
        return None
    ratios = [item.observed_chars / item.chars_hint for item in ordered]
    for index in range(1, len(ratios) - 1):
        if ratios[index] < ratios[index - 1] and ratios[index + 1] <= ratios[index]:
            return ordered[index - 1].chars_hint
    return ordered[-1].chars_hint


def calibrate_samples(
    samples: list[CalibrationSample],
    *,
    model_id: str,
    calibrated_at: date | None = None,
    expand_retention_threshold: float | None = None,
) -> ModelCalibration:
    valid = [
        sample
        for sample in samples
        if sample.model == model_id
        and sample.finish_reason not in {"max_tokens", "length"}
    ]
    if not valid:
        raise ValueError(f"no usable calibration samples for model {model_id!r}")

    span_ratios = [ratio for sample in valid for ratio in sample.span_ratios]
    beat_ratios = [ratio for sample in valid for ratio in sample.budget_ratios]
    scene_ratios = [
        sample.scene_ratio
        if sample.scene_ratio is not None
        else sample.observed_chars / sample.chars_hint
        for sample in valid
    ]
    tail_ratios = [
        sample.head_tail_ratio
        for sample in valid
        if sample.head_tail_ratio is not None
    ]
    reliable = _reliable_span(valid)
    return ModelCalibration(
        calibrated=reliable is not None and bool(span_ratios) and bool(beat_ratios),
        calibrated_at=calibrated_at or date.today(),
        reliable_span_chars=reliable,
        missing_span_ratio=_lower_quartile(span_ratios),
        beat_thin_ratio=_lower_quartile(beat_ratios),
        ending_rush_threshold=_lower_quartile(tail_ratios),
        too_short_ratio=_lower_quartile(scene_ratios),
        expand_retention_threshold=expand_retention_threshold,
        samples=len(valid),
    )


def dry_run_plan(
    *,
    model_id: str,
    hints: list[int],
    sample_count: int = 10,
) -> str:
    if not hints:
        raise ValueError("at least one chars_hint is required")
    if any(hint <= 0 for hint in hints):
        raise ValueError("chars_hint values must be positive")
    lines = [
        "METRON V0 calibration dry-run",
        f"model: {model_id}",
        f"samples: {sample_count}",
        "provider calls: disabled",
        "chars_hint sequence: " + ", ".join(str(hint) for hint in hints),
        "required sample fields: observed_chars, span_ratios, budget_ratios, head_tail_ratio, finish_reason",
        "next step: obtain user approval before production generation",
    ]
    return "\n".join(lines) + "\n"


def merge_model_calibration(
    path: str | Path,
    *,
    model_id: str,
    calibration: ModelCalibration,
) -> None:
    """モデル設定を既存ファイルへ原子的に反映する（providerは呼ばない）。"""

    target = Path(path)
    if target.exists():
        data = load_yaml(target)
    else:
        data = {}
    models: dict[str, Any] = data.setdefault("models", {})
    if not isinstance(models, dict):
        raise ValueError("config models must be a mapping")
    previous = models.get(model_id)
    models[model_id] = calibration.model_dump(mode="json", exclude_none=False)
    if (
        isinstance(previous, dict)
        and calibration.expand_retention_threshold is None
        and previous.get("expand_retention_threshold") is not None
    ):
        models[model_id]["expand_retention_threshold"] = previous[
            "expand_retention_threshold"
        ]
    atomic_write_text(
        target,
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
    )
