from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from inspection_flags import (  # noqa: E402
    InspectionConfigError,
    InspectionFlag,
    load_inspection_flags,
    parse_inspection_flags,
    should_append_audit_log,
)


def _config(rows: str, *, outside: str = "") -> str:
    return (
        "# config.md\n\n"
        "## 基本情報\n\n"
        "| 項目 | 内容 |\n"
        "|------|------|\n"
        f"{rows}\n\n"
        "## キーワード\n\n"
        f"{outside}\n"
    )


def test_missing_rows_are_implicit_off() -> None:
    flags = parse_inspection_flags(_config("| novel_ID | 001 |"))

    assert flags.metron is InspectionFlag.OFF
    assert flags.chronos is InspectionFlag.OFF
    assert flags.audit_log is InspectionFlag.ON
    assert flags.explicit == frozenset()


def test_reads_independent_flags_from_basic_info_table() -> None:
    flags = parse_inspection_flags(
        _config("| METRON | ON |\n| CHRONOS | OFF |\n| AUDIT_LOG | OFF |")
    )

    assert flags.metron is InspectionFlag.ON
    assert flags.chronos is InspectionFlag.OFF
    assert flags.audit_log is InspectionFlag.OFF
    assert flags.explicit == frozenset({"METRON", "CHRONOS", "AUDIT_LOG"})


def test_ignores_flag_text_outside_basic_info_table() -> None:
    flags = parse_inspection_flags(
        _config("| novel_ID | 001 |", outside="METRON: ON")
    )

    assert flags.metron is InspectionFlag.OFF
    assert flags.chronos is InspectionFlag.OFF


def test_missing_basic_info_heading_is_implicit_off() -> None:
    flags = parse_inspection_flags(
        "# config.md\n\n| METRON | ON |\n| CHRONOS | ON |\n"
    )

    assert flags.metron is InspectionFlag.OFF
    assert flags.chronos is InspectionFlag.OFF
    assert flags.audit_log is InspectionFlag.ON
    assert flags.explicit == frozenset()


@pytest.mark.parametrize(
    "rows",
    [
        "| METRON | Yes |",
        "| CHRONOS | true |",
        "| METRON | オン |",
        "| METRON | ON | extra |",
    ],
)
def test_invalid_flag_value_or_shape_is_an_error(rows: str) -> None:
    with pytest.raises(InspectionConfigError):
        parse_inspection_flags(_config(rows))


def test_duplicate_flag_is_an_error() -> None:
    with pytest.raises(InspectionConfigError, match="duplicate"):
        parse_inspection_flags(_config("| METRON | ON |\n| METRON | OFF |"))


def test_noncanonical_flag_key_is_an_error_instead_of_implicit_off() -> None:
    with pytest.raises(InspectionConfigError, match="uppercase"):
        parse_inspection_flags(_config("| metron | ON |"))


def test_separator_variants_are_supported() -> None:
    flags = parse_inspection_flags(
        _config("| METRON | ON |\n| CHRONOS | OFF |").replace(
            "|------|------|", "| --- | :--- |"
        )
    )

    assert flags.metron is InspectionFlag.ON
    assert flags.chronos is InspectionFlag.OFF


def test_missing_config_file_is_implicit_off(tmp_path: Path) -> None:
    flags = load_inspection_flags(tmp_path / "config.md")

    assert flags.metron is InspectionFlag.OFF
    assert flags.audit_log is InspectionFlag.ON
    assert flags.source == "implicit:missing-config"


def test_audit_log_defaults_on_when_only_inspection_flags_are_set() -> None:
    flags = parse_inspection_flags(_config("| METRON | ON |\n| CHRONOS | ON |"))

    assert flags.audit_log is InspectionFlag.ON
    assert flags.is_explicit("AUDIT_LOG") is False


def test_should_append_audit_log_follows_explicit_off(tmp_path: Path) -> None:
    config = tmp_path / "config.md"
    config.write_text(_config("| AUDIT_LOG | OFF |"), encoding="utf-8")

    assert should_append_audit_log(config) is False
    assert should_append_audit_log(tmp_path / "missing.md") is True


def test_existing_non_file_config_is_an_error(tmp_path: Path) -> None:
    config = tmp_path / "config.md"
    config.mkdir()

    with pytest.raises(InspectionConfigError):
        load_inspection_flags(config)


def test_invalid_utf8_config_is_an_error(tmp_path: Path) -> None:
    config = tmp_path / "config.md"
    config.write_bytes(b"# config.md\n" + bytes([0x90]))

    with pytest.raises(InspectionConfigError, match="could not be read"):
        load_inspection_flags(config)
