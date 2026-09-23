from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from story_reflection_op import (  # noqa: E402
    EXIT_INCOMPLETE,
    EXIT_OK,
    NovelPaths,
    OpError,
    acquire_lock,
    atomic_write_text,
    finish_lock,
    hold_existing_lock,
    main,
    parse_journal,
    read_lock,
    unlink_owned_lock,
    resolve_target,
    sha256_file,
)


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def _novel(tmp_path: Path) -> Path:
    novel = tmp_path / "novels" / "001_sample"
    _write(novel / "design_specification.md", "## 第18章\n\n1. 旧確定\n\n## 予定\n\n1. 未執筆\n")
    _write(novel / "_meta.md", "# meta\n\n- 進捗: 旧\n")
    _write(novel / "_novel_text" / "novel_text18.md", "本文A\n")
    return novel


def _run(tmp_path: Path, *argv: str) -> tuple[int, dict]:
    code = main(["--repo-root", str(tmp_path), *argv])
    # main prints JSON; tests that need payload re-read files or call again.
    return code


def _run_json(tmp_path: Path, capsys, *argv: str) -> tuple[int, dict]:
    code = main(["--repo-root", str(tmp_path), *argv])
    payload = json.loads(capsys.readouterr().out)
    return code, payload


def _hashes(novel: Path, *, design: Path | None = None, meta: Path | None = None, text: Path | None = None) -> dict:
    design = design or novel / "design_specification.md"
    meta = meta or novel / "_meta.md"
    text = text or novel / "_novel_text" / "novel_text18.md"
    return {
        "target": "第18章",
        "input_design_sha256": sha256_file(novel / "design_specification.md"),
        "input_meta_sha256": sha256_file(novel / "_meta.md"),
        "input_text_sha256": {"_novel_text/novel_text18.md": sha256_file(text)},
        "intended_design_sha256": sha256_file(design),
        "intended_chapter_sha256": sha256_file(design),
        "intended_meta_sha256": sha256_file(meta),
    }


def _evidence(tmp_path: Path, novel: Path, data: dict) -> Path:
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def test_resolve_chapter_and_section_coexistence():
    design = "\n".join(
        [
            "## 第1章",
            "1. 章側",
            "## 第1章1項（本編・前半）",
            "1. 項側",
            "### 第18章「題」",
            "1. 確定",
        ]
    )
    chapter = resolve_target(design, "novel_text01.md")
    assert chapter["ok"] is True
    assert chapter["write_scope"] == "chapter_anchor"
    section = resolve_target(design, "novel_text01_1.md")
    assert section["ok"] is True
    assert section["write_scope"] == "section_anchor"
    assert section["label"] == "第1章1項"
    assert resolve_target(design, "novel_text18.md")["ok"] is True


def test_resolve_section_heading_is_not_two_chapters():
    design = "## 第1章1項（本編・前半）\n\n1. 公開事故\n\n## 第1章第2項\n\n1. 予定\n"
    first = resolve_target(design, "novel_text01_1.md")
    second = resolve_target(design, "novel_text01_2.md")
    assert first["ok"] and first["kind"] == "section"
    assert second["ok"] and second["label"] == "第1章2項"
    whole = resolve_target(design, "novel_text01.md")
    assert whole["ok"]
    assert whole["write_scope"] == "all_sections_aggregate"


def test_resolve_duplicate_chapter_stops():
    design = "## 第18章\n\n1. A\n\n## 第18章\n\n1. B\n"
    result = resolve_target(design, "novel_text18.md")
    assert result["ok"] is False
    assert result["code"] == "UNRESOLVED"


def test_begin_apply_and_second_operation_does_not_rewrite_terminal(tmp_path: Path, capsys):
    novel = _novel(tmp_path)
    new_design = _write(tmp_path / "new_design.md", "## 第18章\n\n1. 新確定\n\n## 予定\n\n1. 未執筆\n")
    new_meta = _write(tmp_path / "new_meta.md", "# meta\n\n- **出来事同期**: 2026-09-12 第18章 更新 op=sr-1\n")
    evidence = _hashes(novel, design=new_design, meta=new_meta)
    ev_path = _evidence(tmp_path, novel, evidence)

    code, payload = _run_json(tmp_path, capsys, "begin", str(novel), "--evidence", str(ev_path))
    assert code == EXIT_OK
    assert payload["current"]["status"] == "prepared"
    assert payload["current"]["transition_seq"] == 1

    code, payload = _run_json(tmp_path, capsys, "apply-design", str(novel), "--file", str(new_design))
    assert code == EXIT_OK
    assert payload["current"]["status"] == "verified"

    code, payload = _run_json(tmp_path, capsys, "apply-meta", str(novel), "--file", str(new_meta))
    assert code == EXIT_OK
    assert payload["current"]["status"] == "done"
    assert not (novel / "_story_reflection_op.lock").exists()
    assert "新確定" in (novel / "design_specification.md").read_text(encoding="utf-8")

    journal = parse_journal(novel / "_story_reflection_op.jsonl")
    statuses = [row["status"] for row in journal.rows if row.get("record_kind") == "transition"]
    assert statuses == ["prepared", "replaced", "verified", "done"]
    first_done_seq = journal.last_journal_seq

    other_design = _write(tmp_path / "design19.md", "## 第18章\n\n1. 新確定\n\n## 予定\n\n1. 未執筆\n")
    other_meta = _write(tmp_path / "meta19.md", "# meta\n\n- **出来事同期**: 2026-09-12 第18章 差分なし op=sr-2\n")
    _write(novel / "_novel_text" / "novel_text18.md", "本文A\n")
    evidence2 = _hashes(novel, design=other_design, meta=other_meta)
    ev2 = tmp_path / "e2.json"
    ev2.write_text(json.dumps(evidence2, ensure_ascii=False), encoding="utf-8")

    code, payload = _run_json(tmp_path, capsys, "begin", str(novel), "--evidence", str(ev2))
    assert code == EXIT_OK
    assert payload["current"]["transition_seq"] == 1
    assert payload["current"]["last_journal_seq"] == first_done_seq + 1

    rows = parse_journal(novel / "_story_reflection_op.jsonl").rows
    transition_rows = [row for row in rows if row.get("record_kind") == "transition"]
    done_rows = [row for row in transition_rows if row.get("status") == "done"]
    assert len(done_rows) == 1


def test_begin_refuses_active_operation(tmp_path: Path, capsys):
    novel = _novel(tmp_path)
    new_meta = _write(tmp_path / "new_meta.md", "# meta\n\n- next\n")
    evidence = _hashes(novel, meta=new_meta)
    ev_path = _evidence(tmp_path, novel, evidence)
    assert _run_json(tmp_path, capsys, "begin", str(novel), "--evidence", str(ev_path))[0] == EXIT_OK
    evidence2 = dict(evidence)
    evidence2["operation_id"] = "sr-other"
    ev2 = tmp_path / "e2.json"
    ev2.write_text(json.dumps(evidence2), encoding="utf-8")
    code, payload = _run_json(tmp_path, capsys, "begin", str(novel), "--evidence", str(ev2))
    assert code == EXIT_INCOMPLETE
    assert payload["code"] == "LOCK_HELD"


def test_stale_text_fails_without_writing_design(tmp_path: Path, capsys):
    novel = _novel(tmp_path)
    new_design = _write(tmp_path / "new_design.md", "## 第18章\n\n1. 新確定\n")
    new_meta = _write(tmp_path / "new_meta.md", "# meta\n\n- sync\n")
    evidence = _hashes(novel, design=new_design, meta=new_meta)
    ev_path = _evidence(tmp_path, novel, evidence)
    assert _run_json(tmp_path, capsys, "begin", str(novel), "--evidence", str(ev_path))[0] == EXIT_OK
    _write(novel / "_novel_text" / "novel_text18.md", "本文が変わった\n")
    old_design = (novel / "design_specification.md").read_text(encoding="utf-8")
    code, payload = _run_json(tmp_path, capsys, "apply-design", str(novel), "--file", str(new_design))
    assert code == EXIT_INCOMPLETE
    assert payload["current"]["status"] == "failed"
    assert (novel / "design_specification.md").read_text(encoding="utf-8") == old_design


def test_orphan_status_mismatch_is_not_resumed_as_prepared(tmp_path: Path, capsys):
    novel = _novel(tmp_path)
    new_design = _write(tmp_path / "new_design.md", "## 第18章\n\n1. 新確定\n")
    new_meta = _write(tmp_path / "new_meta.md", "# meta\n\n- sync\n")
    evidence = _hashes(novel, design=new_design, meta=new_meta)
    ev_path = _evidence(tmp_path, novel, evidence)
    assert _run_json(tmp_path, capsys, "begin", str(novel), "--evidence", str(ev_path))[0] == EXIT_OK
    assert _run_json(tmp_path, capsys, "apply-design", str(novel), "--file", str(new_design))[0] == EXIT_OK

    current = json.loads((novel / "_story_reflection_op.json").read_text(encoding="utf-8"))
    current["status"] = "prepared"
    current["transition_seq"] = 1
    (novel / "_story_reflection_op.json").write_text(json.dumps(current, ensure_ascii=False), encoding="utf-8")

    other_meta = _write(tmp_path / "other_meta.md", "# meta\n\n- other\n")
    evidence2 = _hashes(novel, design=novel / "design_specification.md", meta=other_meta)
    ev2 = tmp_path / "e2.json"
    ev2.write_text(json.dumps(evidence2), encoding="utf-8")
    # lock remains from first op; release is denied because orphan/active
    code, payload = _run_json(tmp_path, capsys, "begin", str(novel), "--evidence", str(ev2))
    assert code == EXIT_INCOMPLETE
    assert payload["code"] in {"LOCK_HELD", "ORPHAN", "JOB_CONFLICT"}
    inspect_code, inspect = _run_json(tmp_path, capsys, "inspect", str(novel))
    assert inspect_code == EXIT_INCOMPLETE
    assert inspect["verdict"] == "orphan"


def test_lock_release_requires_terminal_match(tmp_path: Path, capsys):
    novel = _novel(tmp_path)
    new_meta = _write(tmp_path / "new_meta.md", "# meta\n\n- sync\n")
    evidence = _hashes(novel, meta=new_meta)
    ev_path = _evidence(tmp_path, novel, evidence)
    assert _run_json(tmp_path, capsys, "begin", str(novel), "--evidence", str(ev_path))[0] == EXIT_OK
    code, payload = _run_json(tmp_path, capsys, "lock-release", str(novel))
    assert code == EXIT_INCOMPLETE
    assert payload["code"] == "LOCK_RELEASE_DENIED"
    assert payload["detail"]["verdict"] == "active"
    assert (novel / "_story_reflection_op.lock").exists()

    assert _run_json(tmp_path, capsys, "fail", str(novel), "--reason", "stop")[0] == EXIT_INCOMPLETE
    # fail は lock を消す。残存 lock を再現してから解除する。
    current = json.loads((novel / "_story_reflection_op.json").read_text(encoding="utf-8"))
    atomic_write_text(
        novel / "_story_reflection_op.lock",
        json.dumps({"operation_id": current["operation_id"], "pid": 1, "created_at": "t"}, ensure_ascii=False) + "\n",
    )
    code, payload = _run_json(tmp_path, capsys, "lock-release", str(novel))
    assert code == EXIT_OK
    assert not (novel / "_story_reflection_op.lock").exists()
    kinds = [row["record_kind"] for row in parse_journal(novel / "_story_reflection_op.jsonl").rows]
    assert "lock_event" in kinds
    last = parse_journal(novel / "_story_reflection_op.jsonl").last_transition
    assert last["status"] == "failed"


def test_second_lock_cannot_be_stolen(tmp_path: Path):
    novel = _novel(tmp_path)
    paths = NovelPaths(novel)
    first = acquire_lock(paths, "sr-one")
    with pytest.raises(Exception) as exc:
        acquire_lock(paths, "sr-two")
    assert exc.value.code == "LOCK_HELD"
    first.release_file()


def test_no_diff_meta_only_path(tmp_path: Path, capsys):
    novel = _novel(tmp_path)
    new_meta = _write(tmp_path / "new_meta.md", "# meta\n\n- **出来事同期**: 2026-09-12 第18章 差分なし op=sr-x\n")
    evidence = _hashes(novel, meta=new_meta)
    ev_path = _evidence(tmp_path, novel, evidence)
    old_design = (novel / "design_specification.md").read_text(encoding="utf-8")
    assert _run_json(tmp_path, capsys, "begin", str(novel), "--evidence", str(ev_path))[0] == EXIT_OK
    assert _run_json(tmp_path, capsys, "apply-design", str(novel), "--file", str(novel / "design_specification.md"))[0] == EXIT_OK
    code, payload = _run_json(tmp_path, capsys, "apply-meta", str(novel), "--file", str(new_meta))
    assert code == EXIT_OK
    assert payload["current"]["status"] == "done"
    assert (novel / "design_specification.md").read_text(encoding="utf-8") == old_design


def _subprocess_cli(tmp_path: Path, *argv: str, env: dict | None = None) -> tuple[int, dict]:
    merged = os.environ.copy()
    if env:
        merged.update(env)
    proc = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "story_reflection_op.py"), "--repo-root", str(tmp_path), *argv],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=merged,
    )
    payload = json.loads(proc.stdout) if proc.stdout and proc.stdout.strip() else {"stderr": proc.stderr}
    return proc.returncode, payload


def test_os_lock_blocks_parallel_apply_design(tmp_path: Path, capsys):
    novel = _novel(tmp_path)
    new_design = _write(tmp_path / "new_design.md", "## 第18章\n\n1. 新確定\n")
    new_meta = _write(tmp_path / "new_meta.md", "# meta\n\n- sync\n")
    evidence = _hashes(novel, design=new_design, meta=new_meta)
    ev_path = _evidence(tmp_path, novel, evidence)
    assert _run_json(tmp_path, capsys, "begin", str(novel), "--evidence", str(ev_path))[0] == EXIT_OK

    held = hold_existing_lock(NovelPaths(novel))
    try:
        code, payload = _subprocess_cli(tmp_path, "apply-design", str(novel), "--file", str(new_design))
    finally:
        held.close_fd()
    assert code == EXIT_INCOMPLETE
    assert payload["code"] == "LOCK_HELD"
    statuses = [
        row["status"]
        for row in parse_journal(novel / "_story_reflection_op.jsonl").rows
        if row.get("record_kind") == "transition"
    ]
    assert statuses == ["prepared"]

    code, payload = _run_json(tmp_path, capsys, "apply-design", str(novel), "--file", str(new_design))
    assert code == EXIT_OK
    assert payload["current"]["status"] == "verified"


def test_parallel_apply_design_does_not_duplicate_journal_seq(tmp_path: Path, capsys):
    novel = _novel(tmp_path)
    new_design = _write(tmp_path / "new_design.md", "## 第18章\n\n1. 新確定\n")
    new_meta = _write(tmp_path / "new_meta.md", "# meta\n\n- sync\n")
    evidence = _hashes(novel, design=new_design, meta=new_meta)
    ev_path = _evidence(tmp_path, novel, evidence)
    assert _run_json(tmp_path, capsys, "begin", str(novel), "--evidence", str(ev_path))[0] == EXIT_OK

    env = {"STORY_REFLECTION_HOLD_SLEEP": "0.3"}
    first = subprocess.Popen(
        [
            sys.executable,
            str(ROOT / "tools" / "story_reflection_op.py"),
            "--repo-root",
            str(tmp_path),
            "apply-design",
            str(novel),
            "--file",
            str(new_design),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        env={**os.environ, **env},
    )
    second = subprocess.Popen(
        [
            sys.executable,
            str(ROOT / "tools" / "story_reflection_op.py"),
            "--repo-root",
            str(tmp_path),
            "apply-design",
            str(novel),
            "--file",
            str(new_design),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        env={**os.environ, **env},
    )
    out1, _ = first.communicate()
    out2, _ = second.communicate()
    payloads = [json.loads(out) for out in (out1, out2) if out and out.strip()]
    codes = [first.returncode, second.returncode]
    assert EXIT_OK in codes
    assert EXIT_INCOMPLETE in codes
    held_codes = [payload.get("code") for payload in payloads]
    assert "LOCK_HELD" in held_codes
    journal_seqs = [
        row["journal_seq"]
        for row in parse_journal(novel / "_story_reflection_op.jsonl").rows
        if row.get("record_kind") == "transition"
    ]
    assert journal_seqs == sorted(journal_seqs)
    assert journal_seqs == list(range(1, len(journal_seqs) + 1))


def test_tampered_journal_last_journal_seq_is_orphan(tmp_path: Path, capsys):
    novel = _novel(tmp_path)
    new_meta = _write(tmp_path / "new_meta.md", "# meta\n\n- sync\n")
    evidence = _hashes(novel, meta=new_meta)
    ev_path = _evidence(tmp_path, novel, evidence)
    assert _run_json(tmp_path, capsys, "begin", str(novel), "--evidence", str(ev_path))[0] == EXIT_OK

    journal_path = novel / "_story_reflection_op.jsonl"
    row = json.loads(journal_path.read_text(encoding="utf-8").splitlines()[0])
    row["last_journal_seq"] = 99
    journal_path.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")

    inspect_code, inspect = _run_json(tmp_path, capsys, "inspect", str(novel))
    assert inspect_code == EXIT_INCOMPLETE
    assert inspect["verdict"] == "orphan"

    code, payload = _run_json(
        tmp_path, capsys, "apply-design", str(novel), "--file", str(novel / "design_specification.md")
    )
    assert code == EXIT_INCOMPLETE
    assert payload["code"] == "ORPHAN"
    parsed = [json.loads(line) for line in journal_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert [row.get("status") for row in parsed if row.get("record_kind") == "transition"] == ["prepared"]


def test_tampered_current_last_journal_seq_is_orphan(tmp_path: Path, capsys):
    novel = _novel(tmp_path)
    new_meta = _write(tmp_path / "new_meta.md", "# meta\n\n- sync\n")
    evidence = _hashes(novel, meta=new_meta)
    ev_path = _evidence(tmp_path, novel, evidence)
    assert _run_json(tmp_path, capsys, "begin", str(novel), "--evidence", str(ev_path))[0] == EXIT_OK
    current_path = novel / "_story_reflection_op.json"
    current = json.loads(current_path.read_text(encoding="utf-8"))
    current["last_journal_seq"] = 99
    current_path.write_text(json.dumps(current, ensure_ascii=False), encoding="utf-8")

    inspect_code, inspect = _run_json(tmp_path, capsys, "inspect", str(novel))
    assert inspect_code == EXIT_INCOMPLETE
    assert inspect["verdict"] == "orphan"


def test_close_orphan_refuses_terminal(tmp_path: Path, capsys):
    novel = _novel(tmp_path)
    new_meta = _write(tmp_path / "new_meta.md", "# meta\n\n- sync\n")
    evidence = _hashes(novel, meta=new_meta)
    ev_path = _evidence(tmp_path, novel, evidence)
    assert _run_json(tmp_path, capsys, "begin", str(novel), "--evidence", str(ev_path))[0] == EXIT_OK
    assert _run_json(tmp_path, capsys, "apply-design", str(novel), "--file", str(novel / "design_specification.md"))[0] == EXIT_OK
    assert _run_json(tmp_path, capsys, "apply-meta", str(novel), "--file", str(new_meta))[0] == EXIT_OK

    code, payload = _run_json(tmp_path, capsys, "close-orphan", str(novel), "--reason", "should-not")
    assert code == EXIT_INCOMPLETE
    assert payload["code"] == "ORPHAN"
    statuses = [
        row["status"]
        for row in parse_journal(novel / "_story_reflection_op.jsonl").rows
        if row.get("record_kind") == "transition"
    ]
    assert statuses[-1] == "done"
    assert statuses.count("failed") == 0
    assert json.loads((novel / "_story_reflection_op.json").read_text(encoding="utf-8"))["status"] == "done"


def test_close_orphan_allows_active_orphan(tmp_path: Path, capsys):
    novel = _novel(tmp_path)
    new_design = _write(tmp_path / "new_design.md", "## 第18章\n\n1. 新確定\n")
    new_meta = _write(tmp_path / "new_meta.md", "# meta\n\n- sync\n")
    evidence = _hashes(novel, design=new_design, meta=new_meta)
    ev_path = _evidence(tmp_path, novel, evidence)
    assert _run_json(tmp_path, capsys, "begin", str(novel), "--evidence", str(ev_path))[0] == EXIT_OK
    assert _run_json(tmp_path, capsys, "apply-design", str(novel), "--file", str(new_design))[0] == EXIT_OK

    current = json.loads((novel / "_story_reflection_op.json").read_text(encoding="utf-8"))
    current["status"] = "prepared"
    current["transition_seq"] = 1
    (novel / "_story_reflection_op.json").write_text(json.dumps(current, ensure_ascii=False), encoding="utf-8")

    _code, payload = _run_json(tmp_path, capsys, "close-orphan", str(novel), "--reason", "user-close")
    assert payload["current"]["status"] == "failed"
    last = parse_journal(novel / "_story_reflection_op.jsonl").last_transition
    assert last["status"] == "failed"
    assert last["transition_seq"] == 4


def test_finish_lock_does_not_unlink_after_fd_closed(tmp_path: Path):
    novel = _novel(tmp_path)
    paths = NovelPaths(novel)
    held = acquire_lock(paths, "sr-old")
    held.close_fd()
    held.delete_file = True
    paths.lock.write_text(
        json.dumps({"operation_id": "sr-new", "lock_token": "other", "pid": 2, "created_at": "t"}) + "\n",
        encoding="utf-8",
    )
    finish_lock(held)
    assert paths.lock.exists()
    assert read_lock(paths.lock)["operation_id"] == "sr-new"


def test_acquire_does_not_publish_unlocked_official_name(tmp_path: Path):
    novel = _novel(tmp_path)
    env = {**os.environ, "STORY_REFLECTION_ACQUIRE_SLEEP_BEFORE_PUBLISH": "0.6"}
    creator = subprocess.Popen(
        [
            sys.executable,
            "-c",
            (
                "import sys; from pathlib import Path; "
                "sys.path.insert(0, sys.argv[1]); "
                "from story_reflection_op import NovelPaths, acquire_lock; "
                "held = acquire_lock(NovelPaths(Path(sys.argv[2])), 'sr-slow'); "
                "held.close_fd()"
            ),
            str(ROOT / "tools"),
            str(novel),
        ],
        env=env,
    )
    time.sleep(0.2)
    assert not (novel / "_story_reflection_op.lock").exists()
    code, payload = _subprocess_cli(
        tmp_path, "apply-design", str(novel), "--file", str(novel / "design_specification.md")
    )
    assert code == EXIT_INCOMPLETE
    assert payload["code"] == "LOCK_HELD"
    assert creator.wait(timeout=5) == 0
    assert (novel / "_story_reflection_op.lock").exists()
    assert read_lock(novel / "_story_reflection_op.lock")["operation_id"] == "sr-slow"


def test_parse_journal_rejects_non_object_row(tmp_path: Path):
    path = tmp_path / "_story_reflection_op.jsonl"
    path.write_text("[1, 2]\n", encoding="utf-8")
    state = parse_journal(path)
    assert state.orphan
    assert "オブジェクトではない" in state.orphan_reason


def test_parse_journal_requires_lock_event_and_archive_fields(tmp_path: Path):
    path = tmp_path / "_story_reflection_op.jsonl"
    path.write_text(
        json.dumps({"record_kind": "lock_event", "journal_seq": 1, "operation_id": "sr-x"}) + "\n",
        encoding="utf-8",
    )
    state = parse_journal(path)
    assert state.orphan
    assert "event" in state.orphan_reason

    path.write_text(
        json.dumps({"record_kind": "archive", "journal_seq": 1, "status": "done"}) + "\n",
        encoding="utf-8",
    )
    state = parse_journal(path)
    assert state.orphan
    assert "operation_id" in state.orphan_reason


def test_resume_refuses_stale_hashes(tmp_path: Path, capsys):
    novel = _novel(tmp_path)
    new_meta = _write(tmp_path / "new_meta.md", "# meta\n\n- sync\n")
    evidence = _hashes(novel, meta=new_meta)
    ev_path = _evidence(tmp_path, novel, evidence)
    assert _run_json(tmp_path, capsys, "begin", str(novel), "--evidence", str(ev_path))[0] == EXIT_OK
    before = (novel / "_story_reflection_op.json").read_text(encoding="utf-8")
    _write(novel / "_novel_text" / "novel_text18.md", "本文が変わった\n")
    code, payload = _run_json(tmp_path, capsys, "resume", str(novel))
    assert code == EXIT_INCOMPLETE
    assert payload["code"] == "STALE_EVIDENCE"
    assert (novel / "_story_reflection_op.json").read_text(encoding="utf-8") == before


def test_unlink_keeps_exclusive_until_name_is_gone(tmp_path: Path):
    novel = _novel(tmp_path)
    ready = tmp_path / "unlink-ready.txt"
    env = {**os.environ, "STORY_REFLECTION_UNLINK_SLEEP_BEFORE_DELETE": "0.7"}
    deleter = subprocess.Popen(
        [
            sys.executable,
            "-c",
            (
                "import sys; from pathlib import Path; "
                "sys.path.insert(0, sys.argv[1]); "
                "from story_reflection_op import NovelPaths, acquire_lock, unlink_owned_lock; "
                "held = acquire_lock(NovelPaths(Path(sys.argv[2])), 'sr-old'); "
                "Path(sys.argv[3]).write_text('ready', encoding='utf-8'); "
                "unlink_owned_lock(held)"
            ),
            str(ROOT / "tools"),
            str(novel),
            str(ready),
        ],
        env=env,
    )
    deadline = time.time() + 5
    while time.time() < deadline and not ready.exists():
        time.sleep(0.05)
    assert ready.exists()
    lock = novel / "_story_reflection_op.lock"
    assert lock.exists()

    def _official_is_old() -> None:
        meta = read_lock(lock)
        assert meta is not None
        assert meta.get("operation_id") != "sr-new"
        if "operation_id" in meta:
            assert meta["operation_id"] == "sr-old"

    _official_is_old()
    with pytest.raises(OpError) as stolen:
        acquire_lock(NovelPaths(novel), "sr-new")
    assert stolen.value.code == "LOCK_HELD"
    with pytest.raises(OpError) as held:
        hold_existing_lock(NovelPaths(novel))
    assert held.value.code == "LOCK_HELD"
    _official_is_old()
    assert deleter.wait(timeout=5) == 0
    assert not lock.exists()


def test_windows_delete_failure_keeps_official_name(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    novel = _novel(tmp_path)
    paths = NovelPaths(novel)
    held = acquire_lock(paths, "sr-old")
    monkeypatch.setenv("STORY_REFLECTION_FAIL_WINDOWS_DELETE", "1")
    unlink_owned_lock(held)
    assert not held.released
    assert paths.lock.exists()
    assert read_lock(paths.lock)["operation_id"] == "sr-old"
    assert not list(paths.lock.parent.glob("._story_reflection_op.lock.dead.*"))
    with pytest.raises(OpError) as stolen:
        acquire_lock(paths, "sr-new")
    assert stolen.value.code == "LOCK_HELD"
    assert read_lock(paths.lock)["operation_id"] == "sr-old"


def test_finish_lock_raises_when_windows_delete_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    novel = _novel(tmp_path)
    paths = NovelPaths(novel)
    held = acquire_lock(paths, "sr-keep")
    held.delete_file = True
    monkeypatch.setenv("STORY_REFLECTION_FAIL_WINDOWS_DELETE", "1")
    with pytest.raises(OpError) as finish_exc:
        finish_lock(held)
    assert finish_exc.value.code == "LOCK_HELD"
    assert paths.lock.exists()
    assert read_lock(paths.lock)["operation_id"] == "sr-keep"
    assert not list(paths.lock.parent.glob("._story_reflection_op.lock.dead.*"))


def test_lock_release_failure_does_not_record_success_event(
    tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch
):
    novel = _novel(tmp_path)
    new_meta = _write(tmp_path / "new_meta.md", "# meta\n\n- sync\n")
    evidence = _hashes(novel, meta=new_meta)
    ev_path = _evidence(tmp_path, novel, evidence)
    assert _run_json(tmp_path, capsys, "begin", str(novel), "--evidence", str(ev_path))[0] == EXIT_OK
    assert _run_json(tmp_path, capsys, "fail", str(novel), "--reason", "stop")[0] == EXIT_INCOMPLETE

    current = json.loads((novel / "_story_reflection_op.json").read_text(encoding="utf-8"))
    atomic_write_text(
        novel / "_story_reflection_op.lock",
        json.dumps({"operation_id": current["operation_id"], "pid": 1, "created_at": "t"}, ensure_ascii=False)
        + "\n",
    )

    monkeypatch.setenv("STORY_REFLECTION_FAIL_WINDOWS_DELETE", "1")
    code, payload = _run_json(tmp_path, capsys, "lock-release", str(novel))
    assert code == EXIT_INCOMPLETE
    assert payload["code"] == "LOCK_HELD"
    assert (novel / "_story_reflection_op.lock").exists()
    rows = parse_journal(novel / "_story_reflection_op.jsonl").rows
    assert not any(row.get("event") == "lock_released" for row in rows)

    monkeypatch.delenv("STORY_REFLECTION_FAIL_WINDOWS_DELETE")
    code, payload = _run_json(tmp_path, capsys, "lock-release", str(novel))
    assert code == EXIT_OK
    assert not (novel / "_story_reflection_op.lock").exists()
    rows = parse_journal(novel / "_story_reflection_op.jsonl").rows
    assert sum(row.get("event") == "lock_released" for row in rows) == 1


def test_acquire_does_not_overwrite_existing_official(tmp_path: Path):
    novel = _novel(tmp_path)
    paths = NovelPaths(novel)
    held = acquire_lock(paths, "sr-old")
    held.close_fd()
    assert paths.lock.exists()
    with pytest.raises(OpError) as exc:
        acquire_lock(paths, "sr-new")
    assert exc.value.code == "LOCK_HELD"
    assert read_lock(paths.lock)["operation_id"] == "sr-old"


def test_resume_refuses_failed_terminal(tmp_path: Path, capsys):
    novel = _novel(tmp_path)
    new_meta = _write(tmp_path / "new_meta.md", "# meta\n\n- sync\n")
    evidence = _hashes(novel, meta=new_meta)
    ev_path = _evidence(tmp_path, novel, evidence)
    assert _run_json(tmp_path, capsys, "begin", str(novel), "--evidence", str(ev_path))[0] == EXIT_OK
    fail_code, fail_payload = _run_json(tmp_path, capsys, "fail", str(novel), "--reason", "stop")
    assert fail_payload["current"]["status"] == "failed"
    assert fail_code == EXIT_INCOMPLETE
    before = (novel / "_story_reflection_op.json").read_text(encoding="utf-8")
    journal_before = (novel / "_story_reflection_op.jsonl").read_text(encoding="utf-8")
    code, payload = _run_json(tmp_path, capsys, "resume", str(novel))
    assert code == EXIT_INCOMPLETE
    assert payload["code"] == "ORPHAN"
    assert "active" in payload["message"]
    assert (novel / "_story_reflection_op.json").read_text(encoding="utf-8") == before
    assert (novel / "_story_reflection_op.jsonl").read_text(encoding="utf-8") == journal_before
    assert not (novel / "_story_reflection_op.lock").exists()
