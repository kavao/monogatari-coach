"""writing_bridge の正規 CLI。LLM は起動しない。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .commands import inspect, prepare, receive, status
from .locate import locate_quote_run
from .publish import publish
from .repair import repair_begin, repair_next, repair_submit, repair_finish
from .errors import BridgeError, ErrorDocument
from .models import RequestKind, Selector, SelectorKind


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
            repair.add_argument("--intent", choices=["auto", "explicit_deepen"], default="auto")
            repair.add_argument("--scope", choices=["scene", "beats"], default="scene")
            repair.add_argument("--beat-ids", help="comma-separated Beat IDs for explicit_deepen")
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
                    scope=args.scope, beat_ids=beat_ids, **kwargs)
            elif args.command == "repair-next":
                code, message = repair_next(Path(args.work), **kwargs)
            elif args.command == "repair-finish":
                code, message = repair_finish(Path(args.work), reason=args.reason,
                    authorization=args.authorization, **kwargs)
            else:
                code, message = repair_submit(Path(args.work), job_id=args.job_id,
                    model=args.model, candidate=args.candidate, error=args.error,
                    review=args.review, observations_path=args.observations, **kwargs)
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


def _add_work(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("work", help="novel work root")


if __name__ == "__main__":
    raise SystemExit(main())
