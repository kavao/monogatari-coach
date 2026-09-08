from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from chronos.check import check_store
from chronos.models import (
    Character,
    CharacterFile,
    CharacterStateConfig,
    ChronosConfig,
    ChronosMeta,
    DimensionSpec,
    Event,
    EventFile,
    EventSource,
    EventTime,
    IgnoreRule,
    IllustrationBind,
    IllustrationRef,
    Location,
    TransitionRule,
)
from chronos.scaffold import init_chronos
from chronos.state import UNKNOWN, format_state_value, resolve_states
from chronos.store import (
    ChronosLoadError,
    load_store,
    write_character_file,
    write_config,
    write_event_file,
    write_location_file,
)
from chronos.storage import model_to_yaml


CLI = TOOLS / "chronos_cli.py"


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
    )


def _event(
    number: int,
    *,
    after: list[str] | None = None,
    actors: list[str] | None = None,
    location: str | None = None,
    title: str | None = None,
    effects_on: dict | None = None,
    ignore: list[IgnoreRule] | None = None,
    illustrations: list[IllustrationRef] | None = None,
) -> Event:
    time = EventTime(after=after or []) if after else None
    source = EventSource(illustrations=illustrations) if illustrations else None
    meta = ChronosMeta(ignore=ignore) if ignore else None
    return Event(
        id=f"EVT-{number:04d}",
        title=title or f"出来事{number}",
        actors=actors or ["CHR-a"],
        location=location,
        time=time,
        effects_on=effects_on,
        source=source,
        chronos=meta,
    )


def _outfit_config(**kwargs: object) -> ChronosConfig:
    transitions = kwargs.pop("transitions", None)
    binds = kwargs.pop("illustration_bind", None)
    rules = kwargs.pop("rules", None)
    extra_dimensions = kwargs.pop("dimensions", None)
    dimensions = extra_dimensions or {
        "outfit": DimensionSpec(
            type="enum",
            values=["home", "school", "travel"],
            default="home",
            canon="illustration",
        ),
        "present": DimensionSpec(type="bool", default=True, canon="world"),
    }
    return ChronosConfig(
        rules=rules or {},
        character_state=CharacterStateConfig(
            dimensions=dimensions,
            transitions=transitions or [],
            illustration_bind=binds or [],
        ),
    )


def _seed(
    tmp_path: Path,
    events: list[Event],
    *,
    config: ChronosConfig | None = None,
    characters: list[Character] | None = None,
    locations: list[Location] | None = None,
) -> Path:
    novel = tmp_path / "novel"
    root = init_chronos(novel)
    write_event_file(root / "events" / "ch01.yaml", events)
    write_character_file(
        root / "entities" / "characters.yaml",
        characters
        or [
            Character(id="CHR-a", name="A"),
            Character(id="CHR-b", name="B"),
        ],
    )
    if locations is not None:
        write_location_file(root / "entities" / "locations.yaml", locations)
    if config is not None:
        write_config(root / "chronos.config.yaml", config)
    return root


def test_state_disabled_check_matches_empty_findings(tmp_path: Path) -> None:
    events = [_event(index, after=[f"EVT-{index - 1:04d}"] if index > 1 else None) for index in range(1, 4)]
    # 人物は登録するが次元は無い。状態検査は走らない。
    root = _seed(tmp_path, events, config=ChronosConfig())
    store = load_store(root)
    assert store.config.character_state is None or not store.config.state_enabled()
    assert check_store(store) == []
    result = _run_cli("check", str(root))
    assert result.returncode == 0
    assert "0 findings" in result.stdout


def test_init_config_omits_character_state(tmp_path: Path) -> None:
    root = init_chronos(tmp_path / "novel")
    text = (root / "chronos.config.yaml").read_text(encoding="utf-8")
    assert "character_state" not in text
    assert "effects_on" not in (root / "events" / "unplaced.yaml").read_text(encoding="utf-8")


def test_old_event_yaml_roundtrip_without_state_keys(tmp_path: Path) -> None:
    event = Event(id="EVT-0001", title="出会い")
    text = model_to_yaml(EventFile(events=[event]))
    assert "effects_on" not in text
    assert "illustrations" not in text
    parsed = EventFile.model_validate({"events": [{"id": "EVT-0001", "title": "出会い"}]})
    assert parsed.events[0].effects_on is None


def test_state_roundtrip_preserves_new_keys(tmp_path: Path) -> None:
    config = _outfit_config(
        transitions=[TransitionRule(dimension="outfit", **{"from": "home", "to": "school"})],
        illustration_bind=[
            IllustrationBind(
                actor="CHR-a",
                character_id="actor_a",
                dimension="outfit",
                value="home",
                variant_ids=["001_normal"],
            ),
            IllustrationBind(
                actor="CHR-a",
                character_id="actor_a",
                dimension="outfit",
                value="school",
                variant_ids=["002_school"],
            ),
            IllustrationBind(
                actor="CHR-a",
                character_id="actor_a",
                dimension="outfit",
                value="travel",
                variant_ids=["003_travel"],
            ),
        ],
    )
    dumped = model_to_yaml(config)
    loaded = ChronosConfig.model_validate(
        __import__("yaml").safe_load(dumped)
    )
    assert loaded.character_state is not None
    assert list(loaded.character_state.dimensions) == ["outfit", "present"]
    assert loaded.character_state.transitions[0].from_value == "home"
    characters = CharacterFile(
        characters=[Character(id="CHR-a", name="A", initial_state={"outfit": "school", "present": False})]
    )
    character_dump = model_to_yaml(characters)
    assert "present: false" in character_dump
    events = EventFile(
        events=[
            _event(
                1,
                effects_on={"CHR-a": {"outfit": "home"}},
                illustrations=[
                    IllustrationRef(path="illustrations/pages/page.yaml", character_id="actor_a")
                ],
            )
        ]
    )
    event_dump = model_to_yaml(events)
    assert "effects_on:" in event_dump
    assert "illustrations:" in event_dump
    again = EventFile.model_validate(__import__("yaml").safe_load(event_dump))
    assert again.events[0].effects_on == {"CHR-a": {"outfit": "home"}}
    assert again.events[0].source is not None
    assert again.events[0].source.illustrations[0].character_id == "actor_a"


def test_view_tracks_outfit_home_to_school(tmp_path: Path) -> None:
    events = [
        _event(1, effects_on={"CHR-a": {"outfit": "school"}}),
        _event(2, after=["EVT-0001"]),
    ]
    root = _seed(tmp_path, events, config=_outfit_config())
    result = _run_cli("view", str(root), "--actor", "CHR-a")
    assert result.returncode == 0, result.stderr
    assert "outfit=home" in result.stdout
    assert "outfit=school" in result.stdout
    assert "[outfit]" in result.stdout
    store = load_store(root)
    resolved = resolve_states(store)
    first = resolved.actors["CHR-a"].events[0]
    assert first.before["outfit"] == "home"
    assert first.after["outfit"] == "school"
    assert first.before["present"] is True


def test_unknown_default_and_false_bool(tmp_path: Path) -> None:
    config = ChronosConfig(
        character_state=CharacterStateConfig(
            dimensions={
                "outfit": DimensionSpec(type="enum", values=["home", "school"], canon="world"),
                "present": DimensionSpec(type="bool", default=False, canon="world"),
            }
        )
    )
    events = [_event(1, effects_on={"CHR-a": {"outfit": "home"}})]
    root = _seed(
        tmp_path,
        events,
        config=config,
        characters=[Character(id="CHR-a", name="A"), Character(id="CHR-b", name="B")],
    )
    resolved = resolve_states(load_store(root))
    first = resolved.actors["CHR-a"].events[0]
    assert first.before["outfit"] is UNKNOWN
    assert first.after["outfit"] == "home"
    assert first.before["present"] is False
    assert format_state_value(UNKNOWN) == "unknown"


def test_initial_state_overrides_default(tmp_path: Path) -> None:
    events = [_event(1)]
    root = _seed(
        tmp_path,
        events,
        config=_outfit_config(),
        characters=[
            Character(id="CHR-a", name="A", initial_state={"outfit": "school"}),
            Character(id="CHR-b", name="B"),
        ],
    )
    first = resolve_states(load_store(root)).actors["CHR-a"].events[0]
    assert first.before["outfit"] == "school"


def test_chr013_skips_incomparable_actor_but_resolves_other(tmp_path: Path) -> None:
    events = [
        _event(1, actors=["CHR-a"]),
        _event(2, actors=["CHR-a"]),
        _event(3, actors=["CHR-b"]),
        _event(4, after=["EVT-0003"], actors=["CHR-b"]),
    ]
    root = _seed(tmp_path, events, config=_outfit_config())
    store = load_store(root)
    findings = check_store(store)
    assert any(item.rule == "CHR013" for item in findings)
    resolved = resolve_states(store)
    assert resolved.actors["CHR-a"].skip_reason == "CHR013"
    assert resolved.actors["CHR-a"].events is None
    assert resolved.actors["CHR-b"].events is not None
    result = _run_cli("view", str(root), "--actor", "CHR-a")
    assert result.returncode == 1
    assert "state unresolved due to CHR013" in result.stdout


def test_chr013_stable_across_file_order(tmp_path: Path) -> None:
    events_first = [_event(2, actors=["CHR-a"]), _event(1, actors=["CHR-a"])]
    events_second = [_event(1, actors=["CHR-a"]), _event(2, actors=["CHR-a"])]
    root_a = _seed(tmp_path / "a", events_first, config=_outfit_config())
    root_b = _seed(tmp_path / "b", events_second, config=_outfit_config())
    left = [item.message for item in check_store(load_store(root_a)) if item.rule == "CHR013"]
    right = [item.message for item in check_store(load_store(root_b)) if item.rule == "CHR013"]
    assert left == right
    assert "EVT-0001 ? EVT-0002" in left[0]


def test_chr013_ignore_hides_finding_but_does_not_resolve(tmp_path: Path) -> None:
    ignore = [IgnoreRule(rule="CHR013", reason="並びは後で足す")]
    events = [
        _event(1, actors=["CHR-a"], ignore=ignore),
        _event(2, actors=["CHR-a"]),
    ]
    root = _seed(tmp_path, events, config=_outfit_config())
    store = load_store(root)
    assert check_store(store) == []
    assert resolve_states(store).actors["CHR-a"].events is None


def test_cycle_skips_all_state_even_if_chr001_ignored(tmp_path: Path) -> None:
    ignore = [IgnoreRule(rule="CHR001", reason="循環語り")]
    events = [
        _event(1, after=["EVT-0002"], ignore=ignore, effects_on={"CHR-a": {"outfit": "school"}}),
        _event(2, after=["EVT-0001"]),
    ]
    root = _seed(tmp_path, events, config=_outfit_config())
    store = load_store(root)
    assert check_store(store) == []
    resolved = resolve_states(store)
    assert resolved.skipped_all
    assert resolved.actors["CHR-a"].events is None
    viewed = _run_cli("view", str(root), "--actor", "CHR-a")
    assert viewed.returncode == 0
    assert "order unreliable due to cycle" in viewed.stdout
    assert "state unresolved due to cycle" in viewed.stdout
    assert "outfit=school" not in viewed.stdout


def test_self_loop_skips_state(tmp_path: Path) -> None:
    events = [_event(1, after=["EVT-0001"])]
    root = _seed(tmp_path, events, config=_outfit_config())
    store = load_store(root)
    assert any(item.rule == "CHR001" for item in check_store(store))
    assert resolve_states(store).skipped_all


def test_chr010_illegal_keeps_recorded_after(tmp_path: Path) -> None:
    config = _outfit_config(
        transitions=[
            TransitionRule(dimension="outfit", **{"from": "home", "to": "school"}),
            TransitionRule(dimension="outfit", **{"from": "school", "to": "home"}),
        ]
    )
    events = [
        _event(1, effects_on={"CHR-a": {"outfit": "travel"}}),
        _event(2, after=["EVT-0001"], effects_on={"CHR-a": {"outfit": "school"}}),
    ]
    root = _seed(tmp_path, events, config=config)
    store = load_store(root)
    findings = check_store(store)
    assert [item.rule for item in findings] == ["CHR010", "CHR010"]
    resolved = resolve_states(store)
    first, second = resolved.actors["CHR-a"].events
    assert first.after["outfit"] == "travel"
    assert second.before["outfit"] == "travel"
    assert second.after["outfit"] == "school"


def test_chr010_empty_table_allows_any_change(tmp_path: Path) -> None:
    events = [_event(1, effects_on={"CHR-a": {"outfit": "travel"}})]
    root = _seed(tmp_path, events, config=_outfit_config(transitions=[]))
    assert check_store(load_store(root)) == []


def test_chr010_same_value_and_unknown_first_ok(tmp_path: Path) -> None:
    config = ChronosConfig(
        character_state=CharacterStateConfig(
            dimensions={
                "outfit": DimensionSpec(type="enum", values=["home", "school"], canon="world"),
            },
            transitions=[TransitionRule(dimension="outfit", **{"from": "home", "to": "school"})],
        )
    )
    events = [
        _event(1, effects_on={"CHR-a": {"outfit": "home"}}),
        _event(2, after=["EVT-0001"], effects_on={"CHR-a": {"outfit": "home"}}),
    ]
    root = _seed(tmp_path, events, config=config)
    assert check_store(load_store(root)) == []


def test_chr010_bool_and_ignore(tmp_path: Path) -> None:
    config = ChronosConfig(
        character_state=CharacterStateConfig(
            dimensions={"present": DimensionSpec(type="bool", default=True, canon="world")},
            transitions=[TransitionRule(dimension="present", **{"from": True, "to": True})],
        )
    )
    events = [
        _event(
            1,
            effects_on={"CHR-a": {"present": False}},
            ignore=[IgnoreRule(rule="CHR010", reason="例外の欠席")],
        )
    ]
    root = _seed(tmp_path, events, config=config)
    store = load_store(root)
    assert check_store(store) == []
    assert resolve_states(store).actors["CHR-a"].events[0].after["present"] is False


def test_chr011_observation_and_mismatch(tmp_path: Path) -> None:
    config = ChronosConfig(
        character_state=CharacterStateConfig(
            dimensions={
                "whereabouts": DimensionSpec(type="loc_ref", canon="world"),
            }
        )
    )
    locations = [Location(id="LOC-home", name="家"), Location(id="LOC-school", name="学校")]
    events = [
        _event(1, location="LOC-home"),
        _event(
            2,
            after=["EVT-0001"],
            location="LOC-school",
            effects_on={"CHR-a": {"whereabouts": "LOC-home"}},
        ),
        _event(3, after=["EVT-0002"]),
    ]
    root = _seed(tmp_path, events, config=config, locations=locations)
    store = load_store(root)
    findings = check_store(store)
    assert len(findings) == 1
    assert findings[0].rule == "CHR011"
    assert findings[0].severity.value == "warning"
    resolved = resolve_states(store)
    states = resolved.actors["CHR-a"].events
    assert states[0].after["whereabouts"] == "LOC-home"
    assert states[1].after["whereabouts"] == "LOC-home"
    assert states[2].after["whereabouts"] == "LOC-home"
    result = _run_cli("check", str(root))
    assert result.returncode == 0


def test_chr011_observation_is_chr010_subject(tmp_path: Path) -> None:
    config = ChronosConfig(
        character_state=CharacterStateConfig(
            dimensions={"whereabouts": DimensionSpec(type="loc_ref", default="LOC-home", canon="world")},
            transitions=[
                TransitionRule(dimension="whereabouts", **{"from": "LOC-home", "to": "LOC-home"}),
            ],
        )
    )
    locations = [Location(id="LOC-home", name="家"), Location(id="LOC-school", name="学校")]
    events = [_event(1, location="LOC-school")]
    root = _seed(tmp_path, events, config=config, locations=locations)
    findings = check_store(load_store(root))
    assert findings[0].rule == "CHR010"
    assert "LOC-home -> LOC-school" in findings[0].message


def test_unregistered_location_observation_is_load_error(tmp_path: Path) -> None:
    config = ChronosConfig(
        character_state=CharacterStateConfig(
            dimensions={"whereabouts": DimensionSpec(type="loc_ref", canon="world")}
        )
    )
    events = [_event(1, location="LOC-missing")]
    root = _seed(
        tmp_path,
        events,
        config=config,
        locations=[Location(id="LOC-home", name="家")],
    )
    with pytest.raises(ChronosLoadError, match="unknown location LOC-missing"):
        load_store(root)
    result = _run_cli("check", str(root))
    assert result.returncode == 2
    assert "LOC-missing" in result.stderr
    assert "Traceback" not in result.stderr


def test_location_without_loc_ref_need_not_be_registered(tmp_path: Path) -> None:
    events = [_event(1, location="LOC-missing")]
    store = load_store(_seed(tmp_path, events, config=_outfit_config()))
    assert store.events[0].location == "LOC-missing"
    assert check_store(store) == []


def test_effects_on_outside_actors_is_load_error(tmp_path: Path) -> None:
    events = [_event(1, actors=["CHR-a"], effects_on={"CHR-b": {"outfit": "school"}})]
    with pytest.raises(ChronosLoadError, match="not in EVT-0001.actors"):
        load_store(_seed(tmp_path, events, config=_outfit_config()))


def test_unregistered_actor_is_load_error_when_state_enabled(tmp_path: Path) -> None:
    events = [_event(1, actors=["CHR-ghost"])]
    with pytest.raises(ChronosLoadError, match="unregistered actor"):
        load_store(_seed(tmp_path, events, config=_outfit_config()))


def test_bool_integer_is_rejected(tmp_path: Path) -> None:
    events = [_event(1, effects_on={"CHR-a": {"present": 1}})]
    with pytest.raises(ChronosLoadError, match="boolean"):
        load_store(_seed(tmp_path, events, config=_outfit_config()))


def test_two_loc_ref_dimensions_rejected(tmp_path: Path) -> None:
    config = ChronosConfig(
        character_state=CharacterStateConfig(
            dimensions={
                "here": DimensionSpec(type="loc_ref", canon="world"),
                "there": DimensionSpec(type="loc_ref", canon="world"),
            }
        )
    )
    with pytest.raises(ChronosLoadError, match="at most one loc_ref"):
        load_store(_seed(tmp_path, [_event(1)], config=config))


def test_state_fields_without_dimensions_are_config_error(tmp_path: Path) -> None:
    events = [_event(1, effects_on={"CHR-a": {"outfit": "school"}})]
    with pytest.raises(ChronosLoadError, match="dimensions is empty"):
        load_store(_seed(tmp_path, events, config=ChronosConfig()))


def test_null_default_rejected() -> None:
    with pytest.raises(ValidationError):
        DimensionSpec.model_validate({"type": "enum", "values": ["home"], "default": None})


def test_warning_only_exits_zero(tmp_path: Path) -> None:
    config = ChronosConfig(
        character_state=CharacterStateConfig(
            dimensions={"whereabouts": DimensionSpec(type="loc_ref", canon="world")}
        )
    )
    locations = [Location(id="LOC-home", name="家"), Location(id="LOC-school", name="学校")]
    events = [
        _event(1, location="LOC-home", effects_on={"CHR-a": {"whereabouts": "LOC-school"}}),
    ]
    root = _seed(tmp_path, events, config=config, locations=locations)
    result = _run_cli("check", str(root), "--json")
    assert result.returncode == 0
    assert "CHR011" in result.stdout


def test_chr010_error_exits_one(tmp_path: Path) -> None:
    config = _outfit_config(
        transitions=[TransitionRule(dimension="outfit", **{"from": "home", "to": "school"})]
    )
    events = [_event(1, effects_on={"CHR-a": {"outfit": "travel"}})]
    root = _seed(tmp_path, events, config=config)
    result = _run_cli("check", str(root), "--json")
    assert result.returncode == 1
    assert "CHR010" in result.stdout


def test_view_does_not_blame_chr001_for_other_findings(tmp_path: Path) -> None:
    config = _outfit_config(
        transitions=[TransitionRule(dimension="outfit", **{"from": "home", "to": "school"})]
    )
    events = [_event(1, effects_on={"CHR-a": {"outfit": "travel"}})]
    root = _seed(tmp_path, events, config=config)
    viewed = _run_cli("view", str(root), "--actor", "CHR-a")
    assert viewed.returncode == 1
    assert "order unreliable due to CHR001" not in viewed.stdout
    assert "CHR010" in viewed.stderr


def test_check_view_do_not_write_inputs(tmp_path: Path) -> None:
    novel = tmp_path / "novel"
    root = init_chronos(novel)
    (novel / "world.md").write_text("world\n", encoding="utf-8")
    text_dir = novel / "_novel_text"
    text_dir.mkdir()
    (text_dir / "novel_text01.md").write_text("本文\n", encoding="utf-8")
    events = [_event(1, after=None, effects_on={"CHR-a": {"outfit": "school"}})]
    write_event_file(root / "events" / "ch01.yaml", events)
    write_character_file(root / "entities" / "characters.yaml", [Character(id="CHR-a", name="A")])
    write_config(root / "chronos.config.yaml", _outfit_config())

    def fingerprint() -> dict[str, str]:
        digest: dict[str, str] = {}
        for path in sorted(novel.rglob("*")):
            if path.is_file() and ".cache" not in path.parts:
                digest[str(path.relative_to(novel))] = hashlib.sha256(path.read_bytes()).hexdigest()
        return digest

    before = fingerprint()
    files_before = set(before)
    assert _run_cli("check", str(root)).returncode == 0
    assert _run_cli("view", str(root), "--actor", "CHR-a").returncode == 0
    after = fingerprint()
    assert after == before
    assert set(after) == files_before


def test_state_thousand_events_timing(tmp_path: Path) -> None:
    novel = tmp_path / "novel"
    root = init_chronos(novel)
    write_character_file(root / "entities" / "characters.yaml", [Character(id="CHR-a", name="A")])
    write_config(root / "chronos.config.yaml", _outfit_config())
    for chapter in range(1, 11):
        start = (chapter - 1) * 100 + 1
        events = []
        for index in range(start, start + 100):
            after = [f"EVT-{index - 1:04d}"] if index > 1 else None
            effects = {"CHR-a": {"outfit": "school"}} if index % 50 == 0 else None
            events.append(_event(index, after=after, effects_on=effects))
        write_event_file(root / "events" / f"ch{chapter:02d}.yaml", events)
    started = time.perf_counter()
    store = load_store(root)
    findings = check_store(store)
    resolved = resolve_states(store)
    elapsed_ms = (time.perf_counter() - started) * 1000
    assert len(store.events) == 1000
    assert findings == []
    assert resolved.actors["CHR-a"].events is not None
    assert len(resolved.actors["CHR-a"].events) == 1000
    print(f"chronos state load+check+resolve 1000 events: {elapsed_ms:.1f} ms")
