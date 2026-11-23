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
  - 改訂枝は数字の直後に英小文字 1 文字を密着させる: 051a_タイトル
    （code は 51 のまま。分岐は次番号を消費しない。051ab_ / 051A_ は不正）

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
from dataclasses import dataclass
from typing import Any

# novels/NNN_title または NNNb_title — 先頭の整数群を novel_code、直後の英小文字1文字を枝とする
NOVEL_FOLDER_RE = re.compile(r"^(?P<code>\d+)(?P<branch>[a-z])?_(?P<title>.+)$")

# 枝の形に見えるが規則外（051ab_ / 051A_ など）。unmatched と分けて知らせる
_BRANCHISH_RE = re.compile(r"^\d+[A-Za-z]+_.+$")

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


def _table_value_re(key: str) -> re.Pattern[str]:
    return re.compile(
        rf"^\s*\|\s*{re.escape(key)}\s*\|\s*([^|]*?)\s*\|\s*$",
        re.MULTILINE,
    )


BRANCH_TABLE_RE = _table_value_re("branch")
PARENT_ID_TABLE_RE = _table_value_re("parent_ID")
BRANCH_REASON_TABLE_RE = _table_value_re("branch_reason")
BRANCH_REASONS = ("revision", "compare")


@dataclass(frozen=True)
class FolderName:
    """作品フォルダ名の解析結果。code は int、digits は元の桁（ゼロ埋め）を保つ。"""

    code: int
    digits: str
    branch: str | None
    title: str

    @property
    def label(self) -> str:
        """表示用の番号（051 / 051a）。"""
        return f"{self.digits}{self.branch or ''}"


def parse_folder_name(folder_name: str) -> FolderName | None:
    """作品フォルダ名を解析する。規則外は None（051ab_ / 051A_ も None）。"""
    m = NOVEL_FOLDER_RE.match(folder_name)
    if not m:
        return None
    return FolderName(
        code=int(m.group("code")),
        digits=m.group("code"),
        branch=m.group("branch"),
        title=m.group("title"),
    )


def is_invalid_branch_name(folder_name: str) -> bool:
    """枝の形に見えるが規則外の名前か（051ab_ / 051A_）。"""
    return parse_folder_name(folder_name) is None and bool(_BRANCHISH_RE.match(folder_name))


def read_table_value(text: str, pattern: re.Pattern[str]) -> str | None:
    """config.md 表の値を読む。行なし・空は None。複数行は最初の値。"""
    m = pattern.search(text)
    if not m:
        return None
    value = m.group(1).strip()
    return value or None


def find_trunk_folders(novels_root: Path, code: int) -> list[Path]:
    """同じ code の元（枝なし）フォルダを列挙する。"""
    if not novels_root.is_dir():
        return []
    found: list[Path] = []
    for child in sorted(novels_root.iterdir()):
        if not child.is_dir():
            continue
        parsed = parse_folder_name(child.name)
        if parsed and parsed.code == code and parsed.branch is None:
            found.append(child)
    return found


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
            "invalid_branch": [],
            "duplicates": [],
            "orphan_branches": [],
        }

    entries: list[dict[str, Any]] = []
    skipped: list[str] = []
    unmatched: list[str] = []
    invalid_branch: list[str] = []

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
        parsed = parse_folder_name(name)
        if parsed is None:
            if is_invalid_branch_name(name):
                invalid_branch.append(name)
            else:
                unmatched.append(name)
            continue
        entries.append(
            {
                "code": parsed.code,
                "branch": parsed.branch,
                "folder": name,
                "title_suffix": parsed.title,
                "path": str(child.as_posix()),
            }
        )

    codes = [e["code"] for e in entries]
    # 同じ code でも branch が違えば別稿（元と改訂枝）。重複は同じ code かつ同じ branch だけ
    key_to_names: dict[tuple[int, str], list[str]] = {}
    for e in entries:
        key_to_names.setdefault((e["code"], e["branch"] or ""), []).append(e["folder"])

    duplicates = [
        {"code": c, "branch": b or None, "folders": names}
        for (c, b), names in sorted(key_to_names.items())
        if len(names) > 1
    ]
    trunk_codes = {e["code"] for e in entries if not e["branch"]}
    orphan_branches = [
        e["folder"] for e in entries if e["branch"] and e["code"] not in trunk_codes
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
        "invalid_branch": invalid_branch,
        "duplicates": duplicates,
        "orphan_branches": orphan_branches,
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
    parsed = parse_folder_name(folder_name)
    return parsed.code if parsed else None


def verify_work_dir(work: Path) -> dict[str, Any]:
    work = work.resolve()
    if not work.is_dir():
        return {"ok": False, "error": f"not a directory: {work}"}

    parsed = parse_folder_name(work.name)
    folder_code = parsed.code if parsed else None
    folder_branch = parsed.branch if parsed else None
    config = work / "config.md"
    novel_id = read_novel_id_from_config(config)
    body = config.read_text(encoding="utf-8") if config.is_file() else ""

    issues: list[str] = []
    warnings: list[str] = []
    if parsed is None:
        if is_invalid_branch_name(work.name):
            issues.append(
                "フォルダ名の枝が規則外です（期待: 数字の直後に英小文字1文字、例 051a_タイトル）: "
                f"{work.name!r}"
            )
        else:
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

    config_branch = read_table_value(body, BRANCH_TABLE_RE)
    parent_raw = read_table_value(body, PARENT_ID_TABLE_RE)
    branch_reason = read_table_value(body, BRANCH_REASON_TABLE_RE)
    parent_folders: list[str] = []

    if parsed is not None:
        if (config_branch or None) != folder_branch:
            issues.append(
                f"config.md の branch ({config_branch or 'なし'}) がフォルダ名の枝 "
                f"({folder_branch or 'なし'}) と一致しません"
            )
        if folder_branch is None:
            if parent_raw is not None:
                issues.append("元フォルダ（枝なし）の config.md に parent_ID があります")
        else:
            if parent_raw is None:
                issues.append("改訂枝の config.md に parent_ID がありません")
            elif not parent_raw.isdigit() or int(parent_raw) != folder_code:
                issues.append(
                    f"parent_ID ({parent_raw}) がフォルダ名の先頭番号 ({folder_code}) と一致しません"
                )
            if branch_reason is None:
                issues.append(
                    "改訂枝の config.md に branch_reason（revision / compare）がありません"
                )
            elif branch_reason not in BRANCH_REASONS:
                issues.append(
                    f"branch_reason が未知の値です（revision / compare）: {branch_reason!r}"
                )
            trunks = find_trunk_folders(work.parent, folder_code)
            parent_folders = [t.name for t in trunks]
            if not trunks:
                issues.append(
                    f"同じ番号の元フォルダ（{parsed.digits}_…）が {work.parent.as_posix()} にありません"
                )
            elif len(trunks) > 1:
                warnings.append(
                    "同じ番号の元フォルダが複数あります（どれが元か parent の名前で確かめる）: "
                    + ", ".join(parent_folders)
                )
        # 同じ code かつ同じ branch の兄弟
        same = [
            c.name
            for c in sorted(work.parent.iterdir())
            if c.is_dir()
            and c.resolve() != work
            and (p := parse_folder_name(c.name)) is not None
            and p.code == folder_code
            and p.branch == folder_branch
        ]
        if same and folder_branch is not None:
            issues.append(
                f"同じ番号・同じ枝のフォルダがほかにあります: {', '.join(same)}"
            )

    alias_ok = bool(ALIAS_HEADING_RE.search(body))

    return {
        "ok": len(issues) == 0,
        "path": str(work.as_posix()),
        "folder_code": folder_code,
        "folder_branch": folder_branch,
        "label": parsed.label if parsed else None,
        "novel_id_from_config": novel_id,
        "branch_from_config": config_branch,
        "parent_id_from_config": parent_raw,
        "branch_reason": branch_reason,
        "parent_folders": parent_folders,
        "config_path": str(config.as_posix()),
        "has_alias_heading": alias_ok,
        "issues": issues,
        "warnings": warnings,
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
            for line in r.get("warnings") or []:
                print(f"WARNING: {line}", file=sys.stderr)
            if r.get("ok"):
                print(f"OK: {r['path']}")
                print(f"  novel_ID / フォルダ番号: {r.get('novel_id_from_config')}")
                if r.get("folder_branch"):
                    print(
                        f"  改訂枝: {r['label']}（parent_ID {r.get('parent_id_from_config')}, "
                        f"branch_reason {r.get('branch_reason')}, 元: {', '.join(r.get('parent_folders') or [])}）"
                    )
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
            branch = f" branch {d['branch']}" if d.get("branch") else ""
            print(f"  code {d['code']}{branch}: {d['folders']}")
    if data.get("invalid_branch"):
        print(
            "WARNING: invalid branch suffix (expected one lowercase letter, e.g. 051a_title):",
            ", ".join(data["invalid_branch"]),
        )
    if data.get("orphan_branches"):
        print(
            "WARNING: branch folders without a trunk folder of the same code:",
            ", ".join(data["orphan_branches"]),
        )
    if data["skipped"]:
        print("skipped (_* or .*):", ", ".join(data["skipped"]))
    if data["unmatched"]:
        print("unmatched (not NNN_title pattern):", ", ".join(data["unmatched"]))
    print("entries:")
    for e in data["entries"]:
        branch = e.get("branch") or ""
        print(f"  {e['code']:>5}{branch:<1}  {e['folder']}")


if __name__ == "__main__":
    raise SystemExit(main())
