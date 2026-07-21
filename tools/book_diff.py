#!/usr/bin/env python3
"""List publishing-package input changes since book.lock.yaml."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from book_package.diff import LockDiffError, diff_against_lock


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def resolve_novel_dir(value: str) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (repo_root() / path).resolve()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="book.lock.yaml との差分を表示する。")
    parser.add_argument("novel", help="作品フォルダ")
    parser.add_argument("--against", choices=("lock",), required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        payload = diff_against_lock(resolve_novel_dir(args.novel))
    except (LockDiffError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for category in ("added", "removed", "changed"):
            print(f"{category}:")
            for path in payload[category]:
                print(f"  {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
