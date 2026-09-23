from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from inspection_bootstrap import (  # noqa: E402
    InspectionBootstrapError,
    create_initial_config,
    initialize_new_layers,
)
from inspection_flags import InspectionFlag, load_inspection_flags  # noqa: E402


def test_new_defaults_record_unanswered_and_prepare_layers(tmp_path: Path) -> None:
    work = tmp_path / "001_旅"

    actions = initialize_new_layers(work, 1, "旅")

    config = (work / "config.md").read_text(encoding="utf-8")
    assert "未応答・既定 ON" in config
    flags = load_inspection_flags(work / "config.md")
    assert flags.metron is InspectionFlag.ON
    assert flags.chronos is InspectionFlag.ON
    assert (work / "_metron").is_dir()
    assert (work / "chronos").is_dir()
    assert any(rel == "_metron/" for rel, _ in actions)
    assert any(rel == "chronos/" for rel, _ in actions)


def test_explicit_off_is_recorded_and_does_not_prepare_layer_dirs(tmp_path: Path) -> None:
    work = tmp_path / "002_静かな旅"

    initialize_new_layers(work, 2, "静かな旅", metron="OFF", chronos="OFF")

    config = (work / "config.md").read_text(encoding="utf-8")
    assert "METRON=ユーザー明示 OFF" in config
    assert "CHRONOS=ユーザー明示 OFF" in config
    flags = load_inspection_flags(work / "config.md")
    assert flags.metron is InspectionFlag.OFF
    assert flags.chronos is InspectionFlag.OFF
    assert not (work / "_metron").exists()
    assert not (work / "chronos").exists()


def test_existing_config_is_never_overwritten(tmp_path: Path) -> None:
    work = tmp_path / "003_既存"
    work.mkdir()
    config = work / "config.md"
    original = "# existing\n\n## 基本情報\n\n| 項目 | 内容 |\n|------|------|\n| METRON | OFF |\n| CHRONOS | OFF |\n"
    config.write_text(original, encoding="utf-8")

    actions = initialize_new_layers(work, 3, "既存")

    assert config.read_text(encoding="utf-8") == original
    assert not (work / "_metron").exists()
    assert not (work / "chronos").exists()
    assert actions == [("config.md", "skip (exists)")]


def test_config_directory_is_rejected(tmp_path: Path) -> None:
    work = tmp_path / "004_壊れた"
    work.mkdir()
    (work / "config.md").mkdir()

    with pytest.raises(InspectionBootstrapError, match="not a file"):
        create_initial_config(work, 4, "壊れた")
