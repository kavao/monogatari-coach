"""作品フォルダの移行ツール（_workingspace/plans/20261024_work-folder-layout.md M6）。"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import novel_work_migrate as nwm  # noqa: E402
from work_paths import legacy_location, migration_marker, new_location, resolve_unit  # noqa: E402

FIXTURE = ROOT / "tools" / "fixtures" / "writing_bridge" / "ok_ch01_001" / "work"
SCENE = "ch01-001"


@pytest.fixture(autouse=True)
def _no_stop():
    nwm.STOP_AFTER = None
    yield
    nwm.STOP_AFTER = None


def _work(tmp_path: Path) -> Path:
    work = tmp_path / "000_neutral_trip"
    shutil.copytree(FIXTURE, work)  # 古い構成（_writing/・_metron/）のまま
    return work


def _snapshot(base: Path) -> dict[str, str]:
    # 場面ロックと移行の共通ロックのファイルは、排他を取ると作られ、解放後も残る設計なので比べない。
    return {
        path.relative_to(base).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(base.rglob("*"))
        if path.is_file() and path.name not in {".operation.lock", ".migrate.lock"}
    }


def _no_leftovers(work: Path) -> None:
    # 移行と復旧の共通ロック（.migrate.lock）は解放後も残す設計なので数えない
    migrating = work / "_work" / ".migrating"
    assert not migrating.exists() or not any(
        path.is_file() and path.name != ".migrate.lock" for path in migrating.rglob("*")
    )


def _story_reflection_work(tmp_path: Path, capsys) -> Path:
    """ストーリー反映の操作を1つ終えた、古い構成（作品直下）の作品。"""
    from test_story_reflection_op import _complete_operation, _novel

    novel = _novel(tmp_path)
    _complete_operation(tmp_path, capsys, novel, "sr-1")
    new_dir = novel / "_work" / "story_reflection"
    (new_dir / "op.json").rename(novel / "_story_reflection_op.json")
    (new_dir / "op.jsonl").rename(novel / "_story_reflection_op.jsonl")
    shutil.rmtree(novel / "_work")
    assert resolve_unit(novel, "story_reflection").layout == "legacy"
    return novel


def _story_snapshot(novel: Path) -> dict[str, str]:
    location = resolve_unit(novel, "story_reflection")
    return {
        role: hashlib.sha256(location.file(role).read_bytes()).hexdigest()
        for role in ("current", "journal")
        if location.file(role).is_file()
    }


# --- 計画と移行 ---


def test_dry_run_lists_units_and_writes_nothing(tmp_path: Path, capsys) -> None:
    work = _work(tmp_path)
    before = _snapshot(work)
    assert nwm.main([str(work), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert f"migrate\twriting/{SCENE}" in out
    assert f"migrate\tmetron/{SCENE}" in out
    assert _snapshot(work) == before
    assert not (work / "_work").exists()


def test_migrate_moves_scene_units_and_tools_keep_working(tmp_path: Path, capsys) -> None:
    work = _work(tmp_path)
    writing_before = _snapshot(legacy_location(work, "writing", SCENE))
    metron_before = _snapshot(legacy_location(work, "metron", SCENE))
    assert nwm.main([str(work)]) == 0
    assert not legacy_location(work, "writing", SCENE).exists()
    assert not legacy_location(work, "metron", SCENE).exists()
    assert _snapshot(new_location(work, "writing", SCENE)) == writing_before
    assert _snapshot(new_location(work, "metron", SCENE)) == metron_before
    assert resolve_unit(work, "writing", SCENE).layout == "new"
    _no_leftovers(work)
    # 空になった古い親フォルダは消える（ファイルが残っていれば消さない）
    assert not (work / "_writing").exists()
    assert not (work / "_metron").exists()
    # 移したあとも、保存済みの _writing/... _metron/... の参照は組の解決で読める
    from work_paths import resolve_reference

    assert resolve_reference(work, f"_metron/{SCENE}/contract.yaml").is_file()
    assert resolve_reference(work, f"_writing/{SCENE}/run-0001/observations.json").is_file()
    # 2回目は何も移さない
    capsys.readouterr()
    assert nwm.main([str(work), "--dry-run"]) == 0
    assert "移すものはありません" in capsys.readouterr().out


def test_migrate_story_reflection_set(tmp_path: Path, capsys) -> None:
    from story_reflection_op import NovelPaths, cmd_inspect

    novel = _story_reflection_work(tmp_path, capsys)
    before = _story_snapshot(novel)
    assert nwm.main([str(novel), "--kind", "story_reflection"]) == 0
    assert not list(novel.glob("_story_reflection_op.*"))
    assert resolve_unit(novel, "story_reflection").layout == "new"
    assert _story_snapshot(novel) == before
    assert cmd_inspect(NovelPaths(novel))["verdict"] == "terminal_match"
    _no_leftovers(novel)


def test_busy_scene_is_not_moved(tmp_path: Path, capsys) -> None:
    work = _work(tmp_path)
    run = legacy_location(work, "writing", SCENE) / "run-0001"
    (run / "repair_state.json").write_text(json.dumps({"status": "active", "session": {}}), encoding="utf-8")
    before = _snapshot(work)
    assert nwm.main([str(work), "--kind", "writing"]) == 1
    assert "BUSY" in capsys.readouterr().out
    assert _snapshot(work) == before
    assert not migration_marker(work, "writing", SCENE).exists()


def test_rename_failure_on_first_move_changes_nothing(tmp_path: Path, monkeypatch) -> None:
    work = _work(tmp_path)
    before = _snapshot(legacy_location(work, "writing", SCENE))
    real_rename = nwm.os.rename

    def refuse_legacy(source, target):
        if Path(source) == legacy_location(work, "writing", SCENE):
            raise PermissionError("in use")
        return real_rename(source, target)

    monkeypatch.setattr(nwm.os, "rename", refuse_legacy)
    with pytest.raises(nwm.MigrationError) as error:
        nwm.migrate_unit(work, nwm.Unit("writing", SCENE))
    assert error.value.code == "IN_USE"
    assert _snapshot(legacy_location(work, "writing", SCENE)) == before
    assert resolve_unit(work, "writing", SCENE).layout == "legacy"
    _no_leftovers(work)


def test_loose_staging_folders_are_moved(tmp_path: Path, capsys) -> None:
    work = _work(tmp_path)
    (work / "_story_work").mkdir()
    (work / "_story_work" / "evidence.json").write_text("{}", encoding="utf-8")
    (work / "_reader" / "_sr_staging").mkdir(parents=True)
    (work / "_reader" / "_sr_staging" / "evidence_ch1.json").write_text("{}", encoding="utf-8")
    assert nwm.main([str(work), "--kind", "story_reflection"]) == 0
    staging = work / "_work" / "story_reflection" / "staging"
    assert (staging / "legacy_story_work" / "evidence.json").is_file()
    assert (staging / "legacy_sr_staging" / "evidence_ch1.json").is_file()
    assert not (work / "_story_work").exists()
    # 材料のフォルダはストーリー反映の組として数えない
    assert resolve_unit(work, "story_reflection").layout == "absent"


# --- 中断と復旧 ---

DIR_STEPS = ["listed", "copying", "copying:file", "verified", "switching", "aside", "placed", "switched", "cleaned"]


@pytest.mark.parametrize("step", DIR_STEPS)
def test_interrupted_scene_migration_recovers_to_one_place(tmp_path: Path, step: str) -> None:
    work = _work(tmp_path)
    before = _snapshot(legacy_location(work, "writing", SCENE))
    nwm.STOP_AFTER = lambda reached: reached == step
    with pytest.raises(nwm._Interrupt):
        nwm.migrate_unit(work, nwm.Unit("writing", SCENE))
    nwm.STOP_AFTER = None
    # 移行の記録がある間は、どのツールもこの組を使わない（cleaned のあとは記録の削除だけが残る）
    from work_paths import WorkPathError

    with pytest.raises(WorkPathError) as refused:
        resolve_unit(work, "writing", SCENE)
    assert refused.value.code == "MIGRATING"

    results = nwm.recover(work)
    assert len(results) == 1
    layout = resolve_unit(work, "writing", SCENE).layout
    assert layout in {"legacy", "new"}
    base = legacy_location(work, "writing", SCENE) if layout == "legacy" else new_location(work, "writing", SCENE)
    other = new_location(work, "writing", SCENE) if layout == "legacy" else legacy_location(work, "writing", SCENE)
    assert _snapshot(base) == before
    assert not other.exists()
    _no_leftovers(work)
    # 段階ごとの戻り先: 古い組を退ける前なら古い置き場、退けたあとは新しい置き場で完了
    expected = "legacy" if DIR_STEPS.index(step) <= DIR_STEPS.index("switching") else "new"
    assert layout == expected


STORY_STEPS = ["listed", "copying", "verified", "switching", "aside:first", "aside", "placing:file", "placed", "switched"]


@pytest.mark.parametrize("step", STORY_STEPS)
def test_interrupted_story_reflection_migration_recovers(tmp_path: Path, capsys, step: str) -> None:
    from story_reflection_op import NovelPaths, cmd_inspect

    novel = _story_reflection_work(tmp_path, capsys)
    before = _story_snapshot(novel)
    nwm.STOP_AFTER = lambda reached: reached == step
    with pytest.raises(nwm._Interrupt):
        nwm.migrate_unit(novel, nwm.Unit("story_reflection", "op"))
    nwm.STOP_AFTER = None
    nwm.recover(novel)
    location = resolve_unit(novel, "story_reflection")
    assert location.layout in {"legacy", "new"}
    assert _story_snapshot(novel) == before
    if location.layout == "new":
        assert not list(novel.glob("_story_reflection_op.*"))
    else:
        assert not (novel / "_work" / "story_reflection" / "op.jsonl").exists()
    assert cmd_inspect(NovelPaths(novel))["verdict"] == "terminal_match"
    _no_leftovers(novel)


def test_migrate_refuses_while_interrupted_migration_remains(tmp_path: Path, capsys) -> None:
    work = _work(tmp_path)
    nwm.STOP_AFTER = lambda reached: reached == "verified"
    with pytest.raises(nwm._Interrupt):
        nwm.migrate_unit(work, nwm.Unit("writing", SCENE))
    nwm.STOP_AFTER = None
    assert nwm.main([str(work)]) == 1
    assert "--recover" in capsys.readouterr().out
    assert nwm.main([str(work), "--recover"]) == 0
    assert nwm.main([str(work)]) == 0
    assert resolve_unit(work, "writing", SCENE).layout == "new"


def test_project_check_reports_layout(tmp_path: Path) -> None:
    from novel_project_check import check_novel_project

    def check(work: Path, **kwargs):
        return check_novel_project(
            work, min_file_bytes=0, require_tag_md=False, require_manga_dir=False, **kwargs
        )

    work = _work(tmp_path)
    result = check(work, check_layout=True)
    layout = result["optional"]["layout"]
    assert {item["path"] for item in layout["legacy_markers"]} >= {"_writing", "_metron"}
    assert any(line.startswith("古い構成の印") for line in result["warnings"])
    assert nwm.main([str(work)]) == 0
    result = check(work, check_layout=True)
    assert result["optional"]["layout"]["legacy_markers"] == []


def test_non_scene_writing_folder_moves_without_scene_lock(tmp_path: Path) -> None:
    work = _work(tmp_path)
    proof = work / "_writing" / "run-reflection-proof" / "note.md"
    proof.parent.mkdir(parents=True)
    proof.write_text("x", encoding="utf-8")
    assert nwm.main([str(work), "--kind", "writing"]) == 0
    assert (work / "_work" / "writing" / "run-reflection-proof" / "note.md").is_file()


def test_empty_legacy_root_kept_when_files_remain(tmp_path: Path) -> None:
    work = _work(tmp_path)
    keep = work / "_metron" / "notes.txt"  # 組（場面フォルダ）の外のファイル
    keep.write_text("x", encoding="utf-8")
    assert nwm.main([str(work)]) == 0
    assert keep.is_file()
    assert (work / "_metron").is_dir()



# --- レビュー指摘（M6）---


def test_recover_is_refused_while_migration_runs(tmp_path: Path) -> None:
    work = _work(tmp_path)
    before = _snapshot(legacy_location(work, "writing", SCENE))
    refused: list[str] = []

    def try_recover(step: str) -> bool:
        if step == "copying":
            try:
                nwm.recover(work)
            except nwm.MigrationError as error:
                refused.append(error.code)
        return False  # 止めずに移行を続ける

    nwm.STOP_AFTER = try_recover
    nwm.migrate_unit(work, nwm.Unit("writing", SCENE))
    nwm.STOP_AFTER = None
    assert refused == ["MIGRATION_RUNNING"]
    assert _snapshot(new_location(work, "writing", SCENE)) == before
    assert not legacy_location(work, "writing", SCENE).exists()
    _no_leftovers(work)


def test_migration_is_refused_while_another_runs(tmp_path: Path) -> None:
    work = _work(tmp_path)
    with nwm.migration_lock(work):
        with pytest.raises(nwm.MigrationError) as error:
            nwm.migrate_unit(work, nwm.Unit("writing", SCENE))
    assert error.value.code == "MIGRATION_RUNNING"
    assert resolve_unit(work, "writing", SCENE).layout == "legacy"


def test_story_lock_release_failure_stops_before_switching(tmp_path: Path, capsys, monkeypatch) -> None:
    novel = _story_reflection_work(tmp_path, capsys)
    before = _story_snapshot(novel)
    monkeypatch.setenv("STORY_REFLECTION_FAIL_WINDOWS_DELETE", "1")
    with pytest.raises(nwm.MigrationError) as error:
        nwm.migrate_unit(novel, nwm.Unit("story_reflection", "op"))
    assert error.value.code == "LOCK_RELEASE"
    monkeypatch.delenv("STORY_REFLECTION_FAIL_WINDOWS_DELETE")
    # 移行の記録は取り消され、組は古い置き場のまま（新しい置き場に何も作らず、競合にならない）
    assert not migration_marker(novel, "story_reflection").exists()
    assert resolve_unit(novel, "story_reflection").layout == "legacy"
    assert not (novel / "_work" / "story_reflection" / "op.jsonl").exists()
    assert _story_snapshot(novel) == before


def _bad_record(work: Path, mutate) -> Path:
    nwm.STOP_AFTER = lambda step: step == "verified"
    with pytest.raises(nwm._Interrupt):
        nwm.migrate_unit(work, nwm.Unit("writing", SCENE))
    nwm.STOP_AFTER = None
    marker = migration_marker(work, "writing", SCENE)
    record = json.loads(marker.read_text(encoding="utf-8"))
    mutate(record)
    marker.write_text(json.dumps(record), encoding="utf-8")
    return marker


@pytest.mark.parametrize(
    "case",
    ["absolute_new", "outside_new", "parent_ref", "other_unit", "kind_mismatch", "bad_hash", "empty_files", "bad_state"],
)
def test_recover_validates_record_before_changing_anything(tmp_path: Path, case: str) -> None:
    work = _work(tmp_path)
    outside = tmp_path / "outside.txt"
    outside.write_text("keep", encoding="utf-8")

    def mutate(record: dict) -> None:
        first = record["files"][0]
        if case == "absolute_new":
            first["new"] = outside.as_posix()
        elif case == "outside_new":
            first["new"] = "config.md"
        elif case == "parent_ref":
            first["new"] = "_work/writing/ch01-001/../../../outside.txt"
        elif case == "other_unit":
            first["new"] = "_work/writing/ch09-001/" + first["new"].split("/", 3)[3]
        elif case == "kind_mismatch":
            record["kind"] = "metron"
        elif case == "bad_hash":
            first["sha256"] = "sha256:xyz"
        elif case == "empty_files":
            record["files"] = []
        elif case == "bad_state":
            record["state"] = "done"

    marker = _bad_record(work, mutate)
    snapshot_before = _snapshot(work)
    with pytest.raises(nwm.MigrationError) as error:
        nwm.recover(work)
    assert error.value.code == "BAD_RECORD"
    assert outside.read_text(encoding="utf-8") == "keep"
    assert (work / "config.md").is_file()
    assert _snapshot(work) == snapshot_before
    assert marker.is_file()



def test_recover_from_record_written_before_hashing(tmp_path: Path) -> None:
    # レビュー指摘（M6 再レビュー）: ハッシュを取る前に止まった最初の記録（copying・sha256 なし）からも戻せる。
    work = _work(tmp_path)
    before = _snapshot(legacy_location(work, "writing", SCENE))
    nwm.STOP_AFTER = lambda step: step == "listed"
    with pytest.raises(nwm._Interrupt):
        nwm.migrate_unit(work, nwm.Unit("writing", SCENE))
    nwm.STOP_AFTER = None
    record = json.loads(migration_marker(work, "writing", SCENE).read_text(encoding="utf-8"))
    assert record["state"] == "copying"
    assert all(item["sha256"] is None for item in record["files"])
    assert nwm.main([str(work), "--recover"]) == 0
    assert resolve_unit(work, "writing", SCENE).layout == "legacy"
    assert _snapshot(legacy_location(work, "writing", SCENE)) == before
    _no_leftovers(work)


def test_hashless_record_is_rejected_after_copying(tmp_path: Path) -> None:
    # verified 以降はハッシュが必須（未確定のままの記録は検証で止め、何も変えない）。
    work = _work(tmp_path)

    def drop_hash(record: dict) -> None:
        record["files"][0]["sha256"] = None

    marker = _bad_record(work, drop_hash)
    with pytest.raises(nwm.MigrationError) as error:
        nwm.recover(work)
    assert error.value.code == "BAD_RECORD"
    assert marker.is_file()


# --- M8: 移行の勧め（計画 §3.4・§3.5） ---


def _meta(work: Path, text: str) -> None:
    (work / "_meta.md").write_text(text, encoding="utf-8")


def test_advise_edit_proposes_once_then_respects_decline(tmp_path: Path) -> None:
    work = _work(tmp_path)  # 古い構成（_writing/・_metron/）
    advice = nwm.advise(work, "edit")
    assert advice["propose_migration"] is True
    assert {item["path"] for item in advice["legacy_markers"]} >= {"_writing", "_metron"}
    nwm.decline(work)
    advice = nwm.advise(work, "edit")
    assert advice["declined"] is True
    assert advice["propose_migration"] is False


@pytest.mark.parametrize("request_kind", ["evaluate", "read"])
def test_advise_does_not_propose_for_evaluation_or_reading(tmp_path: Path, request_kind: str) -> None:
    work = _work(tmp_path)
    assert nwm.advise(work, request_kind)["propose_migration"] is False


def test_advise_does_not_propose_while_operation_active(tmp_path: Path) -> None:
    work = _work(tmp_path)
    run = legacy_location(work, "writing", SCENE) / "run-0001"
    (run / "repair_state.json").write_text(json.dumps({"status": "active", "session": {}}), encoding="utf-8")
    advice = nwm.advise(work, "edit")
    assert advice["propose_migration"] is False
    assert advice["active_operation"]


def test_advise_new_layout_with_new_meta_proposes_nothing(tmp_path: Path) -> None:
    work = _work(tmp_path)
    assert nwm.main([str(work)]) == 0
    template = (ROOT / "_how_to.example" / "meta.md").read_text(encoding="utf-8")
    _meta(work, template)
    advice = nwm.advise(work, "edit")
    assert advice["legacy_markers"] == []
    assert advice["meta_form"] == "new"
    assert advice["propose_migration"] is False
    assert advice["ensure_sections"] == []


def test_advise_lists_sections_to_ensure_by_request(tmp_path: Path) -> None:
    work = _work(tmp_path)
    _meta(work, "## 2. 執筆用コンテキスト・アンカー\n- x\n")
    assert nwm.advise(work, "evaluate")["ensure_sections"] == ["evaluation-history"]
    assert nwm.advise(work, "edit")["ensure_sections"] == ["phase-status"]
    assert nwm.advise(work, "read")["ensure_sections"] == []


def test_advise_requires_recover_when_interrupted(tmp_path: Path) -> None:
    work = _work(tmp_path)
    nwm.STOP_AFTER = lambda step: step == "verified"
    with pytest.raises(nwm._Interrupt):
        nwm.migrate_unit(work, nwm.Unit("writing", SCENE))
    nwm.STOP_AFTER = None
    advice = nwm.advise(work, "edit")
    assert advice["interrupted_migrations"]
    assert advice["propose_migration"] is False
    assert "--recover" in advice["message"]


# --- M9: 付属原稿（book_matter/ → _novel_text/matter/） ---


def _with_book_matter(work: Path) -> None:
    (work / "book_matter" / "frontmatter").mkdir(parents=True)
    (work / "book_matter" / "frontmatter" / "characters.md").write_text("# 登場人物\n", encoding="utf-8")
    (work / "book.yaml").write_text(
        "manuscript:\n  frontmatter:\n    - id: characters\n      file: book_matter/frontmatter/characters.md\n"
        "  chapters:\n    - id: ch01\n      file: _novel_text/novel_text01.md\n",
        encoding="utf-8",
    )


def test_book_matter_moves_and_book_yaml_is_rewritten(tmp_path: Path, capsys) -> None:
    work = _work(tmp_path)
    _with_book_matter(work)
    assert nwm.main([str(work), "--kind", "matter", "--dry-run"]) == 0
    assert "book_matter\t1 files" in capsys.readouterr().out
    assert (work / "book_matter").is_dir()
    assert nwm.main([str(work), "--kind", "matter"]) == 0
    assert not (work / "book_matter").exists()
    assert (work / "_novel_text" / "matter" / "frontmatter" / "characters.md").is_file()
    book = (work / "book.yaml").read_text(encoding="utf-8")
    assert "file: _novel_text/matter/frontmatter/characters.md" in book
    assert "file: _novel_text/novel_text01.md" in book  # 章のパスは変えない


def test_book_matter_write_failure_is_recovered(tmp_path: Path, monkeypatch) -> None:
    # book.yaml を書けずに止まっても、移行の記録から --recover で移したあとの形に完了させる。
    work = _work(tmp_path)
    _with_book_matter(work)
    real_replace = nwm.os.replace

    def refuse_book(source, target):
        if Path(target).name == "book.yaml":
            raise PermissionError("locked")
        return real_replace(source, target)

    monkeypatch.setattr(nwm.os, "replace", refuse_book)
    with pytest.raises(nwm.MigrationError) as error:
        nwm.migrate_book_matter(work)
    assert error.value.code == "INTERRUPTED"
    monkeypatch.setattr(nwm.os, "replace", real_replace)
    assert nwm.main([str(work)]) == 1  # 中断した移行があるので、先に --recover を求める
    assert nwm.main([str(work), "--recover"]) == 0
    assert (work / "_novel_text" / "matter" / "frontmatter" / "characters.md").is_file()
    assert "file: _novel_text/matter/frontmatter/characters.md" in (work / "book.yaml").read_text(encoding="utf-8")
    assert not (work / "_work" / ".migrating" / "matter" / "book_matter.json").exists()


@pytest.mark.parametrize(
    "step", ["matter:prepared", "matter:moved", "matter:written", "matter:done", "matter:staged_removed"]
)
def test_interrupted_book_matter_migration_recovers(tmp_path: Path, step: str) -> None:
    work = _work(tmp_path)
    _with_book_matter(work)
    original = (work / "book.yaml").read_text(encoding="utf-8")
    nwm.STOP_AFTER = lambda reached: reached == step
    with pytest.raises(nwm._Interrupt):
        nwm.migrate_book_matter(work)
    nwm.STOP_AFTER = None
    results = nwm.recover(work)
    side = results[-1].rsplit(" ", 1)[-1]
    book = (work / "book.yaml").read_text(encoding="utf-8")
    if side == "legacy":
        assert (work / "book_matter" / "frontmatter" / "characters.md").is_file()
        assert not (work / "_novel_text" / "matter").exists()
        assert book == original
    else:
        assert side == "new"
        assert not (work / "book_matter").exists()
        assert (work / "_novel_text" / "matter" / "frontmatter" / "characters.md").is_file()
        assert "book_matter/" not in book
    assert side == ("legacy" if step == "matter:prepared" else "new")
    assert not (work / "_work" / ".migrating" / "matter" / "book_matter.json").exists()
    assert not (work / "_work" / ".migrating" / "matter" / "book.yaml.new").exists()


def test_book_matter_rewrites_every_path_on_a_line(tmp_path: Path) -> None:
    work = _work(tmp_path)
    (work / "book_matter" / "backmatter").mkdir(parents=True)
    (work / "book_matter" / "backmatter" / "a.md").write_text("a", encoding="utf-8")
    (work / "book_matter" / "backmatter" / "b.md").write_text("b", encoding="utf-8")
    (work / "book.yaml").write_text(
        "manuscript:\n  backmatter:\n    - id: notes\n"
        '      files: [book_matter/backmatter/a.md, "book_matter/backmatter/b.md"]\n',
        encoding="utf-8",
    )
    assert nwm.main([str(work), "--kind", "matter"]) == 0
    book = (work / "book.yaml").read_text(encoding="utf-8")
    assert 'files: [_novel_text/matter/backmatter/a.md, "_novel_text/matter/backmatter/b.md"]' in book
    assert "book_matter/" not in book


def test_book_yaml_that_cannot_be_rewritten_safely_stops_before_moving(tmp_path: Path) -> None:
    work = _work(tmp_path)
    (work / "book_matter").mkdir()
    (work / "book_matter" / "x.md").write_text("x", encoding="utf-8")
    # キーそのものに book_matter/ が入っていると、値だけを書き換えたことにならない
    (work / "book.yaml").write_text("book_matter/x.md: 1\n", encoding="utf-8")
    with pytest.raises(nwm.MigrationError) as error:
        nwm.migrate_book_matter(work)
    assert error.value.code == "BOOK_YAML"
    assert (work / "book_matter" / "x.md").is_file()
    assert not (work / "_work" / ".migrating" / "matter").exists()


def test_chapter_tools_do_not_count_matter(tmp_path: Path) -> None:
    import novel_char_count
    from novel_project_check import _novel_text_files

    work = _work(tmp_path)
    _with_book_matter(work)
    assert nwm.main([str(work), "--kind", "matter"]) == 0
    (work / "_novel_text" / "matter" / "novel_text99.md").write_text("x", encoding="utf-8")
    assert all("matter" not in path.parts for path in _novel_text_files(work))
    counted = novel_char_count.collect_targets([work], ROOT)
    assert counted  # 章は数えられている
    assert all("matter" not in Path(path).parts for path in counted)


def test_manuscript_source_does_not_remap_matter() -> None:
    from book_package.paths import apply_manuscript_source

    assert apply_manuscript_source("_novel_text/matter/frontmatter/characters.md", "novel_text_re") == (
        "_novel_text/matter/frontmatter/characters.md"
    )
    assert apply_manuscript_source("_novel_text/novel_text01.md", "novel_text_re") == "_novel_text_re/novel_text01.md"
    assert apply_manuscript_source("book_matter/frontmatter/characters.md", "novel_text_re") == (
        "book_matter/frontmatter/characters.md"
    )



def test_done_record_with_changed_book_yaml_is_not_cleaned_up(tmp_path: Path) -> None:
    # 完了の記録があっても、book.yaml が書き換えたあとの内容と違えば、片付けずに止める。
    work = _work(tmp_path)
    _with_book_matter(work)
    nwm.STOP_AFTER = lambda reached: reached == "matter:staged_removed"
    with pytest.raises(nwm._Interrupt):
        nwm.migrate_book_matter(work)
    nwm.STOP_AFTER = None
    book = work / "book.yaml"
    book.write_text(book.read_text(encoding="utf-8") + "# 手で足した行\n", encoding="utf-8")
    marker = work / "_work" / ".migrating" / "matter" / "book_matter.json"
    with pytest.raises(nwm.MigrationError) as error:
        nwm.recover(work)
    assert error.value.code == "UNRECOVERABLE"
    assert marker.is_file()
