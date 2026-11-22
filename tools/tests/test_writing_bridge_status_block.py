"""章末ステータス（CHAPTER_STATUS）と writing_bridge：ブロックの保持と status_block の run。

受け入れ条件（計画 _workingspace/plans/20261121_chapter-status-display.md §7 P5）の ①②⑥⑧。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from test_writing_bridge import ROOT, _copy_ok
from test_writing_bridge_publish import AUTH, OBS
import chapter_status as cs
from novel_project_check import _measured_text_hashes
from writing_bridge.commands import inspect, prepare, receive
from writing_bridge.errors import BridgeError
from writing_bridge.hashes import raw_sha256, text_sha256
from writing_bridge.models import RequestKind, Selector, SelectorKind
from writing_bridge.publish import compose_published, publish, read_publish_state, replacement_span

BLOCK = cs.render_block("《記録》技能「時刻読み」を得た")
TEXT = "work/_novel_text/novel_text01.md"


# ── ① 編集範囲はブロックの手前まで ─────────────────────────────


def test_replacement_span_stops_before_block() -> None:
    text = "# 第一章\n\n　本文。\n\n" + BLOCK
    limit = cs.body_end(text)
    assert replacement_span(text, scene_id="ch01-001", selector=None, request_kind=RequestKind.APPEND) == (limit, limit)
    heading = Selector(kind=SelectorKind.HEADING, value="第一章")
    start, end = replacement_span(text, scene_id="ch01-001", selector=heading, request_kind=RequestKind.NEW)
    assert end == limit
    composed, _, suffix = compose_published(
        text, "# 第一章\n\n　書き直した本文。\n", scene_id="ch01-001", selector=heading,
        request_kind=RequestKind.NEW,
    )
    assert composed.endswith(BLOCK) and "書き直した本文" in composed
    appended, _, _ = compose_published(
        text, "　足した段落。\n", scene_id="ch01-001", selector=None, request_kind=RequestKind.APPEND
    )
    assert appended.index("足した段落") < appended.index("<!-- status:begin -->")
    assert appended.endswith(BLOCK)


def test_scene_anchor_span_is_clipped_at_block() -> None:
    text = "<!-- scene: ch01-001 -->\n　本文。\n\n" + BLOCK
    start, end = replacement_span(text, scene_id="ch01-001", selector=None, request_kind=RequestKind.NEW)
    assert text[end:].lstrip("\n").startswith("<!-- status:begin -->")


def _with_block(tmp_path: Path) -> Path:
    work = _copy_ok(tmp_path)
    text = work / "_novel_text" / "novel_text01.md"
    text.write_text(text.read_text(encoding="utf-8").rstrip("\n") + "\n\n" + BLOCK, encoding="utf-8")
    return work


def _publish_scene(work: Path, *, dry_run: bool = False) -> tuple[int, str]:
    prepare(
        work, scene_id="ch01-001", text_path="_novel_text/novel_text01.md", request_kind=RequestKind.NEW,
        model_id="local-writer", selector=Selector(kind=SelectorKind.HEADING, value="第一章　駅までの道"),
        links_path=None, repo_root=ROOT, allow_publish=True,
    )
    receive(work, scene_id="ch01-001", run_id="run-0001",
            candidate=work / "_metron" / "ch01-001" / "marked.md", request_id=None)
    inspect(work, scene_id="ch01-001", run_id="run-0001", observations_path=OBS, marked_path=None, repo_root=ROOT)
    if dry_run:
        publish(work, scene_id="ch01-001", run_id="run-0001", authorization=AUTH, repo_root=ROOT,
                observations_path=OBS, dry_run=True)
    return publish(work, scene_id="ch01-001", run_id="run-0001", authorization=AUTH, repo_root=ROOT,
                   observations_path=OBS)


def test_publish_keeps_block_and_hash_matches_plan(tmp_path: Path) -> None:
    work = _with_block(tmp_path)
    code, _ = _publish_scene(work, dry_run=True)
    text = work / "_novel_text" / "novel_text01.md"
    body = text.read_text(encoding="utf-8")
    assert code == 0
    assert body.endswith(BLOCK) and body.count("<!-- status:begin -->") == 1
    assert "旅行用の上着" in body
    state = read_publish_state(work / "_work" / "writing" / "ch01-001" / "run-0001" / "publish_state.json")
    # ② 保存予定全文（ブロックを含む）のハッシュと、書いた全文が一致する。
    assert state.intended_raw_sha256 == raw_sha256(text)
    assert BLOCK in state.suffix


# ── ⑥⑧ status_block の run ─────────────────────────────


def _status_block_run(work: Path, content: str, run_id: str) -> tuple[int, str]:
    prepare(
        work, scene_id="ch01-001", text_path="_novel_text/novel_text01.md",
        request_kind=RequestKind.STATUS_BLOCK, model_id="local-writer", selector=None,
        links_path=None, repo_root=ROOT, allow_publish=True,
    )
    candidate = work / "status_candidate.md"
    candidate.write_text(content, encoding="utf-8")
    receive(work, scene_id="ch01-001", run_id=run_id, candidate=candidate, request_id=None)
    return publish(work, scene_id="ch01-001", run_id=run_id, authorization=AUTH, repo_root=ROOT)


def _is_measured(work: Path) -> bool:
    text = work / "_novel_text" / "novel_text01.md"
    hashes = _measured_text_hashes(work, 1)["hashes"].get("_novel_text/novel_text01.md", set())
    return text_sha256(text.read_text(encoding="utf-8")) in hashes


def test_status_block_update_keeps_chapter_measured(tmp_path: Path) -> None:
    work = _with_block(tmp_path)
    _publish_scene(work)
    assert _is_measured(work)
    before_body = cs.split_body_and_tail((work / "_novel_text" / "novel_text01.md").read_text(encoding="utf-8"))[0]

    code, message = _status_block_run(work, "《記録》技能「時刻読み」が第二段階に至った\n", "run-0002")
    text = (work / "_novel_text" / "novel_text01.md").read_text(encoding="utf-8")
    assert code == 0 and "published status block" in message
    assert "第二段階" in text and text.count("<!-- status:begin -->") == 1
    assert cs.split_body_and_tail(text)[0] == before_body
    assert _is_measured(work)
    assert not list((work / "_metron" / "ch01-001").glob("marked_*.md")) or all(
        "第二段階" not in p.read_text(encoding="utf-8")
        for p in (work / "_metron" / "ch01-001").glob("marked*.md")
    )
    again = publish(work, scene_id="ch01-001", run_id="run-0002", authorization=AUTH, repo_root=ROOT)
    assert "already published" in again[1]

    # 空の候補はブロックを外す。
    code, _ = _status_block_run(work, "\n", "run-0003")
    text = (work / "_novel_text" / "novel_text01.md").read_text(encoding="utf-8")
    assert code == 0 and "<!-- status:" not in text and _is_measured(work)


def test_status_block_refuses_unmeasured_text(tmp_path: Path) -> None:
    work = _with_block(tmp_path)
    with pytest.raises(BridgeError) as caught:
        _status_block_run(work, "x\n", "run-0001")
    assert caught.value.code == "STALE_EVIDENCE"
    assert (work / "_novel_text" / "novel_text01.md").read_text(encoding="utf-8").endswith(BLOCK)


def test_status_block_refuses_body_change_after_begin(tmp_path: Path) -> None:
    work = _with_block(tmp_path)
    _publish_scene(work)
    prepare(
        work, scene_id="ch01-001", text_path="_novel_text/novel_text01.md",
        request_kind=RequestKind.STATUS_BLOCK, model_id="local-writer", selector=None,
        links_path=None, repo_root=ROOT, allow_publish=True,
    )
    candidate = work / "status_candidate.md"
    candidate.write_text("y\n", encoding="utf-8")
    receive(work, scene_id="ch01-001", run_id="run-0002", candidate=candidate, request_id=None)
    # 計測していない本文の変更（ブロックの外）を混ぜてから保存しようとする。
    text = work / "_novel_text" / "novel_text01.md"
    body, tail = cs.split_body_and_tail(text.read_text(encoding="utf-8"))
    text.write_text(body + "　計測していない追記。\n" + tail, encoding="utf-8")
    with pytest.raises(BridgeError) as caught:
        publish(work, scene_id="ch01-001", run_id="run-0002", authorization=AUTH, repo_root=ROOT)
    assert caught.value.code == "STALE_EVIDENCE"


def test_status_block_is_not_inspected_and_rejects_markers(tmp_path: Path) -> None:
    work = _with_block(tmp_path)
    _publish_scene(work)
    with pytest.raises(BridgeError) as caught:
        _status_block_run(work, "<!-- status:begin -->\nx\n<!-- status:end -->\n", "run-0002")
    assert caught.value.code == "JOB_CONFLICT"
    with pytest.raises(BridgeError) as inspected:
        inspect(work, scene_id="ch01-001", run_id="run-0002", observations_path=None,
                marked_path=None, repo_root=ROOT)
    assert inspected.value.code == "JOB_CONFLICT"


def test_status_block_needs_metron_on(tmp_path: Path) -> None:
    work = _with_block(tmp_path)
    config = work / "config.md"
    config.write_text(config.read_text(encoding="utf-8").replace("| METRON | ON |", "| METRON | OFF |")
                      .replace("| CHRONOS | ON |", "| CHRONOS | OFF |"), encoding="utf-8")
    code, message = prepare(
        work, scene_id="ch01-001", text_path="_novel_text/novel_text01.md",
        request_kind=RequestKind.STATUS_BLOCK, model_id="local-writer", selector=None,
        links_path=None, repo_root=ROOT, allow_publish=True,
    )
    assert "skipped" in message


# ── レビュー指摘：版の照合と、場面の候補の印 ─────────────────────────────


def _prepare_and_receive_block(work: Path, content: str, run_id: str) -> Path:
    prepare(
        work, scene_id="ch01-001", text_path="_novel_text/novel_text01.md",
        request_kind=RequestKind.STATUS_BLOCK, model_id="local-writer", selector=None,
        links_path=None, repo_root=ROOT, allow_publish=True,
    )
    candidate = work / f"status_candidate_{run_id}.md"
    candidate.write_text(content, encoding="utf-8")
    receive(work, scene_id="ch01-001", run_id=run_id, candidate=candidate, request_id=None)
    return work / "_work" / "writing" / "ch01-001" / run_id


def test_old_status_block_run_cannot_overwrite_newer_update(tmp_path: Path) -> None:
    work = _with_block(tmp_path)
    _publish_scene(work)
    _prepare_and_receive_block(work, "《記録》古い run の中身\n", "run-0002")
    code, _ = publish(work, scene_id="ch01-001", run_id="run-0002", authorization=AUTH, repo_root=ROOT,
                      dry_run=True)
    assert code == 0
    _prepare_and_receive_block(work, "《記録》新しい run の中身\n", "run-0003")
    assert publish(work, scene_id="ch01-001", run_id="run-0003", authorization=AUTH, repo_root=ROOT)[0] == 0
    with pytest.raises(BridgeError) as caught:
        publish(work, scene_id="ch01-001", run_id="run-0002", authorization=AUTH, repo_root=ROOT)
    assert caught.value.code == "STALE_EVIDENCE"
    text = (work / "_novel_text" / "novel_text01.md").read_text(encoding="utf-8")
    assert "新しい run の中身" in text and "古い run の中身" not in text


def test_status_block_refuses_candidate_edited_after_receive(tmp_path: Path) -> None:
    work = _with_block(tmp_path)
    _publish_scene(work)
    dest = _prepare_and_receive_block(work, "《記録》受け取った中身\n", "run-0002")
    (dest / "candidate.md").write_text("《記録》あとから書き換えた中身\n", encoding="utf-8")
    with pytest.raises(BridgeError) as caught:
        publish(work, scene_id="ch01-001", run_id="run-0002", authorization=AUTH, repo_root=ROOT)
    assert caught.value.code == "STALE_EVIDENCE"
    assert "書き換えた" not in (work / "_novel_text" / "novel_text01.md").read_text(encoding="utf-8")


def test_scene_candidate_with_block_markers_is_refused(tmp_path: Path) -> None:
    from writing_bridge.publish import _clean_scene_body

    work = _with_block(tmp_path)
    prepare(
        work, scene_id="ch01-001", text_path="_novel_text/novel_text01.md", request_kind=RequestKind.NEW,
        model_id="local-writer", selector=Selector(kind=SelectorKind.HEADING, value="第一章　駅までの道"),
        links_path=None, repo_root=ROOT, allow_publish=True,
    )
    marked = (work / "_metron" / "ch01-001" / "marked.md").read_text(encoding="utf-8")
    candidate = work / "with_block.md"
    candidate.write_text(marked.rstrip("\n") + "\n\n" + BLOCK, encoding="utf-8")
    with pytest.raises(BridgeError) as caught:
        receive(work, scene_id="ch01-001", run_id="run-0001", candidate=candidate, request_id=None)
    assert caught.value.code == "JOB_CONFLICT"
    # 保存の段でも拒む。本文内の通知の独立した行（status:line）は通す。
    with pytest.raises(BridgeError):
        _clean_scene_body("　本文。\n\n" + BLOCK)
    assert "<!-- status:line -->" in _clean_scene_body("　本文。\n\n<!-- status:line -->《声》技能を得た\n")
