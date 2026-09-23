from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from chronos.check import check_store
from chronos.models import (
    Character,
    CharacterStateConfig,
    ChronosConfig,
    DimensionSpec,
    Event,
    EventSource,
    EventTime,
    IllustrationBind,
    IllustrationRef,
    StateAt,
)
from chronos.scaffold import init_chronos
from chronos.store import (
    ChronosLoadError,
    load_store,
    write_character_file,
    write_config,
    write_event_file,
)


CLI = TOOLS / "chronos_cli.py"

_ILLUSTRATION_YAML = """schema_version: "1.0"
character_snapshots:
  - character_id: {character_id}
    selected_variant_id: "{variant_id}"
"""

_TAG_YAML = """character_id: {character_id}
prompt_variants:
  - variant_id: "001_normal"
  - variant_id: "002_school"
  - variant_id: "003_other"
"""


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


def _binds_for(*actors: tuple[str, str]) -> list[IllustrationBind]:
    binds: list[IllustrationBind] = []
    for actor, character_id in actors:
        binds.extend(
            [
                IllustrationBind(
                    actor=actor,
                    character_id=character_id,
                    dimension="outfit",
                    value="home",
                    variant_ids=["001_normal"],
                ),
                IllustrationBind(
                    actor=actor,
                    character_id=character_id,
                    dimension="outfit",
                    value="school",
                    variant_ids=["002_school"],
                ),
            ]
        )
    return binds


def _config(binds: list[IllustrationBind], *, chr012: str = "warning") -> ChronosConfig:
    return ChronosConfig(
        rules={"CHR012": chr012},  # type: ignore[arg-type]
        character_state=CharacterStateConfig(
            dimensions={
                "outfit": DimensionSpec(
                    type="enum",
                    values=["home", "school"],
                    default="home",
                    canon="illustration",
                )
            },
            illustration_bind=binds,
        ),
    )


def _write_page(novel: Path, name: str, character_id: str, variant_id: str) -> None:
    path = novel / "illustrations" / "pages" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        _ILLUSTRATION_YAML.format(character_id=character_id, variant_id=variant_id),
        encoding="utf-8",
    )


def _write_tag(novel: Path, character_id: str) -> None:
    path = novel / "tag" / "characters" / f"{character_id}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_TAG_YAML.format(character_id=character_id), encoding="utf-8")


def _seed(tmp_path: Path, events: list[Event], config: ChronosConfig) -> Path:
    novel = tmp_path / "novel"
    root = init_chronos(novel)
    write_event_file(root / "events" / "ch01.yaml", events)
    write_character_file(
        root / "entities" / "characters.yaml",
        [Character(id="CHR-a", name="A"), Character(id="CHR-b", name="B")],
    )
    write_config(root / "chronos.config.yaml", config)
    return root


def test_chr012_off_does_not_read_illustration_files(tmp_path: Path) -> None:
    events = [
        Event(
            id="EVT-0001",
            title="出発",
            actors=["CHR-a"],
            source=EventSource(
                illustrations=[
                    IllustrationRef(
                        path="illustrations/pages/missing.yaml",
                        character_id="actor_a",
                    )
                ]
            ),
        )
    ]
    config = _config(_binds_for(("CHR-a", "actor_a")), chr012="off")
    root = _seed(tmp_path, events, config)
    assert check_store(load_store(root)) == []


def test_chr012_mismatch_and_match(tmp_path: Path) -> None:
    novel = tmp_path / "novel"
    events = [
        Event(
            id="EVT-0001",
            title="登校",
            actors=["CHR-a"],
            effects_on={"CHR-a": {"outfit": "school"}},
            source=EventSource(
                illustrations=[
                    IllustrationRef(
                        path="illustrations/pages/page.yaml",
                        character_id="actor_a",
                        state_at=StateAt.AFTER,
                    )
                ]
            ),
        )
    ]
    root = _seed(tmp_path, events, _config(_binds_for(("CHR-a", "actor_a"))))
    _write_tag(novel, "actor_a")
    _write_page(novel, "page.yaml", "actor_a", "001_normal")
    findings = check_store(load_store(root))
    assert len(findings) == 1
    assert findings[0].rule == "CHR012"
    assert "variant=001_normal" in findings[0].message
    _write_page(novel, "page.yaml", "actor_a", "002_school")
    assert check_store(load_store(root)) == []


def test_chr012_same_variant_id_is_per_character(tmp_path: Path) -> None:
    novel = tmp_path / "novel"
    events = [
        Event(
            id="EVT-0001",
            title="同席",
            actors=["CHR-a", "CHR-b"],
            time=EventTime(after=[]),
            source=EventSource(
                illustrations=[
                    IllustrationRef(path="illustrations/pages/a.yaml", character_id="actor_a"),
                    IllustrationRef(path="illustrations/pages/b.yaml", character_id="actor_b"),
                ]
            ),
        )
    ]
    root = _seed(
        tmp_path,
        events,
        _config(_binds_for(("CHR-a", "actor_a"), ("CHR-b", "actor_b"))),
    )
    _write_tag(novel, "actor_a")
    _write_tag(novel, "actor_b")
    _write_page(novel, "a.yaml", "actor_a", "001_normal")
    _write_page(novel, "b.yaml", "actor_b", "001_normal")
    assert check_store(load_store(root)) == []


def test_chr012_before_vs_after(tmp_path: Path) -> None:
    novel = tmp_path / "novel"
    events = [
        Event(
            id="EVT-0001",
            title="着替え",
            actors=["CHR-a"],
            effects_on={"CHR-a": {"outfit": "school"}},
            source=EventSource(
                illustrations=[
                    IllustrationRef(
                        path="illustrations/pages/before.yaml",
                        character_id="actor_a",
                        state_at=StateAt.BEFORE,
                    )
                ]
            ),
        )
    ]
    root = _seed(tmp_path, events, _config(_binds_for(("CHR-a", "actor_a"))))
    _write_tag(novel, "actor_a")
    _write_page(novel, "before.yaml", "actor_a", "001_normal")
    assert check_store(load_store(root)) == []
    _write_page(novel, "before.yaml", "actor_a", "002_school")
    findings = check_store(load_store(root))
    assert findings[0].rule == "CHR012"


def test_chr012_unknown_state_is_finding_not_match(tmp_path: Path) -> None:
    novel = tmp_path / "novel"
    config = ChronosConfig(
        rules={"CHR012": "warning"},
        character_state=CharacterStateConfig(
            dimensions={
                "outfit": DimensionSpec(
                    type="enum",
                    values=["home", "school"],
                    canon="illustration",
                )
            },
            illustration_bind=_binds_for(("CHR-a", "actor_a")),
        ),
    )
    events = [
        Event(
            id="EVT-0001",
            title="不明",
            actors=["CHR-a"],
            source=EventSource(
                illustrations=[
                    IllustrationRef(path="illustrations/pages/page.yaml", character_id="actor_a")
                ]
            ),
        )
    ]
    root = _seed(tmp_path, events, config)
    _write_tag(novel, "actor_a")
    _write_page(novel, "page.yaml", "actor_a", "001_normal")
    findings = check_store(load_store(root))
    assert findings[0].rule == "CHR012"
    assert "state unknown" in findings[0].message


def test_chr012_missing_file_exits_two(tmp_path: Path) -> None:
    events = [
        Event(
            id="EVT-0001",
            title="欠落",
            actors=["CHR-a"],
            source=EventSource(
                illustrations=[
                    IllustrationRef(path="illustrations/pages/missing.yaml", character_id="actor_a")
                ]
            ),
        )
    ]
    root = _seed(tmp_path, events, _config(_binds_for(("CHR-a", "actor_a"))))
    result = _run_cli("check", str(root))
    assert result.returncode == 2
    assert "not found" in result.stderr


def test_chr012_ambiguous_snapshot_is_input_error(tmp_path: Path) -> None:
    novel = tmp_path / "novel"
    events = [
        Event(
            id="EVT-0001",
            title="曖昧",
            actors=["CHR-a"],
            source=EventSource(
                illustrations=[
                    IllustrationRef(path="illustrations/pages/page.yaml", character_id="actor_a")
                ]
            ),
        )
    ]
    root = _seed(tmp_path, events, _config(_binds_for(("CHR-a", "actor_a"))))
    _write_tag(novel, "actor_a")
    page = novel / "illustrations" / "pages" / "page.yaml"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(
        """character_snapshots:
  - character_id: actor_a
    selected_variant_id: "001_normal"
  - character_id: actor_a
    selected_variant_id: "002_school"
""",
        encoding="utf-8",
    )
    with pytest.raises(ChronosLoadError, match="ambiguous"):
        check_store(load_store(root))


def test_chr012_no_bind_does_not_run(tmp_path: Path) -> None:
    events = [
        Event(
            id="EVT-0001",
            title="無bind",
            actors=["CHR-a"],
            source=EventSource(
                illustrations=[
                    IllustrationRef(path="illustrations/pages/missing.yaml", character_id="actor_a")
                ]
            ),
        )
    ]
    config = ChronosConfig(
        rules={"CHR012": "error"},
        character_state=CharacterStateConfig(
            dimensions={
                "outfit": DimensionSpec(
                    type="enum",
                    values=["home", "school"],
                    default="home",
                    canon="illustration",
                )
            }
        ),
    )
    root = _seed(tmp_path, events, config)
    assert check_store(load_store(root)) == []


def test_chr012_link_actor_must_participate(tmp_path: Path) -> None:
    events = [
        Event(
            id="EVT-0001",
            title="別人の挿絵",
            actors=["CHR-b"],
            source=EventSource(
                illustrations=[
                    IllustrationRef(path="illustrations/pages/page.yaml", character_id="actor_a")
                ]
            ),
        )
    ]
    root = _seed(
        tmp_path,
        events,
        _config(_binds_for(("CHR-a", "actor_a"), ("CHR-b", "actor_b"))),
    )
    with pytest.raises(ChronosLoadError, match="not in actors"):
        check_store(load_store(root))
    result = _run_cli("check", str(root))
    assert result.returncode == 2
    assert "not in actors" in result.stderr
    assert "Traceback" not in result.stderr
    assert "ok:" not in result.stdout


def test_chr012_invalid_illustration_yaml_exits_two(tmp_path: Path) -> None:
    novel = tmp_path / "novel"
    events = [
        Event(
            id="EVT-0001",
            title="壊れた挿絵",
            actors=["CHR-a"],
            source=EventSource(
                illustrations=[
                    IllustrationRef(path="illustrations/pages/page.yaml", character_id="actor_a")
                ]
            ),
        )
    ]
    root = _seed(tmp_path, events, _config(_binds_for(("CHR-a", "actor_a"))))
    _write_tag(novel, "actor_a")
    page = novel / "illustrations" / "pages" / "page.yaml"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text("character_snapshots: [\n", encoding="utf-8")
    result = _run_cli("check", str(root))
    assert result.returncode == 2
    assert "invalid YAML" in result.stderr
    assert "Traceback" not in result.stderr


def test_chr012_invalid_tag_yaml_exits_two(tmp_path: Path) -> None:
    novel = tmp_path / "novel"
    events = [
        Event(
            id="EVT-0001",
            title="壊れたタグ",
            actors=["CHR-a"],
            source=EventSource(
                illustrations=[
                    IllustrationRef(path="illustrations/pages/page.yaml", character_id="actor_a")
                ]
            ),
        )
    ]
    root = _seed(tmp_path, events, _config(_binds_for(("CHR-a", "actor_a"))))
    _write_page(novel, "page.yaml", "actor_a", "001_normal")
    tag_path = novel / "tag" / "characters" / "actor_a.yaml"
    tag_path.parent.mkdir(parents=True, exist_ok=True)
    tag_path.write_text("prompt_variants: [\n", encoding="utf-8")
    result = _run_cli("check", str(root))
    assert result.returncode == 2
    assert "invalid YAML" in result.stderr
    assert "Traceback" not in result.stderr


def test_duplicate_bind_is_load_error() -> None:
    from chronos.store import _validate_bind_conflicts

    binds = _binds_for(("CHR-a", "actor_a")) + [
        IllustrationBind(
            actor="CHR-a",
            character_id="actor_a",
            dimension="outfit",
            value="home",
            variant_ids=["009_dup"],
        )
    ]
    with pytest.raises(ChronosLoadError, match="duplicate illustration_bind"):
        _validate_bind_conflicts(
            binds,
            {
                "outfit": DimensionSpec(
                    type="enum",
                    values=["home", "school"],
                    canon="illustration",
                )
            },
        )
