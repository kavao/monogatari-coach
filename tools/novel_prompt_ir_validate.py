#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Validate manga-prompt-ir YAML files with the Pydantic schemas."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def load_models():
    skill_root = repo_root() / ".rulesync" / "skills" / "manga-prompt-ir"
    sys.path.insert(0, str(skill_root))
    from schemas.character import CharacterPrompt
    from schemas.manga_page import MangaPagePrompt

    return CharacterPrompt, MangaPagePrompt


def load_yaml(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"YAML root must be a mapping: {path}")
    return data


def collect_files(args: argparse.Namespace) -> tuple[list[Path], list[Path]]:
    character_files = [Path(p) for p in args.character]
    manga_page_files = [Path(p) for p in args.manga_page]
    if args.novel_dir:
        novel_dir = Path(args.novel_dir)
        if not novel_dir.is_absolute():
            novel_dir = (repo_root() / novel_dir).resolve()
        character_files.extend(sorted((novel_dir / "tag" / "characters").glob("*.yaml")))
        manga_page_files.extend(sorted((novel_dir / "manga" / "pages").glob("*.yaml")))
    return character_files, manga_page_files


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate manga-prompt-ir YAML files")
    parser.add_argument("novel_dir", nargs="?", help="Novel directory containing tag/characters and manga/pages")
    parser.add_argument("--character", action="append", default=[], help="Character YAML file")
    parser.add_argument("--manga-page", action="append", default=[], help="Manga page YAML file")
    args = parser.parse_args(argv)

    CharacterPrompt, MangaPagePrompt = load_models()
    character_files, manga_page_files = collect_files(args)
    if not character_files and not manga_page_files:
        parser.error("provide novel_dir, --character, or --manga-page")

    character_ids: set[str] = set()
    errors: list[str] = []

    for path in character_files:
        try:
            character = CharacterPrompt.model_validate(load_yaml(path))
            character_ids.add(character.character_id)
            print(f"OK character: {path}")
        except Exception as exc:
            errors.append(f"{path}: {exc}")

    for path in manga_page_files:
        try:
            page = MangaPagePrompt.model_validate(load_yaml(path))
            missing = [cid for cid in page.character_ids if cid not in character_ids]
            subject_missing = [
                subject.character_id
                for panel in page.panels
                for subject in panel.subjects
                if subject.character_id and subject.character_id not in character_ids
            ]
            if missing or subject_missing:
                unknown = sorted(set(missing + subject_missing))
                raise ValueError(f"unknown character_id reference: {', '.join(unknown)}")
            print(f"OK manga_page: {path}")
        except Exception as exc:
            errors.append(f"{path}: {exc}")

    if errors:
        print("Validation failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    print(f"validated characters={len(character_files)} manga_pages={len(manga_page_files)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
