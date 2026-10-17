from __future__ import annotations

import json

import pytest

from test_writing_bridge import _run_cli
from test_writing_bridge_ops_speed import _ops_bridge
from metron.analyze import analyze_marked_text
from metron.contract import load_beat_plan
from metron.length import assembled_chars
from metron.models import LengthTarget
from metron.repair import _text_by_beat
from writing_bridge.errors import BridgeError
from writing_bridge.repair import (
    canon_precheck, length_review, read_state, repair_begin, repair_next, repair_submit,
)

SCENE = dict(scene_id="ch01-001", run_id="run-0001")
ADDITION = "改札の電子音が遠くで鳴り、ホームを渡る風が冷たかった。"


def _beat_chars(work) -> int:
    plan = load_beat_plan(work / "_metron/ch01-001/beats.yaml")
    marked = (work / "_metron/ch01-001/marked.md").read_text(encoding="utf-8")
    analyzed = analyze_marked_text(marked, plan, run=1)
    return assembled_chars(plan, _text_by_beat(analyzed.clean_text, plan, analyzed.spans))


def _begin(work, repo, target: LengthTarget | None):
    return repair_begin(work, model="fixture-writer", authorization="ユーザー依頼: 4000字に合わせて",
                        repo_root=repo, intent="length", length_target=target, **SCENE)


def _pending(run):
    return read_state(run / "repair_state.json").session.pending


def _write_candidate(tmp_path, run, name="deep.md"):
    state = read_state(run / "repair_state.json")
    job = state.session.pending
    path = tmp_path / name
    path.write_text(state.session.working_texts[job.beat_id].rstrip("\n") + "\n\n　" + ADDITION,
                    encoding="utf-8")
    return job, path


def test_length_rejects_band_below_floor(tmp_path):
    work, repo, _ = _ops_bridge(tmp_path, chars=220, floor=200)
    with pytest.raises(BridgeError) as error:
        _begin(work, repo, LengthTarget(target_chars=150))
    assert error.value.code == "LENGTH_CONFIG"


def test_length_requires_a_target(tmp_path):
    work, repo, _ = _ops_bridge(tmp_path, chars=220, floor=200)
    with pytest.raises(BridgeError) as error:
        _begin(work, repo, None)
    assert error.value.code == "MISSING_FIELD"


def test_length_in_band_is_not_needed(tmp_path):
    work, repo, run = _ops_bridge(tmp_path, chars=220, floor=200)
    with pytest.raises(BridgeError) as error:
        _begin(work, repo, LengthTarget(target_chars=_beat_chars(work)))
    assert error.value.code == "REPAIR_NOT_NEEDED"
    assert not (run / "repair_state.json").exists()


def test_length_refuses_scope_flags_of_regular_repair(tmp_path):
    work, repo, _ = _ops_bridge(tmp_path, chars=220, floor=200)
    with pytest.raises(BridgeError) as error:
        repair_begin(work, model="fixture-writer", authorization="x", repo_root=repo,
                     intent="length", scope="beats", beat_ids=["pack_bag"],
                     length_target=LengthTarget(target_chars=400), **SCENE)
    assert error.value.code == "JOB_CONFLICT"


def test_chronos_off_skips_precheck_and_records_note(tmp_path):
    work, repo, run = _ops_bridge(tmp_path, chars=220, floor=200)
    code, message = _begin(work, repo, LengthTarget(target_chars=400))
    assert code == 0 and "CANON_PRECHECK_SKIPPED" in message
    assert _pending(run) is None
    repair_next(work, repo_root=repo, **SCENE)
    job = _pending(run)
    assert job.operation == "deepen"
    assert "既出事実" in job.prompt


def test_events_require_author_precheck_and_block_on_conflict(tmp_path):
    work, repo, run = _ops_bridge(tmp_path, chars=220, floor=200, chronos="ON")
    target = LengthTarget(target_chars=400)
    with pytest.raises(BridgeError) as missing:
        _begin(work, repo, target)
    assert missing.value.code == "CANON_PRECHECK_REQUIRED"
    _, view = canon_precheck(work, **SCENE)
    assert "EVT-0001" in view and "兄" in view
    assert not (run / "canon_review.json").exists()
    canon_precheck(work, result="conflict", authorization="著者: 切符の件が食い違う", **SCENE)
    with pytest.raises(BridgeError) as conflict:
        _begin(work, repo, target)
    assert conflict.value.code == "CANON_CONFLICT"
    canon_precheck(work, result="no_conflict", authorization="著者: 矛盾なし", **SCENE)
    code, message = _begin(work, repo, target)
    assert code == 0 and "CANON_PRECHECK_OK" in message


def test_precheck_goes_stale_when_events_change(tmp_path):
    work, repo, _ = _ops_bridge(tmp_path, chars=220, floor=200, chronos="ON")
    canon_precheck(work, result="no_conflict", authorization="著者: 矛盾なし", **SCENE)
    events = work / "chronos/events/ch01.yaml"
    events.write_text(events.read_text(encoding="utf-8").replace(
        "券売機で切符を買うと話す", "窓口で切符を買うと話す"), encoding="utf-8")
    with pytest.raises(BridgeError) as error:
        _begin(work, repo, LengthTarget(target_chars=400))
    assert error.value.code == "STALE_EVIDENCE"


def test_precheck_requires_authorization_when_recording(tmp_path):
    work, _, _ = _ops_bridge(tmp_path, chars=220, floor=200, chronos="ON")
    with pytest.raises(BridgeError) as error:
        canon_precheck(work, result="no_conflict", authorization="", **SCENE)
    assert error.value.code == "MISSING_FIELD"


def test_confirmed_candidate_needs_author_fact_confirmation(tmp_path):
    work, repo, run = _ops_bridge(tmp_path, chars=220, floor=200)
    _begin(work, repo, LengthTarget(target_chars=400))
    repair_next(work, repo_root=repo, **SCENE)
    job, candidate = _write_candidate(tmp_path, run)
    _, view = length_review(work, job_id=job.job_id, candidate=candidate, repo_root=repo, **SCENE)
    assert ADDITION in view and "元文に無い文" in view
    with pytest.raises(BridgeError) as error:
        repair_submit(work, job_id=job.job_id, model="fixture-writer", candidate=candidate,
                      error=None, review="confirmed", repo_root=repo, **SCENE)
    assert error.value.code == "MISSING_FIELD"
    assert read_state(run / "repair_state.json").session.history == []
    repair_submit(work, job_id=job.job_id, model="fixture-writer", candidate=candidate,
                  error=None, review="confirmed", repo_root=repo,
                  canon_authorization="著者: 出来事の追加・変更・欠落なし", **SCENE)
    record = json.loads((run / "canon_review.json").read_text(encoding="utf-8"))
    entry = record["candidates"][0]
    assert entry["job_id"] == job.job_id and entry["review"] == "confirmed"
    assert entry["authorization"].startswith("著者") and entry["new_sentences"] == 1
    history = read_state(run / "repair_state.json").session.history
    assert history[0].rejection is None


def test_rejected_candidate_is_recorded_and_not_adopted(tmp_path):
    work, repo, run = _ops_bridge(tmp_path, chars=220, floor=200)
    _begin(work, repo, LengthTarget(target_chars=400, max_passes=1))
    repair_next(work, repo_root=repo, **SCENE)
    job, candidate = _write_candidate(tmp_path, run)
    before = read_state(run / "repair_state.json").session.working_texts[job.beat_id]
    repair_submit(work, job_id=job.job_id, model="fixture-writer", candidate=candidate,
                  error=None, review="rejected", repo_root=repo, **SCENE)
    state = read_state(run / "repair_state.json")
    assert state.session.history[0].rejection is not None
    assert state.session.working_texts[job.beat_id] == before
    assert state.status == "escalated"
    assert any(note.startswith("LENGTH_MAX_PASSES") for note in state.notes)
    record = json.loads((run / "canon_review.json").read_text(encoding="utf-8"))
    assert record["candidates"][0]["review"] == "rejected"


def test_cli_length_begin_and_review(tmp_path):
    work, repo, run = _ops_bridge(tmp_path, chars=220, floor=200)
    begun = _run_cli("repair-begin", str(work), "--scene-id", "ch01-001", "--run-id", "run-0001",
                     "--model", "fixture-writer", "--authorization", "ユーザー依頼",
                     "--intent", "length", "--target-chars", "400", "--repo-root", str(repo))
    assert begun.returncode == 0, begun.stderr
    bad = _run_cli("repair-begin", str(work), "--scene-id", "ch01-001", "--run-id", "run-0001",
                   "--model", "fixture-writer", "--authorization", "ユーザー依頼",
                   "--intent", "length", "--length-scope", "beat", "--repo-root", str(repo))
    assert bad.returncode == 2 and "MISSING_FIELD" in bad.stderr
    _run_cli("repair-next", str(work), "--scene-id", "ch01-001", "--run-id", "run-0001",
             "--repo-root", str(repo))
    job, candidate = _write_candidate(tmp_path, run)
    shown = _run_cli("length-review", str(work), "--scene-id", "ch01-001", "--run-id", "run-0001",
                     "--job-id", job.job_id, "--candidate", str(candidate), "--repo-root", str(repo))
    assert shown.returncode == 0 and ADDITION in shown.stdout


def test_length_completes_inside_band_after_confirmed_deepen(tmp_path):
    work, repo, run = _ops_bridge(tmp_path, chars=220, floor=200)
    goal = _beat_chars(work) + len("\n\n　" + ADDITION)
    _begin(work, repo, LengthTarget(target_chars=goal))
    repair_next(work, repo_root=repo, **SCENE)
    job, candidate = _write_candidate(tmp_path, run)
    repair_submit(work, job_id=job.job_id, model="fixture-writer", candidate=candidate,
                  error=None, review="confirmed", repo_root=repo,
                  canon_authorization="著者: 出来事の追加・変更・欠落なし", **SCENE)
    state = read_state(run / "repair_state.json")
    assert state.status == "completed"
    assert any(note.startswith("LENGTH_IN_BAND") for note in state.notes)
    assert any(note.startswith("CANON_PRECHECK_SKIPPED") for note in state.notes)
    assert ADDITION in (work / state.output_path).read_text(encoding="utf-8")


def test_finish_below_band_escalates_even_when_floor_is_met(tmp_path):
    from writing_bridge.repair import repair_finish
    work, repo, run = _ops_bridge(tmp_path, chars=220, floor=200)
    _begin(work, repo, LengthTarget(target_chars=506))
    repair_next(work, repo_root=repo, **SCENE)
    repair_finish(work, reason="floor_met", authorization="ユーザー: ここで止める",
                  repo_root=repo, **SCENE)
    state = read_state(run / "repair_state.json")
    assert state.status == "escalated"
    assert any(note.startswith("LENGTH_NOT_IN_BAND") for note in state.notes)


def test_resubmitting_the_same_result_is_idempotent(tmp_path):
    work, repo, run = _ops_bridge(tmp_path, chars=220, floor=200)
    _begin(work, repo, LengthTarget(target_chars=400))
    repair_next(work, repo_root=repo, **SCENE)
    job, candidate = _write_candidate(tmp_path, run)
    arguments = dict(job_id=job.job_id, model="fixture-writer", candidate=candidate, error=None,
                     review="confirmed", repo_root=repo,
                     canon_authorization="著者: 出来事の追加・変更・欠落なし", **SCENE)
    repair_submit(work, **arguments)
    code, _ = repair_submit(work, **arguments)
    assert code in (0, 1)
    state = read_state(run / "repair_state.json")
    assert [item.job.job_id for item in state.session.history] == [job.job_id]
    record = json.loads((run / "canon_review.json").read_text(encoding="utf-8"))
    assert [item["job_id"] for item in record["candidates"]] == [job.job_id]
    changed = dict(arguments, review="rejected")
    with pytest.raises(BridgeError) as error:
        repair_submit(work, **changed)
    assert error.value.code == "JOB_CONFLICT"
