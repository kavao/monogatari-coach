"""Batch entry point for NovelAI Image2Image restyle.

One invocation owns one ``_restyle/<batch_id>/`` directory.  Each source keeps
its own redacted plan and result manifest inside that directory, so a batch can
be approved and executed without creating one top-level run directory per
image.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

from image_edit.restyle import (  # noqa: E402
    RestyleError,
    _new_run_id,
    _resolve_output_dir,
    _safe_artifact_filename,
    build_restyle_plan,
    execute_restyle,
    load_prompt_candidates,
    load_restyle_plan,
    save_restyle_plan,
)
from image_provider_generate import load_json, load_root_config  # noqa: E402
from image_provider_edit import _load_options, _style_paths  # noqa: E402


def _save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _parse_target_size(raw: str | None) -> tuple[int, int] | None:
    if not raw:
        return None
    try:
        width, height = raw.lower().split("x", 1)
        return int(width), int(height)
    except (ValueError, AttributeError) as exc:
        raise RestyleError("--target-size は WIDTHxHEIGHT 形式で指定してください") from exc


def _prompt_for_source(args: argparse.Namespace, source: Path) -> tuple[str, str, str]:
    candidates: dict[str, str] = {}
    source_json = source.with_suffix(".json")
    if source_json.is_file():
        candidates = load_prompt_candidates(source_json)
    if args.prompt_file:
        prompt = Path(args.prompt_file).read_text(encoding="utf-8")
        prompt_source = "--prompt-file"
    elif args.prompt is not None:
        prompt = args.prompt
        prompt_source = "--prompt"
    else:
        prompt = candidates.get("prompt")
        prompt_source = "same-name-json"
    if not isinstance(prompt, str) or not prompt.strip():
        raise RestyleError(
            f"promptは--prompt、--prompt-file、または同名JSONのpromptで指定してください: {source}"
        )
    negative = args.negative_prompt
    if negative is None:
        negative = candidates.get("negative_prompt", "")
    return prompt.strip(), str(negative or "").strip(), prompt_source


def _batch_plan_path(batch_dir: Path) -> Path:
    return batch_dir / "batch_plan.json"


def _validate_batch_plan(path: Path) -> tuple[dict[str, Any], Path]:
    batch_path = path.expanduser().resolve()
    data = load_json(batch_path)
    if not isinstance(data, dict) or data.get("schema_version") != "1.0":
        raise RestyleError("batch計画の形式が不正です")
    if data.get("operation") != "image_to_image_batch" or data.get("provider") != "novelai":
        raise RestyleError("NovelAI restyle batch計画ではありません")
    output_dir = Path(str(data.get("output_dir", ""))).expanduser().resolve()
    if not any(part.lower() == "_restyle" for part in output_dir.parts):
        raise RestyleError("batch計画の出力先は _restyle/ 配下である必要があります")
    if batch_path.parent != output_dir:
        raise RestyleError("batch計画のパスとoutput_dirが一致しません")
    items = data.get("items")
    if not isinstance(items, list) or not items:
        raise RestyleError("batch計画に画像項目がありません")
    item_ids = [str(item.get("item_id", "")) for item in items if isinstance(item, dict)]
    if len(item_ids) != len(items) or len(set(item_ids)) != len(item_ids):
        raise RestyleError("batch計画のitem_idが重複または欠落しています")
    return data, output_dir


def _batch_run_path(output_dir: Path) -> Path:
    return output_dir / "batch_run.json"


def _ensure_batch_output_clean(
    *, batch: dict[str, Any], output_dir: Path, plans: list[dict[str, Any]]
) -> None:
    run_path = _batch_run_path(output_dir)
    if run_path.exists():
        raise RestyleError(
            f"このbatchは既に実行記録があります。候補の上書きを防ぐため再executeを拒否します: {run_path}"
        )
    batch_id = str(batch["batch_id"])
    for plan in plans:
        source_stem = Path(str(plan["source_image"]["path"])).stem
        candidate_prefix = f"{source_stem}_restyle_{batch_id}_candidate_"
        if any(output_dir.glob(f"{candidate_prefix}*")):
            raise RestyleError(
                f"このbatchの候補が既に存在します。上書きを防ぐため再executeを拒否します: {source_stem}"
            )
        result_name = str(plan.get("result_manifest_filename") or "restyle_run.json")
        if Path(result_name).name != result_name or Path(result_name).suffix.lower() != ".json":
            raise RestyleError("結果manifestのファイル名は単純なJSON名で指定してください")
        if (output_dir / result_name).exists():
            raise RestyleError(
                f"このbatchの結果manifestが既に存在します。上書きを防ぐため再executeを拒否します: {result_name}"
            )


def _new_batch_run(batch: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "operation": "image_to_image_batch",
        "intent": "restyle",
        "provider": "novelai",
        "batch_id": batch["batch_id"],
        "output_dir": str(output_dir),
        "status": "running",
        "items": [
            {
                "item_id": item["item_id"],
                "source_image": item.get("source_image"),
                "status": "pending",
                "candidates": [],
                "adoption": {"status": "unadopted"},
            }
            for item in batch["items"]
        ],
        "adoption": {"status": "unadopted"},
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="NovelAI Image2Image restyle batch")
    parser.add_argument("--input", action="append", required=False, help="元画像PNG/JPEG（複数可）")
    parser.add_argument("--model", help="restyle先model。MVPはv4-5-full")
    parser.add_argument("--style-reference", action="append", default=[], help="Vibeまたは画像参照")
    parser.add_argument("--no-style-reference", action="store_true", help="参照なしを明示")
    parser.add_argument("--novel", help="作品フォルダ。--portionと併用")
    parser.add_argument("--portion", help="厳密解決するNovelAI portion ID")
    parser.add_argument("--prompt")
    parser.add_argument("--prompt-file", type=Path)
    parser.add_argument("--negative-prompt")
    parser.add_argument("--provider-options", type=Path)
    parser.add_argument("--output-dir", help="候補の親ディレクトリ（_restyleを自動付加）")
    parser.add_argument("--batch-plan", type=Path, help="dry-runで保存したbatch_plan.json（execute時に必須）")
    parser.add_argument("--target-size", help="変換案の目標寸法 WIDTHxHEIGHT")
    parser.add_argument("--allow-transform", action="store_true", help="dry-run時に寸法変換を承認")
    parser.add_argument("--alpha-background", help="RGBA入力をRGB合成する背景色（whiteまたは#RRGGBB）")
    parser.add_argument("--dry-run", action="store_true", help="要求せずbatch計画を保存")
    parser.add_argument("--execute", action="store_true", help="承認済みbatch計画をNovelAIへ送信")
    parser.add_argument("--json", action="store_true", help="JSONで表示（既定もJSON）")
    return parser


def _dry_run(args: argparse.Namespace) -> dict[str, Any]:
    if not args.input or not args.model or not args.output_dir:
        raise RestyleError("--dry-runには--input（1つ以上）、--model、--output-dirが必要です")
    sources = [Path(value).expanduser().resolve() for value in args.input]
    if len({str(path) for path in sources}) != len(sources):
        raise RestyleError("batchの--inputに同じ画像を重複指定できません")
    stems = [source.stem for source in sources]
    if len(set(stems)) != len(stems):
        raise RestyleError("batchの--inputに同じstemの画像を混在させられません")
    options = _load_options(args.provider_options)
    style_paths = _style_paths(args, ROOT)
    batch_id = _new_run_id()
    batch_dir = _resolve_output_dir(ROOT, args.output_dir) / batch_id
    batch_dir.mkdir(parents=True, exist_ok=True)
    items: list[dict[str, Any]] = []
    for source in sources:
        prompt, negative, prompt_source = _prompt_for_source(args, source)
        plan = build_restyle_plan(
            root=ROOT,
            source_path=source,
            model=args.model,
            prompt=prompt,
            negative_prompt=negative,
            style_reference_paths=style_paths,
            options=options,
            output_dir=str(batch_dir),
            run_id=batch_id,
            target_size=_parse_target_size(args.target_size),
            allow_transform=args.allow_transform,
            alpha_background=args.alpha_background,
            run_dir=batch_dir,
            prepared_filename=f"{source.stem}_prepared_source.png",
        )
        plan["prompt"]["source"] = prompt_source
        plan["batch_id"] = batch_id
        plan["batch_item_id"] = source.stem
        plan["result_manifest_filename"] = f"{source.stem}_restyle_run.json"
        plan_name = _safe_artifact_filename(f"{source.stem}_restyle_plan.json", label="restyle計画")
        plan_path = save_restyle_plan(plan, filename=plan_name)
        items.append(
            {
                "item_id": source.stem,
                "source_image": plan["source_image"],
                "plan_path": str(plan_path),
                "result_manifest_filename": plan["result_manifest_filename"],
                "sendable": bool(plan.get("sendable")),
            }
        )
    batch = {
        "schema_version": "1.0",
        "operation": "image_to_image_batch",
        "intent": "restyle",
        "provider": "novelai",
        "model": str(args.model),
        "batch_id": batch_id,
        "output_dir": str(batch_dir),
        "items": items,
        "approval": {"dry_run_required": True, "network_sent": False, "provider_switch": False},
        "notes": [
            "1回のbatchにつき最上位の_restyle/<batch_id>/を1つだけ使用",
            "各画像のplan・prepared画像・result manifestは同じbatchディレクトリに保存",
            "承認前の本番送信とprovider自動切替は行わない",
        ],
    }
    batch_path = _batch_plan_path(batch_dir)
    batch["batch_plan_path"] = str(batch_path)
    _save_json(batch_path, batch)
    return batch


def _execute(args: argparse.Namespace) -> dict[str, Any]:
    if args.batch_plan is None:
        raise RestyleError("--executeにはdry-runで保存した --batch-plan が必要です")
    batch, output_dir = _validate_batch_plan(args.batch_plan)
    plans: list[dict[str, Any]] = []
    for item in batch["items"]:
        if not isinstance(item, dict) or not item.get("plan_path"):
            raise RestyleError("batch計画のitemにplan_pathがありません")
        item_plan_path = Path(str(item["plan_path"])).expanduser().resolve()
        try:
            item_plan_path.relative_to(output_dir)
        except ValueError as exc:
            raise RestyleError("batch itemの計画がoutput_dir配下にありません") from exc
        plan = load_restyle_plan(item_plan_path)
        if plan.get("batch_id") != batch.get("batch_id") or Path(plan["output_dir"]).resolve() != output_dir:
            raise RestyleError("batch itemの計画が同じbatchディレクトリを指していません")
        plans.append(plan)
    _ensure_batch_output_clean(batch=batch, output_dir=output_dir, plans=plans)
    cfg = load_root_config(ROOT / "config" / "image_generation.json")
    provider_cfg = cfg["providers"]["novelai"]
    run = _new_batch_run(batch, output_dir)
    run_path = _batch_run_path(output_dir)
    run["batch_run_path"] = str(run_path)
    _save_json(run_path, run)
    for index, (item, plan) in enumerate(zip(batch["items"], plans)):
        try:
            result = execute_restyle(root=ROOT, plan=plan, provider_cfg=provider_cfg)
        except Exception as exc:
            run_item = run["items"][index]
            run_item["status"] = "failed"
            run_item["error"] = {"type": type(exc).__name__, "message": str(exc)[:500]}
            run["status"] = "partial_failure"
            run["failure"] = {
                "item_id": item["item_id"],
                "index": index,
                "message": str(exc)[:500],
                "remaining_items": [entry["item_id"] for entry in run["items"][index + 1 :]],
            }
            _save_json(run_path, run)
            raise RestyleError(
                f"batch item {item['item_id']} で停止しました。batch_run.jsonを確認し、同じ計画の再executeは行いません: {exc}"
            ) from exc
        run_item = run["items"][index]
        run_item.update(
            {
                "status": "success",
                "run_id": result.get("run_id"),
                "source_image": result.get("source_image"),
                "candidates": result.get("candidates", []),
                "adoption": {"status": "unadopted"},
            }
        )
        _save_json(run_path, run)
    run["status"] = "success"
    _save_json(run_path, run)
    return run


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.dry_run == args.execute:
        print("--dry-run または --execute のどちらか一方を指定してください", file=sys.stderr)
        return 2
    try:
        result = _dry_run(args) if args.dry_run else _execute(args)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (RestyleError, FileNotFoundError, KeyError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
