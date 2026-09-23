"""CHR012: 挿絵 IR の selected_variant_id と状態値の照合。読取専用。"""

from __future__ import annotations

from pathlib import Path

from .models import Canon, DimensionType, Finding, IllustrationBind, Severity, StateAt
from .state import StateResolution, format_state_value, is_unknown
from .store import ChronosLoadError, ChronosStore, novel_root_for
from .storage import load_yaml


def chr012_active(store: ChronosStore) -> bool:
    if store.config.severity_for("CHR012") is Severity.OFF:
        return False
    config = store.config.character_state
    return config is not None and bool(config.illustration_bind)


def check_chr012(store: ChronosStore, resolution: StateResolution) -> list[Finding]:
    if not chr012_active(store):
        return []
    assert store.config.character_state is not None
    binds = store.config.character_state.illustration_bind
    actor_by_character = {bind.character_id: bind.actor for bind in binds}
    allowed = _variant_index(binds)
    findings: list[Finding] = []
    severity = store.config.severity_for("CHR012")
    novel_root = novel_root_for(store)
    pages_root = (novel_root / "illustrations" / "pages").resolve()

    for event in store.events:
        if event.source is None or not event.source.illustrations:
            continue
        for link in event.source.illustrations:
            actor_id = actor_by_character.get(link.character_id)
            if actor_id is None:
                raise ChronosLoadError(
                    f"{event.id}: illustration character_id {link.character_id} has no illustration_bind"
                )
            if actor_id not in event.actors:
                raise ChronosLoadError(
                    f"{event.id}: illustration character_id {link.character_id} maps to {actor_id} "
                    "who is not in actors"
                )
            actor_resolution = resolution.actors.get(actor_id)
            path = _resolve_illustration_path(novel_root, pages_root, link.path)
            variant_id = _selected_variant(path, link.character_id)
            _require_known_variant(novel_root, link.character_id, variant_id, event.id)
            if (
                actor_resolution is None
                or actor_resolution.events is None
                or resolution.skipped_all
                or actor_resolution.skip_reason
            ):
                continue
            if "CHR012" in event.ignored_rules():
                continue
            snapshot = next(
                (item for item in actor_resolution.events if item.event_id == event.id),
                None,
            )
            if snapshot is None:
                continue
            state = snapshot.before if link.state_at is StateAt.BEFORE else snapshot.after
            findings.extend(
                _match_variants(
                    store=store,
                    event_id=event.id,
                    actor_id=actor_id,
                    state=state,
                    variant_id=variant_id,
                    allowed=allowed,
                    severity=severity,
                )
            )
    return findings


def _variant_index(binds: list[IllustrationBind]) -> dict[tuple[str, str, str], set[str]]:
    index: dict[tuple[str, str, str], set[str]] = {}
    for bind in binds:
        index[(bind.actor, bind.dimension, bind.value)] = set(bind.variant_ids)
    return index


def _resolve_illustration_path(novel_root: Path, pages_root: Path, relative: str) -> Path:
    candidate = (novel_root / relative).resolve()
    try:
        candidate.relative_to(pages_root)
    except ValueError as error:
        raise ChronosLoadError(
            f"illustration path escapes illustrations/pages/: {relative}"
        ) from error
    if not candidate.is_file():
        raise ChronosLoadError(f"illustration file not found: {relative}")
    return candidate


def _selected_variant(path: Path, character_id: str) -> str:
    try:
        data = load_yaml(path)
    except ValueError as error:
        raise ChronosLoadError(f"invalid illustration YAML: {path}: {error}") from error
    snapshots = data.get("character_snapshots")
    if not isinstance(snapshots, list):
        raise ChronosLoadError(f"invalid illustration YAML (character_snapshots): {path}")
    matches = [
        item
        for item in snapshots
        if isinstance(item, dict) and item.get("character_id") == character_id
    ]
    if not matches:
        raise ChronosLoadError(f"character_id {character_id} not in {path}")
    if len(matches) > 1:
        raise ChronosLoadError(f"ambiguous character_id {character_id} in {path}")
    variant = matches[0].get("selected_variant_id")
    if not variant or not isinstance(variant, str):
        raise ChronosLoadError(f"missing selected_variant_id for {character_id} in {path}")
    return variant


def _require_known_variant(novel_root: Path, character_id: str, variant_id: str, event_id: str) -> None:
    tag_path = novel_root / "tag" / "characters" / f"{character_id}.yaml"
    if not tag_path.is_file():
        raise ChronosLoadError(f"{event_id}: tag file not found for {character_id}: {tag_path}")
    try:
        data = load_yaml(tag_path)
    except ValueError as error:
        raise ChronosLoadError(f"invalid tag YAML: {tag_path}: {error}") from error
    variants = data.get("prompt_variants")
    if not isinstance(variants, list):
        raise ChronosLoadError(f"{tag_path}: prompt_variants must be a list")
    known: set[str] = set()
    for item in variants:
        if isinstance(item, dict) and isinstance(item.get("variant_id"), str):
            known.add(item["variant_id"])
    if variant_id not in known:
        raise ChronosLoadError(
            f"{event_id}: unknown variant {variant_id} for {character_id} (not in {tag_path.name})"
        )


def _match_variants(
    *,
    store: ChronosStore,
    event_id: str,
    actor_id: str,
    state: dict[str, object],
    variant_id: str,
    allowed: dict[tuple[str, str, str], set[str]],
    severity: Severity,
) -> list[Finding]:
    assert store.config.character_state is not None
    findings: list[Finding] = []
    for name, spec in store.config.character_state.dimensions.items():
        if spec.type is not DimensionType.ENUM or spec.canon is not Canon.ILLUSTRATION:
            continue
        if not any(actor == actor_id and dimension == name for actor, dimension, _value in allowed):
            continue
        value = state.get(name)
        if is_unknown(value):
            findings.append(
                Finding(
                    rule="CHR012",
                    severity=severity,
                    message=(
                        f"illustration state unknown for {actor_id}.{name}; "
                        f"cannot match variant {variant_id}"
                    ),
                    events=[event_id],
                )
            )
            continue
        if not isinstance(value, str):
            continue
        permitted = allowed.get((actor_id, name, value))
        if not permitted:
            raise ChronosLoadError(
                f"{event_id}: no illustration_bind for known value {actor_id}.{name}={value}"
            )
        if variant_id not in permitted:
            findings.append(
                Finding(
                    rule="CHR012",
                    severity=severity,
                    message=(
                        f"illustration variant mismatch for {actor_id}.{name}: "
                        f"state={format_state_value(value)} variant={variant_id} "
                        f"allowed=[{', '.join(sorted(permitted))}]"
                    ),
                    events=[event_id],
                )
            )
    return findings
