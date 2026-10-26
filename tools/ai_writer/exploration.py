"""探索機能 E1「別の展開を見る」（計画 ``_workingspace/plans/20261009_ai_writer_creative_exploration.md`` §3・§6）。

同じ出発点（本文の末尾）から、明示したモデルで独立した続きの候補を直列に生成し、比較・手動レビュー用に保存する。

- モデルは明示が必須。失敗しても別のモデルへ黙って切り替えない（§2）。通常操作の既定（preferred_operations）は変えない。
- 候補数は既定 3、最大 5。1 候補 1 要求で、前の候補を次の要求に混ぜない（§3.1）。
- 停止すると、生成中のストリームを閉じて部分出力を ``incomplete`` で保存し、未開始の候補は送らない（§6.2）。
- 再開では成功済みの枠を飛ばす。途中で止まった・失敗した枠は ``retry_incomplete`` を明示したときだけ、
  新しい候補 ID（親 ID を記録）で生成し直す。旧候補は上書きしない。
- 保存先は ``_workingspace/ai_writer/creative/<run_id>/``。作品の本文・人物・世界設定へは書かない（§5）。
- 生成の状態（complete / incomplete / error）とレビューの状態（unreviewed / selected / rejected / adopted）は別の欄。
  意味の検査は未実装なので、各候補の Guard 記録の ``not_run`` に残る（人が確認する）。
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from metron.storage import atomic_write_text
from novel_char_count import count_chars

from . import novelai as nai
from .bench import SCENES_PATH, Scene, load_scenes
from .candidates import Candidate, CandidateStore, input_from_dict, input_to_dict
from .entities import KnownEntityDictionary
from .exploration_prompts import EXPLORE_OPERATION, EXPLORE_RENDERER_VERSION, render_explore
from .guard import GUARD_VERSION, MinimumGuard
from .manifest import SourceRef, build_manifest, work_refs
from .postprocess import POSTPROCESS_VERSION, clean_for
from .prompt_renderer import ExploreBranchInput
from .provider import GenerationResult, NovelAIProvider
from .router import NOVELAI_SAMPLING, Route, SamplingName
from .spike import REPO_ROOT, _abbreviate
from .transport import TransportError
from .writer import WriterOutput, WriterSession
from .writer_cli import known_from_scene

OUT_ROOT = REPO_ROOT / "_workingspace" / "ai_writer" / "creative"
DEFAULT_CANDIDATES = 3
MAX_CANDIDATES = 5
RUN_MANIFEST = "manifest.json"
EVAL_COLUMNS = ("naturalness", "appeal", "character", "lore", "useful_surprise", "adopt", "adopt_range", "conflicts",
                "edit_minutes", "note")
GROUP_COLUMNS = ("diversity", "adoptable_any", "review_minutes", "note")


class ExplorationError(ValueError):
    pass


def resolve_route(provider: NovelAIProvider, model: str, sampling: SamplingName) -> Route:
    """明示したモデルの経路。使えなければ理由を返し、別のモデルへは切り替えない。"""
    if model not in provider.profiles:
        raise ExplorationError(f"未知のモデル {model}。別のモデルへは切り替えない")
    profile = provider.profiles[model]
    if "chat" not in profile.endpoints:
        raise ExplorationError(f"{model} は chat エンドポイントを持たない。別のモデルへは切り替えない")
    if sampling not in NOVELAI_SAMPLING:
        raise ExplorationError(f"未知の Sampling Profile {sampling}")
    return Route(EXPLORE_OPERATION, model, "chat", NOVELAI_SAMPLING[sampling], "explicit", profile.revision)


@dataclass
class Slot:
    index: int
    attempts: list[str]


class ExplorationRun:
    """1 回の探索（同じ出発点からの候補群）。``manifest.json`` に設定と枠ごとの試行を記録する。"""

    def __init__(self, provider: NovelAIProvider, run_dir: Path, manifest: dict[str, Any],
                 guard: MinimumGuard | None = None) -> None:
        self.provider = provider
        self.run_dir = Path(run_dir)
        self.manifest = manifest
        self.guard = guard if guard is not None else MinimumGuard()
        self.store = CandidateStore(self.run_dir)
        self._stop = threading.Event()
        self._session: WriterSession | None = None
        self._lock = threading.Lock()

    # 作成と読み込み ------------------------------------------------------------
    @classmethod
    def create(cls, provider: NovelAIProvider, out_root: Path, data: ExploreBranchInput, *, model: str,
               candidates: int = DEFAULT_CANDIDATES, sampling: SamplingName = "stable", source: dict[str, Any] | None = None,
               refs: list[SourceRef] | None = None, guard: MinimumGuard | None = None,
               run_id: str | None = None) -> ExplorationRun:
        if not 1 <= candidates <= MAX_CANDIDATES:
            raise ExplorationError(f"候補数は 1〜{MAX_CANDIDATES}（{candidates} が来た）")
        resolve_route(provider, model, sampling)  # 作る前に使えるか確かめる
        run_id = run_id or datetime.now().strftime("%Y%m%d_%H%M%S")
        run_dir = Path(out_root) / run_id
        run_dir.mkdir(parents=True, exist_ok=False)  # 既存の run を上書きしない
        manifest = {
            "run_id": run_id, "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "purpose": EXPLORE_OPERATION, "model": model, "sampling": sampling, "candidates": candidates,
            "renderer_version": EXPLORE_RENDERER_VERSION, "postprocess_version": POSTPROCESS_VERSION,
            "guard_version": GUARD_VERSION, "status": "planned", "source": source or {},
            "refs": [asdict(r) for r in (refs or [])], "input": input_to_dict(data),
            "slots": [{"index": i, "attempts": []} for i in range(1, candidates + 1)],
        }
        run = cls(provider, run_dir, manifest, guard)
        run._save_manifest()
        (run_dir / "selections.json").write_text(json.dumps({"selections": []}, ensure_ascii=False, indent=2),
                                                 encoding="utf-8")
        return run

    @classmethod
    def open(cls, provider: NovelAIProvider, run_dir: Path, guard: MinimumGuard | None = None) -> ExplorationRun:
        path = Path(run_dir) / RUN_MANIFEST
        if not path.is_file():
            raise ExplorationError(f"探索の記録がない: {path}")
        return cls(provider, Path(run_dir), json.loads(path.read_text(encoding="utf-8")), guard)

    # 参照 -------------------------------------------------------------------
    @property
    def data(self) -> ExploreBranchInput:
        data = input_from_dict(self.manifest["input"])
        assert isinstance(data, ExploreBranchInput)
        return data

    @property
    def refs(self) -> list[SourceRef]:
        return [SourceRef(**r) for r in self.manifest.get("refs", [])]

    def slots(self) -> list[Slot]:
        return [Slot(s["index"], list(s["attempts"])) for s in self.manifest["slots"]]

    def latest(self, slot: Slot) -> Candidate | None:
        return self.store.load(slot.attempts[-1]) if slot.attempts else None

    def pending(self, *, retry_incomplete: bool = False) -> list[tuple[Slot, Candidate | None]]:
        """これから生成する枠と、作り直すときの親候補。"""
        out = []
        for slot in self.slots():
            last = self.latest(slot)
            if last is None:
                out.append((slot, None))
            elif last.generation_status != "complete" and retry_incomplete:
                out.append((slot, last))
        return out

    def preview(self) -> dict[str, Any]:
        route = resolve_route(self.provider, self.manifest["model"], self.manifest["sampling"])
        rendered = render_explore(self.data, route.model, sampling=route.sampling.values)
        return {"route": route, "rendered": rendered, "request": self.provider.preview(rendered.request)}

    # 生成 -------------------------------------------------------------------
    def request_stop(self) -> None:
        """別スレッドから呼べる。生成中の候補を止め（部分出力は incomplete で保存）、次の枠へ進まない。"""
        self._stop.set()
        with self._lock:
            if self._session is not None:
                self._session.cancel()

    def run(self, *, retry_incomplete: bool = False) -> dict[str, Any]:
        route = resolve_route(self.provider, self.manifest["model"], self.manifest["sampling"])
        data = self.data
        rendered = render_explore(data, route.model, sampling=route.sampling.values)
        preview = self.provider.preview(rendered.request)
        estimate = self.provider.count_tokens(rendered.request.input_text(), route.model)
        saved: list[str] = []
        self._set_status("running")
        for slot, parent in self.pending(retry_incomplete=retry_incomplete):
            if self._stop.is_set():
                break
            out, interrupted = self._generate(route, rendered, preview, data, estimate)
            # 止めた候補も含めて、必ず保存してから次へ進む（または抜ける）
            cand = self.store.save(out, build_manifest(out, refs=self.refs, scene_id=self.manifest["source"].get("scene_id")),
                                   parent_id=parent.candidate_id if parent else None, run_id=self.manifest["run_id"])
            self._record_attempt(slot.index, cand.candidate_id)
            saved.append(cand.candidate_id)
            if interrupted:  # Ctrl+C。次の枠へ進まない
                self._stop.set()
                break
        unstarted = len(self.pending())
        remaining = sum(1 for s in self.slots() if (c := self.latest(s)) is None or c.generation_status != "complete")
        self._set_status("done" if not remaining else ("stopped" if self._stop.is_set() else "partial"))
        write_review(self)
        return {"saved": saved, "stopped": self._stop.is_set(), "remaining": remaining, "unstarted": unstarted,
                "incomplete": remaining - unstarted, "status": self.manifest["status"]}

    def _generate(self, route: Route, rendered: Any, preview: dict[str, Any], data: ExploreBranchInput,
                  estimate: Any) -> tuple[WriterOutput, bool]:
        """1 候補を生成する。戻り値の 2 つ目は Ctrl+C で中断されたか。"""
        try:
            generation = self.provider.stream(rendered.request)
        except TransportError as e:
            failed = GenerationResult(generation_id="", model=route.model, status="error", error=e.body[:2000],
                                      http_status=e.status, attempts=e.attempts)
            return WriterOutput(route, rendered, preview, failed, clean_for(EXPLORE_OPERATION, ""), None, data, estimate), False
        session = WriterSession(route, rendered, preview, generation, data, self.guard, estimate)
        with self._lock:
            self._session = session
            if self._stop.is_set():
                session.cancel()
        interrupted = False
        try:
            for _ in session:
                if self._stop.is_set():
                    session.cancel()
                    break
        except KeyboardInterrupt:
            interrupted = True
            session.cancel()
        finally:
            with self._lock:
                self._session = None
        return session.finish(), interrupted

    # 記録 -------------------------------------------------------------------
    def _record_attempt(self, index: int, candidate_id: str) -> None:
        for s in self.manifest["slots"]:
            if s["index"] == index:
                s["attempts"].append(candidate_id)
        self._save_manifest()

    def _set_status(self, status: str) -> None:
        self.manifest["status"] = status
        self._save_manifest()

    def _save_manifest(self) -> None:
        atomic_write_text(self.run_dir / RUN_MANIFEST, json.dumps(self.manifest, ensure_ascii=False, indent=2))


# ---- レビュー用ファイル ---------------------------------------------------------

def _read_rows(path: Path, key: str) -> dict[str, dict[str, str]]:
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8", newline="") as f:
        return {row[key]: row for row in csv.DictReader(f)}


def write_review(run: ExplorationRun) -> None:
    """review.md（読み比べ）、evaluation.csv（候補ごとの評価）、group.csv（候補群の評価）を作る。既存の記入は残す。"""
    m, data = run.manifest, run.data
    lines = [f"# 別の展開の候補 {m['run_id']}", "",
             f"- モデル: {m['model']}（明示）／ sampling: {m['sampling']} ／ 版: {m['renderer_version']}・{m['postprocess_version']}・{m['guard_version']}",
             f"- 状態: {m['status']} ／ 候補数: {m['candidates']} ／ 出典: {m['source'].get('label', '-')}",
             "- 評価は evaluation.csv（候補ごと）と group.csv（候補群）に書く。生成の状態とレビューの状態は別。"
             "意味の検査は未実装なので、設定との矛盾は人が確認する。", "",
             "## 守ること", "", *(f"- {f}" for f in data.fixed or ("（本文のみ）",)), "",
             "## 自由にしてよいこと", "", *(f"- {f}" for f in data.free or ("分岐点から先の行動、会話、選択、結末",)), "",
             "## 本文（分岐の出発点）", "", "```text", data.text, "```", ""]
    rows: list[dict[str, Any]] = []
    for slot in run.slots():
        cand = run.latest(slot)
        if cand is None:
            lines += [f"## 候補 {slot.index}", "", "（未生成）", ""]
            continue
        chars = count_chars(cand.text, strip_fm=False)
        guard = cand.guard or {}
        lines += [f"## 候補 {slot.index}（{cand.candidate_id}、{cand.generation_status}、{chars}字、Guard {guard.get('status', '-')}）", ""]
        if cand.generation_status == "incomplete":
            lines += ["途中で止めた候補。部分結果の採用・続きの生成・破棄を選べる（続きは明示した再試行で新しい ID になる）。", ""]
        if cand.generation_status == "error":
            lines += [f"生成に失敗: {cand.error}", ""]
        for f in guard.get("findings", []):
            lines.append(f"- Guard {f['severity']}: {f['check']}「{f['text'][:30]}」{f['detail']}")
        for r in cand.review_items:
            lines.append(f"- 要確認: {r['detail']}（{r['start']}〜{r['end']} 字目）")
        lines += ["", cand.text or "（本文なし）", ""]
        rows.append({"candidate_id": cand.candidate_id, "slot": slot.index, "model": cand.model,
                     "generation_status": cand.generation_status, "chars": chars, "guard_status": guard.get("status", "")})
    atomic_write_text(run.run_dir / "review.md", "\n".join(lines) + "\n")

    eval_path = run.run_dir / "evaluation.csv"
    existing = _read_rows(eval_path, "candidate_id")
    header = ["candidate_id", "slot", "model", "generation_status", "chars", "guard_status", *EVAL_COLUMNS]
    with eval_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=header)
        w.writeheader()
        for row in rows:
            row.update({k: existing.get(row["candidate_id"], {}).get(k, "") for k in EVAL_COLUMNS})
            w.writerow(row)
    group_path = run.run_dir / "group.csv"
    group = _read_rows(group_path, "run_id").get(m["run_id"], {})
    with group_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["run_id", "model", "candidates", *GROUP_COLUMNS])
        w.writeheader()
        w.writerow({"run_id": m["run_id"], "model": m["model"], "candidates": len(rows),
                    **{k: group.get(k, "") for k in GROUP_COLUMNS}})


# ---- CLI -----------------------------------------------------------------------

def _source_from_args(args: argparse.Namespace) -> tuple[ExploreBranchInput, dict[str, Any], list[SourceRef], KnownEntityDictionary]:
    free = tuple(args.free or ())
    if args.scene:
        scenes = {s.id: s for s in load_scenes()}
        if args.scene not in scenes:
            raise ExplorationError(f"未知の Scene {args.scene}（{', '.join(sorted(scenes))}）")
        scene: Scene = scenes[args.scene]
        data = ExploreBranchInput(scene.text, tuple(scene.canon_facts) + tuple(args.fixed or ()), free,
                                  args.end, args.target_chars)
        refs = [SourceRef.from_file("scene", SCENES_PATH, REPO_ROOT), SourceRef.from_text("source_text", scene.id, scene.passage)]
        return data, {"label": f"benchmark scene {scene.id}", "scene_id": scene.id}, refs, known_from_scene(scene)
    path = Path(args.text_file)
    text = path.read_text(encoding="utf-8")
    data = ExploreBranchInput(text, tuple(args.fixed or ()), free, args.end, args.target_chars)
    try:
        refs = [SourceRef.from_file("source_text", path, REPO_ROOT)]
    except ValueError:  # リポジトリの外のファイル
        refs = [SourceRef.from_text("source_text", path.name, text)]
    known = KnownEntityDictionary()
    if args.work_dir:
        work = Path(args.work_dir)
        known = KnownEntityDictionary.from_work(work)
        refs += work_refs(work, REPO_ROOT)
    return data, {"label": str(path)}, refs, known


def _print_plan(run_like: dict[str, Any], n: int) -> None:
    route, rendered, req = run_like["route"], run_like["rendered"], run_like["request"]
    print(f"モデル {route.model}（明示）sampling {route.sampling.name}（{'実測済み' if route.sampling.verified else '未検証'}）"
          f" 版 {rendered.version}。候補 {n} 件 = 生成 {n} 回（1 候補 1 要求、直列、各要求は同じ内容）")
    print(json.dumps(_abbreviate(req, 1200), ensure_ascii=False, indent=2))


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    parser = argparse.ArgumentParser(description="別の展開を見る（探索機能 E1、既定は dry-run）")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("plan", "run"):
        sp = sub.add_parser(name)
        src = sp.add_mutually_exclusive_group(required=True)
        src.add_argument("--scene", help="Benchmark の Scene ID を出発点にする")
        src.add_argument("--text-file", help="出発点の本文ファイル（UTF-8）")
        sp.add_argument("--work-dir", help="作品フォルダ。character.md / world.md を既知の名前として読む（書き込まない）")
        sp.add_argument("--model", required=True, choices=nai.CHAT_MODELS, help="使うモデル（明示が必須）")
        sp.add_argument("--candidates", type=int, default=DEFAULT_CANDIDATES, help=f"候補数（既定 {DEFAULT_CANDIDATES}、最大 {MAX_CANDIDATES}）")
        sp.add_argument("--fixed", action="append", help="守ること（複数可）")
        sp.add_argument("--free", action="append", help="自由にしてよいこと（複数可）")
        sp.add_argument("--end", help="終わる位置（指定したときだけ必須になる）")
        sp.add_argument("--target-chars", type=int, default=400)
        sp.add_argument("--sampling", default="stable", choices=sorted(NOVELAI_SAMPLING))
        if name == "run":
            sp.add_argument("--execute", action="store_true", help="実際に NovelAI へ送信する")
    rs = sub.add_parser("resume", help="止まった探索を続ける（成功済みの枠は飛ばす）")
    rs.add_argument("run_dir")
    rs.add_argument("--retry-incomplete", action="store_true", help="途中で止まった・失敗した枠も新しい ID で作り直す")
    rs.add_argument("--execute", action="store_true")
    rv = sub.add_parser("review", help="review.md / evaluation.csv / group.csv を作り直す（送信しない）")
    rv.add_argument("run_dir")
    args = parser.parse_args(argv)

    try:
        if args.cmd in ("plan", "run"):
            if not 1 <= args.candidates <= MAX_CANDIDATES:
                raise ExplorationError(f"候補数は 1〜{MAX_CANDIDATES}")
            data, source, refs, known = _source_from_args(args)
            if args.cmd == "plan" or not args.execute:
                dry = NovelAIProvider("dry-run", headers=nai.load_request_headers(REPO_ROOT))
                route = resolve_route(dry, args.model, args.sampling)
                rendered = render_explore(data, route.model, sampling=route.sampling.values)
                _print_plan({"route": route, "rendered": rendered, "request": dry.preview(rendered.request)}, args.candidates)
                print(f"\n保存先（本番）: {OUT_ROOT}/<run_id>/。本番実行には run --execute を付けてください。")
                return 0
            run = ExplorationRun.create(_provider(), OUT_ROOT, data, model=args.model, candidates=args.candidates,
                                        sampling=args.sampling, source=source, refs=refs, guard=MinimumGuard(known))
            return _execute(run, retry_incomplete=False)
        if args.cmd == "resume":
            run = ExplorationRun.open(_dry_or_real(args.execute), Path(args.run_dir))
            todo = run.pending(retry_incomplete=args.retry_incomplete)
            print(f"{run.run_dir}: 生成する枠 {len(todo)} 件（{', '.join(str(s.index) for s, _ in todo) or 'なし'}）")
            if not args.execute:
                if todo:
                    _print_plan(run.preview(), len(todo))
                print("\n本番実行には resume --execute を付けてください。")
                return 0
            return _execute(run, retry_incomplete=args.retry_incomplete)
        run = ExplorationRun.open(_dry_or_real(False), Path(args.run_dir))
        write_review(run)
        print(f"作り直した: {run.run_dir / 'review.md'}")
        return 0
    except ExplorationError as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 2


def _provider() -> NovelAIProvider:
    return NovelAIProvider.from_repo(REPO_ROOT)


def _dry_or_real(execute: bool) -> NovelAIProvider:
    return _provider() if execute else NovelAIProvider("dry-run", headers=nai.load_request_headers(REPO_ROOT))


def _execute(run: ExplorationRun, *, retry_incomplete: bool) -> int:
    print(f"探索 {run.manifest['run_id']}: モデル {run.manifest['model']}、候補 {run.manifest['candidates']} 件。Ctrl+C で止められます")
    summary = run.run(retry_incomplete=retry_incomplete)
    for slot in run.slots():
        cand = run.latest(slot)
        if cand is not None:
            print(f"  候補 {slot.index}: {cand.generation_status} {count_chars(cand.text, strip_fm=False)}字 "
                  f"Guard {(cand.guard or {}).get('status', '-')} {cand.candidate_id}")
    print(f"状態 {summary['status']}（未生成 {summary['unstarted']} 枠、途中で止まった・失敗 {summary['incomplete']} 枠）。"
          f"保存先: {run.run_dir}")
    if summary["unstarted"]:
        print(f"未生成の枠を続けるには: uv run python tools/ai_writer_creative_cli.py resume {run.run_dir} --execute")
    if summary["incomplete"]:
        print(f"途中の枠を新しい ID で作り直すには: uv run python tools/ai_writer_creative_cli.py resume {run.run_dir} "
              "--retry-incomplete --execute")
    return 0
