from datetime import datetime, timedelta, timezone
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from workspace_temp_inventory import entries
from workspace_temp_inventory import is_link


def set_age(path: Path, time: datetime) -> None:
    timestamp = time.timestamp()
    os.utime(path, (timestamp, timestamp))


def test_inventory_reports_runs_hold_and_legacy_without_writes(tmp_path: Path) -> None:
    now = datetime(2026, 11, 22, tzinfo=timezone.utc)
    runs = tmp_path / "_workingspace" / "tmp" / "runs"
    expired = runs / "expired"
    held = runs / "held"
    broken = runs / "broken"
    for directory in (expired, held, broken):
        directory.mkdir(parents=True)
    (expired / "data.txt").write_text("old", encoding="utf-8")
    (held / ".run.json").write_text(json.dumps({
        "hold": True, "reason": "再開予定", "hold_since": "2026-11-12T00:00:00+00:00"
    }), encoding="utf-8")
    (broken / ".run.json").write_text("{", encoding="utf-8")
    legacy = tmp_path / "_workingspace" / "tmp_old"
    legacy.write_text("old", encoding="utf-8")
    protected = tmp_path / "_workingspace" / ".gitkeep"
    protected.write_text("keep", encoding="utf-8")
    old = now - timedelta(days=31)
    set_age(expired / "data.txt", old)
    for directory in (expired, held, broken):
        set_age(directory, old)
    before = {p: p.stat().st_mtime_ns for p in tmp_path.rglob("*")}

    rows = {Path(row["path"]).name: row for row in entries(tmp_path, now)}

    assert rows["expired"]["status"] == "期限切れ"
    assert rows["expired"]["modified"].endswith("+09:00")
    assert rows["expired"]["expires"].endswith("+09:00")
    assert rows["held"]["status"] == "保留"
    assert rows["held"]["hold_days"] == 10
    assert rows["broken"]["status"] == "保留"
    assert rows["tmp_old"]["status"] == "要確認"
    assert ".gitkeep" not in rows
    assert {p: p.stat().st_mtime_ns for p in tmp_path.rglob("*")} == before


def test_recent_parent_prevents_expiry_of_old_copied_file(tmp_path: Path) -> None:
    now = datetime.now(timezone.utc)
    run = tmp_path / "_workingspace" / "tmp" / "runs" / "copy"
    run.mkdir(parents=True)
    copied = run / "copy.txt"
    copied.write_text("content", encoding="utf-8")
    set_age(copied, now - timedelta(days=50))
    set_age(run, now - timedelta(days=1))
    assert entries(tmp_path, now)[0]["status"] == "保存中"


def test_link_inside_run_is_not_followed(tmp_path: Path) -> None:
    run = tmp_path / "_workingspace" / "tmp" / "runs" / "linked"
    run.mkdir(parents=True)
    try:
        (run / "link").symlink_to(tmp_path, target_is_directory=True)
    except OSError:
        if os.name != "nt":
            pytest.skip("この環境ではシンボリックリンクを作成できない")
        result = subprocess.run(
            ["cmd.exe", "/c", "mklink", "/J", str(run / "link"), str(tmp_path)],
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            pytest.skip("この環境ではジャンクションを作成できない")
    row = entries(tmp_path, datetime.now(timezone.utc))[0]
    assert row["status"] == "要確認"
    assert "リンク" in row["reason"]


def test_windows_reparse_point_is_treated_as_a_link() -> None:
    class DirectoryAttributes:
        st_mode = 0o040755
        st_file_attributes = 0x400

    assert is_link(DirectoryAttributes())


def test_expiry_boundary_and_unreadable_hold_are_reported(tmp_path: Path) -> None:
    now = datetime(2026, 11, 22, tzinfo=timezone.utc)
    runs = tmp_path / "_workingspace" / "tmp" / "runs"
    at_boundary = runs / "boundary"
    invalid_hold = runs / "invalid_hold"
    at_boundary.mkdir(parents=True)
    invalid_hold.mkdir()
    (invalid_hold / ".run.json").write_text('{"hold": "yes"}', encoding="utf-8")
    set_age(at_boundary, now - timedelta(days=30))
    rows = {Path(row["path"]).name: row for row in entries(tmp_path, now)}
    assert rows["boundary"]["status"] == "期限切れ"
    assert rows["invalid_hold"]["status"] == "保留"


def test_protected_names_are_excluded_and_containing_runs_are_held(tmp_path: Path) -> None:
    runs = tmp_path / "_workingspace" / "tmp" / "runs"
    (runs / "_novel_text_re").mkdir(parents=True)
    (runs / "_manga_ir_backup").mkdir()
    (runs / "job" / "novelai_manga_tests").mkdir(parents=True)
    rows = entries(tmp_path, datetime.now(timezone.utc))
    assert len(rows) == 1
    assert rows[0]["path"].endswith("/job")
    assert rows[0]["status"] == "要確認"
    assert "保護する名前" in rows[0]["reason"]


def test_gitkeep_inside_a_run_is_a_normal_file(tmp_path: Path) -> None:
    now = datetime.now(timezone.utc)
    run = tmp_path / "_workingspace" / "tmp" / "runs" / "job"
    nested = run / "nested"
    nested.mkdir(parents=True)
    placeholder = nested / ".gitkeep"
    placeholder.write_text("", encoding="utf-8")
    old = now - timedelta(days=31)
    for path in (placeholder, nested, run):
        set_age(path, old)
    rows = entries(tmp_path, now)
    assert len(rows) == 1
    assert rows[0]["status"] == "期限切れ"
    assert rows[0]["files"] == 1


def test_creating_and_removing_hold_updates_the_parent_expiry(tmp_path: Path) -> None:
    now = datetime.now(timezone.utc)
    run = tmp_path / "_workingspace" / "tmp" / "runs" / "job"
    run.mkdir(parents=True)
    set_age(run, now - timedelta(days=31))
    hold = run / ".run.json"
    hold.write_text('{"hold": true, "reason": "保留"}', encoding="utf-8")
    assert entries(tmp_path, datetime.now(timezone.utc))[0]["status"] == "保留"
    hold.unlink()
    assert entries(tmp_path, datetime.now(timezone.utc))[0]["status"] == "保存中"
