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

プロンプト組み立て（positive）:
  000〜099 番台:
    STYLE_PREFIX + prepend + fixed + danbooru_tags + append（カンマ連結）

  100番台かつ combines_with あり（_how_to.example/tag.md）:
    NovelAI: STYLE_PREFIX + 「資料タグ | combines_with 先の danbooru_tags」（パイプ）
    その他 provider: 000番台と同様に fixed + 資料 + 結合先をカンマ連結

  100番台で combines_with が無い場合は従来どおり fixed + 資料タグのみ。

prepend / append の指定（後勝ちではなく連結。重複は先勝ちで除去）:
  1. 作品 _meta.yaml の character_tag_batch
  2. tag/characters/<id>.yaml の tag_batch
  3. CLI --prepend-tags / --append-tags（その実行だけ）

negative は DEFAULT_NEGATIVE + prepend_negative + YAML negative_tags + append_negative。
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

_VARIANT_ID_NUM = re.compile(r"^(\d+)")

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


@dataclass(frozen=True)
class TagBatchLayers:
    """バッチ実行時にプロンプト前後へ挿入するタグ層。"""

    prepend_tags: tuple[str, ...] = ()
    append_tags: tuple[str, ...] = ()
    prepend_negative_tags: tuple[str, ...] = ()
    append_negative_tags: tuple[str, ...] = ()

    @staticmethod
    def empty() -> TagBatchLayers:
        return TagBatchLayers()

    def merge(self, other: TagBatchLayers) -> TagBatchLayers:
        """self のあとに other を連結（同キー内の順序を保つ）。"""
        return TagBatchLayers(
            prepend_tags=tuple(dedupe_tags([*self.prepend_tags, *other.prepend_tags])),
            append_tags=tuple(dedupe_tags([*self.append_tags, *other.append_tags])),
            prepend_negative_tags=tuple(
                dedupe_tags([*self.prepend_negative_tags, *other.prepend_negative_tags])
            ),
            append_negative_tags=tuple(
                dedupe_tags([*self.append_negative_tags, *other.append_negative_tags])
            ),
        )


def parse_tag_tokens(values: list[str] | None) -> list[str]:
    """CLI の nargs またはカンマ区切り1引数をタグ列に展開する。"""
    if not values:
        return []
    out: list[str] = []
    for raw in values:
        for part in str(raw).split(","):
            token = part.strip()
            if token:
                out.append(token)
    return out


def layers_from_mapping(data: object | None) -> TagBatchLayers:
    """_meta.yaml の character_tag_batch または character YAML の tag_batch。"""
    if not isinstance(data, dict):
        return TagBatchLayers.empty()

    def _list(key: str) -> tuple[str, ...]:
        raw = data.get(key) or []
        if not isinstance(raw, list):
            return ()
        return tuple(dedupe_tags(str(x) for x in raw))

    return TagBatchLayers(
        prepend_tags=_list("prepend_tags"),
        append_tags=_list("append_tags"),
        prepend_negative_tags=_list("prepend_negative_tags"),
        append_negative_tags=_list("append_negative_tags"),
    )


def load_novel_tag_batch_layers(novel_dir: Path) -> TagBatchLayers:
    from novel_meta_yaml import load_meta_yaml

    meta = load_meta_yaml(novel_dir)
    if not meta:
        return TagBatchLayers.empty()
    return layers_from_mapping(meta.get("character_tag_batch"))


def compose_positive_tags(
    fixed: list[str],
    danbooru: list[str],
    layers: TagBatchLayers,
) -> list[str]:
    return dedupe_tags([*layers.prepend_tags, *fixed, *danbooru, *layers.append_tags])


def compose_negative_prompt(
    base_negative: str,
    yaml_neg_extra: list[str],
    layers: TagBatchLayers,
) -> str:
    parts: list[str] = []
    if layers.prepend_negative_tags:
        parts.append(", ".join(layers.prepend_negative_tags))
    if base_negative.strip():
        parts.append(base_negative.strip())
    if yaml_neg_extra:
        parts.append(", ".join(dedupe_tags(yaml_neg_extra)))
    if layers.append_negative_tags:
        parts.append(", ".join(layers.append_negative_tags))
    return ", ".join(p for p in parts if p)


def load_character_yaml(yaml_path: Path) -> dict:
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{yaml_path}: ルートがオブジェクトではありません")
    if "character_id" not in data:
        raise ValueError(f"{yaml_path}: character_id が見つかりません")
    if "prompt_variants" not in data:
        raise ValueError(f"{yaml_path}: prompt_variants が見つかりません")
    return data


def reference_slot_number(variant_id: str) -> int | None:
    m = _VARIANT_ID_NUM.match((variant_id or "").strip())
    if not m:
        return None
    return int(m.group(1))


def is_reference_slot(variant_id: str) -> bool:
    n = reference_slot_number(variant_id)
    return n is not None and n >= 100


def variants_by_id(variants: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for v in variants:
        vid = str(v.get("variant_id") or "").strip()
        if vid:
            out[vid] = v
    return out


def base_fixed_tags_from(char: dict, variants: list[dict]) -> list[str]:
    """固定外見の正本は ``000_base`` の danbooru_tags（_how_to.example/tag.md）。"""
    from manga_prompt_ir.character_fixed_tags import base_fixed_tags_from as _base_fixed

    return _base_fixed(char, variants)


def danbooru_for_combines_with(
    variants: list[dict],
    combines_with: str,
    char: dict | None = None,
) -> list[str]:
    ref = variants_by_id(variants).get(combines_with.strip())
    if not ref:
        known = ", ".join(sorted(variants_by_id(variants)))
        raise ValueError(
            f"combines_with={combines_with!r} が prompt_variants にありません。"
            f" 既存: {known or '(なし)'}"
        )
    target = list(ref.get("danbooru_tags") or [])
    if char is not None:
        base = base_fixed_tags_from(char, variants)
        return dedupe_tags([*base, *target])
    return target


def compose_job_prompt(
    char: dict,
    variant: dict,
    variants: list[dict],
    job_layers: TagBatchLayers,
    *,
    use_novelai_pipe: bool,
) -> str:
    """1ジョブ分の positive プロンプト（STYLE_PREFIX 込み）。"""
    base_fixed = base_fixed_tags_from(char, variants)
    danbooru: list[str] = list(variant.get("danbooru_tags") or [])
    vid = str(variant.get("variant_id") or "")
    combines_raw = variant.get("combines_with")
    combines = str(combines_raw).strip() if combines_raw else ""

    if combines and is_reference_slot(vid):
        right_tags = danbooru_for_combines_with(variants, combines, char)
        if use_novelai_pipe:
            from image_provider_novel_manga_batch import join_novelai_pipe_tag_line

            left_tags = compose_positive_tags([], danbooru, job_layers)
            body = join_novelai_pipe_tag_line(left_tags, [right_tags])
            return STYLE_PREFIX + body
        merged = compose_positive_tags([], [*danbooru, *right_tags], job_layers)
        return STYLE_PREFIX + ", ".join(merged)

    if combines:
        right_tags = danbooru_for_combines_with(variants, combines, char)
        merged = compose_positive_tags([], [*danbooru, *right_tags], job_layers)
        return STYLE_PREFIX + ", ".join(merged)

    all_tags = compose_positive_tags(base_fixed, danbooru, job_layers)
    return STYLE_PREFIX + ", ".join(all_tags)


def iter_tag_jobs(
    novel_dir: Path,
    only_char: set[str] | None,
    variant_ids: set[str] | None,
    novel_layers: TagBatchLayers | None = None,
    cli_layers: TagBatchLayers | None = None,
    *,
    use_novelai_pipe: bool = False,
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

    base_layers = (novel_layers or TagBatchLayers.empty()).merge(
        cli_layers or TagBatchLayers.empty()
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

        char_layers = layers_from_mapping(char.get("tag_batch"))
        job_layers = base_layers.merge(char_layers)
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

            try:
                prompt = compose_job_prompt(
                    char,
                    v,
                    variants,
                    job_layers,
                    use_novelai_pipe=use_novelai_pipe,
                )
            except ValueError as e:
                print(
                    f"warning: {char_id}/{vid} を読み飛ばし ({e})",
                    file=sys.stderr,
                )
                continue
            prefix = f"{char_id}_{vid}"
            output_dir = (novel_dir / "tag" / char_id).as_posix()

            jobs.append({
                "char_id": char_id,
                "variant_id": vid,
                "prefix": prefix,
                "prompt": prompt,
                "neg_extra": neg_extra,
                "tag_layers": job_layers,
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
    p.add_argument(
        "--workflow",
        default=None,
        metavar="ID",
        help=(
            "作品 _meta.yaml の workflows セクションに登録した名前付きレシピ ID。"
            " novelai_portion_id / strength / information_extracted を適用する。"
            " 利用可能な ID は --list-workflows で確認できる"
        ),
    )
    p.add_argument(
        "--list-workflows",
        action="store_true",
        help="作品 _meta.yaml に登録された workflows 一覧を表示して終了",
    )
    p.add_argument(
        "--prepend-tags",
        nargs="*",
        default=None,
        metavar="TAG",
        help=(
            "全ジョブの positive 先頭へ追加（fixed より前）。"
            "カンマ区切り1引数可。例: --prepend-tags solo simple_background"
        ),
    )
    p.add_argument(
        "--append-tags",
        nargs="*",
        default=None,
        metavar="TAG",
        help="全ジョブの positive 末尾へ追加（danbooru_tags の後）",
    )
    p.add_argument(
        "--prepend-negative-tags",
        nargs="*",
        default=None,
        metavar="TAG",
        help="negative 先頭へ追加（--negative-prompt より前）",
    )
    p.add_argument(
        "--append-negative-tags",
        nargs="*",
        default=None,
        metavar="TAG",
        help="negative 末尾へ追加（YAML negative_tags の後）",
    )
    p.add_argument(
        "--novelai-portion-id",
        default=None,
        metavar="ID",
        help="NovelAI ポーション ID（_meta.yaml の novelai.portions）。none で参照なし。--workflow より CLI が優先",
    )
    p.add_argument(
        "--novelai-reference-strength",
        type=float,
        default=None,
        metavar="FLOAT",
        help="NovelAI Vibe strength 乗数（例: 0.5）。--workflow より CLI が優先",
    )
    p.add_argument(
        "--novelai-reference-information-extracted",
        type=float,
        default=None,
        metavar="FLOAT",
        help="NovelAI information_extracted 乗数。--workflow より CLI が優先",
    )
    args = p.parse_args(argv)

    root = repo_root()
    novel = args.novel_dir
    if not novel.is_absolute():
        novel = (root / novel).resolve()
    if not novel.is_dir():
        print(f"error: ディレクトリがありません: {novel}", file=sys.stderr)
        return 2

    from novel_meta_yaml import list_workflows, resolve_workflow  # noqa: E402

    if args.list_workflows:
        wfs = list_workflows(novel)
        if not wfs:
            print("(workflows が _meta.yaml に未登録です)", file=sys.stderr)
            return 0
        for wid, entry in wfs.items():
            label = (entry or {}).get("label", "")
            print(f"{wid}\t{label}")
        return 0

    novelai_portion_id = args.novelai_portion_id
    novelai_ref_strength = args.novelai_reference_strength
    novelai_ref_ie = args.novelai_reference_information_extracted

    if args.workflow:
        try:
            wf = resolve_workflow(novel, args.workflow)
        except (FileNotFoundError, ValueError, KeyError) as e:
            print(f"error: --workflow: {e}", file=sys.stderr)
            return 2
        if novelai_portion_id is None and wf.get("novelai_portion_id"):
            novelai_portion_id = str(wf["novelai_portion_id"])
        if novelai_ref_strength is None and wf.get("strength") is not None:
            novelai_ref_strength = float(wf["strength"])
        if novelai_ref_ie is None and wf.get("information_extracted") is not None:
            novelai_ref_ie = float(wf["information_extracted"])
        print(f"workflow={args.workflow!r} を適用しました", file=sys.stderr)

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

    novel_layers = load_novel_tag_batch_layers(novel)
    cli_layers = TagBatchLayers(
        prepend_tags=tuple(parse_tag_tokens(args.prepend_tags)),
        append_tags=tuple(parse_tag_tokens(args.append_tags)),
        prepend_negative_tags=tuple(parse_tag_tokens(args.prepend_negative_tags)),
        append_negative_tags=tuple(parse_tag_tokens(args.append_negative_tags)),
    )
    run_layers = novel_layers.merge(cli_layers)

    try:
        jobs = iter_tag_jobs(
            novel,
            only_char,
            variant_ids,
            novel_layers=novel_layers,
            cli_layers=cli_layers,
            use_novelai_pipe=(provider == "novelai"),
        )
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

    from image_provider_novel_manga_batch import (  # noqa: E402
        novelai_reference_job_fields,
        resolve_novelai_reference,
    )

    try:
        novelai_ref = resolve_novelai_reference(
            [],
            root,
            novel_dir=novel,
            portion_id=novelai_portion_id,
            cli_strength=novelai_ref_strength,
            cli_information_extracted=novelai_ref_ie,
        )
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    novelai_ref_fields = novelai_reference_job_fields(
        novelai_ref.paths if provider == "novelai" else [],
        strength=novelai_ref.strength,
        information_extracted=novelai_ref.information_extracted,
        root=root,
    )

    print(f"novel : {novel}")
    print(f"provider: {provider}")
    print(f"jobs  : {len(jobs)}")
    if run_layers.prepend_tags:
        print(f"prepend_tags: {', '.join(run_layers.prepend_tags)}")
    if run_layers.append_tags:
        print(f"append_tags: {', '.join(run_layers.append_tags)}")
    if run_layers.prepend_negative_tags or run_layers.append_negative_tags:
        print(
            "negative layers: "
            f"prepend={list(run_layers.prepend_negative_tags)!r} "
            f"append={list(run_layers.append_negative_tags)!r}"
        )
    if args.workflow:
        print(f"workflow: {args.workflow}")
    if novelai_ref.paths:
        print(
            f"novelai_reference: {len(novelai_ref.paths)} file(s) "
            f"(source={novelai_ref.source})"
        )
        print(
            f"  strength_multiplier={novelai_ref.strength} "
            f"ie_multiplier={novelai_ref.information_extracted}"
        )
        if novelai_ref_fields:
            rs = novelai_ref_fields.get("reference_strength_multiple", [])
            ri = novelai_ref_fields.get("reference_information_extracted_multiple", [])
            if rs:
                print(f"  reference_strength_multiple={rs}")
            if ri:
                print(f"  reference_information_extracted_multiple={ri}")

    for job in jobs:
        job_layers: TagBatchLayers = job["tag_layers"]
        negative = compose_negative_prompt(
            args.negative_prompt,
            job["neg_extra"],
            job_layers,
        )

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
        if novelai_ref_fields:
            payload.update(novelai_ref_fields)

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
