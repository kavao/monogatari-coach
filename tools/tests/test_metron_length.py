from __future__ import annotations

import pytest

from test_metron import _beat, _calibration, _plan
from metron.analyze import analyze_marked_text
from metron.length import (
    LENGTH_TOKEN, LengthConfigError, LengthSpec, assembled_chars, band_state,
    canon_review_digest, resolve_bounds, validate_tightening,
)
from metron.models import LengthTarget, LengthTolerance
from metron.repair import build_expand_prompt, marked_text_for_measurement
from metron.repair_steps import RepairJob, begin_repair, next_job, submit_result


TEXTS = {
    "a": "　朝の玄関で、兄は旅行用の上着に袖を通した。母が時刻表を一度だけ確かめる。",
    "b": "　二人は家を出て、駅の券売機の前に立った。兄は財布から硬貨を数えて出した。",
}
ADDITIONS = [
    "改札の電子音が遠くで鳴り、ホームを渡る風が冷たかった。",
    "母は言いかけた言葉を飲みこみ、時刻表を鞄の奥へしまった。",
    "券売機の画面が白く光り、兄の指先がわずかにためらった。",
]


def _target(chars: int, **kwargs) -> LengthTarget:
    return LengthTarget(target_chars=chars, **kwargs)


def _session(target: LengthTarget, *, floor: int = 1, hints=(10, 10), weights=("normal", "normal")):
    beats = [_beat(beat_id, chars_hint=hint, weight=weight)
             for beat_id, hint, weight in zip(TEXTS, hints, weights)]
    plan = _plan(*beats, chars_floor=floor)
    analyzed = analyze_marked_text(marked_text_for_measurement(plan, TEXTS), plan, run=1)
    state = begin_repair(analyzed.metrics, plan, _calibration(), clean_text=analyzed.clean_text,
                         spans=analyzed.spans, model="m", seam_enabled=False,
                         length=LengthSpec(target=target, known_facts="- EVT-0001: 駅へ向かう"))
    return state, plan


def _drive(state, respond, limit: int = 12):
    jobs = []
    for _ in range(limit):
        result = next_job(state)
        if not isinstance(result, RepairJob):
            return result, jobs
        jobs.append(result)
        candidate, review = respond(result, state.working_texts[result.beat_id], len(jobs))
        submit_result(state, job_id=result.job_id, model="m", candidate=candidate, review=review)
    pytest.fail("length adjustment did not stop")


def _scene_chars(plan) -> int:
    return assembled_chars(plan, TEXTS)


def test_bounds_round_endpoints_and_reject_band_below_floor():
    plan = _plan(_beat("a", chars_hint=10), chars_floor=1)
    bounds = resolve_bounds(_target(4000), plan)
    assert (bounds.lower_chars, bounds.upper_chars) == (3880, 4120)
    assert bounds.effective_lower == 3880 and not bounds.floor_raised
    with pytest.raises(LengthConfigError):
        resolve_bounds(_target(3000), _plan(_beat("a"), chars_floor=4000))


def test_bounds_raise_lower_to_floor_and_use_beat_hint_for_beat_scope():
    raised = resolve_bounds(_target(4000), _plan(_beat("a"), chars_floor=4000))
    assert raised.effective_lower == 4000 and raised.floor_raised
    plan = _plan(_beat("a", chars_hint=300), _beat("b", chars_hint=10), chars_floor=4000)
    beat = resolve_bounds(_target(320, scope="beat", beat_id="a"), plan)
    assert beat.floor == 300 and beat.scene_floor == 4000
    assert beat.effective_lower == 311
    with pytest.raises(LengthConfigError):
        resolve_bounds(_target(200, scope="beat", beat_id="a"), plan)
    with pytest.raises(LengthConfigError):
        resolve_bounds(_target(4000, scope="chapter"), plan)


def test_band_state_includes_endpoints():
    bounds = resolve_bounds(_target(100), _plan(_beat("a")))
    assert [band_state(value, bounds) for value in (96, 97, 103, 104)] == [
        "short", "in_band", "in_band", "over"]


def test_length_target_scope_validation():
    with pytest.raises(ValueError):
        LengthTarget(target_chars=10, scope="beat")
    with pytest.raises(ValueError):
        LengthTarget(target_chars=10, beat_id="a")
    with pytest.raises(ValueError):
        LengthTarget(target_chars=10, tolerance=LengthTolerance(lower=1.1, upper=1.2))


def test_validate_tightening_accepts_shorter_text_without_new_sentences():
    original = "　彼は走るという行動を開始した。駅までの道は非常にとても長かった。母が手を振る。"
    candidate = "　彼は走り出した。駅までの道は長かった。母が手を振る。"
    assert validate_tightening(original, candidate).accepted


@pytest.mark.parametrize("candidate, reason", [
    ("　彼は走り出した。空から竜が降りてきた。母が手を振る。", "adds a sentence"),
    ("　母が手を振る。彼は走り出した。駅までの道は長かった。", "sentence order"),
    ("　彼は走るという行動を開始した。駅までの道は非常にとても長かった。母が大きく手を振っている。", "does not decrease"),
    ("　母が手を振る。", "removed too much"),
])
def test_validate_tightening_rejects_unsafe_candidates(candidate, reason):
    original = "　彼は走るという行動を開始した。駅までの道は非常にとても長かった。母が手を振る。"
    check = validate_tightening(original, candidate)
    assert not check.accepted and reason in check.reason


def test_validate_tightening_respects_minimum_chars():
    original = "　彼は走るという行動を開始した。駅までの道は非常にとても長かった。母が手を振る。"
    candidate = "　彼は走り出した。駅までの道は長かった。母が手を振る。"
    assert "lower bound" in validate_tightening(original, candidate, min_chars=40).reason


def test_canon_review_digest_marks_new_and_removed_terms():
    original = "　兄はリュックを背負った。母が見送る。"
    digest = canon_review_digest(original, "　兄はリュックを背負った。トランクも持った。",
                                 known_text="", names=("母",))
    assert digest.new_terms == ("トランク",)
    assert digest.removed_sentences == ("母が見送る。",)
    assert digest.removed_terms == ("母",)
    shorter = canon_review_digest(original, "　兄は背負った。母が見送る。")
    assert shorter.removed_terms == ("リュック",)


def test_short_scene_deepens_until_band_and_stops():
    probe, plan = _session(_target(100))
    addition = ADDITIONS[0]
    goal = _scene_chars(plan) + len(addition)
    state, _ = _session(_target(goal))
    result, jobs = _drive(state, lambda job, text, n: (text.rstrip("\n") + addition, "confirmed"))
    assert [job.operation for job in jobs] == ["deepen"]
    assert LENGTH_TOKEN not in result.escalated_beats
    assert any(note.startswith("LENGTH_IN_BAND") for note in result.notes)


def test_deepen_prompt_carries_known_facts_and_no_new_fact_instruction():
    state, plan = _session(_target(400))
    job = next_job(state)
    assert job.operation == "deepen"
    assert "EVT-0001: 駅へ向かう" in job.prompt
    assert "新しい出来事・人物・過去・選択・所持品を追加しない" in job.prompt
    assert "新規事実を" not in job.prompt


def test_heavy_beat_is_deepened_first():
    state, _ = _session(_target(400), weights=("normal", "heavy"))
    assert next_job(state).beat_id == "b"


def test_rejected_candidates_count_toward_max_passes_and_escalate():
    state, _ = _session(_target(400, max_passes=2))
    result, jobs = _drive(state, lambda job, text, n: (text, "rejected"))
    assert len(jobs) == 2
    assert LENGTH_TOKEN in result.escalated_beats
    assert any(note.startswith("LENGTH_MAX_PASSES: short") for note in result.notes)
    assert any(note.startswith("LENGTH_ESCALATE_ADD") for note in result.notes)


def test_overshoot_after_deepen_uses_tighten_only():
    probe, plan = _session(_target(100))
    goal = _scene_chars(plan) + 5
    state, _ = _session(_target(goal, tolerance=LengthTolerance(lower=0.99, upper=1.01)))

    def respond(job, text, n):
        if job.operation == "deepen":
            return text.rstrip("\n") + "".join(ADDITIONS), "confirmed"
        return text, "rejected"

    result, jobs = _drive(state, respond)
    operations = [job.operation for job in jobs]
    assert operations[0] == "deepen"
    assert "tighten" in operations
    assert "deepen" not in operations[operations.index("tighten"):]
    assert LENGTH_TOKEN in result.escalated_beats


def test_over_scene_only_tightens_and_reports_revise():
    probe, plan = _session(_target(100))
    state, _ = _session(_target(_scene_chars(plan) // 2, max_passes=2))
    result, jobs = _drive(state, lambda job, text, n: (text, "rejected"))
    assert {job.operation for job in jobs} == {"tighten"}
    assert any(note.startswith("LENGTH_ESCALATE_REVISE") for note in result.notes)


def test_tighten_candidate_is_validated_on_submit():
    probe, plan = _session(_target(100))
    state, _ = _session(_target(_scene_chars(plan) - 6, max_passes=1))
    job = next_job(state)
    assert job.operation == "tighten"
    submit_result(state, job_id=job.job_id, model="m",
                  candidate="　竜が空から降りてきた。", review="confirmed")
    assert state.history[-1].rejection is not None


def test_regular_deepen_prompt_drops_new_fact_instruction():
    beat = _beat("a")
    beat.budget.new_facts = 2
    prompt = build_expand_prompt(beat, "短い。")
    assert "新規事実を" not in prompt
    assert "新しい出来事・人物・過去・選択・所持品・事実は足さない" in prompt
    assert "制度" not in prompt


def _beat_session(target: LengthTarget, *, floor: int, expandable: bool = True):
    beats = [_beat("a", chars_hint=10, expandable=expandable), _beat("b", chars_hint=10)]
    plan = _plan(*beats, chars_floor=floor)
    analyzed = analyze_marked_text(marked_text_for_measurement(plan, TEXTS), plan, run=1)
    return begin_repair(analyzed.metrics, plan, _calibration(), clean_text=analyzed.clean_text,
                        spans=analyzed.spans, model="m", seam_enabled=False,
                        length=LengthSpec(target=target))


def test_beat_scope_in_band_still_requires_the_scene_floor():
    beat_chars = len(TEXTS["a"])
    state = _beat_session(_target(beat_chars, scope="beat", beat_id="a"), floor=2000)
    result, jobs = _drive(state, lambda job, text, n: (text, "rejected"))
    assert jobs == []
    assert LENGTH_TOKEN in result.escalated_beats
    assert any(note.startswith("LENGTH_SCENE_FLOOR") for note in result.notes)


def test_beat_scope_skips_non_expandable_beat():
    state = _beat_session(_target(200, scope="beat", beat_id="a"), floor=1, expandable=False)
    result, jobs = _drive(state, lambda job, text, n: (text, "rejected"))
    assert jobs == []
    assert LENGTH_TOKEN in result.escalated_beats
    assert any(note.startswith("LENGTH_NO_ELIGIBLE") for note in result.notes)
