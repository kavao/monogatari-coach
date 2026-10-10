"""Phase 0 日本語 Benchmark（計画書 §52〜54）。

固定 Scene（``fixtures/benchmark/scenes.yaml``）× 操作 × モデル × 試行回数で生成し、
自動指標と、人または判定者が付ける採点（``scores.csv``）を集計する。

操作と方式は Phase 0 Spike で良かったものに固定する。
- ``continue``: completions に本文を渡し、素の続きを書かせる（指示なし）
- ``directed_continue``: chat に Beat Contract と本文を渡し、続きを書かせる
- ``expand``: chat に挿入位置の印を付けた本文を渡し、挟む文を書かせる（Insertion）

字数はプロジェクト標準の ``novel_char_count.count_chars``、出力トークン数はチャンクの token_ids。
同時生成は 1 本までなので直列に送る。既定は dry-run。中断したら ``--resume <run_dir>`` で続きから。
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from metron.repair import sentence_char_ngram_jaccard, split_sentences
from novel_char_count import count_chars
from pydantic import BaseModel, ConfigDict, Field

from . import novelai as nai
from .expand_spike import GAP, _call, clean_insertion, cut_trailer
from .spike import REPO_ROOT, STANDARD_SAMPLING, _abbreviate

SCENES_PATH = Path(__file__).resolve().parent / "fixtures" / "benchmark" / "scenes.yaml"
OUT_ROOT = REPO_ROOT / "_workingspace" / "ai_writer" / "phase0_bench"
OPERATIONS = ("continue", "directed_continue", "expand")
CONTINUE_CHARS = 400
EXPAND_CHARS = 80
CHARS_PER_TOKEN = 1.3  # Phase 0 Spike の暫定 median
SYSTEM = "あなたは日本語の小説家です。指示された本文だけを出力し、前置き・説明・見出し・区切り記号は書きません。"

# 採点項目（計画書 §54）。判断基準は fixtures/benchmark/rubric.md を正とする。
SCORE_COLUMNS = (
    "naturalness",      # 日本語自然度 1-5
    "appeal",           # 文章の魅力 1-5
    "compliance",       # 指示遵守 1-5（continue は空欄）
    "character",        # Character 維持 1-5
    "lore",             # Lore 維持 1-5
    "new_fact",         # 新規事実 0/1
    "continuity",       # 続きを書く能力 1-5（continue / directed_continue）
    "non_progress",     # Expand 非進行性 1-5（expand）
    "end_condition",    # end_condition 遵守 met / unmet / exceeded（directed_continue）
)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SceneContract(_Strict):
    objective: str
    must_include: list[str] = Field(default_factory=list)
    must_not: list[str] = Field(default_factory=list)
    end_condition: str
    target_chars: int


class Scene(_Strict):
    id: str
    genre: str
    passage: str
    characters: list[str]
    canon_facts: list[str] = Field(default_factory=list)
    contract: SceneContract

    @property
    def text(self) -> str:
        return self.passage.replace(GAP, "")

    def marked(self) -> str:
        return self.passage.replace(GAP, "【ここに挿入】")

    def after_gap(self) -> str:
        return self.passage.split(GAP, 1)[1]


def load_scenes(path: Path = SCENES_PATH) -> list[Scene]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    scenes = [Scene.model_validate(s) for s in raw["scenes"]]
    for s in scenes:
        if s.passage.count(GAP) != 1:
            raise ValueError(f"{s.id}: 挿入位置 {GAP} はちょうど 1 つにする")
    return scenes


# ---- 要求の組み立て ----------------------------------------------------------

def _chat(model: str, user: str, max_tokens: int) -> tuple[str, dict[str, Any]]:
    body = nai.build_chat_body(model, [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
                               max_tokens=max_tokens, sampling=STANDARD_SAMPLING)
    return nai.TEXT_HOST + nai.CHAT_PATH, body


def build_continue(scene: Scene, model: str) -> tuple[str, dict[str, Any]]:
    body = nai.build_completions_body(model, scene.text, max_tokens=int(CONTINUE_CHARS / CHARS_PER_TOKEN),
                                      sampling=STANDARD_SAMPLING)
    return nai.TEXT_HOST + nai.COMPLETIONS_PATH, body


def build_directed(scene: Scene, model: str) -> tuple[str, dict[str, Any]]:
    c = scene.contract
    user = (
        f"次の小説本文の続きを、約{c.target_chars}字で書いてください。続きの本文だけを出力してください。\n\n"
        "この場面の契約:\n"
        f"- 目的: {c.objective}\n"
        f"- 必ず含める: {'、'.join(c.must_include)}\n"
        f"- してはいけない: {'、'.join(c.must_not)}\n"
        f"- 終わる位置: {c.end_condition}。そこで書くのをやめる\n"
        "- 登場人物と設定は、本文と次の事実に合わせる:\n"
        + "".join(f"  - {f}\n" for f in scene.canon_facts)
        + "\n本文:\n" + scene.text
    )
    return _chat(model, user, max_tokens=int(c.target_chars * 1.6 / CHARS_PER_TOKEN))


def build_expand(scene: Scene, model: str) -> tuple[str, dict[str, Any]]:
    user = (
        f"次の小説本文の【ここに挿入】の位置に入れる文を、{EXPAND_CHARS}字ほど（1〜3文）で書いてください。"
        "挿入する文だけを出力してください。\n\n"
        "条件:\n"
        "- 新しい出来事、新しい人物、新しい場所、新しい事実を足さない。\n"
        "- 足してよいのは、情景、感情、動作の細部だけ。\n"
        "- 前後の文を繰り返したり、先の展開を書いたりしない。\n"
        "\n本文:\n" + scene.marked()
    )
    return _chat(model, user, max_tokens=int(EXPAND_CHARS * 2 / CHARS_PER_TOKEN))


BUILDERS: dict[str, Callable[[Scene, str], tuple[str, dict[str, Any]]]] = {
    "continue": build_continue, "directed_continue": build_directed, "expand": build_expand,
}


# ---- 整形と自動指標 -----------------------------------------------------------

def _trim_partial_tail(text: str) -> str:
    """途中で切れた末尾の文を落とす（文末記号が一つもなければそのまま）。"""
    if text and text[-1] not in "。！？」』…":
        cut = max(text.rfind(c) for c in "。！？」』")
        if cut >= 0:
            return text[: cut + 1]
    return text


def clean_output(op: str, raw: str) -> str:
    if op == "expand":
        return clean_insertion(raw)
    return _trim_partial_tail(cut_trailer(raw).strip("\n").rstrip())


def auto_metrics(scene: Scene, op: str, raw: str, text: str, output_tokens: int) -> dict[str, Any]:
    chars = count_chars(text, strip_fm=False)
    raw_chars = count_chars(raw.strip(), strip_fm=False)
    tail = split_sentences(scene.text)[-3:]
    head = split_sentences(text)[:1]
    metrics: dict[str, Any] = {
        "chars": chars,
        "trimmed_chars": max(0, raw_chars - chars),
        "output_tokens": output_tokens,
        "chars_per_token": round(raw_chars / output_tokens, 3) if output_tokens else None,
        "markdown": "**" in raw or "***" in raw,
        "fullwidth_space_breaks": "　　" in text,
        "names_present": [n for n in scene.characters if n in text],
        "repeats_source": round(max((sentence_char_ngram_jaccard(head[0], t) for t in tail), default=0.0), 3) if head else 0.0,
    }
    if op == "directed_continue":
        metrics["target_ratio"] = round(chars / scene.contract.target_chars, 3)
        metrics["must_include_hits"] = [w for w in scene.contract.must_include if w in text or w in scene.text]
        metrics["must_include_in_output"] = [w for w in scene.contract.must_include if w in text]
    if op == "expand":
        following = split_sentences(scene.after_gap())
        metrics["next_sentence_jaccard"] = round(sentence_char_ngram_jaccard(text, following[0]), 3) if following and text else 0.0
    return metrics


# ---- 実行 -------------------------------------------------------------------

@dataclass(frozen=True)
class Cell:
    scene: Scene
    op: str
    model: str
    sample: int

    @property
    def id(self) -> str:
        return f"{self.scene.id}__{self.op}__{self.model}__{self.sample}"


def cells(scenes: list[Scene], ops: list[str] | None, models: list[str] | None, samples: int,
          scene_ids: list[str] | None) -> list[Cell]:
    bad = [o for o in ops or [] if o not in OPERATIONS]
    if bad:
        raise SystemExit(f"未知の操作: {', '.join(bad)}")
    # 試行回を外側に回し、同じ条件が時間的に偏らないようにする
    return [Cell(s, op, m, n)
            for n in range(1, samples + 1)
            for s in scenes if not scene_ids or s.id in scene_ids
            for op in OPERATIONS if not ops or op in ops
            for m in nai.CHAT_MODELS if not models or m in models]


def run_cell(cell: Cell, token: str, headers: dict[str, str]) -> dict[str, Any]:
    url, body = BUILDERS[cell.op](cell.scene, cell.model)
    res = _call(url, token, body, headers)
    text = clean_output(cell.op, res.text)
    return {"id": cell.id, "scene": cell.scene.id, "genre": cell.scene.genre, "op": cell.op, "model": cell.model,
            "sample": cell.sample, "ok": res.status == 200, "output": text,
            "metrics": auto_metrics(cell.scene, cell.op, res.text, text, res.output_tokens),
            "request": {"url": url, "body": body}, "result": res.to_dict()}


RUBRIC_PATH = Path(__file__).resolve().parent / "fixtures" / "benchmark" / "rubric.md"
EXTRA_COLUMNS = ("excluded", "judge", "note")
DIFF_THRESHOLD = 2
BLIND_SEED = 20261009


def _load_records(run_dir: Path) -> list[dict[str, Any]]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(run_dir.glob("cells/*.json"))]


def _read_csv(path: Path, key: str) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8", newline="") as f:
        return {row[key]: row for row in csv.DictReader(f)}


def _scene_block(scene: Scene) -> list[str]:
    c = scene.contract
    return ["```text", scene.passage, "```", "",
            f"- 契約: {c.objective} / 含める: {'、'.join(c.must_include)} / 禁止: {'、'.join(c.must_not)} / 終わり: {c.end_condition}",
            f"- 事実: {' '.join(scene.canon_facts)}",
            f"- {GAP} は Expand の挿入位置（Continue / Directed Continue では無視する）", ""]


def write_sheets(run_dir: Path, scenes: list[Scene]) -> None:
    """review.md（読む用）と scores.csv（一次点。既存の採点は消さない）を作る。"""
    records = _load_records(run_dir)
    lines = [f"# 日本語 Benchmark {run_dir.name}", "",
             f"一次点は scores.csv に書く。採点基準は `{RUBRIC_PATH.relative_to(REPO_ROOT).as_posix()}`。", ""]
    for scene in scenes:
        group = [r for r in records if r["scene"] == scene.id]
        if not group:
            continue
        lines += [f"## {scene.id}（{scene.genre}）", "", *_scene_block(scene)]
        for r in sorted(group, key=lambda r: (r["op"], r["model"], r["sample"])):
            m = r["metrics"]
            lines += [f"### {r['op']} / {r['model']} / #{r['sample']}（{m['chars']}字、{m['output_tokens']}tok、切落 {m['trimmed_chars']}）",
                      "", r["output"] or f"（空。誤り: {r['result'].get('error')}）", ""]
    (run_dir / "review.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    scores_path = run_dir / "scores.csv"
    existing = _read_csv(scores_path, "id")
    header = ["id", "scene", "op", "model", "sample", *SCORE_COLUMNS, *EXTRA_COLUMNS]
    with scores_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=header)
        writer.writeheader()
        for r in sorted(records, key=lambda r: r["id"]):
            row = {k: r[k] for k in ("id", "scene", "op", "model", "sample")}
            row.update({k: existing.get(r["id"], {}).get(k, "") for k in (*SCORE_COLUMNS, *EXTRA_COLUMNS)})
            if not r["ok"] and not row["excluded"]:
                row["excluded"] = f"通信失敗 {r['result'].get('status')}"
            elif not r["output"] and not row["excluded"]:
                row["excluded"] = "空出力"
            writer.writerow(row)


# ---- 独立採点と照合 -----------------------------------------------------------

def make_blind(run_dir: Path, scenes: list[Scene], sample: int = 1, seed: int = BLIND_SEED) -> int:
    """モデル名と一次点を伏せた独立採点用シートを ``blind/`` に作る。対応表は blind_key.json。"""
    import random

    records = [r for r in _load_records(run_dir) if r["sample"] == sample]
    random.Random(seed).shuffle(records)
    blind_dir = run_dir / "blind"
    blind_dir.mkdir(exist_ok=True)
    key = {f"B{i:03d}": r["id"] for i, r in enumerate(records, 1)}
    (blind_dir / "blind_key.json").write_text(json.dumps(key, ensure_ascii=False, indent=2), encoding="utf-8")
    by_id = {r["id"]: r for r in records}
    by_scene = {s.id: s for s in scenes}
    lines = [f"# 独立採点シート {run_dir.name}（試行 #{sample}、{len(key)} 件）", "",
             f"モデル名と一次点は伏せてある。採点は blind/scores_independent.csv に書く。基準は `{RUBRIC_PATH.relative_to(REPO_ROOT).as_posix()}`。", ""]
    for code, cid in key.items():
        r = by_id[cid]
        lines += [f"## {code}（{r['scene']} / {r['op']}）", "", *_scene_block(by_scene[r["scene"]]),
                  "出力:", "", r["output"] or "（空）", ""]
    (blind_dir / "review_blind.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    path = blind_dir / "scores_independent.csv"
    existing = _read_csv(path, "code")
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["code", "scene", "op", *SCORE_COLUMNS, *EXTRA_COLUMNS])
        writer.writeheader()
        for code, cid in key.items():
            row = {"code": code, "scene": by_id[cid]["scene"], "op": by_id[cid]["op"]}
            row.update({k: existing.get(code, {}).get(k, "") for k in (*SCORE_COLUMNS, *EXTRA_COLUMNS)})
            writer.writerow(row)
    return len(key)


def compare_scores(run_dir: Path) -> dict[str, Any]:
    """一次点と独立点を照合し、点差 2 以上・判定の食い違いと、残りの試行を確かめる条件を返す。"""
    key = json.loads((run_dir / "blind" / "blind_key.json").read_text(encoding="utf-8"))
    primary = _read_csv(run_dir / "scores.csv", "id")
    independent = _read_csv(run_dir / "blind" / "scores_independent.csv", "code")
    numeric = [c for c in SCORE_COLUMNS if c not in ("new_fact", "end_condition")]
    flagged: list[dict[str, Any]] = []
    unscored: list[str] = []
    for code, cid in key.items():
        p, q = primary.get(cid, {}), independent.get(code, {})
        if p.get("excluded") or q.get("excluded"):
            continue
        if not p.get("naturalness") or not q.get("naturalness"):
            unscored.append(code)
            continue
        reasons = []
        for c in numeric:
            if p.get(c) and q.get(c) and abs(float(p[c]) - float(q[c])) >= DIFF_THRESHOLD:
                reasons.append(f"{c} {p[c]}→{q[c]}")
        for c in ("new_fact", "end_condition"):
            if (p.get(c) or q.get(c)) and p.get(c) != q.get(c):
                reasons.append(f"{c} {p.get(c) or '空'}→{q.get(c) or '空'}")
        if reasons:
            flagged.append({"code": code, "id": cid, "reasons": reasons,
                            "note_primary": p.get("note", ""), "note_independent": q.get("note", "")})
    conditions = sorted({"__".join(f["id"].split("__")[:3]) for f in flagged})
    return {"compared": len(key) - len(unscored), "unscored": unscored, "flagged": flagged,
            "recheck_conditions": conditions}


def compare_md(run_dir: Path, result: dict[str, Any]) -> str:
    lines = [f"# 一次点と独立点の照合 {run_dir.name}", "",
             f"- 照合 {result['compared']} 件、未採点 {len(result['unscored'])} 件、要照合 {len(result['flagged'])} 件",
             f"- 残り2件も確認する条件（scene__op__model）: {', '.join(result['recheck_conditions']) or 'なし'}", "",
             "| code | セル | 食い違い | 一次 note | 独立 note |", "| --- | --- | --- | --- | --- |"]
    for f in result["flagged"]:
        lines.append(f"| {f['code']} | {f['id']} | {'、'.join(f['reasons'])} | {f['note_primary']} | {f['note_independent']} |")
    return "\n".join(lines) + "\n"


# ---- 集計 -------------------------------------------------------------------

def _percentiles(values: list[float]) -> dict[str, Any]:
    if len(values) < 2:
        return {"p10": None, "median": values[0] if values else None, "p90": None, "n": len(values)}
    deciles = statistics.quantiles(values, n=10)
    return {"p10": round(deciles[0], 3), "median": round(statistics.median(values), 3), "p90": round(deciles[-1], 3),
            "n": len(values)}


def _mean_sd(values: list[float]) -> str:
    if not values:
        return "-"
    if len(values) == 1:
        return f"{values[0]:.2f}"
    return f"{statistics.mean(values):.2f}±{statistics.stdev(values):.2f}"


def _mean(values: list[float]) -> float | None:
    return statistics.mean(values) if values else None


def build_report(run_dir: Path) -> str:
    records = _load_records(run_dir)
    final_path = run_dir / "scores_final.csv"
    source = "scores_final.csv（照合後の確定点）" if final_path.exists() else "scores.csv（一次点）"
    scores = _read_csv(final_path if final_path.exists() else run_dir / "scores.csv", "id")
    lines = [f"# 日本語 Benchmark 集計 {run_dir.name}", ""]
    failed = [r["id"] for r in records if not r["ok"]]
    excluded = [cid for cid, row in scores.items() if row.get("excluded")]
    lines += [f"- セル {len(records)} 件、通信失敗 {len(failed)} 件、採点対象外 {len(excluded)} 件",
              f"- 採点の出典: {source}", ""]

    cpt = [r["metrics"]["chars_per_token"] for r in records if r["metrics"].get("chars_per_token")]
    lines += ["## chars_per_token（出力、整形前の字数 ÷ token_ids 数）", "", "| 対象 | p10 | median | p90 | n |", "| --- | --- | --- | --- | --- |"]
    for label, vals in [("全体", cpt)] + [(m, [r["metrics"]["chars_per_token"] for r in records
                                               if r["model"] == m and r["metrics"].get("chars_per_token")]) for m in nai.CHAT_MODELS]:
        p = _percentiles(vals)
        lines.append(f"| {label} | {p['p10']} | {p['median']} | {p['p90']} | {p['n']} |")

    lines += ["", "## 自動指標（平均±標準偏差）", "",
              "| 操作 | モデル | 字数 | 目標比 | 切落あり | 冒頭の反復 | 次文の類似 | Markdown |", "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for op in OPERATIONS:
        for model in nai.CHAT_MODELS:
            g = [r["metrics"] for r in records if r["op"] == op and r["model"] == model]
            if not g:
                continue
            lines.append(
                f"| {op} | {model} | {_mean_sd([m['chars'] for m in g])} | "
                f"{_mean_sd([m['target_ratio'] for m in g if 'target_ratio' in m])} | "
                f"{sum(1 for m in g if m['trimmed_chars'] > 0)}/{len(g)} | {_mean_sd([m['repeats_source'] for m in g])} | "
                f"{_mean_sd([m['next_sentence_jaccard'] for m in g if 'next_sentence_jaccard' in m])} | "
                f"{sum(1 for m in g if m['markdown'])}/{len(g)} |")

    def scored(op: str, model: str, scene: str | None = None) -> list[dict[str, str]]:
        rows = [scores[r["id"]] for r in records
                if r["op"] == op and r["model"] == model and (scene is None or r["scene"] == scene) and r["id"] in scores]
        return [row for row in rows if row.get("naturalness") and not row.get("excluded")]

    numeric = [c for c in SCORE_COLUMNS if c not in ("new_fact", "end_condition")]
    lines += ["", "## 採点（平均±標準偏差。採点対象外を除く）", "",
              "| 操作 | モデル | 採点数 | " + " | ".join(numeric) + " | 新規事実 | end met / unmet / exceeded |",
              "| --- | --- | --- | " + " | ".join("---" for _ in numeric) + " | --- | --- |"]
    for op in OPERATIONS:
        for model in nai.CHAT_MODELS:
            rows = scored(op, model)
            if not rows:
                lines.append(f"| {op} | {model} | 0 | " + " | ".join("-" for _ in numeric) + " | - | - |")
                continue
            cols = [_mean_sd([float(row[c]) for row in rows if row.get(c)]) for c in numeric]
            nf = [int(row["new_fact"]) for row in rows if row.get("new_fact") in ("0", "1")]
            ends = [row["end_condition"] for row in rows if row.get("end_condition")]
            end_cell = f"{ends.count('met')} / {ends.count('unmet')} / {ends.count('exceeded')}" if ends else "-"
            lines.append(f"| {op} | {model} | {len(rows)} | " + " | ".join(cols)
                         + f" | {f'{sum(nf)}/{len(nf)}' if nf else '-'} | {end_cell} |")

    a, b = nai.CHAT_MODELS[1], nai.CHAT_MODELS[0]
    lines += ["", f"## 同じ場面・操作でのモデル間差（{a} − {b}、平均の差）", "",
              "魅力と遵守を別々に比べる。7 場面の結果をジャンル全体の性質として一般化しない。", "",
              "| 場面 | 操作 | appeal 差 | compliance 差 | 採点数 |", "| --- | --- | --- | --- | --- |"]
    scene_ids = list(dict.fromkeys(r["scene"] for r in records))
    for scene in scene_ids:
        for op in OPERATIONS:
            ra, rb = scored(op, a, scene), scored(op, b, scene)
            if not ra or not rb:
                continue
            diffs = []
            for col in ("appeal", "compliance"):
                ma = _mean([float(x[col]) for x in ra if x.get(col)])
                mb = _mean([float(x[col]) for x in rb if x.get(col)])
                diffs.append(f"{ma - mb:+.2f}" if ma is not None and mb is not None else "-")
            lines.append(f"| {scene} | {op} | {diffs[0]} | {diffs[1]} | {len(ra)}/{len(rb)} |")
    return "\n".join(lines) + "\n"


# ---- CLI --------------------------------------------------------------------

def cmd_plan(args: argparse.Namespace) -> int:
    scenes = load_scenes()
    todo = cells(scenes, args.op, args.model, args.samples, args.scene)
    print(f"Scene {len(scenes)} × 操作 {len(args.op or OPERATIONS)} × モデル {len(args.model or nai.CHAT_MODELS)} × {args.samples} 回 = 生成 {len(todo)} 回（直列）")
    shown: set[str] = set()
    for cell in todo:
        if cell.op in shown:
            continue
        shown.add(cell.op)
        url, body = BUILDERS[cell.op](cell.scene, cell.model)
        print(f"\n## 例: {cell.op} / {cell.scene.id} / {cell.model}\nPOST {url}")
        print(json.dumps(_abbreviate(body, 900), ensure_ascii=False, indent=2))
    print("\n本番実行には run --execute を付けてください。")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    if not args.execute:
        return cmd_plan(args)
    scenes = load_scenes()
    todo = cells(scenes, args.op, args.model, args.samples, args.scene)
    run_dir = Path(args.resume) if args.resume else OUT_ROOT / datetime.now().strftime("%Y%m%d_%H%M%S")
    (run_dir / "cells").mkdir(parents=True, exist_ok=True)
    token = nai.load_token(REPO_ROOT)
    headers = nai.load_request_headers(REPO_ROOT)
    for i, cell in enumerate(todo, 1):
        path = run_dir / "cells" / f"{cell.id}.json"
        if path.exists() and json.loads(path.read_text(encoding="utf-8")).get("ok"):
            continue
        rec = run_cell(cell, token, headers)
        path.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
        m = rec["metrics"]
        status = "ok" if rec["ok"] else f"失敗 {rec['result'].get('status')}"
        print(f"[{i}/{len(todo)}] {cell.id}: {status} {m['chars']}字 {m['output_tokens']}tok 切落{m['trimmed_chars']}", flush=True)
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


def cmd_blind(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir)
    n = make_blind(run_dir, load_scenes(), sample=args.sample)
    print(f"独立採点シート {n} 件: {run_dir / 'blind' / 'review_blind.md'}（採点は blind/scores_independent.csv）")
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir)
    md = compare_md(run_dir, compare_scores(run_dir))
    (run_dir / "blind" / "compare.md").write_text(md, encoding="utf-8")
    print(md)
    return 0


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    parser = argparse.ArgumentParser(description="Phase 0 日本語 Benchmark（既定は dry-run）")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name, func in (("plan", cmd_plan), ("run", cmd_run)):
        sp = sub.add_parser(name)
        sp.add_argument("--scene", action="append", help="Scene ID")
        sp.add_argument("--op", action="append", help="操作（continue / directed_continue / expand）")
        sp.add_argument("--model", action="append", help="モデル ID")
        sp.add_argument("--samples", type=int, default=3, help="各セルの試行回数（既定 3）")
        if name == "run":
            sp.add_argument("--execute", action="store_true", help="実際に NovelAI へ送信する")
            sp.add_argument("--resume", help="中断した run ディレクトリ。成功済みのセルは飛ばす")
        sp.set_defaults(func=func)
    rp = sub.add_parser("report", help="review.md / scores.csv を作り直し、report.md を集計する（通信しない）")
    rp.add_argument("run_dir")
    rp.set_defaults(func=cmd_report)
    bp = sub.add_parser("blind", help="モデル名と一次点を伏せた独立採点用シートを作る（通信しない）")
    bp.add_argument("run_dir")
    bp.add_argument("--sample", type=int, default=1, help="使う試行番号（既定 1）")
    bp.set_defaults(func=cmd_blind)
    cp = sub.add_parser("compare", help="一次点と独立点を照合する（通信しない）")
    cp.add_argument("run_dir")
    cp.set_defaults(func=cmd_compare)
    args = parser.parse_args(argv)
    return args.func(args)
