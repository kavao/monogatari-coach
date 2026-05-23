#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
新規作品フォルダの初期ディレクトリと ``_meta.yaml`` を雛形から作成する。

Plan Mode / Source Material Intake で ``_meta.md`` と併せて実行する想定。
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from novel_meta_yaml import (  # noqa: E402
    LEGACY_META_YML_FILENAME,
    META_YAML_FILENAME,
    META_YAML_TEMPLATE,
)

BOOTSTRAP_DIRS = (
    "_novel_text",
    "_reader",
    "references/novelai",
)

REFERENCES_README = """# 本作品の NovelAI ポーション

`.naiv4vibebundle` をこのフォルダに置き、`_meta.yaml` の `novelai.portions` で `path` を指す。

横断既定は `_how_to/image_refs/novelai/`（`_meta.yaml` の `cross_flat` など）。
"""


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def resolve_novel_dir(raw: Path, root: Path) -> Path:
    novel = raw if raw.is_absolute() else (root / raw)
    return novel.resolve()


def scaffold_meta_yaml(
    novel_dir: Path,
    root: Path,
    *,
    force: bool = False,
) -> tuple[Path | None, str]:
    """``_meta.yaml`` を雛形から作成。既存時は ``force`` 以外スキップ。"""
    dest = novel_dir / META_YAML_FILENAME
    legacy = novel_dir / LEGACY_META_YML_FILENAME
    if dest.is_file() and not force:
        return None, "skip (exists)"
    if legacy.is_file() and not dest.is_file() and not force:
        legacy.rename(dest)
        return dest, "renamed from _meta.yml"
    template = root / META_YAML_TEMPLATE
    if not template.is_file():
        raise FileNotFoundError(f"template not found: {template}")
    novel_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(template, dest)
    return dest, "created from template"


def scaffold_references_readme(novel_dir: Path) -> tuple[Path | None, str]:
    readme = novel_dir / "references" / "novelai" / "README.md"
    if readme.is_file():
        return None, "skip (exists)"
    readme.parent.mkdir(parents=True, exist_ok=True)
    readme.write_text(REFERENCES_README, encoding="utf-8")
    return readme, "created"


def bootstrap_novel(
    novel_dir: Path,
    root: Path,
    *,
    force_meta: bool = False,
) -> list[tuple[str, str]]:
    """執筆前ブートストラップ（ディレクトリ + _meta.yaml + references README）。"""
    actions: list[tuple[str, str]] = []
    novel_dir.mkdir(parents=True, exist_ok=True)

    for rel in BOOTSTRAP_DIRS:
        p = novel_dir / rel
        if p.is_dir():
            actions.append((str(p.relative_to(novel_dir)), "skip (exists)"))
        else:
            p.mkdir(parents=True, exist_ok=True)
            actions.append((str(p.relative_to(novel_dir)), "created"))

    path, status = scaffold_meta_yaml(novel_dir, root, force=force_meta)
    if path is not None:
        actions.append((META_YAML_FILENAME, status))
    else:
        actions.append((META_YAML_FILENAME, status))

    path, status = scaffold_references_readme(novel_dir)
    if path is not None:
        actions.append(("references/novelai/README.md", status))

    return actions


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    p = argparse.ArgumentParser(
        description="作品フォルダに _meta.yaml・references/novelai/・必須ディレクトリを雛形から作成"
    )
    p.add_argument("novel_dir", type=Path, help="novels/NNN_作品名")
    p.add_argument(
        "--force-meta",
        action="store_true",
        help=f"既存の {META_YAML_FILENAME} を雛形で上書きする",
    )
    p.add_argument(
        "--meta-only",
        action="store_true",
        help="_meta.yaml のみ作成（ディレクトリは作らない）",
    )
    args = p.parse_args(argv)

    root = repo_root()
    novel = resolve_novel_dir(args.novel_dir, root)
    if not novel.is_dir() and not args.meta_only:
        print(f"error: ディレクトリがありません: {novel}", file=sys.stderr)
        return 2

    print(f"novel: {novel}")
    if args.meta_only:
        try:
            path, status = scaffold_meta_yaml(novel, root, force=args.force_meta)
        except FileNotFoundError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        print(f"  {META_YAML_FILENAME}: {status}" + (f" -> {path}" if path else ""))
        return 0

    try:
        actions = bootstrap_novel(novel, root, force_meta=args.force_meta)
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    for rel, status in actions:
        print(f"  {rel}: {status}")
    print("完了。続けて novel_project_check.py で必須ファイルを確認してください。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
