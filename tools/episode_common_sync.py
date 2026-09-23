#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
common 向け episode_common.json を MD 正本から同期する。

各トップレベルキーは対応する MD（## サブカテゴリ + 箇条書き）から生成する。
実行: python tools/episode_common_sync.py
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
EXAMPLE_COMMON = REPO_ROOT / "_how_to.example" / "episode" / "common"
USER_COMMON = REPO_ROOT / "_how_to" / "episode" / "common"
JSON_NAME = "episode_common.json"

COMMON_SECTIONS: list[tuple[str, str, str]] = [
    (
        "恋愛フック",
        "epsode_common_hooks.md",
        "恋愛・親愛系の冒頭フック。距離軸サブカテゴリの具体シチュエーションを抽選する。"
        "正本は epsode_common_hooks.md（MD-first）。",
    ),
    (
        "関係進行",
        "epsode_common_progression.md",
        "恋愛・親愛系の関係進行。段階サブカテゴリの具体シチュエーションを抽選する。"
        "正本は epsode_common_progression.md（MD-first）。",
    ),
    (
        "親愛のきっかけ",
        "epsode_common_affection.md",
        "恋愛に限らない親愛・好意の芽生え。正本は epsode_common_affection.md（MD-first）。",
    ),
    (
        "恥じらい",
        "epsode_common_shyness.md",
        "恥じらい・照れが関係を動かす候補。正本は epsode_common_shyness.md（MD-first）。",
    ),
]

PICK_PATHS_EXAMPLES = [
    "恋愛フック.サブカテゴリ.再会.内訳",
    "関係進行.サブカテゴリ.距離の揺れ.内訳",
    "親愛のきっかけ.サブカテゴリ.偶然の触れ合い.内訳",
    "恥じらい.サブカテゴリ.視線と逸らし.内訳",
]


def resolve_base(*, use_user: bool) -> Path:
    if use_user and (USER_COMMON / "epsode_common_hooks.md").is_file():
        return USER_COMMON
    return EXAMPLE_COMMON


def sync_common_json(
    base: Path,
    json_path: Path,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    if not (base / "epsode_common_hooks.md").is_file():
        raise FileNotFoundError(f"epsode_common_hooks.md not found under {base}")

    data: dict[str, Any] = {}
    if json_path.is_file():
        data = cast(dict[str, Any], json.loads(json_path.read_text(encoding="utf-8")))

    synced_keys: list[str] = []
    for key, md_name, overview in COMMON_SECTIONS:
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

    hooks_md = base / "epsode_common_hooks.md"
    try:
        source_md = str(hooks_md.relative_to(REPO_ROOT)).replace("\\", "/")
    except ValueError:
        source_md = hooks_md.as_posix()

    meta = coerce_json_dict(data.get("_meta"))
    meta.update(
        {
            "schema_version": "1.1",
            "source_md": source_md,
            "sync_tool": "tools/episode_common_sync.py",
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
    parser = argparse.ArgumentParser(description="Sync episode_common.json from common MD sources")
    parser.add_argument(
        "--user",
        action="store_true",
        help="Use _how_to/episode/common/ instead of _how_to.example/",
    )
    parser.add_argument("--dry-run", action="store_true", help="Parse only; do not write JSON")
    args = parser.parse_args()

    base = resolve_base(use_user=args.user)
    json_path = base / JSON_NAME
    try:
        data = sync_common_json(base, json_path, dry_run=args.dry_run)
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    parts: list[str] = []
    for key, _, _ in COMMON_SECTIONS:
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
