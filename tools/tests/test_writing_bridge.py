from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
FIXTURE = ROOT / "tools" / "fixtures" / "writing_bridge"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from writing_bridge.commands import inspect, prepare, receive, status
from writing_bridge.errors import BridgeError
from writing_bridge.hashes import EMPTY_RAW_SHA256, read_normalized, text_sha256
from writing_bridge.models import RequestKind, Selector, SelectorKind
from writing_bridge.storage import load_json_model, load_model
from writing_bridge.models import (
    ArtifactRefsDocument,
    ContextDocument,
    ObservationsDocument,
    ReportDocument,
    RequestDocument,
)

CLI = TOOLS / "writing_bridge_cli.py"


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
        cwd=cwd or ROOT,
    )


def _copy_ok(tmp_path: Path) -> Path:
    dest = tmp_path / "000_neutral_trip"
    shutil.copytree(FIXTURE / "ok_ch01_001" / "work", dest)
    writing = dest / "_writing"
    if writing.exists():
        shutil.rmtree(writing)
    return dest


def test_both_off_does_not_create_run(tmp_path: Path) -> None:
    work = tmp_path / "off"
    (work / "_novel_text").mkdir(parents=True)
    (work / "_novel_text" / "novel_text01.md").write_text("　本文\n", encoding="utf-8")
    (work / "config.md").write_text(
        "# x\n\n## 基本情報\n\n| 項目 | 内容 |\n|------|------|\n| METRON | OFF |\n| CHRONOS | OFF |\n",
        encoding="utf-8",
    )
    code, message = prepare(
        work,
        scene_id="ch01-001",
        text_path="_novel_text/novel_text01.md",
        request_kind=RequestKind.NEW,
        model_id="local-writer",
        selector=None,
        links_path=None,
        repo_root=ROOT,
    )
    assert code == 0
    assert "skipped" in message
    assert not (work / "_writing").exists()


def test_prepare_inspect_ok_does_not_rewrite_text(tmp_path: Path) -> None:
    work = _copy_ok(tmp_path)
    text = work / "_novel_text" / "novel_text01.md"
    before = text.read_bytes()
    code, message = prepare(
        work,
        scene_id="ch01-001",
        text_path="_novel_text/novel_text01.md",
        request_kind=RequestKind.NEW,
        model_id="local-writer",
        selector=Selector(kind=SelectorKind.HEADING, value="第一章　駅までの道"),
        links_path=None,
        repo_root=ROOT,
    )
    assert code == 0
    run = work / "_writing" / "ch01-001" / "run-0001"
    request = load_model(run / "request.yaml", RequestDocument)
    context = load_json_model(run / "context.json", ContextDocument)
    assert request.flags.metron.value == "ON"
    assert request.flags.chronos.value == "ON"
    assert context.expected_checks
    assert context.prose_start_end is not None
    assert "LOC-home" not in str(context.prose_start_end.get("start_location"))
    receive_code, _ = receive(
        work,
        scene_id="ch01-001",
        run_id="run-0001",
        candidate=work / "_metron" / "ch01-001" / "marked.md",
        request_id=request.request_id,
    )
    assert receive_code == 0
    observations = FIXTURE / "ok_ch01_001" / "work" / "_writing" / "ch01-001" / "run-0001" / "observations.json"
    inspect_code, inspect_message = inspect(
        work,
        scene_id="ch01-001",
        run_id="run-0001",
        observations_path=observations,
        marked_path=None,
        repo_root=ROOT,
    )
    assert inspect_code == 0, inspect_message
    observed = load_json_model(run / "observations.json", ObservationsDocument)
    assert observed.expected_total == len(context.expected_checks)
    assert all(item.confirmation.value == "match" for item in observed.items)
    assert text.read_bytes() == before
    status_code, status_text = status(work, scene_id="ch01-001", run_id="run-0001")
    assert status_code == 0
    assert "text_state: success" in status_text


def test_stale_hash_is_detected(tmp_path: Path) -> None:
    work = _copy_ok(tmp_path)
    prepare(
        work,
        scene_id="ch01-001",
        text_path="_novel_text/novel_text01.md",
        request_kind=RequestKind.NEW,
        model_id="local-writer",
        selector=Selector(kind=SelectorKind.HEADING, value="第一章　駅までの道"),
        links_path=None,
        repo_root=ROOT,
    )
    text = work / "_novel_text" / "novel_text01.md"
    text.write_text(text.read_text(encoding="utf-8") + "\n追記\n", encoding="utf-8")
    with pytest.raises(BridgeError) as caught:
        inspect(
            work,
            scene_id="ch01-001",
            run_id="run-0001",
            observations_path=None,
            marked_path=None,
            repo_root=ROOT,
        )
    assert caught.value.code == "STALE_EVIDENCE"


def test_missing_observations_are_unverified(tmp_path: Path) -> None:
    work = _copy_ok(tmp_path)
    prepare(
        work,
        scene_id="ch01-001",
        text_path="_novel_text/novel_text01.md",
        request_kind=RequestKind.NEW,
        model_id="local-writer",
        selector=Selector(kind=SelectorKind.HEADING, value="第一章　駅までの道"),
        links_path=None,
        repo_root=ROOT,
    )
    receive(
        work,
        scene_id="ch01-001",
        run_id="run-0001",
        candidate=work / "_metron" / "ch01-001" / "marked.md",
        request_id=None,
    )
    code, _ = inspect(
        work,
        scene_id="ch01-001",
        run_id="run-0001",
        observations_path=None,
        marked_path=None,
        repo_root=ROOT,
    )
    assert code == 1
    report = (work / "_writing" / "ch01-001" / "run-0001" / "report.json").read_text(encoding="utf-8")
    assert "TEXT_STATE_UNVERIFIED" in report


def test_invalid_request_unknown_key() -> None:
    with pytest.raises(ValidationError):
        RequestDocument.model_validate(
            {
                "schema": 1,
                "request_id": "WRQ-0001",
                "run_id": "run-0001",
                "work_rel": "x",
                "scene_id": "ch01-001",
                "request_kind": "Yes",
                "extra_flag": True,
                "target": {
                    "text_path": "_novel_text/novel_text01.md",
                    "base_raw_sha256": "sha256:" + ("a" * 64),
                    "base_text_sha256": "sha256:" + ("b" * 64),
                },
                "model": {"id": "local-writer", "calibrated": True},
                "permissions": {
                    "draft": True,
                    "repair": False,
                    "publish": False,
                    "event_patch": False,
                },
                "flags": {"metron": "ON", "chronos": "ON"},
            }
        )


def test_cli_prepare_dry_run(tmp_path: Path) -> None:
    work = _copy_ok(tmp_path)
    result = _run_cli(
        "prepare",
        str(work),
        "--scene-id",
        "ch01-001",
        "--text-path",
        "_novel_text/novel_text01.md",
        "--selector-kind",
        "heading",
        "--selector-value",
        "第一章　駅までの道",
        "--dry-run",
        "--repo-root",
        str(ROOT),
    )
    assert result.returncode == 0
    assert "would prepare" in result.stdout
    assert not (work / "_writing").exists()


def test_cli_receive_after_prepare_dry_run_fails(tmp_path: Path) -> None:
    work = _copy_ok(tmp_path)
    dry = _run_cli(
        "prepare",
        str(work),
        "--scene-id",
        "ch01-001",
        "--text-path",
        "_novel_text/novel_text01.md",
        "--selector-kind",
        "heading",
        "--selector-value",
        "第一章　駅までの道",
        "--dry-run",
        "--repo-root",
        str(ROOT),
    )
    assert dry.returncode == 0
    assert not (work / "_writing").exists()
    received = _run_cli(
        "receive",
        str(work),
        "--scene-id",
        "ch01-001",
        "--run-id",
        "run-0001",
        "--candidate",
        str(work / "_metron" / "ch01-001" / "marked.md"),
    )
    assert received.returncode != 0
    assert not (work / "_writing" / "ch01-001" / "run-0001" / "request.yaml").exists()


def test_cli_allow_publish_new_without_selector_fails(tmp_path: Path) -> None:
    work = _copy_ok(tmp_path)
    result = _run_cli(
        "prepare",
        str(work),
        "--scene-id",
        "ch01-001",
        "--text-path",
        "_novel_text/novel_text01.md",
        "--request-kind",
        "new",
        "--allow-publish",
        "--repo-root",
        str(ROOT),
    )
    assert result.returncode != 0
    assert "MISSING_FIELD" in result.stderr
    assert not (work / "_writing").exists()


def test_metron_only_skips_c1(tmp_path: Path) -> None:
    work = _copy_ok(tmp_path)
    config = work / "config.md"
    config.write_text(
        config.read_text(encoding="utf-8").replace("| CHRONOS | ON |", "| CHRONOS | OFF |"),
        encoding="utf-8",
    )
    prepare(
        work,
        scene_id="ch01-001",
        text_path="_novel_text/novel_text01.md",
        request_kind=RequestKind.NEW,
        model_id="local-writer",
        selector=Selector(kind=SelectorKind.HEADING, value="第一章　駅までの道"),
        links_path=None,
        repo_root=ROOT,
    )
    assert not (work / "_writing" / "ch01-001" / "run-0001" / "links.yaml").exists()
    receive(
        work,
        scene_id="ch01-001",
        run_id="run-0001",
        candidate=work / "_metron" / "ch01-001" / "marked.md",
        request_id=None,
    )
    code, _ = inspect(
        work,
        scene_id="ch01-001",
        run_id="run-0001",
        observations_path=None,
        marked_path=None,
        repo_root=ROOT,
    )
    assert code == 0
    report = (work / "_writing" / "ch01-001" / "run-0001" / "report.json").read_text(encoding="utf-8")
    assert '"text_state": "skipped"' in report
    assert '"chronos_registered": "skipped"' in report


def test_chronos_only_skips_metron(tmp_path: Path) -> None:
    work = _copy_ok(tmp_path)
    config = work / "config.md"
    config.write_text(
        config.read_text(encoding="utf-8").replace("| METRON | ON |", "| METRON | OFF |"),
        encoding="utf-8",
    )
    prepare(
        work,
        scene_id="ch01-001",
        text_path="_novel_text/novel_text01.md",
        request_kind=RequestKind.NEW,
        model_id="local-writer",
        selector=Selector(kind=SelectorKind.HEADING, value="第一章　駅までの道"),
        links_path=None,
        repo_root=ROOT,
    )
    observations = (
        FIXTURE / "ok_ch01_001" / "work" / "_writing" / "ch01-001" / "run-0001" / "observations.json"
    )
    code, _ = inspect(
        work,
        scene_id="ch01-001",
        run_id="run-0001",
        observations_path=observations,
        marked_path=None,
        repo_root=ROOT,
    )
    assert code == 0
    report = (work / "_writing" / "ch01-001" / "run-0001" / "report.json").read_text(encoding="utf-8")
    assert '"metron": "skipped"' in report


def test_normalized_hash_matches_fixture() -> None:
    novel = FIXTURE / "ok_ch01_001" / "work" / "_novel_text" / "novel_text01.md"
    marked = FIXTURE / "ok_ch01_001" / "work" / "_metron" / "ch01-001" / "marked.md"
    body = read_normalized(novel)
    assert "旅行用の上着" in body
    assert text_sha256(novel.read_text(encoding="utf-8")) == text_sha256(
        marked.read_text(encoding="utf-8")
    )


def _prepare_ok(work: Path, **kwargs) -> Path:
    defaults = dict(
        scene_id="ch01-001",
        text_path="_novel_text/novel_text01.md",
        request_kind=RequestKind.NEW,
        model_id="local-writer",
        selector=Selector(kind=SelectorKind.HEADING, value="第一章　駅までの道"),
        links_path=None,
        repo_root=ROOT,
    )
    defaults.update(kwargs)
    code, message = prepare(work, **defaults)
    assert code == 0, message
    return work / "_writing" / "ch01-001" / "run-0001"


def test_inspect_uses_received_candidate_not_novel(tmp_path: Path) -> None:
    work = _copy_ok(tmp_path)
    run = _prepare_ok(work)
    marked = (work / "_metron" / "ch01-001" / "marked.md").read_text(encoding="utf-8")
    junk = tmp_path / "unrelated.md"
    junk.write_text(marked.replace("旅行用の上着", "通学用の上着"), encoding="utf-8")
    receive(work, scene_id="ch01-001", run_id="run-0001", candidate=junk, request_id=None)
    observations = (
        FIXTURE / "ok_ch01_001" / "work" / "_writing" / "ch01-001" / "run-0001" / "observations.json"
    )
    with pytest.raises(BridgeError) as caught:
        inspect(
            work,
            scene_id="ch01-001",
            run_id="run-0001",
            observations_path=observations,
            marked_path=None,
            repo_root=ROOT,
        )
    assert caught.value.code == "STALE_EVIDENCE"
    inspect(
        work,
        scene_id="ch01-001",
        run_id="run-0001",
        observations_path=None,
        marked_path=None,
        repo_root=ROOT,
    )
    report = load_json_model(run / "report.json", ReportDocument)
    assert report.target_text_sha256 == text_sha256(junk.read_text(encoding="utf-8"))
    novel = work / "_novel_text" / "novel_text01.md"
    assert report.target_text_sha256 != text_sha256(novel.read_text(encoding="utf-8"))


def test_inspect_rebuilds_context_when_chronos_input_changes(tmp_path: Path) -> None:
    work = _copy_ok(tmp_path)
    run = _prepare_ok(work)
    before = load_json_model(run / "context.json", ContextDocument)
    assert any(
        item.dimension == "outfit" and item.expected_value == "travel"
        for item in before.expected_checks
    )
    events = work / "chronos" / "events" / "ch01.yaml"
    events.write_text(
        events.read_text(encoding="utf-8").replace("outfit: travel", "outfit: school"),
        encoding="utf-8",
    )
    receive(
        work,
        scene_id="ch01-001",
        run_id="run-0001",
        candidate=work / "_metron" / "ch01-001" / "marked.md",
        request_id=None,
    )
    observations = (
        FIXTURE / "ok_ch01_001" / "work" / "_writing" / "ch01-001" / "run-0001" / "observations.json"
    )
    code, _ = inspect(
        work,
        scene_id="ch01-001",
        run_id="run-0001",
        observations_path=observations,
        marked_path=None,
        repo_root=ROOT,
    )
    assert code == 1
    after = load_json_model(run / "context.json", ContextDocument)
    assert any(
        item.dimension == "outfit" and item.expected_value == "school"
        for item in after.expected_checks
    )
    report = load_json_model(run / "report.json", ReportDocument)
    assert report.text_state.value == "failed"
    journal = (run / "journal.jsonl").read_text(encoding="utf-8")
    assert "context rebuilt: input_hashes changed" in journal


def test_range_mismatch_does_not_count_as_text_state_success(tmp_path: Path) -> None:
    work = _copy_ok(tmp_path)
    run = _prepare_ok(work)
    receive(
        work,
        scene_id="ch01-001",
        run_id="run-0001",
        candidate=work / "_metron" / "ch01-001" / "marked.md",
        request_id=None,
    )
    source = (
        FIXTURE / "ok_ch01_001" / "work" / "_writing" / "ch01-001" / "run-0001" / "observations.json"
    )
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["items"][0]["quote"] = "違う引用"
    bad = tmp_path / "bad_observations.json"
    bad.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    code, _ = inspect(
        work,
        scene_id="ch01-001",
        run_id="run-0001",
        observations_path=bad,
        marked_path=None,
        repo_root=ROOT,
    )
    assert code == 1
    report = load_json_model(run / "report.json", ReportDocument)
    assert report.text_state.value != "success"
    observed = load_json_model(run / "observations.json", ObservationsDocument)
    first = next(item for item in observed.items if item.dimension == "outfit")
    assert first.confirmation.value != "match"


def test_prepare_new_allows_missing_text_file(tmp_path: Path) -> None:
    work = _copy_ok(tmp_path)
    run = _prepare_ok(
        work,
        text_path="_novel_text/novel_text11.md",
        selector=None,
    )
    request = load_model(run / "request.yaml", RequestDocument)
    assert request.target.base_raw_sha256 == EMPTY_RAW_SHA256
    assert request.target.base_exists is False
    assert not (work / "_novel_text" / "novel_text11.md").exists()
    context = load_json_model(run / "context.json", ContextDocument)
    assert all(item.path != "_novel_text/novel_text11.md" for item in context.input_hashes)
    with pytest.raises(BridgeError) as inspect_error:
        inspect(
            work,
            scene_id="ch01-001",
            run_id="run-0001",
            observations_path=None,
            marked_path=None,
            repo_root=ROOT,
        )
    assert inspect_error.value.code == "UNKNOWN_REF"
    with pytest.raises(BridgeError) as append_error:
        prepare(
            work,
            scene_id="ch01-001",
            text_path="_novel_text/novel_text12.md",
            request_kind=RequestKind.APPEND,
            model_id="local-writer",
            selector=None,
            links_path=None,
            repo_root=ROOT,
        )
    assert append_error.value.code == "UNKNOWN_REF"


def test_receive_keeps_versioned_candidates(tmp_path: Path) -> None:
    work = _copy_ok(tmp_path)
    run = _prepare_ok(work)
    first = work / "_metron" / "ch01-001" / "marked.md"
    second = tmp_path / "second.md"
    second.write_text(
        first.read_text(encoding="utf-8").replace("旅行用の上着", "通学用の上着"),
        encoding="utf-8",
    )
    receive(work, scene_id="ch01-001", run_id="run-0001", candidate=first, request_id=None)
    receive(work, scene_id="ch01-001", run_id="run-0001", candidate=second, request_id=None)
    receive(work, scene_id="ch01-001", run_id="run-0001", candidate=first, request_id=None)
    marked_one = work / "_metron" / "ch01-001" / "marked.001.md"
    marked_two = work / "_metron" / "ch01-001" / "marked.002.md"
    assert marked_one.is_file()
    assert marked_two.is_file()
    assert first.is_file()
    assert not (work / "_metron" / "ch01-001" / "marked.003.md").exists()
    refs = load_json_model(run / "artifact_refs.json", ArtifactRefsDocument)
    assert len(refs.candidates) == 2
    assert refs.candidate is not None
    assert refs.candidate.path.endswith("marked.001.md")
    off = _copy_ok(tmp_path / "off")
    off_config = off / "config.md"
    off_config.write_text(
        off_config.read_text(encoding="utf-8").replace("| METRON | ON |", "| METRON | OFF |"),
        encoding="utf-8",
    )
    off_run = _prepare_ok(off)
    receive(off, scene_id="ch01-001", run_id="run-0001", candidate=first, request_id=None)
    receive(off, scene_id="ch01-001", run_id="run-0001", candidate=second, request_id=None)
    assert (off_run / "candidates" / "candidate.001.md").is_file()
    assert (off_run / "candidates" / "candidate.002.md").is_file()


def test_prepare_records_state_and_link_inputs(tmp_path: Path) -> None:
    work = _copy_ok(tmp_path)
    run = _prepare_ok(work)
    context = load_json_model(run / "context.json", ContextDocument)
    paths = {item.path for item in context.input_hashes}
    assert "chronos/entities/characters.yaml" in paths
    assert "chronos/entities/locations.yaml" in paths
    assert "chronos/scenes.yaml" in paths
    assert "_writing/ch01-001/run-0001/links.yaml" in paths


def test_inspect_rebuilds_context_when_character_initial_changes(tmp_path: Path) -> None:
    work = _copy_ok(tmp_path)
    run = _prepare_ok(work)
    before = load_json_model(run / "context.json", ContextDocument)
    assert any(
        row.get("actor_id") == "CHR-a" and row.get("before", {}).get("outfit") == "home"
        for row in before.states
    )
    characters = work / "chronos" / "entities" / "characters.yaml"
    characters.write_text(
        characters.read_text(encoding="utf-8").replace(
            "  - id: CHR-a\n    name: 兄\n    initial_state:\n      outfit: home",
            "  - id: CHR-a\n    name: 兄\n    initial_state:\n      outfit: school",
            1,
        ),
        encoding="utf-8",
    )
    receive(
        work,
        scene_id="ch01-001",
        run_id="run-0001",
        candidate=work / "_metron" / "ch01-001" / "marked.md",
        request_id=None,
    )
    inspect(
        work,
        scene_id="ch01-001",
        run_id="run-0001",
        observations_path=(
            FIXTURE
            / "ok_ch01_001"
            / "work"
            / "_writing"
            / "ch01-001"
            / "run-0001"
            / "observations.json"
        ),
        marked_path=None,
        repo_root=ROOT,
    )
    after = load_json_model(run / "context.json", ContextDocument)
    assert any(
        row.get("actor_id") == "CHR-a" and row.get("before", {}).get("outfit") == "school"
        for row in after.states
    )
    journal = (run / "journal.jsonl").read_text(encoding="utf-8")
    assert "context rebuilt: input_hashes changed" in journal


def test_inspect_detects_new_text_created_after_prepare(tmp_path: Path) -> None:
    work = _copy_ok(tmp_path)
    _prepare_ok(work, text_path="_novel_text/novel_text11.md", selector=None)
    created = work / "_novel_text" / "novel_text11.md"
    created.write_text("# 第十一章\n　本文\n", encoding="utf-8")
    with pytest.raises(BridgeError) as caught:
        inspect(
            work,
            scene_id="ch01-001",
            run_id="run-0001",
            observations_path=None,
            marked_path=None,
            repo_root=ROOT,
        )
    assert caught.value.code == "STALE_EVIDENCE"


def test_prepare_empty_file_is_not_missing(tmp_path: Path) -> None:
    work = _copy_ok(tmp_path)
    empty = work / "_novel_text" / "novel_text11.md"
    empty.write_text("", encoding="utf-8")
    run = _prepare_ok(work, text_path="_novel_text/novel_text11.md", selector=None)
    request = load_model(run / "request.yaml", RequestDocument)
    assert request.target.base_exists is True
    assert request.target.base_raw_sha256 == EMPTY_RAW_SHA256
    empty.write_text("# 第十一章\n　本文\n", encoding="utf-8")
    with pytest.raises(BridgeError) as caught:
        inspect(
            work,
            scene_id="ch01-001",
            run_id="run-0001",
            observations_path=None,
            marked_path=None,
            repo_root=ROOT,
        )
    assert caught.value.code == "STALE_EVIDENCE"


def test_inspect_rejects_rewritten_received_candidate(tmp_path: Path) -> None:
    work = _copy_ok(tmp_path)
    run = _prepare_ok(work)
    receive(
        work,
        scene_id="ch01-001",
        run_id="run-0001",
        candidate=work / "_metron" / "ch01-001" / "marked.md",
        request_id=None,
    )
    stored = work / "_metron" / "ch01-001" / "marked.001.md"
    stored.write_text(
        stored.read_text(encoding="utf-8").replace("旅行用の上着", "通学用の上着"),
        encoding="utf-8",
    )
    with pytest.raises(BridgeError) as rewritten:
        inspect(
            work,
            scene_id="ch01-001",
            run_id="run-0001",
            observations_path=None,
            marked_path=None,
            repo_root=ROOT,
        )
    assert rewritten.value.code == "STALE_EVIDENCE"
    stored.unlink()
    with pytest.raises(BridgeError) as missing:
        inspect(
            work,
            scene_id="ch01-001",
            run_id="run-0001",
            observations_path=None,
            marked_path=None,
            repo_root=ROOT,
        )
    assert missing.value.code == "STALE_EVIDENCE"
    assert "receive" in str(missing.value).lower() or "missing" in str(missing.value).lower()


def test_inspect_revalidates_links_on_rebuild(tmp_path: Path) -> None:
    work = _copy_ok(tmp_path)
    run = _prepare_ok(work)
    receive(
        work,
        scene_id="ch01-001",
        run_id="run-0001",
        candidate=work / "_metron" / "ch01-001" / "marked.md",
        request_id=None,
    )
    links = run / "links.yaml"
    links.write_text(
        links.read_text(encoding="utf-8").replace(
            "scene_id: ch01-001",
            "scene_id: ch99-001",
            1,
        ),
        encoding="utf-8",
    )
    with pytest.raises(BridgeError) as caught:
        inspect(
            work,
            scene_id="ch01-001",
            run_id="run-0001",
            observations_path=(
                FIXTURE
                / "ok_ch01_001"
                / "work"
                / "_writing"
                / "ch01-001"
                / "run-0001"
                / "observations.json"
            ),
            marked_path=None,
            repo_root=ROOT,
        )
    assert caught.value.code == "LINK_CONFLICT"


def test_receive_recovers_from_corrupted_candidate_history(tmp_path: Path) -> None:
    work = _copy_ok(tmp_path)
    run = _prepare_ok(work)
    original = work / "_metron" / "ch01-001" / "marked.md"
    receive(work, scene_id="ch01-001", run_id="run-0001", candidate=original, request_id=None)
    first = work / "_metron" / "ch01-001" / "marked.001.md"
    first.write_text(
        first.read_text(encoding="utf-8").replace("旅行用の上着", "通学用の上着"),
        encoding="utf-8",
    )
    receive(work, scene_id="ch01-001", run_id="run-0001", candidate=original, request_id=None)
    second = work / "_metron" / "ch01-001" / "marked.002.md"
    assert first.is_file()
    assert "通学用の上着" in first.read_text(encoding="utf-8")
    assert second.is_file()
    refs = load_json_model(run / "artifact_refs.json", ArtifactRefsDocument)
    assert refs.candidate is not None
    assert refs.candidate.path.endswith("marked.002.md")
    assert len(refs.candidates) == 2
    code, message = inspect(
        work,
        scene_id="ch01-001",
        run_id="run-0001",
        observations_path=(
            FIXTURE
            / "ok_ch01_001"
            / "work"
            / "_writing"
            / "ch01-001"
            / "run-0001"
            / "observations.json"
        ),
        marked_path=None,
        repo_root=ROOT,
    )
    assert code == 0, message
    report = load_json_model(run / "report.json", ReportDocument)
    assert report.text_state.value == "success"
