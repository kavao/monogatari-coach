#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
_workingspace/log/(YYYYMM).md 査証ログ — 追記専用（公式用）。

- 既存内容の上書き・削除は行わない（追記は open(..., 'a') のみ）。
- 新規月ファイルは、存在しないか空のときだけ先頭に「# 査証ログ YYYY年M月」を書き込む。
- エントリ1行形式: 「- YYYY-MM-DD HH:MM: 本文」

定義・運用はスキル workspace-audit-log（.rulesync/skills/workspace-audit-log/SKILL.md）に従う。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def log_dir(root: Path | None = None) -> Path:
    r = root or repo_root()
    return r / "_workingspace" / "log"


def month_file_path(year: int, month: int, root: Path | None = None) -> Path:
    return log_dir(root) / f"{year:04d}{month:02d}.md"


def format_month_header(year: int, month: int) -> str:
    return f"# 査証ログ {year}年{month}月\n\n"


def normalize_message(text: str) -> str:
    text = text.strip()
    if not text:
        raise ValueError("メッセージが空です")
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return " ".join(lines)


ENTRY_LINE_RE = re.compile(
    r"^-\s*(\d{4}-\d{2}-\d{2})\s+(\d{1,2}:\d{2})(?::(\d{2}))?\s*:\s*(.*)$"
)


def parse_year_month(s: str | None) -> tuple[int, int] | None:
    if not s:
        return None
    ym = s.strip()
    if len(ym) != 6 or not ym.isdigit():
        raise ValueError("--year-month は YYYYMM（例: 202604）で指定してください")
    y, m = int(ym[:4]), int(ym[4:6])
    if not (1 <= m <= 12):
        raise ValueError("月は 01〜12 です")
    return y, m


def append_entry(
    message: str,
    *,
    file_year: int,
    file_month: int,
    stamp: datetime,
    root: Path | None = None,
    dry_run: bool = False,
) -> dict[str, str | bool]:
    path = month_file_path(file_year, file_month, root)
    msg = normalize_message(message)
    date_s = stamp.strftime("%Y-%m-%d")
    time_s = stamp.strftime("%H:%M")
    line = f"- {date_s} {time_s}: {msg}\n"

    if not dry_run:
        path.parent.mkdir(parents=True, exist_ok=True)

    is_new = not path.exists() or (path.exists() and path.stat().st_size == 0)

    prefix_newline = False
    if not is_new and path.exists() and path.stat().st_size > 0:
        with open(path, "rb") as f:
            f.seek(-1, 2)
            if f.read(1) != b"\n":
                prefix_newline = True

    chunks: list[str] = []
    if is_new:
        chunks.append(format_month_header(file_year, file_month))
    elif prefix_newline:
        chunks.append("\n")
    chunks.append(line)
    payload = "".join(chunks)

    display_line = (
        (format_month_header(file_year, file_month) if is_new else "")
        + (("\n" if prefix_newline and not is_new else ""))
        + line
    ).rstrip("\n")

    result: dict[str, str | bool] = {
        "path": str(path.resolve()),
        "line": display_line,
        "dry_run": dry_run,
        "is_new_month_file": is_new,
    }

    if dry_run:
        result["written"] = False
        return result

    with open(path, "a", encoding="utf-8") as f:
        f.write(payload)

    result["written"] = True
    return result


def parse_at(s: str) -> datetime:
    s = s.strip().replace("T", " ", 1)
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    raise argparse.ArgumentTypeError(
        "日時は YYYY-MM-DDTHH:MM または 'YYYY-MM-DD HH:MM' 形式で指定してください"
    )


def cmd_append(args: argparse.Namespace) -> int:
    root = Path(args.repo_root).resolve() if args.repo_root else repo_root()
    if args.message is not None:
        message = args.message
    else:
        message = sys.stdin.read()

    now = datetime.now()
    ym = parse_year_month(args.year_month)
    if ym:
        file_year, file_month = ym
    else:
        file_year, file_month = now.year, now.month

    if args.at:
        stamp = args.at
    else:
        stamp = now

    try:
        r = append_entry(
            message,
            file_year=file_year,
            file_month=file_month,
            stamp=stamp,
            root=root,
            dry_run=args.dry_run,
        )
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
    else:
        if args.dry_run:
            print("[dry-run] 追記内容:")
            print(r["line"])
            print(f"→ {r['path']}")
        else:
            print(f"追記しました: {r['path']}")
    return 0


def cmd_path(args: argparse.Namespace) -> int:
    root = Path(args.repo_root).resolve() if args.repo_root else repo_root()
    now = datetime.now()
    ym = parse_year_month(args.year_month)
    if ym:
        y, m = ym
    else:
        y, m = now.year, now.month
    p = month_file_path(y, m, root)
    if args.json:
        print(
            json.dumps(
                {
                    "path": str(p.resolve()),
                    "year_month": f"{y:04d}{m:02d}",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(p.resolve())
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    root = Path(args.repo_root).resolve() if args.repo_root else repo_root()
    ld = log_dir(root)
    strict = getattr(args, "strict", False)
    if not ld.is_dir():
        print(f"NG: log ディレクトリがありません: {ld}", file=sys.stderr)
        return 1

    errors: list[str] = []
    warnings: list[str] = []
    md_files = sorted(ld.glob("*.md"))
    for p in md_files:
        if p.name.startswith("."):
            continue
        if not re.match(r"^\d{6}\.md$", p.name):
            errors.append(f"想定外のファイル名（YYYYMM.md 以外）: {p.name}")
            continue
        text = p.read_text(encoding="utf-8")
        lines = text.splitlines()
        if not lines:
            errors.append(f"{p.name}: 空ファイル")
            continue
        if not lines[0].startswith("# 査証ログ "):
            errors.append(f"{p.name}: 1行目が「# 査証ログ …」ではありません")
        for i, line in enumerate(lines[1:], start=2):
            if not line.strip():
                continue
            if line.startswith("#"):
                errors.append(f"{p.name}:{i}: 本文中に # 見出しが混入しています")
                continue
            if line.startswith("- "):
                if not ENTRY_LINE_RE.match(line):
                    msg = (
                        f"{p.name}:{i}: 推奨形式と異なります"
                        f"（`- YYYY-MM-DD HH:MM: 本文`）。tool append で追記した行は厳密に一致します: {line[:80]}"
                    )
                    if strict:
                        errors.append(msg)
                    else:
                        warnings.append(msg)
            else:
                errors.append(f"{p.name}:{i}: 箇条書き「- 」で始まっていません")

    for w in warnings:
        print(f"WARN: {w}", file=sys.stderr)

    if errors:
        for e in errors:
            print(f"NG: {e}", file=sys.stderr)
        return 1
    print(f"OK: {len(md_files)} ファイルを検査 ({ld})" + (" [strict]" if strict else ""))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="_workingspace/log 査証ログへ追記（追記モードのみ）"
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="リポジトリルート（既定: 本スクリプトから自動）",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    pa = sub.add_parser("append", help="査証ログに1行追記")
    pa.add_argument(
        "message",
        nargs="?",
        default=None,
        help="本文（省略時は標準入力）",
    )
    pa.add_argument(
        "--dry-run",
        action="store_true",
        help="書き込まず内容だけ表示",
    )
    pa.add_argument(
        "--json",
        action="store_true",
    )
    pa.add_argument(
        "--year-month",
        type=str,
        default=None,
        help="追記先ファイルの年月 YYYYMM（既定: 今日の年月）",
    )
    pa.add_argument(
        "--at",
        dest="at",
        type=parse_at,
        default=None,
        help="エントリの日時（既定: 実行時刻）。YYYY-MM-DD HH:MM",
    )
    pa.set_defaults(func=cmd_append)

    pp = sub.add_parser("path", help="指定月のログファイルの絶対パスを表示")
    pp.add_argument("--json", action="store_true")
    pp.add_argument(
        "--year-month",
        type=str,
        default=None,
        help="YYYYMM（既定: 今日の年月）",
    )
    pp.set_defaults(func=cmd_path)

    pv = sub.add_parser(
        "verify",
        help="log 配下の *.md の体裁を検査（読み取り専用）",
    )
    pv.add_argument(
        "--strict",
        action="store_true",
        help="各行を公式形式（日付+時刻+本文）に厳密照合（移行前ログは WARN になりうる）",
    )
    pv.set_defaults(func=cmd_verify)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
