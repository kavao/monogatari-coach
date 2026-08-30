"""SceneContract / BeatPlan のロードと P-rule 検証。"""

from __future__ import annotations

from pathlib import Path

from .models import BeatPlan, MetricsDocument, SceneContract, SpansDocument
from .storage import load_model


class ContractValidationError(ValueError):
    """契約の構造または物理パスとの対応が不正。"""


def load_scene_contract(path: str | Path) -> SceneContract:
    return load_model(path, SceneContract)


def load_beat_plan(path: str | Path) -> BeatPlan:
    return load_model(path, BeatPlan)


def load_spans(path: str | Path) -> SpansDocument:
    return load_model(path, SpansDocument)


def load_metrics(path: str | Path) -> MetricsDocument:
    return load_model(path, MetricsDocument)


def validate_contract(
    contract: SceneContract,
    *,
    expected_scene_id: str | None = None,
) -> None:
    """P-rule と、指定された成果物ディレクトリとの Scene ID 対応を検証する。"""

    actual = contract.scene.id
    if expected_scene_id is not None and actual != expected_scene_id:
        raise ContractValidationError(
            f"scene.id {actual!r} does not match expected {expected_scene_id!r}"
        )
    if contract.scene.chronos_span is not None and len(contract.scene.chronos_span) != 2:
        raise ContractValidationError("chronos_span must contain exactly two values")
