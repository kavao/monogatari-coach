#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
character_checklist.yaml の body_gender_rules ラベル名で
_how_to/episode_mature.json（schema 2.0）からボディー候補を抽選する。

ラベル名と JSON トップレベルキーは同一。旧キー名は episode_path 正規化時のみエイリアス。

用法:
  python tools/novel_character_body_pick.py --gender female --age-band 若者
  python tools/novel_character_body_pick.py --gender male --age-band 若妖精 --seed 42 --json
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path
from typing import Any

from json_weighted_pick import navigate, pick_from_list

AGE_BANDS = ("若妖精", "若者", "熟年", "男の娘")

# schema 1.x の先頭セグメント → 2.0（ラベル＝キー）
FIRST_SEGMENT_LEGACY: dict[str, str] = {
    "女性の体型": "体型",
    "男性の体型": "体型",
    "栗突起のサイズ": "栗突起",
    "治療穴の内部形状": "治療穴の内部",
    "傘突起の長さ": "傘突起",
    "傘突起の太さ": "傘突起",
    "傘頭の皮の状態": "感度",
    "傘頭のエラ": "傘突起",
    "餅ヒダ": "餅ヒダ（全体）",
}


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def normalize_episode_path(path: str) -> str:
    """旧 episode_path を schema 2.0 のドットパスへ寄せる。"""
    if not path or not path.strip():
        return path
    parts = path.split(".")
    if len(parts) >= 3 and parts[0] == "餅ヒダ" and parts[1] == "細部":
        rest = parts[2:]
        return ".".join(rest)
    if parts[0] in FIRST_SEGMENT_LEGACY:
        parts[0] = FIRST_SEGMENT_LEGACY[parts[0]]
    return ".".join(parts)


def resolve_pick_path(
    mature: dict[str, Any],
    label: str,
    age_band: str | None,
) -> str | None:
    """
    ラベル（= episode_mature トップレベルキー）から抽選リストへのドットパスを決める。
    """
    node = mature.get(label)
    if not isinstance(node, dict):
        return None

    if age_band and age_band in node:
        band = node[age_band]
        if isinstance(band, dict) and isinstance(band.get("内訳"), list):
            return f"{label}.{age_band}.内訳"

    if isinstance(node.get("内訳"), list):
        return f"{label}.内訳"

    if isinstance(node.get("要約内訳"), list):
        return f"{label}.要約内訳"

    if isinstance(node.get("形状バリエーション"), list):
        return f"{label}.形状バリエーション"

    if isinstance(node.get("普通"), dict) and isinstance(
        node["普通"].get("内訳"), list
    ):
        return f"{label}.普通.内訳"

    return None


def format_hint(picked: Any) -> str:
    if isinstance(picked, dict):
        for key in ("タイプ", "全体形状", "形状"):
            if key in picked and picked[key]:
                return str(picked[key])
        for key in ("解説", "説明"):
            if key in picked and picked[key]:
                return str(picked[key])[:120]
        return json.dumps(picked, ensure_ascii=False)[:120]
    return str(picked)


def load_mature(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: JSON ルートはオブジェクトである必要があります")
    return data


def load_checklist(path: Path) -> dict[str, Any]:
    try:
        import yaml
    except ImportError as e:
        raise SystemExit("error: PyYAML が必要です。pip install pyyaml") from e
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def gender_labels(checklist: dict[str, Any], gender: str) -> tuple[list[str], list[str]]:
    rules = checklist.get("body_gender_rules") or {}
    block = rules.get(gender) or {}
    require = [str(x) for x in block.get("require_child_labels") or []]
    forbid = [str(x) for x in block.get("forbid_child_labels") or []]
    return require, forbid


def pick_label(
    mature: dict[str, Any],
    label: str,
    age_band: str | None,
    rng: random.Random,
) -> dict[str, Any] | None:
    path = resolve_pick_path(mature, label, age_band)
    if not path:
        return None
    path = normalize_episode_path(path)
    try:
        target = navigate(mature, path)
    except (KeyError, TypeError):
        return None
    if not isinstance(target, list) or not target:
        return None
    chosen, _index, mode, _wlist = pick_from_list(target, rng=rng)
    return {
        "source": "episode_mature",
        "mode": mode,
        "episode_path": path,
        "raw": chosen,
        "hint": format_hint(chosen),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="episode_mature.json からボディー候補を抽選")
    parser.add_argument("--gender", choices=("male", "female"), required=True)
    parser.add_argument("--age-band", default="若者", choices=AGE_BANDS)
    parser.add_argument(
        "--mature",
        type=Path,
        default=repo_root() / "_how_to" / "episode_mature.json",
    )
    parser.add_argument(
        "--checklist",
        type=Path,
        default=repo_root() / "_how_to" / "character_checklist.yaml",
    )
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    mature = load_mature(args.mature.resolve())
    checklist = load_checklist(args.checklist.resolve())
    require, forbid = gender_labels(checklist, args.gender)
    forbid_set = set(forbid)

    rng = random.Random(args.seed)
    hints: dict[str, Any] = {}
    for label in require:
        if label in forbid_set:
            continue
        picked = pick_label(mature, label, args.age_band, rng)
        if picked:
            hints[label] = picked
        else:
            hints[label] = {
                "source": "checklist",
                "hint": f"（episode_mature に {label!r} の抽選リストがありません）",
            }

    out = {
        "gender": args.gender,
        "age_band": args.age_band,
        "require_labels": require,
        "forbid_labels": forbid,
        "hints": hints,
        "mature_reference": str(args.mature.resolve()),
        "schema_note": "ラベル名 = episode_mature トップレベルキー（2.0）",
    }

    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        for label, info in hints.items():
            print(f"{label}: {info.get('hint', info)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
