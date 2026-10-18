"""章の設計密度（D21）。章の目標字数 ÷ 章出来事の件数で、1項あたりの仕上がり見込みを出す。

章出来事として数えるのは、章見出しの下で行頭（字下げなし）から始まる番号付き項目だけ。
字下げした入れ子の番号付き補足と、コードブロックの中は数えない。

目標の取り先は、ユーザーが明示した字数（--target）か、design_specification.md の章の
「**分量目安**」の書き出しの字数だけ。書き出しが字数でなければ保留にする（同じ行の
「初稿は 7,983字」などの実測字数を目標に流用しないため）。本文・設計書は書き換えない。

    uv run python tools/design_density.py novels/NNN_作品名 [--chapter N] [--target 8000]
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import math
from pathlib import Path
import re
import sys

PER_ITEM_LOW = 500    # 推奨帯の下限（1項あたりの仕上がり）
PER_ITEM_HIGH = 800   # 推奨帯の上限
TOO_FEW_ABOVE = 1000  # 1項あたりこれを超える見込みなら、項目が少なすぎる
TOO_MANY_BELOW = 300  # 1項あたりこれ未満の見込みなら、項目が多すぎる（300 ちょうどは含めない）

_CHAPTER_RE = re.compile(r"^###\s*第\s*([0-9０-９]+)\s*章(.*)$")
# 章出来事は行頭（字下げなし）の番号付き項目だけ。字下げした入れ子の補足やコード例は数えない。
_ITEM_RE = re.compile(r"^[0-9０-９]+[.．]\s+\S")
_FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
_TARGET_RE = re.compile(r"^\*\*分量目安\*\*\s*[：:]\s*([0-9０-９][0-9０-９,，]*)\s*字")


@dataclass(frozen=True)
class ChapterDensity:
    chapter: int
    title: str
    items: int
    target: int | None
    target_source: str
    per_item: float | None
    verdict: str
    recommended: tuple[int, int] | None


def _number(text: str) -> int:
    return int(text.translate(str.maketrans("０１２３４５６７８９", "0123456789")).replace(",", "").replace("，", ""))


def recommended_items(target: int) -> tuple[int, int]:
    """推奨帯（500〜800字/項）に入る件数の幅。"""
    return math.ceil(target / PER_ITEM_HIGH), math.floor(target / PER_ITEM_LOW)


def judge(target: int | None, items: int) -> tuple[float | None, str]:
    if target is None:
        return None, "保留（章の目標字数が無い）"
    if items == 0:
        return None, "少なすぎ（章出来事が0件）"
    per_item = target / items
    if per_item > TOO_FEW_ABOVE:
        return per_item, "少なすぎ（設計へ子エピソードを足す）"
    if per_item < TOO_MANY_BELOW:
        return per_item, "多すぎ（統合を提案する）"
    if PER_ITEM_LOW <= per_item <= PER_ITEM_HIGH:
        return per_item, "推奨帯"
    return per_item, "帯の外だが許容"


def chapter_densities(design_text: str, *, targets: dict[int, int] | None = None) -> list[ChapterDensity]:
    """章ごとの件数と目標を読む。targets はユーザーが明示した章の目標字数（設計書より優先）。"""
    targets = targets or {}
    chapters: list[dict] = []
    current: dict | None = None
    fence: str | None = None  # 開いているフェンス（文字種と長さ）
    for line in design_text.splitlines():
        if fence is not None:
            closing = _FENCE_RE.match(line)
            # 閉じるのは、同じ文字種で開始時以上の長さのフェンスだけ（後ろは空白のみ）。
            if (closing and closing.group(1)[0] == fence[0]
                    and len(closing.group(1)) >= len(fence) and not closing.group(2).strip()):
                fence = None
            continue
        opening = _FENCE_RE.match(line)
        if opening and not (opening.group(1)[0] == "`" and "`" in opening.group(2)):
            fence = opening.group(1)
            continue
        heading = _CHAPTER_RE.match(line)
        if heading:
            current = {"chapter": _number(heading.group(1)), "title": heading.group(2).strip(),
                       "items": 0, "target": None}
            chapters.append(current)
            continue
        if line.startswith("## ") or (line.startswith("### ") and not heading):
            current = None
            continue
        if current is None:
            continue
        if _ITEM_RE.match(line):
            current["items"] += 1
        target = _TARGET_RE.match(line.strip())
        if target and current["target"] is None:
            current["target"] = _number(target.group(1))
    result = []
    for item in chapters:
        explicit = targets.get(item["chapter"])
        target = explicit if explicit is not None else item["target"]
        source = "明示" if explicit is not None else ("設計の分量目安" if item["target"] else "なし")
        per_item, verdict = judge(target, item["items"])
        result.append(ChapterDensity(item["chapter"], item["title"], item["items"], target, source,
                                     per_item, verdict,
                                     recommended_items(target) if target else None))
    return result


def render(rows: list[ChapterDensity]) -> str:
    lines = ["| 章 | 件数 | 目標字数（取り先） | 1項あたり | 推奨件数 | 判定 |",
             "| --- | --- | --- | --- | --- | --- |"]
    for row in rows:
        target = f"{row.target}（{row.target_source}）" if row.target else "—"
        per_item = f"{row.per_item:.0f}字" if row.per_item else "—"
        recommended = f"{row.recommended[0]}〜{row.recommended[1]}" if row.recommended else "—"
        lines.append(f"| 第{row.chapter}章{row.title} | {row.items} | {target} | {per_item} | {recommended} | {row.verdict} |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    from console_io import configure_stdio_utf8

    configure_stdio_utf8()
    parser = argparse.ArgumentParser(description="章の設計密度（1項あたりの仕上がり見込み）を出す。書き換えない。")
    parser.add_argument("work", type=Path, help="作品フォルダ")
    parser.add_argument("--chapter", type=int, help="この章だけ")
    parser.add_argument("--target", type=int, help="ユーザーが明示した章の目標字数（--chapter と一緒に）")
    args = parser.parse_args(argv)
    if args.target is not None and args.chapter is None:
        parser.error("--target は --chapter と一緒に指定する")
    path = args.work / "design_specification.md"
    if not path.is_file():
        print(f"design_specification.md が見つかりません: {path}", file=sys.stderr)
        return 2
    targets = {args.chapter: args.target} if args.target is not None else None
    rows = chapter_densities(path.read_text(encoding="utf-8"), targets=targets)
    if args.chapter is not None:
        rows = [row for row in rows if row.chapter == args.chapter]
        if not rows:
            print(f"第{args.chapter}章が design_specification.md にありません", file=sys.stderr)
            return 2
    print(render(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
