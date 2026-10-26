from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from ai_writer.validator_fixtures import (  # noqa: E402
    VIOLATION_TYPES,
    check_consistency,
    coverage,
    expected_predictions,
    load_fixtures,
    score,
)


def test_fixtures_are_consistent() -> None:
    assert check_consistency(load_fixtures()) == []


def test_fixtures_cover_every_violation_type_in_each_scene() -> None:
    sets = load_fixtures()
    assert coverage(sets)["missing_types"] == []
    for fs in sets:
        assert coverage([fs])["missing_types"] == [], fs.scene_id
        assert coverage([fs])["negative"] >= 4, fs.scene_id


def test_perfect_predictions_score_perfectly() -> None:
    sets = load_fixtures()
    result = score(sets, expected_predictions(sets))
    assert result["status_accuracy"] == 1.0
    assert result["errors"] == []
    assert result["detection"]["false_positive_rate"] == 0.0
    for t in VIOLATION_TYPES:
        assert result["per_type"][t]["recall"] == 1.0, t
        assert result["per_type"][t]["precision"] == 1.0, t


def test_all_pass_predictions_miss_every_violation() -> None:
    sets = load_fixtures()
    preds = {cid: {"status": "pass", "violations": []} for cid in expected_predictions(sets)}
    result = score(sets, preds)
    assert result["detection"]["recall"] == 0.0
    assert result["detection"]["false_positive_rate"] == 0.0
    assert result["per_type"]["new_character"]["fn"] >= 2


def test_acceptable_extra_is_not_counted_as_false_positive() -> None:
    sets = load_fixtures()
    preds = expected_predictions(sets)
    preds["station-pos-new-character"]["violations"].append("new_event")
    preds["station-neg-01"] = {"status": "warning", "violations": ["new_fact"]}
    result = score(sets, preds)
    assert result["per_type"]["new_event"]["fp"] == 0
    assert result["per_type"]["new_fact"]["fp"] == 1
    assert result["detection"]["fp"] == 1


def test_missing_predictions_are_reported() -> None:
    sets = load_fixtures()
    preds = expected_predictions(sets)
    preds.pop("library-neg-01")
    preds["no-such-case"] = {"status": "pass", "violations": []}
    result = score(sets, preds)
    assert result["missing_predictions"] == ["library-neg-01"]
    assert result["unknown_predictions"] == ["no-such-case"]
