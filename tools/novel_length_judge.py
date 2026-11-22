"""清書のあとに章の分量を判定する（計画 20261121_metron-length-relaxation §10.2）。

章の合計字数（章末ステータスのブロックと通知の行は数えない）を、次の二つと比べる。

- 章の目標: ユーザーが明示した字数（--target）→ design_specification.md の章の「**分量目安**」の順に取る。
  「N字」は N、「N〜M字」のような範囲は下限、「N字以上」は N。読めなければ「保留」。
  15% 不足までは完了（10% を超える不足は reported）、それより足りなければ below。
- 場面の床: METRON の作品で、その章に属する場面（scene_id が chNN- で始まる）の床 × 0.9 の合計。
  清書のあとの本文には場面の境目の印が無いので、場面ごとの判定は後追い計測（writing_bridge）に任せる。

数値の正は tools/metron/length.py。本文も設計書も書き換えない。

    uv run python tools/novel_length_judge.py novels/NNN_作品名 --chapter 3 [--target 8000] [--json]
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
import sys

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from metron.length import (  # noqa: E402
    LENGTH_REPORT_RATIO, LENGTH_TOLERANCE, effective_floor, target_length_status,
)
from novel_char_count import count_chars  # noqa: E402

_CHAPTER_RE = re.compile(r"^###\s*第\s*([0-9０-９]+)\s*章")
_TARGET_LINE_RE = re.compile(r"^\*\*分量目安\*\*\s*[：:]\s*(.+)$")
_NUMBER = r"[0-9０-９][0-9０-９,，]*"
# 字のあとに続いてよいのは、目安の言い方と区切りだけ（「8000字未満」のような上限の書き方は読まない）。
_TAIL = r"(?:以上|程度|前後|くらい|ぐらい|ほど|目安)?\s*(?:[（(、。,，].*)?$"
# 「4,000〜8,000文字程度」「4,000字〜8,000字」「4000-8000字」は下限を取る。
_RANGE_RE = re.compile(rf"^({_NUMBER})\s*(?:文?字)?\s*[〜~～\-－]\s*{_NUMBER}\s*文?字\s*{_TAIL}")
# 「8,000字以上」「8000字」「8,000文字程度」は N を取る。
_SINGLE_RE = re.compile(rf"^({_NUMBER})\s*文?字\s*{_TAIL}")
_UPPER_BOUND_RE = re.compile(r"未満|以下|以内|まで")
_FILE_RE = re.compile(r"^novel_text(\d+)(?:_(\d+))?\.md$")


@dataclass(frozen=True)
class ChapterLength:
    chapter: int
    chars: int
    files: list[str]
    target: int | None
    target_source: str  # 明示 / 設計の分量目安 / 保留（目標を読めない） / なし
    target_status: str  # ok / reported / below / 保留
    floor_total: int | None  # 場面の床 × 0.9 の合計（METRON の場面が無ければ None）
    floor_status: str  # ok / below / なし
    judged: bool  # 目標か場面の床のどちらかで判定できたか（どちらも無ければ保留）
    complete: bool
    notes: list[str]


def _number(text: str) -> int:
    return int(text.translate(str.maketrans("０１２３４５６７８９", "0123456789")).replace(",", "").replace("，", ""))


def parse_target(value: str) -> int | None:
    """分量目安の値を読む。読めなければ None（保留）。"""

    text = value.strip()
    if _UPPER_BOUND_RE.search(text):
        return None  # 「8000字未満」「8000字（以内）」など上限の書き方は目標にしない
    match = _RANGE_RE.match(text) or _SINGLE_RE.match(text)
    return _number(match.group(1)) if match else None


def chapter_target_line(design_text: str, chapter: int) -> str | None:
    """章見出し（### 第N章）の下の最初の「**分量目安**」の値。無ければ None。"""

    current: int | None = None
    for line in design_text.splitlines():
        heading = _CHAPTER_RE.match(line)
        if heading:
            current = _number(heading.group(1))
            continue
        if re.match(r"^#{1,3}\s", line):  # 章の見出し以外の見出しで、章の範囲を切る
            current = None
            continue
        if current == chapter:
            found = _TARGET_LINE_RE.match(line.strip())
            if found:
                return found.group(1)
    return None


def chapter_text_files(work: Path, chapter: int) -> list[Path]:
    files = []
    for path in sorted((work / "_novel_text").glob("novel_text*.md")):
        match = _FILE_RE.match(path.name)
        if match and int(match.group(1)) == chapter:
            files.append((int(match.group(2) or 0), path))
    return [path for _, path in sorted(files)]


def scene_floors(work: Path, chapter: int) -> tuple[list[tuple[str, int]], list[str]]:
    """その章の METRON の場面と床、および beats.yaml を読めなかった場面。"""

    try:
        from work_paths import iter_unit_ids, resolve_unit
        from metron.contract import load_beat_plan
    except ImportError:
        return [], []
    prefix = f"ch{chapter:02d}-"
    result = []
    unreadable: list[str] = []
    for scene_id in iter_unit_ids(work, "metron"):
        if not scene_id.startswith(prefix):
            continue
        beats = resolve_unit(work, "metron", scene_id).base / "beats.yaml"
        if not beats.is_file():
            continue
        try:
            result.append((scene_id, load_beat_plan(beats).generation.chars_floor))
        except Exception:  # noqa: BLE001 - 読めない場面は理由を問わず判定を保留にする
            unreadable.append(scene_id)
    return result, unreadable


def judge_chapter(work: Path, chapter: int, *, target: int | None = None) -> ChapterLength:
    files = chapter_text_files(work, chapter)
    if not files:
        raise FileNotFoundError(f"第{chapter}章の本文ファイルがありません: {work / '_novel_text'}")
    try:
        chars = sum(count_chars(path.read_text(encoding="utf-8"), strip_fm=True) for path in files)
    except (UnicodeDecodeError, OSError) as error:
        raise ValueError(f"本文ファイルを読めない: {error}") from error
    notes: list[str] = []
    if target is not None:
        source = "明示"
    else:
        design = work / "design_specification.md"
        try:
            line = chapter_target_line(design.read_text(encoding="utf-8"), chapter) if design.is_file() else None
        except (OSError, UnicodeDecodeError) as error:
            line = None
            notes.append(f"設計書を読めない（{error.__class__.__name__}）。目標は保留")
        if line is None:
            source = "なし"
        else:
            target = parse_target(line)
            source = "設計の分量目安" if target is not None else "保留（目標を読めない）"
            notes.append(f"分量目安: {line.strip()}" + (f" → {target}字" if target is not None else ""))
    target_status = target_length_status(target, chars) if target else "保留"
    floors, unreadable = scene_floors(work, chapter)
    floor_total = sum(effective_floor(floor) for _, floor in floors) if floors else None
    floor_status = "なし" if floor_total is None else ("ok" if chars >= floor_total else "below")
    if unreadable:
        # 読めない場面の床を抜いて合計すると、足りない章を完了と判定しうる。判定を保留にする。
        floor_status = "保留"
        notes.append("beats.yaml を読めない場面: " + "、".join(unreadable) + "（場面の床の判定は保留）")
    if floors:
        notes.append("場面の床: " + "、".join(f"{scene} {floor}" for scene, floor in floors)
                     + "（場面ごとの判定は後追い計測で見る）")
    judged = floor_status != "保留" and (target_status != "保留" or floor_status != "なし")
    complete = judged and target_status != "below" and floor_status != "below"
    return ChapterLength(chapter, chars, [path.name for path in files], target, source,
                         target_status, floor_total, floor_status, judged, complete, notes)


def render(result: ChapterLength) -> str:
    lines = [f"第{result.chapter}章: {result.chars}字（{'、'.join(result.files)}）"]
    if result.target:
        lines.append(f"- 章の目標: {result.target}字（{result.target_source}）→ {result.target_status}"
                     f"（完了は {LENGTH_TOLERANCE:.0%} 不足まで、{LENGTH_REPORT_RATIO:.0%} を超える不足は報告）")
    else:
        lines.append(f"- 章の目標: {result.target_source}。場面の床だけで判定する")
    if result.floor_total is not None:
        lines.append(f"- 場面の床 × 0.9 の合計: {result.floor_total}字 → {result.floor_status}")
    lines.extend(f"- {note}" for note in result.notes)
    if not result.judged:
        reason = ("読めない場面の床がある" if result.floor_status == "保留"
                  else "章の目標も場面の床も無い。目標を --target で渡すと判定できる")
        lines.append(f"判定: 保留（{reason}）")
    else:
        lines.append("判定: " + ("完了" if result.complete else "未完了（言い換えで埋め戻さない。全体の深化か指示加筆で足す）"))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="清書のあとに章の分量を判定する（本文は書き換えない）")
    parser.add_argument("work", type=Path, help="作品フォルダ（novels/NNN_作品名）")
    parser.add_argument("--chapter", type=int, required=True)
    parser.add_argument("--target", type=int, help="ユーザーが明示した章の目標字数（設計書より優先）")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.target is not None and args.target <= 0:
        parser.error("--target must be positive")
    try:
        result = judge_chapter(args.work, args.chapter, target=args.target)
    except (FileNotFoundError, ValueError) as error:
        print(f"[ERROR] {error}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
    else:
        print(render(result))
    if not result.judged:
        return 3
    return 0 if result.complete else 1


if __name__ == "__main__":
    raise SystemExit(main())
