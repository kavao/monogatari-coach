#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Migrate legacy ``character_tags`` root field into ``000_base.danbooru_tags``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"YAML root must be a mapping: {path}")
    return data


def collect_character_yaml(novel_dir: Path) -> list[Path]:
    tag_dir = novel_dir / "tag" / "characters"
    if not tag_dir.is_dir():
        return []
    return sorted(tag_dir.glob("*.yaml"))


def collect_all_novels(root: Path) -> list[Path]:
    novels: list[Path] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir() or entry.name.startswith("_"):
            continue
        if collect_character_yaml(entry):
            novels.append(entry)
    return novels


def merge_character_tags_into_base(
    raw: dict[str, Any],
    *,
    strict: bool,
) -> tuple[bool, list[str]]:
    """Return (changed, warnings). Mutates *raw* in place."""
    tools_dir = Path(__file__).resolve().parent
    if str(tools_dir) not in sys.path:
        sys.path.insert(0, str(tools_dir))
    from manga_prompt_ir.character_fixed_tags import dedupe_tags
    from manga_prompt_ir.character_tag_quality import find_exposure_tags

    warnings: list[str] = []
    if "character_tags" not in raw:
        return False, warnings

    char_tags = [str(t) for t in raw.pop("character_tags") or [] if t]
    if not char_tags:
        return True, warnings

    exposure = find_exposure_tags(char_tags)
    if exposure:
        msg = f"character_tags に露出タグがあります（006_nude へ手動移動）: {', '.join(exposure)}"
        if strict:
            raise ValueError(msg)
        warnings.append(msg)

    variants: list[dict[str, Any]] = [
        v for v in raw.get("prompt_variants") or [] if isinstance(v, dict)
    ]
    base_idx: int | None = None
    for index, variant in enumerate(variants):
        if str(variant.get("variant_id") or "").strip() == "000_base":
            base_idx = index
            break

    if base_idx is None:
        appearance = raw.get("appearance") or {}
        variants.insert(
            0,
            {
                "variant_id": "000_base",
                "title": "基本外見",
                "description": "固定外見（マイグレーション自動生成）",
                "danbooru_tags": [],
            },
        )
        base_idx = 0
        warnings.append("000_base を新規作成しました")

    base_variant = variants[base_idx]
    existing = [str(t) for t in base_variant.get("danbooru_tags") or [] if t]
    merged = dedupe_tags([*existing, *char_tags])
    base_variant["danbooru_tags"] = merged
    raw["prompt_variants"] = variants
    return True, warnings


def migrate_file(path: Path, *, dry_run: bool, strict: bool) -> tuple[bool, list[str]]:
    raw = load_yaml(path)
    changed, warnings = merge_character_tags_into_base(raw, strict=strict)
    if not changed:
        return False, warnings
    if dry_run:
        return True, warnings
    path.write_text(
        yaml.safe_dump(raw, allow_unicode=True, sort_keys=False, width=120),
        encoding="utf-8",
    )
    return True, warnings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Migrate character_tags into 000_base.danbooru_tags and remove the legacy key.",
    )
    parser.add_argument("novel_dir", nargs="?", type=Path, help="作品フォルダ（--all-novels 時は省略可）")
    parser.add_argument("--all-novels", action="store_true", help="novels/ 配下の全作品を処理")
    parser.add_argument("--dry-run", action="store_true", help="書き込まず変更対象のみ表示")
    parser.add_argument("--strict", action="store_true", help="露出タグ混入時に停止")
    args = parser.parse_args(argv)

    root = repo_root()
    if args.all_novels:
        novel_dirs = collect_all_novels(root / "novels")
    else:
        if args.novel_dir is None:
            parser.error("novel_dir を指定するか --all-novels を使ってください")
        novel_dir = args.novel_dir
        if not novel_dir.is_absolute():
            novel_dir = (root / novel_dir).resolve()
        novel_dirs = [novel_dir]

    if not novel_dirs:
        parser.error("対象作品が見つかりません")

    changed_files = 0
    all_warnings: list[str] = []
    for novel_dir in novel_dirs:
        for path in collect_character_yaml(novel_dir):
            try:
                changed, warnings = migrate_file(path, dry_run=args.dry_run, strict=args.strict)
            except ValueError as exc:
                print(f"ERROR {path}: {exc}", file=sys.stderr)
                return 1
            if warnings:
                for warning in warnings:
                    all_warnings.append(f"{path}: {warning}")
            if changed:
                changed_files += 1
                action = "would update" if args.dry_run else "updated"
                print(f"{action}: {path}")

    if all_warnings:
        print("Warnings:", file=sys.stderr)
        for warning in all_warnings:
            print(f"- {warning}", file=sys.stderr)

    print(f"novels={len(novel_dirs)} changed_files={changed_files}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
