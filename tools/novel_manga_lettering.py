#!/usr/bin/env python3
"""Crop, composite, and letter manga page images without calling providers."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml
from PIL import Image

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from manga_prompt_ir.page_edit import (
    PageEditError,
    bind_actual_geometry,
    composite_masked_region,
    composite_panel,
    crop_panel,
    letter_page,
    refuse_region_edit_provider,
    project_design_geometry,
    sha256_file,
    write_json,
)


def _load_page(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="漫画ページの切り出し・合成・写植（ローカル）")
    sub = parser.add_subparsers(dest="command", required=True)

    project = sub.add_parser("project-design", help="IRのlayout_geometryを画素矩形へ投影する")
    project.add_argument("--page", type=Path, required=True)
    project.add_argument("--image", type=Path, required=True)
    project.add_argument("--out", type=Path, required=True)

    bind = sub.add_parser("bind-actual", help="source_sha256付きactual_geometryを検証する")
    bind.add_argument("--geometry", type=Path, required=True)
    bind.add_argument("--image", type=Path, required=True)
    bind.add_argument("--out", type=Path, required=True)
    bind.add_argument("--page", type=Path, help="指定すると未知／panel不一致の text_id を停止する")

    bubbles = sub.add_parser("validate-bubbles", help="local frame 用 bubbles sidecar を検証する")
    bubbles.add_argument("--page", type=Path, required=True)
    bubbles.add_argument("--bubbles", type=Path, required=True)
    bubbles.add_argument("--generation-json", type=Path, required=True, help="泡抑止記録（local+none+bubbles_suppressed）")
    bubbles.add_argument("--image", type=Path, help="指定すると正規化座標を画素へ投影する")
    bubbles.add_argument("--out", type=Path, help="投影結果の書き出し先")

    bubbles_actual = sub.add_parser(
        "bind-bubbles-actual",
        help="bubbles設計座標を画像hash付きactual geometryへ確定する",
    )
    bubbles_actual.add_argument("--page", type=Path, required=True)
    bubbles_actual.add_argument("--bubbles", type=Path, required=True)
    bubbles_actual.add_argument("--generation-json", type=Path, required=True)
    bubbles_actual.add_argument("--image", type=Path, required=True)
    bubbles_actual.add_argument("--out", type=Path, required=True)

    frames = sub.add_parser("render-bubbles", help="clean PNG へ local 吹き出し枠を描く")
    frames.add_argument("--page", type=Path, required=True)
    frames.add_argument("--bubbles", type=Path, required=True)
    frames.add_argument("--generation-json", type=Path, required=True)
    frames.add_argument("--image", type=Path, required=True)
    frames.add_argument("--out", type=Path, required=True)
    frames.add_argument("--result-json", type=Path)

    crop = sub.add_parser("crop", help="指定panelを切り出す")
    crop.add_argument("--image", type=Path, required=True)
    crop.add_argument("--geometry", type=Path, required=True)
    crop.add_argument("--panel-id", type=int, required=True)
    crop.add_argument("--out", type=Path, required=True)

    composite = sub.add_parser("composite", help="切り出しコマをページへ戻し範囲外画素を検査する")
    composite.add_argument("--page-image", type=Path, required=True)
    composite.add_argument("--panel-image", type=Path, required=True)
    composite.add_argument("--geometry", type=Path, required=True)
    composite.add_argument("--panel-id", type=int, required=True)
    composite.add_argument("--out", type=Path, required=True)

    letter = sub.add_parser("letter", help="IRの文字を既知矩形へ載せる。未配置・はみ出しは未完成")
    letter.add_argument("--page", type=Path, required=True)
    letter.add_argument("--image", type=Path, required=True)
    letter.add_argument("--geometry", type=Path, required=True)
    letter.add_argument("--font", type=Path, required=True)
    letter.add_argument(
        "--font-size",
        type=int,
        default=None,
        help="基準フォントサイズ。省略時はページのmanga.lettering.base_font_size（既定30）",
    )
    letter.add_argument("--size-ratio", type=float, default=1.0)
    letter.add_argument("--vertical-scale", type=float, default=1.0)
    letter.add_argument("--out", type=Path, required=True)
    letter.add_argument("--result-json", type=Path)

    region = sub.add_parser(
        "region-edit",
        help="maskの非ゼロ画素だけを差し替える。範囲外は元画素と一致する必要がある",
    )
    region.add_argument("--page-image", type=Path, required=True)
    region.add_argument("--replacement", type=Path, required=True)
    region.add_argument("--mask", type=Path, required=True)
    region.add_argument("--source-sha256", required=True)
    region.add_argument("--out", type=Path, required=True)
    region.add_argument("--provider", default=None, help="指定すると未対応providerは送信前に拒否する")

    args = parser.parse_args(argv)
    try:
        if args.command == "project-design":
            with Image.open(args.image) as image:
                size = image.size
            payload = project_design_geometry(_load_page(args.page), image_size=size)
            payload["image_path"] = str(args.image.resolve())
            payload["source_sha256"] = sha256_file(args.image)
            write_json(args.out, payload)
            print(f"kind=design_projected panels={len(payload['panels'])} -> {args.out}")
            return 0
        if args.command == "bind-actual":
            page = _load_page(args.page) if args.page else None
            payload = bind_actual_geometry(
                _load_json(args.geometry),
                image_path=args.image,
                page=page,
            )
            write_json(args.out, payload)
            print(
                f"kind=actual panels={len(payload['panels'])} "
                f"texts={len(payload['texts'])} -> {args.out}"
            )
            return 0
        if args.command == "validate-bubbles":
            from manga_prompt_ir.bubble_geometry import (
                project_bubble_design,
                validate_bubble_design,
            )

            page = _load_page(args.page)
            sidecar = yaml.safe_load(args.bubbles.read_text(encoding="utf-8"))
            generation = _load_json(args.generation_json)
            document = validate_bubble_design(
                page,
                sidecar,
                source_generation=generation,
                image_path=args.image,
            )
            if args.image is None:
                print(f"kind=design_projected bubbles={len(document.bubbles)}")
                return 0
            with Image.open(args.image) as image:
                size = image.size
            projected = project_bubble_design(
                page,
                sidecar,
                image_size=size,
                source_generation=generation,
                image_path=args.image,
            )
            if args.out:
                write_json(args.out, projected)
                print(f"kind=design_projected bubbles={len(projected['bubbles'])} -> {args.out}")
            else:
                print(f"kind=design_projected bubbles={len(projected['bubbles'])}")
            return 0
        if args.command == "bind-bubbles-actual":
            from manga_prompt_ir.bubble_geometry import (
                bind_bubble_actual,
                project_bubble_design,
            )

            page = _load_page(args.page)
            sidecar = yaml.safe_load(args.bubbles.read_text(encoding="utf-8"))
            generation = _load_json(args.generation_json)
            with Image.open(args.image) as image:
                size = image.size
            projected = project_bubble_design(
                page,
                sidecar,
                image_size=size,
                source_generation=generation,
                image_path=args.image,
            )
            payload = bind_bubble_actual(
                projected,
                image_path=args.image,
                page=page,
            )
            write_json(args.out, payload)
            print(
                f"kind=actual bubbles={len(payload['bubbles'])} "
                f"texts={len(payload['texts'])} -> {args.out}"
            )
            return 0
        if args.command == "render-bubbles":
            from manga_prompt_ir.bubble_frame_render import render_local_bubble_frames

            result = render_local_bubble_frames(
                _load_page(args.page),
                yaml.safe_load(args.bubbles.read_text(encoding="utf-8")),
                image_path=args.image,
                out_path=args.out,
                source_generation=_load_json(args.generation_json),
            )
            if args.result_json:
                write_json(args.result_json, result)
            print(
                json.dumps(
                    {k: result[k] for k in ("complete", "frame_count", "path")},
                    ensure_ascii=False,
                )
            )
            return 0 if result["complete"] else 3
        if args.command == "region-edit":
            if args.provider:
                refuse_region_edit_provider(args.provider)
            result = composite_masked_region(
                args.page_image,
                args.replacement,
                args.mask,
                args.out,
                source_sha256=args.source_sha256,
            )
            print(json.dumps(result, ensure_ascii=False))
            return 0 if result["complete"] else 3
        geometry = _load_json(args.geometry)
        if args.command == "crop":
            result = crop_panel(args.image, geometry, args.panel_id, args.out)
            print(json.dumps(result, ensure_ascii=False))
            return 0
        if args.command == "composite":
            result = composite_panel(
                args.page_image,
                args.panel_image,
                geometry,
                args.panel_id,
                args.out,
            )
            print(json.dumps(result, ensure_ascii=False))
            return 0 if result["complete"] else 3
        if args.command == "letter":
            result = letter_page(
                _load_page(args.page),
                args.image,
                args.out,
                font_path=args.font,
                geometry=geometry,
                font_size=args.font_size,
                size_ratio=args.size_ratio,
                vertical_scale=args.vertical_scale,
            )
            if args.result_json:
                write_json(args.result_json, result)
            print(json.dumps({k: result[k] for k in ("complete", "unplaced", "overflow", "path")}, ensure_ascii=False))
            return 0 if result["complete"] else 3
    except (PageEditError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
