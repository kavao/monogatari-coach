"""Validator Fixture の形式・整合検査・採点（計画書 §55〜57）。

Fixture は ``tools/ai_writer/fixtures/validator/*.yaml``。1 ファイルが 1 場面で、場面の文脈・
Beat Contract・正解ラベル付きの候補本文（cases）を持つ。

- 重大度: ``new_*`` は warning、``must_*`` と ``end_condition_*`` は fail（§29〜30）。
  期待 status は違反の最大重大度と一致しなければならない。
- ``acceptable_extra``: 出しても誤検出に数えない副次の違反（例: 人物の登場は出来事でもある）。
- 採点は違反種別ごとに TP / FP / TN / FN を数え、precision / recall / FPR / FNR を出す（§57）。

実行: ``uv run python tools/ai_writer_validator_fixture_cli.py validate``
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "validator"

ViolationType = Literal[
    "new_character", "new_location", "new_event", "new_fact",
    "must_include_missing", "must_not_violation", "end_condition_unmet", "end_condition_exceeded",
]
Status = Literal["pass", "warning", "fail"]

VIOLATION_TYPES: tuple[str, ...] = (
    "new_character", "new_location", "new_event", "new_fact",
    "must_include_missing", "must_not_violation", "end_condition_unmet", "end_condition_exceeded",
)
SEVERITY: dict[str, Status] = {
    "new_character": "warning", "new_location": "warning", "new_event": "warning", "new_fact": "warning",
    "must_include_missing": "fail", "must_not_violation": "fail",
    "end_condition_unmet": "fail", "end_condition_exceeded": "fail",
}
_STATUS_RANK = {"pass": 0, "warning": 1, "fail": 2}
# 欠落を表す種別は本文に根拠の文字列がない
NO_EVIDENCE_TYPES = frozenset({"must_include_missing", "end_condition_unmet"})


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class KnownEntities(_Strict):
    characters: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    items: list[str] = Field(default_factory=list)


class Context(_Strict):
    preceding_text: str
    known_entities: KnownEntities
    canon_facts: list[str] = Field(default_factory=list)


class Contract(_Strict):
    objective: str
    must_include: list[str] = Field(default_factory=list)
    must_not: list[str] = Field(default_factory=list)
    end_condition: str


class Violation(_Strict):
    type: ViolationType
    evidence: str | None = None
    target: str | None = None


class Expected(_Strict):
    status: Status
    violations: list[Violation] = Field(default_factory=list)
    acceptable_extra: list[ViolationType] = Field(default_factory=list)


class Case(_Strict):
    id: str
    polarity: Literal["negative", "positive"]
    note: str | None = None
    candidate: str
    expected: Expected


class FixtureSet(_Strict):
    scene_id: str
    label: str
    context: Context
    contract: Contract
    cases: list[Case]


def expected_status(violations: list[Violation]) -> Status:
    status: Status = "pass"
    for v in violations:
        if _STATUS_RANK[SEVERITY[v.type]] > _STATUS_RANK[status]:
            status = SEVERITY[v.type]
    return status


def load_fixtures(directory: Path = FIXTURE_DIR) -> list[FixtureSet]:
    return [FixtureSet.model_validate(yaml.safe_load(p.read_text(encoding="utf-8")))
            for p in sorted(directory.glob("*.yaml"))]


def check_consistency(sets: list[FixtureSet]) -> list[str]:
    """形式（pydantic）では捉えられない整合の誤りを返す。空なら整合している。"""
    errors: list[str] = []
    seen: set[str] = set()
    for fs in sets:
        for case in fs.cases:
            where = f"{fs.scene_id}/{case.id}"
            if case.id in seen:
                errors.append(f"{where}: id が重複")
            seen.add(case.id)
            exp = case.expected
            if (case.polarity == "negative") != (not exp.violations):
                errors.append(f"{where}: negative なら違反なし、positive なら違反ありにする")
            if exp.status != expected_status(exp.violations):
                errors.append(f"{where}: status {exp.status} が違反の重大度 {expected_status(exp.violations)} と一致しない")
            types = {v.type for v in exp.violations}
            overlap = types & set(exp.acceptable_extra)
            if overlap:
                errors.append(f"{where}: acceptable_extra と violations が重なる {sorted(overlap)}")
            for v in exp.violations:
                if v.type in NO_EVIDENCE_TYPES:
                    if v.evidence:
                        errors.append(f"{where}: {v.type} は欠落の違反なので evidence を書かない")
                elif not v.evidence:
                    errors.append(f"{where}: {v.type} に evidence がない")
                elif v.evidence not in case.candidate:
                    errors.append(f"{where}: evidence「{v.evidence}」が候補本文にない")
                if v.type == "must_include_missing":
                    if v.target not in fs.contract.must_include:
                        errors.append(f"{where}: target は contract.must_include のどれかにする")
                elif v.type == "must_not_violation":
                    if v.target not in fs.contract.must_not:
                        errors.append(f"{where}: target は contract.must_not のどれかにする")
                elif v.target is not None:
                    errors.append(f"{where}: {v.type} に target は書かない")
    return errors


def coverage(sets: list[FixtureSet]) -> dict[str, Any]:
    cases = [c for fs in sets for c in fs.cases]
    by_type = {t: sum(1 for c in cases for v in c.expected.violations if v.type == t) for t in VIOLATION_TYPES}
    return {
        "scenes": len(sets),
        "cases": len(cases),
        "negative": sum(1 for c in cases if c.polarity == "negative"),
        "positive": sum(1 for c in cases if c.polarity == "positive"),
        "by_type": by_type,
        "missing_types": [t for t, n in by_type.items() if n == 0],
    }


def expected_predictions(sets: list[FixtureSet]) -> dict[str, dict[str, Any]]:
    """正解そのものを予測の形で返す（採点の自己確認と、予測ファイルの雛形に使う）。"""
    return {c.id: {"status": c.expected.status, "violations": [v.type for v in c.expected.violations]}
            for fs in sets for c in fs.cases}


def _pred_types(pred: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    for v in pred.get("violations") or []:
        out.add(v["type"] if isinstance(v, dict) else str(v))
    return out


def _rates(tp: int, fp: int, tn: int, fn: int) -> dict[str, float | None]:
    def div(a: int, b: int) -> float | None:
        return round(a / b, 3) if b else None
    return {"precision": div(tp, tp + fp), "recall": div(tp, tp + fn),
            "false_positive_rate": div(fp, fp + tn), "false_negative_rate": div(fn, fn + tp)}


def score(sets: list[FixtureSet], predictions: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """違反種別ごとと、違反の有無（検出）について混同行列と率を出す。"""
    cases = [c for fs in sets for c in fs.cases]
    missing = [c.id for c in cases if c.id not in predictions]
    unknown = sorted(set(predictions) - {c.id for c in cases})
    per_type: dict[str, dict[str, Any]] = {}
    for t in VIOLATION_TYPES:
        tp = fp = tn = fn = 0
        for c in cases:
            if c.id not in predictions:
                continue
            truth = t in {v.type for v in c.expected.violations}
            pred = t in _pred_types(predictions[c.id])
            if truth and pred:
                tp += 1
            elif truth:
                fn += 1
            elif pred and t not in c.expected.acceptable_extra:
                fp += 1
            elif not pred:
                tn += 1
        per_type[t] = {"tp": tp, "fp": fp, "tn": tn, "fn": fn, **_rates(tp, fp, tn, fn)}
    d_tp = d_fp = d_tn = d_fn = 0
    status_hits = 0
    errors: list[dict[str, Any]] = []
    for c in cases:
        if c.id not in predictions:
            continue
        pred = predictions[c.id]
        truth_any = bool(c.expected.violations)
        pred_any = pred.get("status", "pass") != "pass"
        d_tp += truth_any and pred_any
        d_fn += truth_any and not pred_any
        d_fp += pred_any and not truth_any
        d_tn += not truth_any and not pred_any
        status_hits += pred.get("status") == c.expected.status
        exp_types = {v.type for v in c.expected.violations}
        got = _pred_types(pred)
        if pred.get("status") != c.expected.status or exp_types - got or (got - exp_types - set(c.expected.acceptable_extra)):
            errors.append({"id": c.id, "expected": {"status": c.expected.status, "violations": sorted(exp_types)},
                           "predicted": {"status": pred.get("status"), "violations": sorted(got)}})
    scored = len(cases) - len(missing)
    return {
        "cases": len(cases), "scored": scored, "missing_predictions": missing, "unknown_predictions": unknown,
        "status_accuracy": round(status_hits / scored, 3) if scored else None,
        "detection": {"tp": d_tp, "fp": d_fp, "tn": d_tn, "fn": d_fn, **_rates(d_tp, d_fp, d_tn, d_fn)},
        "per_type": per_type,
        "errors": errors,
    }


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    parser = argparse.ArgumentParser(description="Validator Fixture の検査と採点")
    parser.add_argument("--dir", type=Path, default=FIXTURE_DIR, help="Fixture のディレクトリ")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("validate", help="形式と整合を検査し、件数を表示する")
    sub.add_parser("expected", help="正解を予測ファイルの形で出す（雛形・自己確認用）")
    sp = sub.add_parser("score", help="予測ファイル（JSON）を採点する")
    sp.add_argument("predictions", type=Path)
    args = parser.parse_args(argv)

    sets = load_fixtures(args.dir)
    if args.cmd == "validate":
        errors = check_consistency(sets)
        print(json.dumps(coverage(sets), ensure_ascii=False, indent=2))
        for e in errors:
            print(f"NG {e}")
        print("OK" if not errors else f"誤り {len(errors)} 件")
        return 0 if not errors else 1
    if args.cmd == "expected":
        print(json.dumps(expected_predictions(sets), ensure_ascii=False, indent=2))
        return 0
    predictions = json.loads(args.predictions.read_text(encoding="utf-8"))
    print(json.dumps(score(sets, predictions), ensure_ascii=False, indent=2))
    return 0
