#!/usr/bin/env python3
"""Freeze a reviewed Phase 1 publishing package into book.lock.yaml."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from book_package.lock import LockError, write_lock


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def resolve_novel_dir(value: str) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (repo_root() / path).resolve()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="export ゲート通過後の出版入力を lockfile に凍結する。")
    parser.add_argument("novel", help="作品フォルダ")
    parser.add_argument("--target", choices=("paper", "ebook", "web"), required=True)
    args = parser.parse_args(argv)
    try:
        path = write_lock(resolve_novel_dir(args.novel), target=args.target)
    except (LockError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
