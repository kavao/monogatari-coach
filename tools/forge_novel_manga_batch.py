#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
作品フォルダの manga/manga_*.md から、各 Page の ## step1 内「tag:」〜「和訳:」を抽出し、
Forge txt2img をコマごとに連続実行する。

保存先: manga/_assets/<manga_stem>/ （既定・file_prefix は <stem>_p<page>_k<koma>）。
  --subdir-by-page 指定時は manga/_assets/<manga_stem>/p<page>/ に保存（8ページなどをフォルダ分割）。
  novel_image_layout の k01.. は「1ページ内のコマ用スロット」用の任意フォルダで、本スクリプト既定では未使用。
前提: config/forge_config.json・Forge --api 起動（tools/forge_generate.py と同じ）
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


def normalize_tag_body(raw: str) -> str:
    s = raw.strip()
    s = re.sub(r"\s+", " ", s)
    return s


def extract_tags_from_step1(step1: str) -> list[str]:
    """
    Step1 本文から、コマ順にプロンプト英語行を抽出する。

    優先:
      - `- **tag**：` の次行にあるバッククォート1行（Monogatari Coach の現行 manga 形式）
    フォールバック:
      - `tag:` ～ `和訳:`（旧形式）
    """
    tags: list[str] = []
    for m in re.finditer(
        r"-\s*\*\*tag\*\*[：:]\s*\r?\n\s*`([^`]+)`",
        step1,
        flags=re.MULTILINE,
    ):
        body = normalize_tag_body(m.group(1))
        if body:
            tags.append(body)
    if tags:
        return tags
    for m in re.finditer(
        r"tag:\s*\r?\n([\s\S]*?)\r?\n和訳:",
        step1,
    ):
        body = normalize_tag_body(m.group(1))
        if body:
            tags.append(body)
    return tags


def extract_step1_block(page_body: str) -> str | None:
    """`### Step1` / `## step1` から次の Step2 手前まで。"""
    m = re.search(
        r"(?ms)^#{1,3}\s*Step1[^\n]*\r?\n(.*?)(?=^#{1,3}\s*Step2\b)",
        page_body,
    )
    return m.group(1) if m else None


def extract_manga_jobs_for_file(md_path: Path) -> list[dict[str, str]]:
    """
    1 つの manga_XX.md から、Page ごとの step1 内の各コマ tag を順に抽出。
    """
    stem = md_path.stem
    text = md_path.read_text(encoding="utf-8")
    jobs: list[dict[str, str]] = []

    # `## Page 1` のみ／`## Page 1 — タイトル` の1行見出しの両方に対応
    page_iter = re.finditer(
        r"## Page\s+(\d+)\s*[^\n]*\r?\n([\s\S]*?)(?=\r?\n## Page\s+\d+|\Z)",
        text,
    )
    for pm in page_iter:
        page_num = int(pm.group(1))
        page_body = pm.group(2)
        step1 = extract_step1_block(page_body)
        if not step1:
            continue
        tag_lines = extract_tags_from_step1(step1)
        koma_idx = 0
        for body in tag_lines:
            koma_idx += 1
            prefix = f"{stem}_p{page_num:02d}_k{koma_idx:02d}"
            jobs.append(
                {
                    "stem": stem,
                    "page": str(page_num),
                    "koma": str(koma_idx),
                    "prefix": prefix,
                    "prompt": STYLE_PREFIX + body,
                }
            )
    return jobs


def iter_manga_jobs(novel_dir: Path, only_stem: str | None) -> list[dict[str, str]]:
    manga_dir = novel_dir / "manga"
    if not manga_dir.is_dir():
        raise FileNotFoundError(f"manga/ がありません: {manga_dir}")
    all_jobs: list[dict[str, str]] = []
    paths = sorted(manga_dir.glob("manga_*.md"))
    if only_stem:
        paths = [p for p in paths if p.stem == only_stem]
        if not paths:
            raise FileNotFoundError(
                f"manga/{only_stem}.md が見つかりません: {manga_dir}"
            )
    for md_path in paths:
        stem = md_path.stem
        base = (manga_dir / "_assets" / stem).resolve()
        for j in extract_manga_jobs_for_file(md_path):
            j["output_dir"] = base.as_posix()
            all_jobs.append(j)
    return all_jobs


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="manga/manga_*.md の各コマ tag を Forge で画像化（各1枚）"
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
        "--manga-stem",
        default=None,
        metavar="STEM",
        help="1 ファイルだけ（例: manga_01）",
    )
    p.add_argument(
        "--negative-prompt",
        default=DEFAULT_NEGATIVE,
        help="negative_prompt（既定は汎用）",
    )
    p.add_argument(
        "--subdir-by-page",
        action="store_true",
        help="保存先を manga/_assets/<stem>/p01, p02, ...（Page 番号）の下に分ける",
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
        jobs = iter_manga_jobs(novel, args.manga_stem)
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    if not jobs:
        print("error: ジョブが0件です（tag: / 和訳: の形式を確認）", file=sys.stderr)
        return 2

    forge = root / "tools" / "forge_generate.py"
    if not forge.is_file():
        print(f"error: {forge} がありません", file=sys.stderr)
        return 2

    print(f"novel: {novel}")
    print(f"jobs: {len(jobs)}")

    for job in jobs:
        out_dir = Path(job["output_dir"])
        if args.subdir_by_page:
            out_dir = out_dir / f"p{int(job['page']):02d}"
        out_dir_posix = out_dir.as_posix()

        payload = {
            "prompt": job["prompt"],
            "negative_prompt": args.negative_prompt,
            "output_dir": out_dir_posix,
            "file_prefix": job["prefix"],
            "count": 1,
            "seed": None,
        }
        if args.dry_run:
            print(f"  [{job['prefix']}] -> {out_dir_posix}")
            print(f"    prompt[:100]: {payload['prompt'][:100]}...")
            continue

        out = out_dir
        out.mkdir(parents=True, exist_ok=True)

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
            print(
                f"error: forge が失敗しました ({job['prefix']}) code={r.returncode}",
                file=sys.stderr,
            )
            return r.returncode or 1
        print(r.stdout.strip())

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
