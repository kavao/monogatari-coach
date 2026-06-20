#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Archive a Codex/ChatGPT built-in image generation result into the workspace."""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def latest_image(search_dir: Path) -> Path:
    candidates = [
        path
        for path in search_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
    ]
    if not candidates:
        raise FileNotFoundError(f"画像ファイルが見つかりません: {search_dir}")
    return max(candidates, key=lambda path: path.stat().st_mtime)


def unique_destination(dest_dir: Path, prefix: str, suffix: str) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    candidate = dest_dir / f"{prefix}_{ts}{suffix}"
    counter = 2
    while candidate.exists():
        candidate = dest_dir / f"{prefix}_{ts}_{counter:02d}{suffix}"
        counter += 1
    return candidate


def write_metadata(
    *,
    meta_path: Path,
    source: Path,
    image_path: Path,
    prompt: str | None,
    note: str | None,
) -> None:
    meta = {
        "provider": "codex_builtin_imagegen",
        "source_image": str(source),
        "saved_image": str(image_path),
        "archived_at": datetime.now().isoformat(timespec="seconds"),
    }
    if prompt:
        meta["prompt"] = prompt
    if note:
        meta["note"] = note
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Copy a built-in Codex/ChatGPT generated image into a project asset folder."
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=None,
        help="生成画像ファイル。未指定なら --search-dir から最新画像を選ぶ。",
    )
    parser.add_argument(
        "--search-dir",
        type=Path,
        default=Path.home() / ".codex" / "generated_images",
        help="--source 未指定時に最新画像を探すディレクトリ。",
    )
    parser.add_argument("--dest-dir", type=Path, required=True, help="コピー先ディレクトリ。")
    parser.add_argument("--prefix", required=True, help="保存ファイル名の接頭辞。")
    parser.add_argument("--prompt", default=None, help="生成プロンプトの記録。")
    parser.add_argument("--note", default=None, help="任意メモ。")
    args = parser.parse_args(argv)

    root = repo_root()
    source = args.source
    if source is None:
        search_dir = args.search_dir
        if not search_dir.is_absolute():
            search_dir = (root / search_dir).resolve()
        source = latest_image(search_dir)
    if not source.is_absolute():
        source = (root / source).resolve()
    if not source.is_file():
        raise FileNotFoundError(f"source が見つかりません: {source}")

    dest_dir = args.dest_dir
    if not dest_dir.is_absolute():
        dest_dir = (root / dest_dir).resolve()
    dest_dir.mkdir(parents=True, exist_ok=True)

    image_path = unique_destination(dest_dir, args.prefix, source.suffix.lower())
    shutil.copy2(source, image_path)
    meta_path = image_path.with_suffix(".json")
    write_metadata(
        meta_path=meta_path,
        source=source,
        image_path=image_path,
        prompt=args.prompt,
        note=args.note,
    )
    print(json.dumps({"image": str(image_path), "json": str(meta_path)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
