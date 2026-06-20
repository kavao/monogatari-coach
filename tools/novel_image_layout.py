#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Monogatari Coach — 作品フォルダ内の「タグ用・漫画用・挿絵用」画像ストックディレクトリを用意する。

.rulesync/rules/overview.md の Tag Mode / Manga Tag Mode「画像ストック」に基づく:
  - tag/<romaji>.md と同名の tag/<romaji>/ にキャラ画像を集約
  - manga/manga_XX.md ごとに manga/_assets/manga_XX/comic/ と backgrounds/ を用意（任意で comic/k01..）
  - illustrations/pages/illustration_XX_pYY.yaml ごとに illustrations/_assets/illustration_XX/ を用意
  - illustrations/plans/ を用意（挿絵計画 MD 用。illustrations/ または pages/*.yaml があるとき）

作成のみ（Markdown の内容や画像ファイルの移動は行わない）。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def resolve_novel_dir(arg: str) -> Path:
    p = Path(arg).expanduser()
    if not p.is_absolute():
        p = repo_root() / p
    return p.resolve()


def k_width(panels: int) -> int:
    return max(2, len(str(max(panels, 1))))


def scaffold_tag_dirs(novel: Path) -> list[Path]:
    tag = novel / "tag"
    created: list[Path] = []
    if not tag.is_dir():
        return created
    for f in sorted(tag.glob("*.md")):
        sub = tag / f.stem
        sub.mkdir(parents=True, exist_ok=True)
        created.append(sub)
    return created


def scaffold_manga_dirs(novel: Path, panels: int | None) -> list[Path]:
    manga = novel / "manga"
    created: list[Path] = []
    if not manga.is_dir():
        return created
    assets = manga / "_assets"
    width = k_width(panels) if panels else 2
    for f in sorted(manga.glob("manga_*.md")):
        stem = f.stem
        base = assets / stem
        comic = base / "comic"
        backgrounds = base / "backgrounds"
        comic.mkdir(parents=True, exist_ok=True)
        backgrounds.mkdir(parents=True, exist_ok=True)
        created.extend([comic, backgrounds])
        if panels is not None and panels > 0:
            for i in range(1, panels + 1):
                kdir = comic / f"k{i:0{width}d}"
                kdir.mkdir(parents=True, exist_ok=True)
                created.append(kdir)
    return created


def illustration_asset_stem(path: Path) -> str:
    return re.sub(r"_p\d+$", "", path.stem)


def illustration_page_files(novel: Path) -> list[Path]:
    pages = novel / "illustrations" / "pages"
    if not pages.is_dir():
        return []
    return sorted(pages.glob("illustration_*.yaml"))


def scaffold_illustration_plans(novel: Path) -> list[Path]:
    """illustrations/plans/ と pages/ を用意（挿絵 IR・計画 MD 用）。"""
    created: list[Path] = []
    pages = illustration_page_files(novel)
    ill = novel / "illustrations"
    if not ill.is_dir() and not pages:
        return created
    if not ill.is_dir():
        ill.mkdir(parents=True, exist_ok=True)
        created.append(ill)
    for name in ("plans", "pages"):
        sub = ill / name
        existed = sub.is_dir()
        sub.mkdir(parents=True, exist_ok=True)
        if not existed:
            created.append(sub)
    return created


def scaffold_illustration_dirs(novel: Path) -> list[Path]:
    created: list[Path] = []
    pages = illustration_page_files(novel)
    if not pages:
        return created
    assets = novel / "illustrations" / "_assets"
    for stem in sorted({illustration_asset_stem(path) for path in pages}):
        base = assets / stem
        base.mkdir(parents=True, exist_ok=True)
        created.append(base)
    return created


def cmd_scaffold(args: argparse.Namespace) -> int:
    novel = resolve_novel_dir(args.novel)
    if not novel.is_dir():
        print(f"error: not a directory: {novel}", file=sys.stderr)
        return 2
    panels = args.panels
    tag_paths = scaffold_tag_dirs(novel)
    manga_paths = scaffold_manga_dirs(novel, panels)
    illustration_paths = scaffold_illustration_plans(novel) + scaffold_illustration_dirs(novel)
    print(f"novel: {novel}")
    print(f"created/updated: {len(tag_paths) + len(manga_paths) + len(illustration_paths)} paths")
    if args.verbose:
        for p in tag_paths + manga_paths + illustration_paths:
            print(f"  {p}")
    return 0


def cmd_paths(args: argparse.Namespace) -> int:
    novel = resolve_novel_dir(args.novel)
    if not novel.is_dir():
        print(f"error: not a directory: {novel}", file=sys.stderr)
        return 2
    panels = args.panels
    tag = novel / "tag"
    if tag.is_dir():
        print("# tag - output_dir に使うパス（キャラ別）")
        for f in sorted(tag.glob("*.md")):
            print((tag / f.stem).as_posix())
    manga = novel / "manga"
    if manga.is_dir():
        print("# manga - output_dir（コマ・ページは comic/、背景資料は backgrounds/）")
        width = k_width(panels) if panels else 2
        for f in sorted(manga.glob("manga_*.md")):
            stem = f.stem
            base = (manga / "_assets" / stem).as_posix()
            print(f"{base}/comic")
            print(f"{base}/backgrounds")
            if panels is not None and panels > 0:
                for i in range(1, panels + 1):
                    print(f"{base}/comic/k{i:0{width}d}")
    illustration_pages = illustration_page_files(novel)
    ill = novel / "illustrations"
    if ill.is_dir() or illustration_pages:
        print("# illustrations - 計画・YAML・output_dir")
        print((ill / "plans").as_posix())
        print((ill / "pages").as_posix())
    if illustration_pages:
        print("# illustrations - output_dir（挿絵・表紙）")
        assets = novel / "illustrations" / "_assets"
        for stem in sorted({illustration_asset_stem(path) for path in illustration_pages}):
            print((assets / stem).as_posix())
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="novel フォルダ内に tag/<romaji>/、manga/_assets/<manga_XX>/{comic,backgrounds}/、illustrations/{plans,pages,_assets}/ を作成・列挙する。"
    )
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("scaffold", help="ディレクトリを作成する")
    s.add_argument("novel", help="作品フォルダ（例: novels/051_タイトル）")
    s.add_argument(
        "--panels",
        type=int,
        default=None,
        metavar="N",
        help="各 manga_XX について k01..kN サブフォルダも作成（0 以下でコマ別フォルダは作らない）",
    )
    s.add_argument("-v", "--verbose", action="store_true", help="作成したパスをすべて表示")
    s.set_defaults(func=cmd_scaffold)

    q = sub.add_parser("paths", help="推奨 output_dir の一覧を表示（作成しない）")
    q.add_argument("novel", help="作品フォルダ")
    q.add_argument(
        "--panels",
        type=int,
        default=None,
        metavar="N",
        help="paths に k01..kN を含める（manga 用）",
    )
    q.set_defaults(func=cmd_paths)

    return p


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
