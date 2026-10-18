"""規定量調整 Phase 3: 子エピソード契約・収束（OP-C）・CANON 検査・冗長化の候補抽出。"""
from __future__ import annotations

from pathlib import Path
import json

import pytest

from test_metron import _beat, _calibration, _plan
from test_metron_length import TEXTS, _drive
from metron.analyze import analyze_marked_text
from metron.canon_check import (
    CanonCheckError, CanonCheckResult, build_canon_check_prompt, evaluate_canon_check,
    parse_canon_check,
)
from metron.episodes import (
    ChildEpisode, EpisodeError, EpisodesDocument, addition_issues, condense_priority, locate_span,
    validate_condense,
)
from metron.length import LENGTH_TOKEN, LengthSpec, assembled_chars
from metron.models import LengthTarget
from metron.repair import marked_text_for_measurement
from metron.repair_steps import begin_repair, next_job, submit_result

import novel_text_rewrite_lint as lint

ROOT = Path(__file__).resolve().parents[2]


def _episode(episode_id: str, beat_id: str = "a", **kwargs) -> ChildEpisode:
    values = dict(id=episode_id, beat_id=beat_id,
                  state_change=[{"kind": "emotion", "who": "兄", "before": "迷う", "after": "決める"}])
    values.update(kwargs)
    return ChildEpisode.model_validate(values)


def _session(target: LengthTarget, episodes: list[ChildEpisode]):
    plan = _plan(_beat("a", chars_hint=10), _beat("b", chars_hint=10), chars_floor=1)
    analyzed = analyze_marked_text(marked_text_for_measurement(plan, TEXTS), plan, run=1)
    state = begin_repair(analyzed.metrics, plan, _calibration(), clean_text=analyzed.clean_text,
                         spans=analyzed.spans, model="m", seam_enabled=False,
                         length=LengthSpec(target=target, episodes=episodes))
    return state, plan


# ── 子エピソード契約 ─────────────────────────────────────────────


def test_episode_ids_must_be_unique():
    with pytest.raises(ValueError):
        EpisodesDocument(scene_id="ch01-001", episodes=[_episode("E1"), _episode("E1")])


def test_addition_issues_follow_the_addition_rules():
    bare = ChildEpisode(id="E1", beat_id="a")
    issues = addition_issues(bare)
    assert any("state_change" in item for item in issues)
    assert any("padding" in item for item in issues)
    abstract = _episode("E2", local_payoff=[{"kind": "atmosphere", "what": "雰囲気を出す"}],
                        connections=["感情を変化させる"])
    assert any("abstract" in item for item in addition_issues(abstract))
    concrete = _episode("E3", local_payoff=[{"kind": "humor", "what": "母が時刻表を逆さに持っていて兄が笑う"}],
                        connections=["感情を変化させる"])
    assert addition_issues(concrete) == []


def test_condense_priority_order():
    empty = _episode("E1")
    payoff = _episode("E2", local_payoff=[{"kind": "rest", "what": "駅前で二人が缶コーヒーを分ける"}])
    light = _episode("E3", carry_back=[{"what": "切符", "used_at": "ch02-001"}])
    heavy = _episode("E4", carry_back=[{"what": "切符", "used_at": "ch02-001"},
                                       {"what": "鍵", "used_at": "ch03-001"}])
    ordered = sorted([heavy, light, payoff, empty], key=condense_priority)
    assert [item.id for item in ordered] == ["E1", "E2", "E3", "E4"]


def test_locate_span_requires_unique_quotes():
    text = "　兄は上着を着た。母が時刻表を見る。兄は上着を脱いだ。"
    episode = _episode("E1", span={"start": "母が", "end": "見る。"})
    start, end = locate_span(text, episode)
    assert text[start:end] == "母が時刻表を見る。"
    with pytest.raises(EpisodeError):
        locate_span(text, _episode("E2", span={"start": "兄は上着", "end": "見る。"}))


def test_validate_condense_shape():
    span = "　母は言いかけた言葉を飲みこみ、時刻表を鞄の奥へしまった。"
    assert validate_condense(span, "　母は何も言わなかった。").accepted
    assert not validate_condense(span, span + "さらに。").accepted
    assert not validate_condense(span, "<!--beat:a-->短い").accepted
    assert not validate_condense(span, "").accepted


# ── 収束（OP-C）による減量 ──────────────────────────────────────


def test_over_scene_condenses_after_tighten_is_exhausted():
    summary = "　兄は上着を着た。"
    probe, plan = _session(LengthTarget(target_chars=100), [])
    texts = dict(TEXTS, a=summary)
    goal = assembled_chars(plan, texts)
    state, _ = _session(LengthTarget(target_chars=goal, max_passes=8), [_episode("E1")])

    def respond(job, text, n):
        if job.operation == "condense":
            return summary, "confirmed"
        return text, "rejected"

    result, jobs = _drive(state, respond)
    operations = [job.operation for job in jobs]
    assert operations[-1] == "condense" and set(operations[:-1]) == {"tighten"}
    assert jobs[-1].episode_id == "E1" and jobs[-1].beat_id == "a"
    assert "必ず残す（後の場面で使われる）:\n- （なし）" in jobs[-1].prompt
    assert LENGTH_TOKEN not in result.escalated_beats
    assert result.beat_texts["a"] == summary


def test_condense_visits_episodes_without_carry_back_first():
    carried = _episode("E-carry", beat_id="a", carry_back=[{"what": "時刻表", "used_at": "ch02-001"}])
    free = _episode("E-free", beat_id="b")
    state, _ = _session(LengthTarget(target_chars=40, max_passes=8), [carried, free])
    result, jobs = _drive(state, lambda job, text, n: (text, "rejected"))
    condensed = [job.episode_id for job in jobs if job.operation == "condense"]
    assert condensed[:1] == ["E-free"]
    carry_prompt = next(job.prompt for job in jobs if job.episode_id == "E-carry")
    assert "時刻表" in carry_prompt and "必ず残す" in carry_prompt


def test_condense_candidate_is_rejected_when_not_shorter():
    state, _ = _session(LengthTarget(target_chars=40, max_passes=8), [_episode("E1")])
    for _ in range(8):
        job = next_job(state)
        if job.operation == "condense":
            break
        submit_result(state, job_id=job.job_id, model="m", candidate="", error="skip")
    else:
        pytest.fail("no condense job")
    submit_result(state, job_id=job.job_id, model="m", candidate=TEXTS["a"] + "さらに長く。",
                  review="confirmed")
    assert state.history[-1].rejection is not None


def test_overshoot_after_deepen_never_condenses():
    probe, plan = _session(LengthTarget(target_chars=100), [])
    goal = assembled_chars(plan, TEXTS) + 5
    state, _ = _session(LengthTarget(target_chars=goal, max_passes=8), [_episode("E1")])

    def respond(job, text, n):
        if job.operation == "deepen":
            return text.rstrip("\n") + "改札の電子音が遠くで鳴り、ホームを渡る風が冷たかった。" * 3, "confirmed"
        return text, "rejected"

    _, jobs = _drive(state, respond)
    assert "condense" not in [job.operation for job in jobs]


# ── CANON 検査 ─────────────────────────────────────────────────


def _result(**kwargs) -> CanonCheckResult:
    values = dict(completed=True, input_sha256="sha256:" + "0" * 64,
                  facts_before=["兄が家を出た"], facts_after=["兄が家を出た"],
                  findings=[], condense=[])
    values.update(kwargs)
    return CanonCheckResult.model_validate(values)


def test_canon_check_fails_on_added_or_changed_facts():
    added = _result(findings=[{"kind": "added", "fact": "兄が鍵を拾った"}])
    assert evaluate_canon_check(added, operation="deepen") == (False, ["added fact (OP-E): 兄が鍵を拾った"])
    changed = _result(findings=[{"kind": "changed", "fact": "母が先に家を出た"}])
    assert not evaluate_canon_check(changed, operation="tighten")[0]


def test_missing_fact_is_only_allowed_when_condensed_and_covered():
    missing = {"kind": "missing", "fact": "母が時刻表を確かめた", "covered_by": "母は出発を見送った"}
    tighten = _result(findings=[missing])
    assert not evaluate_canon_check(tighten, operation="tighten")[0]
    condensed = _result(findings=[missing], condense=[
        {"episode_id": "E1", "state_change_kept": True, "carry_back_kept": True,
         "emotion_direction_kept": True}])
    assert evaluate_canon_check(condensed, operation="condense", episode=_episode("E1"))[0]
    lost = _result(findings=[missing], condense=[
        {"episode_id": "E1", "state_change_kept": True, "carry_back_kept": False,
         "emotion_direction_kept": True}])
    passed, reasons = evaluate_canon_check(lost, operation="condense", episode=_episode("E1"))
    assert not passed and any("CHK-C2" in item for item in reasons)
    uncovered = _result(findings=[dict(missing, covered_by=None)], condense=condensed.condense)
    assert not evaluate_canon_check(uncovered, operation="condense", episode=_episode("E1"))[0]
    assert not evaluate_canon_check(_result(), operation="condense", episode=_episode("E1"))[0]


def test_parse_canon_check_accepts_fenced_json_and_rejects_garbage():
    parsed = parse_canon_check("結果です。\n" + "```json\n" + _result().model_dump_json() + "\n```")
    assert parsed.findings == []
    with pytest.raises(CanonCheckError):
        parse_canon_check("問題ありません")


@pytest.mark.parametrize("field", [
    "completed", "input_sha256", "facts_before", "facts_after", "findings", "condense",
])
def test_canon_check_requires_each_result_field(field):
    payload = _result().model_dump()
    del payload[field]
    with pytest.raises(CanonCheckError):
        parse_canon_check(json.dumps(payload))


@pytest.mark.parametrize("changes", [
    {"completed": False}, {"facts_before": []}, {"facts_after": []},
    {"facts_before": [" "]}, {"input_sha256": "not-a-hash"},
])
def test_canon_check_rejects_incomplete_results(changes):
    payload = _result().model_dump()
    payload.update(changes)
    with pytest.raises(CanonCheckError):
        parse_canon_check(json.dumps(payload))


def test_default_budget_reserves_a_condense_attempt():
    summary = "　兄は上着を着た。"
    _, plan = _session(LengthTarget(target_chars=100), [])
    goal = assembled_chars(plan, dict(TEXTS, a=summary))
    state, _ = _session(LengthTarget(target_chars=goal), [_episode("E1")])

    def respond(job, text, n):
        return (summary, "confirmed") if job.operation == "condense" else (text, "rejected")

    result, jobs = _drive(state, respond)
    assert [job.operation for job in jobs] == ["tighten", "tighten", "condense"]
    assert LENGTH_TOKEN not in result.escalated_beats


def test_single_attempt_budget_does_not_skip_tighten_or_exceed_budget():
    state, _ = _session(LengthTarget(target_chars=50, max_passes=1), [_episode("E1")])
    result, jobs = _drive(state, lambda job, text, n: (text, "rejected"))
    assert [job.operation for job in jobs] == ["tighten"]
    assert LENGTH_TOKEN in result.escalated_beats


def test_canon_check_prompt_names_condense_checks():
    episode = _episode("E1", carry_back=[{"what": "切符", "used_at": "ch02-001"}])
    prompt = build_canon_check_prompt(operation="condense", known_facts="- EVT-0001: 駅へ",
                                      original="元", candidate="後", episode=episode,
                                      input_sha256="sha256:" + "0" * 64)
    assert "carry_back_kept" in prompt and "切符" in prompt and "EVT-0001" in prompt
    assert '"findings"' in prompt


# ── 冗長化（OP-P）の候補抽出 CHK-P1 ─────────────────────────────


def test_padding_profile_lists_candidates_without_failing_strict(tmp_path, monkeypatch):
    monkeypatch.setenv(lint.ENV_RULES, str(ROOT / "_how_to.example" / "novel_text_rewrite_rules.yaml"))
    work = tmp_path / "work"
    (work / "_novel_text").mkdir(parents=True)
    (work / "_novel_text" / "novel_text01.md").write_text(
        "# 第一章\n\n　彼は駅へ走ることができた。言うまでもなく寒かった。\n"
        "　まず最初に切符を買った。言葉にできないほどの朝だった。\n", encoding="utf-8")
    result = lint.run_lint(work, profile="padding", strict=True, root=ROOT)
    rules = {item["rule_id"] for item in result["issues"]}
    assert rules == {"padding_circumlocution", "padding_meta_preface", "padding_redundant_modifier",
                     "padding_abstract"}
    assert all(item["level"] == "info" for item in result["issues"])
    assert result["ok"]
    default = lint.run_lint(work, profile="default", strict=True, root=ROOT)
    assert not any(item["rule_id"].startswith("padding_") for item in default["issues"])
