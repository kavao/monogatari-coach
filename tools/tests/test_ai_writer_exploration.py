"""探索機能 E1「別の展開を見る」の模擬通信試験（計画 20261009_ai_writer_creative_exploration.md §8 の受入条件）。"""

from __future__ import annotations

import csv
import hashlib
import json
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from ai_writer import exploration as ex  # noqa: E402
from ai_writer import novelai as nai  # noqa: E402
from ai_writer.exploration_prompts import EXPLORE_RENDERER_VERSION, render_explore  # noqa: E402
from ai_writer.prompt_renderer import ExploreBranchInput  # noqa: E402
from ai_writer.provider import NovelAIProvider  # noqa: E402
from ai_writer.testing import FakeHandle, FakeTransport, sse  # noqa: E402
from ai_writer.transport import TransportError  # noqa: E402

TOKEN = "pst-explore-test"
TEXT = "　雨の駅で、十年ぶりに二人は再会した。\n「久しぶり」と彼女は言った。"
DATA = ExploreBranchInput(TEXT, fixed=("二人はすでに別れている",), free=("再会の理由", "次の選択"))


def provider(t: FakeTransport) -> NovelAIProvider:
    return NovelAIProvider(TOKEN, transport=t, slot=threading.BoundedSemaphore(1), sleep=lambda _s: None)


def new_run(tmp_path: Path, t: FakeTransport, n: int = 3, model: str = "xialong-v1") -> ex.ExplorationRun:
    return ex.ExplorationRun.create(provider(t), tmp_path, DATA, model=model, candidates=n, run_id="run1",
                                    source={"label": "test"})


# ---- 入力の組立 ----------------------------------------------------------------

def test_render_separates_fixed_and_free_and_is_model_neutral() -> None:
    glm = render_explore(DATA, "glm-4-6", sampling={"temperature": 0.8})
    xia = render_explore(DATA, "xialong-v1", sampling={"temperature": 0.8})
    user = glm.request.messages[1]["content"]  # type: ignore[index]
    assert "守ること:\n- 本文にすでに書かれた出来事と、人物どうしの関係\n- 二人はすでに別れている" in user
    assert "自由にしてよいこと:\n- 再会の理由\n- 次の選択" in user
    assert "終わる位置" not in user  # 探索では未指定を許す
    assert glm.version == EXPLORE_RENDERER_VERSION and glm.request.endpoint == "chat"
    body_g, body_x = glm.request.body(), xia.request.body()
    body_g.pop("model"), body_x.pop("model")
    assert body_g == body_x  # 両モデルに同じ入力（共通条件）


# ---- 生成・独立性・保存 ------------------------------------------------------------

def test_run_generates_independent_candidates_and_review_files(tmp_path: Path) -> None:
    t = FakeTransport(sse("　一案目。"), sse("　二案目。\n***\n　翌朝。"), sse("　三案目。\n[解説] 意外性を足した"))
    run = new_run(tmp_path, t)
    summary = run.run()
    assert summary["status"] == "done" and len(summary["saved"]) == 3 and summary["remaining"] == 0
    bodies = [c["body"] for c in t.calls]
    assert bodies[0] == bodies[1] == bodies[2]  # 前の候補を次の要求に混ぜない
    assert all(b["model"] == "xialong-v1" for b in bodies)
    cands = [run.latest(s) for s in run.slots()]
    assert [c.generation_status for c in cands if c] == ["complete"] * 3
    second, third = cands[1], cands[2]
    assert second and second.text == "　二案目。\n***\n　翌朝。"  # *** は切らずにレビューへ
    assert [r["reason"] for r in second.review_items] == ["scene_break"]
    assert third and third.text == "　三案目。" and third.removals[-1]["reason"] == "trailer"
    assert third.guard and "semantic（Phase 2）" in third.guard["not_run"]
    m = json.loads((tmp_path / "run1" / "manifest.json").read_text(encoding="utf-8"))
    assert m["renderer_version"] == EXPLORE_RENDERER_VERSION and m["model"] == "xialong-v1"
    review = (tmp_path / "run1" / "review.md").read_text(encoding="utf-8")
    assert "## 候補 2" in review and "要確認: 場面転換 ***（要確認）" in review
    assert (tmp_path / "run1" / "selections.json").is_file()
    assert TOKEN not in json.dumps(m, ensure_ascii=False)


def test_review_files_keep_filled_evaluations(tmp_path: Path) -> None:
    run = new_run(tmp_path, FakeTransport(sse("一。"), sse("二。")), n=2)
    run.run()
    path = tmp_path / "run1" / "evaluation.csv"
    rows = list(csv.DictReader(path.open(encoding="utf-8", newline="")))
    rows[0].update({"appeal": "4", "adopt": "idea", "note": "再会の理由が意外"})
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    ex.write_review(run)
    again = list(csv.DictReader(path.open(encoding="utf-8", newline="")))
    assert (again[0]["appeal"], again[0]["adopt"], again[0]["note"]) == ("4", "idea", "再会の理由が意外")


# ---- 停止と再開 -----------------------------------------------------------------

def test_stop_saves_partial_and_does_not_send_unstarted(tmp_path: Path) -> None:
    held = FakeHandle(sse("　二案目の途中", finish=None, done=False), hold=True)
    t = FakeTransport(sse("　一案目。"), held, sse("三案目。"))
    run = new_run(tmp_path, t)
    started = threading.Event()
    real_iter = run.provider.stream

    def stream_and_signal(req):  # type: ignore[no-untyped-def]
        gen = real_iter(req)
        if len(t.calls) == 2:
            started.set()
        return gen

    run.provider.stream = stream_and_signal  # type: ignore[method-assign]
    th = threading.Thread(target=run.run)
    th.start()
    assert started.wait(5)
    run.request_stop()
    th.join(5)
    assert not th.is_alive()
    assert len(t.calls) == 2  # 3 件目は送らない
    slots = run.slots()
    assert run.latest(slots[0]).generation_status == "complete"  # type: ignore[union-attr]
    partial = run.latest(slots[1])
    assert partial and partial.generation_status == "incomplete" and partial.raw_text == "　二案目の途中"
    assert run.latest(slots[2]) is None
    assert run.manifest["status"] == "stopped" and held.closed.is_set() and t.active == 0


def test_keyboard_interrupt_saves_partial_and_stops(tmp_path: Path) -> None:
    t = FakeTransport(sse("　一案目。"), sse("　二案目。"))
    run = new_run(tmp_path, t, n=2)
    original = run._generate  # noqa: SLF001
    calls = {"n": 0}

    def generate(*a, **k):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        out, _ = original(*a, **k)
        return out, calls["n"] == 1  # 1 件目の生成中に Ctrl+C が来たことにする

    run._generate = generate  # type: ignore[method-assign]  # noqa: SLF001
    summary = run.run()
    assert summary["stopped"] and len(summary["saved"]) == 1 and len(t.calls) == 1
    assert run.manifest["status"] == "stopped"


def test_resume_skips_complete_and_retries_incomplete_only_when_asked(tmp_path: Path) -> None:
    t = FakeTransport(sse("　一案目。"), FakeHandle(sse("　途中", finish=None, done=False), hold=True))
    run = new_run(tmp_path, t)
    th = threading.Thread(target=run.run)
    th.start()
    while len(t.calls) < 2:
        pass
    run.request_stop()
    th.join(5)
    first_id = run.latest(run.slots()[0]).candidate_id  # type: ignore[union-attr]
    incomplete = run.latest(run.slots()[1])
    assert incomplete
    record_before = (tmp_path / "run1" / "candidates" / incomplete.candidate_id / "record.json").read_bytes()

    # 再開（明示なし）: 未生成の 3 枠目だけ
    t2 = FakeTransport(sse("　三案目。"))
    resumed = ex.ExplorationRun.open(provider(t2), tmp_path / "run1")
    assert [s.index for s, _ in resumed.pending()] == [3]
    assert resumed.run()["status"] == "partial" and len(t2.calls) == 1
    assert resumed.latest(resumed.slots()[0]).candidate_id == first_id  # type: ignore[union-attr]

    # 明示した再試行: 2 枠目を新しい ID で作り直し、親を記録。旧候補は変わらない
    t3 = FakeTransport(sse("　二案目のやり直し。"))
    retry = ex.ExplorationRun.open(provider(t3), tmp_path / "run1")
    assert [s.index for s, _ in retry.pending(retry_incomplete=True)] == [2]
    assert retry.run(retry_incomplete=True)["status"] == "done"
    redo = retry.latest(retry.slots()[1])
    assert redo and redo.candidate_id != incomplete.candidate_id and redo.parent_candidate_id == incomplete.candidate_id
    assert retry.slots()[1].attempts == [incomplete.candidate_id, redo.candidate_id]
    assert (tmp_path / "run1" / "candidates" / incomplete.candidate_id / "record.json").read_bytes() == record_before


# ---- 明示モデル・候補数・正本への非書込み --------------------------------------------------

def test_explicit_model_failure_is_recorded_without_fallback(tmp_path: Path) -> None:
    t = FakeTransport(TransportError(500, "server error"), sse("二。"), sse("三。"))
    run = new_run(tmp_path, t)
    run.run()
    first = run.latest(run.slots()[0])
    assert first and first.generation_status == "error" and first.model == "xialong-v1"
    assert all(c["body"]["model"] == "xialong-v1" for c in t.calls)
    with pytest.raises(ex.ExplorationError, match="切り替えない"):
        ex.ExplorationRun.create(provider(FakeTransport()), tmp_path, DATA, model="llama-3-erato-v1", run_id="x")


@pytest.mark.parametrize("n", [0, 6])
def test_candidate_count_is_limited(tmp_path: Path, n: int) -> None:
    with pytest.raises(ex.ExplorationError, match="候補数"):
        new_run(tmp_path, FakeTransport(), n=n)


def test_existing_run_is_not_overwritten(tmp_path: Path) -> None:
    new_run(tmp_path, FakeTransport(), n=1)
    with pytest.raises(FileExistsError):
        new_run(tmp_path, FakeTransport(), n=1)


def _tree_hash(path: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(path.rglob("*")):
        if p.is_file():
            h.update(str(p.relative_to(path)).encode())
            h.update(p.read_bytes())
    return h.hexdigest()


def test_cli_with_work_dir_reads_but_never_writes_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    work = tmp_path / "novels" / "999_test"
    work.mkdir(parents=True)
    (work / "character.md").write_text("## 美緒（みお）\n\n- **名前**: 美緒（みお）\n", encoding="utf-8")
    (work / "_novel_text").mkdir()
    (work / "_novel_text" / "novel_text.md").write_text("本文の正本。\n", encoding="utf-8")
    text = tmp_path / "start.md"
    text.write_text("　駅のホームで、美緒は振り返った。", encoding="utf-8")
    before = _tree_hash(work)
    t = FakeTransport(sse("　美緒は笑った。"), sse("　森先生が来た。"))
    monkeypatch.setattr(ex, "_provider", lambda: provider(t))
    monkeypatch.setattr(ex, "OUT_ROOT", tmp_path / "creative")
    assert ex.main(["run", "--text-file", str(text), "--work-dir", str(work), "--model", "glm-4-6",
                    "--candidates", "2", "--execute"]) == 0
    assert _tree_hash(work) == before  # 作品フォルダ（正本）は変わらない
    [run_dir] = list((tmp_path / "creative").iterdir())
    run = ex.ExplorationRun.open(provider(FakeTransport()), run_dir)
    second = run.latest(run.slots()[1])
    assert second and second.guard and [f["text"] for f in second.guard["findings"]] == ["森"]  # 美緒は既知
    first = run.latest(run.slots()[0])
    assert first and first.guard and first.guard["status"] == "pass"


def test_cli_plan_is_dry_run_and_requires_model(capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*_a, **_k):  # type: ignore[no-untyped-def]
        raise AssertionError("dry-run でトークンを読んだ／送信した")

    monkeypatch.setattr(nai, "load_token", fail)
    monkeypatch.setattr("ai_writer.transport.UrllibTransport.open_stream", fail)
    assert ex.main(["plan", "--scene", "romance", "--model", "xialong-v1"]) == 0
    out = capsys.readouterr().out
    assert "候補 3 件 = 生成 3 回" in out and "Bearer ***" in out and "xialong-v1（明示）" in out
    assert ex.main(["run", "--scene", "romance", "--model", "glm-4-6", "--candidates", "5"]) == 0  # --execute なしは dry-run
    with pytest.raises(SystemExit):
        ex.main(["plan", "--scene", "romance"])  # モデルの明示は必須
