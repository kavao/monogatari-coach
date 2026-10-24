#!/usr/bin/env python3
"""構造方針 rolled の抽選を、スキル novel-plot-arrange の手順6〜7のとおりに行い、抽選の記録へ追記する。

計画: _workingspace/plans/20261025_structure-theory-dosing.md（第1段階の最小手順の自動化）

入力は診断の表（JSON）。章ごとの持ち味の強さ・既存の転・範囲（抽選対象かどうか）と、作品全体の項目の
扱い（維持・見直し・未決）を書く。このツールは:

- 実効の表を決める（`--novel` 付きのレジストリ → 作業用 JSON → 標準 JSON。合成しない）。
- 振らない条件・倍率・位置の帯・回数の調停・直近の型の抑制を当てて、既存の json_weighted_pick と
  同じ抽選関数で振る（`--eval --seed` で手で振った結果と一致する）。
- 振るたびに `<作品>/_work/structure/draws.jsonl` へ1行追記する。確率0／1に固定した章や振らない章も残す。

設計・本文・`_meta.md` は書き換えない。案の作成と採用はスキルの手順8以降で行う。
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import random
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

_TOOLS = Path(__file__).resolve().parent
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

import novel_pick_registry  # noqa: E402
from json_weighted_pick import navigate, pick_from_list  # noqa: E402
from work_paths import new_only_location  # noqa: E402

STANDARD_TABLE = "_how_to.example/episode/general/episode_structure_dosing.json"
WORKING_TABLE = "_how_to/episode/general/episode_structure_dosing.json"
DRAWS_FILE = "draws.jsonl"

LIST_IDS: dict[str, str] = {
    "major_type": "structure_break_major_type",
    "minor_type": "structure_break_minor_type",
    "contract_break": "structure_contract_break",
    "payoff_mode": "structure_payoff_mode",
    "payoff_answer": "structure_payoff_answer",
    "ending_tone": "structure_ending_tone",
}
WORK_ITEMS = ("contract_break", "payoff_mode", "payoff_answer", "ending_tone")
WORK_ITEM_STATUSES = ("keep", "review", "undecided")
PREMISE_TYPE = "前提を壊す"
JST = timezone(timedelta(hours=9))


class DrawError(Exception):
    """入力・表の不備。終了コード 2 で止める。"""


# --- シードと表 -----------------------------------------------------------


def derive_seed(work_seed: int | str, scope: str, item: str, attempt: int) -> int:
    """個別のシード: `W:scope:item:attempt` の SHA-256 の先頭8桁を16進数として読んだ値。"""
    text = f"{work_seed}:{scope}:{item}:{attempt}"
    return int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:8], 16)


@dataclass
class TableRef:
    """候補を読む表。"""

    path: Path
    key: str
    registry_dir: str = ""
    fragment: str = ""

    def info(self) -> dict[str, Any]:
        data = _load_json(self.path)
        version = data.get("_meta", {}).get("version") if isinstance(data, dict) else None
        return {
            "path": _rel(self.path),
            "key": self.key,
            "version": version,
            "sha256": hashlib.sha256(self.path.read_bytes()).hexdigest(),
            "registry_dir": self.registry_dir or None,
            "fragment": self.fragment or None,
        }

    def candidates(self) -> list[Any]:
        target = navigate(_load_json(self.path), self.key)
        if not isinstance(target, list) or not target:
            raise DrawError(f"候補の配列が無い: {_rel(self.path)} の {self.key}")
        return copy.deepcopy(target)


def _root() -> Path:
    return novel_pick_registry.repo_root()


def _rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(_root().resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DrawError(f"JSON を読めない: {path}: {error}") from error


def correction_table() -> Path:
    """補正の数値を読む表: 作業用 JSON があればそちら、無ければ標準。"""
    working = _root() / WORKING_TABLE
    return working if working.is_file() else _root() / STANDARD_TABLE


def resolve_table(item: str, novel_dir: Path | None) -> TableRef:
    """実効の表: `--novel` 付きのレジストリの source → 標準を指していて作業用 JSON があれば作業用。"""
    list_id = LIST_IDS[item]
    entries = novel_pick_registry.merge_registry(novel_dir=novel_dir)
    entry = entries.get(list_id)
    if entry is None:
        raise DrawError(f"list_id が登録されていない: {list_id}")
    source = novel_pick_registry.resolve_source_path(entry.source)
    standard = (_root() / STANDARD_TABLE).resolve()
    working = _root() / WORKING_TABLE
    if source == standard and working.is_file():
        source = working.resolve()
    return TableRef(source, entry.path, entry.registry_dir, entry.fragment)


# --- 抽選と記録 -----------------------------------------------------------


@dataclass
class Recorder:
    """抽選の記録。dry-run でなければ1行ずつ追記する（すぐ記録する）。"""

    path: Path
    dry_run: bool
    next_id: int
    lines: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def open(cls, path: Path, dry_run: bool) -> "Recorder":
        last = 0
        if path.is_file():
            for raw in path.read_text(encoding="utf-8").splitlines():
                if not raw.strip():
                    continue
                try:
                    last = max(last, int(json.loads(raw).get("draw_id", 0)))
                except (json.JSONDecodeError, TypeError, ValueError, AttributeError) as error:
                    raise DrawError(f"抽選の記録を読めない行がある: {path}: {error}") from error
        return cls(path, dry_run, last + 1)

    def write(self, record: dict[str, Any]) -> int:
        draw_id = self.next_id
        self.next_id += 1
        line = {"draw_id": draw_id, "at": datetime.now(JST).isoformat(timespec="seconds"), "mode": "rolled", **record}
        self.lines.append(line)
        if not self.dry_run:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(line, ensure_ascii=False) + "\n")
        return draw_id


@dataclass
class Context:
    work_seed: int | str
    attempt: int
    recorder: Recorder
    corrections_ref: TableRef


def _draw(
    ctx: Context,
    *,
    scope: str,
    item: str,
    candidates: list[dict[str, Any]],
    table: dict[str, Any] | None,
    list_id: str,
    adjustments: list[str],
    budget: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], int]:
    seed = derive_seed(ctx.work_seed, scope, item, ctx.attempt)
    picked, index, mode, weights = pick_from_list(candidates, rng=random.Random(seed))
    if mode != "weighted":
        raise DrawError(f"重み付きで振れなかった（{mode}）: {scope} {item}。候補の「確率」欄を直す")
    record: dict[str, Any] = {
        "scope": scope,
        "item": item,
        "list_id": list_id,
        "table_source": table,
        "adjustments": adjustments,
        "candidates": candidates,
        "weights_used": weights,
        "seed": seed,
        "result": {"picked": picked, "index": index, "mode": mode},
    }
    if budget is not None:
        record["budget"] = budget
    return picked, ctx.recorder.write(record)


def _fixed(ctx: Context, *, scope: str, item: str, fixed: str, adjustments: list[str], budget: dict[str, Any]) -> int:
    """振らなかった章の記録（確率0／1に固定、または振らない条件）。"""
    return ctx.recorder.write(
        {
            "scope": scope,
            "item": item,
            "list_id": "inline",
            "table_source": ctx.corrections_ref.info(),
            "adjustments": adjustments,
            "candidates": None,
            "weights_used": None,
            "seed": None,
            "result": None,
            "fixed": fixed,
            "budget": budget,
        }
    )


def _yes_no(probability: float) -> list[dict[str, Any]]:
    probability = round(probability, 6)
    return [{"結果": "有", "確率": probability}, {"結果": "無", "確率": round(1 - probability, 6)}]


# --- 診断の表 ---------------------------------------------------------------


@dataclass
class Chapter:
    index: int
    id: str
    strength: int
    major: str | None
    major_status: str | None
    minor: bool
    backlog: int
    target: bool
    no_remainder: bool
    foreshadow_before: bool


def load_diagnosis(path: Path) -> dict[str, Any]:
    data = _load_json(path)
    if not isinstance(data, dict):
        raise DrawError("診断の表はオブジェクトにする")
    chapters = data.get("chapters")
    if not isinstance(chapters, list) or not chapters:
        raise DrawError("chapters が空")
    if data.get("seed") in (None, ""):
        raise DrawError("作品のシード seed が無い（_meta.md に記録した W を書く）")
    return data


def parse_chapters(raw: list[Any]) -> list[Chapter]:
    chapters: list[Chapter] = []
    seen: set[str] = set()
    for position, item in enumerate(raw, start=1):
        if not isinstance(item, dict) or not item.get("id"):
            raise DrawError(f"{position} 番目の章に id が無い")
        chapter_id = str(item["id"])
        if chapter_id in seen:
            raise DrawError(f"章の id が重複している: {chapter_id}")
        seen.add(chapter_id)
        strength = item.get("strength")
        if not isinstance(strength, int) or not 0 <= strength <= 3:
            raise DrawError(f"{chapter_id}: strength は 0〜3 の整数")
        backlog = item.get("backlog", 0)
        if not isinstance(backlog, int) or not 0 <= backlog <= 2:
            raise DrawError(f"{chapter_id}: backlog は 0〜2 の整数")
        major = item.get("major")
        major_text = None if major in (None, False, "") else (str(major) if major is not True else "（型の記載なし）")
        status = item.get("major_status")
        if major_text is None:
            status = None
        elif status not in ("keep", "review"):
            raise DrawError(f"{chapter_id}: 大きな転がある章は major_status を keep か review にする")
        scope = item.get("scope", "outside")
        if scope not in ("target", "outside"):
            raise DrawError(f"{chapter_id}: scope は target か outside")
        chapters.append(
            Chapter(
                index=position,
                id=chapter_id,
                strength=strength,
                major=major_text,
                major_status=status,
                minor=bool(item.get("minor", False)),
                backlog=backlog,
                target=scope == "target" or status == "review",
                no_remainder=bool(item.get("no_remainder", False)),
                foreshadow_before=bool(item.get("foreshadow_before", True)),
            )
        )
    return chapters


def reader_flat_chapters(trace_path: Path | None) -> set[str]:
    """読み進みの反応の推移（`novel_reader_walk_check.py --trace-output` の JSON）で、
    trend がすべて flat の章（場面ID `chNN-MMM` の `chNN`）。"""
    if trace_path is None:
        return set()
    trace = _load_json(trace_path)
    if not isinstance(trace, list):
        raise DrawError("読み進みの推移は JSON の配列にする")
    trends: dict[str, list[str]] = {}
    for entry in trace:
        if not isinstance(entry, dict):
            continue
        scene = str(entry.get("scene_id", ""))
        trend = entry.get("trend")
        if "-" not in scene or trend is None:
            continue
        trends.setdefault(scene.split("-", 1)[0], []).append(str(trend))
    return {chapter for chapter, values in trends.items() if values and all(value == "flat" for value in values)}


def length_range(corrections: dict[str, Any], data: dict[str, Any]) -> tuple[int, int, str]:
    override = data.get("range")
    if isinstance(override, dict) and "L" in override and "U" in override:
        lower, upper = int(override["L"]), int(override["U"])
        source = "作者の指定"
    else:
        total = data.get("total_chars")
        if not isinstance(total, int) or total <= 0:
            raise DrawError("total_chars（作品の字数）か range（L・U）が要る")
        for row in corrections["回数の範囲"]:
            limit = row.get("字数_以下")
            if limit is None or total <= limit:
                lower, upper = int(row["下限"]), int(row["上限"])
                break
        else:
            raise DrawError("回数の範囲の表に当てはまる行が無い")
        source = f"字数 {total}"
    if lower < 0 or upper < lower:
        raise DrawError(f"回数の範囲が不正: L={lower} U={upper}")
    return lower, upper, source


def _round_half_up(value: float) -> int:
    return int(math.floor(value + 0.5))


# --- 本体 -------------------------------------------------------------------


def run(diagnosis_path: Path, novel_dir: Path, *, attempt: int = 0, dry_run: bool = False, reader_trace: Path | None = None) -> dict[str, Any]:
    data = load_diagnosis(diagnosis_path)
    chapters = parse_chapters(data["chapters"])
    corrections_path = correction_table()
    corrections_ref = TableRef(corrections_path, "補正")
    corrections = navigate(_load_json(corrections_path), "補正")
    draws_path = new_only_location(novel_dir, "structure") / DRAWS_FILE
    ctx = Context(data["seed"], attempt, Recorder.open(draws_path, dry_run), corrections_ref)

    total = len(chapters)
    lower, upper, range_source = length_range(corrections, data)
    early_limit = math.floor(total * float(corrections["序盤の除外_割合"]))
    band = corrections["位置の帯"]
    centers = [_round_half_up(total * float(ratio)) for ratio in band["中心_割合"]]
    width = max(1, math.ceil(total * float(band["幅_割合"])))
    shift = math.floor(total * float(band["ずらし_割合"]))

    offset = data.get("band_offset")
    if offset is None:
        if shift == 0:
            offset = 0
        else:
            candidates = [{"ずらし": value, "確率": 1} for value in range(-shift, shift + 1)]
            picked, _ = _draw(
                ctx,
                scope="work",
                item="band_offset",
                candidates=candidates,
                table=corrections_ref.info(),
                list_id="inline",
                adjustments=[f"章数 {total}、ずらし幅 ±{shift}"],
            )
            offset = int(picked["ずらし"])
    shifted = [center + int(offset) for center in centers]

    reader_flat = reader_flat_chapters(reader_trace)

    def flat(position: int) -> bool:
        """平坦: 読み進みの推移で trend がすべて flat の章、または隣の章と強さが同じで、どちらにも転が無い章。"""
        chapter = chapters[position]
        if chapter.id in reader_flat:
            return True
        quiet = lambda c: c.major is None and not c.minor  # noqa: E731
        for neighbor in (position - 1, position + 1):
            if 0 <= neighbor < total:
                other = chapters[neighbor]
                if other.strength == chapter.strength and quiet(other) and quiet(chapter):
                    return True
        return False

    multipliers = corrections["倍率"]
    base = float(corrections["大きな転_基準確率"])
    cap = float(corrections["大きな転_上限確率"])
    recency = corrections["直近の型の抑制"]
    minor_probability = float(corrections["小さな転_確率"])

    kept = [c for c in chapters if c.major is not None and c.major_status == "keep"]
    count = len(kept)
    major_at: dict[int, str] = {c.index: str(c.major) for c in kept}  # 章番号 → 型（見直しの転は含めない）
    scope_listing = {
        "keep": [c.id for c in kept],
        "review": [c.id for c in chapters if c.major_status == "review"],
        "target": [c.id for c in chapters if c.target],
    }

    def gate_of(chapter: Chapter) -> str | None:
        """振らない条件。その時点で分かっている転（維持する転・当たった転）に照らして判定する。"""
        if chapter.major_status == "keep":
            return "維持する大きな転がある（振り直さない）"
        if chapter.index <= early_limit:
            return "序盤（最初の 1/8）"
        if chapter.no_remainder:
            return "残るもの・主人公の選択の余地を挙げられない"
        if major_at.get(chapter.index - 1) is not None:
            return "直前の章に大きな転"
        return None

    targets = [c for c in chapters if c.target]
    results: list[dict[str, Any]] = []
    shortage_reasons: list[str] = []
    first_budget = True

    for position, chapter in enumerate(targets):
        reasons = []
        gate = gate_of(chapter)
        # R: この章を含め、まだ処理していない抽選対象のうち、いま分かっている転に照らして置ける章の数
        r_value = sum(1 for c in targets[position:] if gate_of(c) is None)
        budget: dict[str, Any] = {"L": lower, "U": upper, "C": count, "R": r_value, "range_source": range_source}
        if first_budget:
            budget["chapters"] = scope_listing
            first_budget = False

        hit = False
        probability: float | None = None
        fixed: str | None = None
        if chapter.major_status == "keep":
            # 維持する転は初期の C に数え済み。振り直さず、小さな転も振らない
            fixed = f"振らない: {gate}"
            _fixed(ctx, scope=chapter.id, item="major", fixed=fixed, adjustments=[str(gate)], budget=budget)
            results.append({"id": chapter.id, "probability": None, "fixed": fixed, "major": False, "kept": True})
            continue
        if gate is not None:
            fixed = f"振らない: {gate}"
            shortage_reasons.append(f"{chapter.id}: {gate}")
            _fixed(ctx, scope=chapter.id, item="major", fixed=fixed, adjustments=[gate], budget=budget)
        elif count >= upper:
            fixed = "上限到達"
            _fixed(ctx, scope=chapter.id, item="major", fixed=fixed, adjustments=["確率0"], budget=budget)
        elif lower - count >= r_value:
            fixed = "下限のため配置"
            hit = True
            _fixed(ctx, scope=chapter.id, item="major", fixed=fixed, adjustments=["確率1"], budget=budget)
        else:
            probability = base
            previous = max([i for i in major_at if i < chapter.index], default=0)
            if chapter.index - previous >= 3:
                probability *= float(multipliers["前の大きな転から3章以上"])
                reasons.append("前の大きな転から3章以上")
            if any(abs(chapter.index - center) <= width for center in shifted):
                probability *= float(multipliers["位置の帯の中"])
                reasons.append("位置の帯の中")
            if flat(chapter.index - 1):
                probability *= float(multipliers["平坦な区間の中"])
                reasons.append("平坦な区間の中")
            if chapter.backlog >= 2:
                probability *= float(multipliers["先送りの溜まりが2"])
                reasons.append("先送りの溜まりが2")
            probability = round(min(cap, probability), 6)
            picked, _ = _draw(
                ctx,
                scope=chapter.id,
                item="major",
                candidates=_yes_no(probability),
                table=corrections_ref.info(),
                list_id="inline",
                adjustments=reasons or ["補正なし"],
                budget=budget,
            )
            hit = picked["結果"] == "有"

        chapter_result: dict[str, Any] = {"id": chapter.id, "probability": probability, "fixed": fixed, "major": hit}
        if hit:
            count += 1
            table = resolve_table("major_type", novel_dir)
            candidates = table.candidates()
            adjustments: list[str] = []
            if not chapter.foreshadow_before:
                candidates = [c for c in candidates if c.get("型") != PREMISE_TYPE]
                adjustments.append(f"{PREMISE_TYPE}を除外（前に伏線を置ける章が無い）")
            window = int(recency["章数"])
            recent = {major_at[i] for i in major_at if chapter.index - window <= i < chapter.index}
            for candidate in candidates:
                if candidate.get("型") in recent:
                    candidate["確率"] = round(float(candidate["確率"]) * float(recency["倍率"]), 6)
                    adjustments.append(f"直近{window}章で使った {candidate['型']} を ×{recency['倍率']}")
            picked, _ = _draw(
                ctx,
                scope=chapter.id,
                item="major_type",
                candidates=candidates,
                table=table.info(),
                list_id=LIST_IDS["major_type"],
                adjustments=adjustments or ["補正なし"],
            )
            major_at[chapter.index] = str(picked.get("型"))
            chapter_result["major_type"] = picked
        else:
            picked, _ = _draw(
                ctx,
                scope=chapter.id,
                item="minor",
                candidates=_yes_no(minor_probability),
                table=corrections_ref.info(),
                list_id="inline",
                adjustments=["大きな転が無い章"],
            )
            if picked["結果"] == "有":
                table = resolve_table("minor_type", novel_dir)
                picked_type, _ = _draw(
                    ctx,
                    scope=chapter.id,
                    item="minor_type",
                    candidates=table.candidates(),
                    table=table.info(),
                    list_id=LIST_IDS["minor_type"],
                    adjustments=["補正なし"],
                )
                chapter_result["minor_type"] = picked_type
        results.append(chapter_result)

    work_items = data.get("work_items") or {}
    work_results: dict[str, Any] = {}
    for item in WORK_ITEMS:
        status = work_items.get(item, "keep")
        if status not in WORK_ITEM_STATUSES:
            raise DrawError(f"work_items.{item} は keep / review / undecided")
        if status == "keep":
            work_results[item] = {"status": "keep"}
            continue
        table = resolve_table(item, novel_dir)
        picked, draw_id = _draw(
            ctx,
            scope="work",
            item=item,
            candidates=table.candidates(),
            table=table.info(),
            list_id=LIST_IDS[item],
            adjustments=[f"作品全体の項目（{status}）"],
        )
        work_results[item] = {"status": status, "picked": picked, "draw_id": draw_id}

    shortage = max(0, lower - count)
    return {
        "draws_path": _rel(draws_path),
        "dry_run": dry_run,
        "written": 0 if dry_run else len(ctx.recorder.lines),
        "draw_ids": [line["draw_id"] for line in ctx.recorder.lines],
        "range": {"L": lower, "U": upper, "source": range_source},
        "count": count,
        "shortage": shortage,
        "shortage_reasons": shortage_reasons if shortage else [],
        "band": {"centers": centers, "offset": offset, "width": width},
        "chapters": results,
        "work_items": work_results,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="構造方針 rolled の抽選（スキル novel-plot-arrange の手順6〜7）")
    parser.add_argument("novel", type=Path, help="作品フォルダ（novels/NNN_作品名）")
    parser.add_argument("diagnosis", type=Path, help="診断の表（JSON）")
    parser.add_argument("--attempt", type=int, default=0, help="やり直しの回数（個別のシードに入る。初回0）")
    parser.add_argument("--reader-trace", type=Path, help="読み進みの反応の推移（JSON）。平坦の検出に加える")
    parser.add_argument("--dry-run", action="store_true", help="抽選の記録へ書かずに結果だけ表示する")
    args = parser.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except AttributeError:
        pass
    if not args.novel.is_dir():
        print(json.dumps({"error": f"作品フォルダが無い: {args.novel}"}, ensure_ascii=False))
        return 2
    try:
        summary = run(
            args.diagnosis,
            args.novel,
            attempt=args.attempt,
            dry_run=args.dry_run,
            reader_trace=args.reader_trace,
        )
    except DrawError as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False))
        return 2
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
