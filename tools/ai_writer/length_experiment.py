"""Directed Continue の字数不足への対処の比較（計画書 Phase 1、Phase 0 結論の留保）。

Phase 0 の日本語 Benchmark で、GLM-4.6 の Directed Continue は目標 400 字に対して約 55% の字数で終わった。
次の 4 条件を、同じ Scene（``fixtures/benchmark/scenes.yaml`` の 7 場面）で比べる。

- ``A``: 基準。今の指示のまま（契約の目標字数＝400 を指示）
- ``B``: 指示字数を 1.5 倍（600 字と指示。出力上限も Renderer の換算どおり上がる）
- ``C``: 指示字数を 2 倍（800 字と指示）
- ``D``: A の出力を土台に、不足分を Expand（Insertion）で 2 か所に分けて補う（A の生成を使い回す）

評価は本来の目標（400 字）に対する字数の比と、副作用（終了条件の超過、新規事実、自然度、Expand の非進行性、
Guard の警告数）。採点基準は ``fixtures/benchmark/rubric.md``。既定は dry-run。同時生成は 1 本なので直列に送る。
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from novel_char_count import count_chars

from . import novelai as nai
from .bench import Scene, load_scenes
from .entities import KnownEntityDictionary
from .guard import MinimumGuard
from .prompt_renderer import BeatContract, DirectedContinueInput, ExpandInsertionInput
from .provider import NovelAIProvider
from .spike import REPO_ROOT, _abbreviate
from .writer import CoreWriter, WriterOutput
from .writer_cli import known_from_scene

OUT_ROOT = REPO_ROOT / "_workingspace" / "ai_writer" / "phase1_length"
CONDITIONS = {"A": 1.0, "B": 1.5, "C": 2.0}
EXPAND_GAPS = 2
EXPAND_MIN, EXPAND_MAX = 30, 150
SCORE_COLUMNS = ("end_condition", "new_fact", "naturalness", "non_progress")
_SENTENCE_END = "。！？」"


def directed_input(scene: Scene, ratio: float) -> DirectedContinueInput:
    """契約の目標字数は書き換えず、指示字数の倍率を明示する（PromptRenderer nai-r2 のモデル既定と重ねない）。"""
    c = scene.contract
    contract = BeatContract(c.objective, c.end_condition, c.target_chars, tuple(c.must_include), tuple(c.must_not))
    return DirectedContinueInput(scene.text, contract, tuple(scene.canon_facts), instruction_multiplier=ratio)


def known_for(scene: Scene) -> KnownEntityDictionary:
    """Writer CLI と同じ辞書（``writer_cli.known_from_scene``）。"""
    return known_from_scene(scene)


def gap_positions(text: str, gaps: int = EXPAND_GAPS) -> list[int]:
    """文の切れ目のうち、本文を (gaps+1) 等分する位置に近いものを選ぶ（末尾は除く）。"""
    ends = [i + 1 for i, ch in enumerate(text) if ch in _SENTENCE_END and i + 1 < len(text)]
    ends = [e for e in ends if not (e < len(text) and text[e] in _SENTENCE_END)]  # 「。」」の間は切らない
    if not ends:
        return []
    chosen: list[int] = []
    for k in range(1, gaps + 1):
        target = len(text) * k / (gaps + 1)
        best = min((e for e in ends if e not in chosen), key=lambda e: abs(e - target), default=None)
        if best is not None:
            chosen.append(best)
    return sorted(set(chosen))


@dataclass
class Sample:
    scene: Scene
    condition: str
    sample: int

    @property
    def id(self) -> str:
        return f"{self.scene.id}__{self.condition}__{self.sample}"


def _output_summary(out: WriterOutput) -> dict[str, Any]:
    return {"status": out.generation.status, "finish_reason": out.generation.finish_reason,
            "output_tokens": out.generation.output_tokens, "guard": out.guard.to_dict() if out.guard else None,
            "record": out.record()}


def expand_complement(writer: CoreWriter, scene: Scene, base: str) -> tuple[str, list[dict[str, Any]]]:
    """``base`` の不足分を Expand で補う。挿入は前から順に行い、2 か所目は 1 か所目を入れた後の本文で組み立てる。"""
    target = scene.contract.target_chars
    shortfall = target - count_chars(base, strip_fm=False)
    positions = gap_positions(base)
    if shortfall <= 0 or not positions:
        return base, []
    per_gap = max(EXPAND_MIN, min(EXPAND_MAX, math.ceil(shortfall / len(positions))))
    text, offset, inserts = base, 0, []
    for pos in positions:
        at = pos + offset
        data = ExpandInsertionInput(scene.text + text[:at], text[at:], per_gap)
        out = writer.run("expand_insertion", data)
        added = out.text if out.generation.status == "complete" else ""
        inserts.append({"at": at, "target_chars": per_gap, "text": added, **_output_summary(out)})
        text = text[:at] + added + text[at:]
        offset += len(added)
    return text, inserts


def run_sample(writer: CoreWriter, s: Sample, base_records: dict[str, dict[str, Any]]) -> dict[str, Any]:
    target = s.scene.contract.target_chars
    if s.condition == "D":
        base = base_records[f"{s.scene.id}__A__{s.sample}"]
        text, inserts = expand_complement(writer, s.scene, base["text"])
        calls = len(inserts)
        detail: dict[str, Any] = {"base_id": base["id"], "base_text": base["text"], "inserts": inserts}
        guard_warnings = base["guard_warnings"] + sum(len((i["guard"] or {}).get("findings", [])) for i in inserts)
        ok = base["ok"] and all(i["status"] == "complete" for i in inserts)
    else:
        out = writer.run("directed_continue", directed_input(s.scene, CONDITIONS[s.condition]))
        text, calls = out.text, 1
        detail = _output_summary(out)
        guard_warnings = len(out.guard.findings) if out.guard else 0
        ok = out.generation.status == "complete"
    chars = count_chars(text, strip_fm=False)
    return {"id": s.id, "scene": s.scene.id, "genre": s.scene.genre, "condition": s.condition, "sample": s.sample,
            "ok": ok, "text": text, "chars": chars, "ratio": round(chars / target, 3), "calls": calls,
            "guard_warnings": guard_warnings, "detail": detail}


def samples(scenes: list[Scene], conditions: list[str], n: int) -> list[Sample]:
    # D は同じ場面・試行の A の後に置く
    order = [c for c in ("A", "D", "B", "C") if c in conditions]
    return [Sample(sc, c, k) for k in range(1, n + 1) for sc in scenes for c in order]


# ---- 評価シートと集計 -------------------------------------------------------------

def _records(run_dir: Path) -> list[dict[str, Any]]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted((run_dir / "cells").glob("*.json"))]


def _marked(rec: dict[str, Any]) -> str:
    """D の挿入箇所を〔＋…〕で見えるようにする。"""
    if rec["condition"] != "D":
        return rec["text"]
    # ins["at"] は先の挿入を入れたあとの本文上の位置。元の本文上の位置に戻してから印を付ける
    base = rec["detail"]["base_text"]
    out, prev, inserted = "", 0, 0
    for ins in sorted(rec["detail"]["inserts"], key=lambda i: i["at"]):
        pos = ins["at"] - inserted
        out += base[prev:pos] + f"〔＋{ins['text']}〕"
        prev, inserted = pos, inserted + len(ins["text"])
    return out + base[prev:]


def write_sheets(run_dir: Path, scenes: list[Scene]) -> None:
    recs = _records(run_dir)
    lines = [f"# 字数不足への対処の比較 {run_dir.name}", "",
             "採点は scores.csv。基準は tools/ai_writer/fixtures/benchmark/rubric.md（end_condition / new_fact / naturalness、"
             "D は non_progress も）。D の〔＋…〕は Expand で挿入した文。", ""]
    for sc in scenes:
        group = [r for r in recs if r["scene"] == sc.id]
        if not group:
            continue
        c = sc.contract
        lines += [f"## {sc.id}（{sc.genre}）", "", "```text", sc.text, "```", "",
                  f"- 契約: {c.objective} / 含める: {'、'.join(c.must_include)} / 禁止: {'、'.join(c.must_not)} / 終わり: {c.end_condition}",
                  f"- 事実: {' '.join(sc.canon_facts)}", ""]
        for r in sorted(group, key=lambda r: (r["sample"], r["condition"])):
            lines += [f"### {r['condition']} #{r['sample']}（{r['chars']}字、目標比 {r['ratio']}、Guard 警告 {r['guard_warnings']}）",
                      "", _marked(r), ""]
    (run_dir / "review.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    path = run_dir / "scores.csv"
    existing: dict[str, dict[str, str]] = {}
    if path.exists():
        with path.open(encoding="utf-8", newline="") as f:
            existing = {row["id"]: row for row in csv.DictReader(f)}
    header = ["id", "scene", "condition", "sample", *SCORE_COLUMNS, "excluded", "judge", "note"]
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=header)
        w.writeheader()
        for r in sorted(recs, key=lambda r: r["id"]):
            row = {"id": r["id"], "scene": r["scene"], "condition": r["condition"], "sample": r["sample"]}
            row.update({k: existing.get(r["id"], {}).get(k, "") for k in (*SCORE_COLUMNS, "excluded", "judge", "note")})
            if not r["ok"] and not row["excluded"]:
                row["excluded"] = "生成の失敗または途中終了"
            w.writerow(row)


def _ms(values: list[float]) -> str:
    if not values:
        return "-"
    return f"{statistics.mean(values):.2f}" + (f"±{statistics.stdev(values):.2f}" if len(values) > 1 else "")


def build_report(run_dir: Path) -> str:
    recs = _records(run_dir)
    scores: dict[str, dict[str, str]] = {}
    if (run_dir / "scores.csv").exists():
        with (run_dir / "scores.csv").open(encoding="utf-8", newline="") as f:
            scores = {row["id"]: row for row in csv.DictReader(f)}
    lines = [f"# 字数不足への対処の比較 集計 {run_dir.name}", "",
             "| 条件 | 件数 | 生成回数 | 字数 | 目標比 | 目標比 0.8〜1.25 | Guard 警告 | 採点数 | end met / unmet / exceeded | 新規事実 | 自然度 | 非進行 |",
             "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for cond in ("A", "B", "C", "D"):
        g = [r for r in recs if r["condition"] == cond and r["ok"]]
        if not g:
            continue
        s = [scores[r["id"]] for r in g if r["id"] in scores and scores[r["id"]].get("end_condition")
             and not scores[r["id"]].get("excluded")]
        ends = [x["end_condition"] for x in s]
        nf = [int(x["new_fact"]) for x in s if x.get("new_fact") in ("0", "1")]
        within = sum(1 for r in g if 0.8 <= r["ratio"] <= 1.25)
        lines.append(
            f"| {cond} | {len(g)} | {sum(r['calls'] for r in g)} | {_ms([r['chars'] for r in g])} | {_ms([r['ratio'] for r in g])} | "
            f"{within}/{len(g)} | {_ms([r['guard_warnings'] for r in g])} | {len(s)} | "
            f"{ends.count('met')} / {ends.count('unmet')} / {ends.count('exceeded')} | {f'{sum(nf)}/{len(nf)}' if nf else '-'} | "
            f"{_ms([float(x['naturalness']) for x in s if x.get('naturalness')])} | "
            f"{_ms([float(x['non_progress']) for x in s if x.get('non_progress')])} |")
    failed = [r["id"] for r in recs if not r["ok"]]
    lines += ["", f"- 失敗・途中終了: {', '.join(failed) or 'なし'}"]
    return "\n".join(lines) + "\n"


# ---- CLI -----------------------------------------------------------------------

def cmd_plan(args: argparse.Namespace) -> int:
    scenes = [s for s in load_scenes() if not args.scene or s.id in args.scene]
    todo = samples(scenes, args.condition, args.samples)
    n_dc = sum(1 for s in todo if s.condition != "D")
    n_ex = sum(EXPAND_GAPS for s in todo if s.condition == "D")
    print(f"Scene {len(scenes)} × 条件 {','.join(args.condition)} × {args.samples} 回: Directed Continue {n_dc} 回 + "
          f"Expand 最大 {n_ex} 回 = 最大 {n_dc + n_ex} 回（直列。D は A の出力が目標以上なら Expand を送らない）")
    w = CoreWriter(NovelAIProvider("dry-run", headers=nai.load_request_headers(REPO_ROOT)))
    sc = scenes[0]
    for cond in [c for c in args.condition if c != "D"]:
        plan = w.plan("directed_continue", directed_input(sc, CONDITIONS[cond]))
        body = plan["request"]["body"]
        print(f"\n## 条件 {cond}（例: {sc.id}）指示 {int(sc.contract.target_chars * CONDITIONS[cond])} 字 max_tokens={body['max_tokens']}")
        print(json.dumps(_abbreviate(body, 400), ensure_ascii=False, indent=2))
    if "D" in args.condition:
        example = ExpandInsertionInput(sc.text + "（A の出力の前半）", "（A の出力の後半）", 90)
        body = w.plan("expand_insertion", example)["request"]["body"]
        print(f"\n## 条件 D（例: {sc.id}）A の出力の文の切れ目 {EXPAND_GAPS} か所へ、不足分を半分ずつ（{EXPAND_MIN}〜{EXPAND_MAX} 字）挿入")
        print(json.dumps(_abbreviate(body, 400), ensure_ascii=False, indent=2))
    print("\n本番実行には run --execute を付けてください。")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    if not args.execute:
        return cmd_plan(args)
    scenes = [s for s in load_scenes() if not args.scene or s.id in args.scene]
    todo = samples(scenes, args.condition, args.samples)
    run_dir = Path(args.resume) if args.resume else OUT_ROOT / datetime.now().strftime("%Y%m%d_%H%M%S")
    (run_dir / "cells").mkdir(parents=True, exist_ok=True)
    provider = NovelAIProvider.from_repo(REPO_ROOT)
    bases: dict[str, dict[str, Any]] = {}
    for i, s in enumerate(todo, 1):
        path = run_dir / "cells" / f"{s.id}.json"
        if path.exists():
            rec = json.loads(path.read_text(encoding="utf-8"))
            if rec.get("ok"):
                bases[s.id] = rec
                continue
        writer = CoreWriter(provider, guard=MinimumGuard(known_for(s.scene)))
        rec = run_sample(writer, s, bases)
        bases[s.id] = rec
        path.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[{i}/{len(todo)}] {s.id}: {'ok' if rec['ok'] else '失敗'} {rec['chars']}字 目標比 {rec['ratio']} "
              f"生成 {rec['calls']} 回 Guard 警告 {rec['guard_warnings']}", flush=True)
    write_sheets(run_dir, scenes)
    (run_dir / "report.md").write_text(build_report(run_dir), encoding="utf-8")
    print(f"\n保存先: {run_dir}")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir)
    write_sheets(run_dir, load_scenes())
    report = build_report(run_dir)
    (run_dir / "report.md").write_text(report, encoding="utf-8")
    print(report)
    return 0


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    parser = argparse.ArgumentParser(description="Directed Continue の字数不足への対処の比較（既定は dry-run）")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name, func in (("plan", cmd_plan), ("run", cmd_run)):
        sp = sub.add_parser(name)
        sp.add_argument("--scene", action="append")
        sp.add_argument("--condition", action="append", choices=("A", "B", "C", "D"))
        sp.add_argument("--samples", type=int, default=2)
        if name == "run":
            sp.add_argument("--execute", action="store_true")
            sp.add_argument("--resume")
        sp.set_defaults(func=func)
    rp = sub.add_parser("report")
    rp.add_argument("run_dir")
    rp.set_defaults(func=cmd_report)
    args = parser.parse_args(argv)
    if getattr(args, "condition", None) is None and hasattr(args, "samples"):
        args.condition = ["A", "B", "C", "D"]
    if "D" in getattr(args, "condition", []) and "A" not in args.condition:
        parser.error("D は A の出力を使うので、A も指定する")
    return args.func(args)

