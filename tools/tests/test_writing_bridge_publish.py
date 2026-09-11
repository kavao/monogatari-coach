from __future__ import annotations

from pathlib import Path

import pytest

from test_writing_bridge import FIXTURE, ROOT, _copy_ok, _run_cli
from writing_bridge.commands import inspect, prepare, receive
from writing_bridge.errors import BridgeError
from writing_bridge.hashes import raw_sha256, text_sha256
from writing_bridge.models import (
    ArtifactRefsDocument,
    RequestKind,
    Selector,
    SelectorKind,
    ReportDocument,
    RequestDocument,
)
from writing_bridge.publish import compose_published, publish, replacement_span
from writing_bridge.storage import load_json_model, load_model


AUTH = "test-only fixture publish"
OBS = FIXTURE / "ok_ch01_001" / "work" / "_writing" / "ch01-001" / "run-0001" / "observations.json"


def _ready(tmp_path: Path, *, allow_publish: bool = True):
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
        allow_publish=allow_publish,
    )
    receive(
        work,
        scene_id="ch01-001",
        run_id="run-0001",
        candidate=work / "_metron" / "ch01-001" / "marked.md",
        request_id=None,
    )
    return work


def test_publish_requires_permission(tmp_path: Path) -> None:
    work = _ready(tmp_path, allow_publish=False)
    with pytest.raises(BridgeError) as caught:
        publish(
            work,
            scene_id="ch01-001",
            run_id="run-0001",
            authorization=AUTH,
            repo_root=ROOT,
        )
    assert caught.value.code == "PERMISSION_DENIED"
    assert (work / "_novel_text" / "novel_text01.md").read_text(encoding="utf-8").count("旅行用の上着") == 1


def test_publish_does_not_follow_draft_run_into_empty_save_run(tmp_path: Path) -> None:
    work = _ready(tmp_path, allow_publish=False)
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
    with pytest.raises(BridgeError) as denied:
        publish(
            work,
            scene_id="ch01-001",
            run_id="run-0001",
            authorization=AUTH,
            repo_root=ROOT,
        )
    assert denied.value.code == "PERMISSION_DENIED"
    with pytest.raises(BridgeError) as missing:
        publish(
            work,
            scene_id="ch01-001",
            run_id="run-0002",
            authorization=AUTH,
            repo_root=ROOT,
        )
    assert missing.value.code == "UNKNOWN_REF"
    receive(
        work,
        scene_id="ch01-001",
        run_id="run-0002",
        candidate=work / "_metron" / "ch01-001" / "marked.md",
        request_id=None,
    )
    code, _message = publish(
        work,
        scene_id="ch01-001",
        run_id="run-0002",
        authorization=AUTH,
        repo_root=ROOT,
        dry_run=True,
    )
    assert code == 0


def test_publish_dry_run_does_not_write(tmp_path: Path) -> None:
    work = _ready(tmp_path)
    before = (work / "_novel_text" / "novel_text01.md").read_bytes()
    code, message = publish(
        work,
        scene_id="ch01-001",
        run_id="run-0001",
        authorization=AUTH,
        repo_root=ROOT,
        dry_run=True,
    )
    assert code == 0
    assert "would publish" in message
    assert (work / "_novel_text" / "novel_text01.md").read_bytes() == before
    assert not (work / "_writing" / "ch01-001" / "run-0001" / "publish_state.json").exists()


def test_publish_writes_canonical_and_backup(tmp_path: Path) -> None:
    work = _ready(tmp_path)
    original = work / "_novel_text" / "novel_text01.md"
    before = original.read_text(encoding="utf-8")
    inspect(
        work,
        scene_id="ch01-001",
        run_id="run-0001",
        observations_path=OBS,
        marked_path=None,
        repo_root=ROOT,
    )
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
    body = original.read_text(encoding="utf-8")
    assert "<!--beat:" not in body
    assert "旅行用の上着" in body
    backups = list((work / "_novel_text_backup").glob("novel_text01_v*.md"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == before
    assert not (work / "_metron" / "ch01-001" / "FINAL.md").exists()
    adopted = work / "_metron" / "ch01-001" / "adopted.run-0001.md"
    assert adopted.is_file()
    run = work / "_writing" / "ch01-001" / "run-0001"
    report = load_json_model(run / "report.json", ReportDocument)
    assert report.text_save.value == "success"
    assert report.target_text_sha256 == text_sha256(body)
    assert any("char_count=" in item.note for item in report.findings)
    assert any("punctuation_gate=" in item.note for item in report.findings)
    assert any("story_sync skipped" in item.note for item in report.findings)
    request = load_model(run / "request.yaml", RequestDocument)
    assert request.target.base_raw_sha256 == raw_sha256(original)
    again, again_message = publish(
        work,
        scene_id="ch01-001",
        run_id="run-0001",
        authorization=AUTH,
        repo_root=ROOT,
    )
    assert again == 0
    assert "already published" in again_message
    assert len(list((work / "_novel_text_backup").glob("novel_text01_v*.md"))) == 1


def test_publish_stale_base_hash(tmp_path: Path) -> None:
    work = _ready(tmp_path)
    target = work / "_novel_text" / "novel_text01.md"
    target.write_text(target.read_text(encoding="utf-8") + "　追記。\n", encoding="utf-8")
    with pytest.raises(BridgeError) as caught:
        publish(
            work,
            scene_id="ch01-001",
            run_id="run-0001",
            authorization=AUTH,
            repo_root=ROOT,
        )
    assert caught.value.code == "STALE_EVIDENCE"


def test_publish_keeps_other_scene(tmp_path: Path) -> None:
    work = _copy_ok(tmp_path)
    text = work / "_novel_text" / "novel_text01.md"
    other = "　後の場面では駅の時計だけが動いている。\n"
    text.write_text(
        "<!-- scene: ch01-001 -->\n"
        + text.read_text(encoding="utf-8").rstrip()
        + "\n\n<!-- scene: ch01-002 -->\n"
        + other,
        encoding="utf-8",
    )
    prepare(
        work,
        scene_id="ch01-001",
        text_path="_novel_text/novel_text01.md",
        request_kind=RequestKind.LOCAL_EXPAND,
        model_id="local-writer",
        selector=Selector(kind=SelectorKind.HTML_COMMENT, value="<!-- scene: ch01-001 -->"),
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
    publish(
        work,
        scene_id="ch01-001",
        run_id="run-0001",
        authorization=AUTH,
        repo_root=ROOT,
    )
    body = text.read_text(encoding="utf-8")
    assert "<!-- scene: ch01-002 -->" in body
    assert other.strip() in body
    assert "<!--beat:" not in body
    assert body.split("<!-- scene: ch01-002 -->", 1)[1].lstrip("\n") == other


def test_replacement_span_offset() -> None:
    text = "AAAA\nBBBB\nCCCC\n"
    start, end = replacement_span(
        text,
        scene_id="ch01-001",
        selector=Selector(kind=SelectorKind.OFFSET, value="5:10"),
        request_kind=RequestKind.LOCAL_EXPAND,
    )
    assert (start, end) == (5, 10)
    composed, prefix, suffix = compose_published(
        text,
        "XXXX\n",
        scene_id="ch01-001",
        selector=Selector(kind=SelectorKind.OFFSET, value="5:10"),
        request_kind=RequestKind.LOCAL_EXPAND,
    )
    assert prefix == "AAAA\n"
    assert suffix == "CCCC\n"
    assert composed == "AAAA\nXXXX\nCCCC\n"


def test_publish_resume_after_inspect_crash(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    work = _ready(tmp_path)
    original = (work / "_novel_text" / "novel_text01.md").read_text(encoding="utf-8")
    from writing_bridge import publish as module

    calls = {"n": 0}
    real = module.commands.inspect

    def boom(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("simulated crash")
        return real(*args, **kwargs)

    monkeypatch.setattr(module.commands, "inspect", boom)
    with pytest.raises(OSError, match="simulated crash"):
        publish(
            work,
            scene_id="ch01-001",
            run_id="run-0001",
            authorization=AUTH,
            repo_root=ROOT,
        )
    written = (work / "_novel_text" / "novel_text01.md").read_text(encoding="utf-8")
    assert "<!--beat:" not in written
    backups = list((work / "_novel_text_backup").glob("novel_text01_v*.md"))
    assert backups and backups[0].read_text(encoding="utf-8") == original
    monkeypatch.setattr(module.commands, "inspect", real)
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
    assert len(list((work / "_novel_text_backup").glob("novel_text01_v*.md"))) == 1


def test_cli_publish_permission_and_status(tmp_path: Path) -> None:
    work = _ready(tmp_path)
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
        "--observations",
        str(OBS),
    )
    assert result.returncode == 0, result.stderr
    status = _run_cli(
        "status",
        str(work),
        "--scene-id",
        "ch01-001",
        "--run-id",
        "run-0001",
    )
    assert "publish: completed" in status.stdout
    assert "text_save: success" in status.stdout


def test_new_without_selector_does_not_replace_other_scenes(tmp_path: Path) -> None:
    work = _copy_ok(tmp_path)
    text = work / "_novel_text" / "novel_text01.md"
    other = "　後の場面では駅の時計だけが動いている。\n"
    text.write_text(text.read_text(encoding="utf-8").rstrip() + "\n\n" + other, encoding="utf-8")
    with pytest.raises(BridgeError) as caught:
        prepare(
            work,
            scene_id="ch01-001",
            text_path="_novel_text/novel_text01.md",
            request_kind=RequestKind.NEW,
            model_id="local-writer",
            selector=None,
            links_path=None,
            repo_root=ROOT,
            allow_publish=True,
        )
    assert caught.value.code == "MISSING_FIELD"
    with pytest.raises(BridgeError) as span_error:
        replacement_span(
            text.read_text(encoding="utf-8"),
            scene_id="ch01-001",
            selector=None,
            request_kind=RequestKind.NEW,
        )
    assert span_error.value.code == "MISSING_FIELD"
    assert other.strip() in text.read_text(encoding="utf-8")


def test_publish_detects_created_and_deleted_canonical(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from writing_bridge import publish as module

    work = _copy_ok(tmp_path)
    text = work / "_novel_text" / "novel_text01.md"
    text.unlink()
    prepare(
        work,
        scene_id="ch01-001",
        text_path="_novel_text/novel_text01.md",
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
    real_save = module._save

    def create_after_save(dest, state):
        real_save(dest, state)
        if not text.exists():
            text.write_text("外部で作られた本文。\n", encoding="utf-8")

    monkeypatch.setattr(module, "_save", create_after_save)
    with pytest.raises(BridgeError) as created:
        publish(
            work,
            scene_id="ch01-001",
            run_id="run-0001",
            authorization=AUTH,
            repo_root=ROOT,
        )
    assert created.value.code == "STALE_EVIDENCE"
    assert text.read_text(encoding="utf-8") == "外部で作られた本文。\n"

    work2 = _ready(tmp_path / "deleted")
    target = work2 / "_novel_text" / "novel_text01.md"
    real_save2 = module._save

    def delete_after_save(dest, state):
        real_save2(dest, state)
        if target.exists() and state.stage == "backup" and state.backup_path is None:
            target.unlink()

    monkeypatch.setattr(module, "_save", delete_after_save)
    with pytest.raises(BridgeError) as deleted:
        publish(
            work2,
            scene_id="ch01-001",
            run_id="run-0001",
            authorization=AUTH,
            repo_root=ROOT,
        )
    assert deleted.value.code == "STALE_EVIDENCE"
    assert not target.exists()


def test_receive_after_publish_does_not_mix_editions(tmp_path: Path) -> None:
    work = _ready(tmp_path)
    publish(
        work,
        scene_id="ch01-001",
        run_id="run-0001",
        authorization=AUTH,
        repo_root=ROOT,
        observations_path=OBS,
    )
    other = tmp_path / "other.md"
    other.write_text(
        (work / "_metron" / "ch01-001" / "marked.md")
        .read_text(encoding="utf-8")
        .replace("旅行用の上着", "通学用の上着"),
        encoding="utf-8",
    )
    with pytest.raises(BridgeError) as caught:
        receive(
            work,
            scene_id="ch01-001",
            run_id="run-0001",
            candidate=other,
            request_id=None,
        )
    assert caught.value.code == "JOB_CONFLICT"
    run = work / "_writing" / "ch01-001" / "run-0001"
    refs = load_json_model(run / "artifact_refs.json", ArtifactRefsDocument)
    stored = work / refs.candidate.path
    stored.write_text(other.read_text(encoding="utf-8"), encoding="utf-8")
    refs.candidate.raw_sha256 = raw_sha256(stored)
    from writing_bridge.storage import write_model
    write_model(run / "artifact_refs.json", refs, json_format=True)
    (run / "observations.json").unlink(missing_ok=True)
    inspect(
        work,
        scene_id="ch01-001",
        run_id="run-0001",
        observations_path=None,
        marked_path=None,
        repo_root=ROOT,
    )
    report = load_json_model(run / "report.json", ReportDocument)
    assert report.text_save.value == "unresolved"
    assert any(item.code == "STALE_EVIDENCE" for item in report.findings)


def test_inspect_marked_must_match_received_candidate(tmp_path: Path) -> None:
    work = _ready(tmp_path)
    publish(
        work,
        scene_id="ch01-001",
        run_id="run-0001",
        authorization=AUTH,
        repo_root=ROOT,
        observations_path=OBS,
    )
    run = work / "_writing" / "ch01-001" / "run-0001"
    refs = load_json_model(run / "artifact_refs.json", ArtifactRefsDocument)
    received = work / refs.candidate.path
    other = tmp_path / "other.md"
    other.write_text(
        received.read_text(encoding="utf-8").replace("旅行用の上着", "通学用の上着"),
        encoding="utf-8",
    )
    with pytest.raises(BridgeError) as caught:
        inspect(
            work,
            scene_id="ch01-001",
            run_id="run-0001",
            observations_path=OBS,
            marked_path=other,
            repo_root=ROOT,
        )
    assert caught.value.code == "STALE_EVIDENCE"
    report = load_json_model(run / "report.json", ReportDocument)
    assert report.text_save.value == "success"

    copy = tmp_path / "same-bytes.md"
    copy.write_bytes(received.read_bytes())
    inspect(
        work,
        scene_id="ch01-001",
        run_id="run-0001",
        observations_path=OBS,
        marked_path=copy,
        repo_root=ROOT,
    )
    report = load_json_model(run / "report.json", ReportDocument)
    assert report.text_save.value == "success"
