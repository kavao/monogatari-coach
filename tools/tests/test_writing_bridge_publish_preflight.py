from __future__ import annotations

import re
from pathlib import Path

import pytest

from novel_punctuation_metrics import evaluate_gate, measure_text
from test_writing_bridge import FIXTURE, ROOT, _copy_ok, _run_cli
from writing_bridge.commands import prepare, receive
from writing_bridge.errors import BridgeError
from writing_bridge.hashes import raw_sha256, text_sha256
from writing_bridge.models import (
    ArtifactRefsDocument,
    JournalAction,
    JournalEntry,
    RequestKind,
    Selector,
    SelectorKind,
    RequestDocument,
)
from writing_bridge.publish import (
    _assemble,
    _clean_scene_body,
    _plan_state,
    _save,
    _update_request_hashes,
    compose_published,
    composed_raw_sha256,
    has_canonical_written_evidence,
    publish,
    read_publish_state,
)
from writing_bridge.storage import append_journal, load_json_model, load_model, now_iso


AUTH = "test-only fixture publish"
OBS = FIXTURE / "ok_ch01_001" / "work" / "_writing" / "ch01-001" / "run-0001" / "observations.json"
_SCOPE = re.compile(
    r"scope=full_text intended_text_sha256=(sha256:[0-9a-f]{64}) "
    r"intended_raw_sha256=(sha256:[0-9a-f]{64})"
)


def _short_marked() -> str:
    return (
        "<!--beat:pack_bag-->\n"
        "　朝の光が窓に届いた。\n"
        "<!--/beat:pack_bag-->\n"
        "<!--beat:say_goodbye-->\n"
        "「行ってくる」\n"
        "<!--/beat:say_goodbye-->\n"
        "<!--beat:reach_station-->\n"
        "　駅へ向かった。\n"
        "<!--/beat:reach_station-->\n"
    )


def _dense_body() -> str:
    return "あ、あ、あ。" * 140 + "\n"


def _hashes_from(message: str) -> tuple[str, str]:
    match = _SCOPE.search(message)
    assert match is not None, message
    return match.group(1), match.group(2)


def _dest(work: Path) -> Path:
    return work / "_writing" / "ch01-001" / "run-0001"


def _snapshot(work: Path, dest: Path, text_file: Path) -> tuple[bytes | None, bytes | None, str]:
    text = text_file.read_bytes() if text_file.is_file() else None
    state = (dest / "publish_state.json").read_bytes() if (dest / "publish_state.json").is_file() else None
    journal = (dest / "journal.jsonl").read_text(encoding="utf-8") if (dest / "journal.jsonl").is_file() else ""
    backup = work / "_novel_text_backup"
    assert not backup.exists() or not list(backup.glob("*.md"))
    return text, state, journal


def _assert_unchanged(
    work: Path,
    dest: Path,
    text_file: Path,
    before: tuple[bytes | None, bytes | None, str],
) -> None:
    text, state, journal = before
    assert (text_file.read_bytes() if text_file.is_file() else None) == text
    assert (
        (dest / "publish_state.json").read_bytes()
        if (dest / "publish_state.json").is_file()
        else None
    ) == state
    assert (
        (dest / "journal.jsonl").read_text(encoding="utf-8")
        if (dest / "journal.jsonl").is_file()
        else ""
    ) == journal
    backup = work / "_novel_text_backup"
    assert not backup.exists() or not list(backup.glob("*.md"))


def _planned(work: Path, dest: Path | None = None):
    dest = dest or _dest(work)
    request = load_model(dest / "request.yaml", RequestDocument)
    refs = load_json_model(dest / "artifact_refs.json", ArtifactRefsDocument)
    assert refs.candidate is not None
    candidate = work / refs.candidate.path
    scene_body = _clean_scene_body(candidate.read_text(encoding="utf-8"))
    text_file = work / request.target.text_path
    state = _plan_state(work, request, text_file, candidate, scene_body, AUTH)
    return dest, request, state, scene_body, text_file, candidate


def _write_evidence(dest: Path, request: RequestDocument, intended_raw: str) -> None:
    append_journal(
        dest / "journal.jsonl",
        JournalEntry(
            schema=1,
            at=now_iso(),
            action=JournalAction.PUBLISH,
            run_id=request.run_id,
            request_id=request.request_id,
            hashes={"published": intended_raw},
            note="canonical text written",
        ),
    )


def _plant(
    work: Path,
    *,
    stage: str,
    write_intended: bool = False,
    evidence: bool = False,
    rollback: bool = False,
) -> tuple[Path, RequestDocument, object, Path, str]:
    dest, request, state, scene_body, text_file, _candidate = _planned(work)
    original = text_file.read_bytes() if text_file.is_file() else None
    composed = _assemble(state, scene_body, request.request_kind)
    state.stage = stage
    state.status = "active"
    _save(dest, state)
    if write_intended:
        text_file.parent.mkdir(parents=True, exist_ok=True)
        text_file.write_text(composed, encoding="utf-8", newline="\n")
    if evidence:
        _write_evidence(dest, request, state.intended_raw_sha256)
    if rollback and original is not None:
        text_file.write_bytes(original)
    return dest, request, state, text_file, composed


def _ready_ok(tmp_path: Path) -> Path:
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
        allow_publish=True,
    )
    receive(
        work,
        scene_id="ch01-001",
        run_id="run-0001",
        candidate=work / "_metron" / "ch01-001" / "marked.md",
        request_id=None,
    )
    return work


def _ready_missing(tmp_path: Path) -> Path:
    work = _copy_ok(tmp_path)
    target = work / "_novel_text" / "novel_text99.md"
    assert not target.exists()
    prepare(
        work,
        scene_id="ch01-001",
        text_path="_novel_text/novel_text99.md",
        request_kind=RequestKind.NEW,
        model_id="local-writer",
        selector=None,
        links_path=None,
        repo_root=ROOT,
        allow_publish=True,
    )
    receive(
        work,
        scene_id="ch01-001",
        run_id="run-0001",
        candidate=work / "_metron" / "ch01-001" / "marked.md",
        request_id=None,
    )
    return work


@pytest.mark.parametrize(
    "kind,selector",
    [
        (RequestKind.NEW, Selector(kind=SelectorKind.HEADING, value="第一章　駅までの道")),
        (RequestKind.REFINE, Selector(kind=SelectorKind.HEADING, value="第一章　駅までの道")),
        (RequestKind.APPEND, Selector(kind=SelectorKind.HEADING, value="第一章　駅までの道")),
    ],
)
def test_plan_state_matches_assemble(tmp_path: Path, kind: RequestKind, selector) -> None:
    work = _copy_ok(tmp_path)
    prepare(
        work,
        scene_id="ch01-001",
        text_path="_novel_text/novel_text01.md",
        request_kind=kind,
        model_id="local-writer",
        selector=selector,
        links_path=None,
        repo_root=ROOT,
        allow_publish=True,
    )
    receive(
        work,
        scene_id="ch01-001",
        run_id="run-0001",
        candidate=work / "_metron" / "ch01-001" / "marked.md",
        request_id=None,
    )
    dest, request, state, scene_body, text_file, _candidate = _planned(work)
    assembled = _assemble(state, scene_body, request.request_kind)
    current = text_file.read_text(encoding="utf-8") if text_file.is_file() else ""
    composed, _prefix, _suffix = compose_published(
        current.replace("\r\n", "\n").replace("\r", "\n"),
        scene_body,
        scene_id=request.scene_id,
        selector=request.target.selector,
        request_kind=request.request_kind,
    )
    assert assembled == composed
    assert composed_raw_sha256(assembled) == state.intended_raw_sha256
    assert text_sha256(assembled) == state.intended_text_sha256


def test_append_candidate_pass_composed_fail(tmp_path: Path) -> None:
    work = _copy_ok(tmp_path)
    target = work / "_novel_text" / "novel_text01.md"
    target.write_text("# 第一章　駅までの道\n\n" + _dense_body(), encoding="utf-8")
    prepare(
        work,
        scene_id="ch01-001",
        text_path="_novel_text/novel_text01.md",
        request_kind=RequestKind.APPEND,
        model_id="local-writer",
        selector=Selector(kind=SelectorKind.HEADING, value="第一章　駅までの道"),
        links_path=None,
        repo_root=ROOT,
        allow_publish=True,
    )
    marked = tmp_path / "short.md"
    marked.write_text(_short_marked(), encoding="utf-8")
    receive(
        work,
        scene_id="ch01-001",
        run_id="run-0001",
        candidate=marked,
        request_id=None,
    )
    scene_body = _clean_scene_body(_short_marked())
    assert evaluate_gate(measure_text(scene_body))["status"] != "fail"
    dest, request, state, _scene, text_file, _c = _planned(work)
    composed = _assemble(state, scene_body, request.request_kind)
    assert evaluate_gate(measure_text(composed))["status"] == "fail"
    before = _snapshot(work, dest, text_file)
    code, message = publish(
        work,
        scene_id="ch01-001",
        run_id="run-0001",
        authorization=AUTH,
        repo_root=ROOT,
        dry_run=True,
    )
    assert code == 1
    assert "punctuation_gate=fail" in message
    text_sha, raw_sha = _hashes_from(message)
    assert text_sha == state.intended_text_sha256
    assert raw_sha == state.intended_raw_sha256
    _assert_unchanged(work, dest, text_file, before)


def test_refine_candidate_pass_composed_fail(tmp_path: Path) -> None:
    work = _copy_ok(tmp_path)
    target = work / "_novel_text" / "novel_text01.md"
    target.write_text(
        "# 第一章　駅までの道\n\n　短い元稿。\n\n# 第十二章　別\n\n" + _dense_body(),
        encoding="utf-8",
    )
    prepare(
        work,
        scene_id="ch01-001",
        text_path="_novel_text/novel_text01.md",
        request_kind=RequestKind.REFINE,
        model_id="local-writer",
        selector=Selector(kind=SelectorKind.HEADING, value="第一章　駅までの道"),
        links_path=None,
        repo_root=ROOT,
        allow_publish=True,
    )
    marked = tmp_path / "short.md"
    marked.write_text(_short_marked(), encoding="utf-8")
    receive(
        work,
        scene_id="ch01-001",
        run_id="run-0001",
        candidate=marked,
        request_id=None,
    )
    scene_body = _clean_scene_body(_short_marked())
    assert evaluate_gate(measure_text(scene_body))["status"] != "fail"
    dest, request, state, _scene, text_file, _c = _planned(work)
    composed = _assemble(state, scene_body, request.request_kind)
    assert evaluate_gate(measure_text(composed))["status"] == "fail"
    before = target.read_bytes()
    code, message = publish(
        work,
        scene_id="ch01-001",
        run_id="run-0001",
        authorization=AUTH,
        repo_root=ROOT,
        dry_run=True,
    )
    assert code == 1
    assert "scope=full_text" in message
    assert target.read_bytes() == before
    assert not (dest / "publish_state.json").exists()


def test_dry_run_hashes_match_publish_state(tmp_path: Path) -> None:
    work = _ready_ok(tmp_path)
    dest, _req, state, _body, text_file, _c = _planned(work)
    code, message = publish(
        work,
        scene_id="ch01-001",
        run_id="run-0001",
        authorization=AUTH,
        repo_root=ROOT,
        dry_run=True,
    )
    assert code == 0
    text_sha, raw_sha = _hashes_from(message)
    assert text_sha == state.intended_text_sha256
    assert raw_sha == state.intended_raw_sha256
    result = _run_cli(
        "publish",
        str(work),
        "--scene-id",
        "ch01-001",
        "--run-id",
        "run-0001",
        "--authorization",
        AUTH,
        "--repo-root",
        str(ROOT),
        "--dry-run",
    )
    assert result.returncode == 0, result.stderr
    cli_text, cli_raw = _hashes_from(result.stdout)
    assert cli_text == state.intended_text_sha256
    assert cli_raw == state.intended_raw_sha256


def test_stale_base_and_candidate_refuse_dry_run(tmp_path: Path) -> None:
    work = _ready_ok(tmp_path)
    target = work / "_novel_text" / "novel_text01.md"
    target.write_text(target.read_text(encoding="utf-8") + "　追記。\n", encoding="utf-8")
    with pytest.raises(BridgeError) as caught:
        publish(
            work,
            scene_id="ch01-001",
            run_id="run-0001",
            authorization=AUTH,
            repo_root=ROOT,
            dry_run=True,
        )
    assert caught.value.code == "STALE_EVIDENCE"

    work = _ready_ok(tmp_path / "candidate")
    dest = _dest(work)
    refs = load_json_model(dest / "artifact_refs.json", ArtifactRefsDocument)
    assert refs.candidate is not None
    candidate = work / refs.candidate.path
    candidate.write_text(candidate.read_text(encoding="utf-8") + "改変\n", encoding="utf-8")
    with pytest.raises(BridgeError) as changed:
        publish(
            work,
            scene_id="ch01-001",
            run_id="run-0001",
            authorization=AUTH,
            repo_root=ROOT,
            dry_run=True,
        )
    assert changed.value.code == "STALE_EVIDENCE"


def test_backup_original_without_evidence_is_preflight(tmp_path: Path) -> None:
    work = _ready_ok(tmp_path)
    dest, _req, state, text_file, composed = _plant(work, stage="backup")
    before = _snapshot(work, dest, text_file)
    code, message = publish(
        work,
        scene_id="ch01-001",
        run_id="run-0001",
        authorization=AUTH,
        repo_root=ROOT,
        dry_run=True,
    )
    assert code == 0
    text_sha, raw_sha = _hashes_from(message)
    assert text_sha == state.intended_text_sha256
    assert raw_sha == state.intended_raw_sha256
    assert raw_sha256(text_file) != state.intended_raw_sha256
    _assert_unchanged(work, dest, text_file, before)
    assert composed_raw_sha256(composed) == state.intended_raw_sha256


def test_backup_intended_without_evidence_is_stale(tmp_path: Path) -> None:
    work = _ready_ok(tmp_path)
    dest, _req, _state, text_file, _composed = _plant(work, stage="backup", write_intended=True)
    before = _snapshot(work, dest, text_file)
    with pytest.raises(BridgeError) as caught:
        publish(
            work,
            scene_id="ch01-001",
            run_id="run-0001",
            authorization=AUTH,
            repo_root=ROOT,
            dry_run=True,
        )
    assert caught.value.code == "STALE_EVIDENCE"
    _assert_unchanged(work, dest, text_file, before)


def test_write_original_without_evidence_is_preflight(tmp_path: Path) -> None:
    work = _ready_ok(tmp_path)
    dest, _req, state, text_file, _composed = _plant(work, stage="write")
    before = _snapshot(work, dest, text_file)
    code, message = publish(
        work,
        scene_id="ch01-001",
        run_id="run-0001",
        authorization=AUTH,
        repo_root=ROOT,
        dry_run=True,
    )
    assert code == 0
    _hashes_from(message)
    assert read_publish_state(dest / "publish_state.json").stage == "write"
    _assert_unchanged(work, dest, text_file, before)
    assert raw_sha256(text_file) == state.original_raw_sha256


def test_write_intended_without_evidence_is_stale(tmp_path: Path) -> None:
    work = _ready_ok(tmp_path)
    dest, _req, _state, text_file, _composed = _plant(work, stage="write", write_intended=True)
    before = _snapshot(work, dest, text_file)
    with pytest.raises(BridgeError) as caught:
        publish(
            work,
            scene_id="ch01-001",
            run_id="run-0001",
            authorization=AUTH,
            repo_root=ROOT,
            dry_run=True,
        )
    assert caught.value.code == "STALE_EVIDENCE"
    _assert_unchanged(work, dest, text_file, before)


@pytest.mark.parametrize("stage", ["backup", "write"])
def test_missing_original_same_bytes_without_evidence_is_stale(tmp_path: Path, stage: str) -> None:
    work = _ready_missing(tmp_path)
    dest, request, state, scene_body, text_file, _c = _planned(work)
    assert not text_file.exists()
    composed = _assemble(state, scene_body, request.request_kind)
    state.stage = stage
    _save(dest, state)
    text_file.parent.mkdir(parents=True, exist_ok=True)
    text_file.write_text(composed, encoding="utf-8", newline="\n")
    assert raw_sha256(text_file) == state.intended_raw_sha256
    assert not has_canonical_written_evidence(dest, state.intended_raw_sha256)
    before = _snapshot(work, dest, text_file)
    with pytest.raises(BridgeError) as caught:
        publish(
            work,
            scene_id="ch01-001",
            run_id="run-0001",
            authorization=AUTH,
            repo_root=ROOT,
            dry_run=True,
        )
    assert caught.value.code == "STALE_EVIDENCE"
    _assert_unchanged(work, dest, text_file, before)


def test_backup_intended_with_evidence_is_conflict(tmp_path: Path) -> None:
    work = _ready_ok(tmp_path)
    dest, _req, _state, text_file, _composed = _plant(
        work, stage="backup", write_intended=True, evidence=True
    )
    before = _snapshot(work, dest, text_file)
    with pytest.raises(BridgeError) as caught:
        publish(
            work,
            scene_id="ch01-001",
            run_id="run-0001",
            authorization=AUTH,
            repo_root=ROOT,
            dry_run=True,
        )
    assert caught.value.code == "JOB_CONFLICT"
    _assert_unchanged(work, dest, text_file, before)


@pytest.mark.parametrize("stage", ["backup", "write", "inspect"])
def test_evidence_with_original_rollback_is_stale(tmp_path: Path, stage: str) -> None:
    work = _ready_ok(tmp_path)
    dest, _req, _state, text_file, _composed = _plant(
        work, stage=stage, write_intended=True, evidence=True, rollback=True
    )
    before = _snapshot(work, dest, text_file)
    with pytest.raises(BridgeError) as caught:
        publish(
            work,
            scene_id="ch01-001",
            run_id="run-0001",
            authorization=AUTH,
            repo_root=ROOT,
            dry_run=True,
        )
    assert caught.value.code == "STALE_EVIDENCE"
    _assert_unchanged(work, dest, text_file, before)


def test_inspect_with_evidence_and_intended_is_conflict(tmp_path: Path) -> None:
    work = _ready_ok(tmp_path)
    dest, _req, _state, text_file, _composed = _plant(
        work, stage="inspect", write_intended=True, evidence=True
    )
    before = _snapshot(work, dest, text_file)
    with pytest.raises(BridgeError) as caught:
        publish(
            work,
            scene_id="ch01-001",
            run_id="run-0001",
            authorization=AUTH,
            repo_root=ROOT,
            dry_run=True,
        )
    assert caught.value.code == "JOB_CONFLICT"
    _assert_unchanged(work, dest, text_file, before)


@pytest.mark.parametrize("stage", ["backup", "write"])
def test_live_missing_same_bytes_without_evidence_is_stale(tmp_path: Path, stage: str) -> None:
    work = _ready_missing(tmp_path)
    dest, request, state, scene_body, text_file, _c = _planned(work)
    composed = _assemble(state, scene_body, request.request_kind)
    state.stage = stage
    _save(dest, state)
    text_file.parent.mkdir(parents=True, exist_ok=True)
    text_file.write_text(composed, encoding="utf-8", newline="\n")
    before = _snapshot(work, dest, text_file)
    with pytest.raises(BridgeError) as caught:
        publish(
            work,
            scene_id="ch01-001",
            run_id="run-0001",
            authorization=AUTH,
            repo_root=ROOT,
            observations_path=OBS,
        )
    assert caught.value.code == "STALE_EVIDENCE"
    _assert_unchanged(work, dest, text_file, before)
    assert read_publish_state(dest / "publish_state.json").status == "active"
    assert not has_canonical_written_evidence(dest, state.intended_raw_sha256)


@pytest.mark.parametrize("stage", ["backup", "write"])
def test_live_replaced_with_intended_without_evidence_is_stale(tmp_path: Path, stage: str) -> None:
    work = _ready_ok(tmp_path)
    dest, _req, state, text_file, _composed = _plant(work, stage=stage, write_intended=True)
    before = _snapshot(work, dest, text_file)
    with pytest.raises(BridgeError) as caught:
        publish(
            work,
            scene_id="ch01-001",
            run_id="run-0001",
            authorization=AUTH,
            repo_root=ROOT,
            observations_path=OBS,
        )
    assert caught.value.code == "STALE_EVIDENCE"
    _assert_unchanged(work, dest, text_file, before)
    assert read_publish_state(dest / "publish_state.json").status == "active"
    assert not has_canonical_written_evidence(dest, state.intended_raw_sha256)


@pytest.mark.parametrize("stage", ["backup", "write", "inspect"])
def test_live_evidence_rollback_is_stale(tmp_path: Path, stage: str) -> None:
    work = _ready_ok(tmp_path)
    dest, _req, state, text_file, _composed = _plant(
        work, stage=stage, write_intended=True, evidence=True, rollback=True
    )
    before = _snapshot(work, dest, text_file)
    with pytest.raises(BridgeError) as caught:
        publish(
            work,
            scene_id="ch01-001",
            run_id="run-0001",
            authorization=AUTH,
            repo_root=ROOT,
            observations_path=OBS,
        )
    assert caught.value.code == "STALE_EVIDENCE"
    _assert_unchanged(work, dest, text_file, before)
    assert raw_sha256(text_file) == state.original_raw_sha256
    assert read_publish_state(dest / "publish_state.json").status == "active"


def test_live_evidence_intended_resumes_without_rewrite(tmp_path: Path) -> None:
    work = _ready_ok(tmp_path)
    dest, request, state, text_file, composed = _plant(
        work, stage="inspect", write_intended=True, evidence=True
    )
    _update_request_hashes(dest, request, text_file)
    before_text = text_file.read_bytes()
    code, message = publish(
        work,
        scene_id="ch01-001",
        run_id="run-0001",
        authorization=AUTH,
        repo_root=ROOT,
        observations_path=OBS,
    )
    assert code == 0
    assert "published:" in message
    assert text_file.read_bytes() == before_text
    assert raw_sha256(text_file) == state.intended_raw_sha256
    assert composed_raw_sha256(composed) == state.intended_raw_sha256
    assert read_publish_state(dest / "publish_state.json").status == "completed"
