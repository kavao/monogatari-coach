"""Core Writer の確認（Phase 1）。既定は dry-run で、操作ごとの経路と送る内容を表示する。

入力は Phase 0 日本語 Benchmark の Scene（``fixtures/benchmark/scenes.yaml``）を使う。
``--execute`` を付けたときだけ送信する。生成は Minimum Guard（Scene の人物と既知の事実から作る辞書）を通し、
Generation Manifest（参照: scenes.yaml と Scene の本文）を付けて Candidate Store
（``_workingspace/ai_writer/candidates/``）に保存する。あわせて ``WriterOutput.record()`` と候補 ID を
``_workingspace/ai_writer/phase1/<実行日時>/writer_<操作>.json`` に残す（トークンは含まない）。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime

from . import novelai as nai
from .bench import GAP, SCENES_PATH, Scene, load_scenes
from .candidates import CandidateStore
from .entities import KnownEntityDictionary
from .guard import GUARD_VERSION, MinimumGuard
from .manifest import SourceRef, build_manifest
from .prompt_renderer import BeatContract, ContinueInput, DirectedContinueInput, ExpandInsertionInput, OperationInput
from .provider import NovelAIProvider
from .router import ENDPOINT_FOR
from .spike import REPO_ROOT
from .writer import CoreWriter

OUT_ROOT = REPO_ROOT / "_workingspace" / "ai_writer" / "phase1"
STORE_ROOT = REPO_ROOT / "_workingspace" / "ai_writer" / "candidates"


def scene_input(scene: Scene, operation: str) -> OperationInput:
    if operation == "continue":
        return ContinueInput(scene.text)
    if operation == "directed_continue":
        c = scene.contract
        return DirectedContinueInput(scene.text, BeatContract(c.objective, c.end_condition, c.target_chars,
                                                              tuple(c.must_include), tuple(c.must_not)),
                                     tuple(scene.canon_facts))
    before, after = scene.passage.split(GAP, 1)
    return ExpandInsertionInput(before, after)


def known_from_scene(scene: Scene) -> KnownEntityDictionary:
    """Scene の人物名と既知の事実から、Minimum Guard の既知エンティティ辞書を作る。"""
    d = KnownEntityDictionary()
    for name in scene.characters:
        d.add(name, "character")
    d.add_corpus("\n".join(scene.canon_facts))
    return d


def scene_refs(scene: Scene) -> list[SourceRef]:
    return [SourceRef.from_file("scene", SCENES_PATH, REPO_ROOT),
            SourceRef.from_text("source_text", scene.id, scene.passage)]


def _provider() -> NovelAIProvider:
    return NovelAIProvider.from_repo(REPO_ROOT)


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    scenes = {s.id: s for s in load_scenes()}
    parser = argparse.ArgumentParser(description="Core Writer の確認（既定は dry-run）")
    parser.add_argument("--scene", default="daily", choices=sorted(scenes))
    parser.add_argument("--op", action="append", choices=sorted(ENDPOINT_FOR), help="既定は 3 操作すべて")
    parser.add_argument("--model", choices=nai.CHAT_MODELS, help="明示しなければ Router の既定（Capability Profile）")
    parser.add_argument("--execute", action="store_true", help="実際に NovelAI へ送信する")
    args = parser.parse_args(argv)
    ops = args.op or ["continue", "directed_continue", "expand_insertion"]
    scene = scenes[args.scene]
    store_label = STORE_ROOT.relative_to(REPO_ROOT).as_posix() if STORE_ROOT.is_relative_to(REPO_ROOT) else str(STORE_ROOT)

    if not args.execute:
        w = CoreWriter(NovelAIProvider("dry-run", headers=nai.load_request_headers(REPO_ROOT)))
        print(f"確認 {len(ops)} 件（生成 {len(ops)} 回、直列）。Scene: {scene.id}（{scene.genre}）。"
              f"本番では Guard {GUARD_VERSION} を通し、候補として {store_label}/ に保存する")
        for op in ops:
            plan = w.plan(op, scene_input(scene, op), model=args.model)
            print(f"\n## {op}: model={plan['model']}（{plan['route_reason']}）sampling={plan['sampling']} "
                  f"renderer={plan['renderer_version']} postprocess={plan['postprocess_version']}")
            print(json.dumps(plan["request"], ensure_ascii=False, indent=2))
        print("\n本番実行には --execute を付けてください。")
        return 0

    w = CoreWriter(_provider(), guard=MinimumGuard(known_from_scene(scene)))
    store = CandidateStore(STORE_ROOT)
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = OUT_ROOT / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    refs = scene_refs(scene)
    for op in ops:
        out = w.run(op, scene_input(scene, op), model=args.model)
        cand = store.save(out, build_manifest(out, refs=refs, scene_id=scene.id), run_id=run_id)
        g = out.generation
        guard = out.guard.status if out.guard else "-"
        print(f"{op}: model={out.route.model} status={g.status} 生出力 {len(g.text)}字 → 整形後 {len(out.text)}字"
              f"（切落 {out.cleaned.removed_chars}字）{g.output_tokens}tok finish={g.finish_reason} "
              f"guard={guard} 候補={cand.candidate_id}")
        for f in (out.guard.findings if out.guard else []):
            print(f"  Guard {f.severity}: {f.check}「{f.text[:30]}」{f.detail}")
        print(f"  本文: {out.text[:80]}")
        record = {"candidate_id": cand.candidate_id, **out.record()}
        (out_dir / f"writer_{op}.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n保存先: {out_dir}\n候補: {STORE_ROOT}")
    return 0
