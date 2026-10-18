from __future__ import annotations

import datetime as dt
import hashlib
import json
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from ai_writer import compare as cmp  # noqa: E402
from ai_writer.provider import NovelAIProvider  # noqa: E402
from ai_writer.testing import FakeTransport, sse  # noqa: E402
from ai_writer.writer import CoreWriter  # noqa: E402

CONTRACT = """scene:
  id: ch01-001
  pov: 悠真
  end_state:
    action: 湯の縁へ招かれる
  forbidden:
    - 湯船に入ること
"""

BEATS = """generation:
  granularity: auto
  chars_floor: 40
beats:
  - id: reach_station
    type: action
    intent: 悠真が桜見駅の改札を出る
    budget: {paragraphs: [1, 3], dialogue_turns: [0, 1], sensory: 1, interiority: 1, new_facts: 1, chars_hint: 30}
  - id: see_sign
    type: discovery
    intent: 悠真が看板を見上げる
    budget: {paragraphs: [1, 3], dialogue_turns: [0, 1], sensory: 1, interiority: 1, new_facts: 1, chars_hint: 30}
"""

DESIGN = """# 設計書

### 第1章「屋号を見て押した」

**目的**: 悠真が店に入る。

1. 悠真が改札を出る。
   - 入れ子の補足は数えない
2. 悠真が看板を見上げる。

---

### 第2章「次」

1. 別の章。
"""

STATION = "金曜の終業後、俺は一本乗り換えて桜見駅の改札を出た。風が冷たかった。"
SIGN = "駅前ビルの二階に、あいかの電飾看板が灯っていた。指先の迷いを思い出す。"


def make_work(repo: Path) -> Path:
    work = repo / "novels" / "900_比較テスト"
    metron = work / "_metron" / "ch01-001"
    metron.mkdir(parents=True)
    (metron / "contract.yaml").write_text(CONTRACT, encoding="utf-8")
    (metron / "beats.yaml").write_text(BEATS, encoding="utf-8")
    (work / "design_specification.md").write_text(DESIGN, encoding="utf-8")
    (work / "_novel_text").mkdir()
    (work / "_novel_text" / "novel_text01.md").write_text("# 第1章\n\n正本。\n", encoding="utf-8")
    (work / "_writing" / "ch01-001" / "run-0001").mkdir(parents=True)
    return work


def snapshot(root: Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


def writer(*scripts: object) -> tuple[CoreWriter, FakeTransport]:
    t = FakeTransport(*scripts)
    p = NovelAIProvider("pst-compare-test", transport=t, slot=threading.BoundedSemaphore(1), sleep=lambda _s: None)
    return CoreWriter(p), t


NOW = dt.datetime(2026, 10, 18, 19, 0, 0)


def test_parse_chapter_design_reads_title_objective_and_top_level_items() -> None:
    design = cmp.parse_chapter_design(DESIGN, 1)
    assert design is not None
    assert design.title == "「屋号を見て押した」"
    assert design.objective == "悠真が店に入る。"
    assert design.items == ("悠真が改札を出る。", "悠真が看板を見上げる。")
    assert cmp.parse_chapter_design(DESIGN, 3) is None


def test_beat_contracts_come_from_metron_and_facts_override(tmp_path: Path) -> None:
    work = make_work(tmp_path)
    inputs = cmp.load_inputs(work, "ch01-001")
    rows = cmp.beat_contracts(inputs)
    assert [b.id for b, _ in rows] == ["reach_station", "see_sign"]
    first, last = rows[0][1], rows[1][1]
    assert first.objective == "悠真が桜見駅の改札を出る" and first.target_chars == 30
    assert "悠真が看板を見上げる" in first.end_condition and "湯の縁へ招かれる" in last.end_condition
    assert "湯船に入ること" in first.must_not and cmp.COMMON_MUST_NOT[0] in first.must_not
    facts = tmp_path / "facts.yaml"
    facts.write_text("canon_facts: [語り手は悠真]\nbeats:\n  see_sign:\n    must_include: [二階の看板]\n"
                     "    end_condition: 階段の前で止める\n", encoding="utf-8")
    inputs = cmp.load_inputs(work, "ch01-001", facts_path=facts)
    see = cmp.beat_contracts(inputs)[1][1]
    assert see.must_include == ("二階の看板",) and see.end_condition == "階段の前で止める"
    assert cmp.canon_facts(inputs) == ("語り手は悠真",)


def test_plan_writes_context_and_plan_without_sending(tmp_path: Path) -> None:
    work = make_work(tmp_path)
    before = snapshot(work)
    w, transport = writer()
    run_dir = cmp.plan_run(tmp_path, cmp.load_inputs(work, "ch01-001"), ("local", "nai"), writer=w, now=NOW)
    assert run_dir == tmp_path / "_workingspace" / "ai_writer" / "900_ch01_compare" / "run-20261018_190000"
    plan = json.loads((run_dir / "plan.json").read_text(encoding="utf-8"))
    assert plan["paid_calls"] == 2 and plan["executed"] == {}
    nai = next(e for e in plan["writers"] if e["writer"] == "nai")
    assert nai["candidate_dir"] == "candidates/nai-glm-4-6" and [b["beat"] for b in nai["beats"]] == [
        "reach_station", "see_sign"]
    context = (run_dir / "context.md").read_text(encoding="utf-8")
    assert "<!--beat:<id>-->" in context and "悠真が改札を出る。" in context and "入れ子" not in context
    assert transport.calls == []
    assert snapshot(work) == before


def test_execute_nai_sends_planned_beats_once_and_marks_boundaries(tmp_path: Path) -> None:
    work = make_work(tmp_path)
    before = snapshot(work)
    inputs = cmp.load_inputs(work, "ch01-001")
    plan_writer, _ = writer()
    run_dir = cmp.plan_run(tmp_path, inputs, ("nai",), writer=plan_writer, now=NOW)
    w, transport = writer(sse(STATION), sse(SIGN))
    result = cmp.execute_nai(run_dir, inputs, w)
    assert result["calls_sent"] == 2 and result["stopped_at"] is None and len(transport.calls) == 2
    marked = (run_dir / "candidates" / "nai-glm-4-6" / "marked.md").read_text(encoding="utf-8")
    assert marked.startswith("# 第1章「屋号を見て押した」\n")
    assert "<!--beat:reach_station-->" in marked and "<!--/beat:see_sign-->" in marked
    with pytest.raises(cmp.CompareError):
        cmp.execute_nai(run_dir, inputs, writer()[0])
    assert snapshot(work) == before


def test_execute_nai_stops_on_incomplete_and_keeps_partial_beat(tmp_path: Path) -> None:
    work = make_work(tmp_path)
    inputs = cmp.load_inputs(work, "ch01-001")
    run_dir = cmp.plan_run(tmp_path, inputs, ("nai",), writer=writer()[0], now=NOW)
    w, transport = writer(sse("金曜の終業を待ちわびていた。", finish=None, done=False))
    result = cmp.execute_nai(run_dir, inputs, w)
    assert result["stopped_at"] == "reach_station" and result["calls_sent"] == 1 and len(transport.calls) == 1
    marked = (run_dir / "candidates" / "nai-glm-4-6" / "marked.md").read_text(encoding="utf-8")
    assert "<!--beat:reach_station-->" in marked and "see_sign" not in marked


def test_execute_nai_refuses_when_beats_changed_after_plan(tmp_path: Path) -> None:
    work = make_work(tmp_path)
    plan_writer, _ = writer()
    run_dir = cmp.plan_run(tmp_path, cmp.load_inputs(work, "ch01-001"), ("nai",), writer=plan_writer, now=NOW)
    beats = work / "_metron" / "ch01-001" / "beats.yaml"
    beats.write_text(BEATS.replace("see_sign", "look_up"), encoding="utf-8")
    w, transport = writer()
    with pytest.raises(cmp.CompareError):
        cmp.execute_nai(run_dir, cmp.load_inputs(work, "ch01-001"), w)
    assert transport.calls == []


def test_receive_and_measure_write_only_inside_run(tmp_path: Path) -> None:
    work = make_work(tmp_path)
    before = snapshot(work)
    inputs = cmp.load_inputs(work, "ch01-001")
    plan_writer, _ = writer()
    run_dir = cmp.plan_run(tmp_path, inputs, ("local", "nai"), writer=plan_writer, now=NOW)
    cmp.execute_nai(run_dir, inputs, writer(sse(STATION), sse(SIGN))[0])
    local = tmp_path / "local.md"
    local.write_text(f"# 第1章\n\n<!--beat:reach_station-->\n{STATION}\n<!--/beat:reach_station-->\n\n"
                     f"<!--beat:see_sign-->\n{SIGN}\n<!--/beat:see_sign-->\n", encoding="utf-8")
    cmp.receive_candidate(run_dir, "local", local)
    with pytest.raises(cmp.CompareError):
        cmp.receive_candidate(run_dir, "local", local)
    with pytest.raises(cmp.CompareError):
        cmp.receive_candidate(run_dir, "nai", local)
    summary = cmp.measure_run(run_dir, inputs)
    rows = {r["writer"]: r for r in summary["writers"]}
    assert rows["local"]["status"] == "measured" and rows["nai"]["status"] == "measured"
    assert rows["local"]["floor_met"] is True and set(rows["local"]["beats"]) == {"reach_station", "see_sign"}
    assert (run_dir / "metrics" / "local-writer" / "metrics.yaml").is_file()
    skeleton = (run_dir / "review_skeleton.md").read_text(encoding="utf-8")
    assert "| reach_station | 30 |" in skeleton and "## 項ごとの突き合わせ" in skeleton
    assert snapshot(work) == before


def test_measure_reports_broken_markers_without_stopping(tmp_path: Path) -> None:
    work = make_work(tmp_path)
    inputs = cmp.load_inputs(work, "ch01-001")
    run_dir = cmp.plan_run(tmp_path, inputs, ("local",), now=NOW)
    broken = tmp_path / "broken.md"
    broken.write_text(f"<!--beat:reach_station-->\n{STATION}\n", encoding="utf-8")
    cmp.receive_candidate(run_dir, "local", broken)
    row = cmp.measure_run(run_dir, inputs)["writers"][0]
    assert row["status"] == "marker_errors" and row["marker_errors"]


def test_run_command_does_not_send_without_execute(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cmp.main(["run", str(tmp_path), "--writer", "nai"]) == 2
    assert "未送信" in capsys.readouterr().out


def test_repeated_sentences_counts_copies_across_beats() -> None:
    text = STATION + SIGN + STATION + "短い。短い。"
    rep = cmp.repeated_sentences(text)
    assert rep["sentences"] == 1 and rep["extra_chars"] == len("金曜の終業後、俺は一本乗り換えて桜見駅の改札を出た。")
    assert cmp.repeated_sentences(STATION + SIGN) == {"sentences": 0, "extra_chars": 0}
