#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
設定監査の鮮度チェック（Monogatari Coach）。

設定3点（character.md / world.md / design_specification.md）のハッシュを出し、
最新の設定監査ファイル `_reader/consistency_design_YYYYMMDD_HHMM.md` の冒頭に
書かれたハッシュと比べる。LLM / provider は呼ばず、作品ファイルを書き換えない。

サブコマンド:
  hash  <作品フォルダ>   監査ファイル冒頭へ貼る「設定ハッシュ」行を出す
  check <作品フォルダ>   最新の設定監査と現在の設定3点を比べる

check の終了コード:
  0  監査済み（最新の設定監査以降、設定3点は変わっていない）
  1  未監査（設定監査ファイルが無い、またはハッシュが変わった）
  2  エラー（作品フォルダや設定3点が無い）

運用: .rulesync/skills/novel-evaluation-output/SKILL.md を参照。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

SETTING_FILES: tuple[str, ...] = (
    "character.md",
    "world.md",
    "design_specification.md",
)

_RE_DESIGN_FILE = re.compile(r"^consistency_design_(\d{8})_(\d{4})\.md$")
_RE_SCOPE = re.compile(r"^\s*-\s*scope\s*[:：]\s*`?(design|text)`?", re.IGNORECASE)
_RE_HASH = re.compile(
    r"^\s*-\s*(" + "|".join(re.escape(n) for n in SETTING_FILES) + r")\s*[:：]\s*`?sha256:([0-9a-f]{64})`?",
)
# 冒頭（ヘッダ）として読む最大行数。本文の表にある同名の記述を拾わないため。
_HEADER_LINES = 60


def file_hash(path: Path) -> str:
    """改行コードの差（CRLF / LF）を無視した SHA-256。"""
    data = path.read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def current_hashes(novel_dir: Path) -> dict[str, str]:
    missing = [n for n in SETTING_FILES if not (novel_dir / n).is_file()]
    if missing:
        raise FileNotFoundError(", ".join(missing))
    return {n: file_hash(novel_dir / n) for n in SETTING_FILES}


def render_hash_lines(hashes: dict[str, str]) -> str:
    lines = ["- 設定ハッシュ:"]
    lines += [f"  - {n}: sha256:{hashes[n]}" for n in SETTING_FILES]
    return "\n".join(lines)


def latest_design_audit(novel_dir: Path) -> Path | None:
    reader = novel_dir / "_reader"
    if not reader.is_dir():
        return None
    found: list[tuple[str, Path]] = []
    for p in reader.iterdir():
        m = _RE_DESIGN_FILE.match(p.name)
        if m and p.is_file():
            found.append((f"{m.group(1)}_{m.group(2)}", p))
    if not found:
        return None
    found.sort(key=lambda t: t[0])
    return found[-1][1]


@dataclass
class AuditHeader:
    scope: str | None = None
    hashes: dict[str, str] = field(default_factory=dict)


def parse_header(path: Path) -> AuditHeader:
    header = AuditHeader()
    text = path.read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines()[:_HEADER_LINES]:
        m = _RE_SCOPE.match(line)
        if m and header.scope is None:
            header.scope = m.group(1).lower()
            continue
        m = _RE_HASH.match(line)
        if m and m.group(1) not in header.hashes:
            header.hashes[m.group(1)] = m.group(2)
    return header


@dataclass
class FreshnessResult:
    status: str  # "fresh" / "stale" / "unaudited" / "error"
    audit_file: str | None = None
    changed: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def exit_code(self) -> int:
        return {"fresh": 0, "stale": 1, "unaudited": 1}.get(self.status, 2)


def check_freshness(novel_dir: Path) -> FreshnessResult:
    if not novel_dir.is_dir():
        return FreshnessResult("error", error=f"作品フォルダがありません: {novel_dir}")
    try:
        now = current_hashes(novel_dir)
    except FileNotFoundError as exc:
        return FreshnessResult("error", error=f"設定資料がありません: {exc}")

    audit = latest_design_audit(novel_dir)
    if audit is None:
        return FreshnessResult("unaudited", changed=list(SETTING_FILES))

    rel = audit.relative_to(novel_dir).as_posix()
    header = parse_header(audit)
    warnings: list[str] = []
    if header.scope is None:
        warnings.append(f"{rel}: 冒頭に scope がありません（ファイル名から design とみなします）")
    elif header.scope != "design":
        warnings.append(f"{rel}: ファイル名は design ですが冒頭の scope は {header.scope} です（冒頭を正とします）")
        return FreshnessResult("unaudited", audit_file=rel, changed=list(SETTING_FILES), warnings=warnings)

    missing = [n for n in SETTING_FILES if n not in header.hashes]
    if missing:
        warnings.append(f"{rel}: 冒頭に設定ハッシュがありません: {', '.join(missing)}")
    changed = [n for n in SETTING_FILES if header.hashes.get(n) != now[n]]
    status = "stale" if changed else "fresh"
    return FreshnessResult(status, audit_file=rel, changed=changed, warnings=warnings)


_STATUS_LABEL = {
    "fresh": "監査済み（最新の設定監査以降、設定3点に変更なし）",
    "stale": "未監査（最新の設定監査以降に設定が変わった）",
    "unaudited": "未監査（設定監査ファイルがない）",
    "error": "エラー",
}


def _cmd_hash(args: argparse.Namespace) -> int:
    try:
        hashes = current_hashes(args.novel_dir)
    except FileNotFoundError as exc:
        print(f"[ERROR] 設定資料がありません: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(hashes, ensure_ascii=False, indent=2))
    else:
        print(render_hash_lines(hashes))
    return 0


def _cmd_check(args: argparse.Namespace) -> int:
    result = check_freshness(args.novel_dir)
    if args.json:
        print(json.dumps(
            {
                "status": result.status,
                "audit_file": result.audit_file,
                "changed": result.changed,
                "warnings": result.warnings,
                "error": result.error,
            },
            ensure_ascii=False,
            indent=2,
        ))
        return result.exit_code
    if result.error:
        print(f"[ERROR] {result.error}", file=sys.stderr)
        return result.exit_code
    print(f"状態: {_STATUS_LABEL[result.status]}")
    print(f"基準: {result.audit_file or 'なし'}")
    if result.status == "stale":
        print(f"変更: {', '.join(result.changed)}")
    for w in result.warnings:
        print(f"[WARN] {w}")
    return result.exit_code


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="設定監査の鮮度チェック（設定3点のハッシュ比較）")
    sub = parser.add_subparsers(dest="command", required=True)

    p_hash = sub.add_parser("hash", help="監査ファイル冒頭へ貼る設定ハッシュ行を出す")
    p_hash.add_argument("novel_dir", type=Path, help="作品フォルダ（novels/NNN_作品名）")
    p_hash.add_argument("--json", action="store_true", help="JSON で出す")
    p_hash.set_defaults(func=_cmd_hash)

    p_check = sub.add_parser("check", help="最新の設定監査と現在の設定3点を比べる")
    p_check.add_argument("novel_dir", type=Path, help="作品フォルダ（novels/NNN_作品名）")
    p_check.add_argument("--json", action="store_true", help="JSON で出す")
    p_check.set_defaults(func=_cmd_check)
    return parser


def main(argv: list[str] | None = None) -> int:
    from console_io import configure_stdio_utf8

    configure_stdio_utf8()
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
