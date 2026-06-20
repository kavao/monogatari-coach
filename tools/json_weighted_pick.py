#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
JSON 定義リストから Python の乱数で1件（または複数件）選択する（公式用）。

- **複数回（-n）**は同一の乱数生成器で連続抽選する（ループごとに Random() を作り直さない。短時間だと同一シード化する不具合を避ける）。
- **--seed** を付けると再現用に固定される。毎回ばらつかせたいときは **--seed を付けない**。

- 文字列の配列: 均等確率
- オブジェクトの配列: 各要素の「確率」系フィールドが**すべて**解釈できれば重み付き。
  一部だけ数値がある／解釈不能な場合は**配列全体を均等**にフォールバック
- 重みのキー（先頭から試行）: 確率, weight, Weight, 重み, prob, probability, ウェイト

定義・運用はスキル weighted-pick（.rulesync/skills/weighted-pick/SKILL.md）に従う。
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path
from typing import Any


WEIGHT_KEYS = (
    "確率",
    "相対確率",  # episode_mature.json 等（0〜1 の小数やパーセント混在可）
    "weight",
    "Weight",
    "重み",
    "prob",
    "probability",
    "ウェイト",
)


def load_json(path: Path | None, stdin: bool) -> Any:
    if stdin:
        return json.load(sys.stdin)
    if path is None:
        raise ValueError("ファイルまたは - で JSON を指定してください")
    text = path.read_text(encoding="utf-8")
    return json.loads(text)


def navigate(data: Any, path_str: str | None) -> Any:
    if not path_str or not path_str.strip():
        return data
    cur: Any = data
    for part in path_str.split("."):
        if part == "":
            continue
        if isinstance(cur, dict):
            if part not in cur:
                raise KeyError(f"キーが存在しません: {part!r} (現在のパス途中)")
            cur = cur[part]
        else:
            raise TypeError(f"辞書以外に descend できません: {type(cur).__name__}")
    return cur


def _parse_weight(obj: dict[str, Any]) -> float | None:
    for k in WEIGHT_KEYS:
        if k not in obj:
            continue
        v = obj[k]
        if isinstance(v, bool):
            return None
        if isinstance(v, (int, float)):
            if v < 0:
                return None
            return float(v)
        if isinstance(v, str):
            s = v.strip().replace("%", "")
            try:
                x = float(s)
                return x if x >= 0 else None
            except ValueError:
                return None
    return None


def pick_from_list(
    items: list[Any],
    *,
    rng: random.Random,
) -> tuple[Any, int, str, list[float | None]]:
    """
    Returns: (chosen, index, mode, weights_per_item or placeholders)
    mode: "uniform" | "weighted" | "uniform_fallback"
    """
    if not items:
        raise ValueError("リストが空です")

    if not all(isinstance(x, dict) for x in items):
        i = rng.randrange(len(items))
        return items[i], i, "uniform", []

    weights: list[float | None] = [_parse_weight(x) for x in items]  # type: ignore[arg-type]
    resolved = [w for w in weights if w is not None]

    if len(resolved) == 0:
        i = rng.randrange(len(items))
        return items[i], i, "uniform", []

    if len(resolved) != len(items):
        # 一部のみ確率あり → データが曖昧なので均等
        i = rng.randrange(len(items))
        return items[i], i, "uniform_fallback", weights

    wsum = sum(resolved)
    if wsum <= 0:
        i = rng.randrange(len(items))
        return items[i], i, "uniform_fallback", weights

    r = rng.random() * wsum
    acc = 0.0
    for idx, w in enumerate(resolved):
        acc += w
        if r <= acc:
            return items[idx], idx, "weighted", weights
    return items[-1], len(items) - 1, "weighted", weights


def run_pick(
    data: Any,
    path_str: str | None,
    *,
    rng: random.Random,
) -> dict[str, Any]:
    target = navigate(data, path_str)
    if isinstance(target, list):
        chosen, index, mode, wlist = pick_from_list(target, rng=rng)
        out: dict[str, Any] = {
            "picked": chosen,
            "index": index,
            "mode": mode,
            "path": path_str or "",
        }
        if wlist:
            out["weights_used"] = wlist
        return out
    if isinstance(target, dict):
        # 辞書のときは「キー一覧から均等」で1キー選び、値を返すオプションも可能だが、
        # まずはキー名を picked として返す
        keys = list(target.keys())
        if not keys:
            raise ValueError("空のオブジェクトです")
        k = rng.choice(keys)
        return {
            "picked": k,
            "value": target[k],
            "mode": "uniform_dict_keys",
            "path": path_str or "",
        }
    # スカラーなど
    return {
        "picked": target,
        "index": None,
        "mode": "scalar",
        "path": path_str or "",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="JSON リストから重み付きまたは均等に1件選択"
    )
    parser.add_argument(
        "json_file",
        type=str,
        nargs="?",
        help="JSON ファイルパス、- で標準入力、省略時は --eval と併用",
    )
    parser.add_argument(
        "--eval",
        "-e",
        type=str,
        default=None,
        help="JSON 文字列を直接渡す（ファイルが無いときのテスト・短いデータ用）",
    )
    parser.add_argument(
        "--path",
        "-p",
        type=str,
        default=None,
        help="ドット区切りで辞書を辿る（例: western_last_names, foo.bar）",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="乱数シード（再現用）。付けたまま繰り返し実行すると毎回同じ結果になる。ばらつきたいときは省略する。",
    )
    parser.add_argument(
        "--count",
        "-n",
        type=int,
        default=1,
        help="独立に繰り返し抽選する回数（既定: 1）",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="結果を JSON で出力",
    )
    args = parser.parse_args(argv)

    stdin_mode = args.json_file == "-"
    path = None if stdin_mode else (Path(args.json_file) if args.json_file else None)

    if args.eval is not None:
        data = json.loads(args.eval)
    elif stdin_mode:
        data = load_json(None, True)
    elif path is not None:
        data = load_json(path, False)
    else:
        parser.error("`--eval` JSON 文字列、JSON ファイル、または `-`（標準入力）を指定してください")
    n = max(1, args.count)
    # 1 つの RNG で連続抽選。ループ毎に Random() を new しない（同一時刻シードの重複を防ぐ）
    if args.seed is not None:
        rng = random.Random(args.seed)
    else:
        rng = random.Random()

    results = []
    for _ in range(n):
        results.append(run_pick(data, args.path, rng=rng))

    if args.json:
        out = results[0] if len(results) == 1 else {"runs": results}
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        for i, r in enumerate(results):
            prefix = f"[{i+1}] " if len(results) > 1 else ""
            picked = r.get("picked")
            mode = r.get("mode")
            if isinstance(picked, dict):
                disp = json.dumps(picked, ensure_ascii=False)
            else:
                disp = repr(picked) if isinstance(picked, str) else str(picked)
            print(f"{prefix}mode={mode} picked={disp}")
            if "value" in r:
                v = r["value"]
                vs = json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else str(v)
                print(f"{prefix}value={vs}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
