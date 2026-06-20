#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Embed per-page character snapshots into manga-prompt-ir YAML files."""

from __future__ import annotations

import argparse
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


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def selected_subject_variant_id(subject: dict[str, Any]) -> str | None:
    for key in ("prompt_variant_id", "costume_variant", "variant_id"):
        value = subject.get(key)
        if value:
            return str(value)
    return None


def load_characters(novel_dir: Path) -> dict[str, dict[str, Any]]:
    character_dir = novel_dir / "tag" / "characters"
    if not character_dir.is_dir():
        raise FileNotFoundError(f"tag/characters/ がありません: {character_dir}")
    characters: dict[str, dict[str, Any]] = {}
    for path in sorted(character_dir.glob("*.yaml")):
        character = load_yaml(path)
        character_id = character.get("character_id")
        if character_id:
            characters[str(character_id)] = character
    return characters


def collect_manga_pages(novel_dir: Path, explicit_pages: list[str]) -> list[Path]:
    if explicit_pages:
        return [Path(page) if Path(page).is_absolute() else (repo_root() / page).resolve() for page in explicit_pages]
    pages_dir = novel_dir / "manga" / "pages"
    if not pages_dir.is_dir():
        raise FileNotFoundError(f"manga/pages/ がありません: {pages_dir}")
    return sorted(pages_dir.glob("*.yaml"))


def find_variant(character: dict[str, Any], variant_id: str | None) -> dict[str, Any] | None:
    if not variant_id:
        return None
    for variant in as_list(character.get("prompt_variants")):
        if isinstance(variant, dict) and variant.get("variant_id") == variant_id:
            return variant
    return None


def appearance_summary(character: dict[str, Any]) -> str:
    appearance = character.get("appearance") or {}
    parts = [
        appearance.get("age_range"),
        appearance.get("gender_presentation"),
        appearance.get("body_type"),
        appearance.get("hair_color"),
        appearance.get("hair_style"),
        appearance.get("eye_color"),
        appearance.get("skin_tone"),
        "、".join(str(v) for v in as_list(appearance.get("species_features"))),
        "、".join(str(v) for v in as_list(appearance.get("distinctive_features"))),
    ]
    return "、".join(str(part) for part in parts if part)


def fixed_tags(character: dict[str, Any], *, include_default_costume: bool) -> list[str]:
    tools_dir = Path(__file__).resolve().parent
    import sys

    if str(tools_dir) not in sys.path:
        sys.path.insert(0, str(tools_dir))
    from manga_prompt_ir.character_fixed_tags import base_fixed_tags_from

    appearance = character.get("appearance") or {}
    costume = character.get("costume") or {}
    rules = character.get("manga_rules") or {}
    tags: list[str] = []
    tags.extend(str(v) for v in base_fixed_tags_from(character))
    if include_default_costume:
        tags.extend(str(v) for v in as_list(costume.get("outfit_tags")))
    tags.extend(str(v) for v in as_list(rules.get("consistency_tags")))
    tags.extend(str(v) for v in as_list(appearance.get("species_features")))
    tags.extend(str(v) for v in as_list(appearance.get("distinctive_features")))
    return unique(tags)


def build_snapshot(character: dict[str, Any], variant_id: str | None) -> dict[str, Any]:
    costume = character.get("costume") or {}
    rules = character.get("manga_rules") or {}
    variant = find_variant(character, variant_id)
    snapshot: dict[str, Any] = {
        "character_id": character["character_id"],
        "name": character.get("name"),
        "name_en": character.get("name_en"),
        "selected_variant_id": variant_id,
        "appearance_summary": appearance_summary(character),
        "costume_summary": (variant.get("description") if variant else costume.get("main_outfit")),
        "fixed_tags": fixed_tags(character, include_default_costume=variant is None),
        "variant_tags": unique([str(v) for v in as_list(variant.get("danbooru_tags"))]) if variant else [],
        "do_not_change": [str(v) for v in as_list(rules.get("do_not_change"))],
    }
    return {key: value for key, value in snapshot.items() if value not in (None, [], "")}


def page_character_variants(page: dict[str, Any]) -> list[tuple[str, str | None]]:
    seen: set[tuple[str, str | None]] = set()
    result: list[tuple[str, str | None]] = []
    for panel in as_list(page.get("panels")):
        if not isinstance(panel, dict):
            continue
        for subject in as_list(panel.get("subjects")):
            if not isinstance(subject, dict):
                continue
            character_id = subject.get("character_id")
            if not character_id:
                continue
            key = (str(character_id), selected_subject_variant_id(subject))
            if key not in seen:
                seen.add(key)
                result.append(key)
    return result


def embed_snapshots(path: Path, characters: dict[str, dict[str, Any]], *, dry_run: bool) -> bool:
    page = load_yaml(path)
    snapshots: list[dict[str, Any]] = []
    for character_id, variant_id in page_character_variants(page):
        character = characters.get(character_id)
        if not character:
            continue
        snapshots.append(build_snapshot(character, variant_id))
    page["character_snapshots"] = snapshots
    if dry_run:
        print(f"would update: {path} snapshots={len(snapshots)}")
        return bool(snapshots)
    path.write_text(yaml.safe_dump(page, allow_unicode=True, sort_keys=False, width=120), encoding="utf-8")
    print(f"updated: {path} snapshots={len(snapshots)}")
    return bool(snapshots)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Embed character snapshots into manga/pages/*.yaml")
    parser.add_argument("novel_dir", type=Path, help="作品フォルダ")
    parser.add_argument("--manga-page", action="append", default=[], help="対象ページYAML。未指定なら全manga/pages/*.yaml")
    parser.add_argument("--dry-run", action="store_true", help="書き込まず対象と件数だけ表示")
    args = parser.parse_args(argv)

    novel_dir = args.novel_dir
    if not novel_dir.is_absolute():
        novel_dir = (repo_root() / novel_dir).resolve()
    characters = load_characters(novel_dir)
    pages = collect_manga_pages(novel_dir, args.manga_page)
    if not pages:
        parser.error("manga page YAML が見つかりません")

    updated = 0
    for page_path in pages:
        if embed_snapshots(page_path, characters, dry_run=args.dry_run):
            updated += 1
    print(f"processed pages={len(pages)} updated={updated}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
