"""作品の抽出ゲートに基づく有効イベント選択。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .graph import build_order_graph, find_cycles, incomparable_pairs
from .models import Event, Finding, Severity


@dataclass(frozen=True)
class OrderUnconfirmed:
    scene_id: str
    event_ids: list[str]
    incomparable_pairs: list[tuple[str, str]]
    edge_count: int


@dataclass
class EventSelection:
    events: list[Event] = field(default_factory=list)
    excluded: list[Event] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    order_unconfirmed: list[OrderUnconfirmed] = field(default_factory=list)
    chapter_counts: dict[int, int] = field(default_factory=dict)
    order_edge_count: int = 0


def select_effective_events(store: Any) -> EventSelection:
    """check / view / state / scene membership share this event set."""

    gate = store.config.extract_gate
    if gate is None:
        return EventSelection(events=list(store.events))

    registered_actors = set(store.characters_by_id)
    registered_locations = set(store.locations_by_id)
    scenes = {scene.id for scene in store.scenes}
    effective: list[Event] = []
    excluded: list[Event] = []
    findings: list[Finding] = []

    for event in store.events:
        reasons: list[str] = []
        if event.review.value != "approved":
            reasons.append(f"review={event.review.value}")
        if event.type is None:
            reasons.append("type is missing")
        elif event.type not in gate.include:
            reasons.append(f"type {event.type.value!r} is outside extract_gate.include")
        if "scene" in gate.required_fields:
            if event.source is None or event.source.scene is None:
                reasons.append("source.scene is missing")
            elif event.source.scene not in scenes:
                reasons.append(f"scene {event.source.scene!r} is not registered")
        if "actors" in gate.required_fields:
            if not event.actors:
                reasons.append("actors is empty")
            elif any(actor not in registered_actors for actor in event.actors):
                unknown = sorted(set(event.actors) - registered_actors)
                reasons.append(f"unregistered actors: {', '.join(unknown)}")
        if "location" in gate.required_fields:
            if event.location is None:
                reasons.append("location is missing")
            elif event.location not in registered_locations:
                reasons.append(f"location {event.location!r} is not registered")
        if "title" in gate.required_fields and not event.title.strip():
            reasons.append("title is empty")
        if "type" in gate.required_fields and event.type is None:
            reasons.append("type is missing")
        if "time" in gate.required_fields and event.time is None:
            reasons.append("time is missing")
        if "effects_on" in gate.required_fields and not event.effects_on:
            reasons.append("effects_on is missing")
        if "causes" in gate.required_fields and not event.causes:
            reasons.append("causes is empty")
        if "effects" in gate.required_fields and not event.effects:
            reasons.append("effects is empty")

        if reasons:
            excluded.append(event)
            findings.append(
                Finding(
                    rule="CHR020",
                    severity=store.config.severity_for("CHR020", Severity.WARNING),
                    message=f"excluded from extract-gate checks: {'; '.join(dict.fromkeys(reasons))}",
                    events=[event.id],
                )
            )
        else:
            effective.append(event)

    active_ids = {event.id for event in effective}
    all_ids = {event.id for event in store.events}
    inactive_refs: dict[str, set[str]] = {}
    for event in effective:
        for ref in _event_refs(event):
            if ref in all_ids and ref not in active_ids:
                inactive_refs.setdefault(event.id, set()).add(ref)
    for scene in store.scenes:
        for ref in scene.refs:
            if ref in all_ids and ref not in active_ids:
                inactive_refs.setdefault(scene.id, set()).add(ref)
    for owner, refs in sorted(inactive_refs.items()):
        findings.append(
            Finding(
                rule="CHR021",
                severity=store.config.severity_for("CHR021", Severity.WARNING),
                message=f"references excluded event(s): {', '.join(sorted(refs))}",
                events=([owner] if owner.startswith("EVT-") else []) + sorted(refs),
            )
        )

    chapter_counts = _chapter_counts(store, effective)
    if gate.per_chapter is not None:
        chapter_numbers = {scene.chapter for scene in store.scenes if scene.chapter is not None}
        for chapter in sorted(chapter_numbers):
            count = chapter_counts.get(chapter, 0)
            if count < gate.per_chapter.min or count > gate.per_chapter.max:
                findings.append(
                    Finding(
                        rule="CHR022",
                    severity=store.config.severity_for("CHR022", Severity.WARNING),
                        message=(
                            f"chapter {chapter} has {count} effective events; "
                            f"expected {gate.per_chapter.min}..{gate.per_chapter.max}"
                        ),
                    )
                )

    result = EventSelection(
        events=effective,
        excluded=excluded,
        findings=findings,
        chapter_counts=chapter_counts,
    )
    result.order_edge_count, result.order_unconfirmed = _order_summary(store, effective)
    for item in result.order_unconfirmed:
        findings.append(
            Finding(
                rule="CHR023",
                severity=store.config.severity_for("CHR023", Severity.WARNING),
                message=(
                    f"order unconfirmed in scene {item.scene_id}: "
                    f"{len(item.incomparable_pairs)} incomparable pair(s), "
                    f"{item.edge_count} confirmed edge(s)"
                ),
                events=item.event_ids,
            )
        )
    return result


def _chapter_counts(store: Any, events: list[Event]) -> dict[int, int]:
    scene_chapters = {scene.id: scene.chapter for scene in store.scenes}
    counts: dict[int, int] = {}
    for event in events:
        scene_id = event.source.scene if event.source is not None else None
        chapter = scene_chapters.get(scene_id)
        if chapter is not None:
            counts[chapter] = counts.get(chapter, 0) + 1
    return counts


def _event_refs(event: Event) -> list[str]:
    refs: list[str] = []
    if event.time is not None:
        refs.extend(event.time.after)
        refs.extend(event.time.before)
        if event.time.offset is not None:
            refs.append(event.time.offset.from_event)
    refs.extend(event.causes)
    refs.extend(event.effects)
    return refs


def _order_summary(store: Any, events: list[Event]) -> tuple[int, list[OrderUnconfirmed]]:
    if not events:
        return 0, []
    graph = build_order_graph(events)
    edge_count = sum(len(targets) for targets in graph.successors.values())
    if find_cycles(graph):
        return edge_count, []

    by_scene: dict[str, list[str]] = {}
    for event in events:
        if event.source is not None and event.source.scene is not None:
            by_scene.setdefault(event.source.scene, []).append(event.id)
    result: list[OrderUnconfirmed] = []
    for scene_id, event_ids in sorted(by_scene.items()):
        if len(event_ids) < 2:
            continue
        pairs = incomparable_pairs(graph, event_ids)
        if not pairs:
            continue
        scene_set = set(event_ids)
        scene_edges = sum(
            1
            for source in scene_set
            for target in graph.successors.get(source, [])
            if target in scene_set
        )
        result.append(
            OrderUnconfirmed(
                scene_id=scene_id,
                event_ids=sorted(scene_set),
                incomparable_pairs=pairs,
                edge_count=scene_edges,
            )
        )
    return edge_count, result
