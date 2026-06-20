#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""新規作品のオンボーディング: 採番→フォルダ作成→scaffold→check→次の一言。

Usage:
    # 作品名から自動採番してフォルダを作成する
    python tools/novel_onboard.py "作品名"

    # フルパスを指定（コードはパスから取得）
    python tools/novel_onboard.py novels/067_作品名

    # 実行前に採番とフォルダパスだけ確認する
    python tools/novel_onboard.py "作品名" --dry-run
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from novel_code_allocate import scan_novels  # noqa: E402
from novel_scaffold import bootstrap_novel   # noqa: E402
from novel_status import (                  # noqa: E402
    _run_project_check,
    determine_next_step,
)

_NOVEL_FOLDER_RE = re.compile(r"^(\d+)_(.+)$")

_W = 52


def _encode_fix() -> None:
    from console_io import configure_stdio_utf8

    configure_stdio_utf8()


def repo_root() -> Path:
    return _TOOLS_DIR.parent


def _title_to_dirname(title: str) -> str:
    """作品名を novels/ フォルダ名に使える形に変換する（空白→_）。"""
    return re.sub(r"[\s　]+", "_", title.strip())


def resolve_target(raw: str, root: Path) -> tuple[int, Path]:
    """入力文字列から (novel_code, novel_dir) を決定する。

    - "novels/067_作品名" のようなパス → コードをパスから取得
    - "作品名" のような文字列 → novels/ を走査して次のコードを採番
    """
    p = Path(raw)

    # novels/ 配下のパスとして解釈できるか試みる
    if "/" in raw or "\\" in raw or (p.parts and p.parts[0] == "novels"):
        resolved = (root / p).resolve() if not p.is_absolute() else p.resolve()
        m = _NOVEL_FOLDER_RE.match(resolved.name)
        if m:
            return int(m.group(1)), resolved
        # パスが与えられたが NNN_ 形式でない → エラー
        raise ValueError(
            f"フォルダ名が 'NNN_タイトル' 形式ではありません: {resolved.name}\n"
            "例: novels/067_新作タイトル"
        )

    # 作品名として扱い、自動採番する
    novels_root = root / "novels"
    scan = scan_novels(novels_root)
    next_code: int = scan["next_code"]
    dirname = f"{next_code:03d}_{_title_to_dirname(raw)}"
    return next_code, (novels_root / dirname).resolve()


def main(argv: list[str] | None = None) -> int:
    _encode_fix()

    p = argparse.ArgumentParser(
        description=(
            "新規作品のオンボーディング: "
            "採番→フォルダ作成→scaffold→project check→次の一言"
        )
    )
    p.add_argument(
        "target",
        help=(
            "作品名（例: '霧の彼方の灯台'）または作品フォルダパス"
            "（例: novels/067_霧の彼方の灯台）"
        ),
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="採番とフォルダパスを表示するだけで、実際には何も作成しない",
    )
    args = p.parse_args(argv)

    root = repo_root()

    try:
        novel_code, novel_dir = resolve_target(args.target, root)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    print(f"\n  {'═' * _W}")
    print(f"  novel onboard")
    print(f"  {'═' * _W}")
    print(f"  novel_code : {novel_code:03d}")
    print(f"  フォルダ   : {novel_dir.relative_to(root)}")

    if args.dry_run:
        print(f"\n  [dry-run] 上記フォルダを作成して scaffold を実行します。")
        print(f"  実行するには --dry-run を外してください。")
        print(f"\n  {'═' * _W}\n")
        return 0

    print()

    # ── フォルダ作成 + scaffold
    novel_dir.mkdir(parents=True, exist_ok=True)
    try:
        actions = bootstrap_novel(novel_dir, root)
    except FileNotFoundError as e:
        print(f"error: scaffold 失敗: {e}", file=sys.stderr)
        return 2

    print("  scaffold")
    print(f"  {'─' * (_W - 2)}")
    for rel, status in actions:
        mark = "+" if "created" in status else "="
        print(f"  [{mark}] {rel}  ({status})")

    # ── project check
    print(f"\n  プロジェクト状態")
    print(f"  {'─' * (_W - 2)}")
    check = _run_project_check(novel_dir)
    if check.get("ok"):
        print("  [OK]  必須ファイル・ディレクトリが揃っています")
    else:
        print("  [NG]")
        for f in check.get("required_files", []):
            if not f.get("ok"):
                print(f"    ! 不足: {f['name']}")
        for d in check.get("required_dirs", []):
            if not d.get("ok"):
                print(f"    ! 不足: {d['name']}/")
        if check.get("issues"):
            for issue in check["issues"]:
                print(f"    ! {issue}")

    # ── 次の一言
    print(f"\n  次の一言")
    print(f"  {'─' * (_W - 2)}")
    label, suggestion = determine_next_step(novel_dir)
    print(f"  [{label}]")
    print(f"  → {suggestion}")

    print(f"\n  {'═' * _W}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
