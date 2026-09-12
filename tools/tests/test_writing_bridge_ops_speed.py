from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from test_metron import _calibration
from test_repair_steps import _bridge, _begin, _next, _submit
from test_writing_bridge import _copy_ok, _run_cli, ROOT
from metron.analyze import analyze_marked_text
from metron.contract import load_beat_plan
from writing_bridge.commands import inspect, prepare, receive, status
from writing_bridge.errors import BridgeError
from writing_bridge.findings import SAVE_NEXT_ACTION, next_action_for
from writing_bridge.models import ItemStatus, ReportDocument, RequestKind
from writing_bridge.repair import repair_begin, repair_finish, repair_next, read_state
from writing_bridge.storage import load_json_model


BEATS = ("pack_bag", "say_goodbye", "reach_station")


def _set_flags(work: Path, *, chronos: str = "OFF") -> None:
    path = work / "config.md"
    text = path.read_text(encoding="utf-8")
    text = text.replace("| CHRONOS | ON |", f"| CHRONOS | {chronos} |")
    path.write_text(text, encoding="utf-8")


def _set_floor(work: Path, floor: int = 200, hints: tuple[int, int, int] = (80, 60, 60)) -> None:
    path = work / "_metron/ch01-001/beats.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["generation"]["chars_floor"] = floor
    for beat, hint in zip(data["beats"], hints):
        beat["budget"]["chars_hint"] = hint
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")


def _scene_chars(work: Path) -> int:
    plan = load_beat_plan(work / "_metron/ch01-001/beats.yaml")
    marked = (work / "_metron/ch01-001/marked.md").read_text(encoding="utf-8")
    return analyze_marked_text(marked, plan, run=1).metrics.metrics.scene.chars


def _pad_marked(work: Path, minimum: int) -> None:
    path = work / "_metron/ch01-001/marked.md"
    text = path.read_text(encoding="utf-8")
    closing = "<!--/beat:reach_station-->"
    while _scene_chars(work) < minimum:
        text = text.replace(closing, "あ" * 8 + "\n" + closing, 1)
        path.write_text(text, encoding="utf-8")


def _ops_bridge(tmp_path, *, chars: int, floor: int = 200, chronos: str = "OFF",
                finish_reason: str | None = None, expandable: bool = True):
    work = _copy_ok(tmp_path)
    _set_flags(work, chronos=chronos)
    repo = tmp_path / "repo"
    (repo / "config").mkdir(parents=True)
    calibration = _calibration(calibrated=True, missing_span_ratio=0.0,
                               beat_thin_ratio=0.01, ending_rush_threshold=0.0)
    (repo / "config" / "metron_models.yaml").write_text(yaml.safe_dump(
        {"models": {"fixture-writer": calibration.model_dump(mode="json")}}), encoding="utf-8")
    _set_floor(work, floor)
    if not expandable:
        path = work / "_metron/ch01-001/beats.yaml"
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        for beat in data["beats"]:
            beat["expandable"] = False
            beat["budget"]["chars_hint"] = 1
        path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    _pad_marked(work, chars)
    prepare(work, scene_id="ch01-001", text_path="_novel_text/novel_text01.md",
            request_kind=RequestKind.NEW, model_id="fixture-writer",
            selector=None, links_path=None, repo_root=repo)
    receive(work, scene_id="ch01-001", run_id="run-0001",
            candidate=work / "_metron/ch01-001/marked.md", request_id=None,
            finish_reason=finish_reason)
    return work, repo, work / "_writing/ch01-001/run-0001"


def test_e_advisory_tooshort_is_separated_and_does_not_begin(tmp_path):
    work, repo, run = _ops_bridge(tmp_path, chars=220)
    code, message = inspect(
        work,
        scene_id="ch01-001",
        run_id="run-0001",
        observations_path=None,
        marked_path=None,
        repo_root=repo,
    )
    assert code == 0, message
    report = load_json_model(run / "report.json", ReportDocument)
    assert any(item.code == "TooShort" for item in report.findings)
    assert all(item.code != "BeatMissing" for item in report.findings)
    assert all(item.code != "GenerationTruncated" for item in report.findings)
    assert report.next_action == SAVE_NEXT_ACTION
    rendered = (run / "report.md").read_text(encoding="utf-8")
    required_at = rendered.index("## required")
    advisory_at = rendered.index("## advisory")
    required_block = rendered[required_at:advisory_at]
    assert "TooShort" not in required_block
    assert "BeatMissing" not in required_block
    assert "なし" in required_block
    assert "TooShort" in rendered[advisory_at:]
    assert SAVE_NEXT_ACTION in rendered
    status_code, status_text = status(work, scene_id="ch01-001", run_id="run-0001")
    assert status_code == 0
    assert "required_findings: none" in status_text
    assert "TooShort" in status_text
    assert "advisory_findings:" in status_text
    required_line = next(
        line for line in status_text.splitlines() if line.startswith("required_findings:")
    )
    assert "TooShort" not in required_line
    assert "metron_auto_repair: none" in status_text
    assert SAVE_NEXT_ACTION in status_text
    with pytest.raises(BridgeError) as caught:
        repair_begin(
            work,
            scene_id="ch01-001",
            run_id="run-0001",
            model="fixture-writer",
            authorization="auto floor check",
            repo_root=repo,
        )
    assert caught.value.code == "REPAIR_NOT_NEEDED"
    assert not (run / "repair_state.json").exists()


def test_e_does_not_suggest_save_when_c1_unverified(tmp_path):
    work, repo, run = _ops_bridge(tmp_path, chars=220, chronos="ON")
    code, message = inspect(
        work,
        scene_id="ch01-001",
        run_id="run-0001",
        observations_path=None,
        marked_path=None,
        repo_root=repo,
    )
    assert code == 1, message
    report = load_json_model(run / "report.json", ReportDocument)
    assert any(item.code == "TEXT_STATE_UNVERIFIED" for item in report.findings)
    assert report.text_state is ItemStatus.UNRESOLVED
    assert report.next_action is None
    rendered = (run / "report.md").read_text(encoding="utf-8")
    assert SAVE_NEXT_ACTION not in rendered
    status_code, status_text = status(work, scene_id="ch01-001", run_id="run-0001")
    assert status_code == 0
    assert SAVE_NEXT_ACTION not in status_text


def test_e_does_not_suggest_save_while_repair_active(tmp_path):
    work, repo, run = _ops_bridge(tmp_path, chars=220)
    begun, _ = repair_begin(
        work,
        scene_id="ch01-001",
        run_id="run-0001",
        model="fixture-writer",
        authorization="explicit scene",
        repo_root=repo,
        intent="explicit_deepen",
        scope="scene",
    )
    assert begun == 0
    _next(work, repo)
    assert read_state(run / "repair_state.json").status == "active"
    code, message = inspect(
        work,
        scene_id="ch01-001",
        run_id="run-0001",
        observations_path=None,
        marked_path=None,
        repo_root=repo,
    )
    assert code == 0, message
    report = load_json_model(run / "report.json", ReportDocument)
    assert report.next_action is None
    rendered = (run / "report.md").read_text(encoding="utf-8")
    assert SAVE_NEXT_ACTION not in rendered
    status_code, status_text = status(work, scene_id="ch01-001", run_id="run-0001")
    assert status_code == 0
    assert "repair: active" in status_text
    assert SAVE_NEXT_ACTION not in status_text


def test_next_action_for_requires_c1_ready_and_idle_repair():
    ok = dict(
        floor_met=True,
        findings=[],
        text_state=ItemStatus.SKIPPED,
        blocking=False,
        repair_active=False,
    )
    assert next_action_for(**ok) == SAVE_NEXT_ACTION
    assert next_action_for(**{**ok, "text_state": ItemStatus.SUCCESS}) == SAVE_NEXT_ACTION
    assert next_action_for(**{**ok, "text_state": ItemStatus.UNRESOLVED}) is None
    assert next_action_for(**{**ok, "blocking": True}) is None
    assert next_action_for(**{**ok, "repair_active": True}) is None
    assert next_action_for(**{**ok, "floor_met": False}) is None


def test_f1_auto_refuses_when_floor_met_without_required(tmp_path):
    work, repo, run = _ops_bridge(tmp_path, chars=220)
    with pytest.raises(BridgeError) as caught:
        repair_begin(work, scene_id="ch01-001", run_id="run-0001",
                     model="fixture-writer", authorization="auto floor check",
                     repo_root=repo)
    assert caught.value.code == "REPAIR_NOT_NEEDED"
    assert caught.value.exit_code == 1
    assert not (run / "repair_state.json").exists()
    journal = (run / "journal.jsonl").read_text(encoding="utf-8")
    assert "repair_begin" not in journal


def test_f1b_explicit_deepen_begins_when_floor_met(tmp_path):
    work, repo, run = _ops_bridge(tmp_path, chars=220)
    code, _ = repair_begin(work, scene_id="ch01-001", run_id="run-0001",
                           model="fixture-writer", authorization="explicit scene",
                           repo_root=repo, intent="explicit_deepen", scope="scene")
    assert code == 0
    _next(work, repo)
    state = read_state(run / "repair_state.json")
    assert state.intent == "explicit_deepen"
    assert state.session.pending is not None
    assert state.session.pending.operation == "deepen"


def test_f1c_beat_ids_normalize_to_plan_order(tmp_path):
    work, repo, run = _ops_bridge(tmp_path, chars=220)
    repair_begin(work, scene_id="ch01-001", run_id="run-0001",
                 model="fixture-writer", authorization="explicit beats",
                 repo_root=repo, intent="explicit_deepen", scope="beats",
                 beat_ids=["reach_station", "pack_bag"])
    state = read_state(run / "repair_state.json")
    assert state.beat_ids == ["pack_bag", "reach_station"]
    again, _ = repair_begin(work, scene_id="ch01-001", run_id="run-0001",
                            model="fixture-writer", authorization="explicit beats",
                            repo_root=repo, intent="explicit_deepen", scope="beats",
                            beat_ids=["pack_bag", "reach_station"])
    assert again == 0
    _next(work, repo)
    pending = read_state(run / "repair_state.json").session.pending
    assert pending.beat_id == "pack_bag"


def test_f1d_under_floor_does_not_issue_out_of_scope_beat(tmp_path):
    work, repo, run = _ops_bridge(tmp_path, chars=150)
    repair_begin(work, scene_id="ch01-001", run_id="run-0001",
                 model="fixture-writer", authorization="only reach_station",
                 repo_root=repo, intent="explicit_deepen", scope="beats",
                 beat_ids=["reach_station"])
    _next(work, repo)
    pending = read_state(run / "repair_state.json").session.pending
    assert pending is not None
    assert pending.beat_id == "reach_station"
    assert pending.operation == "deepen"


def test_f12_authorization_text_does_not_override_auto(tmp_path):
    work, repo, run = _ops_bridge(tmp_path, chars=210)
    with pytest.raises(BridgeError) as caught:
        repair_begin(work, scene_id="ch01-001", run_id="run-0001",
                     model="fixture-writer",
                     authorization="ユーザー依頼: この場面を Deepen",
                     repo_root=repo)
    assert caught.value.code == "REPAIR_NOT_NEEDED"
    assert not (run / "repair_state.json").exists()


def test_f2_next_completes_after_floor_reached(tmp_path):
    work, repo, run = _ops_bridge(tmp_path, chars=150)
    _begin(work, repo)
    _next(work, repo)
    for index in range(8):
        state = read_state(run / "repair_state.json")
        if state.status != "active" or state.session.pending is None:
            break
        job = state.session.pending
        candidate = tmp_path / f"deep-{index}.md"
        body = state.session.working_texts[job.beat_id] + "追記。" * 40
        candidate.write_text(body, encoding="utf-8")
        _submit(work, repo, job, candidate=candidate)
    else:
        pytest.fail("repair did not reach a terminal state")
    state = read_state(run / "repair_state.json")
    if state.status == "active":
        _next(work, repo)
        state = read_state(run / "repair_state.json")
    assert state.status == "completed"
    assert state.session.pending is None
    assert all(item.job.operation != "seam" for item in state.session.history)


def test_f3_finish_discards_explicit_deepen_pending(tmp_path):
    work, repo, run = _ops_bridge(tmp_path, chars=210)
    repair_begin(work, scene_id="ch01-001", run_id="run-0001",
                 model="fixture-writer", authorization="explicit scene",
                 repo_root=repo, intent="explicit_deepen")
    _next(work, repo)
    assert read_state(run / "repair_state.json").session.pending is not None
    code, message = repair_finish(work, scene_id="ch01-001", run_id="run-0001",
                                  reason="floor_met", authorization="stop deepen",
                                  repo_root=repo)
    assert code == 0, message
    state = read_state(run / "repair_state.json")
    assert state.status == "completed"
    assert state.session.pending is None
    assert len(state.skipped_jobs) == 1
    assert state.skipped_jobs[0].reason == "floor_met"
    journal = (run / "journal.jsonl").read_text(encoding="utf-8")
    assert "repair_finish" in journal
    again, again_msg = repair_finish(work, scene_id="ch01-001", run_id="run-0001",
                                     reason="floor_met", authorization="stop deepen",
                                     repo_root=repo)
    assert again == 0
    assert "already completed" in again_msg
    assert len(read_state(run / "repair_state.json").skipped_jobs) == 1


def test_f4a_floor_met_reason_refuses_below_floor(tmp_path):
    work, repo, run = _ops_bridge(tmp_path, chars=150)
    _begin(work, repo)
    _next(work, repo)
    with pytest.raises(BridgeError) as caught:
        repair_finish(work, scene_id="ch01-001", run_id="run-0001",
                      reason="floor_met", authorization="too short", repo_root=repo)
    assert caught.value.code == "JOB_CONFLICT"
    assert read_state(run / "repair_state.json").status == "active"


def test_f4b_truncated_next_escalates_and_requires_new_run(tmp_path):
    work, repo, run = _ops_bridge(tmp_path, chars=210, finish_reason="length")
    code, _ = repair_begin(work, scene_id="ch01-001", run_id="run-0001",
                           model="fixture-writer", authorization="truncated required",
                           repo_root=repo)
    assert code == 0
    _next(work, repo)
    state = read_state(run / "repair_state.json")
    assert state.status == "escalated"
    assert state.session.pending is None
    assert any("REQUIRED_UNREPAIRABLE" in note for note in state.notes)
    with pytest.raises(BridgeError) as caught:
        repair_finish(work, scene_id="ch01-001", run_id="run-0001",
                      reason="floor_met", authorization="still truncated", repo_root=repo)
    assert caught.value.code == "JOB_CONFLICT"
    other = tmp_path / "new-run.md"
    other.write_text("新run向けの別稿である。\n", encoding="utf-8")
    with pytest.raises(BridgeError) as receive_error:
        receive(work, scene_id="ch01-001", run_id="run-0001",
                candidate=other, request_id=None)
    assert receive_error.value.code == "JOB_CONFLICT"
    marked = (work / "_metron/ch01-001/marked.md").read_text(encoding="utf-8")
    code, message = repair_finish(work, scene_id="ch01-001", run_id="run-0001",
                                  reason="author_stop", authorization="stop truncated",
                                  repo_root=repo)
    assert code == 0, message
    state = read_state(run / "repair_state.json")
    assert state.status == "escalated"
    assert state.stop_reason == "author_stop"
    assert state.skipped_jobs == []
    journal = (run / "journal.jsonl").read_text(encoding="utf-8")
    assert "repair_finish" in journal
    assert (work / "_metron/ch01-001/marked.md").read_text(encoding="utf-8") == marked
    again, again_msg = repair_finish(work, scene_id="ch01-001", run_id="run-0001",
                                     reason="author_stop", authorization="stop truncated",
                                     repo_root=repo)
    assert again == 0
    assert "already completed" in again_msg


def test_f4b_author_stop_after_begin_without_next(tmp_path):
    work, repo, run = _ops_bridge(tmp_path, chars=210, finish_reason="length")
    repair_begin(work, scene_id="ch01-001", run_id="run-0001",
                 model="fixture-writer", authorization="truncated required",
                 repo_root=repo)
    marked = (work / "_metron/ch01-001/marked.md").read_text(encoding="utf-8")
    code, message = repair_finish(work, scene_id="ch01-001", run_id="run-0001",
                                  reason="author_stop", authorization="stop before next",
                                  repo_root=repo)
    assert code == 0, message
    state = read_state(run / "repair_state.json")
    assert state.status == "escalated"
    assert state.stop_reason == "author_stop"
    assert state.session.pending is None
    assert state.skipped_jobs == []
    assert any("REQUIRED_UNREPAIRABLE" in note for note in state.notes)
    journal = (run / "journal.jsonl").read_text(encoding="utf-8")
    assert "repair_finish" in journal
    assert (work / "_metron/ch01-001/marked.md").read_text(encoding="utf-8") == marked
    again, again_msg = repair_finish(work, scene_id="ch01-001", run_id="run-0001",
                                     reason="author_stop", authorization="stop before next",
                                     repo_root=repo)
    assert again == 0
    assert "already completed" in again_msg
    with pytest.raises(BridgeError) as caught:
        repair_finish(work, scene_id="ch01-001", run_id="run-0001",
                      reason="floor_met", authorization="still truncated", repo_root=repo)
    assert caught.value.code == "JOB_CONFLICT"


def test_missing_pending_job_json_is_stale(tmp_path):
    work, repo, run = _ops_bridge(tmp_path, chars=150)
    _begin(work, repo)
    _next(work, repo)
    job = read_state(run / "repair_state.json").session.pending
    (run / "jobs" / f"{job.job_id}.json").unlink()
    with pytest.raises(BridgeError) as caught:
        repair_finish(work, scene_id="ch01-001", run_id="run-0001",
                      reason="author_stop", authorization="missing job", repo_root=repo)
    assert caught.value.code == "STALE_EVIDENCE"
    assert read_state(run / "repair_state.json").status == "active"
    assert read_state(run / "repair_state.json").skipped_jobs == []


def test_f4e_author_stop_after_scene_floor_no_eligible(tmp_path):
    work, repo, run = _ops_bridge(tmp_path, chars=150, floor=500, expandable=False)
    _begin(work, repo)
    _next(work, repo)
    state = read_state(run / "repair_state.json")
    assert state.status == "escalated"
    assert state.stop_reason is None
    assert state.session.pending is None
    assert any(item.startswith("SCENE_FLOOR_NO_ELIGIBLE") for item in state.notes)
    marked = (work / "_metron/ch01-001/marked.md").read_text(encoding="utf-8")
    code, message = repair_finish(work, scene_id="ch01-001", run_id="run-0001",
                                  reason="author_stop", authorization="stop no eligible",
                                  repo_root=repo)
    assert code == 0, message
    state = read_state(run / "repair_state.json")
    assert state.status == "escalated"
    assert state.stop_reason == "author_stop"
    assert state.skipped_jobs == []
    assert any(item.startswith("SCENE_FLOOR_NO_ELIGIBLE") for item in state.notes)
    journal = (run / "journal.jsonl").read_text(encoding="utf-8")
    assert "repair_finish" in journal
    assert (work / "_metron/ch01-001/marked.md").read_text(encoding="utf-8") == marked
    again, again_msg = repair_finish(work, scene_id="ch01-001", run_id="run-0001",
                                     reason="author_stop", authorization="stop no eligible",
                                     repo_root=repo)
    assert again == 0
    assert "already completed" in again_msg
    with pytest.raises(BridgeError) as caught:
        repair_finish(work, scene_id="ch01-001", run_id="run-0001",
                      reason="floor_met", authorization="still short", repo_root=repo)
    assert caught.value.code == "JOB_CONFLICT"


def test_f4c_author_stop_below_floor_escalates(tmp_path):
    work, repo, run = _ops_bridge(tmp_path, chars=150)
    _begin(work, repo)
    _next(work, repo)
    assert read_state(run / "repair_state.json").session.pending is not None
    code, message = repair_finish(work, scene_id="ch01-001", run_id="run-0001",
                                  reason="author_stop", authorization="stop short",
                                  repo_root=repo)
    assert code == 0, message
    state = read_state(run / "repair_state.json")
    assert state.status == "escalated"
    assert len(state.skipped_jobs) == 1
    assert state.skipped_jobs[0].reason == "author_stop"


def test_f4d_coverage_failure_is_range_mismatch_not_not_needed(tmp_path):
    work, repo, run = _ops_bridge(tmp_path, chars=210)
    marked = work / "_metron/ch01-001/marked.md"
    marked.write_text(marked.read_text(encoding="utf-8").replace(
        "<!--/beat:pack_bag-->", ""), encoding="utf-8")
    receive(work, scene_id="ch01-001", run_id="run-0001",
            candidate=marked, request_id=None)
    with pytest.raises(BridgeError) as caught:
        repair_begin(work, scene_id="ch01-001", run_id="run-0001",
                     model="fixture-writer", authorization="broken map",
                     repo_root=repo)
    assert caught.value.code == "RANGE_MISMATCH"
    assert not (run / "repair_state.json").exists()


def test_f5_no_provider_seam_after_deepen(tmp_path):
    work, repo, run = _ops_bridge(tmp_path, chars=150)
    _begin(work, repo)
    for _ in range(8):
        state = read_state(run / "repair_state.json")
        if state.status != "active" or state.session.pending is None:
            break
        job = state.session.pending
        assert job.operation != "seam"
        candidate = tmp_path / f"{job.job_id}.md"
        body = state.session.working_texts[job.beat_id] + "追記。" * 30
        candidate.write_text(body, encoding="utf-8")
        _submit(work, repo, job, candidate=candidate)
    state = read_state(run / "repair_state.json")
    assert all(item.job.operation != "seam" for item in state.session.history)


def test_f6_marker_rewrite_rejected_without_seam(tmp_path):
    work, repo, run = _ops_bridge(tmp_path, chars=150)
    _begin(work, repo)
    _next(work, repo)
    job = read_state(run / "repair_state.json").session.pending
    candidate = tmp_path / "moved.md"
    candidate.write_text("<!--beat:pack_bag-->移した。<!--/beat:pack_bag-->", encoding="utf-8")
    _submit(work, repo, job, candidate=candidate)
    history = read_state(run / "repair_state.json").session.history
    assert history[0].rejection


def test_cli_repair_finish_and_intent(tmp_path):
    work, repo, run = _ops_bridge(tmp_path, chars=210)
    common = [str(work), "--scene-id", "ch01-001", "--run-id", "run-0001",
              "--repo-root", str(repo)]
    begun = _run_cli("repair-begin", *common, "--model", "fixture-writer",
                     "--authorization", "cli deepen", "--intent", "explicit_deepen")
    assert begun.returncode == 0, begun.stderr
    nxt = _run_cli("repair-next", *common)
    assert nxt.returncode == 0, nxt.stderr
    finished = _run_cli("repair-finish", *common, "--reason", "floor_met",
                        "--authorization", "cli stop")
    assert finished.returncode == 0, finished.stderr
    report = json.loads((run / "report.json").read_text(encoding="utf-8"))
    assert any(item.get("status") == "skipped" for item in report["repair_history"])
