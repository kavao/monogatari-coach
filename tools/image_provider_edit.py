#!/usr/bin/env python3
"""Explicit image editing entry point.

Restyle is intentionally separate from ``image_provider_generate.py``.  Use
``--dry-run`` first; network execution requires the explicit ``--execute``
flag and never falls back to another provider.
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
    build_restyle_plan,
    execute_restyle,
    load_restyle_plan,
    load_prompt_candidates,
    save_restyle_plan,
)
from image_provider_generate import load_json, load_root_config  # noqa: E402
from novel_meta_yaml import resolve_novelai_portion_strict  # noqa: E402


def _parse_target_size(raw: str | None) -> tuple[int, int] | None:
    if not raw:
        return None
    try:
        width, height = raw.lower().split("x", 1)
        return int(width), int(height)
    except (ValueError, AttributeError) as exc:
        raise RestyleError("--target-size は WIDTHxHEIGHT 形式で指定してください") from exc


def _load_options(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    data = load_json(path)
    if not isinstance(data, dict):
        raise RestyleError("--provider-options のJSONルートはobjectである必要があります")
    return data


def _prompt_values(args: argparse.Namespace) -> tuple[str, str, str]:
    source = Path(args.input).expanduser().resolve()
    candidates: dict[str, str] = {}
    source_json = Path(args.source_json).expanduser().resolve() if args.source_json else source.with_suffix(".json")
    if source_json.is_file():
        candidates = load_prompt_candidates(source_json)
    prompt = args.prompt
    prompt_source = "--prompt"
    if args.prompt_file:
        prompt = Path(args.prompt_file).read_text(encoding="utf-8")
        prompt_source = "--prompt-file"
    if prompt is None:
        prompt = candidates.get("prompt")
        prompt_source = "same-name-json"
    if not isinstance(prompt, str) or not prompt.strip():
        raise RestyleError("promptは--prompt、--prompt-file、または許可された同名JSONのpromptで指定してください")
    negative = args.negative_prompt
    if negative is None:
        negative = candidates.get("negative_prompt", "")
    return prompt.strip(), str(negative or "").strip(), prompt_source


def _style_paths(args: argparse.Namespace, root: Path) -> list[Path]:
    direct = []
    for value in args.style_reference:
        candidate = Path(value).expanduser()
        direct.append(candidate if candidate.is_absolute() else root / candidate)
    if args.novel and args.portion:
        if direct:
            raise RestyleError("--novel/--portion と --style-reference は同時指定できません")
        portion = resolve_novelai_portion_strict(
            Path(args.novel).expanduser().resolve(), root, portion_id=args.portion
        )
        return [Path(path) for path in portion.paths]
    if args.novel or args.portion:
        raise RestyleError("作品ポーションは --novel と --portion を同時に指定してください")
    if not direct and not args.no_style_reference:
        raise RestyleError("参照なしは --no-style-reference を明示してください")
    return direct


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="NovelAI Image2Image restyle/edit")
    parser.add_argument("--operation", choices=("image-to-image",), default="image-to-image")
    parser.add_argument("--intent", choices=("restyle",), default="restyle")
    parser.add_argument("--provider", choices=("novelai",), default="novelai")
    parser.add_argument("--input", help="元画像PNG/JPEG（dry-run時に必須）")
    parser.add_argument("--model", help="restyle先model。MVPはv4-5-full（dry-run時に必須）")
    parser.add_argument("--style-reference", action="append", default=[], help="Vibeまたは画像参照。複数指定可")
    parser.add_argument("--no-style-reference", action="store_true", help="参照なしを明示")
    parser.add_argument("--novel", help="作品フォルダ。--portionと併用")
    parser.add_argument("--portion", help="厳密解決するNovelAI portion ID")
    parser.add_argument("--prompt")
    parser.add_argument("--prompt-file", type=Path)
    parser.add_argument("--source-json", type=Path, help="prompt/negative_promptだけを読む同名JSON")
    parser.add_argument("--negative-prompt")
    parser.add_argument("--provider-options", type=Path)
    parser.add_argument("--output-dir", help="候補の親ディレクトリ（dry-run時に必須。_restyleを自動付加）")
    parser.add_argument("--plan", type=Path, help="dry-runで保存した承認済みrestyle_plan.json（execute時に必須）")
    parser.add_argument("--target-size", help="変換案の目標寸法 WIDTHxHEIGHT")
    parser.add_argument("--allow-transform", action="store_true", help="承認済みの寸法変換を許可")
    parser.add_argument(
        "--alpha-background",
        help="RGBA入力を明示的にRGB合成する背景色（white または #RRGGBB）",
    )
    parser.add_argument("--dry-run", action="store_true", help="要求せずredacted planを表示")
    parser.add_argument("--execute", action="store_true", help="明示的にNovelAIへ送信")
    parser.add_argument("--json", action="store_true", help="JSONで表示（既定もJSON）")
    return parser


def main(argv: list[str] | None = None) -> int:
    raw_argv = list(argv if argv is not None else sys.argv[1:])
    if "--batch" in raw_argv:
        from image_provider_edit_batch import main as batch_main

        return batch_main([value for value in raw_argv if value != "--batch"])
    args = build_parser().parse_args(raw_argv)
    if args.dry_run == args.execute:
        print("--dry-run または --execute のどちらか一方を指定してください", file=sys.stderr)
        return 2
    try:
        root = ROOT
        if args.execute:
            if args.plan is None:
                raise RestyleError("--execute にはdry-runで保存した --plan を指定してください")
            plan = load_restyle_plan(args.plan)
            cfg = load_root_config(root / "config" / "image_generation.json")
            provider_cfg = cfg["providers"]["novelai"]
            result = execute_restyle(
                root=root,
                plan=plan,
                provider_cfg=provider_cfg,
                allow_transform=args.allow_transform,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0

        missing = [
            name
            for name, value in (
                ("--input", args.input),
                ("--model", args.model),
                ("--output-dir", args.output_dir),
            )
            if not value
        ]
        if missing:
            raise RestyleError(f"--dry-runには次の指定が必要です: {', '.join(missing)}")
        prompt, negative, prompt_source = _prompt_values(args)
        options = _load_options(args.provider_options)
        style_paths = _style_paths(args, root)
        plan = build_restyle_plan(
            root=root,
            source_path=Path(args.input),
            model=args.model,
            prompt=prompt,
            negative_prompt=negative,
            style_reference_paths=style_paths,
            options=options,
            output_dir=args.output_dir,
            target_size=_parse_target_size(args.target_size),
            allow_transform=args.allow_transform,
            alpha_background=args.alpha_background,
        )
        plan["prompt"]["source"] = prompt_source
        plan_path = save_restyle_plan(plan)
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        print(f"dry-run計画を保存しました: {plan_path}", file=sys.stderr)
        return 0
    except (RestyleError, FileNotFoundError, KeyError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
