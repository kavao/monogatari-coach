"""探索機能 E2 実験A（creative_bench）の模擬通信試験。"""

from __future__ import annotations

import csv
import json
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from ai_writer import creative_bench as cb  # noqa: E402
from ai_writer import novelai as nai  # noqa: E402
from ai_writer.exploration_prompts import render_explore  # noqa: E402
from ai_writer.provider import NovelAIProvider  # noqa: E402
from ai_writer.testing import FakeTransport, sse  # noqa: E402
from ai_writer.transport import TransportError  # noqa: E402


def provider(t: FakeTransport) -> NovelAIProvider:
    return NovelAIProvider("pst-cbench-test", transport=t, slot=threading.BoundedSemaphore(1), sleep=lambda _s: None)


def test_fixture_has_six_tasks_and_judge_only_is_not_sent() -> None:
    fx = cb.load_fixture()
    assert [t.theme for t in fx.tasks] == ["対人の迷い", "探索", "危機", "恋愛", "コメディ", "SF"]
    for task in fx.tasks:
        bodies = {}
        for model in nai.CHAT_MODELS:
            body = render_explore(cb.task_input(task, fx.target_chars), model, sampling={"temperature": 0.8}).request.body()
            user = body["messages"][1]["content"]
            assert all(f in user for f in task.fixed) and all(f in user for f in task.free)
            assert not any(j in user for j in task.judge_only), task.id
            body.pop("model")
            bodies[model] = body
        assert bodies["glm-4-6"] == bodies["xialong-v1"]


def test_cells_alternate_model_order() -> None:
    order = [(t.id, m) for t, m in cb.cells(cb.load_fixture())]
    assert len(order) == 12
    assert order[:4] == [("daily", "glm-4-6"), ("daily", "xialong-v1"), ("explore", "xialong-v1"), ("explore", "glm-4-6")]


def _run_two(tmp_path: Path, *scripts: object) -> tuple[Path, FakeTransport]:
    fx = cb.load_fixture()
    t = FakeTransport(*scripts)
    bench = tmp_path / "bench"
    cb.run_bench(provider(t), bench, fx, cb.cells(fx, ["daily"]))
    return bench, t


def test_run_bench_and_resume_without_resending(tmp_path: Path) -> None:
    bench, t = _run_two(tmp_path, *[sse(f"　案{i}。") for i in range(6)])
    assert len(t.calls) == 6
    assert [c["body"]["model"] for c in t.calls] == ["glm-4-6"] * 3 + ["xialong-v1"] * 3
    run_dir = bench / "runs" / "daily__glm-4-6"
    rec = json.loads(next((run_dir / "candidates").iterdir()).joinpath("record.json").read_text(encoding="utf-8"))
    assert rec["generation"]["total_sec"] is not None and rec["generation"]["attempts"] == 1
    t2 = FakeTransport()
    cb.run_bench(provider(t2), bench, cb.load_fixture(), cb.cells(cb.load_fixture(), ["daily"]))
    assert t2.calls == []  # 成功済みは送り直さない


def test_blind_sheets_hide_models_and_keep_scores(tmp_path: Path) -> None:
    bench, _ = _run_two(tmp_path, sse("　一。"), TransportError(500, "x"), sse("　三。"), sse("　四。"), sse("　五。"), sse("　六。"))
    assert cb.write_sheets(bench, provider(FakeTransport())) == 2
    review = (bench / "blind" / "review.md").read_text(encoding="utf-8")
    assert "glm" not in review and "xialong" not in review
    assert "採点者だけが参照する事実" in review
    key = json.loads((bench / "blind" / "key.json").read_text(encoding="utf-8"))
    assert {k["model"] for k in key.values()} == set(nai.CHAT_MODELS)
    rows = list(csv.DictReader((bench / "blind" / "candidates.csv").open(encoding="utf-8", newline="")))
    assert len(rows) == 6 and sum(1 for r in rows if r["excluded"] == "error") == 1
    rows[0].update({"appeal": "4", "note": "記入"})
    with (bench / "blind" / "candidates.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    cb.write_sheets(bench, provider(FakeTransport()))
    again = list(csv.DictReader((bench / "blind" / "candidates.csv").open(encoding="utf-8", newline="")))
    assert (again[0]["appeal"], again[0]["note"]) == ("4", "記入")


def test_report_unblinds_scores_by_model(tmp_path: Path) -> None:
    bench, _ = _run_two(tmp_path, *[sse(f"　案{i}。駅で待つ。") for i in range(6)])
    cb.write_sheets(bench, provider(FakeTransport()))
    key = json.loads((bench / "blind" / "key.json").read_text(encoding="utf-8"))
    model_of = {code: k["model"] for code, k in key.items()}
    path = bench / "blind" / "candidates.csv"
    rows = list(csv.DictReader(path.open(encoding="utf-8", newline="")))
    for r in rows:
        glm = model_of[r["code"]] == "glm-4-6"
        r.update({"naturalness": "4", "appeal": "3" if glm else "5", "character": "4", "lore": "5",
                  "useful_surprise": "2" if glm else "4", "adopt": "none" if glm else "idea", "fix_fact": "0", "fix_taste": "1"})
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    gpath = bench / "blind" / "groups.csv"
    grows = list(csv.DictReader(gpath.open(encoding="utf-8", newline="")))
    for r in grows:
        glm = model_of[r["code"]] == "glm-4-6"
        r.update({"diversity": "2" if glm else "4", "adoptable_any": "0" if glm else "1", "review_minutes": "5"})
    with gpath.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(grows[0].keys()))
        w.writeheader()
        w.writerows(grows)
    report = cb.build_report(bench, provider(FakeTransport()))
    assert "| glm-4-6 | 3 | 4.00±0.00 | 3.00±0.00 | 4.00±0.00 | 5.00±0.00 | 2.00±0.00 | 0/0/0/3 |" in report
    assert "| xialong-v1 | 3 | 4.00±0.00 | 5.00±0.00 | 4.00±0.00 | 5.00±0.00 | 4.00±0.00 | 0/0/3/0 |" in report
    assert "| glm-4-6 | 1 | 2.00 | 0/1 | 5.00 |" in report and "| xialong-v1 | 1 | 4.00 | 1/1 | 5.00 |" in report
    assert "| daily（対人の迷い） | 3.00±0.00 / 2.00±0.00 / 2 | 5.00±0.00 / 4.00±0.00 / 4 |" in report


def test_plan_is_dry_run(capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*_a, **_k):  # type: ignore[no-untyped-def]
        raise AssertionError("dry-run でトークンを読んだ／送信した")

    monkeypatch.setattr(nai, "load_token", fail)
    monkeypatch.setattr("ai_writer.transport.UrllibTransport.open_stream", fail)
    assert cb.main(["run"]) == 0
    out = capsys.readouterr().out
    assert "生成 36 回" in out and "Bearer ***" in out
