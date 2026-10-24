"""試し書き・書き比べ（D7）。同じ METRON の契約・Beat から複数の Writer の候補を作り、比較フォルダで測る。

作品フォルダの本文（``_novel_text/``）、``_writing/``、``_metron/`` には書かない。保存先は
``_workingspace/ai_writer/<作品code>_chNN_compare/run-<日時>/`` だけである。

- ``plan_run``: 比較 run を作り、Writer 共通の文脈と送信予定（``plan.json``）を書く。送信しない。
- ``execute_nai``: 承認済みの ``plan.json`` に従い、NovelAI へ Beat ごとに Directed Continue を送る。
- ``receive_candidate``: 親の LLM（local-writer）が書いたマーカー付き候補を受け取る。
- ``measure_run``: 各候補を METRON で計測し、``summary.json`` と ``review_skeleton.md`` を書く。

Beat の割り方・マーカー・Writer への送り方は親の LLM が決める（D3）。NovelAI は本文だけを書く。
"""

from __future__ import annotations

import datetime as dt
import json
import re
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from metron.analyze import analyze_marked_text
from metron.contract import load_beat_plan, load_scene_contract
from metron.models import Beat, BeatPlan, GeneratorInfo, SceneContract, instruction_target_chars
from novel_char_count import count_chars

from .prompt_renderer import BeatContract, DirectedContinueInput
from .writer import CoreWriter

LOCAL = "local"
NAI = "nai"
WRITERS = (LOCAL, NAI)
DEFAULT_NAI_MODEL = "glm-4-6"
SCENE_ID_RE = re.compile(r"^ch(\d{2,})-\d{3,}$")
COMMON_MUST_NOT = ("次の Beat の出来事を先に書くこと", "正本の文章を写すこと")


class CompareError(RuntimeError):
    """比較 run の入力や状態が不正なとき。"""


@dataclass(frozen=True)
class ChapterDesign:
    number: int
    title: str
    objective: str
    items: tuple[str, ...]


@dataclass(frozen=True)
class CompareInputs:
    work_dir: Path
    scene_id: str
    chapter: int
    contract: SceneContract
    plan: BeatPlan
    design: ChapterDesign | None
    facts: dict[str, Any] = field(default_factory=dict)


def work_code(work_dir: Path) -> str:
    code = work_dir.name.split("_", 1)[0]
    if not code.isdigit():
        raise CompareError(f"作品フォルダ名が <code>_<title> ではない: {work_dir.name}")
    return code


def chapter_of(scene_id: str) -> int:
    match = SCENE_ID_RE.match(scene_id)
    if not match:
        raise CompareError(f"scene_id は chNN-MMM 形式: {scene_id}")
    return int(match.group(1))


def compare_root(repo_root: Path, work_dir: Path, chapter: int) -> Path:
    return repo_root / "_workingspace" / "ai_writer" / f"{work_code(work_dir)}_ch{chapter:02d}_compare"


def candidate_dir_name(writer: str, nai_model: str) -> str:
    return "local-writer" if writer == LOCAL else f"nai-{nai_model}"


_HEADING_RE = re.compile(r"^###\s+第(\d+)章(.*)$")
_ITEM_RE = re.compile(r"^(\d+)\.\s+(.*)$")


def parse_chapter_design(design_text: str, chapter: int) -> ChapterDesign | None:
    """設計書の「### 第N章」節から章題・目的・番号付き出来事（行頭のものだけ）を取り出す。"""
    lines = design_text.splitlines()
    start = None
    title = ""
    for i, line in enumerate(lines):
        m = _HEADING_RE.match(line.strip())
        if m and int(m.group(1)) == chapter:
            start, title = i, m.group(2).strip()
            break
    if start is None:
        return None
    objective = ""
    items: list[str] = []
    for line in lines[start + 1:]:
        if line.startswith("### ") or line.startswith("## ") or line.strip() == "---":
            break
        if line.startswith("**目的**"):
            objective = line.split(":", 1)[-1].split("：", 1)[-1].strip()
        m = _ITEM_RE.match(line)
        if m:
            items.append(m.group(2).strip())
    return ChapterDesign(chapter, title, objective, tuple(items))


def load_inputs(work_dir: Path, scene_id: str, *, facts_path: Path | None = None) -> CompareInputs:
    from work_paths import WorkPathError, resolve_unit

    # METRON の場面は古い _metron/ か新しい _work/metron/ のどちらか一方（tools/work_paths.py の組の規則）。
    try:
        metron_dir = resolve_unit(work_dir, "metron", scene_id).base
    except WorkPathError as error:
        raise CompareError(f"METRON の場面の置き場を決められない: {error}") from error
    contract_path, beats_path = metron_dir / "contract.yaml", metron_dir / "beats.yaml"
    for path in (contract_path, beats_path):
        if not path.is_file():
            raise CompareError(f"METRON の入力が無い（先に親の LLM が起こす）: {path}")
    contract = load_scene_contract(contract_path)
    if contract.scene.id != scene_id:
        raise CompareError(f"contract の scene.id が一致しない: {contract.scene.id} != {scene_id}")
    chapter = chapter_of(scene_id)
    design_path = work_dir / "design_specification.md"
    design = parse_chapter_design(design_path.read_text(encoding="utf-8"), chapter) if design_path.is_file() else None
    facts: dict[str, Any] = {}
    if facts_path is not None:
        loaded = yaml.safe_load(facts_path.read_text(encoding="utf-8")) or {}
        if not isinstance(loaded, dict):
            raise CompareError(f"facts は YAML の辞書: {facts_path}")
        facts = loaded
    return CompareInputs(work_dir, scene_id, chapter, contract, load_beat_plan(beats_path), design, facts)


def chapter_heading(inputs: CompareInputs) -> str:
    title = inputs.design.title if inputs.design else ""
    return f"# 第{inputs.chapter}章{title}".rstrip()


def canon_facts(inputs: CompareInputs) -> tuple[str, ...]:
    facts = [str(item) for item in inputs.facts.get("canon_facts") or ()]
    if not facts:
        facts.append(f"視点人物は{inputs.contract.scene.pov}")
        if inputs.design and inputs.design.objective:
            facts.append(f"この章の目的: {inputs.design.objective}")
    return tuple(facts)


def _beat_override(inputs: CompareInputs, beat_id: str) -> dict[str, Any]:
    beats = inputs.facts.get("beats") or {}
    value = beats.get(beat_id) if isinstance(beats, dict) else None
    return value if isinstance(value, dict) else {}


def beat_contracts(inputs: CompareInputs) -> list[tuple[Beat, BeatContract]]:
    """契約・Beat から NovelAI の Beat 別依頼を組む。must_include と end_condition は facts で上書きできる。"""
    beats = inputs.plan.beats
    must_not = tuple(inputs.contract.scene.forbidden) + COMMON_MUST_NOT
    end_state = inputs.contract.scene.end_state
    rows: list[tuple[Beat, BeatContract]] = []
    for i, beat in enumerate(beats):
        override = _beat_override(inputs, beat.id)
        if "end_condition" in override:
            end = str(override["end_condition"])
        elif i + 1 < len(beats):
            end = f"この Beat の出来事を書き終えたところで止める。次の出来事（{beats[i + 1].intent}）には入らない"
        else:
            tail = end_state.action if end_state and end_state.action else beat.intent
            end = f"場面の終わり（{tail}）で止める"
        include = tuple(str(x) for x in override.get("must_include") or ())
        rows.append((beat, BeatContract(beat.intent, end, beat.budget.chars_hint, include, must_not)))
    return rows


def render_context(inputs: CompareInputs) -> str:
    """Writer 共通の文脈。local-writer はこれを見てマーカー付き候補を1回で書く。"""
    scene = inputs.contract.scene
    floor = inputs.plan.generation.chars_floor
    lines = [f"# 書き比べの文脈 — {inputs.work_dir.name} {inputs.scene_id}", ""]
    lines += ["この文脈は比較用。作品の本文（_novel_text）へは書かない。", ""]
    lines += ["## 場面", "", f"- 視点: {scene.pov}（{scene.narrative_distance.value}）"]
    for label, state in (("始まり", scene.start_state), ("終わり", scene.end_state)):
        if state:
            parts = [p for p in (state.location, state.action, state.emotion) if p]
            lines.append(f"- {label}: {' / '.join(parts)}")
    lines.append(f"- 分量: 床 {floor}字、指示目標 {instruction_target_chars(floor)}字（助言）")
    if scene.forbidden:
        lines += ["", "## 書かないこと", ""] + [f"- {item}" for item in scene.forbidden]
    if inputs.design:
        lines += ["", f"## 設計書 第{inputs.chapter}章{inputs.design.title}", ""]
        if inputs.design.objective:
            lines += [f"目的: {inputs.design.objective}", ""]
        lines += [f"{n}. {item}" for n, item in enumerate(inputs.design.items, start=1)]
    facts = canon_facts(inputs)
    if facts:
        lines += ["", "## 設定の要点", ""] + [f"- {item}" for item in facts]
    lines += ["", "## Beat", "", "| id | type | intent | chars_hint | paragraphs | dialogue_turns |",
              "| --- | --- | --- | ---: | --- | --- |"]
    for beat in inputs.plan.beats:
        b = beat.budget
        lines.append(f"| `{beat.id}` | {beat.type} | {beat.intent} | {b.chars_hint} | "
                     f"{_range(b.paragraphs)} | {_range(b.dialogue_turns)} |")
    lines += ["", "## マーカー", "", "各 Beat の本文を次の形で囲む。順番は上の表のとおり。", "",
              "```text", chapter_heading(inputs), "", "<!--beat:<id>-->", "本文", "<!--/beat:<id>-->", "```", ""]
    return "\n".join(lines)


def _range(bounds: tuple[int, int | None]) -> str:
    low, high = bounds
    return f"{low}〜{high}" if high is not None else f"{low}〜"


def _now_id(now: dt.datetime | None) -> str:
    return (now or dt.datetime.now()).strftime("%Y%m%d_%H%M%S")


def plan_run(repo_root: Path, inputs: CompareInputs, writers: tuple[str, ...], *, nai_model: str = DEFAULT_NAI_MODEL,
             writer: CoreWriter | None = None, token_status: str = "unknown",
             now: dt.datetime | None = None) -> Path:
    """比較 run を作る。送信はしない。課金のある送信の一覧は plan.json の ``paid_calls`` に出す。"""
    unknown = [w for w in writers if w not in WRITERS]
    if unknown or not writers:
        raise CompareError(f"writers は {WRITERS} から選ぶ: {writers}")
    run_dir = compare_root(repo_root, inputs.work_dir, inputs.chapter) / f"run-{_now_id(now)}"
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "context.md").write_text(render_context(inputs), encoding="utf-8", newline="\n")
    entries: list[dict[str, Any]] = []
    paid_calls = 0
    for name in writers:
        entry: dict[str, Any] = {"writer": name, "candidate_dir": f"candidates/{candidate_dir_name(name, nai_model)}"}
        if name == NAI:
            if writer is None:
                raise CompareError("NovelAI の plan には CoreWriter（dry-run の provider）が要る")
            beats = []
            for beat, contract in beat_contracts(inputs):
                data = DirectedContinueInput(chapter_heading(inputs) + "\n", contract, canon_facts(inputs))
                body = writer.plan("directed_continue", data, model=nai_model)["request"].get("body") or {}
                beats.append({"beat": beat.id, "target_chars": contract.target_chars,
                              "end_condition": contract.end_condition, "must_include": list(contract.must_include),
                              "max_tokens": body.get("max_tokens")})
            entry.update({"model": nai_model, "operation": "directed_continue", "calls": len(beats),
                          "paid": True, "beats": beats})
            paid_calls += len(beats)
        else:
            entry.update({"model": "local-writer", "calls": 0, "paid": False,
                          "note": "親の LLM が context.md を見てマーカー付き候補を1回で書き、receive で渡す"})
        entries.append(entry)
    plan = {"schema": 1, "run_id": run_dir.name.removeprefix("run-"), "work": inputs.work_dir.name,
            "scene_id": inputs.scene_id, "chapter": inputs.chapter, "writers": entries, "paid_calls": paid_calls,
            "token_status": token_status, "canonical_text": "not written", "executed": {}}
    _write_json(run_dir / "plan.json", plan)
    if inputs.facts:
        (run_dir / "facts.yaml").write_text(yaml.safe_dump(inputs.facts, allow_unicode=True, sort_keys=False),
                                            encoding="utf-8", newline="\n")
    return run_dir


def load_plan(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "plan.json"
    if not path.is_file():
        raise CompareError(f"plan.json が無い（先に plan を実行する）: {run_dir}")
    return json.loads(path.read_text(encoding="utf-8"))


def _plan_entry(plan: dict[str, Any], name: str) -> dict[str, Any]:
    for entry in plan["writers"]:
        if entry["writer"] == name:
            return entry
    raise CompareError(f"plan に無い Writer は使えない: {name}")


def _join(acc: str, piece: str) -> str:
    acc, piece = acc.rstrip(), piece.strip()
    return acc + "\n\n" + piece + "\n" if acc else piece + "\n"


def execute_nai(run_dir: Path, inputs: CompareInputs, writer: CoreWriter, *,
                on_beat: Callable[[dict[str, Any]], None] | None = None,
                save_candidate: Callable[[Any, str], str | None] | None = None) -> dict[str, Any]:
    """承認済みの plan.json どおりに NovelAI へ送る。回数・Beat が plan と食い違えば送らない。"""
    plan = load_plan(run_dir)
    entry = _plan_entry(plan, NAI)
    if NAI in plan.get("executed", {}):
        raise CompareError("この run の NovelAI は送信済み。やり直すときは新しい plan を作る")
    contracts = beat_contracts(inputs)
    if [b.id for b, _ in contracts] != [row["beat"] for row in entry["beats"]]:
        raise CompareError("beats.yaml が plan のあとで変わった。新しい plan を作って承認を取り直す")
    out_dir = run_dir / entry["candidate_dir"]
    (out_dir / "beats").mkdir(parents=True, exist_ok=False)
    heading = chapter_heading(inputs)
    prefix = heading + "\n"
    marked = heading + "\n"
    rows: list[dict[str, Any]] = []
    stopped = None
    for i, (beat, contract) in enumerate(contracts, start=1):
        data = DirectedContinueInput(prefix, contract, canon_facts(inputs))
        out = writer.run("directed_continue", data, model=entry["model"])
        g = out.generation
        (out_dir / "beats" / f"{i:02d}_{beat.id}.md").write_text(out.text, encoding="utf-8", newline="\n")
        row = {"index": i, "beat": beat.id, "status": g.status, "chars": count_chars(out.text, strip_fm=False),
               "output_tokens": g.output_tokens, "finish_reason": g.finish_reason, "http_status": g.http_status,
               "guard": out.guard.status if out.guard else None, "error": g.error,
               "candidate_id": save_candidate(out, beat.id) if save_candidate else None}
        rows.append(row)
        if on_beat:
            on_beat(row)
        if out.text.strip():  # 途中で切れた Beat も本文があれば残し、計測で短さが見えるようにする
            marked = _join(marked, f"<!--beat:{beat.id}-->\n{out.text.strip()}\n<!--/beat:{beat.id}-->")
        if g.status != "complete" or not out.text.strip():
            stopped = beat.id
            break
        prefix = _join(prefix, out.text)
    (out_dir / "marked.md").write_text(marked, encoding="utf-8", newline="\n")
    result = {"writer": NAI, "model": entry["model"], "calls_sent": len(rows), "calls_planned": entry["calls"],
              "stopped_at": stopped, "beats": rows}
    _write_json(out_dir / "send.json", result)
    plan.setdefault("executed", {})[NAI] = {"calls_sent": len(rows), "stopped_at": stopped}
    _write_json(run_dir / "plan.json", plan)
    return result


def receive_candidate(run_dir: Path, name: str, candidate: Path) -> Path:
    """親の LLM が書いたマーカー付き候補を比較 run へ写す。plan に無い Writer は受けない。"""
    plan = load_plan(run_dir)
    entry = _plan_entry(plan, name)
    if entry.get("paid"):
        raise CompareError(f"{name} は送信で候補を作る Writer なので receive では受けない")
    out_dir = run_dir / entry["candidate_dir"]
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / "marked.md"
    if dest.exists():
        raise CompareError(f"候補は受領済み: {dest}")
    shutil.copyfile(candidate, dest)
    return dest


def measure_run(run_dir: Path, inputs: CompareInputs) -> dict[str, Any]:
    """候補ごとに METRON で計測し、summary.json と review_skeleton.md を書く。正本・_metron には書かない。"""
    plan = load_plan(run_dir)
    floor = inputs.plan.generation.chars_floor
    rows: list[dict[str, Any]] = []
    for entry in plan["writers"]:
        cand_dir = run_dir / entry["candidate_dir"]
        marked = cand_dir / "marked.md"
        row: dict[str, Any] = {"writer": entry["writer"], "model": entry["model"],
                               "candidate": marked.relative_to(run_dir).as_posix()}
        if not marked.is_file():
            row["status"] = "missing"
            rows.append(row)
            continue
        text = marked.read_text(encoding="utf-8")
        try:
            result = analyze_marked_text(text, inputs.plan, run=1,
                                         generator=GeneratorInfo(model=entry["model"], granularity="auto"))
        except Exception as exc:  # マーカー不正など。比較は続ける
            row.update({"status": "unmeasured", "error": f"{type(exc).__name__}: {exc}"})
            rows.append(row)
            continue
        metrics_dir = run_dir / "metrics" / Path(entry["candidate_dir"]).name
        metrics_dir.mkdir(parents=True, exist_ok=True)
        (metrics_dir / "draft.md").write_text(result.clean_text, encoding="utf-8", newline="\n")
        _write_yaml(metrics_dir / "metrics.yaml", result.metrics.model_dump(mode="json"))
        _write_yaml(metrics_dir / "spans.yaml", result.spans.model_dump(mode="json"))
        scene = result.metrics.metrics.scene
        spans = result.spans
        marker_errors = list(spans.missing_markers) + list(spans.parse_errors)
        row.update({"status": "marker_errors" if marker_errors else "measured", "marker_errors": marker_errors,
                    "scene_chars": scene.chars, "chars_floor": floor,
                    "floor_met": scene.chars >= floor, "coverage": scene.coverage,
                    "plain_chars": count_chars(result.clean_text, strip_fm=False),
                    "repeated": repeated_sentences(result.clean_text),
                    "beats": {b.id: b.chars for b in result.metrics.metrics.beats}})
        rows.append(row)
    summary = {"schema": 1, "run_id": plan["run_id"], "work": plan["work"], "scene_id": plan["scene_id"],
               "canonical_text": "not written", "writers": rows}
    _write_json(run_dir / "summary.json", summary)
    (run_dir / "review_skeleton.md").write_text(render_review_skeleton(inputs, summary), encoding="utf-8",
                                                newline="\n")
    return summary


_SENTENCE_RE = re.compile(r"[^。！？]*[。！？]」?")
REPEAT_MIN_CHARS = 20


def repeated_sentences(text: str, *, min_chars: int = REPEAT_MIN_CHARS) -> dict[str, int]:
    """同じ文（min_chars 字以上）が2回以上出る箇所を数える。Beat をまたぐ写し返しで字数が水増しされていないかを見る。"""
    counts: dict[str, int] = {}
    for match in _SENTENCE_RE.finditer(text):
        sentence = match.group(0).strip()
        if len(sentence) >= min_chars:
            counts[sentence] = counts.get(sentence, 0) + 1
    repeated = {k: v for k, v in counts.items() if v > 1}
    return {"sentences": len(repeated), "extra_chars": sum(len(k) * (v - 1) for k, v in repeated.items())}


def render_review_skeleton(inputs: CompareInputs, summary: dict[str, Any]) -> str:
    """review.md の下書き。数値の表だけ埋め、文章の節は親の LLM が書く。"""
    measured = [r for r in summary["writers"] if "scene_chars" in r]
    lines = [f"# 読み比べ — {inputs.work_dir.name} 第{inputs.chapter}章", "",
             f"- 対象: `{inputs.scene_id}`（比較用。正本は書かない）"]
    for r in summary["writers"]:
        chars = f"{r['scene_chars']:,}字" if "scene_chars" in r else r.get("status")
        if r.get("repeated", {}).get("sentences"):
            chars += f"（同じ文の繰り返し {r['repeated']['sentences']} 文・延べ {r['repeated']['extra_chars']:,}字）"
        if r.get("marker_errors"):
            chars += f"（マーカーの誤り: {', '.join(r['marker_errors'])}）"
        lines.append(f"- {r['writer']}（{r['model']}）: `{r['candidate']}` {chars}")
    lines += ["", "## 総評", "", "（親の LLM が書く）", "", "## 分量", ""]
    if measured:
        header = "| Beat | chars_hint | " + " | ".join(r["writer"] for r in measured) + " |"
        lines += [header, "| --- | ---: | " + " | ".join("---:" for _ in measured) + " |"]
        for beat in inputs.plan.beats:
            cells = " | ".join(f"{r['beats'].get(beat.id, 0):,}" for r in measured)
            lines.append(f"| {beat.id} | {beat.budget.chars_hint:,} | {cells} |")
        total = " | ".join(f"{r['scene_chars']:,}" for r in measured)
        lines.append(f"| 計（床 {inputs.plan.generation.chars_floor:,}） | | {total} |")
    lines += ["", "## 項ごとの突き合わせ", ""]
    if inputs.design and inputs.design.items:
        lines += [f"{n}. {item[:40]}… — （親の LLM が書く）" for n, item in enumerate(inputs.design.items, start=1)]
    else:
        lines.append("（設計書の章出来事が見つからない）")
    lines += ["", "## 設定とのずれ", "", "（親の LLM が書く）", "", "## 文体", "", "（親の LLM が書く）",
              "", "## 採否", "", "（親の LLM が書く。正本にするなら本経路の起草 run A → 保存用 run B → publish）", ""]
    return "\n".join(lines)


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def _write_yaml(path: Path, data: dict[str, Any]) -> None:
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8", newline="\n")


# --- CLI -------------------------------------------------------------------

def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _token_status(repo_root: Path) -> str:
    from . import novelai as nai

    try:
        nai.load_token(repo_root)
        return f"{nai.TOKEN_ENV}: set"
    except Exception as exc:  # 値は出さない
        return f"{nai.TOKEN_ENV}: missing ({type(exc).__name__})"


def _inputs_from_run(repo_root: Path, run_dir: Path) -> CompareInputs:
    plan = load_plan(run_dir)
    facts = run_dir / "facts.yaml"
    return load_inputs(repo_root / "novels" / plan["work"], plan["scene_id"],
                       facts_path=facts if facts.is_file() else None)


def _rel(path: Path, repo_root: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return str(path)


def cmd_plan(args: Any) -> int:
    from .provider import NovelAIProvider
    from . import novelai as nai

    repo = _repo_root()
    work_dir = Path(args.work)
    if not work_dir.is_absolute():
        work_dir = (Path.cwd() / work_dir).resolve()
    writers = tuple(w.strip() for w in args.writers.split(",") if w.strip())
    inputs = load_inputs(work_dir, args.scene_id, facts_path=Path(args.facts) if args.facts else None)
    writer = CoreWriter(NovelAIProvider("dry-run", headers=nai.load_request_headers(repo))) if NAI in writers else None
    run_dir = plan_run(repo, inputs, writers, nai_model=args.nai_model, writer=writer,
                       token_status=_token_status(repo))
    plan = load_plan(run_dir)
    print(f"plan（未送信）: {_rel(run_dir, repo)}")
    print(f"作品 {plan['work']} scene {plan['scene_id']}。正本・_writing・_metron は書かない")
    for entry in plan["writers"]:
        paid = "課金あり" if entry["paid"] else "課金なし"
        print(f"- {entry['writer']}: {entry['model']} 送信 {entry['calls']} 回（{paid}）→ {entry['candidate_dir']}/")
    print(f"課金のある送信: 合計 {plan['paid_calls']} 回。{plan['token_status']}")
    if plan["paid_calls"]:
        print("本番は承認後に: uv run python tools/ai_writer_compare_cli.py run "
              f"{_rel(run_dir, repo)} --writer nai --execute")
    if any(e["writer"] == LOCAL for e in plan["writers"]):
        print(f"local-writer: {_rel(run_dir / 'context.md', repo)} を見てマーカー付き候補を書き、receive で渡す")
    return 0


def cmd_run(args: Any) -> int:
    from .candidates import CandidateStore
    from .entities import KnownEntityDictionary
    from .guard import MinimumGuard
    from .manifest import build_manifest, work_refs
    from .provider import NovelAIProvider

    if args.writer != NAI:
        print("run で送るのは nai だけ。local は receive で渡す")
        return 2
    if not args.execute:
        print("未送信。承認を得たら --execute を付ける")
        return 2
    repo = _repo_root()
    run_dir = Path(args.run_dir).resolve()
    inputs = _inputs_from_run(repo, run_dir)
    known = KnownEntityDictionary.from_work(inputs.work_dir, extra_files=("design_specification.md",))
    writer = CoreWriter(NovelAIProvider.from_repo(repo), guard=MinimumGuard(known))
    store = CandidateStore(run_dir / "store")
    refs = work_refs(inputs.work_dir, repo)
    run_id = run_dir.name.removeprefix("run-")

    def save(out: Any, beat_id: str) -> str:
        manifest = build_manifest(out, refs=refs, scene_id=inputs.scene_id, beat_id=beat_id)
        return store.save(out, manifest, run_id=run_id).candidate_id

    def report(row: dict[str, Any]) -> None:
        print(f"BEAT_DONE {row['index']} {row['beat']} status={row['status']} chars={row['chars']} "
              f"guard={row['guard']}", flush=True)

    result = execute_nai(run_dir, inputs, writer, on_beat=report, save_candidate=save)
    print(f"送信 {result['calls_sent']}/{result['calls_planned']} 回。stopped={result['stopped_at']}。正本は書いていない")
    return 0 if result["stopped_at"] is None else 1


def cmd_receive(args: Any) -> int:
    repo = _repo_root()
    dest = receive_candidate(Path(args.run_dir).resolve(), args.writer, Path(args.candidate))
    print(f"received: {_rel(dest, repo)}")
    return 0


def cmd_measure(args: Any) -> int:
    repo = _repo_root()
    run_dir = Path(args.run_dir).resolve()
    summary = measure_run(run_dir, _inputs_from_run(repo, run_dir))
    for row in summary["writers"]:
        if "scene_chars" in row:
            floor = "床到達" if row["floor_met"] else "床未達"
            note = f" マーカーの誤り: {row['marker_errors']}" if row.get("marker_errors") else ""
            rep = row.get("repeated", {})
            if rep.get("sentences"):
                note += f" 同じ文の繰り返し {rep['sentences']} 文・延べ {rep['extra_chars']}字"
            print(f"- {row['writer']}: {row['scene_chars']}字（{floor}、床 {row['chars_floor']}）{note}")
        else:
            print(f"- {row['writer']}: {row['status']} {row.get('error', '')}".rstrip())
    print(f"summary: {_rel(run_dir / 'summary.json', repo)}")
    print(f"review の下書き: {_rel(run_dir / 'review_skeleton.md', repo)}（review.md は親の LLM が書く）")
    return 0


def main(argv: list[str] | None = None) -> int:
    import argparse
    import sys

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    parser = argparse.ArgumentParser(description="試し書き・書き比べ（正本は書かない）")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan", help="比較 run を作り送信予定を書く（送信しない）")
    p.add_argument("work", help="作品フォルダ（novels/NNN_作品名）")
    p.add_argument("--scene-id", required=True)
    p.add_argument("--writers", default="local,nai", help="local / nai をカンマ区切り")
    p.add_argument("--nai-model", default=DEFAULT_NAI_MODEL)
    p.add_argument("--facts", help="親の LLM が書いた canon_facts / Beat 別の上書き（YAML）")
    p.set_defaults(func=cmd_plan)
    r = sub.add_parser("run", help="承認済みの plan どおり NovelAI へ送る")
    r.add_argument("run_dir")
    r.add_argument("--writer", default=NAI)
    r.add_argument("--execute", action="store_true")
    r.set_defaults(func=cmd_run)
    c = sub.add_parser("receive", help="local-writer の候補を受け取る")
    c.add_argument("run_dir")
    c.add_argument("--writer", default=LOCAL)
    c.add_argument("--candidate", required=True)
    c.set_defaults(func=cmd_receive)
    m = sub.add_parser("measure", help="候補を METRON で計測し summary と review の下書きを書く")
    m.add_argument("run_dir")
    m.set_defaults(func=cmd_measure)
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except CompareError as exc:
        print(f"error: {exc}")
        return 2
