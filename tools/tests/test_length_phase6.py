"""D21（Phase 6）: 章の設計密度、不足率による Deepen と設計追加の振り分け、設計から登録する子エピソード。"""
from __future__ import annotations

import json

import pytest

from test_metron import _beat, _plan
from test_metron_length import TEXTS
from test_writing_bridge_length import SCENE, _beat_chars
from test_writing_bridge_ops_speed import _ops_bridge
from design_density import chapter_densities, judge, recommended_items
from metron.episodes import ChildEpisode, EpisodeError, locate_span
from metron.length import DESIGN_SHORTAGE_LIMIT, finish_target, shortage_ratio
from metron.models import LengthTarget
from writing_bridge.errors import BridgeError
from writing_bridge.repair import read_state, repair_begin


# ── 章の設計密度 ───────────────────────────────────────────────


@pytest.mark.parametrize("target, items, verdict", [
    (8000, 12, "推奨帯"),            # 約667字/項
    (4000, 12, "帯の外だが許容"),     # 約333字/項。件数だけで「多すぎ」にしない
    (4000, 14, "多すぎ"),            # 約286字/項
    (3000, 10, "帯の外だが許容"),     # 300字/項ちょうどは「300字未満」に含めない
    (8000, 6, "少なすぎ"),           # 約1333字/項
    (8000, 0, "少なすぎ"),
    (None, 12, "保留"),
])
def test_density_verdicts(target, items, verdict):
    _, result = judge(target, items)
    assert result.startswith(verdict)


def test_recommended_item_counts():
    assert recommended_items(8000) == (10, 16)
    assert recommended_items(4000) == (5, 8)


DESIGN = """# design_specification.md

## ストーリー（章ごと詳細）

### 第1章「出会い」

1. 慎が宿に着く。
2. 杏咲が現れる。

**分量目安**：出会いまでを同じ章に置く。初稿は 7,983字。

### 第2章「湯の中」

1. 慎が湯に入る。
2. 杏咲が背中を流す。
3. 二人が向かい合う。

**分量目安**：2,400字以上。初稿は 2,047字。

## ストーリー相関図

1. これは章の出来事ではない。
"""


def test_chapter_target_comes_only_from_the_head_of_the_volume_note():
    rows = {row.chapter: row for row in chapter_densities(DESIGN)}
    assert rows[1].target is None and rows[1].verdict.startswith("保留")
    assert rows[2].target == 2400 and rows[2].items == 3 and rows[2].verdict.startswith("推奨帯")
    explicit = {row.chapter: row for row in chapter_densities(DESIGN, targets={1: 1400})}
    assert explicit[1].target == 1400 and explicit[1].target_source == "明示"
    assert explicit[1].verdict.startswith("推奨帯")


# ── 不足率（本文がある段階） ─────────────────────────────────────


def test_shortage_ratio_and_limit():
    assert DESIGN_SHORTAGE_LIMIT == 0.10
    assert shortage_ratio(8000, 6016) == pytest.approx(0.248)
    assert shortage_ratio(8000, 9000) == 0.0


def test_shortage_is_measured_against_the_target_with_margin():
    """案A: 余地を含めない目標では不足9%でも、余地込みの増量目標では10%以上になる。"""
    target = finish_target(1000)
    current = 910
    assert shortage_ratio(target.finish_chars, current) < DESIGN_SHORTAGE_LIMIT
    assert shortage_ratio(target.target_chars, current) >= DESIGN_SHORTAGE_LIMIT


def _length_begin(work, repo, target):
    return repair_begin(work, model="fixture-writer", authorization="ユーザー依頼: 字数合わせ",
                        repo_root=repo, intent="length", length_target=target, **SCENE)


@pytest.mark.parametrize("ratio", [0.15, 0.10])
def test_length_adjustment_with_a_large_shortage_routes_to_design(tmp_path, ratio):
    work, repo, run = _ops_bridge(tmp_path, chars=220, floor=200)
    current = _beat_chars(work)
    target = LengthTarget(target_chars=round(current / (1 - ratio)) + 1)
    with pytest.raises(BridgeError) as error:
        _length_begin(work, repo, target)
    assert error.value.code == "DESIGN_DENSITY"
    assert not (run / "repair_state.json").exists()
    log = (work / "_metron/ch01-001/shortage_log.jsonl").read_text(encoding="utf-8").splitlines()
    entry = json.loads(log[-1])
    assert entry["intent"] == "length" and entry["stopped"] and entry["shortage"] >= 0.10


def test_length_adjustment_with_a_small_shortage_deepens(tmp_path):
    work, repo, run = _ops_bridge(tmp_path, chars=220, floor=200)
    current = _beat_chars(work)
    code, _ = _length_begin(work, repo, LengthTarget(target_chars=round(current / 0.95)))
    assert code == 0
    entry = json.loads((work / "_metron/ch01-001/shortage_log.jsonl").read_text(
        encoding="utf-8").splitlines()[-1])
    assert not entry["over_limit"] and not entry["stopped"]


def test_finish_target_shortage_uses_the_margin(tmp_path):
    """仕上がり目標に対しては不足が10%未満でも、余地込みの目標で10%以上なら設計追加へ。"""
    work, repo, _ = _ops_bridge(tmp_path, chars=220, floor=200)
    current = _beat_chars(work)
    finish = round(current / 0.93)
    assert shortage_ratio(finish, current) < DESIGN_SHORTAGE_LIMIT
    with pytest.raises(BridgeError) as error:
        _length_begin(work, repo, finish_target(finish))
    assert error.value.code == "DESIGN_DENSITY"


def test_auto_repair_only_measures_and_reports(tmp_path):
    """6-7: 自動修復（初稿直後を含む）は、不足10%以上でも止めずに報告と記録だけ行う。"""
    work, repo, run = _ops_bridge(tmp_path, chars=150, floor=200)
    code, _ = repair_begin(work, model="fixture-writer", authorization="test", repo_root=repo,
                           **SCENE)
    assert code == 0
    state = read_state(run / "repair_state.json")
    assert any(note.startswith("DESIGN_DENSITY") for note in state.notes)
    entry = json.loads((work / "_metron/ch01-001/shortage_log.jsonl").read_text(
        encoding="utf-8").splitlines()[-1])
    assert entry["intent"] == "auto" and entry["over_limit"] and not entry["stopped"]


def test_missing_beats_are_filled_before_the_density_stop(tmp_path):
    """欠落 Beat があるときは、設計追加より先に欠落を埋める（止めずに記録だけ）。"""
    import yaml
    work, repo, run = _ops_bridge(tmp_path, chars=220, floor=200)
    path = repo / "config" / "metron_models.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["models"]["fixture-writer"]["missing_span_ratio"] = 0.95
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    code, _ = _length_begin(work, repo, LengthTarget(target_chars=400))
    assert code == 0
    entry = json.loads((work / "_metron/ch01-001/shortage_log.jsonl").read_text(
        encoding="utf-8").splitlines()[-1])
    assert entry["over_limit"] and not entry["stopped"]


# ── 設計から登録する子エピソード（6-5） ─────────────────────────


def test_episode_registered_before_writing_is_not_condensed_until_span_is_written():
    episode = ChildEpisode(id="E-new", beat_id="a", span_pending=True,
                           state_change=[{"kind": "info", "who": "慎", "before": "知らない",
                                          "after": "休憩室を知る"}],
                           carry_back=[{"what": "休憩室", "used_at": "ch03-001"}])
    with pytest.raises(EpisodeError):
        locate_span(TEXTS["a"], episode)
    with pytest.raises(ValueError):
        ChildEpisode(id="E-x", beat_id="a", span_pending=True,
                     span={"start": "朝の", "end": "確かめる。"})


def test_pending_episode_is_skipped_by_condense():
    from metron.analyze import analyze_marked_text
    from metron.length import LengthSpec, assembled_chars
    from metron.repair import marked_text_for_measurement
    from metron.repair_steps import RepairJob, begin_repair, next_job, submit_result
    from test_metron import _calibration
    plan = _plan(_beat("a", chars_hint=10), _beat("b", chars_hint=10), chars_floor=1)
    analyzed = analyze_marked_text(marked_text_for_measurement(plan, TEXTS), plan, run=1)
    pending = ChildEpisode(id="E-new", beat_id="a", span_pending=True,
                           state_change=[{"kind": "info", "who": "慎", "before": "a", "after": "b"}])
    state = begin_repair(analyzed.metrics, plan, _calibration(), clean_text=analyzed.clean_text,
                         spans=analyzed.spans, model="m", seam_enabled=False,
                         length=LengthSpec(target=LengthTarget(target_chars=40, max_passes=8),
                                           episodes=[pending]))
    operations = []
    for _ in range(10):
        job = next_job(state)
        if not isinstance(job, RepairJob):
            break
        operations.append(job.operation)
        submit_result(state, job_id=job.job_id, model="m", candidate="", error="skip")
    assert "condense" not in operations
    assert any(note.startswith("CONDENSE_SKIPPED") and "pending" in note for note in job.notes)


# ── 欠落 Beat を埋めたあとの不足率（レビュー P1） ───────────────────


def _after_fill(target_of):
    from metron.length import LENGTH_TOKEN, LengthSpec, assembled_chars
    from test_length_phase4 import _drive, _state
    filled = "　券売機の前で、兄は財布の中の硬貨を一枚ずつ数えた。" * 4
    beats = [_beat("a", chars_hint=10), _beat("b", chars_hint=400)]
    total = assembled_chars(_plan(*beats), dict(TEXTS, b=filled))
    state = _state(dict(TEXTS, b="　短い。"), beats, length=LengthSpec(
        target=LengthTarget(target_chars=target_of(total), max_passes=3)))

    def respond(job, text):
        if job.operation == "regenerate":
            return filled, None
        return text.rstrip("\n") + "\n\n　改札の電子音が遠くで鳴り、ホームを渡る風が冷たかった。", None

    result, jobs = _drive(state, respond)
    return result, [job.operation for job in jobs], LENGTH_TOKEN


def test_large_shortage_after_filling_missing_beats_stops_before_deepen():
    result, operations, token = _after_fill(lambda total: total * 2)
    assert operations == ["regenerate"]
    assert token in result.escalated_beats
    assert any(note.startswith("DESIGN_DENSITY") for note in result.notes)


def test_small_shortage_after_filling_missing_beats_deepens():
    result, operations, _ = _after_fill(lambda total: round(total / 0.95))
    assert operations[:2] == ["regenerate", "deepen"]
    assert not any(note.startswith("DESIGN_DENSITY") for note in result.notes)


def test_nested_lists_and_code_blocks_are_not_counted_as_chapter_events():
    """レビュー P2: 字下げした補足やコード例を章出来事に数えない。"""
    events = "\n".join(f"{n}. 慎が{n}番目の部屋に入る。\n   1. 補足: 部屋の札は古い。" for n in range(1, 7))
    design = ("### 第1章「宿」\n\n" + events + "\n\n```text\n1. 例の行\n2. 例の行\n```\n\n"
              "**分量目安**：8,000字。\n")
    row = chapter_densities(design)[0]
    assert row.items == 6
    assert row.verdict.startswith("少なすぎ")


@pytest.mark.parametrize("outer, inner", [("````", "```"), ("~~~~", "~~~"), ("```", "~~~"),
                                          ("~~~", "```")])
def test_inner_fences_do_not_close_the_outer_code_block(outer, inner):
    """再レビュー P2: 閉じるのは同じ文字種・開始時以上の長さのフェンスだけ。"""
    events = "\n".join(f"{n}. 慎が{n}番目の部屋に入る。" for n in range(1, 7))
    sample = "\n".join(f"{n}. 例の行" for n in range(1, 7))
    design = (f"### 第1章「宿」\n\n{events}\n\n{outer}markdown\n{inner}text\n{sample}\n{inner}\n"
              f"{sample}\n{outer}\n\n**分量目安**：8,000字。\n")
    row = chapter_densities(design)[0]
    assert row.items == 6 and row.verdict.startswith("少なすぎ")
