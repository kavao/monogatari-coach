from __future__ import annotations

import datetime as dt
import json
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from ai_writer.candidates import CandidateError, CandidateStore, input_from_dict, input_to_dict  # noqa: E402
from ai_writer.entities import KnownEntityDictionary  # noqa: E402
from ai_writer.guard import MinimumGuard  # noqa: E402
from ai_writer.manifest import GenerationManifest, SourceRef, build_manifest, content_hash, stale_refs, work_refs  # noqa: E402
from ai_writer.prompt_renderer import BeatContract, ContinueInput, DirectedContinueInput, ExpandInsertionInput  # noqa: E402
from ai_writer.provider import NovelAIProvider  # noqa: E402
from ai_writer.testing import FakeHandle, FakeTransport, sse  # noqa: E402
from ai_writer.transport import TransportError  # noqa: E402
from ai_writer.writer import CoreWriter, WriterOutput  # noqa: E402

TOKEN = "pst-candidate-test"
NOW = dt.datetime(2026, 10, 9, 3, 0, 0, tzinfo=dt.timezone.utc)
SOURCE = "　駅のホームには誰もいなかった。"


def make_writer(*scripts: object, guard: MinimumGuard | None = None) -> tuple[CoreWriter, FakeTransport]:
    t = FakeTransport(*scripts)
    provider = NovelAIProvider(TOKEN, transport=t, slot=threading.BoundedSemaphore(1), sleep=lambda _s: None)
    return CoreWriter(provider, guard=guard), t


def work(tmp_path: Path) -> Path:
    d = tmp_path / "novels" / "999_test"
    d.mkdir(parents=True)
    (d / "character.md").write_text("## 悠真（ゆうま）\n\n- **名前**: 悠真（ゆうま）\n", encoding="utf-8")
    (d / "world.md").write_text("舞台は廃駅。もう列車は来ない。\n", encoding="utf-8")
    return d


def cancelled_output(w: CoreWriter) -> WriterOutput:
    session = w.start("continue", ContinueInput(SOURCE))
    text = ""
    for chunk in session:
        text += chunk.text
        if "途中" in text:
            session.cancel()
            break
    return session.finish()


# ---- Manifest ------------------------------------------------------------------

def test_manifest_records_versions_counts_and_refs(tmp_path: Path) -> None:
    d = work(tmp_path)
    w, _ = make_writer(sse("　風が吹いた。", "ベンチがきしんだ。"), guard=MinimumGuard())
    out = w.run("continue", ContinueInput(SOURCE))
    refs = work_refs(d, tmp_path) + [SourceRef.from_text("source_text", "scene-1", SOURCE)]
    m = build_manifest(out, refs=refs, scene_id="scene-1", beat_id="beat-2", constraint_ids=["c-1"], now=NOW)
    assert (m.model, m.operation, m.route_reason, m.capability_revision) == ("glm-4-6", "continue", "default", out.route.profile_revision)
    assert (m.renderer_version, m.postprocess_version, m.guard_version) == ("nai-r2", "pp-1", "mg-2")
    assert m.render_params == {"target_chars": 400, "resolved_max_tokens": 307}
    assert m.output_chars == 16 and m.raw_chars == 16 and m.output_tokens == 16  # 「　風が吹いた。」7 字＋「ベンチがきしんだ。」9 字
    assert m.context_tokens and m.context_tokens_method == "benchmark_estimate"
    assert m.generation_status == "complete" and m.validation_status == "pass"
    assert [r.path for r in m.refs] == ["novels/999_test/character.md", "novels/999_test/world.md", None]
    assert m.created_at == "2026-10-09T03:00:00+00:00"
    assert GenerationManifest.from_dict(json.loads(json.dumps(m.to_dict()))) == m
    assert TOKEN not in json.dumps(m.to_dict(), ensure_ascii=False)


def test_prompt_hash_follows_the_request_body() -> None:
    w, _ = make_writer(sse("一。"), sse("二。"), sse("三。"))
    a = build_manifest(w.run("continue", ContinueInput(SOURCE)))
    b = build_manifest(w.run("continue", ContinueInput(SOURCE)))
    c = build_manifest(w.run("continue", ContinueInput(SOURCE + "別の本文。")))
    assert a.prompt_hash == b.prompt_hash != c.prompt_hash


def test_content_hash_ignores_newline_style_and_normalization() -> None:
    assert content_hash("が\r\n") == content_hash("が\n")


def test_stale_refs_detects_changed_and_missing_files(tmp_path: Path) -> None:
    d = work(tmp_path)
    w, _ = make_writer(sse("一。"))
    m = build_manifest(w.run("continue", ContinueInput(SOURCE)),
                       refs=work_refs(d, tmp_path) + [SourceRef.from_text("source_text", "s", SOURCE)])
    assert stale_refs(m, tmp_path) == []
    (d / "character.md").write_text("## 悠真（ゆうま）\n\n- **名前**: 悠真（ゆうま）\n- **一人称**: 僕\n", encoding="utf-8")
    (d / "world.md").unlink()
    stale = {(s.ref.path, s.reason) for s in stale_refs(m, tmp_path)}
    assert stale == {("novels/999_test/character.md", "changed"), ("novels/999_test/world.md", "missing")}


# ---- Candidate Store -------------------------------------------------------------

def test_save_writes_immutable_files_and_unreviewed_state(tmp_path: Path) -> None:
    store = CandidateStore(tmp_path / "store", clock=lambda: NOW)
    w, _ = make_writer(sse("\n　風が吹いた。", "\n***\n[解説] 雰囲気を足した"))
    out = w.run("continue", ContinueInput(SOURCE))
    cand = store.save(out, build_manifest(out, now=NOW), run_id="run-1")
    d = tmp_path / "store" / "candidates" / cand.candidate_id
    assert (d / "raw.txt").read_text(encoding="utf-8") == "\n　風が吹いた。\n***\n[解説] 雰囲気を足した"
    assert (d / "output.txt").read_text(encoding="utf-8") == "　風が吹いた。"
    assert store.load(cand.candidate_id) == cand
    assert cand.generation_status == "complete" and cand.run_id == "run-1"
    assert {r["reason"] for r in cand.removals} >= {"scene_break"}
    assert store.review(cand.candidate_id).status == "unreviewed"
    assert TOKEN not in (d / "record.json").read_text(encoding="utf-8")


def test_regeneration_gets_a_new_id_and_never_overwrites(tmp_path: Path) -> None:
    store = CandidateStore(tmp_path)
    w, _ = make_writer(sse("一。"), sse("二。"))
    first = store.save(o := w.run("continue", ContinueInput(SOURCE)), build_manifest(o))
    before = (tmp_path / "candidates" / first.candidate_id / "record.json").read_bytes()
    second = store.save(o2 := w.run("continue", ContinueInput(SOURCE)), build_manifest(o2), parent_id=first.candidate_id)
    assert second.candidate_id != first.candidate_id and second.parent_candidate_id == first.candidate_id
    assert (tmp_path / "candidates" / first.candidate_id / "record.json").read_bytes() == before
    with pytest.raises(CandidateError, match="候補がない"):
        store.save(o2, build_manifest(o2), parent_id="c20000101T000000-00000000")


def test_review_transitions_and_history(tmp_path: Path) -> None:
    store = CandidateStore(tmp_path)
    w, _ = make_writer(sse("一。"), TransportError(500, "boom"))
    ok = store.save(o := w.run("continue", ContinueInput(SOURCE)), build_manifest(o))
    store.set_review(ok.candidate_id, "selected", note="この表現が良い")
    state = store.set_review(ok.candidate_id, "adopted")
    assert state.status == "adopted" and [h["status"] for h in state.history] == ["unreviewed", "selected", "adopted"]
    with pytest.raises(CandidateError, match="変えられない"):
        store.set_review(ok.candidate_id, "rejected")
    failed = store.save(o2 := w.run("continue", ContinueInput(SOURCE)), build_manifest(o2))
    assert failed.generation_status == "error" and failed.error == "boom"
    with pytest.raises(CandidateError, match="失敗"):
        store.set_review(failed.candidate_id, "selected")
    assert [c.candidate_id for c in store.find(review_status="adopted")] == [ok.candidate_id]
    assert [c.candidate_id for c in store.find(generation_status="error")] == [failed.candidate_id]


def test_incomplete_candidate_keeps_partial_and_guard(tmp_path: Path) -> None:
    store = CandidateStore(tmp_path)
    known = KnownEntityDictionary()
    w, t = make_writer(FakeHandle(sse("　駅員がいた。", "途中で"), hold=True), guard=MinimumGuard(known))
    out = cancelled_output(w)
    cand = store.save(out, build_manifest(out))
    assert cand.generation_status == "incomplete" and cand.cancelled
    assert cand.raw_text == "　駅員がいた。途中で" and cand.text == "　駅員がいた。"
    assert cand.guard and cand.guard["status"] == "warning"  # 部分出力も Guard を通す（§47）
    assert cand.manifest["generation_status"] == "incomplete"
    assert store.incomplete_actions(cand.candidate_id) == ["adopt_partial", "continue", "discard"]
    assert t.active == 0


def test_incomplete_candidate_needs_explicit_partial_adoption(tmp_path: Path) -> None:
    store = CandidateStore(tmp_path)
    w, _ = make_writer(FakeHandle(sse("　一文目。", "途中で"), hold=True))
    cand = store.save(o := cancelled_output(w), build_manifest(o))
    with pytest.raises(CandidateError, match="partial=True"):
        store.set_review(cand.candidate_id, "selected")
    state = store.adopt_partial(cand.candidate_id)
    assert state.status == "selected" and state.partial
    assert store.set_review(cand.candidate_id, "adopted").partial is True


def test_continue_from_incomplete_creates_child_candidate(tmp_path: Path) -> None:
    store = CandidateStore(tmp_path)
    w, t = make_writer(FakeHandle(sse("　一文目。", "途中で"), hold=True), sse("二文目。"))
    parent = store.save(o := cancelled_output(w), build_manifest(o))
    op, data = store.continuation_input(parent.candidate_id)
    assert op == "continue" and isinstance(data, ContinueInput) and data.text == SOURCE + "　一文目。"
    child_out = w.run(op, data)
    child = store.save(child_out, build_manifest(child_out), parent_id=parent.candidate_id)
    assert child.parent_candidate_id == parent.candidate_id and child.generation_status == "complete"
    assert t.calls[1]["body"]["prompt"] == SOURCE + "　一文目。"
    store.discard(parent.candidate_id)
    assert store.review(parent.candidate_id).status == "rejected"
    with pytest.raises(CandidateError, match="途中で止めた"):
        store.continuation_input(child.candidate_id)


def test_input_round_trip_for_all_operations() -> None:
    for data in (ContinueInput("本文"), ExpandInsertionInput("前", "後", 60),
                 DirectedContinueInput("本文", BeatContract("目的", "終わり", 400, ("a",), ("b",)), ("事実",)),
                 DirectedContinueInput("本文", BeatContract("目的", "終わり", 400), (), instruction_multiplier=2.0)):
        assert input_from_dict(json.loads(json.dumps(input_to_dict(data)))) == data


def test_candidate_id_cannot_escape_the_store(tmp_path: Path) -> None:
    store = CandidateStore(tmp_path)
    for bad in ("../x", "a/b", ".hidden", ""):
        with pytest.raises(CandidateError):
            store.load(bad)


def test_refs_outside_repo_use_absolute_path_and_still_detect_changes(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "elsewhere" / "character.md"
    outside.parent.mkdir()
    outside.write_text("## 悠真\n", encoding="utf-8")
    ref = SourceRef.from_file("character", outside, repo)
    assert ref.path == outside.resolve().as_posix()
    w, _ = make_writer(sse("一。"))
    m = build_manifest(w.run("continue", ContinueInput(SOURCE)), refs=[ref])
    assert stale_refs(m, repo) == []
    outside.write_text("## 悠真（変更）\n", encoding="utf-8")
    assert [s.reason for s in stale_refs(m, repo)] == ["changed"]
