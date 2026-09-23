"""人物状態の畳み込み。トポロジカル順を事実の順序としては使わない。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .graph import build_order_graph, find_cycles, incomparable_pairs, order_by_reachability
from .models import Character, DimensionSpec, Event, Finding, Severity
from .store import ChronosStore


class UnknownSentinel:
    __slots__ = ()

    def __repr__(self) -> str:
        return "unknown"

    def __str__(self) -> str:
        return "unknown"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, UnknownSentinel)

    def __hash__(self) -> int:
        return hash("chronos.unknown")


UNKNOWN = UnknownSentinel()
StateValue = bool | str | UnknownSentinel

SKIP_CYCLE = "cycle"
SKIP_CHR013 = "CHR013"


@dataclass
class EventState:
    event_id: str
    before: dict[str, StateValue]
    after: dict[str, StateValue]
    changed: list[str]


@dataclass
class ActorResolution:
    actor_id: str
    events: list[EventState] | None = None
    skip_reason: str | None = None
    incomparable_pairs: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class StateIssue:
    rule: str
    message: str
    events: list[str]
    actor_id: str | None = None


@dataclass
class StateResolution:
    enabled: bool
    skipped_all: bool
    skip_reason: str | None
    loc_ref_dimension: str | None
    actors: dict[str, ActorResolution] = field(default_factory=dict)
    issues: list[StateIssue] = field(default_factory=list)
    dimension_order: list[str] = field(default_factory=list)


def is_unknown(value: object) -> bool:
    return isinstance(value, UnknownSentinel)


def format_state_value(value: object) -> str:
    if is_unknown(value):
        return "unknown"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def resolve_states(store: ChronosStore) -> StateResolution:
    if not store.config.state_enabled():
        return StateResolution(enabled=False, skipped_all=False, skip_reason=None, loc_ref_dimension=None)

    assert store.config.character_state is not None
    dimensions = store.config.character_state.dimensions
    dimension_order = list(dimensions)
    loc_dim = store.loc_ref_dimension
    graph = build_order_graph(store.events)
    resolution = StateResolution(
        enabled=True,
        skipped_all=False,
        skip_reason=None,
        loc_ref_dimension=loc_dim,
        dimension_order=dimension_order,
    )

    if find_cycles(graph):
        resolution.skipped_all = True
        resolution.skip_reason = SKIP_CYCLE
        for actor_id in sorted(store.by_actor):
            if actor_id in store.characters_by_id:
                resolution.actors[actor_id] = ActorResolution(
                    actor_id=actor_id,
                    skip_reason=SKIP_CYCLE,
                )
        return resolution

    allowed = _transition_index(store)
    for actor_id in sorted(store.by_actor):
        if actor_id not in store.characters_by_id:
            continue
        event_ids = list(store.by_actor[actor_id])
        pairs = incomparable_pairs(graph, event_ids)
        if pairs:
            resolution.actors[actor_id] = ActorResolution(
                actor_id=actor_id,
                skip_reason=SKIP_CHR013,
                incomparable_pairs=pairs,
            )
            pair_text = "; ".join(f"{left} ? {right}" for left, right in pairs)
            involved = sorted({event_id for pair in pairs for event_id in pair})
            resolution.issues.append(
                StateIssue(
                    rule="CHR013",
                    message=f"incomparable world order for {actor_id}: {pair_text}",
                    events=involved,
                    actor_id=actor_id,
                )
            )
            continue

        ordered_ids = order_by_reachability(graph, event_ids)
        current = _initial_state(store.characters_by_id[actor_id], dimensions)
        event_states: list[EventState] = []
        for event_id in ordered_ids:
            event = store.by_id[event_id]
            before = dict(current)
            after, issues = _apply_event(
                actor_id=actor_id,
                event=event,
                before=before,
                dimensions=dimensions,
                loc_dim=loc_dim,
                allowed=allowed,
            )
            resolution.issues.extend(issues)
            changed = [name for name in dimension_order if before.get(name) != after.get(name)]
            event_states.append(
                EventState(event_id=event_id, before=before, after=after, changed=changed)
            )
            current = after
        resolution.actors[actor_id] = ActorResolution(actor_id=actor_id, events=event_states)

    return resolution


def findings_from_resolution(store: ChronosStore, resolution: StateResolution) -> list[Finding]:
    findings: list[Finding] = []
    for issue in resolution.issues:
        severity = store.config.severity_for(issue.rule)
        if severity is Severity.OFF:
            continue
        if issue.rule == "CHR013":
            actor = resolution.actors.get(issue.actor_id or "")
            pairs = actor.incomparable_pairs if actor is not None else []
            remaining = [
                pair
                for pair in pairs
                if "CHR013" not in store.by_id[pair[0]].ignored_rules()
                and "CHR013" not in store.by_id[pair[1]].ignored_rules()
            ]
            if not remaining:
                continue
            pair_text = "; ".join(f"{left} ? {right}" for left, right in remaining)
            involved = sorted({event_id for pair in remaining for event_id in pair})
            findings.append(
                Finding(
                    rule="CHR013",
                    severity=severity,
                    message=f"incomparable world order for {actor.actor_id if actor else issue.actor_id}: {pair_text}",
                    events=involved,
                )
            )
            continue
        else:
            event_id = issue.events[0] if issue.events else ""
            event = store.by_id.get(event_id)
            if event is not None and issue.rule in event.ignored_rules():
                continue
        findings.append(
            Finding(
                rule=issue.rule,
                severity=severity,
                message=issue.message,
                events=issue.events,
            )
        )
    return findings


def _initial_state(character: Character, dimensions: dict[str, DimensionSpec]) -> dict[str, StateValue]:
    initial = character.initial_state or {}
    state: dict[str, StateValue] = {}
    for name, spec in dimensions.items():
        if name in initial:
            state[name] = initial[name]
        elif spec.default is not None:
            state[name] = spec.default
        else:
            state[name] = UNKNOWN
    return state


def _transition_index(store: ChronosStore) -> dict[str, set[tuple[Any, Any]]]:
    assert store.config.character_state is not None
    allowed: dict[str, set[tuple[Any, Any]]] = {}
    for rule in store.config.character_state.transitions:
        allowed.setdefault(rule.dimension, set()).add((rule.from_value, rule.to))
    return allowed


def _apply_event(
    *,
    actor_id: str,
    event: Event,
    before: dict[str, StateValue],
    dimensions: dict[str, DimensionSpec],
    loc_dim: str | None,
    allowed: dict[str, set[tuple[Any, Any]]],
) -> tuple[dict[str, StateValue], list[StateIssue]]:
    after = dict(before)
    explicit: dict[str, Any] = {}
    if event.effects_on and actor_id in event.effects_on:
        explicit = event.effects_on[actor_id]
        for name, value in explicit.items():
            after[name] = value

    issues: list[StateIssue] = []
    if loc_dim is not None:
        if loc_dim in explicit:
            if event.location is not None and event.location != explicit[loc_dim]:
                issues.append(
                    StateIssue(
                        rule="CHR011",
                        message=(
                            f"location mismatch for {actor_id}.{loc_dim}: "
                            f"event location {event.location} vs explicit {explicit[loc_dim]}"
                        ),
                        events=[event.id],
                        actor_id=actor_id,
                    )
                )
        elif event.location is not None:
            after[loc_dim] = event.location

    for name in dimensions:
        old = before[name]
        new = after[name]
        if old == new:
            continue
        if is_unknown(old):
            continue
        table = allowed.get(name)
        if not table:
            continue
        if (old, new) not in table:
            issues.append(
                StateIssue(
                    rule="CHR010",
                    message=(
                        f"illegal transition for {actor_id}.{name}: "
                        f"{format_state_value(old)} -> {format_state_value(new)}"
                    ),
                    events=[event.id],
                    actor_id=actor_id,
                )
            )
    return after, issues
