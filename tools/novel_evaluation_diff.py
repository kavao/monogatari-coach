#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
評価スコア推移表ツール（Monogatari Coach）。

_reader/ 配下の評価ファイルを時系列に並べ、スコアの変化を表示する。
受け入れ条件: パイロット作品で v1→v2 の点差が表示できる。

運用: .rulesync/skills/novel-evaluation-output/SKILL.md を参照。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# ─── 評価ファイルの分類（novel_evaluation_prepare.py と同じパターン）────────
_FILE_TYPES: list[tuple[re.Pattern, str, int]] = [
    (re.compile(r"^score_(\d{8})_(\d{4})\.md$"), "Editor Score", 1),
    (re.compile(r"^interest_(\d{8})\.md$"), "Interest Check", 0),
    (re.compile(r"^consistency_(\d{8})\.md$"), "Consistency Audit", 0),
    (re.compile(r"^synopsis_(\d{8})\.md$"), "Synopsis", 0),
    (re.compile(r"^(\d{8})_(\d{4})\.md$"), "First Reader", 1),
    (re.compile(r"^reader_(\d{8})_(\d{4})\.md$"), "First Reader（旧形式）", 1),
]

_RE_SCORE_100 = re.compile(r"(?<!\d)(\d{1,3})\s*/\s*100(?!\d)")
_RE_SCORE_5 = re.compile(r"(?<!\d)(\d+\.\d)\s*/\s*5\.?0?(?!\d)")  # 小数点あり（4.5/5.0 等）のみ
_RE_GATE = re.compile(r"ゲート段階[:：]\s*(G[123])")
_RE_JUDGMENT = re.compile(r"(読むべき|読まなくていい)")
_OLD_FORMAT_KINDS = {"First Reader（旧形式）"}


def _file_sort_key(name: str) -> str:
    """ファイル名から日時部分を抽出して sort key にする（降順→昇順）。"""
    # score_20260608_1400.md → 20260608_1400
    m = re.search(r"(\d{8})_?(\d{4})?", name)
    if m:
        return f"{m.group(1)}_{m.group(2) or '0000'}"
    return name


def _classify(name: str) -> tuple[str, bool]:
    """(種別ラベル, スコア対象か) を返す。"""
    for pattern, label, has_score in _FILE_TYPES:
        if pattern.match(name):
            return label, bool(has_score)
    return "不明", False


def _extract(path: Path, has_score: bool, kind: str = "") -> dict:
    if not has_score:
        return {"score_100": None, "score_5": None, "gate": None, "judgment": None}
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {"score_100": None, "score_5": None, "gate": None, "judgment": None}

    # フロントマターをスキップして本文のみ対象にする
    body = text
    if text.startswith("---"):
        lines = text.splitlines(keepends=True)
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                body = "".join(lines[i + 1:])
                break

    # 100点スコア: 本文中の最大値が総合点（100を超えるものは除外）
    scores_100 = [int(m.group(1)) for m in _RE_SCORE_100.finditer(body) if int(m.group(1)) <= 100]
    score_100 = max(scores_100) if scores_100 else None

    # 5段階スコア: 旧形式ファイルのみ有効（小数点付きの XX.X/5.0 形式に限定）
    score_5 = None
    if kind in _OLD_FORMAT_KINDS:
        m5 = _RE_SCORE_5.search(body)
        if m5:
            score_5 = float(m5.group(1))

    gate_m = _RE_GATE.search(body)
    judg_m = _RE_JUDGMENT.search(body)
    return {
        "score_100": score_100,
        "score_5": score_5,
        "gate": gate_m.group(1) if gate_m else None,
        "judgment": judg_m.group(1) if judg_m else None,
    }


def _score_str(e: dict) -> str:
    if e["score_100"] is not None:
        return f"{e['score_100']:3d} / 100"
    if e["score_5"] is not None:
        return f"{e['score_5']} / 5.0（旧）"
    return "—"


def run(novel_dir: Path, *, show_all: bool = False) -> int:
    novel_dir = novel_dir.resolve()
    reader_dir = novel_dir / "_reader"
    if not reader_dir.is_dir():
        print(f"_reader/ が見つかりません: {reader_dir}", file=sys.stderr)
        return 1

    entries = []
    for f in reader_dir.glob("*.md"):
        if f.name.startswith("_"):
            continue
        kind, has_score = _classify(f.name)
        if not show_all and not has_score:
            continue
        info = _extract(f, has_score, kind)
        entries.append({"name": f.name, "kind": kind, "has_score": has_score, **info})

    if not entries:
        print("評価ファイルが見つかりません。", file=sys.stderr)
        return 1

    entries.sort(key=lambda e: _file_sort_key(e["name"]))

    # ─── テーブルヘッダ ──────────────────────────────────────────
    print(f"\n=== {novel_dir.name} 評価推移 ===\n")
    col_name = 42
    col_kind = 22
    col_score = 14
    col_gate = 4
    col_judg = 14
    header = (
        f"{'ファイル':<{col_name}}  {'種別':<{col_kind}}  {'スコア':>{col_score}}"
        f"  {'GT':<{col_gate}}  {'判定':<{col_judg}}"
    )
    print(header)
    print("─" * (col_name + col_kind + col_score + col_gate + col_judg + 10))

    scored_scores: list[int] = []
    prev_score: int | None = None

    for e in entries:
        s_str = _score_str(e)
        gate = e.get("gate") or "—"
        judg = e.get("judgment") or "—"
        delta_str = ""
        if e["score_100"] is not None:
            if prev_score is not None:
                diff = e["score_100"] - prev_score
                delta_str = f"  [{diff:+d}]" if diff != 0 else "  [→]"
            scored_scores.append(e["score_100"])
            prev_score = e["score_100"]
        row = (
            f"{e['name']:<{col_name}}  {e['kind']:<{col_kind}}  {s_str:>{col_score}}"
            f"  {gate:<{col_gate}}  {judg:<{col_judg}}{delta_str}"
        )
        print(row)

    print()

    # ─── サマリ ─────────────────────────────────────────────────
    if scored_scores:
        print(f"最新スコア  : {scored_scores[-1]} / 100  ({entries[-1]['name']})")
        if len(scored_scores) >= 2:
            total_change = scored_scores[-1] - scored_scores[0]
            print(
                f"推移        : {scored_scores[0]} → {scored_scores[-1]}"
                f"  ({total_change:+d} ポイント、{len(scored_scores)} 回評価)"
            )
    print()
    return 0


def main(argv: list[str] | None = None) -> int:
    from console_io import configure_stdio_utf8

    configure_stdio_utf8()

    p = argparse.ArgumentParser(
        description="_reader/ の評価スコア推移を時系列で表示する。"
    )
    p.add_argument("novel_dir", type=Path, help="novels/NNN_作品名")
    p.add_argument(
        "--all",
        action="store_true",
        help="Synopsis / Interest Check / Consistency も含めて全ファイルを表示",
    )

    args = p.parse_args(argv)
    return run(args.novel_dir, show_all=args.all)


if __name__ == "__main__":
    raise SystemExit(main())
