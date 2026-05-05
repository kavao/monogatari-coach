#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
作品フォルダの tag/characters/*.yaml から prompt_variants の danbooru_tags を読み込み、
画像生成 API を連続実行する。

YAML IR（manga-prompt-ir スキル）を正本として使う。
Markdown（tag/<romaji>.md）は参照しない。

実装: 各ジョブは tools/image_provider_generate.py を子プロセスで呼び出す（provider は CLI / .env /
config/image_generation.json で解決）。

前提:
- Forge: WebUI/Forge を --api 付きで起動し、config/image_generation.json の
  providers.forge.base_url が指す先に疎通できること
- NovelAI / Grok: リポジトリ直下の .env に各 auth_env が入っていること
- PyYAML: pip install pyyaml

YAML の推奨書式: manga-prompt-ir スキル（.rulesync/skills/manga-prompt-ir/）の
schemas/character.py と examples/character.yaml を参照。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    import yaml
except ImportError:
    print("error: PyYAML が必要です。pip install pyyaml", file=sys.stderr)
    sys.exit(2)

PROVIDER_CHOICES = ("forge", "novelai", "grok", "grok_pro", "openrouter")
_GROK_FAMILY = frozenset({"grok", "grok_pro"})
TAG_PROVIDER_ENV = "MONOCRI_CHARACTER_TAG_PROVIDER_DEFAULT"

STYLE_PREFIX = (
    "best quality, very aesthetic, ultra-detailed, best illustration, "
)

DEFAULT_NEGATIVE = (
    "lowres, worst quality, jpeg artifacts, blurry, bad hands, bad anatomy, "
    "extra fingers, watermark, username, text, logo"
)


# ---------------------------------------------------------------------------
# 設定・プロバイダ解決
# ---------------------------------------------------------------------------

def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_dotenv(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path.is_file():
        return env
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if not key:
            continue
        if value.startswith(("'", '"')) and value.endswith(("'", '"')) and len(value) >= 2:
            value = value[1:-1]
        env[key] = value
    return env


def load_root_config(root: Path) -> dict:
    cfg_path = root / "config" / "image_generation.json"
    if not cfg_path.is_file():
        raise FileNotFoundError(f"config/image_generation.json が見つかりません: {cfg_path}")
    raw = load_json(cfg_path)
    if not isinstance(raw, dict):
        raise ValueError(f"{cfg_path} は JSON オブジェクトである必要があります")
    if not isinstance(raw.get("providers"), dict):
        raise ValueError(f"{cfg_path} の providers はオブジェクトである必要があります")
    return raw


def validate_provider(provider: str, *, source: str) -> str:
    n = provider.strip().lower()
    if n not in PROVIDER_CHOICES:
        raise ValueError(
            f"{source} の provider {provider!r} は未対応。"
            f"available: {', '.join(PROVIDER_CHOICES)}"
        )
    return n


def resolve_batch_provider(root: Path, args_provider: str | None) -> str:
    if args_provider:
        return validate_provider(args_provider, source="CLI --provider")
    dotenv_map = load_dotenv(root / ".env")
    env_provider = dotenv_map.get(TAG_PROVIDER_ENV)
    if env_provider:
        return validate_provider(env_provider, source=f".env {TAG_PROVIDER_ENV}")
    root_cfg = load_root_config(root)
    return validate_provider(
        str(root_cfg.get("default_provider", "forge")),
        source="config default_provider",
    )


# ---------------------------------------------------------------------------
# YAML 読み込み・プロンプト構築
# ---------------------------------------------------------------------------

def dedupe_tags(tags: list[str]) -> list[str]:
    """順序を保ちつつ重複・空白を除去する。"""
    return list(dict.fromkeys(t.strip() for t in tags if t and t.strip()))


def load_character_yaml(yaml_path: Path) -> dict:
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{yaml_path}: ルートがオブジェクトではありません")
    if "character_id" not in data:
        raise ValueError(f"{yaml_path}: character_id が見つかりません")
    if "prompt_variants" not in data:
        raise ValueError(f"{yaml_path}: prompt_variants が見つかりません")
    return data


def fixed_tags_from(char: dict) -> list[str]:
    """
    character_tags + costume.outfit_tags + manga_rules.consistency_tags
    + appearance.species_features + appearance.distinctive_features を結合して返す。
    schemas/character.py の fixed_prompt_tags() 相当。
    """
    tags: list[str] = []
    tags.extend(char.get("character_tags") or [])
    costume = char.get("costume") or {}
    tags.extend(costume.get("outfit_tags") or [])
    manga_rules = char.get("manga_rules") or {}
    tags.extend(manga_rules.get("consistency_tags") or [])
    appearance = char.get("appearance") or {}
    tags.extend(appearance.get("species_features") or [])
    tags.extend(appearance.get("distinctive_features") or [])
    return tags


def iter_tag_jobs(
    novel_dir: Path,
    only_char: set[str] | None,
    variant_ids: set[str] | None,
) -> list[dict]:
    """
    tag/characters/*.yaml を走査してジョブリストを返す。

    job keys:
      char_id, variant_id, prefix, prompt, neg_extra (list[str]), output_dir
    """
    char_dir = novel_dir / "tag" / "characters"
    if not char_dir.is_dir():
        raise FileNotFoundError(
            f"tag/characters/ がありません: {char_dir}\n"
            "ヒント: YAML IR がまだ作成されていない場合は manga-prompt-ir スキルを参照してください"
        )

    yaml_files = sorted(char_dir.glob("*.yaml"))
    if not yaml_files:
        raise FileNotFoundError(
            f"tag/characters/ に .yaml ファイルがありません: {char_dir}"
        )

    jobs: list[dict] = []
    for yaml_path in yaml_files:
        try:
            char = load_character_yaml(yaml_path)
        except (ValueError, yaml.YAMLError) as e:
            print(f"warning: {yaml_path.name} を読み飛ばし ({e})", file=sys.stderr)
            continue

        char_id: str = char["character_id"]
        if only_char and char_id not in only_char:
            continue

        fixed = fixed_tags_from(char)
        neg_extra: list[str] = char.get("negative_tags") or []
        variants: list[dict] = char.get("prompt_variants") or []

        if not variants:
            print(f"warning: {char_id} に prompt_variants がありません。スキップ", file=sys.stderr)
            continue

        for v in variants:
            vid: str = v.get("variant_id") or ""
            if not vid:
                print(f"warning: {char_id} のバリアントに variant_id がありません。スキップ", file=sys.stderr)
                continue
            if variant_ids and vid not in variant_ids:
                continue

            danbooru: list[str] = v.get("danbooru_tags") or []
            all_tags = dedupe_tags(fixed + danbooru)
            prompt = STYLE_PREFIX + ", ".join(all_tags)
            prefix = f"{char_id}_{vid}"
            output_dir = (novel_dir / "tag" / char_id).as_posix()

            jobs.append({
                "char_id": char_id,
                "variant_id": vid,
                "prefix": prefix,
                "prompt": prompt,
                "neg_extra": neg_extra,
                "output_dir": output_dir,
            })

    return jobs


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="tag/characters/*.yaml の prompt_variants を画像化する（YAML IR 直読み）"
    )
    p.add_argument(
        "novel_dir",
        type=Path,
        help="作品フォルダ（例: novels/051_タイトル）",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="生成せず抽出ジョブだけ表示する",
    )
    p.add_argument(
        "--negative-prompt",
        default=DEFAULT_NEGATIVE,
        help="ベースの negative_prompt（YAML の negative_tags はここに追加される）",
    )
    p.add_argument(
        "--provider",
        choices=PROVIDER_CHOICES,
        default=None,
        help=(
            "生成プロバイダ。未指定時は .env の "
            f"{TAG_PROVIDER_ENV}、無ければ config/image_generation.json の "
            "default_provider を使う"
        ),
    )
    p.add_argument(
        "--aspect-ratio",
        default=None,
        help="比率 preset 名または比率文字列（例: portrait, 3:4）",
    )
    p.add_argument(
        "--resolution",
        default=None,
        help="Grok 用解像度（例: 1k, 2k）",
    )
    p.add_argument(
        "--only-char",
        nargs="*",
        default=None,
        metavar="CHAR_ID",
        help=(
            "絞り込む character_id（例: --only-char kazuki）。"
            "複数可。未指定なら tag/characters/ の全 YAML を処理する。"
        ),
    )
    p.add_argument(
        "--variant-id",
        nargs="*",
        default=None,
        metavar="VARIANT_ID",
        help=(
            "絞り込む variant_id（例: --variant-id normal battle）。"
            "複数可。未指定なら全バリアントを処理する。"
        ),
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
        provider = resolve_batch_provider(root, args.provider)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    only_char = (
        {s.strip() for s in args.only_char if s and str(s).strip()}
        if args.only_char else None
    )
    variant_ids = (
        {s.strip() for s in args.variant_id if s and str(s).strip()}
        if args.variant_id else None
    )

    try:
        jobs = iter_tag_jobs(novel, only_char, variant_ids)
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    if not jobs:
        print(
            "error: 生成ジョブが 0 件でした\n"
            "ヒント: --only-char / --variant-id の指定、または YAML の内容を確認してください",
            file=sys.stderr,
        )
        return 2

    provider_cli = root / "tools" / "image_provider_generate.py"
    if not provider_cli.is_file():
        print(f"error: {provider_cli} がありません", file=sys.stderr)
        return 2

    print(f"novel : {novel}")
    print(f"provider: {provider}")
    print(f"jobs  : {len(jobs)}")

    for job in jobs:
        neg_parts = [args.negative_prompt]
        if job["neg_extra"]:
            neg_parts.append(", ".join(job["neg_extra"]))
        negative = ", ".join(filter(None, neg_parts))

        payload = {
            "provider": provider,
            "prompt": job["prompt"],
            "negative_prompt": negative,
            "output_dir": job["output_dir"],
            "file_prefix": job["prefix"],
            "count": 1,
            "seed": None,
        }
        if args.aspect_ratio is not None:
            payload["aspect_ratio_preset"] = args.aspect_ratio
        if args.resolution is not None:
            payload["resolution"] = args.resolution

        if args.dry_run:
            print(f"  [{job['prefix']}] -> {job['output_dir']}")
            print(f"    prompt[:120]: {payload['prompt'][:120]}...")
            continue

        (novel / "tag" / job["char_id"]).mkdir(parents=True, exist_ok=True)

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
                [sys.executable, str(provider_cli), "--params", str(tf_path), "--json"],
                cwd=str(root),
                capture_output=True,
                text=True,
            )
        finally:
            tf_path.unlink(missing_ok=True)

        if r.returncode != 0:
            print(r.stderr or r.stdout, file=sys.stderr)
            print(
                f"error: 生成失敗 ({job['prefix']}) code={r.returncode}",
                file=sys.stderr,
            )
            return r.returncode or 1

        print(r.stdout.strip())

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
