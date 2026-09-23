#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Monogatari Coach 小説本文の文字数カウント（公式用）。

「文字数」定義:
  - ファイルを UTF-8 で読み、Unicode 正規形 NFC に揃えたうえで、
    コードポイント（Python str の要素）1 つを 1 文字と数える。
  - 全角の仮名・漢字・全角記号はそれぞれ 1 文字。
  - Markdown の # や半角英数字・記号も、表示上の 1 コードポイントごとに 1 文字。

オプションで YAML フロントマター（先頭の --- ... ---）を除外できる（既定: 除外）。
"""

from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from pathlib import Path


# 出版パッケージが本文のアンカーとして使う行コメント。組版・画像配置のための
# 構造情報であり、読者が読む本文文字数には含めない。任意の HTML コメントまで
# 除外しないよう、許可した 2 種類だけを対象にする。
_PUBLISHING_DIRECTIVE = re.compile(
    r"(?m)^[ \t]*<!--\s*(?:"
    r"scene:\s*ch\d{2,}-\d{3,}"
    r"|illustration:\s*[a-z][a-z0-9_]*"
    r")\s*-->[ \t]*(?:\r?\n)?"
)


def strip_yaml_front_matter(text: str) -> str:
    if not text.startswith("---"):
        return text
    lines = text.splitlines(keepends=True)
    if not lines:
        return text
    if lines[0].strip() != "---":
        return text
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return "".join(lines[i + 1 :])
    return text


def count_chars(text: str, *, strip_fm: bool) -> int:
    body = strip_yaml_front_matter(text) if strip_fm else text
    body = _PUBLISHING_DIRECTIVE.sub("", body)
    normalized = unicodedata.normalize("NFC", body)
    return len(normalized)


def collect_targets(paths: list[Path], repo_root: Path) -> list[Path]:
    files: list[Path] = []
    novels_root = repo_root / "novels"

    for raw in paths:
        p = raw.resolve()
        if p.is_file():
            if p.suffix.lower() == ".md":
                files.append(p)
            continue
        if not p.is_dir():
            continue

        nt = p / "_novel_text"
        if nt.is_dir():
            files.extend(sorted(nt.glob("novel_text*.md")))
            continue

        if p.name == "_novel_text" or "_novel_text" in p.parts:
            files.extend(sorted(p.glob("novel_text*.md")))
            continue

        # リポジトリルートが渡された場合は novels/ 配下のみを対象にする
        scan_novels = novels_root if p.resolve() == repo_root else p
        if scan_novels == novels_root and novels_root.is_dir():
            for novel_dir in sorted(novels_root.iterdir()):
                if not novel_dir.is_dir():
                    continue
                if novel_dir.name.startswith("_"):
                    continue
                sub = novel_dir / "_novel_text"
                if sub.is_dir():
                    files.extend(sorted(sub.glob("novel_text*.md")))

    seen: set[Path] = set()
    unique: list[Path] = []
    for f in files:
        rp = f.resolve()
        if rp not in seen:
            seen.add(rp)
            unique.append(rp)
    return sorted(unique)


def discover_all_novel_text(repo_root: Path) -> list[Path]:
    novels = repo_root / "novels"
    if not novels.is_dir():
        return []
    return collect_targets([novels], repo_root)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="小説 Markdown の文字数（Unicode コードポイント、NFC）を数える。"
    )
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="ファイル、作品フォルダ（_novel_text を内包）、または novels 配下のパス",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="novels/ 以下の全作品の _novel_text/novel_text*.md を対象にする",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="リポジトリルート（未指定時は本スクリプトの親の親）",
    )
    parser.add_argument(
        "--keep-front-matter",
        action="store_true",
        help="YAML フロントマターを本文に含めて数える（既定は除外）",
    )
    args = parser.parse_args()

    script_dir = Path(__file__).resolve().parent
    repo_root = (args.repo_root or script_dir.parent).resolve()

    if args.all:
        targets = discover_all_novel_text(repo_root)
    elif args.paths:
        targets = collect_targets(args.paths, repo_root)
    else:
        parser.print_help()
        print(
            "\n例: python tools/novel_char_count.py novels/050_作品名",
            file=sys.stderr,
        )
        print(
            "    python tools/novel_char_count.py --all",
            file=sys.stderr,
        )
        return 2

    if not targets:
        print("対象となる novel_text*.md が見つかりません。", file=sys.stderr)
        return 1

    strip_fm = not args.keep_front_matter
    grand = 0
    for md in targets:
        try:
            text = md.read_text(encoding="utf-8")
        except OSError as e:
            print(f"読み込み失敗: {md}: {e}", file=sys.stderr)
            return 1
        n = count_chars(text, strip_fm=strip_fm)
        grand += n
        try:
            rel = md.relative_to(repo_root)
        except ValueError:
            rel = md
        print(f"{n:6d}  {rel.as_posix()}")

    print(f"{'─' * 40}")
    print(f"{grand:6d}  合計 ({len(targets)} ファイル)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
