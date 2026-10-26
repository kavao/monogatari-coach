"""執筆接続の置き場（_workingspace/plans/20261024_work-folder-layout.md §3.1、M4）。"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from test_writing_bridge import FIXTURE, ROOT, _copy_ok  # noqa: E402
from work_paths import resolve_unit  # noqa: E402
from writing_bridge import locking  # noqa: E402
from writing_bridge.commands import allocate_request_id, inspect, prepare, receive  # noqa: E402
from writing_bridge.errors import BridgeError  # noqa: E402
from writing_bridge.models import ContextDocument, RequestDocument, RequestKind, Selector, SelectorKind  # noqa: E402
from writing_bridge.storage import load_json_model, load_model  # noqa: E402

SCENE = "ch01-001"
OBSERVATIONS = FIXTURE / "ok_ch01_001" / "work" / "_writing" / SCENE / "run-0001" / "observations.json"


def _prepare(work: Path) -> None:
    code, message = prepare(
        work,
        scene_id=SCENE,
        text_path="_novel_text/novel_text01.md",
        request_kind=RequestKind.NEW,
        model_id="local-writer",
        selector=Selector(kind=SelectorKind.HEADING, value="第一章　駅までの道"),
        links_path=None,
        repo_root=ROOT,
    )
    assert code == 0, message


def _receive(work: Path, run_id: str) -> None:
    code, message = receive(
        work,
        scene_id=SCENE,
        run_id=run_id,
        candidate=work / "_metron" / SCENE / "marked.md",
        request_id=None,
    )
    assert code == 0, message


def _inspect(work: Path, run_id: str) -> tuple[int, str]:
    return inspect(
        work,
        scene_id=SCENE,
        run_id=run_id,
        observations_path=OBSERVATIONS,
        marked_path=None,
        repo_root=ROOT,
    )


def _seed_legacy_scene(work: Path) -> Path:
    # 解放後も残る場面ロックだけがある古い置き場（M4 より前の作品で、run を作る前の状態）
    lock = work / "_writing" / SCENE / ".operation.lock"
    lock.parent.mkdir(parents=True)
    lock.write_bytes(b"0")
    return lock.parent


def test_new_work_runs_go_to_work_dir(tmp_path: Path) -> None:
    work = _copy_ok(tmp_path)
    _prepare(work)
    run = work / "_work" / "writing" / SCENE / "run-0001"
    assert (run / "request.yaml").is_file()
    assert not (work / "_writing").exists()
    context = load_json_model(run / "context.json", ContextDocument)
    paths = {item.path for item in context.input_hashes}
    # 記録には実際の置き場を書く（執筆接続は新しい置き場、METRON は M5 まで古い置き場）
    assert f"_work/writing/{SCENE}/run-0001/links.yaml" in paths
    assert f"_metron/{SCENE}/contract.yaml" in paths


def test_legacy_scene_keeps_new_runs_in_legacy(tmp_path: Path) -> None:
    work = _copy_ok(tmp_path)
    legacy = _seed_legacy_scene(work)
    _prepare(work)
    assert (legacy / "run-0001" / "request.yaml").is_file()
    assert not (work / "_work" / "writing").exists()
    context = load_json_model(legacy / "run-0001" / "context.json", ContextDocument)
    assert f"_writing/{SCENE}/run-0001/links.yaml" in {item.path for item in context.input_hashes}


def test_migrated_scene_inspects_without_context_rebuild(tmp_path: Path) -> None:
    work = _copy_ok(tmp_path)
    legacy = _seed_legacy_scene(work)
    _prepare(work)
    _receive(work, "run-0001")
    # 移行を模す: 場面の組をまとめて新しい置き場へ移す（記録の中の _writing/... の参照は書き換えない）
    target = work / "_work" / "writing" / SCENE
    target.parent.mkdir(parents=True)
    shutil.move(str(legacy), str(target))
    assert resolve_unit(work, "writing", SCENE).layout == "new"

    code, message = _inspect(work, "run-0001")
    assert code == 0, message
    journal = (target / "run-0001" / "journal.jsonl").read_text(encoding="utf-8")
    # 記録した入力のパス（_writing/...）と今のパス（_work/writing/...）は、照合では同じ組として扱われる
    assert "context rebuilt" not in journal
    # 古い置き場に場面を作り直していない（空の親フォルダ _writing/ はテストの移動で残るだけ）
    assert not (work / "_writing" / SCENE).exists()


def test_request_numbers_count_both_locations(tmp_path: Path) -> None:
    work = _copy_ok(tmp_path)
    _prepare(work)
    request_text = (work / "_work" / "writing" / SCENE / "run-0001" / "request.yaml").read_text(encoding="utf-8")
    assert "WRQ-0001" in request_text
    legacy_request = work / "_writing" / "ch09-001" / "run-0001" / "request.yaml"
    legacy_request.parent.mkdir(parents=True)
    legacy_request.write_text(
        request_text.replace("WRQ-0001", "WRQ-0005").replace(SCENE, "ch09-001"), encoding="utf-8"
    )
    assert load_model(legacy_request, RequestDocument).request_id == "WRQ-0005"
    assert allocate_request_id(work) == "WRQ-0006"


def test_same_scene_in_both_locations_is_conflict(tmp_path: Path) -> None:
    work = _copy_ok(tmp_path)
    _seed_legacy_scene(work)
    other = work / "_work" / "writing" / SCENE / "note.txt"
    other.parent.mkdir(parents=True)
    other.write_text("x", encoding="utf-8")
    with pytest.raises(BridgeError) as error:
        _prepare(work)
    assert error.value.code == "LAYOUT_CONFLICT"


def test_scene_lock_detects_location_moved_after_resolution(tmp_path: Path, monkeypatch) -> None:
    # レビュー指摘（M2）と同じ順序: 古い置き場を選んだあとに移行が終わっても、古い置き場に組を作り直さない。
    work = _copy_ok(tmp_path)
    legacy = _seed_legacy_scene(work)
    target = work / "_work" / "writing" / SCENE
    real = locking.writing_scene_dir
    calls = {"n": 0}

    def resolve_then_migrate(root: Path, scene_id: str) -> Path:
        chosen = real(root, scene_id)
        calls["n"] += 1
        if calls["n"] == 1:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(legacy), str(target))
        return chosen

    monkeypatch.setattr(locking, "writing_scene_dir", resolve_then_migrate)
    with pytest.raises(BridgeError) as error:
        with locking.scene_lock(work, SCENE):
            pass
    assert error.value.code == "STALE_LOCATION"
    # 自分で作り直したロックとフォルダは片付けられ、組は新しい置き場だけにある
    assert not (work / "_writing" / SCENE).exists()
    assert resolve_unit(work, "writing", SCENE).layout == "new"
    monkeypatch.setattr(locking, "writing_scene_dir", real)
    with locking.scene_lock(work, SCENE):
        assert (target / ".operation.lock").is_file()


def test_repair_input_comparison_treats_both_locations_as_same_unit() -> None:
    from writing_bridge.repair import _canonical_hashes

    legacy = {f"_writing/{SCENE}/run-0001/links.yaml": "sha256:a", f"_metron/{SCENE}/beats.yaml": "sha256:b"}
    new = {f"_work/writing/{SCENE}/run-0001/links.yaml": "sha256:a", f"_work/metron/{SCENE}/beats.yaml": "sha256:b"}
    assert _canonical_hashes(legacy) == _canonical_hashes(new)
    changed = dict(new)
    changed[f"_work/metron/{SCENE}/beats.yaml"] = "sha256:c"
    assert _canonical_hashes(legacy) != _canonical_hashes(changed)


def test_readers_find_runs_in_new_location(tmp_path: Path) -> None:
    import goal_status
    from novel_project_check import _measured_text_hashes

    work = _copy_ok(tmp_path)
    _prepare(work)
    status = goal_status.judge_scene(work, SCENE, 1)
    assert status.state != goal_status.NOT_STARTED
    assert SCENE in goal_status._scene_ids(work).get(1, set())
    assert _measured_text_hashes(work, 1)["run_exists"] is True


def test_prepare_does_not_create_run_in_legacy_after_scene_moved(tmp_path: Path, monkeypatch) -> None:
    # レビュー指摘（M4）: 保存先を決めた直後に場面が新しい置き場へ移っても、古い置き場に run を作らない。
    work = _copy_ok(tmp_path)
    _prepare(work)
    legacy = work / "_writing" / SCENE
    new = work / "_work" / "writing" / SCENE
    shutil.move(str(new), str(legacy))  # M4 より前の場面（古い置き場）を再現
    shutil.rmtree(work / "_work")
    real = locking.writing_scene_dir
    calls = {"n": 0}

    def resolve_then_migrate(root: Path, scene_id: str) -> Path:
        chosen = real(root, scene_id)
        calls["n"] += 1
        if calls["n"] == 1:
            new.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(legacy), str(new))
        return chosen

    monkeypatch.setattr(locking, "writing_scene_dir", resolve_then_migrate)
    with pytest.raises(BridgeError) as error:
        _prepare(work)
    assert error.value.code == "STALE_LOCATION"
    assert not legacy.exists()
    assert sorted(child.name for child in new.iterdir() if child.name.startswith("run-")) == ["run-0001"]
    assert resolve_unit(work, "writing", SCENE).layout == "new"
    # もう一度実行すれば、新しい置き場で次の run が作られる
    monkeypatch.setattr(locking, "writing_scene_dir", real)
    _prepare(work)
    assert (new / "run-0002" / "request.yaml").is_file()


def test_failed_prepare_leaves_no_lock_only_scene(tmp_path: Path) -> None:
    work = _copy_ok(tmp_path)
    with pytest.raises(BridgeError):
        prepare(
            work,
            scene_id=SCENE,
            text_path="_novel_text/missing.md",
            request_kind=RequestKind.REFINE,
            model_id="local-writer",
            selector=Selector(kind=SelectorKind.HEADING, value="x"),
            links_path=None,
            repo_root=ROOT,
        )
    assert not (work / "_work").exists()


@pytest.mark.parametrize("problem", ["conflict", "migrating"])
def test_inspection_gate_does_not_accept_unresolved_scene(tmp_path: Path, problem: str) -> None:
    # レビュー指摘（M4）: 競合・移行中の場面の run を、計測済みの根拠に採用しない。
    from novel_project_check import _measured_text_hashes
    from work_paths import migration_marker

    work = _copy_ok(tmp_path)
    _prepare(work)
    new = work / "_work" / "writing" / SCENE
    report = new / "run-0001" / "report.json"
    report.write_text('{"target_text_sha256": "sha256:x"}', encoding="utf-8")
    assert _measured_text_hashes(work, 1)["layout_errors"] == []
    if problem == "conflict":
        stray = work / "_writing" / SCENE / "note.txt"
        stray.parent.mkdir(parents=True)
        stray.write_text("x", encoding="utf-8")
        expected = "CONFLICT"
    else:
        marker = migration_marker(work, "writing", SCENE)
        marker.parent.mkdir(parents=True)
        marker.write_text("{}", encoding="utf-8")
        expected = "MIGRATING"
    measured = _measured_text_hashes(work, 1)
    assert measured["hashes"] == {}
    assert measured["layout_errors"] == [{"scene": SCENE, "code": expected}]


@pytest.mark.parametrize("problem", ["conflict", "migrating"])
def test_inspection_gate_reports_chapter_when_scene_unresolved(tmp_path: Path, problem: str) -> None:
    from novel_project_check import _check_inspection_layers, _current_text_hash
    from work_paths import migration_marker

    work = _copy_ok(tmp_path)
    _prepare(work)
    run = work / "_work" / "writing" / SCENE / "run-0001"
    digest = _current_text_hash(work / "_novel_text" / "novel_text01.md")
    (run / "report.json").write_text('{"target_text_sha256": "' + digest + '"}', encoding="utf-8")

    def chapter_one():
        return [item for item in _check_inspection_layers(work)["unmeasured_chapters"] if item["chapter"] == 1]

    assert chapter_one() == []  # 本文のハッシュが一致していれば計測済み
    if problem == "conflict":
        stray = work / "_writing" / SCENE / "note.txt"
        stray.parent.mkdir(parents=True)
        stray.write_text("x", encoding="utf-8")
    else:
        marker = migration_marker(work, "writing", SCENE)
        marker.parent.mkdir(parents=True)
        marker.write_text("{}", encoding="utf-8")
    pending = chapter_one()
    assert len(pending) == 1
    assert any(entry.startswith("場面の置き場") for entry in pending[0]["missing"])


_HOLDER = """
import sys, time
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from writing_bridge import locking
work, scene, held, release = Path(sys.argv[2]), sys.argv[3], Path(sys.argv[4]), Path(sys.argv[5])
with locking.scene_lock(work, scene):
    held.write_text("held", encoding="utf-8")
    deadline = time.time() + 30
    while not release.exists() and time.time() < deadline:
        time.sleep(0.05)
"""


def test_lock_file_is_never_deleted_and_other_process_keeps_its_lock(tmp_path: Path) -> None:
    # レビュー指摘（M4 再レビュー）: 解放したあとに正式なロックを消さない。別のプロセスが取ったロックを壊さない。
    import subprocess
    import sys
    import time

    work = _copy_ok(tmp_path)
    lock = work / "_work" / "writing" / SCENE / ".operation.lock"

    # 失敗した操作のあとも、ロックファイルは残り、元の例外がそのまま出る
    with pytest.raises(RuntimeError, match="boom"):
        with locking.scene_lock(work, SCENE):
            raise RuntimeError("boom")
    assert lock.is_file()

    held, release = tmp_path / "held", tmp_path / "release"
    child = subprocess.Popen(
        [sys.executable, "-c", _HOLDER, str(ROOT / "tools"), str(work), SCENE, str(held), str(release)],
    )
    try:
        deadline = time.time() + 30
        while not held.exists() and time.time() < deadline:
            time.sleep(0.05)
        assert held.exists(), "child did not take the lock"
        for _ in range(2):
            with pytest.raises(BridgeError) as error:
                with locking.scene_lock(work, SCENE):
                    pass
            assert error.value.code == "JOB_CONFLICT"
            assert lock.is_file()  # 取れなかった側はロックを消さない
    finally:
        release.write_text("go", encoding="utf-8")
        assert child.wait(timeout=30) == 0
    assert lock.is_file()
    with locking.scene_lock(work, SCENE):
        pass


# --- M5: METRON の場面の置き場 ---


def _move_metron_to_new(work: Path) -> Path:
    target = work / "_work" / "metron" / SCENE
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(work / "_metron" / SCENE), str(target))
    return target


def test_metron_scene_in_new_location_receives_measurements(tmp_path: Path) -> None:
    work = _copy_ok(tmp_path)
    metron = _move_metron_to_new(work)
    marked = metron / "marked.md"
    _prepare(work)
    run = work / "_work" / "writing" / SCENE / "run-0001"
    context = load_json_model(run / "context.json", ContextDocument)
    paths = {item.path for item in context.input_hashes}
    assert f"_work/metron/{SCENE}/contract.yaml" in paths
    assert f"_metron/{SCENE}/contract.yaml" not in paths
    code, message = receive(work, scene_id=SCENE, run_id="run-0001", candidate=marked, request_id=None)
    assert code == 0, message
    code, message = _inspect(work, "run-0001")
    assert code == 0, message
    # 計測の記録は新しい置き場の場面に書かれ、古い置き場に場面を作り直さない
    assert any(path.name.startswith("marked.") and path.name != "marked.md" for path in metron.iterdir())
    assert not (work / "_metron" / SCENE).exists()


def test_inspection_gate_stops_on_metron_conflict(tmp_path: Path) -> None:
    from novel_project_check import _check_inspection_layers

    work = _copy_ok(tmp_path)
    stray = work / "_work" / "metron" / SCENE / "note.txt"
    stray.parent.mkdir(parents=True)
    stray.write_text("x", encoding="utf-8")
    pending = [item for item in _check_inspection_layers(work)["unmeasured_chapters"] if item["chapter"] == 1]
    assert pending
    assert any(entry.startswith("METRON の場面の置き場") for entry in pending[0]["missing"])


def test_ai_writer_compare_reads_metron_in_new_location(tmp_path: Path) -> None:
    from ai_writer.compare import load_inputs

    work = _copy_ok(tmp_path)
    _move_metron_to_new(work)
    inputs = load_inputs(work, SCENE)
    assert inputs is not None
