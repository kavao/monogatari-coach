from datetime import datetime, timedelta, timezone
import json
import os
import subprocess
import shutil
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from workspace_temp_inventory import entries
from workspace_temp_lock import operation_lock
from workspace_temp_quarantine import delete_item, list_items, quarantine_item, recover_move, restore_item, save_record


def make_expired_run(root: Path) -> tuple[Path, dict]:
    run = root / "_workingspace" / "tmp" / "runs" / "job"
    run.mkdir(parents=True)
    data = run / "data.txt"
    data.write_text("元の内容", encoding="utf-8")
    old = (datetime.now(timezone.utc) - timedelta(days=31)).timestamp()
    os.utime(data, (old, old))
    os.utime(run, (old, old))
    return run, entries(root, datetime.now(timezone.utc))[0]


def test_quarantine_restore_and_hold(tmp_path: Path) -> None:
    run, row = make_expired_run(tmp_path)
    item_id = quarantine_item(tmp_path, row["path"], row["modified"], row["fingerprint"])
    assert not run.exists()
    restored = restore_item(tmp_path, item_id)
    assert restored == run
    assert (run / "data.txt").read_text(encoding="utf-8") == "元の内容"
    assert entries(tmp_path, datetime.now(timezone.utc))[0]["status"] == "保留"


def test_quarantine_rejects_stale_held_or_protected(tmp_path: Path) -> None:
    run, row = make_expired_run(tmp_path)
    (run / "data.txt").write_text("更新", encoding="utf-8")
    with pytest.raises(ValueError):
        quarantine_item(tmp_path, row["path"], row["modified"], row["fingerprint"])
    (run / ".run.json").write_text('{"hold": true}', encoding="utf-8")
    held = entries(tmp_path, datetime.now(timezone.utc))[0]
    with pytest.raises(ValueError):
        quarantine_item(tmp_path, held["path"], held["modified"], held["fingerprint"])
    with pytest.raises(ValueError):
        quarantine_item(tmp_path, "_workingspace/.gitkeep", row["modified"], row["fingerprint"])


def test_quarantine_cli_accepts_fingerprint_without_modified(tmp_path: Path, monkeypatch) -> None:
    import workspace_temp_quarantine as command

    run, row = make_expired_run(tmp_path)
    monkeypatch.setattr(command, "ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["workspace_temp_quarantine.py", "quarantine", row["path"],
                                      "--fingerprint", row["fingerprint"]])
    assert command.main() == 0
    assert not run.exists()
    records = list_items(tmp_path)
    assert len(records) == 1
    assert records[0]["state"] == "quarantined"
    assert records[0]["source"] == row["path"]


def test_optional_modified_still_rejects_a_mismatch(tmp_path: Path) -> None:
    run, row = make_expired_run(tmp_path)
    with pytest.raises(ValueError):
        quarantine_item(tmp_path, row["path"], "2000-01-01T00:00:00+09:00", row["fingerprint"])
    assert (run / "data.txt").is_file()


def test_fingerprint_is_required_and_checked_without_modified(tmp_path: Path) -> None:
    run, row = make_expired_run(tmp_path)
    with pytest.raises(ValueError):
        quarantine_item(tmp_path, row["path"])
    (run / "data.txt").write_text("変更しました", encoding="utf-8")
    with pytest.raises(ValueError):
        quarantine_item(tmp_path, row["path"], expected_fingerprint=row["fingerprint"])
    assert (run / "data.txt").is_file()


def test_delete_uses_quarantine_time_and_retains_record(tmp_path: Path) -> None:
    run, row = make_expired_run(tmp_path)
    item_id = quarantine_item(tmp_path, row["path"], row["modified"], row["fingerprint"])
    item = tmp_path / "_workingspace" / "tmp" / "_quarantine" / item_id
    record_path = item / "record.json"
    record = json.loads(record_path.read_text(encoding="utf-8"))
    moved = datetime.fromisoformat(record["moved_at"])
    with pytest.raises(ValueError):
        delete_item(tmp_path, item_id, moved + timedelta(days=14) - timedelta(seconds=1))
    assert (item / "payload" / "data.txt").is_file()
    delete_item(tmp_path, item_id, moved + timedelta(days=14))
    assert not (item / "payload").exists()
    assert json.loads(record_path.read_text(encoding="utf-8"))["state"] == "deleted"
    assert not run.exists()


def test_restore_collision_does_not_overwrite(tmp_path: Path) -> None:
    run, row = make_expired_run(tmp_path)
    item_id = quarantine_item(tmp_path, row["path"], row["modified"], row["fingerprint"])
    run.mkdir()
    (run / "data.txt").write_text("別の内容", encoding="utf-8")
    with pytest.raises(ValueError):
        restore_item(tmp_path, item_id)
    assert (run / "data.txt").read_text(encoding="utf-8") == "別の内容"


def test_interrupted_move_record_can_be_recovered(tmp_path: Path) -> None:
    _, row = make_expired_run(tmp_path)
    item_id = quarantine_item(tmp_path, row["path"], row["modified"], row["fingerprint"])
    record_path = tmp_path / "_workingspace" / "tmp" / "_quarantine" / item_id / "record.json"
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record.update(state="moving", moved_at=None)
    save_record(record_path, record)
    recover_move(tmp_path, item_id)
    assert json.loads(record_path.read_text(encoding="utf-8"))["state"] == "quarantined"


def test_operations_use_the_same_lock(tmp_path: Path) -> None:
    _, row = make_expired_run(tmp_path)
    with operation_lock(tmp_path):
        with pytest.raises(RuntimeError):
            quarantine_item(tmp_path, row["path"], row["modified"], row["fingerprint"])


def test_legacy_file_restores_to_held_folder(tmp_path: Path) -> None:
    temporary = tmp_path / "_workingspace" / "tmp"
    temporary.mkdir(parents=True)
    source = temporary / "old.txt"
    source.write_text("original", encoding="utf-8")
    row = entries(tmp_path, datetime.now(timezone.utc))[0]
    item_id = quarantine_item(tmp_path, row["path"], row["modified"], row["fingerprint"])
    restored = restore_item(tmp_path, item_id)
    assert restored.read_text(encoding="utf-8") == "original"
    assert restored.parent.name == f"restored_{item_id}"
    assert json.loads((restored.parent / ".run.json").read_text(encoding="utf-8"))["hold"] is True


def test_legacy_file_can_be_quarantined_when_tmp_does_not_exist(tmp_path: Path) -> None:
    workspace = tmp_path / "_workingspace"
    workspace.mkdir()
    source = workspace / "tmp_old.txt"
    source.write_text("original", encoding="utf-8")
    row = entries(tmp_path, datetime.now(timezone.utc))[0]
    item_id = quarantine_item(tmp_path, row["path"], row["modified"], row["fingerprint"])
    restored = restore_item(tmp_path, item_id)
    assert restored.read_text(encoding="utf-8") == "original"


def test_interrupted_restore_checks_identity(tmp_path: Path) -> None:
    run, row = make_expired_run(tmp_path)
    item_id = quarantine_item(tmp_path, row["path"], row["modified"], row["fingerprint"])
    item = tmp_path / "_workingspace" / "tmp" / "_quarantine" / item_id
    payload = item / "payload"
    record_path = item / "record.json"
    record = json.loads(record_path.read_text(encoding="utf-8"))
    info = payload.lstat()
    record.update(state="restoring", restore_inode=info.st_ino, restore_device=info.st_dev)
    save_record(record_path, record)
    os.rename(payload, run)
    assert restore_item(tmp_path, item_id) == run
    assert json.loads(record_path.read_text(encoding="utf-8"))["state"] == "restored"


def test_changed_child_is_rejected_even_if_latest_time_is_unchanged(tmp_path: Path) -> None:
    run, row = make_expired_run(tmp_path)
    original_mtime = run.stat().st_mtime_ns
    data = run / "data.txt"
    original_file_mtime = data.stat().st_mtime_ns
    data.write_text("別の内容です", encoding="utf-8")
    os.utime(data, ns=(original_file_mtime, original_file_mtime))
    os.utime(run, ns=(original_mtime, original_mtime))
    with pytest.raises(ValueError):
        quarantine_item(tmp_path, row["path"], row["modified"], row["fingerprint"])
    assert data.exists()


def test_bad_quarantine_record_cannot_be_deleted(tmp_path: Path) -> None:
    _, row = make_expired_run(tmp_path)
    item_id = quarantine_item(tmp_path, row["path"], row["modified"], row["fingerprint"])
    item = tmp_path / "_workingspace" / "tmp" / "_quarantine" / item_id
    (item / "record.json").write_text("{", encoding="utf-8")
    with pytest.raises(ValueError):
        delete_item(tmp_path, item_id, datetime.now(timezone.utc) + timedelta(days=100))
    assert (item / "payload" / "data.txt").is_file()


def test_changed_quarantined_content_is_not_deleted(tmp_path: Path) -> None:
    _, row = make_expired_run(tmp_path)
    item_id = quarantine_item(tmp_path, row["path"], row["modified"], row["fingerprint"])
    item = tmp_path / "_workingspace" / "tmp" / "_quarantine" / item_id
    payload = item / "payload"
    added = payload / "new.txt"
    added.write_text("あとから追加", encoding="utf-8")
    with pytest.raises(ValueError, match="変更"):
        delete_item(tmp_path, item_id, datetime.now(timezone.utc) + timedelta(days=15))
    assert added.read_text(encoding="utf-8") == "あとから追加"


def test_interrupted_delete_with_remaining_payload_requires_review(tmp_path: Path) -> None:
    _, row = make_expired_run(tmp_path)
    item_id = quarantine_item(tmp_path, row["path"], row["modified"], row["fingerprint"])
    item = tmp_path / "_workingspace" / "tmp" / "_quarantine" / item_id
    record_path = item / "record.json"
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record["state"] = "deleting"
    save_record(record_path, record)
    with pytest.raises(ValueError, match="中断"):
        delete_item(tmp_path, item_id, datetime.now(timezone.utc) + timedelta(days=15))
    assert (item / "payload" / "data.txt").is_file()


def test_junction_in_quarantine_is_not_traversed_or_deleted(tmp_path: Path) -> None:
    _, row = make_expired_run(tmp_path)
    item_id = quarantine_item(tmp_path, row["path"], row["modified"], row["fingerprint"])
    payload = tmp_path / "_workingspace" / "tmp" / "_quarantine" / item_id / "payload"
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("keep", encoding="utf-8")
    link = payload / "linked"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        if os.name != "nt":
            pytest.skip("シンボリックリンクを作成できない")
        result = subprocess.run(["cmd.exe", "/c", "mklink", "/J", str(link), str(outside)],
                                capture_output=True, check=False)
        if result.returncode != 0:
            pytest.skip("ジャンクションを作成できない")
    future = datetime.now(timezone.utc) + timedelta(days=15)
    with pytest.raises(ValueError):
        delete_item(tmp_path, item_id, future)
    record_path = payload.parent / "record.json"
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record.update(state="delete_failed", error="削除に失敗")
    save_record(record_path, record)
    assert "remaining_error" in list_items(tmp_path)[0]
    with pytest.raises(ValueError):
        delete_item(tmp_path, item_id, future, retry_fingerprint="invalid")
    assert (outside / "keep.txt").read_text(encoding="utf-8") == "keep"


def test_failed_deletion_keeps_record_and_requires_review(tmp_path: Path, monkeypatch) -> None:
    _, row = make_expired_run(tmp_path)
    item_id = quarantine_item(tmp_path, row["path"], row["modified"], row["fingerprint"])
    item = tmp_path / "_workingspace" / "tmp" / "_quarantine" / item_id

    def fail_delete(path: Path) -> None:
        raise PermissionError("in use")

    monkeypatch.setattr(shutil, "rmtree", fail_delete)
    with pytest.raises(PermissionError):
        delete_item(tmp_path, item_id, datetime.now(timezone.utc) + timedelta(days=15))
    record = json.loads((item / "record.json").read_text(encoding="utf-8"))
    assert record["state"] == "delete_failed"
    assert "PermissionError" in record["error"]
    with pytest.raises(ValueError):
        delete_item(tmp_path, item_id, datetime.now(timezone.utc) + timedelta(days=15))
    assert (item / "payload" / "data.txt").is_file()


def test_retry_delete_requires_confirmed_remaining_fingerprint(tmp_path: Path, monkeypatch) -> None:
    _, row = make_expired_run(tmp_path)
    item_id = quarantine_item(tmp_path, row["path"], row["modified"], row["fingerprint"])
    item = tmp_path / "_workingspace" / "tmp" / "_quarantine" / item_id
    payload = item / "payload"
    (payload / "extra.txt").write_text("追加", encoding="utf-8")
    record_path = item / "record.json"
    record = json.loads(record_path.read_text(encoding="utf-8"))
    from workspace_temp_inventory import fingerprint_path
    record["payload_fingerprint"] = fingerprint_path(payload)
    save_record(record_path, record)
    original_rmtree = shutil.rmtree

    def fail_after_partial_deletion(path: Path) -> None:
        (path / "extra.txt").unlink()
        raise PermissionError("in use")

    monkeypatch.setattr(shutil, "rmtree", fail_after_partial_deletion)
    future = datetime.now(timezone.utc) + timedelta(days=15)
    with pytest.raises(PermissionError):
        delete_item(tmp_path, item_id, future)
    monkeypatch.setattr(shutil, "rmtree", original_rmtree)
    preview = list_items(tmp_path)[0]
    assert preview["state"] == "delete_failed"
    assert preview["remaining_files"] == 1
    assert preview["remaining_bytes"] > 0
    fingerprint = preview["remaining_fingerprint"]
    with pytest.raises(ValueError, match="確認"):
        delete_item(tmp_path, item_id, future)
    with pytest.raises(ValueError, match="14日"):
        delete_item(tmp_path, item_id, datetime.now(timezone.utc), retry_fingerprint=fingerprint)
    with pytest.raises(ValueError, match="変更"):
        delete_item(tmp_path, item_id, future, retry_fingerprint="incorrect")
    assert (payload / "data.txt").is_file()
    delete_item(tmp_path, item_id, future, retry_fingerprint=fingerprint)
    result = json.loads(record_path.read_text(encoding="utf-8"))
    assert result["state"] == "deleted"
    assert result["retry_count"] == 1
    assert "PermissionError" in result["previous_error"]
    assert not payload.exists()


def test_retry_delete_handles_missing_payload_only_after_confirmation(tmp_path: Path) -> None:
    _, row = make_expired_run(tmp_path)
    item_id = quarantine_item(tmp_path, row["path"], row["modified"], row["fingerprint"])
    item = tmp_path / "_workingspace" / "tmp" / "_quarantine" / item_id
    record_path = item / "record.json"
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record.update(state="delete_failed", error="削除に失敗")
    save_record(record_path, record)
    shutil.rmtree(item / "payload")
    preview = list_items(tmp_path)[0]
    assert preview["remaining_fingerprint"] == "missing"
    future = datetime.now(timezone.utc) + timedelta(days=15)
    with pytest.raises(ValueError):
        delete_item(tmp_path, item_id, future, retry_fingerprint="not-missing")
    delete_item(tmp_path, item_id, future, retry_fingerprint="missing")
    assert json.loads(record_path.read_text(encoding="utf-8"))["state"] == "deleted"


def test_retry_delete_rechecks_changes_after_preview(tmp_path: Path) -> None:
    _, row = make_expired_run(tmp_path)
    item_id = quarantine_item(tmp_path, row["path"], row["modified"], row["fingerprint"])
    item = tmp_path / "_workingspace" / "tmp" / "_quarantine" / item_id
    record_path = item / "record.json"
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record.update(state="delete_failed", error="削除に失敗")
    save_record(record_path, record)
    fingerprint = list_items(tmp_path)[0]["remaining_fingerprint"]
    added = item / "payload" / "new.txt"
    added.write_text("new", encoding="utf-8")
    with pytest.raises(ValueError, match="変更"):
        delete_item(tmp_path, item_id, datetime.now(timezone.utc) + timedelta(days=15), retry_fingerprint=fingerprint)
    assert added.is_file()
    assert json.loads(record_path.read_text(encoding="utf-8"))["state"] == "delete_failed"


def test_retry_delete_cli_uses_confirmed_preview(tmp_path: Path, monkeypatch) -> None:
    import workspace_temp_quarantine as command

    _, row = make_expired_run(tmp_path)
    item_id = quarantine_item(tmp_path, row["path"], row["modified"], row["fingerprint"])
    item = tmp_path / "_workingspace" / "tmp" / "_quarantine" / item_id
    record_path = item / "record.json"
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record.update(state="delete_failed", error="削除に失敗",
                  moved_at=(datetime.now(timezone.utc) - timedelta(days=15)).isoformat())
    save_record(record_path, record)
    fingerprint = list_items(tmp_path)[0]["remaining_fingerprint"]
    monkeypatch.setattr(command, "ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["workspace_temp_quarantine.py", "retry-delete", item_id,
                                      "--fingerprint", fingerprint])
    assert command.main() == 0
    assert json.loads(record_path.read_text(encoding="utf-8"))["state"] == "deleted"
    assert not (item / "payload").exists()


def test_interrupted_completed_deletion_can_be_finalized(tmp_path: Path) -> None:
    _, row = make_expired_run(tmp_path)
    item_id = quarantine_item(tmp_path, row["path"], row["modified"], row["fingerprint"])
    item = tmp_path / "_workingspace" / "tmp" / "_quarantine" / item_id
    record_path = item / "record.json"
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record["state"] = "deleting"
    save_record(record_path, record)
    shutil.rmtree(item / "payload")
    delete_item(tmp_path, item_id, datetime.now(timezone.utc) + timedelta(days=15))
    assert json.loads(record_path.read_text(encoding="utf-8"))["state"] == "deleted"


def test_recovery_rejects_changed_payload_and_list_is_read_only(tmp_path: Path) -> None:
    _, row = make_expired_run(tmp_path)
    item_id = quarantine_item(tmp_path, row["path"], row["modified"], row["fingerprint"])
    item = tmp_path / "_workingspace" / "tmp" / "_quarantine" / item_id
    record_path = item / "record.json"
    listed = list_items(tmp_path)
    assert listed[0]["id"] == item_id
    assert listed[0]["delete_after"].endswith("+09:00")
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record["state"] = "moving"
    save_record(record_path, record)
    (item / "payload" / "new.txt").write_text("added", encoding="utf-8")
    with pytest.raises(ValueError, match="一致"):
        recover_move(tmp_path, item_id)
    assert (item / "payload" / "new.txt").is_file()
