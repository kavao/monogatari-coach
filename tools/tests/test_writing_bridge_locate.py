from __future__ import annotations

import json
from pathlib import Path

import pytest

from test_writing_bridge import FIXTURE, ROOT, _copy_ok, _ok_observations, _prepare_ok, _run_cli
from writing_bridge.commands import inspect, receive
from writing_bridge.errors import BridgeError
from writing_bridge.hashes import range_sha256, text_sha256
from writing_bridge.locate import locate_quote, locate_quote_run
from writing_bridge.models import ArtifactRefsDocument, ObservationsDocument
from writing_bridge.storage import load_json_model


def _ready(tmp_path: Path) -> Path:
    work = _copy_ok(tmp_path)
    _prepare_ok(work)
    receive(
        work,
        scene_id="ch01-001",
        run_id="run-0001",
        candidate=work / "_metron" / "ch01-001" / "marked.md",
        request_id=None,
    )
    return work


def test_locate_quote_matches_inspect_observation_coordinates(tmp_path: Path) -> None:
    work = _ready(tmp_path)
    observations = load_json_model(_ok_observations(), ObservationsDocument)
    item = next(entry for entry in observations.items if entry.quote == "旅行用の上着")
    code, message = locate_quote_run(
        work,
        scene_id="ch01-001",
        run_id="run-0001",
        quote="旅行用の上着",
    )
    assert code == 0
    located = json.loads(message)
    assert located["start"] == item.start
    assert located["end"] == item.end
    assert located["range_sha256"] == item.range_sha256
    assert located["text_sha256"] == observations.text_sha256
    inspect_code, inspect_message = inspect(
        work,
        scene_id="ch01-001",
        run_id="run-0001",
        observations_path=_ok_observations(),
        marked_path=None,
        repo_root=ROOT,
    )
    assert inspect_code == 0, inspect_message
    observed = load_json_model(
        work / "_writing" / "ch01-001" / "run-0001" / "observations.json",
        ObservationsDocument,
    )
    matched = next(entry for entry in observed.items if entry.quote == "旅行用の上着")
    assert matched.confirmation.value == "match"
    assert matched.start == located["start"]
    assert matched.end == located["end"]


def test_locate_quote_stops_when_quote_is_duplicated(tmp_path: Path) -> None:
    work = _copy_ok(tmp_path)
    _prepare_ok(work)
    marked = work / "_metron" / "ch01-001" / "marked.md"
    original = marked.read_text(encoding="utf-8")
    assert original.count("旅行用の上着") == 1
    marked.write_text(original.replace("時刻表", "旅行用の上着", 1), encoding="utf-8")
    assert marked.read_text(encoding="utf-8").count("旅行用の上着") == 2
    receive(
        work,
        scene_id="ch01-001",
        run_id="run-0001",
        candidate=marked,
        request_id=None,
    )
    with pytest.raises(BridgeError) as caught:
        locate_quote_run(
            work,
            scene_id="ch01-001",
            run_id="run-0001",
            quote="旅行用の上着",
        )
    assert caught.value.code == "JOB_CONFLICT"
    assert "not unique" in str(caught.value)


def test_locate_quote_unknown_ref_when_missing() -> None:
    with pytest.raises(BridgeError) as caught:
        locate_quote("朝の玄関で兄は上着に袖を通した。", "旅行用の上着", text_sha256="sha256:" + "a" * 64)
    assert caught.value.code == "UNKNOWN_REF"


def test_locate_quote_core_unique_span() -> None:
    body = "朝の玄関で、兄は旅行用の上着に袖を通した。"
    digest = text_sha256(body)
    located = locate_quote(body, "旅行用の上着", text_sha256=digest)
    assert located.start == body.index("旅行用の上着")
    assert located.end == located.start + len("旅行用の上着")
    assert located.range_sha256 == range_sha256("旅行用の上着")
    assert located.text_sha256 == digest


def _received_candidate(work):
    refs = load_json_model(
        work / "_writing" / "ch01-001" / "run-0001" / "artifact_refs.json",
        ArtifactRefsDocument,
    )
    assert refs.candidate is not None
    return work / refs.candidate.path


def test_locate_quote_refuses_changed_received_candidate(tmp_path: Path) -> None:
    work = _ready(tmp_path)
    candidate = _received_candidate(work)
    candidate.write_text(candidate.read_text(encoding="utf-8") + "改変\n", encoding="utf-8")
    with pytest.raises(BridgeError) as located:
        locate_quote_run(
            work,
            scene_id="ch01-001",
            run_id="run-0001",
            quote="旅行用の上着",
        )
    assert located.value.code == "STALE_EVIDENCE"
    with pytest.raises(BridgeError) as inspected:
        inspect(
            work,
            scene_id="ch01-001",
            run_id="run-0001",
            observations_path=_ok_observations(),
            marked_path=None,
            repo_root=ROOT,
        )
    assert inspected.value.code == "STALE_EVIDENCE"


def test_locate_quote_refuses_missing_received_candidate(tmp_path: Path) -> None:
    work = _ready(tmp_path)
    candidate = _received_candidate(work)
    candidate.unlink()
    with pytest.raises(BridgeError) as located:
        locate_quote_run(
            work,
            scene_id="ch01-001",
            run_id="run-0001",
            quote="旅行用の上着",
        )
    assert located.value.code == "STALE_EVIDENCE"
    with pytest.raises(BridgeError) as inspected:
        inspect(
            work,
            scene_id="ch01-001",
            run_id="run-0001",
            observations_path=_ok_observations(),
            marked_path=None,
            repo_root=ROOT,
        )
    assert inspected.value.code == "STALE_EVIDENCE"


def test_locate_quote_refuses_changed_base_text(tmp_path: Path) -> None:
    work = _ready(tmp_path)
    novel = work / "_novel_text" / "novel_text01.md"
    novel.write_text(novel.read_text(encoding="utf-8") + "　追記。\n", encoding="utf-8")
    with pytest.raises(BridgeError) as located:
        locate_quote_run(
            work,
            scene_id="ch01-001",
            run_id="run-0001",
            quote="旅行用の上着",
        )
    assert located.value.code == "STALE_EVIDENCE"
    with pytest.raises(BridgeError) as inspected:
        inspect(
            work,
            scene_id="ch01-001",
            run_id="run-0001",
            observations_path=_ok_observations(),
            marked_path=None,
            repo_root=ROOT,
        )
    assert inspected.value.code == "STALE_EVIDENCE"


def test_cli_locate_quote(tmp_path: Path) -> None:
    work = _ready(tmp_path)
    result = _run_cli(
        "locate-quote",
        str(work),
        "--scene-id",
        "ch01-001",
        "--run-id",
        "run-0001",
        "--quote",
        "旅行用の上着",
    )
    assert result.returncode == 0, result.stderr
    located = json.loads(result.stdout)
    assert located["start"] == 22
    assert located["end"] == 28
