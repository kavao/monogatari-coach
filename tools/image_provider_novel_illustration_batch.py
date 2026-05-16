#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
作品フォルダの illustrations/pages/*.yaml から、挿絵・表紙の画像生成ジョブを作る。

保存先: illustrations/_assets/<illustration_stem>/ （file_prefix は <stem>_p<page>）。
前提: config/image_generation.json・各 provider の準備完了（tools/image_provider_generate.py と同じ）。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from image_provider_novel_manga_batch import (  # noqa: E402
    DEFAULT_NEGATIVE,
    PROVIDER_CHOICES,
    STYLE_PREFIX,
    as_list,
    join_tags,
    load_character_ir_map,
    load_dotenv,
    load_yaml,
    merge_panel_negative_prompt,
    repo_root,
    validate_provider,
    yaml_panel_tags,
)
from manga_prompt_ir.schemas.manga_page import MangaPagePrompt  # noqa: E402
from manga_prompt_ir.prompt_formatters import (  # noqa: E402
    format_illustration_prompt,
    provider_config_from_root,
    resolve_prompt_formatter,
)


ILLUSTRATION_PROVIDER_ENV = "MONOCRI_ILLUSTRATION_PROVIDER_DEFAULT"
ILLUSTRATION_MODEL_ENV = "MONOCRI_ILLUSTRATION_MODEL_DEFAULT"
ILLUSTRATION_ASPECT_RATIO_ENV = "MONOCRI_ILLUSTRATION_ASPECT_RATIO_DEFAULT"
ILLUSTRATION_RESOLUTION_ENV = "MONOCRI_ILLUSTRATION_RESOLUTION_DEFAULT"


def safe_print(text: str, *, stderr: bool = False) -> None:
    if not text:
        return
    stream = sys.stderr if stderr else sys.stdout
    try:
        print(text, file=stream)
    except UnicodeEncodeError:
        enc = getattr(stream, "encoding", None) or "utf-8"
        print(text.encode(enc, errors="backslashreplace").decode(enc), file=stream)


def yaml_page_number(path: Path, fallback: int) -> int:
    match = re.search(r"_p(\d+)$", path.stem)
    if match:
        return int(match.group(1))
    return fallback


def illustration_asset_stem(path: Path, page: dict[str, Any]) -> str:
    stem = str(page.get("stem") or path.stem)
    return re.sub(r"_p\d+$", "", stem)


def iter_illustration_paths(novel_dir: Path, only_stem: str | None) -> list[Path]:
    pages_dir = novel_dir / "illustrations" / "pages"
    if not pages_dir.is_dir():
        raise FileNotFoundError(f"illustrations/pages/ がありません: {pages_dir}")
    paths = sorted(pages_dir.glob("illustration_*.yaml"))
    if only_stem:
        paths = [
            path
            for path in paths
            if re.match(rf"{re.escape(only_stem)}(?:_p\d+)?$", path.stem)
        ]
        if not paths:
            raise FileNotFoundError(
                f"illustrations/pages/{only_stem}_p*.yaml が見つかりません: {pages_dir}"
            )
    return paths


def page_prompt_tags(page: dict[str, Any], characters: dict[str, Any]) -> list[str]:
    tags: list[str] = []
    manga = page.get("manga") or {}
    tags.extend(as_list(manga.get("genre_tags")))
    tags.extend(as_list(manga.get("visual_tags")))
    for panel in as_list(page.get("panels")):
        if isinstance(panel, dict):
            tags.extend(yaml_panel_tags(page, panel, characters, single_panel=True))
    return tags


def iter_illustration_jobs(
    novel_dir: Path,
    only_stem: str | None,
    *,
    cli_negative_prompt: str,
    provider: str,
    prompt_formatter: str,
) -> list[dict[str, str]]:
    characters = load_character_ir_map(novel_dir)
    pages_dir = novel_dir / "illustrations"
    jobs: list[dict[str, str]] = []
    for index, path in enumerate(iter_illustration_paths(novel_dir, only_stem), start=1):
        page = load_yaml(path)
        model = MangaPagePrompt.model_validate(page)
        if model.meta.intent != "illustration":
            raise ValueError(f"{path}: meta.intent は illustration である必要があります")
        stem = illustration_asset_stem(path, page)
        page_num = yaml_page_number(path, index)
        tags = join_tags(page_prompt_tags(page, characters))
        if not tags:
            continue
        technical = page.get("technical") or {}
        negative_prompt = merge_panel_negative_prompt(
            cli_negative_prompt,
            as_list(technical.get("negative_tags")),
            [],
            [],
        )
        bundle = format_illustration_prompt(
            page,
            tag_prompt=tags,
            negative_prompt=negative_prompt,
            formatter=prompt_formatter,
            style_prefix=STYLE_PREFIX,
        )
        jobs.append(
            {
                "stem": stem,
                "page": str(page_num),
                "prefix": f"{stem}_p{page_num:02d}",
                "prompt": bundle.prompt,
                "negative_prompt": bundle.negative_prompt,
                "prompt_formatter": bundle.formatter,
                "negative_mode": bundle.negative_mode,
                "output_dir": (pages_dir / "_assets" / stem).resolve().as_posix(),
            }
        )
    return jobs


def dotenv_or_env(root: Path, name: str) -> str | None:
    value = os.environ.get(name)
    if value and value.strip():
        return value.strip()
    dotenv_map = load_dotenv(root / ".env")
    value = dotenv_map.get(name)
    if value and value.strip():
        return value.strip()
    return None


def resolve_illustration_provider(root: Path, args_provider: str | None) -> str:
    if args_provider:
        return validate_provider(args_provider, source="CLI --provider")
    env_provider = dotenv_or_env(root, ILLUSTRATION_PROVIDER_ENV)
    if env_provider:
        return validate_provider(env_provider, source=f".env {ILLUSTRATION_PROVIDER_ENV}")
    return validate_provider("grok_pro", source="illustration default")


def resolve_illustration_option(
    root: Path,
    cli_value: str | None,
    env_name: str,
    default: str | None = None,
) -> str | None:
    if cli_value is not None:
        return cli_value
    env_value = dotenv_or_env(root, env_name)
    if env_value:
        return env_value
    return default


def run_provider_job(
    root: Path,
    provider_cli: Path,
    provider: str,
    job: dict[str, str],
    *,
    aspect_ratio: str | None,
    model: str | None,
    resolution: str | None,
    dry_run: bool,
) -> int:
    payload: dict[str, Any] = {
        "provider": provider,
        "prompt": job["prompt"],
        "negative_prompt": job["negative_prompt"],
        "prompt_formatter": job["prompt_formatter"],
        "negative_mode": job["negative_mode"],
        "output_dir": job["output_dir"],
        "file_prefix": job["prefix"],
        "count": 1,
        "seed": None,
    }
    if model is not None:
        payload["model"] = model
    if aspect_ratio is not None:
        payload["aspect_ratio_preset"] = aspect_ratio
    if resolution is not None:
        payload["resolution"] = resolution

    if dry_run:
        print(f"  [{job['prefix']}] -> {job['output_dir']}")
        print(f"    prompt_formatter: {job['prompt_formatter']}")
        print(f"    negative_mode: {job['negative_mode']}")
        print(f"    prompt[:100]: {payload['prompt'][:100]}...")
        neg_show = str(payload["negative_prompt"])
        if len(neg_show) > 160:
            neg_show = neg_show[:160] + "..."
        print(f"    negative: {neg_show}")
        return 0

    Path(job["output_dir"]).mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".json",
        delete=False,
        encoding="utf-8",
    ) as tf:
        json.dump(payload, tf, ensure_ascii=False, indent=2)
        tf_path = Path(tf.name)

    try:
        result = subprocess.run(
            [
                sys.executable,
                str(provider_cli),
                "--params",
                str(tf_path),
                "--json",
            ],
            cwd=str(root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    finally:
        tf_path.unlink(missing_ok=True)

    if result.returncode != 0:
        safe_print(result.stderr or result.stdout, stderr=True)
        print(
            f"error: image provider が失敗しました ({job['prefix']}) code={result.returncode}",
            file=sys.stderr,
        )
        return result.returncode or 1
    safe_print(result.stdout.strip())
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="illustrations/pages/*.yaml から挿絵・表紙の画像生成ジョブを作る"
    )
    parser.add_argument("novel_dir", type=Path, help="作品フォルダ（例: novels/051_タイトル）")
    parser.add_argument("--dry-run", action="store_true", help="image provider に送らず、抽出したジョブだけ表示")
    parser.add_argument("--illustration-stem", default=None, metavar="STEM", help="1 系列だけ（例: illustration_01）")
    parser.add_argument("--negative-prompt", default=DEFAULT_NEGATIVE, help="negative_prompt（既定は汎用）")
    parser.add_argument("--provider", choices=PROVIDER_CHOICES, default=None, help="生成プロバイダ")
    parser.add_argument("--prompt-formatter", default=None, help="provider 別プロンプト整形を上書き")
    parser.add_argument("--model", default=None, help="provider に渡すモデル名または alias（例: quality）")
    parser.add_argument("--aspect-ratio", default=None, help="Forge/Grok 用の比率 preset 名または比率文字列")
    parser.add_argument("--resolution", default=None, help="Grok 用の解像度（例: 1k, 2k）")
    parser.add_argument("--min-page", type=int, default=None, help="処理する Page 番号の下限（含む）")
    parser.add_argument("--max-page", type=int, default=None, help="処理する Page 番号の上限（含む）")
    args = parser.parse_args(argv)

    root = repo_root()
    novel = args.novel_dir
    if not novel.is_absolute():
        novel = (root / novel).resolve()
    if not novel.is_dir():
        print(f"error: ディレクトリがありません: {novel}", file=sys.stderr)
        return 2

    try:
        provider = resolve_illustration_provider(root, args.provider)
        prompt_formatter = resolve_prompt_formatter(
            provider,
            "illustration",
            provider_cfg=provider_config_from_root(root, provider),
            cli_formatter=args.prompt_formatter,
        )
        model = resolve_illustration_option(root, args.model, ILLUSTRATION_MODEL_ENV)
        aspect_ratio = resolve_illustration_option(
            root,
            args.aspect_ratio,
            ILLUSTRATION_ASPECT_RATIO_ENV,
            default="book_cover",
        )
        resolution = resolve_illustration_option(
            root,
            args.resolution,
            ILLUSTRATION_RESOLUTION_ENV,
            default="2k",
        )
        jobs = iter_illustration_jobs(
            novel,
            args.illustration_stem,
            cli_negative_prompt=args.negative_prompt,
            provider=provider,
            prompt_formatter=prompt_formatter,
        )
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    jobs = [
        job for job in jobs
        if (
            (args.min_page is None or int(job["page"]) >= args.min_page)
            and (args.max_page is None or int(job["page"]) <= args.max_page)
        )
    ]
    if not jobs:
        print("error: ジョブが0件です（illustrations/pages/*.yaml の panels/prompt_tags を確認）", file=sys.stderr)
        return 2

    provider_cli = root / "tools" / "image_provider_generate.py"
    if not provider_cli.is_file():
        print(f"error: {provider_cli} がありません", file=sys.stderr)
        return 2

    print(f"novel: {novel}")
    print("input: yaml")
    print(f"provider: {provider}")
    print(f"prompt_formatter: {prompt_formatter}")
    if model is not None:
        print(f"model: {model}")
    if aspect_ratio is not None:
        print(f"aspect_ratio: {aspect_ratio}")
    if resolution is not None:
        print(f"resolution: {resolution}")
    print(f"jobs: {len(jobs)}")

    for job in jobs:
        code = run_provider_job(
            root,
            provider_cli,
            provider,
            job,
            aspect_ratio=aspect_ratio,
            model=model,
            resolution=resolution,
            dry_run=args.dry_run,
        )
        if code != 0:
            return code
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
