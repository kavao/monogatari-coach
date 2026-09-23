"""作品単位の METRON / CHRONOS / AUDIT_LOG フラグを読む。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
import re


class InspectionConfigError(ValueError):
    """config.md の検査レイヤ設定が読み取れない。"""


class InspectionFlag(str, Enum):
    ON = "ON"
    OFF = "OFF"


DEFAULT_OFF_KEYS = ("METRON", "CHRONOS")
DEFAULT_ON_KEYS = ("AUDIT_LOG",)
FLAG_KEYS = DEFAULT_OFF_KEYS + DEFAULT_ON_KEYS
_BASIC_INFO_HEADING_RE = re.compile(r"^##[ \t]+基本情報[ \t]*$")
_ANY_HEADING_RE = re.compile(r"^#{1,6}(?:[ \t]+|$)")
_SEPARATOR_CELL_RE = re.compile(r"^:?-{3,}:?$")


@dataclass(frozen=True)
class InspectionFlags:
    """作品の検査・記録フラグと、表に明示されたキーを保持する。"""

    metron: InspectionFlag = InspectionFlag.OFF
    chronos: InspectionFlag = InspectionFlag.OFF
    audit_log: InspectionFlag = InspectionFlag.ON
    explicit: frozenset[str] = field(default_factory=frozenset)
    source: str = "implicit"

    def value_for(self, key: str) -> InspectionFlag:
        if key == "METRON":
            return self.metron
        if key == "CHRONOS":
            return self.chronos
        if key == "AUDIT_LOG":
            return self.audit_log
        raise KeyError(key)

    def is_explicit(self, key: str) -> bool:
        return key in self.explicit

    def as_dict(self) -> dict[str, object]:
        return {
            "METRON": self.metron.value,
            "CHRONOS": self.chronos.value,
            "AUDIT_LOG": self.audit_log.value,
            "explicit": sorted(self.explicit),
            "source": self.source,
        }


def should_append_audit_log(config_path: str | Path) -> bool:
    """対象作品の査証ログを自動追記してよいか。行なしは ON。"""

    return load_inspection_flags(config_path).audit_log is InspectionFlag.ON


def load_inspection_flags(config_path: str | Path) -> InspectionFlags:
    """config.md からフラグを読む。ファイルまたは行がなければ METRON / CHRONOS は OFF、AUDIT_LOG は ON。"""

    path = Path(config_path)
    if not path.exists():
        return InspectionFlags(source="implicit:missing-config")
    if not path.is_file():
        raise InspectionConfigError(f"config.md is not a file: {path}")
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as error:
        raise InspectionConfigError(f"config.md could not be read: {path}: {error}") from error
    return parse_inspection_flags(text, source=str(path))


def parse_inspection_flags(text: str, *, source: str = "config.md") -> InspectionFlags:
    """`## 基本情報` の最初の Markdown 表からフラグを読む。"""

    lines = text.splitlines()
    table_rows = _basic_info_table_rows(lines)
    values: dict[str, InspectionFlag] = {}
    for cells in table_rows:
        if not cells:
            continue
        key = cells[0]
        normalized_key = key.upper()
        if normalized_key not in FLAG_KEYS:
            continue
        if key != normalized_key:
            raise InspectionConfigError(
                f"inspection flag key must be uppercase {normalized_key}: {key!r}"
            )
        if len(cells) != 2:
            raise InspectionConfigError(
                f"inspection flag row must have exactly 2 columns: {key}"
            )
        if key in values:
            raise InspectionConfigError(f"duplicate inspection flag: {key}")
        value = cells[1]
        if value not in (InspectionFlag.ON.value, InspectionFlag.OFF.value):
            raise InspectionConfigError(
                f"unknown value for {key}: {value!r} (expected ON or OFF)"
            )
        values[key] = InspectionFlag(value)

    return InspectionFlags(
        metron=values.get("METRON", InspectionFlag.OFF),
        chronos=values.get("CHRONOS", InspectionFlag.OFF),
        audit_log=values.get("AUDIT_LOG", InspectionFlag.ON),
        explicit=frozenset(values),
        source=source if values else "implicit:no-flag-row",
    )


def _basic_info_table_rows(lines: list[str]) -> list[list[str]]:
    heading_index = next(
        (index for index, line in enumerate(lines) if _BASIC_INFO_HEADING_RE.match(line)),
        None,
    )
    if heading_index is None:
        return []

    section_end = len(lines)
    for index in range(heading_index + 1, len(lines)):
        if _ANY_HEADING_RE.match(lines[index]):
            section_end = index
            break

    header_index: int | None = None
    for index in range(heading_index + 1, section_end - 1):
        header = _split_table_row(lines[index])
        separator = _split_table_row(lines[index + 1])
        if header is not None and separator is not None and _is_separator_row(separator):
            header_index = index
            break
    if header_index is None:
        return []

    rows: list[list[str]] = []
    for line in lines[header_index + 2 : section_end]:
        cells = _split_table_row(line)
        if cells is None:
            break
        rows.append(cells)
    return rows


def _split_table_row(line: str) -> list[str] | None:
    stripped = line.strip()
    if not (stripped.startswith("|") and stripped.endswith("|")):
        return None
    cells = [cell.strip() for cell in stripped[1:-1].split("|")]
    return cells if len(cells) >= 2 else None


def _is_separator_row(cells: list[str]) -> bool:
    return all(_SEPARATOR_CELL_RE.fullmatch(cell) for cell in cells)
