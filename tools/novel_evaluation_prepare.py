#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
評価セッション準備ツール（Monogatari Coach）。

- 作品フォルダの章別文字数を章グループ単位で表示
- _reader/ の既存評価ファイルとスコアを一覧
- 評価 Markdown のフロントマターテンプレを生成

運用: .rulesync/skills/novel-evaluation-output/SKILL.md を参照。
"""

from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

import novel_char_count as ncc  # noqa: E402

# ─── 評価ファイルの分類 ────────────────────────────────────────────────
_FILE_TYPES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"^score_\d{8}_\d{4}\.md$"), "Editor Score"),
    (re.compile(r"^interest_\d{8}\.md$"), "Interest Check"),
    (re.compile(r"^consistency_\d{8}\.md$"), "Consistency Audit"),
    (re.compile(r"^synopsis_\d{8}\.md$"), "Synopsis"),
    (re.compile(r"^\d{8}_\d{4}\.md$"), "First Reader"),
    (re.compile(r"^reader_\d{8}_\d{4}\.md$"), "First Reader（旧形式）"),
]

_RE_SCORE_100 = re.compile(r"(\d{1,3})\s*/\s*100")
_RE_SCORE_5 = re.compile(r"(\d+\.?\d*)\s*/\s*5\.?0?")
_RE_JUDGMENT = re.compile(r"(読むべき|読まなくていい)")
_RE_NOVEL_CODE = re.compile(r"^(\d{3})")


def _classify_file(name: str) -> str:
    for pattern, label in _FILE_TYPES:
        if pattern.match(name):
            return label
    return "不明"


def _extract_scores(text: str) -> dict:
    m100 = _RE_SCORE_100.search(text)
    m5 = _RE_SCORE_5.search(text)
    mj = _RE_JUDGMENT.search(text)
    return {
        "score_100": int(m100.group(1)) if m100 else None,
        "score_5": float(m5.group(1)) if m5 else None,
        "judgment": mj.group(1) if mj else None,
    }


def _sort_key_novel_text(path: Path) -> tuple:
    """novel_text01_2.md → (1, 2) の数値タプルで自然順ソート。"""
    m = re.match(r"novel_text(\d+)(?:_(\d+))?", path.stem)
    if m:
        ch = int(m.group(1))
        item = int(m.group(2)) if m.group(2) else 0
        return (ch, item)
    return (999, 0)


def _group_novel_text(novel_dir: Path) -> list[tuple[str, list[Path], int]]:
    """chapter グループ → (label, files, total_chars) のリストを返す。"""
    novel_text_dir = novel_dir / "_novel_text"
    if not novel_text_dir.is_dir():
        return []

    files = sorted(novel_text_dir.glob("novel_text*.md"), key=_sort_key_novel_text)
    groups: dict[str, list[Path]] = {}
    for f in files:
        m = re.match(r"novel_text(\d+)", f.stem)
        if m:
            key = f"ch{m.group(1).zfill(2)}"
            groups.setdefault(key, []).append(f)

    result: list[tuple[str, list[Path], int]] = []
    for key in sorted(groups):
        group_files = groups[key]
        total = sum(
            ncc.count_chars(f.read_text(encoding="utf-8"), strip_fm=True)
            for f in group_files
        )
        result.append((key, group_files, total))
    return result


def _get_prologue(novel_dir: Path) -> tuple[Path, int] | None:
    p = novel_dir / "_novel_text" / "novel_prologue.md"
    if not p.is_file():
        return None
    chars = ncc.count_chars(p.read_text(encoding="utf-8"), strip_fm=True)
    return (p, chars)


_SCORE_KINDS = {"First Reader", "First Reader（旧形式）", "Editor Score"}
_JUDGMENT_KINDS = {"First Reader", "First Reader（旧形式）"}


def _list_reader_files(reader_dir: Path) -> list[dict]:
    if not reader_dir.is_dir():
        return []
    entries = []
    for f in sorted(reader_dir.glob("*.md")):
        if f.name.startswith("_"):
            continue
        kind = _classify_file(f.name)
        scores = {"score_100": None, "score_5": None, "judgment": None}
        if kind in _SCORE_KINDS:
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
                scores = _extract_scores(text)
                if kind not in _JUDGMENT_KINDS:
                    scores["judgment"] = None
            except OSError:
                pass
        entries.append({"name": f.name, "kind": kind, **scores})
    return entries


def _get_work_title(novel_dir: Path) -> str:
    config = novel_dir / "config.md"
    if config.is_file():
        text = config.read_text(encoding="utf-8", errors="replace")
        m = re.search(r"\*\*作品名\*\*[:：]\s*(.+)", text)
        if m:
            return m.group(1).strip()
    return novel_dir.name


def _latest_score_summary(entries: list[dict]) -> str:
    scored = [e for e in entries if e["score_100"] is not None]
    if not scored:
        return "（評価なし）"
    latest = scored[-1]
    return f"{latest['name']}（{latest['score_100']} / 100）"


def _render(novel_dir: Path, mode: str, gate: str) -> int:
    novel_dir = novel_dir.resolve()
    if not novel_dir.is_dir():
        print(f"エラー: ディレクトリが見つかりません: {novel_dir}", file=sys.stderr)
        return 1

    title = _get_work_title(novel_dir)
    groups = _group_novel_text(novel_dir)
    prologue = _get_prologue(novel_dir)
    reader_entries = _list_reader_files(novel_dir / "_reader")

    total_files = sum(len(g[1]) for g in groups)
    total_chars = sum(g[2] for g in groups)
    if prologue:
        total_files += 1
        prologue_chars = prologue[1]
    else:
        prologue_chars = 0

    # ─── ヘッダ ──────────────────────────────────────────────────
    print(f"\n=== {novel_dir.name} 評価準備 ===")
    print(f"    作品名: {title}")
    print(f"    日時  : {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    # ─── 文字数・章構成 ──────────────────────────────────────────
    print("\n【文字数・章構成】")
    row_fmt = "  {:<10}  {:<30}  {:>8}  ({}ファイル)"
    if prologue:
        print(row_fmt.format("prologue", "novel_prologue.md", f"{prologue_chars:,}字", 1))
    for label, files, chars in groups:
        first = files[0].name
        last = files[-1].name
        range_str = first if len(files) == 1 else f"{first}〜{last.split('novel_text')[-1]}"
        print(row_fmt.format(label, range_str, f"{chars:,}字", len(files)))

    print(f"  {'─' * 62}")
    total_display = total_chars + prologue_chars
    print(f"  {'合計':<10}  {'（novel_char_count.py計測値）':<30}  {total_chars:>8,}字  ({total_files - (1 if prologue else 0)}ファイル)")
    if prologue:
        print(f"  {'  ＋prologue':<10}  {'（推定）':<30}  {total_display:>8,}字  ({total_files}ファイル)")

    # ─── 既存評価ファイル ────────────────────────────────────────
    print("\n【既存評価ファイル（_reader/）】")
    if not reader_entries:
        print("  （評価ファイルなし）")
    else:
        for e in reader_entries:
            score_str = ""
            if e["score_100"] is not None:
                score_str = f"{e['score_100']} / 100"
            elif e["score_5"] is not None:
                score_str = f"{e['score_5']} / 5.0（旧形式）"
            judg = f"  {e['judgment']}" if e["judgment"] else ""
            print(f"  {e['name']:<40}  {e['kind']:<20}  {score_str}{judg}")

    # ─── frontmatter テンプレ ────────────────────────────────────
    now_str = datetime.now().strftime("%Y%m%d_%H%M")
    latest = _latest_score_summary(reader_entries)

    print("\n【frontmatter テンプレ（コピー用）】")
    if mode == "editor-score":
        print(f"""---
種別: Editor Score（深掘り採点）
作品: {title}
日時: {now_str}
対象範囲: （例: プロローグ〜第{len(groups)}章 / {total_files}ファイル {total_display:,}字）
文字数: {total_display:,}
ゲート前提: {latest}
算出根拠: novels/{novel_dir.name}/_reader/_work/{datetime.now().strftime('%Y%m%d')}/aggregate.md
---""")
    else:
        gate_str = gate if gate in ("G1", "G2", "G3") else "G1 / G2 / G3"
        print(f"""---
日時: {now_str}
対象作品: {title}
対象範囲: （章番号・ファイル数・文字数を記入）
文字数: （novel_char_count.py 実測値）
ゲート段階: {gate_str}
前回書評: {latest}
---""")

    print()
    return 0


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    p = argparse.ArgumentParser(
        description="評価セッションの準備情報を表示し、frontmatter テンプレを生成する。"
    )
    p.add_argument("novel_dir", type=Path, help="novels/NNN_作品名")
    p.add_argument(
        "--mode",
        choices=["first-reader", "editor-score"],
        default="first-reader",
        help="評価モード（既定: first-reader）",
    )
    p.add_argument(
        "--gate",
        choices=["G1", "G2", "G3"],
        default="G3",
        help="First Reader のゲート段階（既定: G3）",
    )

    args = p.parse_args(argv)
    return _render(args.novel_dir, args.mode, args.gate)


if __name__ == "__main__":
    raise SystemExit(main())
