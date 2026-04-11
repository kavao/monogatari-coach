#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
作品フォルダの tag/*.md から「Danbooru Tags:」行を抽出し、Forge txt2img を連続実行する。

前提: config/forge_config.json・Forge --api 起動（tools/forge_generate.py と同じ）

MD の推奨書式: _how_to/tag.md「Markdown ファイル形式（機械抽出と整合）」、
スキル novel-tag-md-format（.rulesync/skills/novel-tag-md-format/SKILL.md）。
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


STYLE_PREFIX = (
    "best quality, very aesthetic, ultra-detailed, best illustration, "
)

DEFAULT_NEGATIVE = (
    "lowres, worst quality, jpeg artifacts, blurry, bad hands, bad anatomy, "
    "extra fingers, watermark, username, text, logo"
)


def extract_sections(md_text: str) -> list[tuple[int, str]]:
    """
    各「N. 見出し」ブロック内の Danbooru Tags 行を返す。
    戻り値: [(section_no, tags_line), ...]
    """
    # 先頭のタイトル・共通行をスキップし、番号付きセクションへ
    # 「1. 見出し」「## 1. 見出し」「### 1. 見出し」に対応
    sec_line = r"(?:#{1,3}\s+)?\d+\.\s+[^\n]+\s*$"
    blocks = re.split(r"\n(?=" + sec_line + r")", md_text, flags=re.MULTILINE)
    out: list[tuple[int, str]] = []
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        m_head = re.match(r"^(?:#{1,3}\s+)?(\d+)\.\s+", block)
        if not m_head:
            continue
        sec_no = int(m_head.group(1))
        # 「Danbooru Tags:」単体、または **Danbooru Tags:**（コロンが太字内）の両方
        dm = re.search(
            r"(?:\*{0,2})Danbooru Tags:(?:\*{0,2})\s*\n\s*([^\n]+)", block
        )
        if not dm:
            continue
        tags = dm.group(1).strip()
        if tags:
            out.append((sec_no, tags))
    out.sort(key=lambda x: x[0])
    return out


def iter_tag_jobs(novel_dir: Path) -> list[dict[str, str]]:
    tag_dir = novel_dir / "tag"
    if not tag_dir.is_dir():
        raise FileNotFoundError(f"tag/ がありません: {tag_dir}")
    jobs: list[dict[str, str]] = []
    for md_path in sorted(tag_dir.glob("*.md")):
        stem = md_path.stem
        text = md_path.read_text(encoding="utf-8")
        sections = extract_sections(text)
        for sec_no, tags in sections:
            prefix = f"{stem}_{sec_no:02d}"
            jobs.append(
                {
                    "stem": stem,
                    "section_no": str(sec_no),
                    "prefix": prefix,
                    "prompt": STYLE_PREFIX + tags,
                    "output_dir": (tag_dir / stem).as_posix(),
                }
            )
    return jobs


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="tag/*.md の Danbooru Tags を Forge で画像化（各1枚）"
    )
    p.add_argument(
        "novel_dir",
        type=Path,
        help="作品フォルダ（例: novels/051_タイトル）",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="forge に送らず、抽出したジョブだけ表示",
    )
    p.add_argument(
        "--negative-prompt",
        default=DEFAULT_NEGATIVE,
        help="negative_prompt（既定は汎用）",
    )
    p.add_argument(
        "--min-section",
        type=int,
        default=None,
        help="番号付きセクションの下限（含む）。未指定なら制限なし",
    )
    p.add_argument(
        "--max-section",
        type=int,
        default=None,
        help="番号付きセクションの上限（含む）。未指定なら制限なし",
    )
    args = p.parse_args(argv)

    root = repo_root()
    novel = args.novel_dir
    if not novel.is_absolute():
        novel = (root / novel).resolve()
    if not novel.is_dir():
        print(f"error: ディレクトリがありません: {novel}", file=sys.stderr)
        return 2

    try:
        jobs = iter_tag_jobs(novel)
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    if args.min_section is not None or args.max_section is not None:
        lo = args.min_section if args.min_section is not None else -10**9
        hi = args.max_section if args.max_section is not None else 10**9
        jobs = [j for j in jobs if lo <= int(j["section_no"]) <= hi]

    if not jobs:
        print("error: Danbooru Tags を1件も抽出できませんでした", file=sys.stderr)
        return 2

    forge = root / "tools" / "forge_generate.py"
    if not forge.is_file():
        print(f"error: {forge} がありません", file=sys.stderr)
        return 2

    print(f"novel: {novel}")
    print(f"jobs: {len(jobs)}")

    for job in jobs:
        payload = {
            "prompt": job["prompt"],
            "negative_prompt": args.negative_prompt,
            "output_dir": job["output_dir"],
            "file_prefix": job["prefix"],
            "count": 1,
            "seed": None,
        }
        if args.dry_run:
            print(f"  [{job['prefix']}] -> {job['output_dir']}")
            print(f"    prompt[:120]: {payload['prompt'][:120]}...")
            continue

        (novel / "tag" / job["stem"]).mkdir(parents=True, exist_ok=True)

        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".json",
            delete=False,
            encoding="utf-8",
        ) as tf:
            json.dump(payload, tf, ensure_ascii=False, indent=2)
            tf_path = Path(tf.name)

        try:
            r = subprocess.run(
                [
                    sys.executable,
                    str(forge),
                    "--params",
                    str(tf_path),
                    "--json",
                ],
                cwd=str(root),
                capture_output=True,
                text=True,
            )
        finally:
            tf_path.unlink(missing_ok=True)

        if r.returncode != 0:
            print(r.stderr or r.stdout, file=sys.stderr)
            print(f"error: forge が失敗しました ({job['prefix']}) code={r.returncode}", file=sys.stderr)
            return r.returncode or 1
        print(r.stdout.strip())

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
