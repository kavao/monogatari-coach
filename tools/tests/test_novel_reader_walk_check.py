#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import locale
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from novel_reader_walk_check import build_trace, main, parse_journal  # noqa: E402

FIXTURE = ROOT / "tools" / "tests" / "fixtures" / "reader_walk" / "reaction_sample.md"


def _block(
    scene_id: str,
    persona_id: str,
    session_id: str,
    intensity: int,
    valence: str = "mixed",
    tags: list[str] | None = None,
    pull: int = 4,
) -> str:
    tags = tags or ["curiosity"]
    tags_json = json.dumps(tags, ensure_ascii=False)
    return "\n".join(
        [
            f"- **scene_id**: `{scene_id}`",
            f"- **persona_id**: `{persona_id}`",
            f"- **session_id**: `{session_id}`",
            f"- **reaction_intensity**: `{intensity}`",
            f"- **reaction_valence**: `{valence}`",
            f"- **reaction_tags**: `{tags_json}`",
            f"- **continuation_pull**: `{pull}`",
        ]
    )


def test_parse_and_trace_separate_personas_and_sessions() -> None:
    entries, issues = parse_journal(FIXTURE.read_text(encoding="utf-8"))

    assert issues == []
    assert len(entries) == 5

    trace = build_trace(entries)
    default = [row for row in trace if row["persona_id"] == "000_default"]
    calm = [row for row in trace if row["persona_id"] == "001_calm"]

    assert [row["trend"] for row in default] == [None, "rising", "flat", "falling"]
    assert [row["peak"] for row in default] == [False, True, False, False]
    assert calm[0]["trend"] is None
    assert calm[0]["peak"] is True


def test_missing_reaction_is_error_by_default_and_warning_when_allowed() -> None:
    journal = "# Reader Walk ジャーナル\n\n## ch01-001\n\n感想だけ。\n"

    entries, issues = parse_journal(journal)
    assert entries == []
    assert [(issue.level, issue.message) for issue in issues] == [("ERROR", "反応ブロックがありません")]

    entries_allowed, issues_allowed = parse_journal(journal, allow_missing_reaction=True)
    assert entries_allowed == []
    assert [(issue.level, issue.message) for issue in issues_allowed] == [("WARNING", "反応ブロックがありません")]


def test_invalid_tag_order_is_rejected() -> None:
    block = _block("ch01-001", "000_default", "s1", 3, tags=["tension", "curiosity"])
    journal = f"# Reader Walk ジャーナル\n\n## one\n\n{block}\n"

    entries, issues = parse_journal(journal)
    assert entries == []
    assert any("固定語彙表の順" in issue.message for issue in issues)


def test_deterministic_fallback_scene_id_is_accepted() -> None:
    journal = (
        "# Reader Walk ジャーナル\n\n## one\n\n"
        + _block("novel_text01-s001", "000_default", "s1", 3)
        + "\n"
    )

    entries, issues = parse_journal(journal)
    assert issues == []
    assert entries[0].scene_id == "novel_text01-s001"


@pytest.mark.parametrize(
    ("block", "message_fragment"),
    [
        (_block("scene one", "000_default", "s1", 3), "scene_id の形式"),
        (_block("ch01-001", "000_default", "s1", 6), "reaction_intensity は0〜5"),
        (_block("ch01-001", "000_default", "s1", 3, valence="unknown"), "reaction_valence が未定義"),
        (_block("ch01-001", "000_default", "s1", 3, pull=7), "continuation_pull は0〜5"),
    ],
)
def test_scalar_schema_constraints_are_rejected(block: str, message_fragment: str) -> None:
    journal = f"# Reader Walk ジャーナル\n\n## one\n\n{block}\n"

    entries, issues = parse_journal(journal)
    assert entries == []
    assert any(message_fragment in issue.message for issue in issues)


def test_missing_field_and_wrong_order_are_rejected() -> None:
    fields = _block("ch01-001", "000_default", "s1", 3).splitlines()
    fields.pop(5)
    missing = "# Reader Walk ジャーナル\n\n## missing\n\n" + "\n".join(fields)
    _, missing_issues = parse_journal(missing)
    assert any("必須フィールドが不足" in issue.message for issue in missing_issues)

    fields = _block("ch01-001", "000_default", "s1", 3).splitlines()
    fields[0], fields[1] = fields[1], fields[0]
    wrong_order = "# Reader Walk ジャーナル\n\n## wrong order\n\n" + "\n".join(fields)
    _, order_issues = parse_journal(wrong_order)
    assert any("不要な固定フィールド" in issue.message for issue in order_issues)


def test_duplicate_observation_is_rejected() -> None:
    block = _block("ch01-001", "000_default", "s1", 3)
    duplicate = _block("ch01-001", "000_default", "s1", 4)
    journal = f"# Reader Walk ジャーナル\n\n## one\n\n{block}\n\n## two\n\n{duplicate}\n"

    entries, issues = parse_journal(journal)
    assert len(entries) == 2
    assert any("同一(session_id, persona_id, scene_id)" in issue.message for issue in issues)


@pytest.mark.parametrize(
    ("values", "expected_peaks"),
    [
        ([2, 4, 5], [False, False, True]),  # 単調増加の末尾
        ([5, 4, 2], [True, False, False]),  # 単調減少の先頭
        ([5, 5, 3], [True, False, False]),  # 同点は先の場面
        ([3, 5, 3], [False, True, False]),  # 通常の局所最大
        ([2, 3, 2], [False, False, False]),  # 4未満の局所最大
        ([4], [True]),  # 1場面だけの範囲
    ],
)
def test_peak_boundary_rules(values: list[int], expected_peaks: list[bool]) -> None:
    blocks = [
        f"## scene {index}\n\n" + _block(f"ch01-{index:03d}", "000_default", "s1", value)
        for index, value in enumerate(values, start=1)
    ]
    entries, issues = parse_journal("# Reader Walk ジャーナル\n\n" + "\n\n".join(blocks))

    assert issues == []
    trace = build_trace(entries)
    assert [row["peak"] for row in trace] == expected_peaks


def test_cli_json_and_trace_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    trace_path = tmp_path / "reaction_trace.json"

    exit_code = main([str(FIXTURE), "--trace-output", str(trace_path), "--json"])

    assert exit_code == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["entries"] == 5
    assert summary["errors"] == 0
    assert summary["warnings"] == 0
    assert summary["trace_entries"] == 5
    assert summary["trace_output"] == str(trace_path)
    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    assert trace[1]["trend"] == "rising"
    assert trace[1]["peak"] is True


def test_cli_process_returns_zero_and_writes_trace(tmp_path: Path) -> None:
    trace_path = tmp_path / "reaction_trace.json"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "novel_reader_walk_check.py"),
            str(FIXTURE),
            "--trace-output",
            str(trace_path),
            "--json",
        ],
        capture_output=True,
        check=False,
        cwd=ROOT,
    )

    assert result.returncode == 0
    output = result.stdout.decode(locale.getpreferredencoding(False))
    assert json.loads(output)["trace_entries"] == 5
    assert trace_path.is_file()


def test_cli_warning_exit_code_for_legacy_entries(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    journal_path = tmp_path / "journal.md"
    journal_path.write_text("# Reader Walk ジャーナル\n\n## ch01-001\n\n感想だけ。\n", encoding="utf-8")

    exit_code = main([str(journal_path), "--allow-missing-reaction", "--json"])

    assert exit_code == 2
    summary = json.loads(capsys.readouterr().out)
    assert summary["errors"] == 0
    assert summary["warnings"] == 1


def test_cli_error_does_not_write_trace(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    journal_path = tmp_path / "journal.md"
    trace_path = tmp_path / "reaction_trace.json"
    journal_path.write_text(
        "# Reader Walk ジャーナル\n\n## invalid\n\n"
        + _block("scene_one", "000_default", "s1", 3)
        + "\n",
        encoding="utf-8",
    )

    exit_code = main([str(journal_path), "--trace-output", str(trace_path)])

    assert exit_code == 1
    assert "scene_id は chNN-MMM" in capsys.readouterr().out
    assert not trace_path.exists()


def test_cli_missing_target_exit_code(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main([str(tmp_path / "missing.md")])

    assert exit_code == 3
    assert "対象journal.mdが見つかりません" in capsys.readouterr().err
