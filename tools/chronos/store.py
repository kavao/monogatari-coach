"""CHRONOS YAML 群のロードとメモリ上インデックス。"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .models import (
    Canon,
    Character,
    CharacterFile,
    ChronosConfig,
    DimensionSpec,
    DimensionType,
    Event,
    EventFile,
    IllustrationBind,
    Location,
    LocationFile,
    Scene,
    SceneFile,
    TransitionRule,
    is_location_id,
)
from .storage import atomic_write_model, load_yaml


class ChronosLoadError(ValueError):
    """スキーマまたは参照の解決に失敗し、検査へ進めない。"""


@dataclass
class ChronosStore:
    root: Path
    events: list[Event] = field(default_factory=list)
    characters: list[Character] = field(default_factory=list)
    locations: list[Location] = field(default_factory=list)
    scenes: list[Scene] = field(default_factory=list)
    config: ChronosConfig = field(default_factory=ChronosConfig)
    event_files: dict[str, Path] = field(default_factory=dict)
    by_id: dict[str, Event] = field(default_factory=dict)
    by_actor: dict[str, list[str]] = field(default_factory=dict)
    by_location: dict[str, list[str]] = field(default_factory=dict)
    by_scene: dict[str, list[str]] = field(default_factory=dict)
    causal_out: dict[str, list[str]] = field(default_factory=dict)
    causal_in: dict[str, list[str]] = field(default_factory=dict)
    characters_by_id: dict[str, Character] = field(default_factory=dict)
    locations_by_id: dict[str, Location] = field(default_factory=dict)
    loc_ref_dimension: str | None = None


def resolve_chronos_root(path: str | Path) -> Path:
    """作品フォルダまたは ``chronos/`` そのものを受け付ける。"""

    candidate = Path(path)
    if candidate.name == "chronos" and candidate.is_dir():
        return candidate
    nested = candidate / "chronos"
    if nested.is_dir():
        return nested
    if candidate.is_dir() and (candidate / "chronos.config.yaml").is_file():
        return candidate
    raise ChronosLoadError(f"chronos root not found: {path}")


def novel_root_for(store: ChronosStore) -> Path:
    root = store.root.resolve()
    if root.name == "chronos":
        return root.parent
    return root


def load_store(path: str | Path) -> ChronosStore:
    root = resolve_chronos_root(path)
    store = ChronosStore(root=root)
    config_path = root / "chronos.config.yaml"
    if config_path.is_file():
        store.config = ChronosConfig.model_validate(load_yaml(config_path))

    characters_path = root / "entities" / "characters.yaml"
    if characters_path.is_file():
        store.characters = CharacterFile.model_validate(
            load_yaml(characters_path)
        ).characters
    locations_path = root / "entities" / "locations.yaml"
    if locations_path.is_file():
        store.locations = LocationFile.model_validate(load_yaml(locations_path)).locations

    scenes_path = root / "scenes.yaml"
    if scenes_path.is_file():
        store.scenes = SceneFile.model_validate(load_yaml(scenes_path)).scenes

    events_dir = root / "events"
    if events_dir.is_dir():
        for yaml_path in sorted(events_dir.glob("**/*.yaml")):
            if yaml_path.name.startswith("."):
                continue
            store.events.extend(_load_event_file(yaml_path, store.event_files))

    _validate_uniqueness(store)
    _validate_event_refs(store)
    _validate_character_state(store)
    _build_indexes(store)
    return store


def write_event_file(path: str | Path, events: list[Event]) -> None:
    atomic_write_model(path, EventFile(events=events))


def write_character_file(path: str | Path, characters: list[Character]) -> None:
    atomic_write_model(path, CharacterFile(characters=characters))


def write_location_file(path: str | Path, locations: list[Location]) -> None:
    atomic_write_model(path, LocationFile(locations=locations))


def write_config(path: str | Path, config: ChronosConfig) -> None:
    atomic_write_model(path, config)


def _load_event_file(path: Path, index: dict[str, Path]) -> list[Event]:
    data = load_yaml(path)
    if not data:
        return []
    if "events" in data:
        parsed = EventFile.model_validate(data).events
    elif "id" in data:
        parsed = [Event.model_validate(data)]
    else:
        raise ChronosLoadError(f"event file must have 'events' or a single event: {path}")
    for event in parsed:
        if event.id in index:
            raise ChronosLoadError(
                f"duplicate event id {event.id}: {index[event.id]} and {path}"
            )
        index[event.id] = path
    return parsed


def _validate_uniqueness(store: ChronosStore) -> None:
    seen_chars: dict[str, str] = {}
    for character in store.characters:
        if character.id in seen_chars:
            raise ChronosLoadError(f"duplicate character id: {character.id}")
        seen_chars[character.id] = character.name
    seen_locs: dict[str, str] = {}
    for location in store.locations:
        if location.id in seen_locs:
            raise ChronosLoadError(f"duplicate location id: {location.id}")
        seen_locs[location.id] = location.name
    overlap = set(seen_chars) & set(seen_locs)
    if overlap:
        raise ChronosLoadError(f"entity id used as both character and location: {sorted(overlap)}")
    seen_scenes: set[str] = set()
    for scene in store.scenes:
        if scene.id in seen_scenes:
            raise ChronosLoadError(f"duplicate scene id: {scene.id}")
        seen_scenes.add(scene.id)
    store.characters_by_id = {character.id: character for character in store.characters}
    store.locations_by_id = {location.id: location for location in store.locations}


def _validate_event_refs(store: ChronosStore) -> None:
    event_ids = {event.id for event in store.events}
    scene_ids = {scene.id for scene in store.scenes}

    def require_event(ref: str, context: str) -> None:
        if ref not in event_ids:
            raise ChronosLoadError(f"unknown event {ref} referenced from {context}")

    for event in store.events:
        context = event.id
        time = event.time
        if time is not None:
            for ref in time.after:
                require_event(ref, f"{context}.time.after")
            for ref in time.before:
                require_event(ref, f"{context}.time.before")
            if time.offset is not None:
                require_event(time.offset.from_event, f"{context}.time.offset.from")
        for ref in event.causes:
            require_event(ref, f"{context}.causes")
        for ref in event.effects:
            require_event(ref, f"{context}.effects")
        if event.source is not None and event.source.scene is not None:
            if scene_ids and event.source.scene not in scene_ids:
                raise ChronosLoadError(
                    f"unknown scene {event.source.scene} referenced from {context}.source.scene"
                )
    for scene in store.scenes:
        for ref in scene.refs:
            require_event(ref, f"{scene.id}.refs")


def _state_payloads_present(store: ChronosStore) -> bool:
    config = store.config.character_state
    if config is not None:
        if config.transitions or config.illustration_bind:
            return True
    for character in store.characters:
        if character.initial_state:
            return True
    for event in store.events:
        if event.effects_on:
            return True
    return False


def _validate_character_state(store: ChronosStore) -> None:
    enabled = store.config.state_enabled()
    if not enabled:
        if _state_payloads_present(store):
            raise ChronosLoadError(
                "character state fields are set but character_state.dimensions is empty"
            )
        store.loc_ref_dimension = None
        return

    assert store.config.character_state is not None
    config = store.config.character_state
    dimensions = config.dimensions
    loc_dims = [name for name, spec in dimensions.items() if spec.type is DimensionType.LOC_REF]
    if len(loc_dims) > 1:
        raise ChronosLoadError(f"at most one loc_ref dimension is allowed: {sorted(loc_dims)}")
    store.loc_ref_dimension = loc_dims[0] if loc_dims else None

    for name, spec in dimensions.items():
        if spec.type is DimensionType.LOC_REF and spec.default is not None:
            _require_location(store, spec.default, f"dimensions.{name}.default")

    registered = set(store.characters_by_id)
    if not registered:
        raise ChronosLoadError("character state requires registered characters")

    for character in store.characters:
        if not character.initial_state:
            continue
        _validate_state_mapping(
            store,
            character.initial_state,
            dimensions,
            f"{character.id}.initial_state",
        )

    for bind in config.illustration_bind:
        if bind.actor not in registered:
            raise ChronosLoadError(f"illustration_bind actor is not registered: {bind.actor}")
        _validate_illustration_bind(store, bind, dimensions)

    _validate_bind_conflicts(config.illustration_bind, dimensions)
    _validate_transitions(store, config.transitions, dimensions)

    for event in store.events:
        for actor in event.actors:
            if actor not in registered:
                raise ChronosLoadError(f"unregistered actor {actor} in {event.id}")
        if store.loc_ref_dimension is not None and event.location is not None:
            _require_location(store, event.location, f"{event.id}.location")
        if not event.effects_on:
            continue
        for actor, diffs in event.effects_on.items():
            if actor not in registered:
                raise ChronosLoadError(f"effects_on actor is not registered: {actor} in {event.id}")
            if actor not in event.actors:
                raise ChronosLoadError(f"effects_on actor {actor} is not in {event.id}.actors")
            _validate_state_mapping(store, diffs, dimensions, f"{event.id}.effects_on.{actor}")


def _validate_illustration_bind(
    store: ChronosStore,
    bind: IllustrationBind,
    dimensions: dict[str, DimensionSpec],
) -> None:
    spec = dimensions.get(bind.dimension)
    if spec is None:
        raise ChronosLoadError(f"illustration_bind unknown dimension: {bind.dimension}")
    if spec.type is not DimensionType.ENUM:
        raise ChronosLoadError(
            f"illustration_bind dimension {bind.dimension} must be enum (got {spec.type.value})"
        )
    if spec.canon is not Canon.ILLUSTRATION:
        raise ChronosLoadError(
            f"illustration_bind dimension {bind.dimension} must have canon illustration"
        )
    if spec.values is None or bind.value not in spec.values:
        raise ChronosLoadError(
            f"illustration_bind value {bind.value!r} is not in {bind.dimension} values"
        )


def _validate_bind_conflicts(
    binds: list[IllustrationBind],
    dimensions: dict[str, DimensionSpec],
) -> None:
    actor_to_character: dict[str, str] = {}
    character_to_actor: dict[str, str] = {}
    seen_keys: set[tuple[str, str, str]] = set()
    variant_to_value: dict[tuple[str, str, str], str] = {}
    covered: dict[tuple[str, str], set[str]] = defaultdict(set)

    for bind in binds:
        key = (bind.actor, bind.dimension, bind.value)
        if key in seen_keys:
            raise ChronosLoadError(
                f"duplicate illustration_bind for {bind.actor}.{bind.dimension}={bind.value}"
            )
        seen_keys.add(key)
        existing_character = actor_to_character.get(bind.actor)
        if existing_character is not None and existing_character != bind.character_id:
            raise ChronosLoadError(
                f"conflicting character_id for {bind.actor}: {existing_character} vs {bind.character_id}"
            )
        actor_to_character[bind.actor] = bind.character_id
        existing_actor = character_to_actor.get(bind.character_id)
        if existing_actor is not None and existing_actor != bind.actor:
            raise ChronosLoadError(
                f"conflicting actor for character_id {bind.character_id}: {existing_actor} vs {bind.actor}"
            )
        character_to_actor[bind.character_id] = bind.actor
        for variant_id in bind.variant_ids:
            variant_key = (bind.actor, bind.dimension, variant_id)
            previous = variant_to_value.get(variant_key)
            if previous is not None and previous != bind.value:
                raise ChronosLoadError(
                    f"variant {variant_id} maps to multiple values for {bind.actor}.{bind.dimension}: "
                    f"{previous} vs {bind.value}"
                )
            variant_to_value[variant_key] = bind.value
        covered[(bind.actor, bind.dimension)].add(bind.value)

    for (actor, dimension), values in covered.items():
        spec = dimensions[dimension]
        expected = set(spec.values or [])
        missing = expected - values
        if missing:
            raise ChronosLoadError(
                f"illustration_bind for {actor}.{dimension} is missing values: {sorted(missing)}"
            )


def _validate_transitions(
    store: ChronosStore,
    transitions: list[TransitionRule],
    dimensions: dict[str, DimensionSpec],
) -> None:
    for index, rule in enumerate(transitions):
        spec = dimensions.get(rule.dimension)
        if spec is None:
            raise ChronosLoadError(f"transitions[{index}] unknown dimension: {rule.dimension}")
        context = f"transitions[{index}]"
        _validate_dimension_value(store, spec, rule.from_value, f"{context}.from")
        _validate_dimension_value(store, spec, rule.to, f"{context}.to")


def _validate_state_mapping(
    store: ChronosStore,
    mapping: dict[str, Any],
    dimensions: dict[str, DimensionSpec],
    context: str,
) -> None:
    for name, value in mapping.items():
        spec = dimensions.get(name)
        if spec is None:
            raise ChronosLoadError(f"unknown dimension {name} in {context}")
        _validate_dimension_value(store, spec, value, f"{context}.{name}")


def _validate_dimension_value(
    store: ChronosStore,
    spec: DimensionSpec,
    value: Any,
    context: str,
) -> None:
    if value is None:
        raise ChronosLoadError(f"{context}: null is not allowed")
    if spec.type is DimensionType.BOOL:
        if type(value) is not bool:
            raise ChronosLoadError(f"{context}: bool dimension requires a boolean")
        return
    if spec.type is DimensionType.ENUM:
        if type(value) is not str:
            raise ChronosLoadError(f"{context}: enum dimension requires a string")
        if spec.values is None or value not in spec.values:
            raise ChronosLoadError(f"{context}: {value!r} is not in enum values")
        return
    if spec.type is DimensionType.LOC_REF:
        if type(value) is not str or not is_location_id(value):
            raise ChronosLoadError(f"{context}: loc_ref dimension requires a LOC-* id")
        _require_location(store, value, context)
        return
    raise ChronosLoadError(f"{context}: unsupported dimension type {spec.type}")


def _require_location(store: ChronosStore, location_id: str, context: str) -> None:
    if location_id not in store.locations_by_id:
        raise ChronosLoadError(f"unknown location {location_id} referenced from {context}")


def _build_indexes(store: ChronosStore) -> None:
    store.by_id = {event.id: event for event in store.events}
    by_actor: dict[str, list[str]] = defaultdict(list)
    by_location: dict[str, list[str]] = defaultdict(list)
    by_scene: dict[str, list[str]] = defaultdict(list)
    causal_out: dict[str, list[str]] = defaultdict(list)
    causal_in: dict[str, list[str]] = defaultdict(list)
    for event in store.events:
        for actor in event.actors:
            by_actor[actor].append(event.id)
        if event.location is not None:
            by_location[event.location].append(event.id)
        if event.source is not None and event.source.scene is not None:
            by_scene[event.source.scene].append(event.id)
        for effect in event.effects:
            causal_out[event.id].append(effect)
            causal_in[effect].append(event.id)
        for cause in event.causes:
            causal_out[cause].append(event.id)
            causal_in[event.id].append(cause)
    for scene in store.scenes:
        for ref in scene.refs:
            if ref not in by_scene[scene.id]:
                by_scene[scene.id].append(ref)
    store.by_actor = dict(by_actor)
    store.by_location = dict(by_location)
    store.by_scene = dict(by_scene)
    store.causal_out = dict(causal_out)
    store.causal_in = dict(causal_in)
