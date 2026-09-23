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

from novel_reader_walk_check import JournalHeader, build_trace, main, parse_journal  # noqa: E402

FIXTURE = ROOT / "tools" / "tests" / "fixtures" / "reader_walk" / "reaction_sample.md"
SESSION_FIXTURE = ROOT / "tools" / "tests" / "fixtures" / "reader_walk" / "walk" / "session_s1"


def _header(persona_id: str = "000_default", session_id: str = "s1") -> str:
    return f"- **persona_id**: `{persona_id}`\n- **session_id**: `{session_id}`"


def _reaction_line(
    scene_id: str,
    intensity: int,
    valence: str = "mixed",
    tags: list[str] | None = None,
    pull: int = 4,
) -> str:
    tags = tags or ["curiosity"]
    return f"反応: scene={scene_id} / intensity={intensity} / valence={valence} / tags={','.join(tags)} / pull={pull}"


def _write_session_journal(
    tmp_path: Path,
    dir_name: str,
    *lines: str,
    persona_id: str = "000_default",
    header_session_id: str | None = None,
    include_header: bool = True,
) -> tuple[Path, Path]:
    """Write a session journal under a proper ``walk/<dir_name>/`` layout."""
    session_dir = tmp_path / "walk" / dir_name
    session_dir.mkdir(parents=True)
    journal = session_dir / "journal.md"
    session_id = dir_name if header_session_id is None else header_session_id
    header = (_header(persona_id, session_id) + "\n\n") if include_header else ""
    body = "\n\n".join(f"## scene {index}\n\n{line}" for index, line in enumerate(lines, start=1))
    journal.write_text("# Reader Walk ジャーナル\n\n" + header + body + "\n", encoding="utf-8")
    return session_dir, journal


def test_parse_and_trace_respects_journal_order() -> None:
    header, entries, issues = parse_journal(FIXTURE.read_text(encoding="utf-8"))

    assert issues == []
    assert header == JournalHeader(persona_id="000_default", session_id="s1")
    assert len(entries) == 4

    trace = build_trace(header, entries)
    assert [row["session_id"] for row in trace] == ["s1"] * 4
    assert [row["persona_id"] for row in trace] == ["000_default"] * 4
    assert [row["trend"] for row in trace] == [None, "rising", "flat", "falling"]
    assert [row["peak"] for row in trace] == [False, True, False, False]


def test_missing_reaction_is_error_by_default_and_warning_when_allowed() -> None:
    journal = "# Reader Walk ジャーナル\n\n" + _header() + "\n\n## ch01-001\n\n感想だけ。\n"

    header, entries, issues = parse_journal(journal)
    assert header == JournalHeader(persona_id="000_default", session_id="s1")
    assert entries == []
    assert [(issue.level, issue.message) for issue in issues] == [("ERROR", "反応行がありません")]

    _, entries_allowed, issues_allowed = parse_journal(journal, allow_missing_reaction=True)
    assert entries_allowed == []
    assert [(issue.level, issue.message) for issue in issues_allowed] == [("WARNING", "反応行がありません")]


def test_missing_header_is_rejected() -> None:
    journal = "# Reader Walk ジャーナル\n\n## ch01-001\n\n感想だけ。\n\n" + _reaction_line("ch01-001", 3) + "\n"

    header, _, issues = parse_journal(journal)
    assert header is None
    assert any("persona_id / session_id ヘッダがありません" in issue.message for issue in issues)


def test_invalid_tag_order_is_rejected() -> None:
    line = _reaction_line("ch01-001", 3, tags=["tension", "curiosity"])
    journal = "# Reader Walk ジャーナル\n\n" + _header() + "\n\n## one\n\n" + line + "\n"

    _, entries, issues = parse_journal(journal)
    assert entries == []
    assert any("固定語彙表の順" in issue.message for issue in issues)


def test_deterministic_fallback_scene_id_is_accepted() -> None:
    line = _reaction_line("novel_text01-s001", 3)
    journal = "# Reader Walk ジャーナル\n\n" + _header() + "\n\n## one\n\n" + line + "\n"

    _, entries, issues = parse_journal(journal)
    assert issues == []
    assert entries[0].scene_id == "novel_text01-s001"


@pytest.mark.parametrize(
    ("line", "message_fragment"),
    [
        (_reaction_line("badscene", 3), "scene_id は chNN-MMM"),
        (_reaction_line("ch01-001", 6), "reaction_intensity は0〜5"),
        (_reaction_line("ch01-001", 3, valence="unknown"), "reaction_valence が未定義"),
        (_reaction_line("ch01-001", 3, pull=7), "continuation_pull は0〜5"),
    ],
)
def test_scalar_schema_constraints_are_rejected(line: str, message_fragment: str) -> None:
    journal = "# Reader Walk ジャーナル\n\n" + _header() + "\n\n## one\n\n" + line + "\n"

    _, entries, issues = parse_journal(journal)
    assert entries == []
    assert any(message_fragment in issue.message for issue in issues)


def test_malformed_reaction_line_is_rejected() -> None:
    missing_field = (
        "# Reader Walk ジャーナル\n\n"
        + _header()
        + "\n\n## missing\n\n反応: scene=ch01-001 / intensity=3 / valence=mixed / pull=4\n"
    )
    _, _, missing_issues = parse_journal(missing_field)
    assert any("反応行の形式が不正です" in issue.message for issue in missing_issues)

    wrong_order = (
        "# Reader Walk ジャーナル\n\n"
        + _header()
        + "\n\n## wrong order\n\n反応: intensity=3 / scene=ch01-001 / valence=mixed / tags=curiosity / pull=4\n"
    )
    _, _, order_issues = parse_journal(wrong_order)
    assert any("反応行の形式が不正です" in issue.message for issue in order_issues)


def test_multiple_reaction_lines_in_one_section_are_rejected() -> None:
    journal = (
        "# Reader Walk ジャーナル\n\n"
        + _header()
        + "\n\n## one\n\n"
        + _reaction_line("ch01-001", 3)
        + "\n"
        + _reaction_line("ch01-001", 4)
        + "\n"
    )

    _, entries, issues = parse_journal(journal)
    assert entries == []
    assert any("反応行が複数あります" in issue.message for issue in issues)


def test_duplicate_observation_is_rejected() -> None:
    journal = (
        "# Reader Walk ジャーナル\n\n"
        + _header()
        + "\n\n## one\n\n"
        + _reaction_line("ch01-001", 3)
        + "\n\n## two\n\n"
        + _reaction_line("ch01-001", 4)
        + "\n"
    )

    _, entries, issues = parse_journal(journal)
    assert len(entries) == 2
    assert any("scene_idが重複しています" in issue.message for issue in issues)


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
    sections = [
        f"## scene {index}\n\n" + _reaction_line(f"ch01-{index:03d}", value)
        for index, value in enumerate(values, start=1)
    ]
    journal = "# Reader Walk ジャーナル\n\n" + _header() + "\n\n" + "\n\n".join(sections)

    header, entries, issues = parse_journal(journal)
    assert issues == []
    trace = build_trace(header, entries)
    assert [row["peak"] for row in trace] == expected_peaks


def test_cli_json_and_trace_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    trace_path = tmp_path / "reaction_trace.json"

    exit_code = main([str(SESSION_FIXTURE), "--trace-output", str(trace_path), "--json"])

    assert exit_code == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["entries"] == 4
    assert summary["errors"] == 0
    assert summary["warnings"] == 0
    assert summary["trace_entries"] == 4
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
            str(SESSION_FIXTURE),
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
    assert json.loads(output)["trace_entries"] == 4
    assert trace_path.is_file()


def test_cli_warning_exit_code_for_legacy_entries(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    session_dir = tmp_path / "walk" / "s1"
    session_dir.mkdir(parents=True)
    journal_path = session_dir / "journal.md"
    journal_path.write_text(
        "# Reader Walk ジャーナル\n\n" + _header() + "\n\n## ch01-001\n\n感想だけ。\n",
        encoding="utf-8",
    )

    exit_code = main([str(journal_path), "--allow-missing-reaction", "--json"])

    assert exit_code == 2
    summary = json.loads(capsys.readouterr().out)
    assert summary["errors"] == 0
    assert summary["warnings"] == 1


def test_cli_error_does_not_write_trace(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    session_dir = tmp_path / "walk" / "s1"
    session_dir.mkdir(parents=True)
    journal_path = session_dir / "journal.md"
    trace_path = tmp_path / "reaction_trace.json"
    journal_path.write_text(
        "# Reader Walk ジャーナル\n\n" + _header() + "\n\n## invalid\n\n" + _reaction_line("badscene", 3) + "\n",
        encoding="utf-8",
    )

    exit_code = main([str(journal_path), "--trace-output", str(trace_path)])

    assert exit_code == 1
    assert "scene_id は chNN-MMM" in capsys.readouterr().out
    assert not trace_path.exists()


def test_cli_missing_target_exit_code(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main([str(tmp_path / "walk" / "s1" / "journal.md")])

    assert exit_code == 3
    assert "対象journal.mdが見つかりません" in capsys.readouterr().err


def test_session_directory_and_journal_targets_are_supported(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    session_dir, journal = _write_session_journal(tmp_path, "s1", _reaction_line("ch01-001", 3))

    assert main([str(session_dir), "--json"]) == 0
    directory_summary = json.loads(capsys.readouterr().out)
    assert directory_summary["entries"] == 1

    assert main([str(journal), "--json"]) == 0
    journal_summary = json.loads(capsys.readouterr().out)
    assert journal_summary["entries"] == 1


def test_session_directory_name_must_match_session_id(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    session_dir, _ = _write_session_journal(
        tmp_path,
        "s1",
        _reaction_line("ch01-001", 3),
        header_session_id="s2",
    )

    assert main([str(session_dir)]) == 1
    assert "ディレクトリ名とsession_idが一致しません" in capsys.readouterr().out


def test_directory_not_under_walk_is_rejected(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    session_dir = tmp_path / "s1"
    session_dir.mkdir()
    (session_dir / "journal.md").write_text(
        "# Reader Walk ジャーナル\n\n" + _header() + "\n\n## scene one\n\n" + _reaction_line("ch01-001", 3) + "\n",
        encoding="utf-8",
    )

    assert main([str(session_dir)]) == 1
    assert "walk/<session_id>/ またはその journal.md" in capsys.readouterr().err


def test_journal_file_not_under_walk_is_rejected(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    session_dir = tmp_path / "s1"
    session_dir.mkdir()
    journal = session_dir / "journal.md"
    journal.write_text(
        "# Reader Walk ジャーナル\n\n" + _header() + "\n\n## scene one\n\n" + _reaction_line("ch01-001", 3) + "\n",
        encoding="utf-8",
    )

    assert main([str(journal)]) == 1
    assert "walk/<session_id>/journal.md" in capsys.readouterr().err


def test_non_journal_filename_is_rejected(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    session_dir = tmp_path / "walk" / "s1"
    session_dir.mkdir(parents=True)
    notes = session_dir / "notes.md"
    notes.write_text("# Reader Walk ジャーナル\n\n" + _header() + "\n", encoding="utf-8")

    assert main([str(notes)]) == 1
    assert "journal.md である必要があります" in capsys.readouterr().err


def test_legacy_root_requires_explicit_flag(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    walk_dir = tmp_path / "walk"
    walk_dir.mkdir()
    journal = walk_dir / "journal.md"
    journal.write_text(
        "# Reader Walk ジャーナル\n\n" + _header() + "\n\n## scene one\n\n" + _reaction_line("ch01-001", 3) + "\n",
        encoding="utf-8",
    )

    assert main([str(walk_dir)]) == 1
    assert "--legacy-root" in capsys.readouterr().err

    assert main([str(walk_dir), "--legacy-root", "--json"]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["entries"] == 1


def test_adjacent_session_directories_are_not_merged(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    walk_dir = tmp_path / "walk"
    first_dir = walk_dir / "s1"
    second_dir = walk_dir / "s2"
    first_dir.mkdir(parents=True)
    second_dir.mkdir()
    for session_dir, session_id in ((first_dir, "s1"), (second_dir, "s2")):
        (session_dir / "journal.md").write_text(
            "# Reader Walk ジャーナル\n\n"
            + _header(session_id=session_id)
            + "\n\n## scene one\n\n"
            + _reaction_line("ch01-001", 3)
            + "\n",
            encoding="utf-8",
        )
    trace_path = first_dir / "reaction_trace.json"

    assert main([str(first_dir), "--trace-output", str(trace_path), "--json"]) == 0
    summary = json.loads(capsys.readouterr().out)
    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    assert summary["entries"] == 1
    assert [row["session_id"] for row in trace] == ["s1"]
