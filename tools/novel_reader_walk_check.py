#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Reader Walk の反応メタデータを検証し、山谷の trace を生成する。

Reader Walk の感想本文は自由記述のまま保ち、各場面の後ろに置く固定形式の
反応ブロックだけを機械的に扱う。ここで扱う数値は作品の評価点ではなく、
特定のペルソナがその場面で受けた反応の記録である。

終了コード:
  0  ERROR なし
  1  ERROR あり
  2  WARNING のみ（--allow-missing-reaction 使用時など）
  3  引数または対象ファイルエラー
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


FIELD_ORDER = (
    "scene_id",
    "persona_id",
    "session_id",
    "reaction_intensity",
    "reaction_valence",
    "reaction_tags",
    "continuation_pull",
)
VALID_VALENCES = ("positive", "negative", "mixed", "neutral")
TAG_ORDER = (
    "curiosity",
    "tension",
    "surprise",
    "joy",
    "relief",
    "sadness",
    "anger",
    "fear",
    "confusion",
    "boredom",
    "admiration",
)
TAG_INDEX = {tag: index for index, tag in enumerate(TAG_ORDER)}

_ENTRY_RE = re.compile(r"^##\s+(?!#)(?P<title>.+?)\s*$")
_FIELD_RE = re.compile(
    r"^- \*\*(?P<key>scene_id|persona_id|session_id|reaction_intensity|"
    r"reaction_valence|reaction_tags|continuation_pull)\*\*: `(?P<value>.*)`$"
)
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$")
_ANCHORED_SCENE_ID_RE = re.compile(r"^ch[0-9]{2}-[0-9]{3}$")
_FALLBACK_SCENE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]*-s[0-9]{3}$")


@dataclass(frozen=True)
class ReactionEntry:
    """A validated reaction block in journal order."""

    section_index: int
    line_number: int
    heading: str
    scene_id: str
    persona_id: str
    session_id: str
    reaction_intensity: int
    reaction_valence: str
    reaction_tags: tuple[str, ...]
    continuation_pull: int


@dataclass(frozen=True)
class Issue:
    level: str
    line_number: int
    message: str


def _issue(level: str, line_number: int, message: str) -> Issue:
    return Issue(level=level, line_number=line_number, message=message)


def _parse_int(value: str, *, field: str, line_number: int) -> tuple[int | None, Issue | None]:
    try:
        parsed = int(value)
    except ValueError:
        return None, _issue("ERROR", line_number, f"{field} は整数で指定してください: {value!r}")
    if not 0 <= parsed <= 5:
        return None, _issue("ERROR", line_number, f"{field} は0〜5の範囲で指定してください: {parsed}")
    return parsed, None


def _parse_tags(value: str, line_number: int) -> tuple[tuple[str, ...] | None, Issue | None]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        return None, _issue("ERROR", line_number, f"reaction_tags はJSON配列で指定してください: {exc.msg}")

    if not isinstance(parsed, list):
        return None, _issue("ERROR", line_number, "reaction_tags はJSON配列で指定してください")
    if not 1 <= len(parsed) <= 3:
        return None, _issue("ERROR", line_number, "reaction_tags は1〜3個で指定してください")
    if any(not isinstance(tag, str) for tag in parsed):
        return None, _issue("ERROR", line_number, "reaction_tags の要素は文字列で指定してください")

    tags = tuple(parsed)
    unknown = [tag for tag in tags if tag not in TAG_INDEX]
    if unknown:
        return None, _issue("ERROR", line_number, f"reaction_tags に未定義の値があります: {', '.join(unknown)}")
    if len(set(tags)) != len(tags):
        return None, _issue("ERROR", line_number, "reaction_tags に重複があります")
    if tuple(sorted(tags, key=TAG_INDEX.__getitem__)) != tags:
        return None, _issue("ERROR", line_number, "reaction_tags は固定語彙表の順に並べてください")
    return tags, None


def _sections(lines: list[str]) -> list[tuple[int, str, list[str]]]:
    starts = [(index, match.group("title")) for index, line in enumerate(lines) if (match := _ENTRY_RE.match(line))]
    sections: list[tuple[int, str, list[str]]] = []
    for position, (start, heading) in enumerate(starts):
        end = starts[position + 1][0] if position + 1 < len(starts) else len(lines)
        sections.append((start, heading, lines[start + 1 : end]))
    return sections


def _parse_entry(
    section_index: int,
    start_line: int,
    heading: str,
    body: list[str],
    *,
    allow_missing_reaction: bool,
) -> tuple[ReactionEntry | None, list[Issue]]:
    issues: list[Issue] = []
    fields: list[tuple[int, str, str]] = []
    for offset, line in enumerate(body):
        match = _FIELD_RE.match(line)
        if match:
            fields.append((start_line + offset + 2, match.group("key"), match.group("value")))

    if not fields:
        level = "WARNING" if allow_missing_reaction else "ERROR"
        issues.append(_issue(level, start_line + 1, "反応ブロックがありません"))
        return None, issues

    first_offset = next((index for index, field in enumerate(fields) if field[1] == FIELD_ORDER[0]), None)
    if first_offset is None:
        issues.append(_issue("ERROR", fields[0][0], "反応ブロックは scene_id から始めてください"))
        return None, issues

    if first_offset > 0:
        issues.append(_issue("ERROR", fields[0][0], "reaction ブロックの前に不要な固定フィールドがあります"))

    block = fields[first_offset : first_offset + len(FIELD_ORDER)]
    if len(block) != len(FIELD_ORDER):
        issues.append(_issue("ERROR", fields[first_offset][0], "反応ブロックの必須フィールドが不足しています"))
        return None, issues

    for (line_number, actual_key, _), expected_key in zip(block, FIELD_ORDER):
        if actual_key != expected_key:
            issues.append(
                _issue(
                    "ERROR",
                    line_number,
                    f"反応ブロックの順序が不正です（期待: {expected_key}, 実際: {actual_key}）",
                )
            )

    if len(fields) != len(FIELD_ORDER):
        issues.append(_issue("ERROR", fields[-1][0], "反応ブロックに重複または未知の固定フィールドがあります"))
    if issues:
        return None, issues

    values = {key: value for _, key, value in block}
    scene_id = values["scene_id"]
    if not (_ANCHORED_SCENE_ID_RE.fullmatch(scene_id) or _FALLBACK_SCENE_ID_RE.fullmatch(scene_id)):
        issues.append(
            _issue(
                "ERROR",
                block[0][0],
                "scene_id は chNN-MMM または source_file_stem-sNNN の形式で指定してください",
            )
        )
    for key in ("scene_id", "persona_id", "session_id"):
        if not _ID_RE.fullmatch(values[key]):
            issues.append(_issue("ERROR", block[FIELD_ORDER.index(key)][0], f"{key} の形式が不正です: {values[key]!r}"))

    intensity, intensity_issue = _parse_int(
        values["reaction_intensity"], field="reaction_intensity", line_number=block[3][0]
    )
    if intensity_issue:
        issues.append(intensity_issue)
    pull, pull_issue = _parse_int(
        values["continuation_pull"], field="continuation_pull", line_number=block[6][0]
    )
    if pull_issue:
        issues.append(pull_issue)

    valence = values["reaction_valence"]
    if valence not in VALID_VALENCES:
        issues.append(_issue("ERROR", block[4][0], f"reaction_valence が未定義です: {valence!r}"))

    tags, tags_issue = _parse_tags(values["reaction_tags"], block[5][0])
    if tags_issue:
        issues.append(tags_issue)

    if issues or intensity is None or pull is None or tags is None:
        return None, issues

    return (
        ReactionEntry(
            section_index=section_index,
            line_number=start_line + 1,
            heading=heading,
            scene_id=values["scene_id"],
            persona_id=values["persona_id"],
            session_id=values["session_id"],
            reaction_intensity=intensity,
            reaction_valence=valence,
            reaction_tags=tags,
            continuation_pull=pull,
        ),
        issues,
    )


def parse_journal(text: str, *, allow_missing_reaction: bool = False) -> tuple[list[ReactionEntry], list[Issue]]:
    """Parse and validate all reaction blocks in a journal."""
    lines = text.splitlines()
    sections = _sections(lines)
    if not sections:
        return [], [_issue("ERROR", 1, "## の Reader Walk 場面エントリが見つかりません")]

    entries: list[ReactionEntry] = []
    issues: list[Issue] = []
    for section_index, (start_line, heading, body) in enumerate(sections):
        entry, entry_issues = _parse_entry(
            section_index,
            start_line,
            heading,
            body,
            allow_missing_reaction=allow_missing_reaction,
        )
        issues.extend(entry_issues)
        if entry is not None:
            entries.append(entry)

    seen: dict[tuple[str, str, str], ReactionEntry] = {}
    for entry in entries:
        key = (entry.session_id, entry.persona_id, entry.scene_id)
        previous = seen.get(key)
        if previous is not None:
            issues.append(
                _issue(
                    "ERROR",
                    entry.line_number,
                    "同一(session_id, persona_id, scene_id)の反応が重複しています。再読はsession_idを変えてください",
                )
            )
        else:
            seen[key] = entry
    return entries, issues


def _trend(previous: int | None, current: int) -> str | None:
    if previous is None:
        return None
    delta = current - previous
    if delta >= 1:
        return "rising"
    if delta <= -1:
        return "falling"
    return "flat"


def _is_peak(values: list[int], index: int) -> bool:
    value = values[index]
    if value < 4:
        return False
    previous = values[index - 1] if index > 0 else None
    following = values[index + 1] if index + 1 < len(values) else None
    if previous is not None and value < previous:
        return False
    if following is not None and value < following:
        return False
    # 同点の山は連続区間の先頭だけを採用する。
    if previous is not None and value == previous:
        return False
    return True


def build_trace(entries: list[ReactionEntry]) -> list[dict[str, Any]]:
    """Build a trace grouped by session/persona and ordered by journal occurrence."""
    groups: dict[tuple[str, str], list[ReactionEntry]] = {}
    for entry in entries:
        groups.setdefault((entry.session_id, entry.persona_id), []).append(entry)

    trace: list[dict[str, Any]] = []
    for (session_id, persona_id), grouped in groups.items():
        values = [entry.reaction_intensity for entry in grouped]
        previous: int | None = None
        for index, entry in enumerate(grouped):
            delta = None if previous is None else entry.reaction_intensity - previous
            trace.append(
                {
                    "session_id": session_id,
                    "persona_id": persona_id,
                    "scene_id": entry.scene_id,
                    "reaction_intensity": entry.reaction_intensity,
                    "reaction_valence": entry.reaction_valence,
                    "reaction_tags": list(entry.reaction_tags),
                    "continuation_pull": entry.continuation_pull,
                    "delta": delta,
                    "trend": _trend(previous, entry.reaction_intensity),
                    "peak": _is_peak(values, index),
                }
            )
            previous = entry.reaction_intensity
    return trace


def validate_file(path: Path, *, allow_missing_reaction: bool = False) -> tuple[list[ReactionEntry], list[Issue]]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [], [_issue("ERROR", 1, f"ファイルを読み込めません: {exc}")]
    except UnicodeError as exc:
        return [], [_issue("ERROR", 1, f"UTF-8として読み込めません: {exc}")]
    return parse_journal(text, allow_missing_reaction=allow_missing_reaction)


def _resolve_journal(target: Path) -> Path:
    if target.is_dir():
        return target / "journal.md"
    return target


def _print_issues(issues: list[Issue]) -> None:
    for issue in issues:
        print(f"{issue.level}: L{issue.line_number}: {issue.message}")


def _write_trace(path: Path, trace: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(trace, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Reader Walk反応ブロックを検証し、山谷traceを生成する")
    parser.add_argument("target", type=Path, help="journal.md または walk ディレクトリ")
    parser.add_argument(
        "--allow-missing-reaction",
        action="store_true",
        help="反応ブロックのない既存エントリをWARNINGとして許容する",
    )
    parser.add_argument(
        "--trace-output",
        type=Path,
        help="検証成功後にreaction trace JSONを書き出すパス",
    )
    parser.add_argument("--json", action="store_true", help="結果概要をJSONで出力する")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    journal = _resolve_journal(args.target)
    if not journal.is_file():
        print(f"ERROR: 対象journal.mdが見つかりません: {journal}", file=sys.stderr)
        return 3

    entries, issues = validate_file(journal, allow_missing_reaction=args.allow_missing_reaction)
    errors = [issue for issue in issues if issue.level == "ERROR"]
    warnings = [issue for issue in issues if issue.level == "WARNING"]
    trace = build_trace(entries) if not errors else []
    if args.trace_output and not errors:
        _write_trace(args.trace_output, trace)

    summary = {
        "journal": str(journal),
        "entries": len(entries),
        "errors": len(errors),
        "warnings": len(warnings),
        "trace_entries": len(trace),
        "trace_output": str(args.trace_output) if args.trace_output and not errors else None,
    }
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        _print_issues(issues)
        status = "OK" if not errors and not warnings else ("WARNING" if not errors else "ERROR")
        print(f"{status}: {len(entries)} entries, {len(errors)} errors, {len(warnings)} warnings")
        if args.trace_output and not errors:
            print(f"trace: {args.trace_output}")

    if errors:
        return 1
    if warnings:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
