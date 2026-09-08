"""CHRONOS の正規 CLI 実装。外部 provider は呼び出さない。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .check import check_store
from .graph import build_order_graph, events_for_actor, events_for_location, find_cycles, topological_order
from .models import Finding, Severity
from .scaffold import ChronosInitError, init_chronos, planned_paths
from .state import SKIP_CHR013, SKIP_CYCLE, format_state_value, resolve_states
from .store import ChronosLoadError, load_store


def _handle_init(args: argparse.Namespace) -> int:
    root = init_chronos(args.root, dry_run=args.dry_run)
    if args.dry_run:
        print(f"would initialize: {root}")
        for path in planned_paths(root):
            print(f"  {path}")
        return 0
    print(f"initialized: {root}")
    return 0


def _handle_check(args: argparse.Namespace) -> int:
    store = load_store(args.root)
    findings = check_store(store)
    if args.json:
        payload = [item.model_dump(mode="json") for item in findings]
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        if not findings:
            print(f"ok: {len(store.events)} events, 0 findings")
        for finding in findings:
            print(_format_finding(finding))
    if any(item.severity is Severity.ERROR for item in findings):
        return 1
    return 0


def _handle_view(args: argparse.Namespace) -> int:
    store = load_store(args.root)
    findings = check_store(store)
    graph = build_order_graph(store.events)
    has_cycle = bool(find_cycles(graph))
    preferred = [event.id for event in store.events]
    order = {event_id: index for index, event_id in enumerate(topological_order(graph, preferred))}
    if args.actor:
        selected = events_for_actor(store.events, args.actor)
        label = args.actor
    elif args.location:
        selected = events_for_location(store.events, args.location)
        label = args.location
    else:
        selected = list(store.events)
        label = "events"
    resolution = resolve_states(store) if store.config.state_enabled() else None
    actor_skip = None
    if args.actor and resolution is not None:
        actor = resolution.actors.get(args.actor)
        if actor is not None:
            actor_skip = actor.skip_reason
        elif resolution.skipped_all:
            actor_skip = SKIP_CYCLE
    if not selected:
        if findings:
            for finding in findings:
                print(_format_finding(finding), file=sys.stderr)
        print(f"{label}: 0 events")
        return _view_exit(findings)
    selected.sort(key=lambda event: order.get(event.id, 10**9))
    if findings:
        for finding in findings:
            print(_format_finding(finding), file=sys.stderr)
    notes = _view_notes(
        findings,
        has_cycle=has_cycle,
        actor_skip=actor_skip,
        state_enabled=store.config.state_enabled(),
        viewing_actor=bool(args.actor),
    )
    suffix = f"; {'; '.join(notes)}" if notes else ""
    print(f"{label} ({len(selected)} events{suffix})")
    actor_states = None
    if args.actor and resolution is not None:
        actor = resolution.actors.get(args.actor)
        if actor is not None and actor.events is not None:
            actor_states = {item.event_id: item for item in actor.events}
            dimension_order = resolution.dimension_order
    for index, event in enumerate(selected, start=1):
        print(f"  {index}. {event.id}  {event.title}")
        if actor_states is not None and event.id in actor_states:
            snapshot = actor_states[event.id]
            before = _format_state_line(snapshot.before, dimension_order)
            after = _format_state_line(snapshot.after, dimension_order)
            changed = ",".join(snapshot.changed)
            change_note = f"  [{changed}]" if changed else ""
            print(f"      before: {before}")
            print(f"      after:  {after}{change_note}")
    return _view_exit(findings)


def _view_notes(
    findings: list[Finding],
    *,
    has_cycle: bool,
    actor_skip: str | None,
    state_enabled: bool,
    viewing_actor: bool,
) -> list[str]:
    notes: list[str] = []
    has_chr001 = any(item.rule == "CHR001" for item in findings)
    if has_chr001:
        notes.append("order unreliable due to CHR001")
    elif has_cycle:
        notes.append("order unreliable due to cycle")
    if viewing_actor and state_enabled:
        if actor_skip == SKIP_CYCLE:
            notes.append("state unresolved due to cycle")
        elif actor_skip == SKIP_CHR013:
            notes.append("state unresolved due to CHR013")
    return notes


def _format_state_line(state: dict[str, object], dimension_order: list[str]) -> str:
    parts = [
        f"{name}={format_state_value(state[name])}"
        for name in dimension_order
        if name in state
    ]
    return " ".join(parts)


def _view_exit(findings: list[Finding]) -> int:
    if any(item.severity is Severity.ERROR for item in findings):
        return 1
    return 0


def _format_finding(finding: Finding) -> str:
    ids = ",".join(finding.events)
    return f"{finding.rule} {finding.severity.value}: {finding.message} [{ids}]"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="chronos", description="CHRONOS temporal and character-state lint")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init", help="create chronos/ scaffold")
    init.add_argument("root", type=Path)
    init.add_argument("--dry-run", action="store_true")
    init.set_defaults(handler=_handle_init)

    check = subparsers.add_parser("check", help="run deterministic lint (CHR001, CHR010-013)")
    check.add_argument("root", type=Path)
    check.add_argument("--json", action="store_true")
    check.set_defaults(handler=_handle_check)

    view = subparsers.add_parser("view", help="list events in constraint order")
    view.add_argument("root", type=Path)
    projection = view.add_mutually_exclusive_group()
    projection.add_argument("--actor")
    projection.add_argument("--location")
    view.set_defaults(handler=_handle_view)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.handler(args)
    except ChronosInitError as error:
        print(f"chronos: {error}", file=sys.stderr)
        return 2
    except (OSError, ValueError, ChronosLoadError) as error:
        print(f"chronos: {error}", file=sys.stderr)
        return 2
