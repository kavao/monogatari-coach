"""規定量調整 Phase 5（D18〜D20）: 場面単位の反復・仕上がり目標と余地・清書稿の報告。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from test_metron import _beat, _calibration, _plan
from test_writing_bridge_length import ADDITION, SCENE, _beat_chars, _write_candidate
from test_writing_bridge_ops_speed import _ops_bridge
from metron.analyze import analyze_marked_text
from metron.length import (
    DEFAULT_FINISH_MARGIN, LengthConfigError, LengthSpec, finish_bounds, finish_target,
)
from metron.repair import build_expand_prompt, marked_text_for_measurement, validate_expansion
from metron.repair_steps import begin_repair, next_job, submit_result
from metron.repetition import (
    STYLE_RULES, frequent_phrases, introduced_repeats, phrase_counts, repeated_phrase_lines,
)
from writing_bridge.errors import BridgeError
from writing_bridge.repair import read_state, repair_begin, repair_next, repair_submit, repair_summary

import novel_text_rewrite_lint as lint

ROOT = Path(__file__).resolve().parents[2]
MOTIF = "キーボード焼けした指先が桶の縁を撫でた。"


# ── 場面単位の語句反復（D18） ───────────────────────────────────


def test_third_occurrence_across_the_scene_is_reported():
    others = ["　" + MOTIF, "　兄は湯を汲んだ。" + MOTIF]
    new = ["キーボード焼けした指先が膝の上で止まった。"]
    hits = introduced_repeats([*others, "　兄は座った。"], [*others, "　兄は座った。" + new[0]], new)
    assert hits and hits[0][1] == 3 and "キーボード焼けした" in hits[0][0]
    assert introduced_repeats([*others, ""], [*others, new[0]], new, allowed=("キーボード焼け",)) == []


def test_short_sentences_are_not_joined_across_boundaries():
    text = "風を感じた。" * 40
    assert phrase_counts([text]) == {}
    assert frequent_phrases([text]) == []


def test_frequent_phrases_list_the_avoid_words():
    texts = ["　" + MOTIF, "　" + MOTIF, "　母が時刻表を確かめる。"]
    avoid = frequent_phrases(texts)
    assert avoid and "キーボード焼け" in avoid[0]
    # 許可語そのものは一覧から外れる。同じ文の残りの部分は、繰り返しなので出てよい。
    allowed = frequent_phrases(texts, allowed=("キーボード焼け",))
    assert all("キーボード焼け" not in item for item in allowed)
    assert frequent_phrases(texts, allowed=(MOTIF,)) == []


def test_deepen_candidate_repeating_a_phrase_from_other_beats_is_rejected():
    others = ("　" + MOTIF, "　母は振り返った。" + MOTIF)
    original = "　兄は湯船の縁に腰を下ろした。"
    candidate = original + "\n\n　キーボード焼けした指先が湯の表面をなぞった。"
    check = validate_expansion(original, candidate, retention_threshold=0.8, others=others)
    assert not check.accepted and "phrase repeats across the scene" in check.reason
    allowed = validate_expansion(original, candidate, retention_threshold=0.8, others=others,
                                 allowed_repeats=("キーボード焼け",))
    assert allowed.accepted


def test_deepen_candidate_paraphrasing_another_beat_is_rejected():
    loop = "フロントへ返すのが正しい手順だと、頭の端で何度も組み立ててはほどいていた。"
    others = ("　" + loop,)
    original = "　兄は小妖精の背中を流した。"
    candidate = original + "\n\n　フロントへ返すのが正しい手順だと、頭の隅で何度も組み立ててはほどいた。"
    check = validate_expansion(original, candidate, retention_threshold=0.8, others=others)
    assert not check.accepted and check.reason == "new sentence paraphrases another beat"
    alone = validate_expansion(original, candidate, retention_threshold=0.8)
    assert alone.accepted


def test_deepen_prompt_carries_style_rules_and_avoid_words():
    prompt = build_expand_prompt(_beat("a"), "短い。", avoid=("キーボード焼けした指",))
    assert all(rule in prompt for rule in STYLE_RULES)
    assert "「キーボード焼けした指」" in prompt


def _auto_state(texts, *, allowed=()):
    beats = [_beat(beat_id, chars_hint=400) for beat_id in texts]
    plan = _plan(*beats, chars_floor=2000)  # 床未達にして Deepen を出させる
    analyzed = analyze_marked_text(marked_text_for_measurement(plan, texts), plan, run=1)
    calibration = _calibration(missing_span_ratio=0.0, beat_thin_ratio=0.01,
                               ending_rush_threshold=0.0)
    return begin_repair(analyzed.metrics, plan, calibration, clean_text=analyzed.clean_text,
                        spans=analyzed.spans, model="m", seam_enabled=False,
                        allowed_repeats=list(allowed))


def test_auto_deepen_job_lists_avoid_words_and_rejects_scene_repeats():
    texts = {"a": "　" + MOTIF + "母が見ていた。", "b": "　" + MOTIF + "兄は黙った。",
             "c": "　二人は駅に着いた。"}
    state = _auto_state(texts)
    job = next_job(state)
    assert job.operation == "deepen" and "繰り返し使われている語句" in job.prompt
    current = state.working_texts[job.beat_id]
    candidate = current.rstrip("\n") + "\n\n　キーボード焼けした指先が切符の端をつまんだ。"
    submit_result(state, job_id=job.job_id, model="m", candidate=candidate, review="confirmed")
    assert "phrase repeats across the scene" in state.history[-1].rejection


# ── 仕上がり目標と余地（D19） ───────────────────────────────────


def test_finish_target_adds_the_margin_and_keeps_the_finish_band():
    target = finish_target(8000)
    assert DEFAULT_FINISH_MARGIN == 0.08
    assert target.target_chars == 8640 and target.finish_chars == 8000
    plan = _plan(_beat("a"), chars_floor=8000)
    assert finish_bounds(target, plan) == (8000, 8240)
    plan_low = _plan(_beat("a"), chars_floor=1)
    assert finish_bounds(target, plan_low) == (7760, 8240)
    assert finish_bounds(target.model_copy(update={"finish_chars": None}), plan_low) is None
    with pytest.raises(LengthConfigError):
        finish_target(8000, margin=1.5)


# ── writing_bridge: 清書稿を含む1回の報告（D20） ───────────────────


def _complete_length_run(tmp_path, *, finish=None):
    work, repo, run = _ops_bridge(tmp_path, chars=220, floor=200)
    goal = _beat_chars(work) + len("\n\n　" + ADDITION)
    target = finish_target(finish, margin=0.0) if finish else finish_target(goal, margin=0.0)
    repair_begin(work, model="fixture-writer", authorization="ユーザー依頼: 字数合わせ",
                 repo_root=repo, intent="length", length_target=target, **SCENE)
    repair_next(work, repo_root=repo, **SCENE)
    job, candidate = _write_candidate(tmp_path, run)
    repair_submit(work, job_id=job.job_id, model="fixture-writer", candidate=candidate,
                  error=None, review="confirmed", repo_root=repo, **SCENE)
    return work, repo, run


def _refined_copy(tmp_path, work, run, *, drop: str):
    state = read_state(run / "repair_state.json")
    marked = (work / state.output_path).read_text(encoding="utf-8")
    refined = tmp_path / "refined.md"
    refined.write_text(marked.replace(drop, ""), encoding="utf-8")
    return refined


def test_summary_with_refined_draft_reports_three_stages_and_records_trim(tmp_path):
    work, repo, run = _complete_length_run(tmp_path)
    refined = _refined_copy(tmp_path, work, run, drop="母が時刻表を一度だけ確かめる。")
    _, text = repair_summary(work, repo_root=repo, refined_path=refined, **SCENE)
    assert "調整前" in text and "増量後" in text and "清書後" in text and "削減" in text
    assert "## 清書で消えた・書き換わった文" in text and "母が時刻表を一度だけ確かめる。" in text
    assert "場面内で3回以上に増えた語句" in text
    repair_summary(work, repo_root=repo, refined_path=refined, accept=True,
                   authorization="著者: これで保存", **SCENE)
    record = json.loads((run / "canon_review.json").read_text(encoding="utf-8"))["final_review"]
    assert record["refined_chars"] < record["deepened_chars"]
    assert 0 < record["trim_ratio"] < 0.5 and record["refined_hash"].startswith("sha256:")


def test_refined_draft_below_the_finish_band_is_flagged(tmp_path):
    work, repo, run = _complete_length_run(tmp_path)
    refined = _refined_copy(tmp_path, work, run, drop=ADDITION)
    _, text = repair_summary(work, repo_root=repo, refined_path=refined, **SCENE)
    assert "REFINED_BELOW_FINISH" in text


def test_refined_draft_must_keep_beat_markers(tmp_path):
    work, repo, run = _complete_length_run(tmp_path)
    broken = tmp_path / "broken.md"
    broken.write_text("　マーカーの無い本文。", encoding="utf-8")
    with pytest.raises(BridgeError) as error:
        repair_summary(work, repo_root=repo, refined_path=broken, **SCENE)
    assert error.value.code == "RANGE_MISMATCH"


def test_contract_allowed_repeats_reach_the_session(tmp_path):
    work, repo, run = _ops_bridge(tmp_path, chars=220, floor=200)
    path = work / "_metron/ch01-001/contract.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["scene"]["allowed_repeats"] = ["券売機の前"]
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    from writing_bridge.commands import prepare, receive
    from writing_bridge.models import RequestKind
    prepare(work, scene_id="ch01-001", text_path="_novel_text/novel_text01.md",
            request_kind=RequestKind.NEW, model_id="fixture-writer", selector=None,
            links_path=None, repo_root=repo)
    receive(work, scene_id="ch01-001", run_id="run-0002",
            candidate=work / "_metron/ch01-001/marked.md", request_id=None)
    repair_begin(work, model="fixture-writer", authorization="x", repo_root=repo,
                 intent="length", length_target=finish_target(400), scene_id="ch01-001",
                 run_id="run-0002")
    state = read_state(work / "_work/writing/ch01-001/run-0002/repair_state.json")
    assert state.session.allowed_repeats == ["券売機の前"]
    assert state.session.length.target.finish_chars == 400


def test_cli_finish_target_conflicts_with_target_chars(tmp_path):
    from test_writing_bridge import _run_cli
    work, repo, _ = _ops_bridge(tmp_path, chars=220, floor=200)
    both = _run_cli("repair-begin", str(work), "--scene-id", "ch01-001", "--run-id", "run-0001",
                    "--model", "fixture-writer", "--authorization", "x", "--intent", "length",
                    "--target-chars", "400", "--finish-target", "400", "--repo-root", str(repo))
    assert both.returncode == 2 and "JOB_CONFLICT" in both.stderr
    # サブプロセスには D21 の停止を外す fixture が効かないので、余地込みでも不足が10%未満になる値にする。
    finish = round(_beat_chars(work) / 0.94 / 1.08)
    ok = _run_cli("repair-begin", str(work), "--scene-id", "ch01-001", "--run-id", "run-0001",
                  "--model", "fixture-writer", "--authorization", "x", "--intent", "length",
                  "--finish-target", str(finish), "--repo-root", str(repo))
    assert ok.returncode == 0, ok.stderr
    state = read_state(work / "_work/writing/ch01-001/run-0001/repair_state.json")
    assert state.session.length.target.target_chars == round(finish * 1.08)
    assert state.session.length.target.finish_chars == finish


# ── lint: 清書の材料（候補だけ） ─────────────────────────────────


def test_lint_lists_repeated_phrases_and_measurements(tmp_path, monkeypatch):
    monkeypatch.setenv(lint.ENV_RULES, str(ROOT / "_how_to.example" / "novel_text_rewrite_rules.yaml"))
    work = tmp_path / "work"
    (work / "_novel_text").mkdir(parents=True)
    body = "\n".join(["# 第二章", "", "　" + MOTIF, "　兄は黙った。" + MOTIF,
                      "　向かい合った距離は数十センチもない。", "　" + MOTIF])
    (work / "_novel_text" / "novel_text02.md").write_text(body + "\n", encoding="utf-8")
    result = lint.run_lint(work, profile="padding", strict=True, root=ROOT)
    repeated = [item for item in result["issues"] if item["rule_id"] == "padding_repeated_phrase"]
    assert len(repeated) == 1 and repeated[0]["line"] == 6 and "（3回）" in repeated[0]["matched"]
    assert any(item["rule_id"] == "padding_measurement" for item in result["issues"])
    assert result["ok"]


def test_repeated_phrase_lines_report_the_third_line():
    lines = [(1, "　" + MOTIF), (5, "　" + MOTIF), (9, "　" + MOTIF)]
    [(phrase, count, line)] = repeated_phrase_lines(lines)
    assert count == 3 and line == 9


def test_unrelated_phrases_are_not_stitched_and_counts_follow_the_stitched_phrase():
    from metron.repetition import count_phrase, repeat_report
    motif_a = "服を着てフロントへ行く。"
    motif_b = "湯気の膜が二人のあいだで揺れた。"
    after = "".join(["　" + motif_a + motif_b] * 3)
    report = repeat_report([""], [after])
    phrases = [phrase for phrase, _, _ in report]
    assert any("服を着てフロントへ行く" in phrase for phrase in phrases)
    assert not any("服を着てフロントへ行く" in phrase and "湯気" in phrase for phrase in phrases)
    long = "十三時間机に縫い付けられた身体が軋んだ。"
    assert count_phrase(["　" + long] * 2, "十三時間机に縫い付けられた") == 2


def test_small_shortfall_against_the_finish_target_is_only_noted(tmp_path):
    """ユーザー指示: 仕上がり目標との数%の差は無理に合わせない。床はルールで厳守する。"""
    from metron.length import FINISH_SLACK, finish_bounds
    work, repo, run = _complete_length_run(tmp_path)
    state = read_state(run / "repair_state.json")
    plan, target = state.session.beat_plan, state.session.length.target
    marked = (work / state.output_path).read_text(encoding="utf-8")
    refined = tmp_path / "refined_small.md"
    refined.write_text(marked.replace("母が時刻表を一度だけ確かめる。", "母が見る。"), encoding="utf-8")
    from writing_bridge.repair import _refined_texts
    from metron.length import assembled_chars
    polished = assembled_chars(plan, _refined_texts(plan, refined))
    lower, _ = finish_bounds(target, plan)
    assert target.finish_chars * (1 - FINISH_SLACK) <= polished < lower
    assert polished >= plan.generation.chars_floor
    _, text = repair_summary(work, repo_root=repo, refined_path=refined, **SCENE)
    assert "REFINED_BELOW_FINISH" not in text and "REFINED_BELOW_FLOOR" not in text
    assert "誤差の範囲" in text


def test_refined_draft_below_the_scene_floor_is_always_flagged(tmp_path):
    work, repo, run = _complete_length_run(tmp_path)
    state = read_state(run / "repair_state.json")
    marked = (work / state.output_path).read_text(encoding="utf-8")
    refined = tmp_path / "refined_floor.md"
    refined.write_text(marked.replace("ああああああああ\n", ""), encoding="utf-8")
    _, text = repair_summary(work, repo_root=repo, refined_path=refined, **SCENE)
    assert "REFINED_BELOW_FLOOR" in text


# ── レビュー r17: Beat 指定の判定・清書稿の検証・帯の逆転・合成された語句 ─────


def _beat_scope_state(tmp_path, finish=70):
    work, repo, run = _ops_bridge(tmp_path, chars=220, floor=200)
    target = finish_target(finish, scope="beat", beat_id="say_goodbye")
    repair_begin(work, model="fixture-writer", authorization="ユーザー依頼: Beat を合わせる",
                 repo_root=repo, intent="length", length_target=target, **SCENE)
    return work, repo, run, read_state(run / "repair_state.json")


def _replace_beat(marked: str, beat_id: str, body: str) -> str:
    opening, closing = f"<!--beat:{beat_id}-->", f"<!--/beat:{beat_id}-->"
    start = marked.index(opening) + len(opening)
    return marked[:start] + "\n" + body + "\n" + marked[marked.index(closing):]


def test_beat_scope_judges_the_target_beat_not_the_whole_scene(tmp_path):
    work, repo, run, state = _beat_scope_state(tmp_path)
    refined = tmp_path / "beat_refined.md"
    refined.write_text(_replace_beat(state.source_marked, "say_goodbye", "「短い」"), encoding="utf-8")
    _, text = repair_summary(work, repo_root=repo, refined_path=refined, **SCENE)
    assert "対象 Beat say_goodbye" in text
    assert "REFINED_BELOW_FINISH" in text
    assert "Beat say_goodbye が" in text and "Beat の床 60" in text


def test_refined_draft_with_reordered_beats_is_refused(tmp_path):
    work, repo, run, state = _beat_scope_state(tmp_path)
    marked = state.source_marked
    a, b = "<!--beat:pack_bag-->", "<!--beat:say_goodbye-->"
    first = marked[marked.index(a):marked.index(b)]
    second_end = marked.index("<!--/beat:say_goodbye-->") + len("<!--/beat:say_goodbye-->")
    second = marked[marked.index(b):second_end]
    swapped = marked.replace(first + second, second + "\n\n" + first.rstrip("\n"))
    refined = tmp_path / "swapped.md"
    refined.write_text(swapped, encoding="utf-8")
    with pytest.raises(BridgeError) as error:
        repair_summary(work, repo_root=repo, refined_path=refined, **SCENE)
    assert error.value.code == "RANGE_MISMATCH" and "order" in str(error.value)


def test_refined_draft_with_text_outside_beats_is_refused(tmp_path):
    work, repo, run, state = _beat_scope_state(tmp_path)
    between = state.source_marked.replace(
        "<!--/beat:pack_bag-->", "<!--/beat:pack_bag-->\n\n　兄は鍵を拾った。", 1)
    path = tmp_path / "between.md"
    path.write_text(between, encoding="utf-8")
    with pytest.raises(BridgeError) as error:
        repair_summary(work, repo_root=repo, refined_path=path, **SCENE)
    assert error.value.code == "RANGE_MISMATCH" and "between" in str(error.value)
    heading = state.source_marked.replace("第一章", "第一章　鍵の行方", 1)
    path.write_text(heading, encoding="utf-8")
    with pytest.raises(BridgeError) as error:
        repair_summary(work, repo_root=repo, refined_path=path, **SCENE)
    assert error.value.code == "RANGE_MISMATCH" and "outside" in str(error.value)


def test_finish_band_that_cannot_meet_the_floor_is_refused(tmp_path):
    from metron.length import resolve_bounds
    with pytest.raises(LengthConfigError):
        resolve_bounds(finish_target(190), _plan(_beat("a"), chars_floor=200))
    work, repo, _ = _ops_bridge(tmp_path, chars=220, floor=200)
    with pytest.raises(BridgeError) as error:
        repair_begin(work, model="fixture-writer", authorization="x", repo_root=repo,
                     intent="length", length_target=finish_target(190), **SCENE)
    assert error.value.code == "LENGTH_CONFIG"


def test_phrases_from_different_sentences_are_not_synthesized():
    from metron.repetition import repeat_report
    first, second = "あいうえおかきくけこ", "いうえおかきくけこさ"
    after = "".join(f"　{first}。　{second}。" for _ in range(3))
    phrases = [phrase for phrase, _, _ in repeat_report([""], [after])]
    assert "あいうえおかきくけこさ" not in phrases
    lines = [(index, f"　{first}。　{second}。") for index in range(1, 4)]
    assert all(phrase != "あいうえおかきくけこさ" for phrase, _, _ in repeated_phrase_lines(lines))
    joined = [(index, "　あいうえおかきくけこさ。") for index in range(1, 4)]
    assert [phrase for phrase, _, _ in repeated_phrase_lines(joined)] == ["あいうえおかきくけこさ"]


def test_stitched_phrase_counts_are_real_occurrences_in_every_draft():
    """レビュー r18: 長い語句の別稿での回数は、構成する短い語句から推し量らない。"""
    from metron.repetition import count_phrase, repeat_report
    long, first, second = "あいうえおかきくけこさ", "あいうえおかきくけこ", "いうえおかきくけこさ"
    deepened = "".join(f"　{long}。" for _ in range(3))
    refined = "".join(f"　{first}。　{second}。" for _ in range(3))
    [(phrase, before, after)] = repeat_report([""], [deepened])
    assert (phrase, before, after) == (long, 0, 3)
    assert count_phrase([refined], long) == 0
    assert count_phrase([refined], first) == 3


@pytest.fixture(autouse=True)
def _before_d21_design_routing(monkeypatch):
    """このモジュールは、D21（不足10%以上は Deepen せず設計追加へ回す）より前の増量の仕組みを
    検証する。fixture の本文は目標から大きく不足しているので、D21 の停止だけを外す。
    D21 の挙動は test_length_phase6.py で既定値のまま確かめる。"""
    import metron.length

    monkeypatch.setattr(metron.length, "DESIGN_SHORTAGE_LIMIT", 1.01)


def test_slop_profile_lists_stock_phrases_without_failing_strict(tmp_path, monkeypatch):
    monkeypatch.setenv(lint.ENV_RULES, str(ROOT / "_how_to.example" / "novel_text_rewrite_rules.yaml"))
    work = tmp_path / "work"
    (work / "_novel_text").mkdir(parents=True)
    body = "\n".join(["# 第一章", "", "　彼は—言いかけて、やめた。単なる店ではなく、町の記憶だった。",
                      "　胸の奥がじんわりと温かくなった。それが答えと言えるでしょう。"])
    (work / "_novel_text" / "novel_text01.md").write_text(body + "\n", encoding="utf-8")
    result = lint.run_lint(work, profile="slop", strict=True, root=ROOT)
    found = {item["rule_id"] for item in result["issues"]}
    assert {"slop_em_dash", "slop_contrast_frame", "slop_stock_emotion", "slop_hedge_close"} <= found
    assert all(item["level"] == "info" for item in result["issues"]) and result["ok"]
    assert "slop_em_dash" in lint.run_lint(work, profile="full", root=ROOT)["active_rules"]
