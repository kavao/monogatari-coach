"""執筆前文脈。CHRONOS の純関数だけを使い、CLI 出力は解析しない。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from chronos.state import format_state_value, is_unknown, resolve_states
from chronos.store import ChronosStore
from metron.contract import load_beat_plan, load_scene_contract
from metron.models import instruction_target_chars

from .errors import BridgeError
from .hashes import raw_sha256
from .links import union_scene_events
from .models import (
    SCHEMA,
    ContextDocument,
    ExpectedCheck,
    InputHash,
    LinkItem,
    LinksDocument,
    LinksStatus,
    Recorder,
    RequestDocument,
    Selector,
    StateAt,
)
from .paths import resolve_work_path


def peek_model_calibrated(config_path: Path, model_id: str) -> bool:
    if not config_path.is_file():
        return False
    try:
        from metron.storage import load_yaml

        models = load_yaml(config_path).get("models")
        if not isinstance(models, dict):
            return False
        raw = models.get(model_id)
        return isinstance(raw, dict) and raw.get("calibrated") is True
    except (OSError, ValueError):
        return False


def collect_input_hashes(work_root: Path, rel_paths: list[str]) -> list[InputHash]:
    hashes: list[InputHash] = []
    for rel in rel_paths:
        path = resolve_work_path(work_root, rel)
        if path.is_file():
            hashes.append(InputHash(path=rel, raw_sha256=raw_sha256(path)))
    return hashes


def build_candidate_links(
    request: RequestDocument,
    store: ChronosStore,
    selector: Selector,
    text_sha: str,
) -> LinksDocument:
    items: list[LinkItem] = []
    for event_id in sorted(union_scene_events(store, request.scene_id)):
        event = store.by_id[event_id]
        actors = list(event.actors) or []
        if not actors:
            continue
        items.append(
            LinkItem(
                event_id=event_id,
                state_at=StateAt.AFTER,
                actors=actors,
            )
        )
    return LinksDocument(
        schema=SCHEMA,
        scene_id=request.scene_id,
        text_path=request.target.text_path,
        selector=selector,
        text_sha256=text_sha,
        status=LinksStatus.CANDIDATE,
        created_by=Recorder.TOOL,
        adopted_by=Recorder.TOOL,
        items=items,
    )


def build_context(
    work_root: Path,
    request: RequestDocument,
    *,
    store: ChronosStore | None,
    links: LinksDocument | None,
    metron_root: Path | None,
    extra_hashes: list[str],
) -> ContextDocument:
    unresolved: list[dict[str, Any]] = []
    expected: list[ExpectedCheck] = []
    states: list[dict[str, Any]] = []
    beats: list[dict[str, Any]] = []
    forbidden: list[str] = []
    instruction = None
    prose = None

    if request.flags.metron.value == "ON":
        if metron_root is None or not (metron_root / "contract.yaml").is_file():
            raise BridgeError(
                "UNKNOWN_REF",
                "METRON is ON but contract.yaml is missing",
                refs={"path": "_metron/" + request.scene_id + "/contract.yaml"},
            )
        if not (metron_root / "beats.yaml").is_file():
            raise BridgeError(
                "UNKNOWN_REF",
                "METRON is ON but beats.yaml is missing",
                refs={"path": "_metron/" + request.scene_id + "/beats.yaml"},
            )
        contract = load_scene_contract(metron_root / "contract.yaml")
        plan = load_beat_plan(metron_root / "beats.yaml")
        if contract.scene.id != request.scene_id:
            raise BridgeError(
                "UNKNOWN_REF",
                "contract scene.id does not match request",
                refs={"contract": contract.scene.id, "request": request.scene_id},
            )
        forbidden = list(contract.scene.forbidden)
        instruction = instruction_target_chars(plan.generation.chars_floor)
        beats = [
            {
                "id": beat.id,
                "type": beat.type,
                "intent": beat.intent,
                "chars_hint": beat.budget.chars_hint,
            }
            for beat in plan.beats
        ]
        start = contract.scene.start_state
        end = contract.scene.end_state
        if start or end:
            prose = {
                "start_location": start.location if start else None,
                "end_location": end.location if end else None,
                "note": "散文。CHRONOS の loc_ref へ変換しない",
            }

    if request.flags.chronos.value == "ON":
        if store is None:
            raise BridgeError("UNKNOWN_REF", "CHRONOS is ON but chronos/ was not loaded")
        resolution = resolve_states(store)
        event_ids = _linked_or_scene_events(store, request.scene_id, links)
        if resolution.skipped_all:
            unresolved.append(
                {
                    "reason": resolution.skip_reason,
                    "note": "state was not invented",
                }
            )
        for event_id in sorted(event_ids):
            event = store.by_id.get(event_id)
            if event is None:
                unresolved.append({"event_id": event_id, "reason": "UNKNOWN_REF"})
                continue
            for actor_id in event.actors:
                actor = resolution.actors.get(actor_id)
                if actor is None or actor.skip_reason or actor.events is None:
                    unresolved.append(
                        {
                            "event_id": event_id,
                            "actor_id": actor_id,
                            "reason": actor.skip_reason if actor else "unresolved",
                        }
                    )
                    continue
                snapshot = next((item for item in actor.events if item.event_id == event_id), None)
                if snapshot is None:
                    unresolved.append(
                        {
                            "event_id": event_id,
                            "actor_id": actor_id,
                            "reason": "event not in resolved actor timeline",
                        }
                    )
                    continue
                states.append(
                    {
                        "event_id": event_id,
                        "actor_id": actor_id,
                        "before": {key: format_state_value(value) for key, value in snapshot.before.items()},
                        "after": {key: format_state_value(value) for key, value in snapshot.after.items()},
                        "changed": list(snapshot.changed),
                    }
                )
                explicit = (event.effects_on or {}).get(actor_id) or {}
                for name in snapshot.changed:
                    value = snapshot.after.get(name)
                    if is_unknown(value):
                        unresolved.append(
                            {
                                "event_id": event_id,
                                "actor_id": actor_id,
                                "dimension": name,
                                "reason": "unknown",
                            }
                        )
                        continue
                    if name not in explicit:
                        continue
                    expected.append(
                        ExpectedCheck(
                            event_id=event_id,
                            actor_id=actor_id,
                            dimension=name,
                            state_at=StateAt.AFTER,
                            expected_value=_json_value(value),
                        )
                    )

    return ContextDocument(
        schema=SCHEMA,
        request_id=request.request_id,
        run_id=request.run_id,
        input_hashes=collect_input_hashes(work_root, extra_hashes),
        expected_checks=expected,
        beats=beats,
        forbidden=forbidden,
        instruction_chars=instruction,
        states=states,
        unresolved=unresolved,
        prose_start_end=prose,
    )


def _linked_or_scene_events(
    store: ChronosStore,
    scene_id: str,
    links: LinksDocument | None,
) -> set[str]:
    if links and links.items:
        return {item.event_id for item in links.items}
    return union_scene_events(store, scene_id)


def _json_value(value: object) -> object:
    if isinstance(value, bool):
        return value
    return str(value)


def render_context_md(context: ContextDocument) -> str:
    lines = [
        f"# context {context.request_id}",
        "",
        f"instruction_chars: {context.instruction_chars}",
        f"expected_checks: {len(context.expected_checks)}",
        f"unresolved: {len(context.unresolved)}",
        "",
    ]
    if context.forbidden:
        lines.append("forbidden: " + ", ".join(context.forbidden))
        lines.append("")
    for beat in context.beats:
        lines.append(f"- beat {beat.get('id')}: {beat.get('intent')}")
    if context.prose_start_end:
        lines.append("")
        lines.append("prose_start_end は CHRONOS 値ではない。")
    return "\n".join(lines) + "\n"
