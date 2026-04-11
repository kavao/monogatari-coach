#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Monogatari Coach — novel_code 採番・検証（公式用）。

.rulesync/rules/overview.md の「命名・採番ルール」に基づく:
  - novels/ 直下の作品フォルダ名から数値コードを抽出し、最大値+1 を次候補とする
  - 作品フォルダの config.md とフォルダ名・novel_ID の整合を検証できる
  - 資料上の別名を config に記載したか（見出し）を検証できる

作品フォルダの命名（厳密）:
  - 1 つ以上の数字 + アンダースコア + タイトル（任意文字）
  - 例: 051_神のダンジョンβテスター, 000_old_man_next_door's_cake

除外（採番対象外）:
  - 名前が '_' で始まるディレクトリ（例: _import）
  - 隠しディレクトリ（名前が '.' で始まる）
  - 上記パターンに一致しないディレクトリ（警告として列挙）
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

# novels/NNN_title — 先頭の整数群を novel_code として扱う
NOVEL_FOLDER_RE = re.compile(r"^(\d+)_(.+)$")

# config.md 表形式: | novel_ID | 051 |
NOVEL_ID_TABLE_RE = re.compile(
    r"^\s*\|\s*novel_ID\s*\|\s*(\d+)\s*\|\s*$",
    re.IGNORECASE | re.MULTILINE,
)

# 「資料上の別名」見出し（## / ### いずれか）
ALIAS_HEADING_RE = re.compile(
    r"^#{1,3}\s*資料上の別名\s*$",
    re.MULTILINE,
)


def repo_root_from_start(start: Path | None) -> Path:
    if start is None:
        return Path(__file__).resolve().parent.parent
    p = start.resolve()
    if p.is_file():
        p = p.parent
    return p


def scan_novels(novels_root: Path) -> dict[str, Any]:
    if not novels_root.is_dir():
        return {
            "error": f"not a directory: {novels_root}",
            "codes": [],
            "max_code": None,
            "next_code": 1,
            "next_code_padded": "001",
            "pad_width": 3,
            "skipped": [],
            "unmatched": [],
            "duplicates": [],
        }

    entries: list[dict[str, Any]] = []
    skipped: list[str] = []
    unmatched: list[str] = []

    for child in sorted(novels_root.iterdir()):
        name = child.name
        if not child.is_dir():
            continue
        if name.startswith("."):
            skipped.append(name)
            continue
        if name.startswith("_"):
            skipped.append(name)
            continue
        m = NOVEL_FOLDER_RE.match(name)
        if not m:
            unmatched.append(name)
            continue
        code = int(m.group(1))
        title_rest = m.group(2)
        entries.append(
            {
                "code": code,
                "folder": name,
                "title_suffix": title_rest,
                "path": str(child.as_posix()),
            }
        )

    codes = [e["code"] for e in entries]
    code_to_names: dict[int, list[str]] = {}
    for e in entries:
        code_to_names.setdefault(e["code"], []).append(e["folder"])

    duplicates = [
        {"code": c, "folders": names}
        for c, names in sorted(code_to_names.items())
        if len(names) > 1
    ]

    max_code = max(codes) if codes else None
    next_num = (max_code + 1) if max_code is not None else 1
    pad_width = 3
    if codes:
        pad_width = max(3, len(str(max(codes))), len(str(next_num)))

    result: dict[str, Any] = {
        "novels_root": str(novels_root.as_posix()),
        "entries": sorted(entries, key=lambda x: (x["code"], x["folder"])),
        "max_code": max_code,
        "next_code": next_num,
        "next_code_padded": str(next_num).zfill(pad_width),
        "pad_width": pad_width,
        "skipped": skipped,
        "unmatched": unmatched,
        "duplicates": duplicates,
    }
    return result


def read_novel_id_from_config(config_path: Path) -> int | None:
    if not config_path.is_file():
        return None
    text = config_path.read_text(encoding="utf-8")
    m = NOVEL_ID_TABLE_RE.search(text)
    if not m:
        return None
    return int(m.group(1))


def parse_folder_code(folder_name: str) -> int | None:
    m = NOVEL_FOLDER_RE.match(folder_name)
    if not m:
        return None
    return int(m.group(1))


def verify_work_dir(work: Path) -> dict[str, Any]:
    work = work.resolve()
    if not work.is_dir():
        return {"ok": False, "error": f"not a directory: {work}"}

    folder_code = parse_folder_code(work.name)
    config = work / "config.md"
    novel_id = read_novel_id_from_config(config)

    issues: list[str] = []
    if folder_code is None:
        issues.append(
            f"フォルダ名が採番規則に一致しません（期待: 数字_タイトル）: {work.name!r}"
        )

    if novel_id is None:
        issues.append(
            f"config.md から novel_ID を表形式で読み取れませんでした: {config}"
        )
    elif folder_code is not None and novel_id != folder_code:
        issues.append(
            f"novel_ID ({novel_id}) がフォルダ名の先頭番号 ({folder_code}) と一致しません"
        )

    alias_ok = False
    if config.is_file():
        body = config.read_text(encoding="utf-8")
        alias_ok = bool(ALIAS_HEADING_RE.search(body))

    return {
        "ok": len(issues) == 0,
        "path": str(work.as_posix()),
        "folder_code": folder_code,
        "novel_id_from_config": novel_id,
        "config_path": str(config.as_posix()),
        "has_alias_heading": alias_ok,
        "issues": issues,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="novels/ の novel_code 採番（最大+1）と config 検証"
    )
    parser.add_argument(
        "--novels-dir",
        type=Path,
        default=None,
        help="novels ディレクトリ（既定: リポジトリルート/novels）",
    )
    sub = parser.add_subparsers(dest="command", help="サブコマンド")

    p_scan = sub.add_parser("scan", help="採番スキャン結果を表示（既定）")
    p_scan.add_argument(
        "--json",
        action="store_true",
        help="JSON で出力",
    )

    p_next = sub.add_parser("next", help="次の novel_code（数値とゼロ埋め）のみ出力")
    p_next.add_argument(
        "--json",
        action="store_true",
    )

    p_verify = sub.add_parser(
        "verify",
        help="作品フォルダの config.md とフォルダ名の整合を検証",
    )
    p_verify.add_argument(
        "work_dir",
        type=Path,
        help="novels/NNN_作品名 へのパス",
    )
    p_verify.add_argument(
        "--require-alias",
        action="store_true",
        help="config.md に「資料上の別名」見出しがあることを必須にする",
    )
    p_verify.add_argument(
        "--json",
        action="store_true",
    )

    args = parser.parse_args(argv)

    root = repo_root_from_start(None)
    novels_root = args.novels_dir
    if novels_root is None:
        novels_root = root / "novels"
    else:
        novels_root = novels_root.resolve()

    cmd = args.command
    if cmd is None:
        # 互換: 引数なしは scan
        data = scan_novels(novels_root)
        _print_scan_text(data)
        return 0 if not data.get("error") else 1

    if cmd == "scan":
        data = scan_novels(novels_root)
        if args.json:
            print(json.dumps(data, ensure_ascii=False, indent=2))
        else:
            _print_scan_text(data)
        return 0 if not data.get("error") else 1

    if cmd == "next":
        data = scan_novels(novels_root)
        if data.get("error"):
            print(data["error"], file=sys.stderr)
            return 1
        if args.json:
            print(
                json.dumps(
                    {
                        "next_code": data["next_code"],
                        "next_code_padded": data["next_code_padded"],
                        "pad_width": data["pad_width"],
                        "max_code": data["max_code"],
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            print(data["next_code_padded"])
        return 0

    if cmd == "verify":
        r = verify_work_dir(args.work_dir)
        if args.require_alias and r.get("ok") and not r.get("has_alias_heading"):
            r = dict(r)
            r["ok"] = False
            r.setdefault("issues", []).append(
                'config.md に見出し「資料上の別名」（## または ###）がありません'
            )
        if args.json:
            print(json.dumps(r, ensure_ascii=False, indent=2))
        else:
            for line in r.get("issues") or []:
                print(f"NG: {line}", file=sys.stderr)
            if r.get("ok"):
                print(f"OK: {r['path']}")
                print(f"  novel_ID / フォルダ番号: {r.get('novel_id_from_config')}")
                if r.get("has_alias_heading"):
                    print("  資料上の別名: 見出しあり")
                else:
                    print("  資料上の別名: 見出しなし（揺れが無ければ省略可）")
            else:
                if not r.get("issues"):
                    print(r.get("error", "verify failed"), file=sys.stderr)
        return 0 if r.get("ok") else 1

    return 1


def _print_scan_text(data: dict[str, Any]) -> None:
    if data.get("error"):
        print(data["error"], file=sys.stderr)
        return
    print(f"novels_root: {data['novels_root']}")
    print(f"max_code: {data['max_code']}")
    print(
        f"next_code: {data['next_code']} (folder prefix suggestion: {data['next_code_padded']}_<title>)"
    )
    print(f"pad_width: {data['pad_width']}")
    if data["duplicates"]:
        print("WARNING: duplicate code numbers in different folders:")
        for d in data["duplicates"]:
            print(f"  code {d['code']}: {d['folders']}")
    if data["skipped"]:
        print("skipped (_* or .*):", ", ".join(data["skipped"]))
    if data["unmatched"]:
        print("unmatched (not NNN_title pattern):", ", ".join(data["unmatched"]))
    print("entries:")
    for e in data["entries"]:
        print(f"  {e['code']:>5}  {e['folder']}")


if __name__ == "__main__":
    raise SystemExit(main())
