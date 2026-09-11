"""links と CHRONOS 場面所属の検証。所属の正は CHRONOS。"""

from __future__ import annotations

from chronos.models import SceneMode
from chronos.store import ChronosStore

from .errors import BridgeError, ErrorItem
from .models import LinksDocument, LinksStatus, SCHEMA, Severity


def scene_event_sets(store: ChronosStore, scene_id: str) -> tuple[set[str], set[str]]:
    refs: set[str] = set()
    for scene in store.scenes:
        if scene.id == scene_id:
            refs.update(scene.refs)
    sourced = {event.id for event in store.events if event.source and event.source.scene == scene_id}
    return refs, sourced


def chronos_scene_conflicts(store: ChronosStore, scene_id: str) -> list[ErrorItem]:
    errors: list[ErrorItem] = []
    refs, sourced = scene_event_sets(store, scene_id)
    if refs and sourced and refs != sourced:
        errors.append(
            ErrorItem(
                schema=SCHEMA,
                code="LINK_CONFLICT",
                severity=Severity.ERROR,
                message="source.scene and scenes.refs disagree",
                refs={
                    "scene_id": scene_id,
                    "refs": sorted(refs),
                    "sourced": sorted(sourced),
                },
            )
        )
    claimed: dict[str, list[str]] = {}
    for scene in store.scenes:
        for event_id in scene.refs:
            claimed.setdefault(event_id, []).append(scene.id)
    for event_id, scene_ids in claimed.items():
        if len(set(scene_ids)) > 1:
            errors.append(
                ErrorItem(
                    schema=SCHEMA,
                    code="LINK_CONFLICT",
                    severity=Severity.ERROR,
                    message=f"{event_id} is listed in multiple scenes.refs",
                    refs={"event_id": event_id, "scenes": scene_ids},
                )
            )
    return errors


def union_scene_events(store: ChronosStore, scene_id: str) -> set[str]:
    refs, sourced = scene_event_sets(store, scene_id)
    return refs | sourced


def validate_links(
    links: LinksDocument,
    store: ChronosStore,
    *,
    scene_id: str,
    metron_on: bool,
) -> list[ErrorItem]:
    errors = chronos_scene_conflicts(store, scene_id)
    if links.scene_id != scene_id:
        errors.append(
            ErrorItem(
                schema=SCHEMA,
                code="LINK_CONFLICT",
                severity=Severity.ERROR,
                message="links.scene_id does not match the request scene",
                refs={"links": links.scene_id, "request": scene_id},
            )
        )
    allowed = union_scene_events(store, scene_id)
    for item in links.items:
        event = store.by_id.get(item.event_id)
        if event is None:
            errors.append(
                ErrorItem(
                    schema=SCHEMA,
                    code="UNKNOWN_REF",
                    severity=Severity.ERROR,
                    message=f"unknown event {item.event_id}",
                    refs={"event_id": item.event_id},
                )
            )
            continue
        if allowed and item.event_id not in allowed:
            errors.append(
                ErrorItem(
                    schema=SCHEMA,
                    code="LINK_CONFLICT",
                    severity=Severity.ERROR,
                    message=f"{item.event_id} is not in this scene's CHRONOS membership",
                    refs={"event_id": item.event_id, "scene_id": scene_id},
                )
            )
        if event.source and event.source.scene and event.source.scene != scene_id:
            errors.append(
                ErrorItem(
                    schema=SCHEMA,
                    code="LINK_CONFLICT",
                    severity=Severity.ERROR,
                    message=f"{item.event_id} source.scene is {event.source.scene}",
                    refs={"event_id": item.event_id, "source.scene": event.source.scene},
                )
            )
        for actor_id in item.actors:
            if actor_id not in event.actors:
                errors.append(
                    ErrorItem(
                        schema=SCHEMA,
                        code="UNKNOWN_REF",
                        severity=Severity.ERROR,
                        message=f"{actor_id} does not participate in {item.event_id}",
                        refs={"event_id": item.event_id, "actor_id": actor_id},
                    )
                )
        if metron_on and links.status is LinksStatus.ADOPTED and not item.beat_id:
            errors.append(
                ErrorItem(
                    schema=SCHEMA,
                    code="MISSING_FIELD",
                    severity=Severity.ERROR,
                    message="adopted links require beat_id when METRON is ON",
                    refs={"event_id": item.event_id},
                )
            )
    if metron_on and links.status is LinksStatus.ADOPTED and not links.items:
        errors.append(
            ErrorItem(
                schema=SCHEMA,
                code="UNKNOWN_REF",
                severity=Severity.ERROR,
                message="adopted links.items is empty while CHRONOS and METRON are ON",
                refs={"scene_id": scene_id},
            )
        )
    return errors


def scene_modes(store: ChronosStore, scene_id: str) -> list[str]:
    return [scene.mode.value for scene in store.scenes if scene.id == scene_id]


def is_flashback(store: ChronosStore, scene_id: str) -> bool:
    return SceneMode.FLASHBACK in {scene.mode for scene in store.scenes if scene.id == scene_id}


def raise_if_errors(errors: list[ErrorItem]) -> None:
    fatal = [item for item in errors if item.severity is Severity.ERROR]
    if not fatal:
        return
    first = fatal[0]
    raise BridgeError(first.code, first.message, severity=first.severity, refs=first.refs)
