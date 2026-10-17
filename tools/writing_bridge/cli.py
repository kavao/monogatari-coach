"""writing_bridge の正規 CLI。LLM は起動しない。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .commands import inspect, prepare, receive, status
from .locate import locate_quote_run
from .publish import publish
from .repair import (
    canon_precheck, length_review, repair_begin, repair_next, repair_submit, repair_finish,
)
from .errors import BridgeError, ErrorDocument
from .models import RequestKind, Selector, SelectorKind
from metron.models import LengthTarget, LengthTolerance


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="writing-bridge",
        description="Connect METRON/CHRONOS context to a writing run (no provider calls)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    prep = sub.add_parser("prepare", help="write context without changing _novel_text")
    _add_work(prep)
    prep.add_argument("--scene-id", required=True)
    prep.add_argument("--text-path", required=True)
    prep.add_argument("--request-kind", choices=[item.value for item in RequestKind], default="new")
    prep.add_argument("--model", default="local-writer")
    prep.add_argument("--selector-kind", choices=[item.value for item in SelectorKind])
    prep.add_argument("--selector-value")
    prep.add_argument("--links", type=Path)
    prep.add_argument("--allow-publish", action="store_true")
    prep.add_argument("--dry-run", action="store_true")
    prep.add_argument("--repo-root", type=Path, default=Path.cwd())

    rec = sub.add_parser("receive", help="store a draft candidate for the run")
    _add_work(rec)
    rec.add_argument("--scene-id", required=True)
    rec.add_argument("--run-id", required=True)
    rec.add_argument("--candidate", type=Path, required=True)
    rec.add_argument("--request-id")
    rec.add_argument(
        "--finish-reason",
        help="generation finish_reason bound to this candidate edition (e.g. length)",
    )

    ins = sub.add_parser("inspect", help="measure and check C1 on the same text version")
    _add_work(ins)
    ins.add_argument("--scene-id", required=True)
    ins.add_argument("--run-id", required=True)
    ins.add_argument("--observations", type=Path)
    ins.add_argument(
        "--marked",
        type=Path,
        help="path to the same received candidate bytes (hash must match artifact_refs)",
    )
    ins.add_argument(
        "--from-run",
        help="reuse observations.json from another run when text hashes match",
    )
    ins.add_argument("--repo-root", type=Path, default=Path.cwd())

    loc = sub.add_parser(
        "locate-quote",
        help="draft C1 coordinates for a unique quote (no meaning check)",
    )
    _add_work(loc)
    loc.add_argument("--scene-id", required=True)
    loc.add_argument("--run-id", required=True)
    loc.add_argument("--quote", required=True, help="exact quote in the normalized text")
    loc.add_argument(
        "--marked",
        type=Path,
        help="path to the same received candidate bytes (hash must match artifact_refs)",
    )

    st = sub.add_parser("status", help="show run journal and report")
    _add_work(st)
    st.add_argument("--scene-id", required=True)
    st.add_argument("--run-id", required=True)

    for name in ("repair-begin", "repair-next", "repair-submit", "repair-finish"):
        repair = sub.add_parser(name, help="advance one local repair step (no provider)")
        _add_work(repair)
        repair.add_argument("--scene-id", required=True)
        repair.add_argument("--run-id", required=True)
        repair.add_argument("--repo-root", type=Path, default=Path.cwd())
        if name not in {"repair-next", "repair-finish"}:
            repair.add_argument("--model", required=True)
        if name == "repair-begin":
            repair.add_argument("--authorization", required=True,
                                help="source of the user's scoped repair request")
            repair.add_argument("--intent", choices=["auto", "explicit_deepen", "length"],
                                default="auto")
            repair.add_argument("--scope", choices=["scene", "beats"], default="scene")
            repair.add_argument("--beat-ids", help="comma-separated Beat IDs for explicit_deepen")
            repair.add_argument("--target-chars", type=int,
                                help="length adjustment target (with --intent length)")
            repair.add_argument("--tolerance", default="0.97,1.03",
                                help="lower,upper ratios of the length band")
            repair.add_argument("--length-scope", choices=["scene", "beat"], default="scene")
            repair.add_argument("--length-beat-id", help="Beat ID for --length-scope beat")
            repair.add_argument("--max-passes", type=int, default=3,
                                help="max deepen/tighten jobs, rejected ones included")
        if name == "repair-finish":
            repair.add_argument("--reason", required=True, choices=["floor_met", "author_stop"])
            repair.add_argument("--authorization", required=True,
                                help="source of the user's scoped repair stop")
        if name == "repair-submit":
            repair.add_argument("--job-id", required=True)
            result = repair.add_mutually_exclusive_group(required=True)
            result.add_argument("--candidate", type=Path)
            result.add_argument("--error", help="explicit failure, including lost job")
            repair.add_argument("--review", choices=["confirmed", "unverified", "rejected"],
                                default="unverified")
            repair.add_argument("--observations", type=Path)
            repair.add_argument("--canon-authorization",
                                help="source of the author's fact confirmation (length runs)")

    pre = sub.add_parser("canon-precheck",
                         help="show or record the author's events/text check before length adjustment")
    _add_work(pre)
    pre.add_argument("--scene-id", required=True)
    pre.add_argument("--run-id", required=True)
    pre.add_argument("--result", choices=["no_conflict", "conflict"])
    pre.add_argument("--authorization", help="source of the author's answer")

    rev = sub.add_parser("length-review",
                         help="show what the author must confirm for a pending length job")
    _add_work(rev)
    rev.add_argument("--scene-id", required=True)
    rev.add_argument("--run-id", required=True)
    rev.add_argument("--job-id", required=True)
    rev.add_argument("--candidate", type=Path, required=True)
    rev.add_argument("--repo-root", type=Path, default=Path.cwd())

    pub = sub.add_parser("publish", help="write the received candidate into _novel_text")
    _add_work(pub)
    pub.add_argument("--scene-id", required=True)
    pub.add_argument("--run-id", required=True)
    pub.add_argument("--authorization", required=True,
                     help="source of the user's scoped publish request")
    pub.add_argument("--observations", type=Path)
    pub.add_argument("--dry-run", action="store_true")
    pub.add_argument("--repo-root", type=Path, default=Path.cwd())

    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            selector = None
            if args.selector_kind or args.selector_value:
                if not args.selector_kind or not args.selector_value:
                    raise BridgeError("MISSING_FIELD", "selector-kind and selector-value must be paired")
                selector = Selector(kind=SelectorKind(args.selector_kind), value=args.selector_value)
            code, message = prepare(
                Path(args.work),
                scene_id=args.scene_id,
                text_path=args.text_path,
                request_kind=RequestKind(args.request_kind),
                model_id=args.model,
                selector=selector,
                links_path=args.links,
                repo_root=args.repo_root,
                dry_run=args.dry_run,
                allow_publish=args.allow_publish,
            )
        elif args.command == "receive":
            code, message = receive(
                Path(args.work),
                scene_id=args.scene_id,
                run_id=args.run_id,
                candidate=args.candidate,
                request_id=args.request_id,
                finish_reason=args.finish_reason,
            )
        elif args.command == "inspect":
            code, message = inspect(
                Path(args.work),
                scene_id=args.scene_id,
                run_id=args.run_id,
                observations_path=args.observations,
                marked_path=args.marked,
                repo_root=args.repo_root,
                from_run=args.from_run,
            )
        elif args.command == "publish":
            code, message = publish(
                Path(args.work),
                scene_id=args.scene_id,
                run_id=args.run_id,
                authorization=args.authorization,
                repo_root=args.repo_root,
                observations_path=args.observations,
                dry_run=args.dry_run,
            )
        elif args.command == "locate-quote":
            code, message = locate_quote_run(
                Path(args.work),
                scene_id=args.scene_id,
                run_id=args.run_id,
                quote=args.quote,
                marked_path=args.marked,
            )
        elif args.command.startswith("repair-"):
            kwargs = dict(scene_id=args.scene_id, run_id=args.run_id, repo_root=args.repo_root)
            if args.command == "repair-begin":
                beat_ids = [item.strip() for item in (args.beat_ids or "").split(",") if item.strip()]
                code, message = repair_begin(Path(args.work), model=args.model,
                    authorization=args.authorization, intent=args.intent,
                    scope=args.scope, beat_ids=beat_ids,
                    length_target=_length_target(args), **kwargs)
            elif args.command == "repair-next":
                code, message = repair_next(Path(args.work), **kwargs)
            elif args.command == "repair-finish":
                code, message = repair_finish(Path(args.work), reason=args.reason,
                    authorization=args.authorization, **kwargs)
            else:
                code, message = repair_submit(Path(args.work), job_id=args.job_id,
                    model=args.model, candidate=args.candidate, error=args.error,
                    review=args.review, observations_path=args.observations,
                    canon_authorization=args.canon_authorization, **kwargs)
        elif args.command == "canon-precheck":
            code, message = canon_precheck(Path(args.work), scene_id=args.scene_id,
                run_id=args.run_id, result=args.result, authorization=args.authorization)
        elif args.command == "length-review":
            code, message = length_review(Path(args.work), scene_id=args.scene_id,
                run_id=args.run_id, job_id=args.job_id, candidate=args.candidate,
                repo_root=args.repo_root)
        else:
            code, message = status(
                Path(args.work),
                scene_id=args.scene_id,
                run_id=args.run_id,
            )
    except BridgeError as error:
        payload = ErrorDocument.from_items([error.to_item()])
        print(payload.model_dump_json(by_alias=True, indent=2), file=sys.stderr)
        return error.exit_code
    print(message)
    return code


def _length_target(args: argparse.Namespace) -> LengthTarget | None:
    """--target-chars があるときだけ許容帯を組み立てる（無ければ beats.yaml を使う）。"""
    if args.target_chars is None:
        if args.length_beat_id or args.length_scope != "scene":
            raise BridgeError("MISSING_FIELD", "--length-scope/--length-beat-id need --target-chars")
        return None
    try:
        lower, upper = (float(item) for item in args.tolerance.split(","))
        return LengthTarget(
            target_chars=args.target_chars,
            tolerance=LengthTolerance(lower=lower, upper=upper),
            scope=args.length_scope, beat_id=args.length_beat_id, max_passes=args.max_passes)
    except ValueError as error:
        raise BridgeError("LENGTH_CONFIG", f"invalid length target: {error}") from error


def _add_work(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("work", help="novel work root")


if __name__ == "__main__":
    raise SystemExit(main())
