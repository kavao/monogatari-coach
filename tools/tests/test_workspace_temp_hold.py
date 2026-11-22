import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from workspace_temp_hold import set_hold
from workspace_temp_inventory import entries


def test_hold_and_release_are_visible_in_inventory(tmp_path: Path) -> None:
    run = tmp_path / "_workingspace" / "tmp" / "runs" / "job"
    run.mkdir(parents=True)
    metadata = set_hold(tmp_path, "job", "再開予定")
    assert entries(tmp_path, datetime.now(timezone.utc))[0]["status"] == "保留"
    assert json.loads(metadata.read_text(encoding="utf-8"))["reason"] == "再開予定"
    set_hold(tmp_path, "job", None)
    assert entries(tmp_path, datetime.now(timezone.utc))[0]["status"] == "保存中"


def test_invalid_metadata_and_outside_paths_are_not_overwritten(tmp_path: Path) -> None:
    run = tmp_path / "_workingspace" / "tmp" / "runs" / "job"
    run.mkdir(parents=True)
    metadata = run / ".run.json"
    metadata.write_text("{", encoding="utf-8")
    with pytest.raises(ValueError):
        set_hold(tmp_path, "job", "保留")
    assert metadata.read_text(encoding="utf-8") == "{"
    with pytest.raises(ValueError):
        set_hold(tmp_path, "../job", "保留")
