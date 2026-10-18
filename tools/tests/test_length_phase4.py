"""規定量調整 Phase 4（現場フィードバック D14〜D17）の回帰テスト。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from test_metron import _beat, _calibration, _plan
from test_metron_length import TEXTS
from test_writing_bridge_length import ADDITION, SCENE, _beat_chars, _write_candidate
from test_writing_bridge_ops_speed import _ops_bridge
from metron.analyze import analyze_marked_text
from metron.contract_fix import CONTRACT_FIX_TOKEN, ContractFixSpec
from metron.length import LENGTH_TOKEN, LengthSpec
from metron.models import LengthTarget
from metron.repair import marked_text_for_measurement
from metron.repair_steps import RepairJob, begin_repair, next_job, submit_result
from writing_bridge.errors import BridgeError
from writing_bridge.repair import (
    canon_precheck, read_state, repair_begin, repair_next, repair_submit, repair_summary,
)

import novel_text_rewrite_lint as lint

ROOT = Path(__file__).resolve().parents[2]


def _state(texts, beats, *, floor=1, calibration=None, **session):
    plan = _plan(*beats, chars_floor=floor)
    analyzed = analyze_marked_text(marked_text_for_measurement(plan, texts), plan, run=1)
    return begin_repair(analyzed.metrics, plan, calibration or _calibration(),
                        clean_text=analyzed.clean_text, spans=analyzed.spans, model="m",
                        seam_enabled=False, **session)


def _drive(state, respond, limit=12):
    jobs = []
    for _ in range(limit):
        result = next_job(state)
        if not isinstance(result, RepairJob):
            return result, jobs
        jobs.append(result)
        candidate, error = respond(result, state.working_texts.get(result.beat_id, ""))
        submit_result(state, job_id=result.job_id, model="m", candidate=candidate, error=error,
                      review="confirmed")
    pytest.fail("repair did not stop")


# ── D17: 欠落 Beat を length の中で先に埋める ───────────────────────


def _missing_session(max_passes=1):
    texts = dict(TEXTS, b="　短い。")
    beats = [_beat("a", chars_hint=10), _beat("b", chars_hint=400)]
    return _state(texts, beats, length=LengthSpec(
        target=LengthTarget(target_chars=300, max_passes=max_passes)))


def test_length_fills_missing_beat_before_adjusting():
    state = _missing_session(max_passes=1)
    filled = "　券売機の前で、兄は財布の中の硬貨を一枚ずつ数えた。" * 4

    def respond(job, text):
        if job.operation == "regenerate":
            return filled, None
        return text.rstrip("\n") + "\n\n　改札の電子音が遠くで鳴り、ホームを渡る風が冷たかった。", None

    result, jobs = _drive(state, respond)
    assert [job.operation for job in jobs][:2] == ["regenerate", "deepen"]
    assert jobs[0].beat_id == "b"
    assert any(note.startswith("LENGTH_MISSING_FILLED: b") for note in result.notes)


def test_unfilled_missing_beat_stops_without_adjusting():
    state = _missing_session(max_passes=3)
    result, jobs = _drive(state, lambda job, text: ("", "provider failed"))
    assert [job.operation for job in jobs] == ["regenerate"]
    assert LENGTH_TOKEN in result.escalated_beats
    assert any(note.startswith("LENGTH_REQUIRED_UNREPAIRED") for note in result.notes)


# ── D16: 床に届いたあとの EndingRush は報告だけ ─────────────────────


ENDING_TEXTS = {
    "a": "　朝の玄関で、兄は旅行用の上着に袖を通した。母が時刻表を一度だけ確かめる。" * 5,
    "b": "　二人は家を出て、駅までの坂を下った。兄は財布の中の硬貨を数えた。" * 5,
    "c": "　二人は駅に着いた。改札の前で立ち止まる。",
    "d": "　兄は切符を買った。",
}


def _ending_rush_state(*, floor, **session):
    beats = [_beat(beat_id, chars_hint=20) for beat_id in ENDING_TEXTS]
    calibration = _calibration(ending_rush_threshold=0.5, missing_span_ratio=0.0,
                               beat_thin_ratio=0.01)
    return _state(ENDING_TEXTS, beats, floor=floor, calibration=calibration, **session)


def test_ending_rush_after_floor_is_reported_not_regenerated():
    """現場（043 第2章）: 開始時は床未達、Deepen で床を超えたあとに末尾再生成が残っていた。"""
    from metron.length import assembled_chars
    plan = _plan(*[_beat(beat_id, chars_hint=20) for beat_id in ENDING_TEXTS])
    floor = assembled_chars(plan, ENDING_TEXTS) + 10
    addition = "\n\n　改札の電子音が遠くで鳴り、ホームを渡る風が冷たかった。"
    result, jobs = _drive(_ending_rush_state(floor=floor),
                          lambda job, text: (text.rstrip("\n") + addition, None))
    operations = [(job.operation, job.beat_id) for job in jobs]
    assert operations and all(operation == "deepen" for operation, _ in operations)
    assert ("regenerate", "d") not in operations
    assert any(note.startswith("ENDING_RUSH_ADVISORY") for note in result.notes)


def test_explicit_ending_rush_still_regenerates():
    state = _ending_rush_state(floor=1, force_ending_rush=True)
    job = next_job(state)
    assert isinstance(job, RepairJob) and job.operation == "regenerate" and job.beat_id == "d"


# ── D16b: 契約修正の再生成 ───────────────────────────────────────


def _fix_state():
    beats = [_beat("a", chars_hint=10), _beat("b", chars_hint=15)]
    return _state(TEXTS, beats, contract_fix=ContractFixSpec(
        beat_ids=["b"], instruction="上がらず、湯船のまま休憩室を思い出す"))


def test_contract_fix_accepts_shorter_text_above_the_beat_floor():
    state = _fix_state()
    job = next_job(state)
    assert job.operation == "regenerate" and "湯船のまま休憩室を思い出す" in job.prompt
    shorter = "　二人は湯船のまま、休憩室を思い出した。"
    assert len(shorter) < len(TEXTS["b"])
    submit_result(state, job_id=job.job_id, model="m", candidate=shorter, review="confirmed")
    assert state.history[-1].rejection is None
    result = next_job(state)
    assert not isinstance(result, RepairJob)
    assert result.beat_texts["b"].strip() == shorter.strip()


def test_contract_fix_allows_a_second_attempt_then_escalates():
    state = _fix_state()
    first = next_job(state)
    submit_result(state, job_id=first.job_id, model="m", candidate="　短い。", review="confirmed")
    assert "below the beat floor" in state.history[-1].rejection
    second = next_job(state)
    assert second.beat_id == "b" and second.attempt == 2
    submit_result(state, job_id=second.job_id, model="m", candidate="　短い。", review="confirmed")
    result = next_job(state)
    assert CONTRACT_FIX_TOKEN in result.escalated_beats


def test_length_and_contract_fix_are_separate_sessions():
    with pytest.raises(ValueError):
        _state(TEXTS, [_beat("a"), _beat("b")],
               length=LengthSpec(target=LengthTarget(target_chars=300)),
               contract_fix=ContractFixSpec(beat_ids=["a"], instruction="x"))


# ── writing_bridge ───────────────────────────────────────────────


def _begin_length(work, repo, target, **kwargs):
    return repair_begin(work, model="fixture-writer", authorization="ユーザー依頼: 字数合わせ",
                        repo_root=repo, intent="length", length_target=target, **kwargs, **SCENE)


def test_bridge_length_begins_with_a_missing_beat(tmp_path):
    work, repo, run = _ops_bridge(tmp_path, chars=220, floor=200)
    path = repo / "config" / "metron_models.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["models"]["fixture-writer"]["missing_span_ratio"] = 0.95
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    code, _ = _begin_length(work, repo, LengthTarget(target_chars=400))
    assert code == 0
    repair_next(work, repo_root=repo, **SCENE)
    assert read_state(run / "repair_state.json").session.pending.operation == "regenerate"


def test_agent_precheck_is_accepted_without_asking_the_author(tmp_path):
    work, repo, run = _ops_bridge(tmp_path, chars=220, floor=200, chronos="ON")
    canon_precheck(work, result="no_conflict", by="agent",
                   authorization="エージェント照合: EVT-0001〜0002 と本文に食い違いなし", **SCENE)
    code, message = _begin_length(work, repo, LengthTarget(target_chars=400))
    assert code == 0 and "the agent" in message
    record = json.loads((run / "canon_review.json").read_text(encoding="utf-8"))
    assert record["pre_check"]["source"] == "agent"


def test_summary_is_shown_once_and_records_the_answer(tmp_path):
    work, repo, run = _ops_bridge(tmp_path, chars=220, floor=200)
    goal = _beat_chars(work) + len("\n\n　" + ADDITION)
    _begin_length(work, repo, LengthTarget(target_chars=goal))
    repair_next(work, repo_root=repo, **SCENE)
    with pytest.raises(BridgeError) as error:
        repair_summary(work, repo_root=repo, accept=True, authorization="著者: よい", **SCENE)
    assert error.value.code == "JOB_CONFLICT"
    job, candidate = _write_candidate(tmp_path, run)
    repair_submit(work, job_id=job.job_id, model="fixture-writer", candidate=candidate,
                  error=None, review="confirmed", repo_root=repo, **SCENE)
    code, text = repair_summary(work, repo_root=repo, **SCENE)
    assert code == 0 and "主要な変化の報告" in text and ADDITION in text
    assert "agent:mechanical-checks" in text and "この内容で保存してよいか" in text
    assert "場面契約と次章" in text
    repair_summary(work, repo_root=repo, accept=True, authorization="著者: これでよい", **SCENE)
    record = json.loads((run / "canon_review.json").read_text(encoding="utf-8"))
    assert record["final_review"]["authorization"] == "著者: これでよい"
    assert record["final_review"]["status"] == "completed"


def _begin_fix(work, repo, **kwargs):
    return repair_begin(work, model="fixture-writer", authorization="ユーザー依頼: 章末を契約に合わせる",
                        repo_root=repo, intent="contract_fix", scope="beats",
                        beat_ids=["reach_station"], **kwargs, **SCENE)


def test_contract_fix_needs_beats_and_instruction(tmp_path):
    work, repo, _ = _ops_bridge(tmp_path, chars=220, floor=200)
    with pytest.raises(BridgeError) as error:
        _begin_fix(work, repo)
    assert error.value.code == "MISSING_FIELD"
    with pytest.raises(BridgeError):
        repair_begin(work, model="fixture-writer", authorization="x", repo_root=repo,
                     intent="auto", instruction="x", **SCENE)


def test_contract_fix_requires_the_author_and_completes(tmp_path):
    work, repo, run = _ops_bridge(tmp_path, chars=220, floor=200)
    _begin_fix(work, repo, instruction="二人は駅に入らず、券売機の前で引き返す")
    repair_next(work, repo_root=repo, **SCENE)
    job = read_state(run / "repair_state.json").session.pending
    assert job.operation == "regenerate"
    candidate = tmp_path / "fix.md"
    # 場面の床（200字）を割らない長さにする（割ると CONTRACT_FIX_SCENE_FLOOR で escalated）。
    candidate.write_text("　二人は券売機の前まで来たが、切符を買わずに引き返した。" * 6, encoding="utf-8")
    with pytest.raises(BridgeError) as error:
        repair_submit(work, job_id=job.job_id, model="fixture-writer", candidate=candidate,
                      error=None, review="confirmed", repo_root=repo, **SCENE)
    assert error.value.code == "MISSING_FIELD"
    repair_submit(work, job_id=job.job_id, model="fixture-writer", candidate=candidate,
                  error=None, review="confirmed", repo_root=repo,
                  canon_authorization="著者: 引き返す形で契約どおり", **SCENE)
    state = read_state(run / "repair_state.json")
    assert state.session.history[-1].rejection is None
    assert state.status == "completed"


# ── lint: METRON の印の行は体裁チェックの対象外 ─────────────────────


def test_marker_lines_are_not_paragraph_indent_findings(tmp_path, monkeypatch):
    monkeypatch.setenv(lint.ENV_RULES, str(ROOT / "_how_to.example" / "novel_text_rewrite_rules.yaml"))
    work = tmp_path / "work"
    (work / "_novel_text").mkdir(parents=True)
    (work / "_novel_text" / "novel_text01.md").write_text(
        "# 第一章\n\n<!--beat:pack_bag-->\n　朝の玄関で、兄は上着を着た。\n<!--/beat:pack_bag-->\n",
        encoding="utf-8")
    result = lint.run_lint(work, profile="grammar", root=ROOT)
    assert not [item for item in result["issues"] if item["rule_id"] == "paragraph_indent"]


# ── レビュー r11: 欠落の再判定・契約修正の保護条件・場面床・並べ替えの提示 ─────


def test_regenerated_beat_that_is_still_missing_stops_the_adjustment():
    state = _missing_session(max_passes=3)
    result, jobs = _drive(state, lambda job, text: ("　短。", None))
    assert [job.operation for job in jobs] == ["regenerate"]
    assert LENGTH_TOKEN in result.escalated_beats
    assert any(note.startswith("LENGTH_REQUIRED_UNREPAIRED") and "b" in note
               for note in result.notes)


def test_contract_fix_refuses_a_truncated_draft(tmp_path):
    work, repo, run = _ops_bridge(tmp_path, chars=220, floor=200, finish_reason="length")
    with pytest.raises(BridgeError) as error:
        _begin_fix(work, repo, instruction="券売機の前で引き返す")
    assert error.value.code == "JOB_CONFLICT" and "GenerationTruncated" in str(error.value)
    assert not (run / "repair_state.json").exists()


def test_contract_fix_below_the_scene_floor_escalates_and_keeps_the_candidate():
    beats = [_beat("a", chars_hint=10), _beat("b", chars_hint=15)]
    state = _state(TEXTS, beats, floor=400, contract_fix=ContractFixSpec(
        beat_ids=["b"], instruction="湯船のまま休憩室を思い出す"))
    job = next_job(state)
    fixed = "　二人は湯船のまま、浴場の奥の休憩室を思い出した。"
    submit_result(state, job_id=job.job_id, model="m", candidate=fixed, review="confirmed")
    result = next_job(state)
    assert CONTRACT_FIX_TOKEN in result.escalated_beats
    assert any(note.startswith("CONTRACT_FIX_SCENE_FLOOR") for note in result.notes)
    assert result.beat_texts["b"].strip() == fixed.strip()


def test_reordered_sentences_are_reported():
    from metron.length import canon_review_digest
    original = "　兄は上着を着た。母が時刻表を見る。二人は家を出た。駅に着いた。"
    reordered = "　駅に着いた。二人は家を出た。母が時刻表を見る。兄は上着を着た。"
    digest = canon_review_digest(original, reordered)
    assert digest.new_sentences == () and digest.removed_sentences == ()
    assert len(digest.moved_sentences) == 3
    unchanged = canon_review_digest(original, original)
    assert unchanged.moved_sentences == ()


def test_summary_lists_reordered_sentences(tmp_path):
    work, repo, run = _ops_bridge(tmp_path, chars=220, floor=200)
    _begin_fix(work, repo, instruction="場面の順序を入れ替える")
    repair_next(work, repo_root=repo, **SCENE)
    state = read_state(run / "repair_state.json")
    job = state.session.pending
    lines = [line for line in state.session.working_texts[job.beat_id].split("\n") if line.strip()]
    candidate = tmp_path / "reordered.md"
    candidate.write_text("\n".join(reversed(lines)), encoding="utf-8")
    repair_submit(work, job_id=job.job_id, model="fixture-writer", candidate=candidate,
                  error=None, review="confirmed", repo_root=repo,
                  canon_authorization="著者: 並べ替えを確認", **SCENE)
    _, text = repair_summary(work, repo_root=repo, **SCENE)
    section = text.split("## 順序が変わった文")[1].split("##")[0]
    assert "- なし" not in section and section.strip()


@pytest.fixture(autouse=True)
def _before_d21_design_routing(monkeypatch):
    """このモジュールは、D21（不足10%以上は Deepen せず設計追加へ回す）より前の増量の仕組みを
    検証する。fixture の本文は目標から大きく不足しているので、D21 の停止だけを外す。
    D21 の挙動は test_length_phase6.py で既定値のまま確かめる。"""
    import metron.length

    monkeypatch.setattr(metron.length, "DESIGN_SHORTAGE_LIMIT", 1.01)
