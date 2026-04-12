#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
_workingspace 配下の月次 Markdown — 追記専用（公式用）。

- **査証ログ**: `log/(YYYYMM).md` — スキル workspace-audit-log
- **横断ナレッジ日記**: `diary/(YYYYMM).md` — スキル workspace-diary

いずれも既存内容の上書き・削除は行わない（追記は open(..., "a") のみ）。
新規月ファイルは、存在しないか空のときだけ先頭に月見出しを1回書き込む。
エントリ1行形式: 「- YYYY-MM-DD HH:MM: 本文」

定義・運用は各スキル（.rulesync/skills/workspace-audit-log|workspace-diary/SKILL.md）に従う。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from enum import Enum
from pathlib import Path


class MonthlyTarget(str, Enum):
    AUDIT = "audit"
    DIARY = "diary"


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def log_dir(root: Path | None = None) -> Path:
    r = root or repo_root()
    return r / "_workingspace" / "log"


def diary_dir(root: Path | None = None) -> Path:
    r = root or repo_root()
    return r / "_workingspace" / "diary"


def month_file_path(
    year: int,
    month: int,
    *,
    target: MonthlyTarget,
    root: Path | None = None,
) -> Path:
    name = f"{year:04d}{month:02d}.md"
    if target is MonthlyTarget.AUDIT:
        return log_dir(root) / name
    return diary_dir(root) / name


def format_month_header(year: int, month: int, *, target: MonthlyTarget) -> str:
    if target is MonthlyTarget.AUDIT:
        return f"# 査証ログ {year}年{month}月\n\n"
    return f"# 日記（横断ナレッジ） {year}年{month}月\n\n"


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
    target: MonthlyTarget,
    file_year: int,
    file_month: int,
    stamp: datetime,
    root: Path | None = None,
    dry_run: bool = False,
) -> dict[str, str | bool]:
    path = month_file_path(file_year, file_month, target=target, root=root)
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

    hdr = format_month_header(file_year, file_month, target=target)
    chunks: list[str] = []
    if is_new:
        chunks.append(hdr)
    elif prefix_newline:
        chunks.append("\n")
    chunks.append(line)
    payload = "".join(chunks)

    display_line = (
        (hdr if is_new else "")
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


def _run_append_cmd(args: argparse.Namespace, *, target: MonthlyTarget) -> int:
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
            target=target,
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
            label = "査証ログ" if target is MonthlyTarget.AUDIT else "日記"
            print(f"追記しました ({label}): {r['path']}")
    return 0


def cmd_append(args: argparse.Namespace) -> int:
    return _run_append_cmd(args, target=MonthlyTarget.AUDIT)


def cmd_diary_append(args: argparse.Namespace) -> int:
    return _run_append_cmd(args, target=MonthlyTarget.DIARY)


def _run_path_cmd(args: argparse.Namespace, *, target: MonthlyTarget) -> int:
    root = Path(args.repo_root).resolve() if args.repo_root else repo_root()
    now = datetime.now()
    ym = parse_year_month(args.year_month)
    if ym:
        y, m = ym
    else:
        y, m = now.year, now.month
    p = month_file_path(y, m, target=target, root=root)
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


def cmd_path(args: argparse.Namespace) -> int:
    return _run_path_cmd(args, target=MonthlyTarget.AUDIT)


def cmd_diary_path(args: argparse.Namespace) -> int:
    return _run_path_cmd(args, target=MonthlyTarget.DIARY)


def _verify_monthly_files(
    base: Path,
    *,
    first_line_prefix: str,
    kind_label: str,
    strict: bool,
    allow_missing_dir: bool = False,
) -> int:
    if not base.is_dir():
        if allow_missing_dir:
            print(
                f"OK: {kind_label} ディレクトリは未作成です（初回追記で作成されます）: {base}"
            )
            return 0
        print(f"NG: {kind_label} ディレクトリがありません: {base}", file=sys.stderr)
        return 1

    errors: list[str] = []
    warnings: list[str] = []
    md_files = sorted(base.glob("*.md"))
    for p in md_files:
        if p.name.startswith("."):
            continue
        if p.name.upper() == "README.MD":
            continue
        if not re.match(r"^\d{6}\.md$", p.name):
            errors.append(f"想定外のファイル名（YYYYMM.md 以外）: {p.name}")
            continue
        text = p.read_text(encoding="utf-8")
        lines = text.splitlines()
        if not lines:
            errors.append(f"{p.name}: 空ファイル")
            continue
        if not lines[0].startswith(first_line_prefix):
            errors.append(
                f"{p.name}: 1行目が「{first_line_prefix}…」ではありません: {lines[0][:60]}"
            )
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
    print(
        f"OK: {len(md_files)} ファイルを検査 ({base}) [{kind_label}]"
        + (" [strict]" if strict else "")
    )
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    root = Path(args.repo_root).resolve() if args.repo_root else repo_root()
    strict = getattr(args, "strict", False)
    return _verify_monthly_files(
        log_dir(root),
        first_line_prefix="# 査証ログ ",
        kind_label="log",
        strict=strict,
        allow_missing_dir=False,
    )


def cmd_diary_verify(args: argparse.Namespace) -> int:
    root = Path(args.repo_root).resolve() if args.repo_root else repo_root()
    strict = getattr(args, "strict", False)
    return _verify_monthly_files(
        diary_dir(root),
        first_line_prefix="# 日記（横断ナレッジ） ",
        kind_label="diary",
        strict=strict,
        allow_missing_dir=True,
    )


def _add_append_flags(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "message",
        nargs="?",
        default=None,
        help="本文（省略時は標準入力）",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="書き込まず内容だけ表示",
    )
    p.add_argument(
        "--json",
        action="store_true",
    )
    p.add_argument(
        "--year-month",
        type=str,
        default=None,
        help="追記先ファイルの年月 YYYYMM（既定: 今日の年月）",
    )
    p.add_argument(
        "--at",
        dest="at",
        type=parse_at,
        default=None,
        help="エントリの日時（既定: 実行時刻）。YYYY-MM-DD HH:MM",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "_workingspace/log（査証ログ）および _workingspace/diary（横断ナレッジ日記）"
            "へ追記（追記モードのみ）"
        )
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="リポジトリルート（既定: 本スクリプトから自動）",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    pa = sub.add_parser("append", help="査証ログに1行追記")
    _add_append_flags(pa)
    pa.set_defaults(func=cmd_append)

    pp = sub.add_parser("path", help="指定月の査証ログファイルの絶対パスを表示")
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

    p_diary = sub.add_parser(
        "diary",
        help="横断ナレッジ日記（_workingspace/diary/YYYYMM.md）の追記・検査",
    )
    d_sub = p_diary.add_subparsers(dest="diary_action", required=True)

    da = d_sub.add_parser("append", help="日記に1行追記")
    _add_append_flags(da)
    da.set_defaults(func=cmd_diary_append)

    dp = d_sub.add_parser("path", help="指定月の日記ファイルの絶対パスを表示")
    dp.add_argument("--json", action="store_true")
    dp.add_argument(
        "--year-month",
        type=str,
        default=None,
        help="YYYYMM（既定: 今日の年月）",
    )
    dp.set_defaults(func=cmd_diary_path)

    dv = d_sub.add_parser(
        "verify",
        help="diary 配下の *.md の体裁を検査（読み取り専用）",
    )
    dv.add_argument(
        "--strict",
        action="store_true",
        help="各行を公式形式に厳密照合",
    )
    dv.set_defaults(func=cmd_diary_verify)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
