"""writing_bridge の正規 CLI。LLM は起動しない。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .commands import inspect, prepare, receive, status
from .locate import locate_quote_run
from .publish import publish
from .repair import (
    canon_check, canon_precheck, length_review, repair_begin, repair_next, repair_submit,
    repair_finish, repair_summary,
)
from .revise import strip_check, strip_record
from .errors import BridgeError, ErrorDocument
from .models import RequestKind, Selector, SelectorKind
from metron.length import DEFAULT_FINISH_MARGIN, finish_target
from metron.models import LengthTarget, LengthTolerance


def main(argv: list[str] | None = None) -> int:
    from console_io import configure_stdio_utf8

    configure_stdio_utf8()
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
            repair.add_argument("--intent",
                                choices=["auto", "explicit_deepen", "length", "contract_fix"],
                                default="auto")
            repair.add_argument("--instruction",
                                help="what the contract fix must change (with --intent contract_fix)")
            repair.add_argument("--scope", choices=["scene", "beats"], default="scene")
            repair.add_argument("--beat-ids", help="comma-separated Beat IDs for explicit_deepen")
            repair.add_argument("--target-chars", type=int,
                                help="length adjustment target (with --intent length)")
            repair.add_argument("--finish-target", type=int,
                                help="finished length after refinement; the adjustment adds a margin")
            repair.add_argument("--finish-margin", type=float, default=DEFAULT_FINISH_MARGIN,
                                help="margin for the refinement that follows (default 0.08)")
            repair.add_argument("--tolerance", default="0.97,1.03",
                                help="lower,upper ratios of the length band")
            repair.add_argument("--length-scope", choices=["scene", "beat"], default="scene")
            repair.add_argument("--length-beat-id", help="Beat ID for --length-scope beat")
            repair.add_argument("--max-passes", type=int, default=3,
                                help="max deepen/tighten/condense jobs, rejected ones included")
            repair.add_argument("--check-replaces-author", action="store_true",
                                help="accept a passing canon check instead of the author's "
                                     "confirmation (only when the user asked for it)")
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
    pre.add_argument("--authorization",
                     help="source of the author's answer, or the agent's basis with --by agent")
    pre.add_argument("--by", choices=["author", "agent"], default="author",
                     help="who compared the events with the text (agent: ask the author only on doubt)")
    pre.add_argument("--check-prompt", action="store_true",
                     help="write a prompt for a separate model check of events vs text")
    pre.add_argument("--check-result", type=Path, help="JSON answer of that check")
    pre.add_argument("--checker-model", help="model that answered the check")

    summ = sub.add_parser("repair-summary",
                          help="show the main changes once before saving, or record the answer")
    _add_work(summ)
    summ.add_argument("--scene-id", required=True)
    summ.add_argument("--run-id", required=True)
    summ.add_argument("--accept", action="store_true",
                      help="record the author's answer to the summary")
    summ.add_argument("--authorization", help="source of the author's answer")
    summ.add_argument("--refined", type=Path,
                      help="the refined draft (with Beat markers) made right after the adjustment")
    summ.add_argument("--repo-root", type=Path, default=Path.cwd())

    chk = sub.add_parser("canon-check",
                         help="write or judge the canon check of a pending length candidate")
    _add_work(chk)
    chk.add_argument("--scene-id", required=True)
    chk.add_argument("--run-id", required=True)
    chk.add_argument("--job-id", required=True)
    chk.add_argument("--candidate", type=Path, required=True)
    chk.add_argument("--result", type=Path, help="JSON answer of the check")
    chk.add_argument("--checker-model", help="model that answered the check")
    chk.add_argument("--repo-root", type=Path, default=Path.cwd())

    for name in ("strip-check", "strip-record"):
        strip = sub.add_parser(name, help="revision step: reference check / record of a deletion")
        _add_work(strip)
        strip.add_argument("--scene-id", required=True)
        target = strip.add_mutually_exclusive_group(required=True)
        target.add_argument("--episode-id")
        target.add_argument("--quote")
        if name == "strip-record":
            strip.add_argument("--reason", required=True)
            strip.add_argument("--authorization", required=True,
                               help="source of the user's approval of the revision step")

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
        elif args.command == "repair-summary":
            code, message = repair_summary(Path(args.work), scene_id=args.scene_id,
                run_id=args.run_id, repo_root=args.repo_root, accept=args.accept,
                authorization=args.authorization, refined_path=args.refined)
        elif args.command.startswith("repair-"):
            kwargs = dict(scene_id=args.scene_id, run_id=args.run_id, repo_root=args.repo_root)
            if args.command == "repair-begin":
                beat_ids = [item.strip() for item in (args.beat_ids or "").split(",") if item.strip()]
                code, message = repair_begin(Path(args.work), model=args.model,
                    authorization=args.authorization, intent=args.intent,
                    scope=args.scope, beat_ids=beat_ids,
                    length_target=_length_target(args),
                    check_replaces_author=args.check_replaces_author,
                    instruction=args.instruction, **kwargs)
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
                run_id=args.run_id, result=args.result, authorization=args.authorization,
                check_prompt=args.check_prompt, check_result=args.check_result,
                checker_model=args.checker_model, by=args.by)
        elif args.command == "canon-check":
            code, message = canon_check(Path(args.work), scene_id=args.scene_id,
                run_id=args.run_id, job_id=args.job_id, candidate=args.candidate,
                repo_root=args.repo_root, result_path=args.result,
                checker_model=args.checker_model)
        elif args.command == "strip-check":
            code, message = strip_check(Path(args.work), scene_id=args.scene_id,
                episode_id=args.episode_id, quote=args.quote)
        elif args.command == "strip-record":
            code, message = strip_record(Path(args.work), scene_id=args.scene_id,
                episode_id=args.episode_id, quote=args.quote, reason=args.reason,
                authorization=args.authorization)
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
    if args.target_chars is not None and args.finish_target is not None:
        raise BridgeError("JOB_CONFLICT", "use either --target-chars or --finish-target")
    if args.target_chars is None and args.finish_target is None:
        if args.length_beat_id or args.length_scope != "scene":
            raise BridgeError("MISSING_FIELD", "--length-scope/--length-beat-id need --target-chars")
        return None
    try:
        lower, upper = (float(item) for item in args.tolerance.split(","))
        fields = dict(tolerance=LengthTolerance(lower=lower, upper=upper),
                      scope=args.length_scope, beat_id=args.length_beat_id,
                      max_passes=args.max_passes)
        if args.finish_target is not None:
            return finish_target(args.finish_target, margin=args.finish_margin, **fields)
        return LengthTarget(target_chars=args.target_chars, **fields)
    except ValueError as error:
        raise BridgeError("LENGTH_CONFIG", f"invalid length target: {error}") from error


def _add_work(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("work", help="novel work root")


if __name__ == "__main__":
    raise SystemExit(main())
