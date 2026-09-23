from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import novel_onboard  # noqa: E402
from inspection_flags import InspectionFlag, load_inspection_flags  # noqa: E402


def test_dry_run_reports_default_decision_without_creating(tmp_path: Path, monkeypatch, capsys) -> None:
    root = tmp_path
    (root / "novels").mkdir()
    monkeypatch.setattr(novel_onboard, "repo_root", lambda: root)

    assert novel_onboard.main(["試験作品", "--dry-run"]) == 0

    output = capsys.readouterr().out
    assert "未応答・既定 ON" in output
    assert not (root / "novels" / "001_試験作品").exists()


def test_new_onboard_writes_flags_and_layers(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path
    (root / "novels").mkdir()
    monkeypatch.setattr(novel_onboard, "repo_root", lambda: root)

    def fake_bootstrap(novel_dir: Path, _root: Path):
        novel_dir.mkdir(parents=True, exist_ok=True)
        return []

    monkeypatch.setattr(novel_onboard, "bootstrap_novel", fake_bootstrap)
    monkeypatch.setattr(
        novel_onboard,
        "determine_next_step",
        lambda _work: ("Plan Mode", "次へ"),
    )

    assert novel_onboard.main(["試験作品"]) == 0

    work = root / "novels" / "001_試験作品"
    flags = load_inspection_flags(work / "config.md")
    assert flags.metron is InspectionFlag.ON
    assert flags.chronos is InspectionFlag.ON
    assert (work / "_metron").is_dir()
    assert (work / "chronos").is_dir()


def test_new_onboard_explicit_off_does_not_prepare_layers(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path
    (root / "novels").mkdir()
    monkeypatch.setattr(novel_onboard, "repo_root", lambda: root)
    monkeypatch.setattr(
        novel_onboard,
        "bootstrap_novel",
        lambda novel_dir, _root: novel_dir.mkdir(parents=True, exist_ok=True) or [],
    )
    monkeypatch.setattr(
        novel_onboard,
        "determine_next_step",
        lambda _work: ("Plan Mode", "次へ"),
    )

    assert novel_onboard.main(["停止作品", "--metron", "OFF", "--chronos", "OFF"]) == 0

    work = root / "novels" / "001_停止作品"
    flags = load_inspection_flags(work / "config.md")
    assert flags.metron is InspectionFlag.OFF
    assert flags.chronos is InspectionFlag.OFF
    assert not (work / "_metron").exists()
    assert not (work / "chronos").exists()


def test_existing_onboard_does_not_turn_missing_flags_on(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path
    novels = root / "novels"
    novels.mkdir()
    work = novels / "001_既存"
    work.mkdir()
    monkeypatch.setattr(novel_onboard, "repo_root", lambda: root)
    monkeypatch.setattr(novel_onboard, "bootstrap_novel", lambda novel_dir, _root: [])
    monkeypatch.setattr(
        novel_onboard,
        "determine_next_step",
        lambda _work: ("Plan Mode", "次へ"),
    )

    assert novel_onboard.main([str(work)]) == 0

    assert not (work / "config.md").exists()
    assert not (work / "_metron").exists()
    assert not (work / "chronos").exists()
