#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Consistency Audit ファイルの体裁検査（Monogatari Coach）。

`_reader/consistency_<scope>_YYYYMMDD_HHMM.md` について、次を決定的に確かめる。
LLM / provider は呼ばず、ファイルを書き換えない。

- ファイル名と冒頭の scope が一致する
- 冒頭に 種別・scope・起動・件数 がある（起動は gate_b / pre_review / user）
- design は冒頭に設定3点のハッシュがある
- 「確認した組み合わせ」の節がある
- 冒頭の件数（矛盾 / 要確認 / 軽微）が、指摘表の判定列の行数と一致する
- 組み合わせ表の指摘数の合計が、件数の合計と一致する

判定列は、セルの中身がちょうど「矛盾」「要確認」「軽微」の行だけを数える。
前回指摘の解消確認など、件数に含めない表では「前回: 矛盾」のように書く。
`## 再監査` 見出しがあるときは、その見出し以降の指摘表だけを数える。

終了コード: 0 = 問題なし / 1 = 不一致あり / 2 = ファイルを読めない

運用: .rulesync/skills/novel-evaluation-output/SKILL.md を参照。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

JUDGMENTS = ("矛盾", "要確認", "軽微")
LAUNCHES = ("gate_b", "pre_review", "user")
SETTING_FILES = ("character.md", "world.md", "design_specification.md")

_RE_NAME = re.compile(r"^consistency_(design|text)_(\d{8})_(\d{4})\.md$")
_RE_SCOPE = re.compile(r"^\s*-\s*scope\s*[:：]\s*`?(design|text)`?", re.IGNORECASE)
_RE_LAUNCH = re.compile(r"^\s*-\s*起動\s*[:：]\s*`?([a-z_]+)`?")
_RE_KIND = re.compile(r"^\s*-\s*種別\s*[:：]\s*Consistency Audit")
_RE_COUNTS = re.compile(r"^\s*-\s*件数\s*[:：](.*)$")
_RE_HASH = re.compile(
    r"^\s*-\s*(" + "|".join(re.escape(n) for n in SETTING_FILES) + r")\s*[:：]\s*`?sha256:[0-9a-f]{64}`?"
)
_RE_HEADING = re.compile(r"^#{1,6}\s+(.*)$")
_HEADER_LINES = 60


@dataclass
class LintResult:
    path: str
    scope: str | None = None
    header_counts: dict[str, int] = field(default_factory=dict)
    table_counts: dict[str, int] = field(default_factory=dict)
    combination_total: int | None = None
    errors: list[str] = field(default_factory=list)

    @property
    def exit_code(self) -> int:
        return 1 if self.errors else 0


def _last_int_after(label: str, text: str) -> int | None:
    """「矛盾 2→0」「矛盾2」「矛盾 2 → 0」から最後の数（再監査後）を取る。"""
    m = re.search(re.escape(label) + r"\s*([0-9０-９]+(?:\s*(?:→|->)\s*[0-9０-９]+)*)", text)
    if not m:
        return None
    nums = re.findall(r"[0-9０-９]+", m.group(1))
    return int(nums[-1].translate(str.maketrans("０１２３４５６７８９", "0123456789")))


def _cells(line: str) -> list[str]:
    stripped = line.strip()
    if not (stripped.startswith("|") and stripped.endswith("|")):
        return []
    return [c.strip() for c in stripped.strip("|").split("|")]


def _is_separator(cells: list[str]) -> bool:
    return bool(cells) and all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c)


def lint_text(text: str, filename: str) -> LintResult:
    result = LintResult(path=filename)
    lines = text.splitlines()
    header = lines[:_HEADER_LINES]

    m = _RE_NAME.match(Path(filename).name)
    name_scope = m.group(1) if m else None
    if m is None:
        result.errors.append("ファイル名が consistency_<design|text>_YYYYMMDD_HHMM.md ではない")

    if not any(_RE_KIND.match(line) for line in header):
        result.errors.append("冒頭に「種別: Consistency Audit」がない")

    scope = next((s.group(1).lower() for line in header if (s := _RE_SCOPE.match(line))), None)
    result.scope = scope
    if scope is None:
        result.errors.append("冒頭に scope がない")
    elif name_scope and scope != name_scope:
        result.errors.append(f"ファイル名の scope（{name_scope}）と冒頭の scope（{scope}）が違う")

    launch = next((s.group(1) for line in header if (s := _RE_LAUNCH.match(line))), None)
    if launch is None:
        result.errors.append("冒頭に「起動」がない")
    elif launch not in LAUNCHES:
        result.errors.append(f"起動が gate_b / pre_review / user のどれでもない: {launch}")

    if (scope or name_scope) == "design":
        found = {h.group(1) for line in header if (h := _RE_HASH.match(line))}
        missing = [n for n in SETTING_FILES if n not in found]
        if missing:
            result.errors.append(f"design なのに設定ハッシュがない: {', '.join(missing)}")

    counts_line = next((c.group(1) for line in header if (c := _RE_COUNTS.match(line))), None)
    if counts_line is None:
        result.errors.append("冒頭に「件数」がない")
    else:
        for label in JUDGMENTS:
            value = _last_int_after(label, counts_line)
            if value is None:
                result.errors.append(f"件数に「{label}」の数がない")
            else:
                result.header_counts[label] = value

    # 見出しで節を切る
    headings = [(i, h.group(1)) for i, line in enumerate(lines) if (h := _RE_HEADING.match(line))]
    reaudit_at = next((i for i, title in headings if title.strip().startswith("再監査")), None)
    combo_at = next((i for i, title in headings if "確認した組み合わせ" in title), None)
    if combo_at is None:
        result.errors.append("「確認した組み合わせ」の節がない")

    def section_end(start: int) -> int:
        nxt = [i for i, _ in headings if i > start]
        return nxt[0] if nxt else len(lines)

    # 組み合わせ表の指摘数の合計（最後の列の先頭の整数）
    if combo_at is not None:
        total = 0
        rows = 0
        for line in lines[combo_at + 1 : section_end(combo_at)]:
            cells = _cells(line)
            if not cells or _is_separator(cells):
                continue
            num = re.match(r"\s*([0-9]+)", cells[-1])
            if num:
                total += int(num.group(1))
                rows += 1
        if rows == 0:
            result.errors.append("「確認した組み合わせ」に表の行がない")
        else:
            result.combination_total = total

    # 指摘表の判定列（セルがちょうど判定語）
    start = reaudit_at if reaudit_at is not None else 0
    counts = {label: 0 for label in JUDGMENTS}
    for line in lines[start:]:
        cells = _cells(line)
        if not cells or _is_separator(cells):
            continue
        for label in JUDGMENTS:
            if label in cells:
                counts[label] += 1
                break
    result.table_counts = counts

    if result.header_counts and len(result.header_counts) == len(JUDGMENTS):
        for label in JUDGMENTS:
            if result.header_counts[label] != counts[label]:
                result.errors.append(
                    f"件数の「{label}」が冒頭 {result.header_counts[label]} 件、指摘表 {counts[label]} 行で一致しない"
                )
        expected = sum(result.header_counts.values())
        if result.combination_total is not None and result.combination_total != expected:
            result.errors.append(
                f"組み合わせ表の指摘数の合計 {result.combination_total} が件数の合計 {expected} と一致しない"
            )
    return result


def lint_file(path: Path) -> LintResult:
    return lint_text(path.read_text(encoding="utf-8"), path.name)


def main(argv: list[str] | None = None) -> int:
    from console_io import configure_stdio_utf8

    configure_stdio_utf8()
    parser = argparse.ArgumentParser(description="Consistency Audit ファイルの体裁検査（件数と表の一致など）")
    parser.add_argument("paths", nargs="+", type=Path, help="監査ファイル、または作品フォルダ（_reader/ の新形式を全部検査）")
    parser.add_argument("--json", action="store_true", help="JSON で出す")
    args = parser.parse_args(argv)

    targets: list[Path] = []
    for p in args.paths:
        if p.is_dir():
            reader = p / "_reader" if (p / "_reader").is_dir() else p
            targets += sorted(f for f in reader.iterdir() if _RE_NAME.match(f.name))
        else:
            targets.append(p)
    if not targets:
        print("[ERROR] 検査する監査ファイルがない", file=sys.stderr)
        return 2

    results: list[LintResult] = []
    for t in targets:
        try:
            results.append(lint_file(t))
        except OSError as exc:
            print(f"[ERROR] 読めない: {t}: {exc}", file=sys.stderr)
            return 2

    if args.json:
        print(json.dumps([r.__dict__ for r in results], ensure_ascii=False, indent=2))
    else:
        for r in results:
            mark = "OK" if not r.errors else "NG"
            counts = " / ".join(f"{k}{r.table_counts.get(k, 0)}" for k in JUDGMENTS)
            print(f"[{mark}] {Path(r.path).name}（{r.scope or '?'}・{counts}）")
            for e in r.errors:
                print(f"  - {e}")
    return 1 if any(r.errors for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
