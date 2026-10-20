from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import goal_status as gs  # noqa: E402
from writing_bridge.hashes import text_sha256  # noqa: E402

TEXT = "本文です。\n" * 20


def _write_text(work: Path, chapter: int = 1, text: str = TEXT) -> Path:
    path = work / "_novel_text" / f"novel_text{chapter:02d}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _run(
    work: Path,
    scene: str,
    run: str,
    *,
    actions: list[str],
    text_path: Path | None = None,
    save: str = "success",
    repair: str | None = None,
) -> Path:
    d = work / "_writing" / scene / run
    d.mkdir(parents=True)
    (d / "journal.jsonl").write_text(
        "".join(json.dumps({"action": a}) + "\n" for a in actions), encoding="utf-8"
    )
    if text_path is not None:
        rel = text_path.relative_to(work).as_posix()
        digest = text_sha256(text_path.read_text(encoding="utf-8"))
        (d / "report.json").write_text(
            json.dumps({"text_save": save, "target_text_sha256": digest}), encoding="utf-8"
        )
        (d / "request.yaml").write_text(f"target:\n  text_path: {rel}\n", encoding="utf-8")
    if repair:
        (d / "repair_state.json").write_text(json.dumps({"status": repair}), encoding="utf-8")
    return d


def _meta(work: Path, task: str) -> None:
    (work / "_meta.md").write_text(
        "# I. 内部メタ情報\n\n## 1. 執筆フェーズ・ステータス\n"
        f"- **現在のフェーズ**: 執筆\n- **次回のタスク**: {task}\n\n"
        "## 2. 執筆用コンテキスト・アンカー\n- 手書き\n",
        encoding="utf-8",
    )


def test_published_and_current_scene_is_done(tmp_path: Path) -> None:
    text = _write_text(tmp_path)
    _run(tmp_path, "ch01-001", "run-0001", actions=["prepare", "publish"], text_path=text)

    scene = gs.judge_scene(tmp_path, "ch01-001", 1)

    assert scene.state == gs.DONE


def test_edit_after_publish_is_in_progress_not_done(tmp_path: Path) -> None:
    text = _write_text(tmp_path)
    _run(tmp_path, "ch01-001", "run-0001", actions=["publish"], text_path=text)
    text.write_text(TEXT + "加筆\n", encoding="utf-8")

    scene = gs.judge_scene(tmp_path, "ch01-001", 1)

    assert scene.state == gs.IN_PROGRESS
    assert "変わった" in scene.detail


def test_later_unpublished_run_keeps_scene_in_progress(tmp_path: Path) -> None:
    text = _write_text(tmp_path)
    _run(tmp_path, "ch01-001", "run-0001", actions=["publish"], text_path=text)
    _run(tmp_path, "ch01-001", "run-0002", actions=["prepare", "receive"])

    scene = gs.judge_scene(tmp_path, "ch01-001", 1)

    assert scene.state == gs.IN_PROGRESS
    assert "run-0002" in scene.detail


def test_escalated_repair_is_held(tmp_path: Path) -> None:
    _write_text(tmp_path)
    _run(tmp_path, "ch01-001", "run-0001", actions=["repair_begin"], repair="escalated")

    assert gs.judge_scene(tmp_path, "ch01-001", 1).state == gs.HELD


def test_active_repair_and_missing_run(tmp_path: Path) -> None:
    _write_text(tmp_path)
    _run(tmp_path, "ch01-001", "run-0001", actions=["repair_begin"], repair="active")

    assert gs.judge_scene(tmp_path, "ch01-001", 1).state == gs.IN_PROGRESS
    assert gs.judge_scene(tmp_path, "ch01-002", 1).state == gs.NOT_STARTED


def test_chapter_fold_priorities() -> None:
    def s(state: str) -> gs.SceneStatus:
        return gs.SceneStatus("ch01-001", 1, state)

    assert gs.fold_chapter(1, [s(gs.DONE), s(gs.DONE)], True).state == gs.DONE
    assert gs.fold_chapter(1, [s(gs.DONE), s(gs.NOT_STARTED)], True).state == gs.IN_PROGRESS
    assert gs.fold_chapter(1, [s(gs.DONE), s(gs.HELD), s(gs.IN_PROGRESS)], True).state == gs.HELD
    assert gs.fold_chapter(1, [s(gs.NOT_STARTED)], False).state == gs.NOT_STARTED
    assert gs.fold_chapter(1, [], True).state == gs.UNDETERMINED


def test_text_without_scene_records_is_undetermined_never_done(tmp_path: Path) -> None:
    _write_text(tmp_path)

    chapters, _ = gs.collect_chapters(tmp_path)

    assert [c.state for c in chapters] == [gs.UNDETERMINED]


def test_metron_from_excludes_early_chapters(tmp_path: Path) -> None:
    _write_text(tmp_path, 1)
    _write_text(tmp_path, 2)
    (tmp_path / "config.md").write_text(
        "## 基本情報\n\n| 項目 | 値 |\n|---|---|\n| METRON_FROM | 2 |\n", encoding="utf-8"
    )

    chapters, excluded = gs.collect_chapters(tmp_path)

    assert excluded == [1]
    assert [c.chapter for c in chapters] == [2]


def test_reconcile_flags_done_chapter_and_missing_reference() -> None:
    done = gs.ChapterStatus(1, gs.DONE)
    todo = gs.ChapterStatus(2, gs.IN_PROGRESS)

    stale = gs.reconcile_with_meta("- **次回のタスク**: 第1章を清書する\n", [done, todo])
    vague = gs.reconcile_with_meta("- **次回のタスク**: 続きを書く\n", [done, todo])
    ok = gs.reconcile_with_meta("- **次回のタスク**: 第2章を書く\n", [done, todo])
    blank = gs.reconcile_with_meta("- **次回のタスク**: (次にAIが何をすべきか)\n", [done])

    assert any("第1章は「できている」" in n for n in stale)
    assert any("第2章" in n for n in vague)
    assert ok == []
    assert blank == ["「次回のタスク」が未記入です"]
    assert gs.reconcile_with_meta("", [done]) == ["_meta.md がありません"]


def test_evaluate_char_window_and_chapter_state(tmp_path: Path) -> None:
    text = _write_text(tmp_path)
    _run(tmp_path, "ch01-001", "run-0001", actions=["publish"], text_path=text)
    _meta(tmp_path, "第2章を書く")
    chars = gs._chapter_chars([text])

    hit = gs.evaluate(tmp_path, chapter=1, chars=chars, project_check=False)
    miss = gs.evaluate(tmp_path, chapter=1, chars=chars * 2, project_check=False)

    assert hit.ok and all(c.status == gs.MET for c in hit.checks)
    assert not miss.ok
    assert any(c.name == "第1章の字数" and c.status == gs.UNMET for c in miss.checks)


def test_evaluate_undetermined_does_not_fail_but_is_not_met(tmp_path: Path) -> None:
    _write_text(tmp_path)

    status = gs.evaluate(tmp_path, chapter=1, project_check=False)

    assert status.ok
    assert [c.status for c in status.checks] == ["undetermined"]


def test_meta_block_inserted_before_section_two_and_replaced_in_place(tmp_path: Path) -> None:
    text = _write_text(tmp_path)
    _run(tmp_path, "ch01-001", "run-0001", actions=["publish"], text_path=text)
    _meta(tmp_path, "第2章を書く")
    today = date(2026, 10, 20)

    status = gs.evaluate(tmp_path, project_check=False)
    assert gs.write_meta(tmp_path, status, today)
    first = (tmp_path / "_meta.md").read_text(encoding="utf-8")

    assert first.index(gs.BLOCK_BEGIN) < first.index("## 2. 執筆用コンテキスト")
    assert "| 第1章 | できている | 1/1場面が保存済み |" in first
    assert "- 手書き" in first

    # 手書き部分を足しても、再実行は枠の中だけを置き換える。
    edited = first.replace("- 手書き", "- 手書き\n- 追記メモ")
    (tmp_path / "_meta.md").write_text(edited, encoding="utf-8")
    assert gs.write_meta(tmp_path, status, date(2026, 10, 21))
    second = (tmp_path / "_meta.md").read_text(encoding="utf-8")

    assert second.count(gs.BLOCK_BEGIN) == 1
    assert "追記メモ" in second
    assert "更新: 2026-10-21" in second


def test_write_meta_without_meta_file_returns_false(tmp_path: Path) -> None:
    status = gs.GoalStatus([], [], [])

    assert gs.write_meta(tmp_path, status) is False


def test_apply_meta_block_appends_when_no_section_two() -> None:
    out = gs.apply_meta_block("# 題\n", f"{gs.BLOCK_BEGIN}\nx\n{gs.BLOCK_END}")

    assert out.endswith(f"{gs.BLOCK_END}\n")
    assert out.startswith("# 題\n")


def test_cli_exit_codes_and_json(tmp_path: Path, capsys) -> None:
    text = _write_text(tmp_path)
    _run(tmp_path, "ch01-001", "run-0001", actions=["publish"], text_path=text)
    _meta(tmp_path, "第2章を書く")

    code = gs.main([str(tmp_path), "--chapter", "1", "--no-project-check", "--json"])
    data = json.loads(capsys.readouterr().out)

    assert code == 0 and data["ok"] is True
    assert data["chapters"][0]["state"] == gs.DONE
    assert gs.main([str(tmp_path / "none")]) == 2
    assert gs.main([str(tmp_path), "--chapter", "9", "--no-project-check"]) == 1
