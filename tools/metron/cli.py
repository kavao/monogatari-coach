"""METRON の正規 CLI 実装。外部 provider は呼び出さない。"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from pydantic import BaseModel

from .analyze import analyze_marked_text
from .calibrate import (
    calibrate_samples,
    dry_run_plan,
    load_samples,
    merge_model_calibration,
)
from .classify import (
    classify_metrics,
    load_model_calibration,
    plan_generation_calls,
)
from .contract import (
    load_beat_plan,
    load_metrics,
    load_scene_contract,
    load_spans,
    validate_contract,
)
from .models import GeneratorInfo
from .regression import build_regression_observation
from .repair import write_final
from .report import render_report, write_report
from .storage import atomic_write_model, atomic_write_text, model_to_yaml


def _new_text(path: Path, text: str) -> None:
    if path.exists():
        raise FileExistsError(f"output already exists and will not be overwritten: {path}")
    atomic_write_text(path, text)


def _new_model(path: Path, model: BaseModel) -> None:
    if path.exists():
        raise FileExistsError(f"output already exists and will not be overwritten: {path}")
    atomic_write_model(path, model)


def _validate_scene_output_dir(output_dir: Path, scene_id: str) -> None:
    if output_dir.name != scene_id:
        raise ValueError(
            f"output directory must be named with scene.id {scene_id!r}: {output_dir}"
        )


def _add_contract_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--beats", type=Path, required=True)


def _handle_validate(args: argparse.Namespace) -> int:
    contract = load_scene_contract(args.contract)
    beat_plan = load_beat_plan(args.beats)
    validate_contract(contract, expected_scene_id=args.scene_id)
    print(f"valid: {contract.scene.id}")
    hints = [beat.budget.chars_hint for beat in beat_plan.beats]
    if len(hints) >= 3 and len(set(hints)) == 1:
        print(
            f"warning: equal_chars_hint scene={contract.scene.id} "
            f"beats={len(hints)} (advisory; not an error)",
            file=sys.stderr,
        )
    return 0


def _handle_analyze(args: argparse.Namespace) -> int:
    contract = load_scene_contract(args.contract)
    beat_plan = load_beat_plan(args.beats)
    validate_contract(contract, expected_scene_id=args.scene_id)
    if args.run < 1:
        raise ValueError("run must be positive")
    generator = GeneratorInfo(
        model=args.model,
        granularity=args.granularity,
        temperature=args.temperature,
    )
    result = analyze_marked_text(
        args.draft.read_text(encoding="utf-8"),
        beat_plan,
        run=args.run,
        finish_reason=args.finish_reason,
        generator=generator,
    )
    output_dir = args.output_dir
    _validate_scene_output_dir(output_dir, contract.scene.id)
    output_dir.mkdir(parents=True, exist_ok=True)
    _new_text(output_dir / f"draft.{args.run:03d}.md", result.clean_text)
    _new_model(output_dir / f"spans.{args.run:03d}.yaml", result.spans)
    _new_model(output_dir / f"metrics.{args.run:03d}.yaml", result.metrics)
    observation = build_regression_observation(result.metrics, beat_plan)
    _new_model(output_dir / f"regression.{args.run:03d}.yaml", observation)
    print(f"analyzed: {output_dir / f'metrics.{args.run:03d}.yaml'}")
    return 0


def _handle_report(args: argparse.Namespace) -> int:
    metrics = load_metrics(args.metrics)
    beat_plan = load_beat_plan(args.beats)
    report = render_report(metrics, beat_plan)
    if args.output is None:
        sys.stdout.write(report)
    else:
        write_report(args.output, metrics, beat_plan)
        print(f"written: {args.output}")
    return 0


def _handle_calibrate(args: argparse.Namespace) -> int:
    if args.dry_run:
        print(
            dry_run_plan(
                model_id=args.model,
                hints=args.hints,
                sample_count=args.sample_count,
            ),
            end="",
        )
        return 0
    if args.samples is None:
        raise ValueError("--samples is required unless --dry-run is used")
    loaded = load_samples(args.samples)
    calibration = calibrate_samples(
        loaded.samples,
        model_id=args.model,
        expand_retention_threshold=args.expand_retention_threshold,
    )
    if not args.approve:
        calibration = calibration.model_copy(update={"calibrated": False})
    if args.write:
        merge_model_calibration(
            args.config,
            model_id=args.model,
            calibration=calibration,
        )
        print(f"calibration written: {args.config}")
    else:
        sys.stdout.write(model_to_yaml(calibration))
    return 0


def _handle_classify(args: argparse.Namespace) -> int:
    beat_plan = load_beat_plan(args.beats)
    metrics = load_metrics(args.metrics)
    calibration = load_model_calibration(args.config, args.model)
    spans = load_spans(args.spans) if args.spans is not None else None
    result = classify_metrics(metrics, beat_plan, calibration, spans=spans)
    if args.output is None:
        sys.stdout.write(model_to_yaml(result))
    else:
        _new_model(args.output, result)
        print(f"written: {args.output}")
    return 0


def _handle_plan(args: argparse.Namespace) -> int:
    beat_plan = load_beat_plan(args.beats)
    calibration = load_model_calibration(args.config, args.model)
    effective, calls = plan_generation_calls(beat_plan, calibration)
    output = model_to_yaml(
        _MappingModel(
            granularity=effective,
            calls=[call.model_dump(mode="json") for call in calls],
        )
    )
    if args.output is None:
        sys.stdout.write(output)
    else:
        _new_text(args.output, output)
        print(f"written: {args.output}")
    return 0


def _handle_finalize(args: argparse.Namespace) -> int:
    write_final(args.output, args.draft.read_text(encoding="utf-8"))
    print(f"written: {args.output}")
    return 0


class _MappingModel(BaseModel):
    """model_to_yaml に渡す CLI だけの最小アダプター。"""

    granularity: str
    calls: list[dict[str, object]]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="metron",
        description="METRON V0/V1 local analysis and repair planning (no provider calls)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate", help="validate contract and BeatPlan")
    _add_contract_args(validate)
    validate.add_argument("--scene-id")
    validate.set_defaults(handler=_handle_validate)

    analyze = subparsers.add_parser("analyze", help="analyze marked draft")
    _add_contract_args(analyze)
    analyze.add_argument("--draft", type=Path, required=True)
    analyze.add_argument("--output-dir", type=Path, required=True)
    analyze.add_argument("--run", type=int, required=True)
    analyze.add_argument("--model", default="fixture")
    analyze.add_argument("--granularity", choices=["scene", "beat", "auto"], default="auto")
    analyze.add_argument("--temperature", type=float)
    analyze.add_argument("--finish-reason")
    analyze.add_argument("--scene-id")
    analyze.set_defaults(handler=_handle_analyze)

    report = subparsers.add_parser("report", help="render an author-facing report")
    report.add_argument("--metrics", type=Path, required=True)
    report.add_argument("--beats", type=Path, required=True)
    report.add_argument("--output", type=Path)
    report.set_defaults(handler=_handle_report)

    calibrate = subparsers.add_parser("calibrate", help="dry-run or aggregate local samples")
    calibrate.add_argument("--model", required=True)
    calibrate.add_argument("--samples", type=Path)
    calibrate.add_argument("--config", type=Path, default=Path("config/metron_models.yaml"))
    calibrate.add_argument("--dry-run", action="store_true")
    calibrate.add_argument("--write", action="store_true")
    calibrate.add_argument(
        "--approve",
        action="store_true",
        help="mark the aggregated calibration approved after the production review",
    )
    calibrate.add_argument("--hints", nargs="+", type=int, default=[400, 800, 1200])
    calibrate.add_argument("--sample-count", type=int, default=10)
    calibrate.add_argument("--expand-retention-threshold", type=float)
    calibrate.set_defaults(handler=_handle_calibrate)

    classify = subparsers.add_parser("classify", help="classify V1 failures")
    classify.add_argument("--metrics", type=Path, required=True)
    classify.add_argument("--beats", type=Path, required=True)
    classify.add_argument("--spans", type=Path)
    classify.add_argument("--config", type=Path, default=Path("config/metron_models.yaml"))
    classify.add_argument("--model", required=True)
    classify.add_argument("--output", type=Path)
    classify.set_defaults(handler=_handle_classify)

    plan = subparsers.add_parser("plan", help="plan scene/Beat generation calls")
    plan.add_argument("--beats", type=Path, required=True)
    plan.add_argument("--config", type=Path, default=Path("config/metron_models.yaml"))
    plan.add_argument("--model", required=True)
    plan.add_argument("--output", type=Path)
    plan.set_defaults(handler=_handle_plan)

    finalize = subparsers.add_parser("finalize", help="write marker-free FINAL.md")
    finalize.add_argument("--draft", type=Path, required=True)
    finalize.add_argument("--output", type=Path, required=True)
    finalize.set_defaults(handler=_handle_finalize)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.handler(args)
    except (OSError, ValueError) as error:
        print(f"metron: {error}", file=sys.stderr)
        return 2
