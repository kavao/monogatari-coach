"""CHRONOS YAML 群のロードとメモリ上インデックス。"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from .models import (
    Character,
    CharacterFile,
    ChronosConfig,
    Event,
    EventFile,
    Location,
    LocationFile,
    Scene,
    SceneFile,
)
from .storage import load_yaml, model_to_yaml, atomic_write_text


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
    _build_indexes(store)
    return store


def write_event_file(path: str | Path, events: list[Event]) -> None:
    atomic_write_text(path, model_to_yaml(EventFile(events=events)))


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
