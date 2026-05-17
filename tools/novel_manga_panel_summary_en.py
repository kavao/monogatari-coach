#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Translate ``panels[].summary`` → ``summary_en`` for manga page YAML IR."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from image_provider_generate import load_dotenv, resolve_env_value  # noqa: E402
from manga_prompt_ir.summary_en import (  # noqa: E402
    needs_summary_en_translation,
    normalize_summary_text,
    translate_panel_summaries,
)

SUMMARY_EN_MODEL_ENV = "MONOCRI_SUMMARY_EN_MODEL"
DEFAULT_SUMMARY_EN_MODEL = "gpt-4o-mini"
SUMMARY_EN_PROVIDER_ENV = "MONOCRI_SUMMARY_EN_PROVIDER"
OPENAI_BASE = "https://api.openai.com/v1"
OPENROUTER_BASE = "https://openrouter.ai/api/v1"


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def load_yaml(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"YAML root must be a mapping: {path}")
    return data


def write_yaml(path: Path, data: dict) -> None:
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=120),
        encoding="utf-8",
    )


def resolve_translate_config(root: Path) -> tuple[str, str, str]:
    dotenv = load_dotenv(root / ".env")
    provider = (
        resolve_env_value(SUMMARY_EN_PROVIDER_ENV, dotenv) or "openai"
    ).strip().lower()
    model = resolve_env_value(SUMMARY_EN_MODEL_ENV, dotenv) or DEFAULT_SUMMARY_EN_MODEL
    if provider == "openrouter":
        api_key = resolve_env_value("OPENROUTER_API_KEY", dotenv) or ""
        base_url = OPENROUTER_BASE
    else:
        api_key = resolve_env_value("OPENAI_API_KEY", dotenv) or ""
        base_url = OPENAI_BASE
    return api_key, model, base_url


def process_page_file(
    path: Path,
    *,
    api_key: str,
    model: str,
    base_url: str,
    force: bool,
    dry_run: bool,
) -> int:
    data = load_yaml(path)
    panels = data.get("panels")
    if not isinstance(panels, list):
        print(f"skip (no panels): {path}")
        return 0

    todo: list[tuple[int, str, dict]] = []
    for panel in panels:
        if not isinstance(panel, dict):
            continue
        if not needs_summary_en_translation(panel, force=force):
            continue
        summary = normalize_summary_text(panel.get("summary"))
        pid = int(panel.get("panel_id", len(todo) + 1))
        todo.append((pid, summary, panel))

    if not todo:
        print(f"OK (up to date): {path}")
        return 0

    if dry_run:
        print(f"would translate {len(todo)} panel(s) in {path}")
        for pid, summary, _ in todo:
            print(f"  panel {pid}: {summary[:60]}...")
        return 0

    batch = [(pid, summary) for pid, summary, _ in todo]
    try:
        translations = translate_panel_summaries(
            batch,
            api_key=api_key,
            model=model,
            base_url=base_url,
        )
    except Exception as batch_err:
        print(f"  batch translate failed ({batch_err}); retrying per panel", file=sys.stderr)
        translations = {}
        for pid, summary in batch:
            last_err: Exception | None = None
            for attempt in range(3):
                try:
                    translations.update(
                        translate_panel_summaries(
                            [(pid, summary)],
                            api_key=api_key,
                            model=model,
                            base_url=base_url,
                        )
                    )
                    last_err = None
                    break
                except Exception as e:
                    last_err = e
            if last_err is not None:
                raise last_err
    for pid, summary, panel in todo:
        en = translations[pid]
        panel["summary_en"] = en
        panel["summary_en_source"] = summary
    write_yaml(path, data)
    print(f"updated {len(todo)} panel(s): {path}")
    return len(todo)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="manga/pages/*.yaml の panels[].summary を英訳し summary_en を書き込む",
    )
    parser.add_argument(
        "novel_dir",
        type=Path,
        nargs="?",
        help="作品フォルダ（manga/pages を一括処理）",
    )
    parser.add_argument(
        "--manga-page",
        action="append",
        default=[],
        type=Path,
        help="単一ページ YAML（繰り返し可）",
    )
    parser.add_argument("--force", action="store_true", help="summary_en があるコマも再翻訳")
    parser.add_argument("--dry-run", action="store_true", help="API を呼ばず対象だけ表示")
    args = parser.parse_args(argv)

    root = repo_root()
    paths: list[Path] = [Path(p) for p in args.manga_page]
    if args.novel_dir:
        novel = args.novel_dir
        if not novel.is_absolute():
            novel = (root / novel).resolve()
        paths.extend(sorted((novel / "manga" / "pages").glob("*.yaml")))

    if not paths:
        parser.error("novel_dir または --manga-page を指定してください")

    api_key, model, base_url = resolve_translate_config(root)
    if not args.dry_run and not api_key:
        print(
            "error: OPENAI_API_KEY（または OPENROUTER + MONOCRI_SUMMARY_EN_PROVIDER=openrouter）が必要です",
            file=sys.stderr,
        )
        return 2

    total = 0
    for path in paths:
        if not path.is_absolute():
            path = (root / path).resolve()
        if not path.is_file():
            print(f"error: not found: {path}", file=sys.stderr)
            return 2
        try:
            total += process_page_file(
                path,
                api_key=api_key,
                model=model,
                base_url=base_url,
                force=bool(args.force),
                dry_run=bool(args.dry_run),
            )
        except Exception as exc:
            print(f"error: {path}: {exc}", file=sys.stderr)
            return 1

    if not args.dry_run:
        print(f"done: translated {total} panel(s) across {len(paths)} file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
