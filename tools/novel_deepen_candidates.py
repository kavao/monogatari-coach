#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""清書・全体の深化で「深める箇所」の候補を出す（計画 20261121_metron-length-relaxation §17）。

    uv run python tools/novel_deepen_candidates.py novels/<作品> --chapter 4
    uv run python tools/novel_deepen_candidates.py novels/<作品> --chapter 4 --limit 5 --json

読むだけ。本文・設計・機械の記録は書き換えない。候補は参考の目印で、深める箇所の決め手にはしない
（既存の清書の書き足しとの重なりは、でたらめより低かった。計画 §17.4.1）。採否は作業者が引用を読んで決める。
出来事は足さない（足すのは既にある出来事の動作・反応・間だけ）。

候補の種類:

- 要約で流した箇所: 要約の語（「その後」「やがて」など。METRON の summary_markers と同じ辞書）を含む地の文の文
- 山場の地の文に台詞が無い: ``weight: heavy`` の Beat で、会話の往復が計画の下限に届かない
- 会話が骨だけ: 地の文を挟まずに台詞が3つ以上続く（Beat が分かるときは重い Beat だけ）
- 終盤を急いでいる（目安）: 最後の Beat の計画比（chars_hint 比）が、ほかの Beat の中央値の 7 割未満

動機の見えない判断は機械では出さない（設計の因果検査で拾う）。
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

_TOOLS = Path(__file__).resolve().parent
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

# METRON の summary_markers と同じ辞書（tools/metron/analyze.py の _SUMMARY_MARKERS）。
from metron.analyze import _SUMMARY_MARKERS as SUMMARY_MARKERS  # noqa: E402

KIND_SUMMARY = "要約で流した箇所"
KIND_HEAVY = "山場の地の文に台詞が無い"
KIND_SKELETON = "会話が骨だけ"
KIND_ENDING = "終盤を急いでいる（目安）"
HOW = {
    KIND_SUMMARY: "その出来事の動作と、相手の反応を書く",
    KIND_HEAVY: "その出来事の動作と、相手の反応を書く",
    KIND_SKELETON: "台詞のあとに、相手の反応・間・言いよどみを書く",
    KIND_ENDING: "最後の出来事の前後の間を書く",
}
ORDER = {KIND_SUMMARY: 0, KIND_HEAVY: 1, KIND_SKELETON: 2, KIND_ENDING: 3}
ENDING_RATIO = 0.7
DEFAULT_LIMIT = 8
UNKNOWN_PER_KIND = 2
SKELETON_RUN = 3
MOTIVE_NOTE = "動機の見えない判断は機械では出さない。設計の因果検査（novel-planning）で拾う"

_SENTENCE_RE = re.compile(r"[^。！？!?\n]+[。！？!?]?")
_FILE_RE = re.compile(r"^novel_text(\d+)(?:_(\d+))?\.md$")
# 「その後の欄」「それからの順」のように「の」が続くと、時間の経過ではなく順番・位置を指すことが多い。
_NON_TEMPORAL_RE = re.compile("|".join(re.escape(marker) + "の" for marker in ("その後", "それから", "翌日")))


def _has_summary_marker(sentence: str) -> bool:
    stripped = _NON_TEMPORAL_RE.sub("", sentence).lstrip("　 ")
    for marker in SUMMARY_MARKERS:
        if marker == "それから":
            # 文の途中の「〜して、それから〜」は一続きの動作の順で、時間を飛ばしていない。文頭だけ数える。
            if stripped.startswith(marker):
                return True
        elif marker in stripped:
            return True
    return False


@dataclass
class Candidate:
    kind: str
    scene_id: str | None
    beat_id: str | None
    weight: str | None
    quote: str
    how: str
    position: int = 0


@dataclass
class CandidateReport:
    work: str
    chapter: int
    candidates: list[Candidate] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class _Unit:
    scene_id: str | None
    beat_id: str | None
    weight: str | None
    text: str
    dialogue_min: int | None = None
    chars_hint: int | None = None
    offset: int = 0


def _is_dialogue(line: str) -> bool:
    return line.lstrip("　 ").startswith(("「", "『"))


def _lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.strip() and not line.lstrip().startswith(("#", "<!--"))]


def _chars(text: str) -> int:
    return len(re.sub(r"\s", "", text))


def _chapter_text(work: Path, chapter: int) -> str:
    from chapter_status import strip_for_measure

    files = []
    for path in sorted((work / "_novel_text").glob("novel_text*.md")):
        match = _FILE_RE.match(path.name)
        if match and int(match.group(1)) == chapter:
            files.append((int(match.group(2) or 0), path))
    if not files:
        raise FileNotFoundError(f"第{chapter}章の本文が無い: {work / '_novel_text'}")
    return "\n".join(strip_for_measure(path.read_text(encoding="utf-8")) for _, path in sorted(files))


def _plain(text: str) -> str:
    from writing_bridge.hashes import normalize_body

    return "\n".join(line.strip() for line in normalize_body(text).splitlines() if line.strip())


def _scene_units(work: Path, chapter: int, chapter_text: str, notes: list[str]) -> list[_Unit]:
    """その章の METRON 場面を、本文に含まれる印つきの稿で Beat に分ける。"""
    try:
        from metron.contract import load_beat_plan
        from metron.markers import parse_markers
        from work_paths import iter_unit_ids, resolve_unit
    except ImportError:
        return []
    plain_chapter = _plain(chapter_text)
    units: list[_Unit] = []
    prefix = f"ch{chapter:02d}-"
    for scene_id in iter_unit_ids(work, "metron"):
        if not scene_id.startswith(prefix):
            continue
        base = resolve_unit(work, "metron", scene_id).base
        beats_path = base / "beats.yaml"
        if not beats_path.is_file():
            continue
        try:
            plan = load_beat_plan(beats_path)
        except Exception:  # noqa: BLE001 - 読めない場面は Beat 不明として扱う
            notes.append(f"{scene_id}: beats.yaml を読めない")
            continue
        drafts = sorted([*base.glob("marked.*.md"), *base.glob("adopted.*.md")],
                        key=lambda path: path.stat().st_mtime, reverse=True)
        matched = None
        for path in drafts:
            try:
                body = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if "<!--beat:" not in body or _plain(body) not in plain_chapter:
                continue
            parsed = parse_markers(body, expected_beats=[beat.id for beat in plan.beats])
            if parsed.coverage:
                matched = (path, parsed)
                break
        if matched is None:
            notes.append(f"{scene_id}: 本文と同じ印つきの稿が無い（清書や手直しで本文が変わった）。Beat 不明で出す")
            continue
        _, parsed = matched
        by_id = {beat.id: beat for beat in plan.beats}
        for span in parsed.spans:
            beat = by_id[span.beat]
            units.append(_Unit(scene_id=scene_id, beat_id=beat.id, weight=beat.weight,
                               text=parsed.clean_text[span.start:span.end],
                               dialogue_min=beat.budget.dialogue_turns[0],
                               chars_hint=beat.budget.chars_hint))
    return units


def _first_narration_sentence(text: str) -> str | None:
    for line in _lines(text):
        if _is_dialogue(line):
            continue
        sentences = _SENTENCE_RE.findall(line.strip())
        if sentences:
            return sentences[0].strip()
    return None


def _candidates_in(unit: _Unit) -> list[Candidate]:
    found: list[Candidate] = []

    def add(kind: str, quote: str) -> None:
        found.append(Candidate(kind=kind, scene_id=unit.scene_id, beat_id=unit.beat_id, weight=unit.weight,
                               quote=quote.strip(), how=HOW[kind]))

    lines = _lines(unit.text)
    for line in lines:
        if _is_dialogue(line):
            continue
        for sentence in _SENTENCE_RE.findall(line.strip()):
            if _has_summary_marker(sentence):
                add(KIND_SUMMARY, sentence)
                break
    if unit.weight == "heavy" and unit.dialogue_min:
        turns = sum(1 for line in lines if _is_dialogue(line))
        if turns < unit.dialogue_min:
            quote = _first_narration_sentence(unit.text)
            if quote:
                add(KIND_HEAVY, quote)
    # 台詞を二つ続ける書き方の作品ではほとんどの段落に当たって絞り込みにならない（§17.4.1）。
    # 地の文を挟まずに台詞が3つ以上続く所だけ、Beat が分かるときは重い Beat だけにする。
    if unit.beat_id is None or unit.weight == "heavy":
        for index in range(len(lines) - SKELETON_RUN + 1):
            if all(_is_dialogue(line) for line in lines[index:index + SKELETON_RUN]):
                add(KIND_SKELETON, lines[index])
                break
    return found


def _ending_candidates(units: list[_Unit]) -> list[Candidate]:
    """場面ごとに、最後の Beat の計画比がほかの中央値の 7 割未満なら候補にする（当たる場面ぜんぶ）。"""
    found: list[Candidate] = []
    scenes: dict[str, list[_Unit]] = {}
    for unit in units:
        if unit.scene_id and unit.beat_id and unit.chars_hint:
            scenes.setdefault(unit.scene_id, []).append(unit)
    for scene_units in scenes.values():
        if len(scene_units) < 3:
            continue
        ratios = [_chars(item.text) / item.chars_hint for item in scene_units]  # type: ignore[operator]
        median = statistics.median(ratios[:-1])
        if median > 0 and ratios[-1] < median * ENDING_RATIO:
            last = scene_units[-1]
            sentences = [item.strip() for item in _SENTENCE_RE.findall(last.text) if item.strip()]
            if sentences:
                found.append(Candidate(kind=KIND_ENDING, scene_id=last.scene_id, beat_id=last.beat_id,
                                       weight=last.weight, quote=sentences[-1], how=HOW[KIND_ENDING]))
    return found


def candidates_for_text(text: str) -> list[Candidate]:
    """Beat の分からない本文だけから、並べ替え・件数の絞りをしない候補を出す（試算・照合用）。"""
    found = _candidates_in(_Unit(scene_id=None, beat_id=None, weight=None, text=text))
    return [item for item in found if item.quote and item.quote in text]


def find_candidates(work: Path, chapter: int, *, limit: int = DEFAULT_LIMIT) -> CandidateReport:
    report = CandidateReport(work=work.as_posix(), chapter=chapter)
    text = _chapter_text(work, chapter)
    units = _scene_units(work, chapter, text, report.notes)
    unmatched = any("印つきの稿が無い" in note for note in report.notes)
    if not units:
        units = [_Unit(scene_id=None, beat_id=None, weight=None, text=text)]
        if not unmatched:
            report.notes.append("METRON の場面が無い作品・章。Beat 不明で出す")
    elif unmatched:
        # 一部の場面だけ印つきの稿が見つかったとき、Beat に分けられた本文を除いた残りも Beat 不明で見る。
        rest = text
        for unit in units:
            piece = unit.text.strip()
            if piece and piece in rest:
                rest = rest.replace(piece, "", 1)
        if rest.strip():
            units.append(_Unit(scene_id=None, beat_id=None, weight=None, text=rest))
    found: list[Candidate] = []
    for position, unit in enumerate(units):
        for candidate in _candidates_in(unit):
            candidate.position = position
            found.append(candidate)
    for ending in _ending_candidates(units):
        ending.position = len(units)
        found.append(ending)
    # 引用が本文にそのまま無い候補は出さない（locate-quote で使えない）
    plain = text.replace("\r\n", "\n")
    found = [item for item in found if item.quote and item.quote in plain]
    # 重い Beat を先に。同じ Beat・同じ種類は1件まで。一つの Beat に集めない（Beat ごとに順に1件ずつ）。
    found.sort(key=lambda item: (item.weight != "heavy", ORDER[item.kind], item.position))
    seen: set[tuple[str | None, str | None, str]] = set()
    unknown_kinds: dict[str, int] = {}
    unique = []
    for item in found:
        if item.beat_id is None:
            # Beat が分からないときは、同じ種類を2件までにして散らす。
            if unknown_kinds.get(item.kind, 0) >= UNKNOWN_PER_KIND:
                continue
            unknown_kinds[item.kind] = unknown_kinds.get(item.kind, 0) + 1
            unique.append(item)
            continue
        key = (item.scene_id, item.beat_id, item.kind)  # Beat ID は場面の中だけで一意
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    spread: list[Candidate] = []
    used_beats: set[tuple[str | None, str]] = set()
    for item in unique:  # まず Beat ごとに1件（場面と Beat ID の組で数える）
        if item.beat_id is None or (item.scene_id, item.beat_id) not in used_beats:
            spread.append(item)
            if item.beat_id is not None:
                used_beats.add((item.scene_id, item.beat_id))
    spread.extend(item for item in unique if item not in spread)
    report.candidates = spread[:limit]
    report.notes.append(MOTIVE_NOTE)
    return report


def render(report: CandidateReport) -> str:
    lines = [f"# 深める候補: 第{report.chapter}章（{len(report.candidates)}件）", "",
             "候補は目印。採否は引用を読んで決める。出来事は足さない（既にある出来事の動作・反応・間だけ）。", ""]
    if not report.candidates:
        lines.append("- 候補なし")
    for number, item in enumerate(report.candidates, 1):
        where = item.beat_id or "Beat 不明"
        weight = f"・{item.weight}" if item.weight else ""
        lines.append(f"{number}. {item.kind}（{where}{weight}）")
        quote = item.quote if item.quote.startswith(("「", "『")) else f"「{item.quote}」"
        lines.append(f"   - 引用: {quote}")
        lines.append(f"   - 増やし方: {item.how}")
    if report.notes:
        lines.extend(["", "## 注"])
        lines.extend(f"- {note}" for note in report.notes)
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    from console_io import configure_stdio_utf8

    configure_stdio_utf8()
    parser = argparse.ArgumentParser(description="清書・全体の深化で深める箇所の候補を出す（読むだけ）")
    parser.add_argument("work", type=Path, help="作品フォルダ（novels/NNN_作品名）")
    parser.add_argument("--chapter", type=int, required=True)
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help=f"出す件数の上限（既定 {DEFAULT_LIMIT}）")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.limit <= 0:
        parser.error("--limit must be positive")
    try:
        report = find_candidates(args.work, args.chapter, limit=args.limit)
    except FileNotFoundError as error:
        print(f"[ERROR] {error}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(asdict(report), ensure_ascii=False, indent=2))
    else:
        print(render(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
