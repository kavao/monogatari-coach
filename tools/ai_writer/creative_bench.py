"""探索機能 E2 実験A「別の展開を見る」（計画 ``20261009_ai_writer_creative_exploration.md`` §7.1・§7.3）。

6 課題（``fixtures/creative/branches.yaml``）× 2 モデル × 独立候補 3 件 = 36 回の生成。各「課題 × モデル」は
E1 の探索（``ExplorationRun``）1 回で、同じ chat 入力・候補数・max_tokens・sampling を両モデルに与える。

- 実行順: 課題ごとにモデルの順番を入れ替え、時間による偏りを抑える。止まったら ``--resume`` で続きから（成功済みは飛ばす）。
- 採点: ``sheets`` がモデル名と群の順番を伏せたシート（``blind/review.md``・``candidates.csv``・``groups.csv``）と
  対応表（``blind/key.json``）を作る。採点基準は ``fixtures/creative/rubric.md``（版 cr-1）。
- 集計: ``report`` が対応表でモデル別に戻し、文章の質・探索としての価値・自動指標（字数・トークン・切落・時間・失敗）と、
  補助指標（群内の文字 2-gram の類似度）をまとめる。
- 既定は dry-run。作品の正本へは書かない。
"""

from __future__ import annotations

import argparse
import csv
import itertools
import json
import random
import statistics
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from metron.repair import sentence_char_ngram_jaccard
from novel_char_count import count_chars
from pydantic import BaseModel, ConfigDict, Field

from . import novelai as nai
from .entities import KnownEntityDictionary
from .exploration import ExplorationRun, resolve_route
from .exploration_prompts import render_explore
from .guard import MinimumGuard
from .manifest import SourceRef
from .prompt_renderer import ExploreBranchInput
from .provider import NovelAIProvider
from .spike import REPO_ROOT, _abbreviate

FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "creative" / "branches.yaml"
RUBRIC_VERSION = "cr-1"
OUT_ROOT = REPO_ROOT / "_workingspace" / "ai_writer" / "creative_bench"
CANDIDATES = 3
BLIND_SEED = 20261009
CAND_COLUMNS = ("naturalness", "appeal", "character", "lore", "useful_surprise", "adopt", "adopt_range",
                "fix_fact", "fix_taste", "conflict", "note")
GROUP_COLUMNS = ("diversity", "adoptable_any", "review_minutes", "note")
NUMERIC = ("naturalness", "appeal", "character", "lore", "useful_surprise")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Task(_Strict):
    id: str
    theme: str
    text: str
    characters: list[str]
    fixed: list[str] = Field(default_factory=list)
    free: list[str] = Field(default_factory=list)
    judge_only: list[str] = Field(default_factory=list)


class Fixture(_Strict):
    version: int
    target_chars: int
    tasks: list[Task]


def load_fixture(path: Path = FIXTURE_PATH) -> Fixture:
    fx = Fixture.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    ids = [t.id for t in fx.tasks]
    if len(ids) != len(set(ids)):
        raise ValueError("課題 ID が重複している")
    return fx


def task_input(task: Task, target_chars: int) -> ExploreBranchInput:
    """モデルに渡すのは fixed と free だけ。judge_only は渡さない。"""
    return ExploreBranchInput(task.text, tuple(task.fixed), tuple(task.free), None, target_chars)


def known_for_task(task: Task) -> KnownEntityDictionary:
    d = KnownEntityDictionary()
    for name in task.characters:
        d.add(name, "character")
    d.add_corpus("\n".join(task.fixed))
    return d


def cells(fx: Fixture, task_ids: list[str] | None = None) -> list[tuple[Task, str]]:
    """課題ごとにモデルの順番を入れ替える（偶数番目は GLM-4.6 から、奇数番目は Xialong から）。"""
    out = []
    for i, task in enumerate(t for t in fx.tasks if not task_ids or t.id in task_ids):
        models = list(nai.CHAT_MODELS) if i % 2 == 0 else list(reversed(nai.CHAT_MODELS))
        out += [(task, m) for m in models]
    return out


def run_id_for(task: Task, model: str) -> str:
    return f"{task.id}__{model}"


# ---- 実行 -------------------------------------------------------------------

def run_bench(provider: NovelAIProvider, bench_dir: Path, fx: Fixture, todo: list[tuple[Task, str]]) -> dict[str, Any]:
    runs_dir = bench_dir / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    refs = [SourceRef.from_file("scene", FIXTURE_PATH, REPO_ROOT)]
    done, stopped = [], False
    for i, (task, model) in enumerate(todo, 1):
        rid = run_id_for(task, model)
        guard = MinimumGuard(known_for_task(task))
        if (runs_dir / rid / "manifest.json").is_file():
            run = ExplorationRun.open(provider, runs_dir / rid, guard)
            if not run.pending():
                continue
        else:
            run = ExplorationRun.create(provider, runs_dir, task_input(task, fx.target_chars), model=model,
                                        candidates=CANDIDATES, sampling="stable", run_id=rid, guard=guard,
                                        source={"label": f"creative fixture {task.id}", "task_id": task.id},
                                        refs=refs + [SourceRef.from_text("source_text", task.id, task.text)])
        summary = run.run()
        print(f"[{i}/{len(todo)}] {rid}: {summary['status']}（保存 {len(summary['saved'])} 件）", flush=True)
        done.append(rid)
        if summary["stopped"]:
            stopped = True
            break
    return {"runs": done, "stopped": stopped}


# ---- 採点シート ---------------------------------------------------------------

def _groups(bench_dir: Path, provider: NovelAIProvider) -> list[dict[str, Any]]:
    fx = load_fixture()
    tasks = {t.id: t for t in fx.tasks}
    groups = []
    for run_dir in sorted((bench_dir / "runs").iterdir()):
        if not (run_dir / "manifest.json").is_file():
            continue
        run = ExplorationRun.open(provider, run_dir)
        task_id = run.manifest["source"].get("task_id", run_dir.name.split("__")[0])
        cands = [c for c in (run.latest(s) for s in run.slots()) if c is not None]
        groups.append({"run": run_dir.name, "task": tasks[task_id], "model": run.manifest["model"], "candidates": cands})
    return groups


def _read(path: Path, key: tuple[str, ...]) -> dict[tuple[str, ...], dict[str, str]]:
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8", newline="") as f:
        return {tuple(row[k] for k in key): row for row in csv.DictReader(f)}


def write_sheets(bench_dir: Path, provider: NovelAIProvider) -> int:
    groups = _groups(bench_dir, provider)
    rng = random.Random(BLIND_SEED)
    order = sorted(groups, key=lambda g: g["run"])
    rng.shuffle(order)
    blind = bench_dir / "blind"
    blind.mkdir(exist_ok=True)
    key: dict[str, Any] = {}
    lines = [f"# 別の展開を見る 採点シート {bench_dir.name}（{len(order)} 群）", "",
             f"モデル名と群の順番は伏せてある。採点は candidates.csv（案ごと）と groups.csv（群ごと）に書く。"
             f"基準は tools/ai_writer/fixtures/creative/rubric.md（{RUBRIC_VERSION}）。key.json は採点を保存するまで開かない。", ""]
    cand_rows, group_rows = [], []
    for gi, g in enumerate(order, 1):
        code = f"G{gi:02d}"
        cands = list(g["candidates"])
        rng.shuffle(cands)
        labels = {chr(ord("A") + i): c for i, c in enumerate(cands)}
        key[code] = {"run": g["run"], "task": g["task"].id, "model": g["model"],
                     "labels": {lab: c.candidate_id for lab, c in labels.items()}}
        t = g["task"]
        lines += [f"## {code}（{t.theme}）", "", "守ること（モデルに渡した）:", *(f"- {f}" for f in t.fixed), "",
                  "自由にしてよいこと:", *(f"- {f}" for f in t.free), "",
                  "採点者だけが参照する事実（モデルには渡していない。衝突は指示違反に数えない）:",
                  *(f"- {f}" for f in t.judge_only or ["（なし）"]), "", "出発点の本文:", "", "```text", t.text, "```", ""]
        for lab, c in labels.items():
            chars = count_chars(c.text, strip_fm=False)
            lines += [f"### {code}-{lab}（{c.generation_status}、{chars}字）", ""]
            for f in (c.guard or {}).get("findings", []):
                lines.append(f"- Guard {f['severity']}: {f['check']}「{f['text'][:30]}」{f['detail']}")
            for r in c.review_items:
                lines.append(f"- 要確認: {r['detail']}")
            lines += ["", c.text or "（本文なし）", ""]
            if c.generation_status != "complete":
                excluded = c.generation_status  # 途中・失敗は採点対象外（1 点にしない）
            elif not c.text.strip():
                excluded = "本文なし"
            else:
                excluded = ""
            cand_rows.append({"code": code, "label": lab, "chars": chars, "generation_status": c.generation_status,
                              "excluded": excluded})
        group_rows.append({"code": code, "theme": t.theme})
    (blind / "review.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (blind / "key.json").write_text(json.dumps(key, ensure_ascii=False, indent=2), encoding="utf-8")
    old_c = _read(blind / "candidates.csv", ("code", "label"))
    with (blind / "candidates.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["code", "label", "chars", "generation_status", "excluded", *CAND_COLUMNS, "judge"])
        w.writeheader()
        for row in cand_rows:
            prev = old_c.get((row["code"], row["label"]), {})
            row.update({k: prev.get(k, "") for k in (*CAND_COLUMNS, "judge")})
            row["excluded"] = prev.get("excluded") or row["excluded"]
            w.writerow(row)
    old_g = _read(blind / "groups.csv", ("code",))
    with (blind / "groups.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["code", "theme", *GROUP_COLUMNS, "judge"])
        w.writeheader()
        for row in group_rows:
            prev = old_g.get((row["code"],), {})
            row.update({k: prev.get(k, "") for k in (*GROUP_COLUMNS, "judge")})
            w.writerow(row)
    return len(order)


# ---- 集計 -------------------------------------------------------------------

def _ms(values: list[float]) -> str:
    if not values:
        return "-"
    return f"{statistics.mean(values):.2f}" + (f"±{statistics.stdev(values):.2f}" if len(values) > 1 else "")


def build_report(bench_dir: Path, provider: NovelAIProvider) -> str:
    groups = {g["run"]: g for g in _groups(bench_dir, provider)}
    blind = bench_dir / "blind"
    key = json.loads((blind / "key.json").read_text(encoding="utf-8")) if (blind / "key.json").is_file() else {}
    cand_scores = _read(blind / "candidates.csv", ("code", "label"))
    group_scores = _read(blind / "groups.csv", ("code",))
    by_cid = {cid: (code, lab) for code, k in key.items() for lab, cid in k["labels"].items()}
    code_of_run = {k["run"]: code for code, k in key.items()}
    lines = [f"# 別の展開を見る 実験A 集計 {bench_dir.name}", "",
             f"採点基準 {RUBRIC_VERSION}。採点はモデル名を伏せたシートで行い、対応表でモデル別に戻した。"
             "6 課題の結果であり、統計的な優位やジャンル全体への一般化は主張しない。", ""]

    lines += ["## 自動指標（案ごと、平均±SD）", "",
              "| モデル | 案 | 失敗・途中 | 字数 | 出力トークン | 切落あり | 生成秒 | Guard 指摘 | 群内の類似度 |",
              "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for model in nai.CHAT_MODELS:
        gs = [g for g in groups.values() if g["model"] == model]
        cs = [c for g in gs for c in g["candidates"]]
        ok = [c for c in cs if c.generation_status == "complete"]
        sims = []
        for g in gs:
            texts = [c.text for c in g["candidates"] if c.text.strip()]
            pairs = [sentence_char_ngram_jaccard(a, b) for a, b in itertools.combinations(texts, 2)]
            if pairs:
                sims.append(statistics.mean(pairs))
        lines.append(
            f"| {model} | {len(cs)} | {len(cs) - len(ok)} | {_ms([count_chars(c.text, strip_fm=False) for c in ok])} | "
            f"{_ms([c.manifest.get('output_tokens', 0) for c in ok])} | "
            f"{sum(1 for c in ok if any(r['reason'] not in ('leading_space', 'trailing_space') for r in c.removals))}/{len(ok)} | "
            f"{_ms([float((c.generation or {}).get('total_sec') or 0) for c in ok])} | "
            f"{_ms([len((c.guard or {}).get('findings', [])) for c in ok])} | {_ms(sims)} |")

    lines += ["", "## 採点（案ごと、採点対象外を除く）", "",
              "| モデル | 採点数 | " + " | ".join(NUMERIC) + " | 使いたい（全文/表現/着想/なし） | 事実の修正 | 好みの修正 |",
              "| --- | --- | " + " | ".join("---" for _ in NUMERIC) + " | --- | --- | --- |"]
    for model in nai.CHAT_MODELS:
        rows = [cand_scores.get(by_cid.get(c.candidate_id, ("", ""))) for g in groups.values() if g["model"] == model
                for c in g["candidates"]]
        rows = [r for r in rows if r and r.get("naturalness") and not r.get("excluded")]
        adopts = [r.get("adopt", "") for r in rows]
        cols = [_ms([float(r[c]) for r in rows if r.get(c)]) for c in NUMERIC]
        lines.append(f"| {model} | {len(rows)} | " + " | ".join(cols) +
                     f" | {adopts.count('full')}/{adopts.count('expression')}/{adopts.count('idea')}/{adopts.count('none')} | "
                     f"{_ms([float(r['fix_fact']) for r in rows if r.get('fix_fact')])} | "
                     f"{_ms([float(r['fix_taste']) for r in rows if r.get('fix_taste')])} |")

    lines += ["", "## 採点（群ごと）", "", "| モデル | 群 | 多様性 | 使いたい案がある群 | 読み比べ分 |", "| --- | --- | --- | --- | --- |"]
    for model in nai.CHAT_MODELS:
        rows = [group_scores.get((code_of_run.get(g["run"], ""),)) for g in groups.values() if g["model"] == model]
        rows = [r for r in rows if r and r.get("diversity")]
        anyv = [int(r["adoptable_any"]) for r in rows if r.get("adoptable_any") in ("0", "1")]
        lines.append(f"| {model} | {len(rows)} | {_ms([float(r['diversity']) for r in rows])} | "
                     f"{f'{sum(anyv)}/{len(anyv)}' if anyv else '-'} | {_ms([float(r['review_minutes']) for r in rows if r.get('review_minutes')])} |")

    lines += ["", "## 課題ごと（魅力・有用な意外性は案の平均、多様性は群）", "",
              "| 課題 | " + " | ".join(f"{m} 魅力 / 意外性 / 多様性" for m in nai.CHAT_MODELS) + " |",
              "| --- | " + " | ".join("---" for _ in nai.CHAT_MODELS) + " |"]
    for task in load_fixture().tasks:
        cells_ = []
        for model in nai.CHAT_MODELS:
            g = groups.get(run_id_for(task, model))
            if not g:
                cells_.append("-")
                continue
            rows = [cand_scores.get(by_cid.get(c.candidate_id, ("", ""))) for c in g["candidates"]]
            rows = [r for r in rows if r and r.get("appeal") and not r.get("excluded")]
            gr = group_scores.get((code_of_run.get(g["run"], ""),), {})
            cells_.append(f"{_ms([float(r['appeal']) for r in rows])} / {_ms([float(r['useful_surprise']) for r in rows if r.get('useful_surprise')])} / {gr.get('diversity') or '-'}")
        lines.append(f"| {task.id}（{task.theme}） | " + " | ".join(cells_) + " |")
    return "\n".join(lines) + "\n"


# ---- CLI --------------------------------------------------------------------

def _provider(execute: bool) -> NovelAIProvider:
    if execute:
        return NovelAIProvider.from_repo(REPO_ROOT)
    return NovelAIProvider("dry-run", headers=nai.load_request_headers(REPO_ROOT))


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    parser = argparse.ArgumentParser(description="探索機能 E2 実験A（既定は dry-run）")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("plan", "run"):
        sp = sub.add_parser(name)
        sp.add_argument("--task", action="append", help="課題 ID（既定は全 6 課題）")
        if name == "run":
            sp.add_argument("--execute", action="store_true")
            sp.add_argument("--resume", help="中断した実験のディレクトリ。成功済みの候補は飛ばす")
    for name in ("sheets", "report"):
        sp = sub.add_parser(name)
        sp.add_argument("bench_dir")
    args = parser.parse_args(argv)
    fx = load_fixture()

    if args.cmd in ("plan", "run"):
        todo = cells(fx, args.task)
        print(f"課題 {len(todo) // 2} × モデル 2 × 候補 {CANDIDATES} = 生成 {len(todo) * CANDIDATES} 回（直列）。"
              f"実行順: {', '.join(run_id_for(t, m) for t, m in todo)}")
        if args.cmd == "plan" or not args.execute:
            dry = _provider(False)
            task = todo[0][0]
            for model in nai.CHAT_MODELS:
                route = resolve_route(dry, model, "stable")
                rendered = render_explore(task_input(task, fx.target_chars), model, sampling=route.sampling.values)
                print(f"\n## 例: {task.id} / {model}（両モデルで model 以外は同じ要求）")
                print(json.dumps(_abbreviate(dry.preview(rendered.request), 900), ensure_ascii=False, indent=2))
            print("\n本番実行には run --execute を付けてください。")
            return 0
        bench_dir = Path(args.resume) if args.resume else OUT_ROOT / datetime.now().strftime("%Y%m%d_%H%M%S")
        result = run_bench(_provider(True), bench_dir, fx, todo)
        n = write_sheets(bench_dir, _provider(False))
        print(f"\n採点シート {n} 群: {bench_dir / 'blind' / 'review.md'}")
        if result["stopped"]:
            print(f"止まりました。続けるには: uv run python tools/ai_writer_creative_bench_cli.py run --execute --resume {bench_dir}")
        return 0
    bench_dir = Path(args.bench_dir)
    if args.cmd == "sheets":
        n = write_sheets(bench_dir, _provider(False))
        print(f"採点シート {n} 群: {bench_dir / 'blind' / 'review.md'}")
        return 0
    report = build_report(bench_dir, _provider(False))
    (bench_dir / "report.md").write_text(report, encoding="utf-8")
    print(report)
    return 0
