#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Reader Walk の反応メタデータを検証し、山谷の trace を生成する。

Reader Walk の感想本文は自由記述のまま保ち、各場面の後ろに置く固定形式の
反応行だけを機械的に扱う。ここで扱う数値は作品の評価点ではなく、
特定のペルソナがその場面で受けた反応の記録である。

`persona_id` / `session_id` はセッションディレクトリ内で常に同一値のため、
ファイル冒頭のヘッダに1回だけ書き、場面ごとの反応行では繰り返さない
（詳細は `_workingspace/plans/20260830_reader-walk-reaction-readability.md`）。

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


HEADER_FIELD_ORDER = ("persona_id", "session_id")
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
_HEADER_FIELD_RE = re.compile(r"^- \*\*(?P<key>persona_id|session_id)\*\*: `(?P<value>.*)`$")
_REACTION_PREFIX = "反応:"
_REACTION_LINE_RE = re.compile(
    r"^反応: scene=(?P<scene>\S+) / intensity=(?P<intensity>\S+) / "
    r"valence=(?P<valence>\S+) / tags=(?P<tags>\S+) / pull=(?P<pull>\S+)$"
)
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$")
_ANCHORED_SCENE_ID_RE = re.compile(r"^ch[0-9]{2}-[0-9]{3}$")
_FALLBACK_SCENE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]*-s[0-9]{3}$")


@dataclass(frozen=True)
class JournalHeader:
    """The persona/session identity shared by every entry in one journal.md."""

    persona_id: str
    session_id: str


@dataclass(frozen=True)
class ReactionEntry:
    """A validated reaction line in journal order."""

    section_index: int
    line_number: int
    heading: str
    scene_id: str
    reaction_intensity: int
    reaction_valence: str
    reaction_tags: tuple[str, ...]
    continuation_pull: int


@dataclass(frozen=True)
class Issue:
    level: str
    line_number: int
    message: str


@dataclass(frozen=True)
class TargetResolution:
    """A checker target and the session scope inferred from its path."""

    journal: Path
    expected_session_id: str | None
    legacy_root: bool


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
    if not value:
        return None, _issue("ERROR", line_number, "reaction_tags は1〜3個で指定してください")

    parts = value.split(",")
    if any(part == "" for part in parts):
        return None, _issue("ERROR", line_number, "reaction_tags はカンマ区切りで空要素を含められません")
    if not 1 <= len(parts) <= 3:
        return None, _issue("ERROR", line_number, "reaction_tags は1〜3個で指定してください")

    tags = tuple(parts)
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


def _parse_header(lines: list[str]) -> tuple[JournalHeader | None, list[Issue]]:
    """Parse the persona_id/session_id header that precedes the first `## ` section."""
    fields: list[tuple[int, str, str]] = []
    for index, line in enumerate(lines):
        match = _HEADER_FIELD_RE.match(line)
        if match:
            fields.append((index + 1, match.group("key"), match.group("value")))

    if not fields:
        return None, [_issue("ERROR", 1, "ファイル冒頭に persona_id / session_id ヘッダがありません")]

    if len(fields) != len(HEADER_FIELD_ORDER):
        return None, [_issue("ERROR", fields[-1][0], "ヘッダの必須フィールドが不足または重複しています")]

    issues: list[Issue] = []
    for (line_number, actual_key, _), expected_key in zip(fields, HEADER_FIELD_ORDER):
        if actual_key != expected_key:
            issues.append(
                _issue(
                    "ERROR",
                    line_number,
                    f"ヘッダの順序が不正です（期待: {expected_key}, 実際: {actual_key}）",
                )
            )
    if issues:
        return None, issues

    values = {key: value for _, key, value in fields}
    for offset, key in enumerate(HEADER_FIELD_ORDER):
        if not _ID_RE.fullmatch(values[key]):
            issues.append(_issue("ERROR", fields[offset][0], f"{key} の形式が不正です: {values[key]!r}"))
    if issues:
        return None, issues

    return JournalHeader(persona_id=values["persona_id"], session_id=values["session_id"]), []


def _preamble(lines: list[str], sections: list[tuple[int, str, list[str]]]) -> list[str]:
    if not sections:
        return lines
    return lines[: sections[0][0]]


def _parse_entry(
    section_index: int,
    start_line: int,
    heading: str,
    body: list[str],
    *,
    allow_missing_reaction: bool,
) -> tuple[ReactionEntry | None, list[Issue]]:
    issues: list[Issue] = []
    matches: list[tuple[int, re.Match[str]]] = []
    malformed: list[int] = []
    for offset, line in enumerate(body):
        if not line.startswith(_REACTION_PREFIX):
            continue
        match = _REACTION_LINE_RE.match(line)
        if match:
            matches.append((start_line + offset + 2, match))
        else:
            malformed.append(start_line + offset + 2)

    if not matches and not malformed:
        level = "WARNING" if allow_missing_reaction else "ERROR"
        issues.append(_issue(level, start_line + 1, "反応行がありません"))
        return None, issues

    if malformed:
        issues.append(_issue("ERROR", malformed[0], "反応行の形式が不正です"))
        return None, issues

    if len(matches) > 1:
        issues.append(_issue("ERROR", matches[1][0], "反応行が複数あります"))
        return None, issues

    line_number, match = matches[0]
    scene_id = match.group("scene")
    if not (_ANCHORED_SCENE_ID_RE.fullmatch(scene_id) or _FALLBACK_SCENE_ID_RE.fullmatch(scene_id)):
        issues.append(
            _issue(
                "ERROR",
                line_number,
                "scene_id は chNN-MMM または source_file_stem-sNNN の形式で指定してください",
            )
        )

    intensity, intensity_issue = _parse_int(match.group("intensity"), field="reaction_intensity", line_number=line_number)
    if intensity_issue:
        issues.append(intensity_issue)
    pull, pull_issue = _parse_int(match.group("pull"), field="continuation_pull", line_number=line_number)
    if pull_issue:
        issues.append(pull_issue)

    valence = match.group("valence")
    if valence not in VALID_VALENCES:
        issues.append(_issue("ERROR", line_number, f"reaction_valence が未定義です: {valence!r}"))

    tags, tags_issue = _parse_tags(match.group("tags"), line_number)
    if tags_issue:
        issues.append(tags_issue)

    if issues or intensity is None or pull is None or tags is None:
        return None, issues

    return (
        ReactionEntry(
            section_index=section_index,
            line_number=start_line + 1,
            heading=heading,
            scene_id=scene_id,
            reaction_intensity=intensity,
            reaction_valence=valence,
            reaction_tags=tags,
            continuation_pull=pull,
        ),
        issues,
    )


def parse_journal(
    text: str, *, allow_missing_reaction: bool = False
) -> tuple[JournalHeader | None, list[ReactionEntry], list[Issue]]:
    """Parse and validate the header and all reaction lines in a journal."""
    lines = text.splitlines()
    sections = _sections(lines)
    header, header_issues = _parse_header(_preamble(lines, sections))

    issues: list[Issue] = list(header_issues)

    if not sections:
        issues.append(_issue("ERROR", 1, "## の Reader Walk 場面エントリが見つかりません"))
        return header, [], issues

    entries: list[ReactionEntry] = []
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

    seen: dict[str, ReactionEntry] = {}
    for entry in entries:
        previous = seen.get(entry.scene_id)
        if previous is not None:
            issues.append(
                _issue(
                    "ERROR",
                    entry.line_number,
                    "同一ファイル内でscene_idが重複しています。再読は新しいセッションディレクトリにしてください",
                )
            )
        else:
            seen[entry.scene_id] = entry

    return header, entries, issues


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


def build_trace(header: JournalHeader | None, entries: list[ReactionEntry]) -> list[dict[str, Any]]:
    """Build a trace in journal occurrence order for one session/persona."""
    if header is None or not entries:
        return []

    values = [entry.reaction_intensity for entry in entries]
    trace: list[dict[str, Any]] = []
    previous: int | None = None
    for index, entry in enumerate(entries):
        delta = None if previous is None else entry.reaction_intensity - previous
        trace.append(
            {
                "session_id": header.session_id,
                "persona_id": header.persona_id,
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


def _validate_header_scope(
    header: JournalHeader | None,
    *,
    expected_session_id: str | None,
) -> list[Issue]:
    """Enforce that the header's session_id matches the session directory name."""
    if header is None or expected_session_id is None:
        return []
    if header.session_id != expected_session_id:
        return [
            _issue(
                "ERROR",
                1,
                f"ディレクトリ名とsession_idが一致しません（期待: {expected_session_id}, 実際: {header.session_id}）",
            )
        ]
    return []


def validate_file(
    path: Path,
    *,
    allow_missing_reaction: bool = False,
    expected_session_id: str | None = None,
) -> tuple[JournalHeader | None, list[ReactionEntry], list[Issue]]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, [], [_issue("ERROR", 1, f"ファイルを読み込めません: {exc}")]
    except UnicodeError as exc:
        return None, [], [_issue("ERROR", 1, f"UTF-8として読み込めません: {exc}")]
    header, entries, issues = parse_journal(text, allow_missing_reaction=allow_missing_reaction)
    issues.extend(_validate_header_scope(header, expected_session_id=expected_session_id))
    return header, entries, issues


def _resolve_target(target: Path, *, allow_legacy_root: bool) -> tuple[TargetResolution | None, Issue | None]:
    """Resolve a session directory or journal and reject the old root layout by default.

    The only accepted shapes are ``walk/<session_id>/`` (or its ``journal.md``) and,
    for migration checks, ``walk/journal.md`` directly under a directory named ``walk``.
    """
    if target.is_dir():
        legacy_root = target.name.casefold() == "walk"
        journal = target / "journal.md"
        if legacy_root:
            expected_session_id = None
        elif target.parent.name.casefold() != "walk":
            return None, _issue(
                "ERROR",
                1,
                "対象は walk/<session_id>/ またはその journal.md を指定してください",
            )
        else:
            expected_session_id = target.name
    else:
        if target.name != "journal.md":
            return None, _issue("ERROR", 1, "対象ファイルは journal.md である必要があります")
        legacy_root = target.parent.name.casefold() == "walk"
        journal = target
        if legacy_root:
            expected_session_id = None
        elif target.parent.parent.name.casefold() != "walk":
            return None, _issue(
                "ERROR",
                1,
                "対象は walk/<session_id>/journal.md を指定してください",
            )
        else:
            expected_session_id = target.parent.name

    if legacy_root and not allow_legacy_root:
        return None, _issue(
            "ERROR",
            1,
            "walk直下のjournal.mdは移行前専用です。移行確認には --legacy-root を指定してください",
        )
    if expected_session_id is not None and not _ID_RE.fullmatch(expected_session_id):
        return None, _issue(
            "ERROR",
            1,
            f"セッションディレクトリ名がID形式ではありません: {expected_session_id!r}",
        )
    return TargetResolution(journal, expected_session_id, legacy_root), None


def _print_issues(issues: list[Issue]) -> None:
    for issue in issues:
        print(f"{issue.level}: L{issue.line_number}: {issue.message}")


def _write_trace(path: Path, trace: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(trace, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Reader Walk反応行を検証し、山谷traceを生成する")
    parser.add_argument("target", type=Path, help="journal.md または walk ディレクトリ")
    parser.add_argument(
        "--allow-missing-reaction",
        action="store_true",
        help="反応行のない既存エントリをWARNINGとして許容する",
    )
    parser.add_argument(
        "--legacy-root",
        action="store_true",
        help="移行前のwalk/journal.mdを一時的に検査する",
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
    resolution, resolution_issue = _resolve_target(args.target, allow_legacy_root=args.legacy_root)
    if resolution_issue is not None:
        if args.json:
            print(json.dumps({"journal": str(args.target), "entries": 0, "errors": 1, "warnings": 0, "trace_entries": 0}, ensure_ascii=False, indent=2))
        else:
            print(f"{resolution_issue.level}: {resolution_issue.message}", file=sys.stderr)
        return 1

    assert resolution is not None
    journal = resolution.journal
    if not journal.is_file():
        print(f"ERROR: 対象journal.mdが見つかりません: {journal}", file=sys.stderr)
        return 3

    header, entries, issues = validate_file(
        journal,
        allow_missing_reaction=args.allow_missing_reaction,
        expected_session_id=resolution.expected_session_id,
    )
    errors = [issue for issue in issues if issue.level == "ERROR"]
    warnings = [issue for issue in issues if issue.level == "WARNING"]
    trace = build_trace(header, entries) if not errors else []
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
