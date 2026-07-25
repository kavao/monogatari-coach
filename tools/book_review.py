#!/usr/bin/env python3
"""Review a novel's Phase 1 publishing package without changing it."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from book_package.review import review_package


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def resolve_novel_dir(value: str) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (repo_root() / path).resolve()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="出版パッケージを読み取り専用で検証する。")
    parser.add_argument("novel", help="作品フォルダ（例: novels/001_作品名）")
    parser.add_argument(
        "--gate", choices=("writing", "export"), default="writing", help="検証ゲート"
    )
    parser.add_argument(
        "--target",
        choices=("paper", "ebook", "web"),
        default=None,
        help="出力対象（省略時は book.yaml の format.primary）",
    )
    parser.add_argument("--json", action="store_true", help="JSON で出力する")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = review_package(
            resolve_novel_dir(args.novel), gate=args.gate, target=args.target
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    payload = result.to_dict()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"review: {payload['mode']} / target={payload['target']}")
        for finding in result.findings:
            print(f"[{finding.severity}] {finding.rule}: {finding.message}")
        if not result.findings:
            print("findings: none")
    return 1 if result.has_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
