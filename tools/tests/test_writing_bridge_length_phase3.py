"""writing_bridge の規定量調整 Phase 3: CANON 検査の記録・収束ジョブ・改稿工程の参照チェック。"""
from __future__ import annotations

import json

import pytest
import yaml

from test_writing_bridge_length import ADDITION, SCENE, _beat_chars, _write_candidate
from test_writing_bridge_ops_speed import _ops_bridge
from metron.models import LengthTarget
from writing_bridge.errors import BridgeError
from writing_bridge.repair import (
    canon_check, canon_precheck, length_review, read_state, repair_begin, repair_next,
    repair_submit,
)
from writing_bridge.revise import strip_check, strip_record

PASSING = {"completed": True, "facts_before": ["兄が家を出た"],
           "facts_after": ["兄が家を出た"], "findings": [], "condense": []}
FAILING = dict(PASSING, findings=[{"kind": "added", "fact": "兄が鍵を拾った"}])
PRECHECK = {"completed": True, "facts": ["兄が駅へ向かう"], "conflicts": []}


def _begin(work, repo, target, **kwargs):
    return repair_begin(work, model="fixture-writer", authorization="ユーザー依頼: 字数合わせ",
                        repo_root=repo, intent="length", length_target=target, **kwargs, **SCENE)


def _check_file(tmp_path, payload, name="check.json"):
    path = tmp_path / name
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _issued_candidate_result(tmp_path, work, repo, run, job, candidate, payload):
    canon_check(work, job_id=job.job_id, candidate=candidate, repo_root=repo, **SCENE)
    request = json.loads((run / "jobs" / f"{job.job_id}.canon_check.request.json").read_text(
        encoding="utf-8"))
    return _check_file(tmp_path, dict(payload, input_sha256=request["input_sha256"]))


def _issued_precheck_result(tmp_path, work, run, payload, name="precheck.json"):
    canon_precheck(work, check_prompt=True, **SCENE)
    request = json.loads((run / "canon_precheck.request.json").read_text(encoding="utf-8"))
    return _check_file(tmp_path, dict(payload, input_sha256=request["input_sha256"]), name)


def _submit(work, repo, job, candidate, **kwargs):
    return repair_submit(work, job_id=job.job_id, model="fixture-writer", candidate=candidate,
                         error=None, repo_root=repo, **kwargs, **SCENE)


def _deepen_job(tmp_path, work, repo, run, **begin):
    _begin(work, repo, LengthTarget(target_chars=400), **begin)
    repair_next(work, repo_root=repo, **SCENE)
    return _write_candidate(tmp_path, run)


def test_canon_check_writes_prompt_then_records_result(tmp_path):
    work, repo, run = _ops_bridge(tmp_path, chars=220, floor=200)
    job, candidate = _deepen_job(tmp_path, work, repo, run)
    code, message = canon_check(work, job_id=job.job_id, candidate=candidate, repo_root=repo, **SCENE)
    prompt = run / "jobs" / f"{job.job_id}.canon_check.prompt.md"
    assert code == 0 and prompt.is_file() and ADDITION in prompt.read_text(encoding="utf-8")
    code, message = canon_check(work, job_id=job.job_id, candidate=candidate, repo_root=repo,
                                result_path=_issued_candidate_result(tmp_path, work, repo, run, job, candidate, PASSING),
                                checker_model="checker-x", **SCENE)
    assert code == 0 and "passed" in message
    record = json.loads((run / "canon_review.json").read_text(encoding="utf-8"))
    assert record["checks"][0]["passed"] and record["checks"][0]["facts_before"] == ["兄が家を出た"]


def test_passing_check_replaces_the_author_only_with_opt_in(tmp_path):
    work, repo, run = _ops_bridge(tmp_path, chars=220, floor=200)
    job, candidate = _deepen_job(tmp_path, work, repo, run)
    canon_check(work, job_id=job.job_id, candidate=candidate, repo_root=repo,
                result_path=_issued_candidate_result(tmp_path, work, repo, run, job, candidate, PASSING), checker_model="checker-x", **SCENE)
    with pytest.raises(BridgeError) as error:
        _submit(work, repo, job, candidate, review="confirmed")
    assert error.value.code == "MISSING_FIELD"

    work2, repo2, run2 = _ops_bridge(tmp_path / "opt", chars=220, floor=200)
    job2, candidate2 = _deepen_job(tmp_path / "opt", work2, repo2, run2, check_replaces_author=True)
    canon_check(work2, job_id=job2.job_id, candidate=candidate2, repo_root=repo2,
                result_path=_issued_candidate_result(tmp_path, work2, repo2, run2, job2, candidate2, PASSING), checker_model="checker-x", **SCENE)
    _submit(work2, repo2, job2, candidate2, review="confirmed")
    record = json.loads((run2 / "canon_review.json").read_text(encoding="utf-8"))
    assert record["candidates"][0]["authorization"] == "canon-check:checker-x"
    assert read_state(run2 / "repair_state.json").check_replaces_author


def test_failing_check_blocks_unless_the_author_confirms(tmp_path):
    work, repo, run = _ops_bridge(tmp_path, chars=220, floor=200)
    job, candidate = _deepen_job(tmp_path, work, repo, run, check_replaces_author=True)
    code, message = canon_check(work, job_id=job.job_id, candidate=candidate, repo_root=repo,
                                result_path=_issued_candidate_result(tmp_path, work, repo, run, job, candidate, FAILING),
                                checker_model="checker-x", **SCENE)
    assert code == 1 and "OP-E" in message
    with pytest.raises(BridgeError) as error:
        _submit(work, repo, job, candidate, review="confirmed")
    assert error.value.code == "CANON_CHECK_FAILED"
    _submit(work, repo, job, candidate, review="confirmed",
            canon_authorization="著者: 鍵は既出。誤検出")
    record = json.loads((run / "canon_review.json").read_text(encoding="utf-8"))
    assert record["candidates"][0]["authorization"].startswith("著者")


def test_check_result_must_be_valid_json(tmp_path):
    work, repo, run = _ops_bridge(tmp_path, chars=220, floor=200)
    job, candidate = _deepen_job(tmp_path, work, repo, run)
    bad = tmp_path / "bad.json"
    bad.write_text("問題なし", encoding="utf-8")
    with pytest.raises(BridgeError) as error:
        canon_check(work, job_id=job.job_id, candidate=candidate, repo_root=repo,
                    result_path=bad, checker_model="checker-x", **SCENE)
    assert error.value.code == "SCHEMA_UNSUPPORTED"


def test_precheck_by_model_check_needs_opt_in(tmp_path):
    work, repo, run = _ops_bridge(tmp_path, chars=220, floor=200, chronos="ON")
    code, message = canon_precheck(work, check_prompt=True, **SCENE)
    assert (run / "canon_precheck.prompt.md").is_file()
    canon_precheck(work, check_result=_issued_precheck_result(tmp_path, work, run, PRECHECK),
                   checker_model="checker-x", **SCENE)
    with pytest.raises(BridgeError) as error:
        _begin(work, repo, LengthTarget(target_chars=400))
    assert error.value.code == "CANON_PRECHECK_REQUIRED"
    code, message = _begin(work, repo, LengthTarget(target_chars=400), check_replaces_author=True)
    assert code == 0 and "checker-x" in message


def test_precheck_check_with_conflict_blocks(tmp_path):
    work, repo, run = _ops_bridge(tmp_path, chars=220, floor=200, chronos="ON")
    conflict = dict(PRECHECK, conflicts=[{"event_id": "EVT-0002", "description": "本文では窓口で買う"}])
    canon_precheck(work, check_result=_issued_precheck_result(tmp_path, work, run, conflict), checker_model="checker-x",
                   **SCENE)
    with pytest.raises(BridgeError) as error:
        _begin(work, repo, LengthTarget(target_chars=400), check_replaces_author=True)
    assert error.value.code == "CANON_CONFLICT"
    unknown = dict(PRECHECK, conflicts=[{"event_id": "EVT-9999", "description": "x"}])
    with pytest.raises(BridgeError):
        canon_precheck(work, check_result=_issued_precheck_result(tmp_path, work, run, unknown, "u.json"),
                       checker_model="checker-x", **SCENE)


def _write_episodes(work, episodes):
    path = work / "_metron/ch01-001/episodes.yaml"
    path.write_text(yaml.safe_dump({"scene_id": "ch01-001", "episodes": episodes},
                                   allow_unicode=True), encoding="utf-8")


EPISODE = {"id": "E-station", "beat_id": "reach_station",
           "span": {"start": "　二人は家を出て", "end": "立った。"},
           "state_change": [{"kind": "position", "who": "兄", "before": "家", "after": "駅"}]}


def test_condense_job_through_the_bridge(tmp_path):
    work, repo, run = _ops_bridge(tmp_path, chars=230, floor=200)
    _write_episodes(work, [EPISODE])
    current = _beat_chars(work)
    _begin(work, repo, LengthTarget(target_chars=current - 15, max_passes=8))
    repair_next(work, repo_root=repo, **SCENE)
    for _ in range(8):
        job = read_state(run / "repair_state.json").session.pending
        if job.operation == "condense":
            break
        repair_submit(work, job_id=job.job_id, model="fixture-writer", candidate=None,
                      error="skip tighten", review="unverified", repo_root=repo, **SCENE)
    else:
        pytest.fail("no condense job")
    assert job.episode_id == "E-station"
    assert json.loads((run / "jobs" / f"{job.job_id}.json").read_text(encoding="utf-8"))["episode_id"]
    candidate = tmp_path / "condense.md"
    candidate.write_text("　二人は駅に着いた。", encoding="utf-8")
    _, view = length_review(work, job_id=job.job_id, candidate=candidate, repo_root=repo, **SCENE)
    assert "二人は駅に着いた。" in view
    _submit(work, repo, job, candidate, review="confirmed",
            canon_authorization="著者: 駅に着いたことは残る")
    state = read_state(run / "repair_state.json")
    assert state.session.history[-1].rejection is None
    assert "二人は駅に着いた。" in state.session.working_texts["reach_station"]


def test_regular_job_json_keeps_its_shape(tmp_path):
    work, repo, run = _ops_bridge(tmp_path, chars=220, floor=200)
    job, _ = _deepen_job(tmp_path, work, repo, run)
    body = json.loads((run / "jobs" / f"{job.job_id}.json").read_text(encoding="utf-8"))
    assert "episode_id" not in body


def test_invalid_episodes_file_stops_the_begin(tmp_path):
    work, repo, _ = _ops_bridge(tmp_path, chars=230, floor=200)
    _write_episodes(work, [dict(EPISODE, beat_id="no_such_beat")])
    with pytest.raises(BridgeError) as error:
        _begin(work, repo, LengthTarget(target_chars=400))
    assert error.value.code == "SCHEMA_UNSUPPORTED"


# ── 改稿工程（OP-S） ───────────────────────────────────────────


def test_strip_check_reports_carry_back_and_refuses_record(tmp_path):
    work, _, _ = _ops_bridge(tmp_path, chars=220, floor=200)
    _write_episodes(work, [dict(EPISODE, carry_back=[{"what": "券売機", "used_at": "ch02-001"}])])
    code, report = strip_check(work, scene_id="ch01-001", episode_id="E-station")
    assert code == 1 and "券売機 → ch02-001" in report and "収束（OP-C）に戻す" in report
    with pytest.raises(BridgeError) as error:
        strip_record(work, scene_id="ch01-001", episode_id="E-station", reason="不要",
                     authorization="ユーザー承認")
    assert error.value.code == "STRIP_REFERENCED"


def test_strip_without_references_is_recorded_once(tmp_path):
    work, _, _ = _ops_bridge(tmp_path, chars=220, floor=200)
    quote = "母が時刻表を一度だけ確かめる。"
    code, report = strip_check(work, scene_id="ch01-001", quote=quote)
    assert code == 0 and "参照なし" in report
    code, message = strip_record(work, scene_id="ch01-001", quote=quote, reason="山場の前で軽くする",
                                 authorization="ユーザー承認: 改稿")
    path = work / "_metron/ch01-001/canon_deletions.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert data["deletions"][0]["text"] == quote and "refine run" in message
    strip_record(work, scene_id="ch01-001", quote=quote, reason="同じ", authorization="ユーザー承認")
    assert len(yaml.safe_load(path.read_text(encoding="utf-8"))["deletions"]) == 1


def test_strip_check_lists_scene_events_when_chronos_is_on(tmp_path):
    work, _, _ = _ops_bridge(tmp_path, chars=220, floor=200, chronos="ON")
    code, report = strip_check(work, scene_id="ch01-001", quote="母が時刻表を一度だけ確かめる。")
    assert "EVT-0001" in report and "EVT-0002" in report


def test_strip_target_must_be_found_once(tmp_path):
    work, _, _ = _ops_bridge(tmp_path, chars=220, floor=200)
    with pytest.raises(BridgeError) as error:
        strip_check(work, scene_id="ch01-001", quote="存在しない一文。")
    assert error.value.code == "RANGE_MISMATCH"


@pytest.mark.parametrize("payload", [
    {}, {"completed": True}, dict(PASSING, completed=False),
    dict(PASSING, facts_before=[]),
])
def test_incomplete_check_cannot_replace_author(tmp_path, payload):
    work, repo, run = _ops_bridge(tmp_path, chars=220, floor=200)
    job, candidate = _deepen_job(tmp_path, work, repo, run, check_replaces_author=True)
    canon_check(work, job_id=job.job_id, candidate=candidate, repo_root=repo, **SCENE)
    with pytest.raises(BridgeError) as error:
        canon_check(work, job_id=job.job_id, candidate=candidate, repo_root=repo,
                    result_path=_check_file(tmp_path, payload), checker_model="checker-x", **SCENE)
    assert error.value.code == "SCHEMA_UNSUPPORTED"
    with pytest.raises(BridgeError) as error:
        _submit(work, repo, job, candidate, review="confirmed")
    assert error.value.code == "MISSING_FIELD"
    assert read_state(run / "repair_state.json").session.history == []


@pytest.mark.parametrize("payload", [
    {}, {"facts": [], "conflicts": []},
    dict(PRECHECK, facts=[]), dict(PRECHECK, completed=False),
])
def test_incomplete_precheck_cannot_replace_author(tmp_path, payload):
    work, repo, run = _ops_bridge(tmp_path, chars=220, floor=200, chronos="ON")
    path = _issued_precheck_result(tmp_path, work, run, payload)
    with pytest.raises(BridgeError) as error:
        canon_precheck(work, check_result=path, checker_model="checker-x", **SCENE)
    assert error.value.code == "SCHEMA_UNSUPPORTED"
    with pytest.raises(BridgeError) as error:
        _begin(work, repo, LengthTarget(target_chars=400), check_replaces_author=True)
    assert error.value.code == "CANON_PRECHECK_REQUIRED"


def test_check_result_needs_an_issued_request(tmp_path):
    work, repo, run = _ops_bridge(tmp_path, chars=220, floor=200)
    job, candidate = _deepen_job(tmp_path, work, repo, run)
    path = _check_file(tmp_path, dict(PASSING, input_sha256="sha256:" + "0" * 64))
    with pytest.raises(BridgeError) as error:
        canon_check(work, job_id=job.job_id, candidate=candidate, repo_root=repo,
                    result_path=path, checker_model="checker-x", **SCENE)
    assert error.value.code == "UNKNOWN_REF"


def test_check_result_is_stale_after_candidate_changes_and_after_reissue(tmp_path):
    work, repo, run = _ops_bridge(tmp_path, chars=220, floor=200)
    job, candidate = _deepen_job(tmp_path, work, repo, run, check_replaces_author=True)
    result = _issued_candidate_result(tmp_path, work, repo, run, job, candidate, PASSING)
    candidate.write_text(candidate.read_text(encoding="utf-8") + "\n\n　兄は拾った鍵を鞄へ入れた。",
                         encoding="utf-8")
    for reissue in (False, True):
        if reissue:
            canon_check(work, job_id=job.job_id, candidate=candidate, repo_root=repo, **SCENE)
        with pytest.raises(BridgeError) as error:
            canon_check(work, job_id=job.job_id, candidate=candidate, repo_root=repo,
                        result_path=result, checker_model="checker-x", **SCENE)
        assert error.value.code == "STALE_EVIDENCE"
    with pytest.raises(BridgeError) as error:
        _submit(work, repo, job, candidate, review="confirmed")
    assert error.value.code == "MISSING_FIELD"


def test_check_result_cannot_be_copied_to_another_run(tmp_path):
    work, repo, run = _ops_bridge(tmp_path / "one", chars=220, floor=200)
    job, candidate = _deepen_job(tmp_path / "one", work, repo, run)
    result = _issued_candidate_result(tmp_path, work, repo, run, job, candidate, PASSING)
    other_work, other_repo, other_run = _ops_bridge(tmp_path / "two", chars=220, floor=200)
    other_job, other_candidate = _deepen_job(tmp_path / "two", other_work, other_repo, other_run)
    canon_check(other_work, job_id=other_job.job_id, candidate=other_candidate,
                repo_root=other_repo, **SCENE)
    with pytest.raises(BridgeError) as error:
        canon_check(other_work, job_id=other_job.job_id, candidate=other_candidate,
                    repo_root=other_repo, result_path=result, checker_model="checker-x", **SCENE)
    assert error.value.code == "STALE_EVIDENCE"


def test_precheck_result_needs_an_issued_request(tmp_path):
    work, repo, run = _ops_bridge(tmp_path, chars=220, floor=200, chronos="ON")
    result = _check_file(tmp_path, dict(PRECHECK, input_sha256="sha256:" + "0" * 64))
    with pytest.raises(BridgeError) as error:
        canon_precheck(work, check_result=result, checker_model="checker-x", **SCENE)
    assert error.value.code == "UNKNOWN_REF"


def test_precheck_result_is_stale_after_events_change(tmp_path):
    work, repo, run = _ops_bridge(tmp_path, chars=220, floor=200, chronos="ON")
    result = _issued_precheck_result(tmp_path, work, run, PRECHECK)
    path = work / "chronos/events/ch01.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["events"][0]["effects"] = ["EVT-0002"]
    data["events"][0]["effects_on"]["CHR-a"]["outfit"] = "school"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    for reissue in (False, True):
        if reissue:
            canon_precheck(work, check_prompt=True, **SCENE)
        with pytest.raises(BridgeError) as error:
            canon_precheck(work, check_result=result, checker_model="checker-x", **SCENE)
        assert error.value.code == "STALE_EVIDENCE"


def test_precheck_prompt_and_author_view_include_event_effects(tmp_path):
    work, repo, run = _ops_bridge(tmp_path, chars=220, floor=200, chronos="ON")
    path = work / "chronos/events/ch01.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["events"][0]["effects"] = ["EVT-0002"]
    data["events"][0]["effects_on"]["CHR-a"]["outfit"] = "school"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    canon_precheck(work, check_prompt=True, **SCENE)
    prompt = (run / "canon_precheck.prompt.md").read_text(encoding="utf-8")
    assert '"effects"' in prompt and '"EVT-0002"' in prompt
    assert '"effects_on"' in prompt and '"school"' in prompt
    assert '"time"' in prompt and '"location"' in prompt
    _, view = canon_precheck(work, **SCENE)
    assert '"effects"' in view and '"school"' in view


@pytest.mark.parametrize("quote", [
    "二人は家を出て、駅の券売機の前に立った。", "駅の券売機の前に立った。",
])
def test_quote_cannot_bypass_registered_carry_back(tmp_path, quote):
    work, _, _ = _ops_bridge(tmp_path, chars=220, floor=200)
    _write_episodes(work, [dict(EPISODE, carry_back=[{"what": "券売機", "used_at": "ch02-001"}])])
    code, report = strip_check(work, scene_id="ch01-001", quote=quote)
    assert code == 1 and "券売機 → ch02-001" in report
    with pytest.raises(BridgeError) as error:
        strip_record(work, scene_id="ch01-001", quote=quote,
                     reason="test", authorization="著者承認")
    assert error.value.code == "STRIP_REFERENCED"
    assert not (work / "_metron/ch01-001/canon_deletions.yaml").exists()


def test_disjoint_quote_does_not_inherit_unrelated_carry_back(tmp_path):
    work, _, _ = _ops_bridge(tmp_path, chars=220, floor=200)
    _write_episodes(work, [dict(EPISODE, carry_back=[{"what": "券売機", "used_at": "ch02-001"}])])
    code, _ = strip_check(work, scene_id="ch01-001", quote="母が時刻表を一度だけ確かめる。")
    assert code == 0


def test_episode_selection_also_checks_overlapping_protected_contracts(tmp_path):
    work, _, _ = _ops_bridge(tmp_path, chars=220, floor=200)
    protected = dict(EPISODE, id="E-protected",
                     span={"start": "券売機", "end": "立った。"},
                     carry_back=[{"what": "券売機", "used_at": "ch02-001"}])
    _write_episodes(work, [EPISODE, protected])
    code, report = strip_check(work, scene_id="ch01-001", episode_id=EPISODE["id"])
    assert code == 1 and "券売機 → ch02-001" in report
