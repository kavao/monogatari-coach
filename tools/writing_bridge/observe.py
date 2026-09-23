"""C1: 引用の機械検証。意味の証明はしない。"""

from __future__ import annotations

from chronos.state import format_state_value, resolve_states
from chronos.store import ChronosStore

from .errors import BridgeError, ErrorItem
from .hashes import range_sha256
from .models import (
    SCHEMA,
    Confirmation,
    ContextDocument,
    ExpectedCheck,
    ObservationItem,
    ObservationsDocument,
    Severity,
    StateAt,
)


def validate_observation_item(
    item: ObservationItem,
    *,
    normalized: str,
    text_sha: str,
    store: ChronosStore,
    expected: dict[tuple[str, str, str, str], ExpectedCheck],
) -> tuple[ObservationItem, list[ErrorItem]]:
    errors: list[ErrorItem] = []
    slice_text = normalized[item.start : item.end]
    if slice_text != item.quote:
        errors.append(
            ErrorItem(
                schema=SCHEMA,
                code="RANGE_MISMATCH",
                severity=Severity.ERROR,
                message="quote does not match [start, end)",
                refs={"event_id": item.event_id, "quote": item.quote},
            )
        )
    if range_sha256(item.quote) != item.range_sha256:
        errors.append(
            ErrorItem(
                schema=SCHEMA,
                code="RANGE_MISMATCH",
                severity=Severity.ERROR,
                message="range_sha256 does not match quote",
                refs={"event_id": item.event_id},
            )
        )
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
        updated = item.model_copy(update={"confirmation": Confirmation.UNCLEAR})
        return updated, errors
    if item.actor_id not in event.actors:
        errors.append(
            ErrorItem(
                schema=SCHEMA,
                code="UNKNOWN_REF",
                severity=Severity.ERROR,
                message=f"{item.actor_id} does not participate in {item.event_id}",
                refs={"event_id": item.event_id, "actor_id": item.actor_id},
            )
        )
    dims = store.config.character_state.dimensions if store.config.character_state else {}
    if item.dimension not in dims:
        errors.append(
            ErrorItem(
                schema=SCHEMA,
                code="UNKNOWN_REF",
                severity=Severity.ERROR,
                message=f"undeclared dimension {item.dimension}",
                refs={"dimension": item.dimension},
            )
        )
    evidence_ok = not any(
        error.code in {"RANGE_MISMATCH", "UNKNOWN_REF"} for error in errors
    )
    key = (item.event_id, item.actor_id, item.dimension, item.state_at.value)
    check = expected.get(key)
    confirmation = item.confirmation
    if not evidence_ok:
        confirmation = Confirmation.UNCLEAR
        updated = item.model_copy(update={"confirmation": confirmation})
        return updated, errors
    if confirmation is Confirmation.UNRECORDED:
        errors.append(_unverified(item, "unrecorded"))
    elif confirmation is Confirmation.ABSENT:
        errors.append(_unverified(item, "absent"))
    elif confirmation is Confirmation.UNCLEAR:
        errors.append(_unverified(item, "unclear"))
    elif check is not None and _same_value(item.value, check.expected_value):
        if confirmation is Confirmation.MISMATCH:
            errors.append(
                ErrorItem(
                    schema=SCHEMA,
                    code="TEXT_STATE_MISMATCH",
                    severity=Severity.ERROR,
                    message="confirmation is mismatch but value equals CHRONOS after/before",
                    refs={"event_id": item.event_id, "dimension": item.dimension},
                )
            )
        confirmation = Confirmation.MATCH
    elif check is not None:
        confirmation = Confirmation.MISMATCH
        errors.append(
            ErrorItem(
                schema=SCHEMA,
                code="TEXT_STATE_MISMATCH",
                severity=Severity.ERROR,
                message="recorded value does not match CHRONOS state",
                refs={
                    "event_id": item.event_id,
                    "dimension": item.dimension,
                    "recorded": item.value,
                    "expected": check.expected_value,
                },
            )
        )
    resolved = resolve_states(store)
    actor = resolved.actors.get(item.actor_id)
    if actor and actor.events:
        snapshot = next((row for row in actor.events if row.event_id == item.event_id), None)
        if snapshot is not None:
            source = snapshot.after if item.state_at is StateAt.AFTER else snapshot.before
            chronos_value = source.get(item.dimension)
            if chronos_value is not None and not _same_value(
                item.value, _as_json(format_state_value(chronos_value), chronos_value)
            ):
                if check is None:
                    confirmation = Confirmation.MISMATCH
                    errors.append(
                        ErrorItem(
                            schema=SCHEMA,
                            code="TEXT_STATE_MISMATCH",
                            severity=Severity.ERROR,
                            message="recorded value does not match resolved CHRONOS state",
                            refs={
                                "event_id": item.event_id,
                                "dimension": item.dimension,
                            },
                        )
                    )
    updated = item.model_copy(update={"confirmation": confirmation})
    return updated, errors


def inspect_observations(
    document: ObservationsDocument | None,
    *,
    request_id: str,
    normalized: str,
    text_sha: str,
    context: ContextDocument,
    store: ChronosStore,
) -> tuple[ObservationsDocument, list[ErrorItem]]:
    if document is not None and document.text_sha256 != text_sha:
        raise BridgeError(
            "STALE_EVIDENCE",
            "observations.text_sha256 does not match current text",
            refs={"expected": document.text_sha256, "actual": text_sha},
            exit_code=1,
        )
    expected = {
        (item.event_id, item.actor_id, item.dimension, item.state_at.value): item
        for item in context.expected_checks
    }
    errors: list[ErrorItem] = []
    items: list[ObservationItem] = []
    seen: set[tuple[str, str, str, str]] = set()
    for raw in document.items if document else []:
        updated, item_errors = validate_observation_item(
            raw,
            normalized=normalized,
            text_sha=text_sha,
            store=store,
            expected=expected,
        )
        errors.extend(item_errors)
        items.append(updated)
        seen.add((raw.event_id, raw.actor_id, raw.dimension, raw.state_at.value))
    for key, check in expected.items():
        if key in seen:
            continue
        errors.append(
            ErrorItem(
                schema=SCHEMA,
                code="TEXT_STATE_UNVERIFIED",
                severity=Severity.ERROR,
                message="required check not recorded",
                refs={
                    "event_id": check.event_id,
                    "actor_id": check.actor_id,
                    "dimension": check.dimension,
                    "state_at": check.state_at.value,
                },
            )
        )
    result = ObservationsDocument(
        schema=SCHEMA,
        request_id=request_id,
        text_sha256=text_sha,
        expected_total=len(context.expected_checks),
        items=items,
    )
    return result, errors


def _unverified(item: ObservationItem, reason: str) -> ErrorItem:
    return ErrorItem(
        schema=SCHEMA,
        code="TEXT_STATE_UNVERIFIED",
        severity=Severity.ERROR,
        message=reason,
        refs={
            "event_id": item.event_id,
            "actor_id": item.actor_id,
            "dimension": item.dimension,
        },
    )


def _same_value(left: object, right: object) -> bool:
    if isinstance(left, bool) and isinstance(right, bool):
        return left == right
    return str(left) == str(right)


def _as_json(formatted: str, original: object) -> object:
    if formatted in {"true", "false"}:
        return formatted == "true"
    return formatted
