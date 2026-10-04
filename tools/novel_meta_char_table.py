#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_meta.md の章別文字数表を生成・照合する。ファイルは書かない。"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path
from typing import TypedDict

from novel_char_count import count_chars

_RE_TEXT = re.compile(r"^novel_text(\d+)(?:_(\d+))?\.md$")
_RE_HEADING = re.compile(r"^#{1,6}\s*章別文字数\s*$")
_RE_CHAPTER = re.compile(r"第\s*(\d+)\s*章")
_RE_SEP = re.compile(r"^\|\s*:?-{3,}")


class ChapterRow(TypedDict):
    chapter: int
    label: str
    body: str
    chars: int


def resolve_work(path: Path, repo_root: Path) -> Path:
    raw = path.expanduser()
    if not raw.is_absolute():
        raw = (repo_root / raw).resolve()
    else:
        raw = raw.resolve()
    if raw.is_file() and raw.name == "_meta.md":
        return raw.parent
    if raw.is_dir():
        return raw
    raise FileNotFoundError(f"作品フォルダが見つかりません: {path}")


def iter_text_files(work: Path) -> list[Path]:
    text_dir = work / "_novel_text"
    if not text_dir.is_dir():
        return []
    return sorted(
        p for p in text_dir.glob("novel_text*.md") if _RE_TEXT.match(p.name)
    )


def measure_chapters(work: Path, *, strip_fm: bool = True) -> list[ChapterRow]:
    groups: dict[int, list[tuple[str, int]]] = {}
    for path in iter_text_files(work):
        matched = _RE_TEXT.match(path.name)
        if not matched:
            continue
        chapter = int(matched.group(1))
        count = count_chars(path.read_text(encoding="utf-8"), strip_fm=strip_fm)
        groups.setdefault(chapter, []).append((path.stem, count))

    rows: list[ChapterRow] = []
    for chapter in sorted(groups):
        files = groups[chapter]
        total = sum(item[1] for item in files)
        stems = [item[0] for item in files]
        if len(stems) == 1 and not re.search(r"_\d+$", stems[0]):
            body = stems[0]
        else:
            body = f"novel_text{chapter:02d}_*"
        label = "プロローグ（第0章）" if chapter == 0 else f"第{chapter}章"
        rows.append(
            {
                "chapter": chapter,
                "label": label,
                "body": body,
                "chars": total,
            }
        )
    return rows


def extract_table_section(meta_text: str) -> str | None:
    lines = meta_text.splitlines()
    start = None
    for index, line in enumerate(lines):
        if _RE_HEADING.match(line.strip()):
            start = index
            break
    if start is None:
        return None
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if re.match(r"^#{1,6}\s", lines[index]):
            end = index
            break
    return "\n".join(lines[start:end])


def parse_table_rows(section: str) -> tuple[dict[int, int], int | None]:
    counts: dict[int, int] = {}
    total: int | None = None
    for raw in section.splitlines():
        line = raw.strip()
        if not line.startswith("|"):
            continue
        if _RE_SEP.match(line) or "実文字数" in line:
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) < 3:
            continue
        label, _body, count_text = cells[0], cells[1], cells[2]
        digits = count_text.replace(",", "").replace("—", "").replace("-", "").strip()
        if not digits.isdigit():
            continue
        value = int(digits)
        if label.startswith("合計"):
            total = value
            continue
        matched = _RE_CHAPTER.search(label)
        if matched:
            counts[int(matched.group(1))] = value
    return counts, total


def parse_status_map(section: str) -> dict[int, str]:
    statuses: dict[int, str] = {}
    for raw in section.splitlines():
        line = raw.strip()
        if not line.startswith("|") or _RE_SEP.match(line) or "実文字数" in line:
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) < 4:
            continue
        label, status = cells[0], cells[3]
        if label.startswith("合計"):
            continue
        matched = _RE_CHAPTER.search(label)
        if matched and status and status not in {"—", "-"}:
            statuses[int(matched.group(1))] = status
    return statuses


def format_table(
    rows: list[ChapterRow],
    *,
    statuses: dict[int, str] | None = None,
    measured_on: str,
) -> str:
    statuses = statuses or {}
    lines = [
        "### 章別文字数",
        "数値の根拠は `tools/novel_char_count.py`。一覧の正本は本表。設計書の想定尺は目標であり在庫ではない。",
        "",
        "| 章 | 本文 | 実文字数 | 状態 | 計測 |",
        "|---|---|---:|---|---|",
    ]
    total = 0
    for row in rows:
        chapter = row["chapter"]
        count = row["chars"]
        total += count
        status = statuses.get(chapter, "初稿")
        lines.append(
            f"| {row['label']} | {row['body']} | {count:,} | {status} | {measured_on} |"
        )
    lines.append(f"| 合計 | — | {total:,} | — | {measured_on} |")
    return "\n".join(lines) + "\n"


def cmd_render(work: Path, *, measured_on: str) -> int:
    statuses: dict[int, str] = {}
    meta = work / "_meta.md"
    if meta.is_file():
        section = extract_table_section(meta.read_text(encoding="utf-8"))
        if section:
            statuses = parse_status_map(section)
    sys.stdout.write(
        format_table(
            measure_chapters(work),
            statuses=statuses,
            measured_on=measured_on,
        )
    )
    return 0


def cmd_check(work: Path) -> int:
    meta = work / "_meta.md"
    if not meta.is_file():
        print("対象外: _meta.md が無い", file=sys.stderr)
        return 0
    section = extract_table_section(meta.read_text(encoding="utf-8"))
    if section is None:
        print("対象外: 章別文字数表が無い", file=sys.stderr)
        return 0

    expected = {row["chapter"]: row["chars"] for row in measure_chapters(work)}
    actual, table_total = parse_table_rows(section)
    mismatches: list[str] = []
    for chapter in sorted(set(expected) | set(actual)):
        if expected.get(chapter) != actual.get(chapter):
            mismatches.append(
                f"第{chapter}章 表={actual.get(chapter)} 集計={expected.get(chapter)}"
            )
    expected_total = sum(expected.values())
    if table_total is not None and table_total != expected_total:
        mismatches.append(f"合計 表={table_total} 集計={expected_total}")
    if mismatches:
        print("章別文字数が集計と一致しない:", file=sys.stderr)
        for item in mismatches:
            print(f"  {item}", file=sys.stderr)
        return 1
    print("OK: 章別文字数は novel_char_count と一致")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="_meta.md の章別文字数表を生成・照合する。_meta.md は書かない。"
    )
    parser.add_argument("command", choices=("render", "check"))
    parser.add_argument("novel", type=Path, help="作品フォルダまたは _meta.md")
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="リポジトリルート（未指定時は本スクリプトの親の親）",
    )
    parser.add_argument(
        "--measured-on",
        default=None,
        help="計測日 YYYY-MM-DD（未指定時は実行日）",
    )
    args = parser.parse_args(argv)
    repo_root = (args.repo_root or Path(__file__).resolve().parent.parent).resolve()
    try:
        work = resolve_work(args.novel, repo_root)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.command == "render":
        return cmd_render(work, measured_on=args.measured_on or date.today().isoformat())
    return cmd_check(work)


if __name__ == "__main__":
    raise SystemExit(main())
