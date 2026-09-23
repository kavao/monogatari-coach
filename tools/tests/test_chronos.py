from __future__ import annotations

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
from chronos.graph import build_order_graph, find_cycles, topological_order
from chronos.models import ChronosMeta, Event, EventTime, IgnoreRule
from chronos.scaffold import ChronosInitError, init_chronos
from chronos.store import ChronosLoadError, load_store, write_event_file


CLI = TOOLS / "chronos_cli.py"


def _run_cli(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        cwd=cwd,
    )


def _event(
    number: int,
    *,
    after: list[str] | None = None,
    before: list[str] | None = None,
    actors: list[str] | None = None,
    location: str | None = None,
    title: str | None = None,
    ignore: list[IgnoreRule] | None = None,
) -> Event:
    event_id = f"EVT-{number:04d}"
    time = None
    if after or before:
        time = EventTime(after=after or [], before=before or [])
    meta = ChronosMeta(ignore=ignore) if ignore else None
    return Event(
        id=event_id,
        title=title or f"出来事{number}",
        actors=actors or [],
        location=location,
        time=time,
        chronos=meta,
    )


def _seed_store(tmp_path: Path, events: list[Event], *, chapter: str = "ch01.yaml") -> Path:
    novel = tmp_path / "novel"
    root = init_chronos(novel)
    write_event_file(root / "events" / chapter, events)
    return root


def test_event_requires_only_id_and_title() -> None:
    event = Event(id="EVT-0001", title="出会い")
    assert event.time is None
    assert event.actors == []


def test_ignore_requires_reason() -> None:
    with pytest.raises(ValidationError):
        IgnoreRule(rule="CHR001", reason="")


def test_order_graph_chain_has_no_cycle() -> None:
    events = [_event(index, after=[f"EVT-{index - 1:04d}"] if index > 1 else None) for index in range(1, 31)]
    graph = build_order_graph(events)
    assert find_cycles(graph) == []
    order = topological_order(graph, [event.id for event in events])
    assert order == [f"EVT-{index:04d}" for index in range(1, 31)]


def test_chr001_reports_cycle(tmp_path: Path) -> None:
    events = [
        _event(1, after=["EVT-0003"]),
        _event(2, after=["EVT-0001"]),
        _event(3, after=["EVT-0002"]),
    ]
    store = load_store(_seed_store(tmp_path, events))
    findings = check_store(store)
    assert len(findings) == 1
    assert findings[0].rule == "CHR001"
    assert findings[0].severity.value == "error"
    assert set(findings[0].events) == {"EVT-0001", "EVT-0002", "EVT-0003"}
    assert "EVT-0001" in findings[0].message


def test_chr001_suppressed_when_event_ignores(tmp_path: Path) -> None:
    ignore = [IgnoreRule(rule="CHR001", reason="意図した循環語り")]
    events = [
        _event(1, after=["EVT-0002"], ignore=ignore),
        _event(2, after=["EVT-0001"]),
    ]
    store = load_store(_seed_store(tmp_path, events))
    assert check_store(store) == []


def test_dangling_event_ref_fails_before_check(tmp_path: Path) -> None:
    events = [_event(1, after=["EVT-0099"])]
    with pytest.raises(ChronosLoadError, match="unknown event EVT-0099"):
        load_store(_seed_store(tmp_path, events))


def test_duplicate_event_id_fails(tmp_path: Path) -> None:
    root = _seed_store(tmp_path, [_event(1)])
    write_event_file(root / "events" / "ch02.yaml", [_event(1, title="重複")])
    with pytest.raises(ChronosLoadError, match="duplicate event id"):
        load_store(root)


def test_view_actor_follows_constraints(tmp_path: Path) -> None:
    events = []
    for index in range(1, 7):
        after = [f"EVT-{index - 1:04d}"] if index > 1 else None
        actors = ["CHR-hero"] if index % 2 == 0 else []
        events.append(_event(index, after=after, actors=actors))
    root = _seed_store(tmp_path, events)
    result = _run_cli("view", str(root), "--actor", "CHR-hero")
    assert result.returncode == 0, result.stderr
    assert result.stdout is not None
    lines = [line.strip() for line in result.stdout.splitlines() if line.startswith("  ")]
    assert [line.split()[1] for line in lines] == ["EVT-0002", "EVT-0004", "EVT-0006"]


def test_init_refuses_overwrite(tmp_path: Path) -> None:
    novel = tmp_path / "novel"
    init_chronos(novel)
    with pytest.raises(ChronosInitError):
        init_chronos(novel)


def test_cli_init_dry_run_does_not_write(tmp_path: Path) -> None:
    novel = tmp_path / "novel"
    result = _run_cli("init", str(novel), "--dry-run")
    assert result.returncode == 0, result.stderr
    assert "would initialize" in result.stdout
    assert not (novel / "chronos").exists()


def test_cli_init_check_ok(tmp_path: Path) -> None:
    novel = tmp_path / "novel"
    init = _run_cli("init", str(novel))
    assert init.returncode == 0, init.stderr
    events = [_event(index, after=[f"EVT-{index - 1:04d}"] if index > 1 else None) for index in range(1, 31)]
    write_event_file(novel / "chronos" / "events" / "ch01.yaml", events)
    check = _run_cli("check", str(novel))
    assert check.returncode == 0, check.stderr
    assert "0 findings" in check.stdout


def test_cli_check_cycle_exits_one(tmp_path: Path) -> None:
    events = [_event(1, after=["EVT-0002"]), _event(2, after=["EVT-0001"])]
    root = _seed_store(tmp_path, events)
    result = _run_cli("check", str(root), "--json")
    assert result.returncode == 1
    assert "CHR001" in result.stdout


def test_view_reports_chr001_when_order_is_cyclic(tmp_path: Path) -> None:
    events = [_event(1, after=["EVT-0002"]), _event(2, after=["EVT-0001"])]
    root = _seed_store(tmp_path, events)
    result = _run_cli("view", str(root), "--actor", "CHR-missing")
    # 0 events still must show that the store has a cycle.
    viewed = _run_cli("view", str(root))
    assert viewed.returncode == 1
    assert "CHR001" in viewed.stderr
    assert "order unreliable due to CHR001" in viewed.stdout
    assert result.returncode == 1
    assert "CHR001" in result.stderr


def test_metron_scene_id_is_accepted(tmp_path: Path) -> None:
    root = _seed_store(tmp_path, [_event(1)])
    (root / "scenes.yaml").write_text(
        "scenes:\n  - id: ch01-001\n    chapter: 1\n    order: 1\n    refs: [EVT-0001]\n",
        encoding="utf-8",
    )
    store = load_store(root)
    assert store.scenes[0].id == "ch01-001"
    assert store.by_scene["ch01-001"] == ["EVT-0001"]


def test_load_thousand_events_from_chapter_files(tmp_path: Path) -> None:
    """章単位ファイルなら 1000 件でも検査パスに乗せる。速度は記録のみ。"""

    novel = tmp_path / "novel"
    root = init_chronos(novel)
    for chapter in range(1, 11):
        start = (chapter - 1) * 100 + 1
        events = []
        for index in range(start, start + 100):
            after = [f"EVT-{index - 1:04d}"] if index > 1 else None
            events.append(_event(index, after=after))
        write_event_file(root / "events" / f"ch{chapter:02d}.yaml", events)
    started = time.perf_counter()
    store = load_store(root)
    findings = check_store(store)
    elapsed_ms = (time.perf_counter() - started) * 1000
    assert len(store.events) == 1000
    assert findings == []
    # 共有ドライブでは 300ms を超えることがある。失敗にはせず実測だけ残す。
    print(f"chronos P0 load+check 1000 events: {elapsed_ms:.1f} ms")
