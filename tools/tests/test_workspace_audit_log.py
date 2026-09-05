from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from workspace_audit_log import main  # noqa: E402


def _config(rows: str) -> str:
    return (
        "# config.md\n\n"
        "## 基本情報\n\n"
        "| 項目 | 内容 |\n"
        "|------|------|\n"
        f"{rows}\n"
    )


def test_append_skips_when_audit_log_off(tmp_path: Path) -> None:
    novel = tmp_path / "novels" / "001_sample"
    novel.mkdir(parents=True)
    (novel / "config.md").write_text(_config("| AUDIT_LOG | OFF |"), encoding="utf-8")
    log_dir = tmp_path / "_workingspace" / "log"
    log_dir.mkdir(parents=True)

    assert (
        main(
            [
                "--repo-root",
                str(tmp_path),
                "append",
                "--novel",
                str(novel),
                "--year-month",
                "202609",
                "should not be written",
            ]
        )
        == 0
    )
    assert not (log_dir / "202609.md").exists()


def test_append_force_writes_when_audit_log_off(tmp_path: Path) -> None:
    novel = tmp_path / "novels" / "001_sample"
    novel.mkdir(parents=True)
    (novel / "config.md").write_text(_config("| AUDIT_LOG | OFF |"), encoding="utf-8")

    assert (
        main(
            [
                "--repo-root",
                str(tmp_path),
                "append",
                "--novel",
                str(novel),
                "--force",
                "--year-month",
                "202609",
                "forced entry",
            ]
        )
        == 0
    )
    text = (tmp_path / "_workingspace" / "log" / "202609.md").read_text(encoding="utf-8")
    assert "forced entry" in text


def test_append_writes_when_novel_config_is_missing(tmp_path: Path) -> None:
    novel = tmp_path / "novels" / "001_sample"
    novel.mkdir(parents=True)

    assert (
        main(
            [
                "--repo-root",
                str(tmp_path),
                "append",
                "--novel",
                str(novel),
                "--year-month",
                "202609",
                "implicit on without config",
            ]
        )
        == 0
    )
    text = (tmp_path / "_workingspace" / "log" / "202609.md").read_text(encoding="utf-8")
    assert "implicit on without config" in text
