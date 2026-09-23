#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
general 向け episode_general.json を MD 正本から同期する。

各トップレベルキーは対応する MD（## サブカテゴリ + 箇条書き）から生成する。
実行: python tools/episode_general_sync.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, cast

_TOOLS = Path(__file__).resolve().parent
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

from episode_json_sync import build_hooks_section, coerce_json_dict, parse_hooks_md  # noqa: E402

REPO_ROOT = _TOOLS.parent
EXAMPLE_GENERAL = REPO_ROOT / "_how_to.example" / "episode" / "general"
USER_GENERAL = REPO_ROOT / "_how_to" / "episode" / "general"
JSON_NAME = "episode_general.json"

# (JSON キー, MD ファイル名, 大分類解説)
GENERAL_SECTIONS: list[tuple[str, str, str]] = [
    (
        "冒頭フック",
        "episode_hooks.md",
        "全年齢向けの冒頭フック。サブカテゴリごとの具体シチュエーションを抽選する。"
        "正本は episode_hooks.md（MD-first）。",
    ),
    (
        "進行パターン",
        "episode_progression.md",
        "全年齢向けの進行パターン。型ごとの具体シチュエーションを抽選する。"
        "正本は episode_progression.md（MD-first）。",
    ),
    (
        "転換点",
        "episode_turning_points.md",
        "物語の方向が変わる転換点。正本は episode_turning_points.md（MD-first）。",
    ),
    (
        "対立軸",
        "episode_conflict_axes.md",
        "対立の構図・軸。正本は episode_conflict_axes.md（MD-first）。",
    ),
    (
        "職業フック",
        "episode_occupation_hooks.md",
        "職業・役割から物語が動き出す候補。正本は episode_occupation_hooks.md（MD-first）。",
    ),
    (
        "対話の型",
        "episode_dialogue_patterns.md",
        "会話の型・口調・食事場面。正本は episode_dialogue_patterns.md（MD-first）。",
    ),
]

PICK_PATHS_EXAMPLES = [
    "冒頭フック.サブカテゴリ.帰省と身寄せ.内訳",
    "進行パターン.サブカテゴリ.調査と深化.内訳",
    "転換点.サブカテゴリ.決断の瞬間.内訳",
    "対立軸.サブカテゴリ.理念の衝突.内訳",
    "職業フック.サブカテゴリ.屋敷奉公.内訳",
    "対話の型.サブカテゴリ.敬語と崩れ.内訳",
]


def resolve_base(*, use_user: bool) -> Path:
    if use_user and (USER_GENERAL / "episode_hooks.md").is_file():
        return USER_GENERAL
    return EXAMPLE_GENERAL


def sync_general_json(
    base: Path,
    json_path: Path,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    if not (base / "episode_hooks.md").is_file():
        raise FileNotFoundError(f"episode_hooks.md not found under {base}")

    data: dict[str, Any] = {}
    if json_path.is_file():
        data = cast(dict[str, Any], json.loads(json_path.read_text(encoding="utf-8")))

    synced_keys: list[str] = []
    for key, md_name, overview in GENERAL_SECTIONS:
        md_path = base / md_name
        if not md_path.is_file():
            continue
        subcategories = parse_hooks_md(md_path)
        if not subcategories:
            continue
        data[key] = build_hooks_section(subcategories=subcategories, overview=overview)
        synced_keys.append(key)

    if not synced_keys:
        raise ValueError(f"no sections synced from {base}")

    hooks_md = base / "episode_hooks.md"
    try:
        source_md = str(hooks_md.relative_to(REPO_ROOT)).replace("\\", "/")
    except ValueError:
        source_md = hooks_md.as_posix()

    meta = coerce_json_dict(data.get("_meta"))
    meta.update(
        {
            "schema_version": "1.1",
            "source_md": source_md,
            "sync_tool": "tools/episode_general_sync.py",
            "pick_paths_examples": PICK_PATHS_EXAMPLES,
            "probability_note": (
                "既定は均等 確率 1.0。作品別の相対確率は _how_to/pick_registry/ "
                "または novels/<作品>/pick_registry/ で上書き（任意運用）。"
            ),
        }
    )
    data["_meta"] = meta

    if dry_run:
        return data

    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync episode_general.json from general MD sources")
    parser.add_argument(
        "--user",
        action="store_true",
        help="Use _how_to/episode/general/ instead of _how_to.example/",
    )
    parser.add_argument("--dry-run", action="store_true", help="Parse only; do not write JSON")
    args = parser.parse_args()

    base = resolve_base(use_user=args.user)
    json_path = base / JSON_NAME
    try:
        data = sync_general_json(base, json_path, dry_run=args.dry_run)
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    parts: list[str] = []
    for key, _, _ in GENERAL_SECTIONS:
        section = data.get(key)
        if not isinstance(section, dict):
            continue
        subs = section.get("サブカテゴリ")
        if not isinstance(subs, dict):
            continue
        total = 0
        for sub in subs.values():
            if not isinstance(sub, dict):
                continue
            items = sub.get("内訳")
            if isinstance(items, list):
                total += len(items)
        parts.append(f"{key}: {len(subs)} subs, {total} items")

    label = "dry-run" if args.dry_run else "wrote"
    print(f"OK ({label}): {json_path} - " + "; ".join(parts))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
