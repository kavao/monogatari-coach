#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
作品フォルダの manga/pages/*.yaml または manga/manga_*.md から、各 Page の Step1 / Step2 相当を抽出し、
画像生成プロバイダへ連続実行する。

保存先:
  - コマ・ページ（step1-panels / step1-pages / step2-pages）: manga/_assets/<manga_stem>/comic/
  - 背景資料（background-concepts）: manga/_assets/<manga_stem>/backgrounds/
  file_prefix は <stem>_p<page>_k<koma> 等。
  --subdir-by-page 指定時は comic/p<page>/ に保存（任意。推奨運用は comic/ 直下のみ）。
  novel_image_layout の k01.. は「1ページ内のコマ用スロット」用の任意フォルダで、本スクリプト既定では未使用。
前提: config/image_generation.json・各 provider の準備完了（tools/image_provider_generate.py と同じ）

`tag/*.md` からのキャラ固定特徴の自動注入は、**`--no-character-anchors`** で無効化できる（NovelAI 等でポリシー拒否が出るとき、step1 の `tag:` だけを送りたいとき）。

YAML 入力・**step1-panels**（コマ単位）時は、各コマの `negative_prompt` を
`--negative-prompt` + `technical.negative_tags` + `panels[].negative_tags` から合成し、
`panels[].omit_negative_tags` に列挙した断片を合成前の集合から除去する（split screen の出し分け等）。

**`--omit-panel-background`**（`MONOCRI_MANGA_STEP1_OMIT_PANEL_BACKGROUND=1` でも可）:
step1-panels 向けに、舞台・背景・照明・場所タグをプロンプトから外し、
`simple_background` 等を足して背景資料と合成しやすいコマ絵を狙う。
"""

from __future__ import annotations

import argparse
import os
import json
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml

_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))


def _safe_print_stdout(text: str) -> None:
    """Windows cp932 等で image provider の stdout に含まれる文字が print できず落ちるのを防ぐ。"""
    if not text:
        return
    try:
        print(text)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "utf-8"
        print(text.encode(enc, errors="backslashreplace").decode(enc))
from manga_prompt_ir.scene_prompt import (
    camera_tag_tokens,
    composition_layout_tag_token,
    composition_tag_tokens,
    lighting_tag_tokens,
    panel_mood_atmosphere_tag_tokens,
    scene_prompt_background_notes,
    scene_prompt_location_time_weather,
    subject_situational_tag_tokens,
    subject_tag_line_token,
)
from manga_prompt_ir.summary_en import panel_summary_en_tag_tokens
from manga_prompt_ir.color_mode import (
    VALID_COLOR_MODES,
    page_color_mode_label,
)
from manga_prompt_ir.user_directives import (
    apply_to_tags as apply_user_directives_to_tags,
    omit_tags_for_panel as user_directives_omit_tags,
)
from manga_prompt_ir.prompt_formatters import (
    NATIVE_NEGATIVE,
    NOVELAI_PIPE,
    TAG_CSV,
    format_background_prompt,
    format_manga_panel_prompt,
    format_manga_page_prompt,
    provider_config_from_root,
    resolve_prompt_formatter,
)

PROVIDER_CHOICES = ("forge", "novelai", "grok", "grok_pro", "openai", "openrouter")
_GROK_FAMILY = frozenset({"grok", "grok_pro"})
INPUT_CHOICES = ("yaml", "markdown")
MANGA_ASSET_SUBDIR_BACKGROUND = "backgrounds"
MANGA_ASSET_SUBDIR_COMIC = "comic"
MANGA_STEP1_PROVIDER_ENV = "MONOCRI_MANGA_STEP1_PROVIDER_DEFAULT"
MANGA_STEP1_OMIT_PANEL_BACKGROUND_ENV = "MONOCRI_MANGA_STEP1_OMIT_PANEL_BACKGROUND"
MANGA_STEP1_INCLUDE_PANEL_SUMMARY_ENV = "MONOCRI_MANGA_STEP1_INCLUDE_PANEL_SUMMARY"
MANGA_NOVELAI_REFERENCE_PATHS_ENV = "MONOCRI_MANGA_NOVELAI_REFERENCE_IMAGE_PATHS"
MANGA_NOVELAI_REFERENCE_STRENGTH_ENV = "MONOCRI_MANGA_NOVELAI_REFERENCE_STRENGTH"
MANGA_NOVELAI_REFERENCE_IE_ENV = "MONOCRI_MANGA_NOVELAI_REFERENCE_INFORMATION_EXTRACTED"

# step1-panels + --omit-panel-background: 背景・舞台タグの除去と簡素背景の付与
OMIT_PANEL_BACKGROUND_ADD_TAGS = [
    "simple_background",
    "white_background",
    "plain_background",
    "depth_of_field",
    "blurry_background",
    "soft_lighting",
]
OMIT_PANEL_BACKGROUND_NEGATIVE_FRAGMENTS = [
    "detailed_background",
    "scenery",
    "landscape",
    "architecture",
    "interior",
    "room",
    "bathroom",
    "background",
]
BACKGROUND_PROMPT_TAG_SUBSTRINGS = (
    "bathroom",
    "bathtub",
    "bath tub",
    "tile",
    "tiles",
    "porcelain",
    "grout",
    "steam",
    "fog",
    "mist",
    "humid",
    "interior",
    "scenery",
    "landscape",
    "architecture",
    "hallway",
    "door frame",
    "ceiling",
    "floor tile",
    "wall tile",
    "renovated",
    "family bathroom",
    "cream beige",
    "gray beige",
    "warm gray",
    "brushed nickel",
    "fixture",
    "faucet",
    "shower",
    "wall sconce",
    "crescent moon",
    "moon lamp",
    "amber glow",
    "hallway light",
    "led light",
    "establishing",
    "onsen",
    "hot spring",
    "water surface",
    "splashing water",
)
MANGA_STEP1_PAGES_PROVIDER_ENV = "MONOCRI_MANGA_STEP1_PAGES_PROVIDER_DEFAULT"
MANGA_STEP2_PROVIDER_ENV = "MONOCRI_MANGA_STEP2_PROVIDER_DEFAULT"
MANGA_BACKGROUND_PROVIDER_ENV = "MONOCRI_MANGA_BACKGROUND_PROVIDER_DEFAULT"
# 漫画バッチのみ。CLI --aspect-ratio 未指定かつ provider=grok_pro のとき、
# config の default_aspect_ratio（多くは 1:1）の代わりに使う。
MANGA_GROK_PRO_DEFAULT_ASPECT_ENV = "MONOCRI_MANGA_GROK_PRO_DEFAULT_ASPECT_RATIO"
# grok_pro で CLI・.env とも未指定のとき（config の default_aspect_ratio 1:1 回避）
MANGA_GROK_PRO_ASPECT_FALLBACK = "manga_b5_portrait"


def dotenv_or_env(root: Path, name: str) -> str | None:
    value = os.environ.get(name)
    if value and value.strip():
        return value.strip()
    dotenv_map = load_dotenv(root / ".env")
    value = dotenv_map.get(name)
    if value and value.strip():
        return value.strip()
    return None


def manga_grok_pro_effective_aspect_ratio(
    cli_aspect: str | None, provider: str, *, root: Path | None = None
) -> str | None:
    """CLI が優先。未指定かつ grok_pro のとき .env → 環境変数 → manga_b5_portrait。"""
    if cli_aspect is not None:
        return cli_aspect
    if provider != "grok_pro":
        return None
    raw = dotenv_or_env(root, MANGA_GROK_PRO_DEFAULT_ASPECT_ENV) if root is not None else None
    if not raw:
        raw = (os.environ.get(MANGA_GROK_PRO_DEFAULT_ASPECT_ENV) or "").strip()
    return raw or MANGA_GROK_PRO_ASPECT_FALLBACK


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def resolve_manga_assets_stem_dir(manga_dir: Path, stem: str) -> Path:
    return (manga_dir / "_assets" / stem).resolve()


def resolve_manga_comic_output_dir(manga_dir: Path, stem: str) -> Path:
    return resolve_manga_assets_stem_dir(manga_dir, stem) / MANGA_ASSET_SUBDIR_COMIC


STYLE_PREFIX = (
    "best quality, very aesthetic, ultra-detailed, best illustration, "
)

DEFAULT_NEGATIVE = (
    "lowres, worst quality, jpeg artifacts, blurry, bad hands, bad anatomy, "
    "extra fingers, watermark, username, text, logo"
)

STEP2_GROK_STYLE_HELPER = """\
画風補助:
- 日本の商業漫画風
- 読みやすいコマ割りと明快な視線誘導
- キャラクターの顔は安定して描写
- 背景は情報量を保ちつつ主役を邪魔しない
- 各コマの役割差が一目で分かる
- 吹き出しや文字は必要最小限で、絵として破綻しない構成
- ページ全体を1枚で完成させ、裁ち切れやコマ欠けを避ける
"""

STEP1_PAGE_GROK_STYLE_HELPER = """\
画風補助:
- 日本の商業漫画風
- 各コマ情報をなるべく落とさず精密に反映
- 各コマの人物、表情、構図、背景、距離感の差を明確に描き分ける
- コマごとの役割差が伝わるように密度と抜きを作る
- 吹き出しや文字は必要最小限で、絵として破綻しない構成
- ページ全体を1枚で完成させ、裁ち切れやコマ欠けを避ける
"""


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_yaml(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"YAML root must be a mapping: {path}")
    return data


def as_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def normalize_tag(value) -> str:
    return str(value).strip().replace(" ", "_")


def join_tags(values: list) -> str:
    return ", ".join(unique([normalize_tag(value) for value in values if value]))


def join_novelai_pipe_tag_line(base: list[str], character_segments: list[list[str]]) -> str:
    """NovelAI 向け ``ベース | キャラA | キャラB | …`` の1行に連結する。"""
    parts: list[str] = []
    b = join_tags(base)
    if b:
        parts.append(b)
    for seg in character_segments:
        s = join_tags(seg)
        if s:
            parts.append(s)
    return " | ".join(parts)


def split_comma_phrases(value) -> list[str]:
    """カンマ区切りの1本の文字列を、空でない断片のリストにする（ネガ・ポジ両方で再利用）。"""
    if value is None:
        return []
    text = str(value).strip()
    if not text:
        return []
    return [part.strip() for part in text.split(",") if part.strip()]


def merge_panel_negative_prompt(
    cli_default: str,
    technical_tags: list,
    panel_extra: list,
    omit_tags: list,
) -> str:
    """
    コマ単位生成向け: CLI の negative_prompt + technical.negative_tags に対し、
    omit_negative_tags で断片を除去し、最後に panels[].negative_tags を追加（順序保持・重複除去）。
    omit は normalize_tag 済みキーまたは原文の lower で一致した断片を落とす。
    """
    parts: list[str] = []
    parts.extend(split_comma_phrases(cli_default))
    parts.extend(str(x).strip() for x in as_list(technical_tags) if x)
    omit_keys = set()
    for o in as_list(omit_tags):
        if not o:
            continue
        s = str(o).strip()
        if not s:
            continue
        omit_keys.add(normalize_tag(s))
        omit_keys.add(s.lower())
    filtered: list[str] = []
    for p in parts:
        if normalize_tag(p) in omit_keys or p.strip().lower() in omit_keys:
            continue
        filtered.append(p)
    filtered.extend(str(x).strip() for x in as_list(panel_extra) if x)
    seen: set[str] = set()
    out: list[str] = []
    for p in filtered:
        key = normalize_tag(p)
        if key in seen:
            continue
        seen.add(key)
        out.append(p.strip())
    return ", ".join(out)


def comma_split_tags(value) -> list[str]:
    """Comma-separated prompt fragments (e.g. scene.background_notes) → tag tokens."""
    if value is None:
        return []
    text = str(value).strip()
    if not text:
        return []
    return [part.strip() for part in text.split(",") if part.strip()]


def load_dotenv(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path.is_file():
        return env
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if value.startswith(("'", '"')) and value.endswith(("'", '"')) and len(value) >= 2:
            value = value[1:-1]
        env[key] = value
    return env


def load_root_config(root: Path) -> dict:
    cfg_path = root / "config" / "image_generation.json"
    if not cfg_path.is_file():
        raise FileNotFoundError(
            f"config/image_generation.json が見つかりません: {cfg_path}"
        )
    raw = load_json(cfg_path)
    if not isinstance(raw, dict):
        raise ValueError(f"{cfg_path} は JSON オブジェクトである必要があります")
    if "providers" in raw:
        if not isinstance(raw.get("providers"), dict):
            raise ValueError(f"{cfg_path} の providers はオブジェクトである必要があります")
        return raw
    raise ValueError(
        f"{cfg_path} は providers キーを持つ image_generation 形式である必要があります"
    )


def validate_provider(provider: str, *, source: str) -> str:
    normalized = provider.strip().lower()
    if normalized not in PROVIDER_CHOICES:
        allowed = ", ".join(PROVIDER_CHOICES)
        raise ValueError(
            f"{source} の provider {provider!r} は未対応です。available: {allowed}"
        )
    return normalized


def resolve_batch_provider(root: Path, source: str, args_provider: str | None) -> str:
    if args_provider:
        return validate_provider(args_provider, source="CLI --provider")
    dotenv_map = load_dotenv(root / ".env")
    if source == "background-concepts":
        env_name = MANGA_BACKGROUND_PROVIDER_ENV
    elif source == "step2-pages":
        env_name = MANGA_STEP2_PROVIDER_ENV
    elif source == "step1-pages":
        env_name = MANGA_STEP1_PAGES_PROVIDER_ENV
    else:
        env_name = MANGA_STEP1_PROVIDER_ENV
    env_provider = dotenv_map.get(env_name)
    if env_provider:
        return validate_provider(env_provider, source=f".env {env_name}")
    if source == "background-concepts":
        return validate_provider("grok", source=f"{source} default")
    if source in ("step1-pages", "step2-pages"):
        return validate_provider("grok_pro", source=f"{source} default")
    root_cfg = load_root_config(root)
    return validate_provider(
        str(root_cfg.get("default_provider", "forge")),
        source="config default_provider",
    )


def normalize_tag_body(raw: str) -> str:
    s = raw.strip()
    s = re.sub(r"\s+", " ", s)
    return s


def normalize_step2_block(raw: str) -> str:
    lines = [ln.rstrip() for ln in raw.strip().splitlines()]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines).strip()


def extract_keywords(text: str) -> list[str]:
    cleaned = text.lower()
    tokens: list[str] = []
    tokens.extend(re.findall(r"[a-z][a-z0-9_-]{2,}", cleaned))
    tokens.extend(re.findall(r"[βa-zA-Zァ-ン一-龯ぁ-ん][βa-zA-Z0-9ァ-ン一-龯ぁ-んー_-]{1,}", text))
    stopwords = {
        "danbooru",
        "tags",
        "caption",
        "和訳",
        "説明",
        "fantasy",
        "realistic",
        "standing",
        "adult",
        "appearance",
        "situation",
        "scene",
        "manga",
        "panel",
        "style",
    }
    seen: set[str] = set()
    result: list[str] = []
    expanded: list[str] = []
    for token in tokens:
        expanded.append(token)
        if token.endswith("時") and len(token) >= 3:
            expanded.append(token[:-1])
        expanded.extend(
            part for part in re.split(r"[のへでをがにと、。・\s]+", token) if len(part) >= 2
        )
    for token in expanded:
        normalized = token.lower()
        if normalized in stopwords:
            continue
        if normalized not in seen:
            seen.add(normalized)
            result.append(token)
    return result


def split_display_aliases(display: str) -> list[str]:
    aliases: list[str] = []
    for part in re.split(r"[（(]", display):
        cleaned = re.sub(r"[)）].*$", "", part).strip()
        if cleaned:
            aliases.append(cleaned)
    return aliases


def expand_aliases(display: str) -> list[str]:
    aliases = split_display_aliases(display)
    expanded: list[str] = []
    for alias in aliases:
        expanded.append(alias)
        if re.search(r"[一-龯ぁ-んァ-ン]", alias):
            for n in (2, 3, 4):
                if len(alias) > n:
                    expanded.append(alias[-n:])
    # preserve order and uniqueness
    seen: set[str] = set()
    result: list[str] = []
    for alias in expanded:
        if alias not in seen:
            seen.add(alias)
            result.append(alias)
    return result


def parse_tag_anchor(tag_path: Path) -> dict[str, object] | None:
    text = tag_path.read_text(encoding="utf-8")
    name_match = re.search(r"(?m)^([^\n]+(?:（[^）]+）)?)\s*$", text)
    if not name_match:
        return None
    display = name_match.group(1).strip()
    if display.startswith("#") or "共通推奨スタイルタグ" in display:
        candidates = re.findall(r"(?m)^([^\n#].*?)(?:\r?\n\r?\n1\.\s*通常時)", text)
        if not candidates:
            return None
        display = candidates[0].strip()
    variants = []
    section_iter = re.finditer(
        r"(?is)(\d+)\.\s*([^\n]+)\r?\n説明:\s*(.*?)\r?\n\r?\nDanbooru Tags:\s*\r?\n([^\n]+)",
        text,
    )
    for match in section_iter:
        title = match.group(2).strip()
        description = normalize_step2_block(match.group(3))
        danbooru = normalize_tag_body(match.group(4))
        if not danbooru:
            continue
        variants.append(
            {
                "index": int(match.group(1)),
                "title": title,
                "description": description,
                "danbooru": danbooru,
                "keywords": extract_keywords(f"{title}\n{description}"),
            }
        )
    if not variants:
        return None
    default_variant = variants[0]
    return {
        "key": tag_path.stem,
        "display": display,
        "aliases": expand_aliases(display),
        "danbooru": default_variant["danbooru"],
        "variants": variants,
    }


def load_character_anchors(novel_dir: Path) -> list[dict[str, object]]:
    tag_dir = novel_dir / "tag"
    if not tag_dir.is_dir():
        return []
    anchors: list[dict[str, object]] = []
    for tag_path in sorted(tag_dir.glob("*.md")):
        parsed = parse_tag_anchor(tag_path)
        if parsed:
            anchors.append(parsed)
    return anchors


def load_character_ir_map(novel_dir: Path) -> dict[str, dict]:
    character_dir = novel_dir / "tag" / "characters"
    if not character_dir.is_dir():
        return {}
    characters: dict[str, dict] = {}
    for path in sorted(character_dir.glob("*.yaml")):
        character = load_yaml(path)
        character_id = character.get("character_id")
        if character_id:
            characters[str(character_id)] = character
    return characters


def selected_subject_variant_id(subject: dict) -> str | None:
    for key in ("prompt_variant_id", "costume_variant", "variant_id"):
        value = subject.get(key)
        if value:
            return str(value)
    return None


def find_character_variant(character: dict, variant_id: str | None) -> dict | None:
    if not variant_id:
        return None
    for variant in as_list(character.get("prompt_variants")):
        if isinstance(variant, dict) and variant.get("variant_id") == variant_id:
            return variant
    return None


def character_ir_tags(character: dict, variant_id: str | None = None) -> list[str]:
    variant = find_character_variant(character, variant_id)
    if variant:
        appearance = character.get("appearance") or {}
        variant_tags: list[str] = []
        variant_tags.extend(str(v) for v in as_list(character.get("character_tags")))
        variant_tags.extend(str(v) for v in as_list(appearance.get("species_features")))
        variant_tags.extend(str(v) for v in as_list(appearance.get("distinctive_features")))
        variant_tags.extend(str(v) for v in as_list(variant.get("danbooru_tags")))
        return unique(variant_tags)

    appearance = character.get("appearance") or {}
    costume = character.get("costume") or {}
    rules = character.get("manga_rules") or {}
    tags: list[str] = []
    tags.extend(str(v) for v in as_list(character.get("character_tags")))
    tags.extend(str(v) for v in as_list(costume.get("outfit_tags")))
    tags.extend(str(v) for v in as_list(rules.get("consistency_tags")))
    tags.extend(str(v) for v in as_list(appearance.get("species_features")))
    tags.extend(str(v) for v in as_list(appearance.get("distinctive_features")))
    return unique(tags)


def snapshot_key(character_id: str | None, variant_id: str | None) -> tuple[str, str]:
    return (str(character_id or ""), str(variant_id or ""))


def page_snapshot_map(page: dict) -> dict[tuple[str, str], dict]:
    snapshots: dict[tuple[str, str], dict] = {}
    for snapshot in as_list(page.get("character_snapshots")):
        if not isinstance(snapshot, dict):
            continue
        cid = snapshot.get("character_id")
        if not cid:
            continue
        key = snapshot_key(str(cid), snapshot.get("selected_variant_id"))
        snapshots[key] = snapshot
        snapshots.setdefault(snapshot_key(str(cid), None), snapshot)
    return snapshots


def subject_snapshot(page: dict, subject: dict) -> dict | None:
    cid = subject.get("character_id")
    if not cid:
        return None
    snapshots = page_snapshot_map(page)
    variant_id = selected_subject_variant_id(subject)
    return snapshots.get(snapshot_key(str(cid), variant_id)) or snapshots.get(snapshot_key(str(cid), None))


def snapshot_tags(snapshot: dict) -> list[str]:
    tags: list[str] = []
    tags.extend(str(v) for v in as_list(snapshot.get("fixed_tags")))
    tags.extend(str(v) for v in as_list(snapshot.get("variant_tags")))
    return unique(tags)


def character_visual_summary_for_step2(character: dict, variant_id: str | None = None) -> str:
    """Step2 向け: tag/characters の appearance / costume から短い日本語の固定見た目列を組む。"""
    _ = variant_id  # 将来: バリアント別の差分を足す余地
    app = character.get("appearance") or {}
    cos = character.get("costume") or {}
    name = str(character.get("name") or character.get("character_id") or "?")
    segments: list[str] = []
    if app.get("hair_color"):
        segments.append(f"髪色 {app['hair_color']}")
    if app.get("hair_style"):
        segments.append(f"髪型 {app['hair_style']}")
    if app.get("eye_color"):
        segments.append(f"目色 {app['eye_color']}")
    if app.get("skin_tone"):
        segments.append(f"肌 {app['skin_tone']}")
    species = [str(x) for x in as_list(app.get("species_features")) if x]
    if species:
        segments.append("種族特徴 " + "・".join(species))
    acc = [str(x) for x in as_list(cos.get("accessories")) if x]
    if acc:
        segments.append("固定小物 " + "・".join(acc))
    dist = [str(x) for x in as_list(app.get("distinctive_features")) if x][:3]
    for d in dist:
        segments.append(str(d))
    if segments:
        return f"{name}・" + "、".join(segments)
    ct = [str(x) for x in as_list(character.get("character_tags")) if x][:8]
    if ct:
        return f"{name}・" + "、".join(ct)
    return name


def subject_step2_character_clause(
    page: dict,
    subject: dict,
    characters: dict[str, dict],
) -> str:
    """1 subject 分の Step2 固定見た目節（空なら空文字）。"""
    cid = subject.get("character_id")
    if not cid:
        return ""
    cid = str(cid)
    snapshot = subject_snapshot(page, subject)
    variant_id = selected_subject_variant_id(subject)
    if snapshot:
        label = str(snapshot.get("name") or snapshot.get("name_en") or cid)
        # Step2 の固定見た目は外見の要約のみ（costume_summary は衣装・状況説明が長くなりがちなため含めない）
        if snapshot.get("appearance_summary"):
            return f"{label}: " + str(snapshot["appearance_summary"]).strip()
        tags = snapshot_tags(snapshot)
        if tags:
            return f"{label}: " + "、".join(tags[:16])
    if cid in characters:
        char = characters[cid]
        return character_visual_summary_for_step2(char, variant_id)
    return ""


def step2_character_anchor_segments(
    page: dict,
    panel: dict,
    characters: dict[str, dict],
) -> list[str]:
    """同一コマ内の登場キャラごとの固定見た目（character_id 単位で重複除去）。"""
    seen: set[str] = set()
    out: list[str] = []
    for subject in as_list(panel.get("subjects")):
        if not isinstance(subject, dict):
            continue
        cid = subject.get("character_id")
        if not cid:
            continue
        cid = str(cid)
        if cid in seen:
            continue
        seen.add(cid)
        clause = subject_step2_character_clause(page, subject, characters)
        if clause:
            out.append(clause)
    return out


def panel_step2_description(panel: dict, *, apply_paraphrase: bool | None = None) -> str:
    """Step2 行の本文。`step2_summary` が非空ならそれを使い、無ければ `summary`。

    apply_paraphrase が True のとき、または None かつ環境変数 MONOCRI_STEP2_PARAPHRASE が真のとき、
    manga_prompt_ir.step2_paraphrase のルールを適用する（既定は avoid に部分一致したら本文全体を use に差し替える ``whole_text``。YAML の ``apply_mode: substring`` で従来の部分置換）。
    """
    from manga_prompt_ir.step2_paraphrase import apply_step2_paraphrase, effective_paraphrase

    raw = panel.get("step2_summary")
    if raw is not None and str(raw).strip():
        body = str(raw).strip()
    else:
        body = str(panel.get("summary") or "").strip()
    if effective_paraphrase(apply_paraphrase):
        body = apply_step2_paraphrase(body)
    return body


def build_step2_panel_line(
    page: dict,
    panel: dict,
    characters: dict[str, dict],
    *,
    apply_paraphrase: bool | None = None,
) -> str:
    """互換 Markdown Step2 の1コマ行（layout・summary の後に固定見た目を任意で付与）。"""
    comp = panel.get("composition") or {}
    pid = panel.get("panel_id", "?")
    layout = comp.get("layout") or ""
    body = panel_step2_description(panel, apply_paraphrase=apply_paraphrase)
    base = f"- コマ{pid}: {layout}。{body}"
    anchors = step2_character_anchor_segments(page, panel, characters)
    if not anchors:
        return base
    return f"{base} 【固定見た目】{' ｜ '.join(anchors)}"


SINGLE_PANEL_BLOCKLIST_EXACT = {
    "color manga page",
    "japanese manga panel layout",
    "clear panel borders",
    "manga page",
    "panel layout",
}

SINGLE_PANEL_BLOCKLIST_SUBSTRINGS = (
    "panel border",
    "panel borders",
    "panel layout",
    "manga panel",
    "top panel",
    "bottom panel",
    "left panel",
    "right panel",
    "page layout",
    "color manga page",
    "1ページ",
    "コマ割り",
    "コマ構成",
    "上段",
    "中段",
    "下段",
    "大コマ",
    "小コマ",
)


def is_single_panel_layout_tag(value: str) -> bool:
    normalized = value.strip().lower().replace("_", " ")
    if not normalized:
        return True
    if normalized in SINGLE_PANEL_BLOCKLIST_EXACT:
        return True
    return any(part in normalized for part in SINGLE_PANEL_BLOCKLIST_SUBSTRINGS)


def filter_single_panel_tags(values: list[str]) -> list[str]:
    return [value for value in values if not is_single_panel_layout_tag(value)]


def _normalize_tag_for_match(value: str) -> str:
    return value.strip().lower().replace("_", " ")


def is_background_prompt_tag(value: str) -> bool:
    """舞台・背景・浴室設備寄りのタグか（コマ単体合成向け omit 用）。"""
    normalized = _normalize_tag_for_match(value)
    if not normalized:
        return False
    return any(part in normalized for part in BACKGROUND_PROMPT_TAG_SUBSTRINGS)


def filter_background_prompt_tags(values: list[str]) -> list[str]:
    return [value for value in values if not is_background_prompt_tag(value)]


def apply_omit_panel_background_tags(values: list[str]) -> list[str]:
    """背景省略モード: 残タグから舞台系を落とし、簡素背景タグを付与する。"""
    filtered = filter_background_prompt_tags(values)
    filtered.extend(OMIT_PANEL_BACKGROUND_ADD_TAGS)
    return unique(filtered)


def resolve_omit_panel_background(cli_flag: bool, root: Path) -> bool:
    if cli_flag:
        return True
    env = load_dotenv(root / ".env").get(MANGA_STEP1_OMIT_PANEL_BACKGROUND_ENV, "")
    return str(env).strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class NovelaiReferenceResolution:
    paths: list[str]
    strength: float  # バンドル内 importInfo への乗数（既定 1.0）
    information_extracted: float  # 同上
    source: str  # cli | _meta.yaml | .env | default


def _resolve_cli_reference_paths(cli_paths: list[str], root: Path) -> list[str]:
    paths = [p.strip() for p in cli_paths if p and str(p).strip()]
    resolved: list[str] = []
    for raw in paths:
        path = Path(raw)
        if not path.is_absolute():
            path = (root / path).resolve()
        if not path.is_file():
            raise FileNotFoundError(f"reference image path not found: {path}")
        resolved.append(path.as_posix())
    return resolved


def resolve_novelai_reference(
    cli_paths: list[str],
    root: Path,
    *,
    novel_dir: Path | None = None,
    portion_id: str | None = None,
    cli_strength: float | None = None,
    cli_information_extracted: float | None = None,
) -> NovelaiReferenceResolution:
    """NovelAI Vibe / ポーション: CLI > 作品 _meta.yaml > .env > 既定。"""
    if cli_paths:
        paths = _resolve_cli_reference_paths(cli_paths, root)
        strength = (
            float(cli_strength)
            if cli_strength is not None
            else resolve_novelai_reference_strength(None, root)
        )
        ie = (
            float(cli_information_extracted)
            if cli_information_extracted is not None
            else resolve_novelai_reference_information_extracted(None, root)
        )
        return NovelaiReferenceResolution(
            paths=paths,
            strength=strength,
            information_extracted=ie,
            source="cli",
        )

    if novel_dir is not None:
        from novel_meta_yaml import resolve_novelai_portion

        try:
            portion = resolve_novelai_portion(
                novel_dir, root, portion_id=portion_id
            )
        except (FileNotFoundError, ValueError) as e:
            raise FileNotFoundError(str(e)) from e
        if portion is not None:
            strength = (
                float(cli_strength)
                if cli_strength is not None
                else portion.strength
            )
            ie = (
                float(cli_information_extracted)
                if cli_information_extracted is not None
                else portion.information_extracted
            )
            label = f" ({portion.label})" if portion.label else ""
            return NovelaiReferenceResolution(
                paths=list(portion.paths),
                strength=strength,
                information_extracted=ie,
                source=f"_meta.yaml#{portion.id}{label}",
            )

    env_paths: list[str] = []
    env = load_dotenv(root / ".env").get(MANGA_NOVELAI_REFERENCE_PATHS_ENV, "")
    if str(env).strip():
        env_paths = [
            p.strip()
            for p in str(env).replace(",", ";").split(";")
            if p.strip()
        ]
    if env_paths:
        paths = _resolve_cli_reference_paths(env_paths, root)
        strength = resolve_novelai_reference_strength(cli_strength, root)
        ie = resolve_novelai_reference_information_extracted(
            cli_information_extracted, root
        )
        return NovelaiReferenceResolution(
            paths=paths,
            strength=strength,
            information_extracted=ie,
            source=".env",
        )

    return NovelaiReferenceResolution(
        paths=[],
        strength=resolve_novelai_reference_strength(cli_strength, root),
        information_extracted=resolve_novelai_reference_information_extracted(
            cli_information_extracted, root
        ),
        source="default",
    )


def resolve_novelai_reference_paths(cli_paths: list[str], root: Path) -> list[str]:
    """後方互換。CLI / .env のみ（作品 _meta.yaml は見ない）。"""
    return resolve_novelai_reference(cli_paths, root).paths


def resolve_novelai_reference_strength(cli_value: float | None, root: Path) -> float:
    if cli_value is not None:
        return float(cli_value)
    env = load_dotenv(root / ".env").get(MANGA_NOVELAI_REFERENCE_STRENGTH_ENV, "")
    if str(env).strip():
        return float(env)
    return 1.0


def resolve_novelai_reference_information_extracted(
    cli_value: float | None, root: Path
) -> float:
    if cli_value is not None:
        return float(cli_value)
    env = load_dotenv(root / ".env").get(MANGA_NOVELAI_REFERENCE_IE_ENV, "")
    if str(env).strip():
        return float(env)
    return 1.0


def novelai_reference_job_fields(
    paths: list[str],
    *,
    strength: float,
    information_extracted: float,
    root: Path,
) -> dict[str, Any]:
    if not paths:
        return {}
    from image_provider_generate import build_novelai_reference_coefficients

    strengths, ies, normalize = build_novelai_reference_coefficients(
        paths,
        root,
        strength_multiplier=strength,
        information_extracted_multiplier=information_extracted,
    )
    if not strengths:
        return {}
    return {
        "reference_image_paths": paths,
        "reference_strength_multiple": strengths,
        "reference_information_extracted_multiple": ies,
        "normalize_reference_strength_multiple": normalize,
    }


def resolve_include_panel_summary(
    *,
    cli_no_flag: bool,
    root: Path,
    source: str,
) -> bool:
    """step1-panels: ``summary_en`` をベースタグ列に併用（既定 ON）。"""
    if source != "step1-panels":
        return False
    if cli_no_flag:
        return False
    env = load_dotenv(root / ".env").get(MANGA_STEP1_INCLUDE_PANEL_SUMMARY_ENV, "")
    if str(env).strip().lower() in ("0", "false", "no", "off"):
        return False
    return True


def _extend_base_summary_en_tags(
    base: list[str],
    panel: dict,
    *,
    include_panel_summary: bool,
) -> None:
    if include_panel_summary:
        base.extend(panel_summary_en_tag_tokens(panel, include=True))


def character_display_name(character: dict, character_id: str) -> str:
    name = character.get("name") or character_id
    name_en = character.get("name_en") or character_id
    if name_en and name_en != name:
        return f"{name}（{name_en}）"
    return str(name)


def subject_text_from_ir(subject: dict, characters: dict[str, dict]) -> str:
    cid = subject.get("character_id")
    if cid and cid in characters:
        base = character_display_name(characters[cid], cid)
    else:
        base = str(subject.get("description") or subject.get("type") or "subject")
    details = [
        str(subject.get("description") or ""),
        str(subject.get("pose_action") or ""),
        str(subject.get("expression") or ""),
        str(subject.get("position") or ""),
    ]
    return "、".join([base] + [value for value in details if value])


def yaml_panel_tags(
    page: dict,
    panel: dict,
    characters: dict[str, dict],
    *,
    single_panel: bool = False,
    omit_panel_background: bool = False,
    include_panel_summary: bool = False,
) -> list[str]:
    manga = page.get("manga") or {}
    scene = panel.get("scene") or page.get("scene") or {}
    composition = panel.get("composition") or {}
    camera = panel.get("camera") or {}
    lighting = panel.get("lighting") or {}
    tags: list[str] = []
    tags.extend(["best_quality", "very_aesthetic", "ultra-detailed", "manga"])
    tags.extend(str(v) for v in as_list(manga.get("genre_tags")))
    tags.extend(str(v) for v in as_list(manga.get("visual_tags")))
    _extend_base_summary_en_tags(tags, panel, include_panel_summary=include_panel_summary)
    if not omit_panel_background:
        # English / Danbooru-style scene line (IR: background_notes_en only; no JP fallback)
        tags.extend(comma_split_tags(scene_prompt_background_notes(scene)))
        tags.extend(str(v) for v in as_list(manga.get("background_tags")))
        loc_pt, tod_pt, wx_pt = scene_prompt_location_time_weather(scene)
        tags.extend(str(v) for v in [loc_pt, tod_pt, wx_pt] if v)
        tags.extend(lighting_tag_tokens(lighting))
        tags.extend(composition_layout_tag_token(composition, single_panel=single_panel))
    panel_prompt_tags = as_list(panel.get("prompt_tags"))
    if omit_panel_background:
        panel_prompt_tags = filter_background_prompt_tags(
            [str(v) for v in panel_prompt_tags]
        )
    tags.extend(str(v) for v in panel_prompt_tags)
    tags.extend(composition_tag_tokens(composition))
    tags.extend(camera_tag_tokens(camera))
    for subject in as_list(panel.get("subjects")):
        if not isinstance(subject, dict):
            continue
        cid = subject.get("character_id")
        snapshot = subject_snapshot(page, subject)
        if snapshot:
            tags.append(str(snapshot.get("name_en") or snapshot.get("name") or cid))
            tags.extend(snapshot_tags(snapshot))
        elif cid and cid in characters:
            character = characters[cid]
            tags.append(str(character.get("name_en") or cid))
            tags.extend(character_ir_tags(character, selected_subject_variant_id(subject)))
        else:
            tags.append(subject_tag_line_token(subject))
        tags.extend(subject_situational_tag_tokens(subject))
    tags.extend(panel_mood_atmosphere_tag_tokens(panel))
    tags = unique(tags)
    tags = apply_user_directives_to_tags(tags, page, panel)
    if single_panel:
        tags = filter_single_panel_tags(tags)
    if omit_panel_background:
        tags = apply_omit_panel_background_tags(tags)
    return tags


def yaml_panel_tags_novelai_split(
    page: dict,
    panel: dict,
    characters: dict[str, dict],
    *,
    single_panel: bool = False,
    omit_panel_background: bool = False,
    include_panel_summary: bool = False,
) -> tuple[list[str], list[list[str]]]:
    """
    NovelAI の「ベース | キャラA | キャラB | …」入力向けにタグを分割する。

    - base: 画風・舞台・構図・panels[].prompt_tags・雰囲気等の状況タグ、
      および character_id / snapshot を持たない subject の短いトークン
    - character_segments: character_snapshots または tag/characters を参照する
      subjects 要素ごとに 1 セグメント（name_en + 固定・バリアント + その行の pose 等）
    """
    manga = page.get("manga") or {}
    scene = panel.get("scene") or page.get("scene") or {}
    composition = panel.get("composition") or {}
    camera = panel.get("camera") or {}
    lighting = panel.get("lighting") or {}
    base: list[str] = []
    character_segments: list[list[str]] = []
    base.extend(["best_quality", "very_aesthetic", "ultra-detailed", "manga"])
    base.extend(str(v) for v in as_list(manga.get("genre_tags")))
    base.extend(str(v) for v in as_list(manga.get("visual_tags")))
    _extend_base_summary_en_tags(base, panel, include_panel_summary=include_panel_summary)
    if not omit_panel_background:
        base.extend(comma_split_tags(scene_prompt_background_notes(scene)))
        base.extend(str(v) for v in as_list(manga.get("background_tags")))
        loc_pt, tod_pt, wx_pt = scene_prompt_location_time_weather(scene)
        base.extend(str(v) for v in [loc_pt, tod_pt, wx_pt] if v)
        base.extend(lighting_tag_tokens(lighting))
        base.extend(
            composition_layout_tag_token(composition, single_panel=single_panel)
        )
    panel_prompt_tags = as_list(panel.get("prompt_tags"))
    if omit_panel_background:
        panel_prompt_tags = filter_background_prompt_tags(
            [str(v) for v in panel_prompt_tags]
        )
    base.extend(str(v) for v in panel_prompt_tags)
    base.extend(composition_tag_tokens(composition))
    base.extend(camera_tag_tokens(camera))
    for subject in as_list(panel.get("subjects")):
        if not isinstance(subject, dict):
            continue
        cid = subject.get("character_id")
        snapshot = subject_snapshot(page, subject)
        situational = subject_situational_tag_tokens(subject)
        seg: list[str] = []
        if snapshot:
            seg.append(str(snapshot.get("name_en") or snapshot.get("name") or cid))
            seg.extend(snapshot_tags(snapshot))
        elif cid and cid in characters:
            character = characters[cid]
            seg.append(str(character.get("name_en") or cid))
            seg.extend(character_ir_tags(character, selected_subject_variant_id(subject)))
        else:
            base.append(subject_tag_line_token(subject))
        if seg:
            seg.extend(situational)
            character_segments.append(seg)
        else:
            base.extend(situational)
    base.extend(panel_mood_atmosphere_tag_tokens(panel))
    base = unique(base)
    character_segments = [unique(seg) for seg in character_segments]
    # base 側に required を加算し、omit は base / character_segments の両側へ反映する。
    # required はキャラ別セグメントへ重ねて入れない（重複・取り違えを避ける）。
    base = apply_user_directives_to_tags(base, page, panel)
    omit = user_directives_omit_tags(page, panel)
    if omit:
        character_segments = [
            [tag for tag in seg if tag not in omit] for seg in character_segments
        ]
    if single_panel:
        base = filter_single_panel_tags(base)
        character_segments = [filter_single_panel_tags(seg) for seg in character_segments]
    if omit_panel_background:
        base = apply_omit_panel_background_tags(base)
        character_segments = [
            apply_omit_panel_background_tags(seg) for seg in character_segments
        ]
    return base, character_segments


def yaml_text_lines(panel: dict) -> list[str]:
    text = panel.get("text") or {}
    lines: list[str] = []
    for item in as_list(text.get("dialogue")):
        if isinstance(item, dict):
            lines.append(f"- セリフ: {item.get('speaker', '不明')}「{item.get('content', '')}」")
    for item in as_list(text.get("monologue")):
        lines.append(f"- モノローグ: {item}")
    for item in as_list(text.get("narration")):
        lines.append(f"- ナレーション: {item}")
    for item in as_list(text.get("sfx")):
        if isinstance(item, dict):
            meaning = f"（{item.get('meaning')}）" if item.get("meaning") else ""
            lines.append(f"- 効果音: {item.get('content', '')}{meaning}")
    return lines


def yaml_page_stem(path: Path, page: dict) -> str:
    manga_id = page.get("manga_id")
    if manga_id:
        return str(manga_id)
    match = re.match(r"(.+)_p\d+$", path.stem)
    return match.group(1) if match else path.stem


def yaml_page_number(path: Path, fallback: int) -> int:
    match = re.search(r"_p(\d+)$", path.stem)
    return int(match.group(1)) if match else fallback


def yaml_render_instruction_block(page: dict) -> str:
    instruction = page.get("render_instruction") or {}
    if not isinstance(instruction, dict):
        return ""
    lines: list[str] = []
    for key in (
        "prompt_header",
        "task",
        "panel_policy",
        "character_policy",
        "text_policy",
        "output_policy",
    ):
        value = instruction.get(key)
        if value:
            lines.append(str(value))
    for note in as_list(instruction.get("notes")):
        if note:
            lines.append(str(note))
    return "\n".join(dict.fromkeys(lines))


def trim_prompt_to_byte_limit(prompt: str, max_bytes: int) -> str:
    """
    UTF-8 バイト数が max_bytes を超えるプロンプトを段階的に圧縮する。
    step1-pages の Grok 向け主用途。
    圧縮順: render_instruction 行 → tag 行 → 日本語訳 行 → 末尾カット
    """
    if len(prompt.encode("utf-8")) <= max_bytes:
        return prompt

    lines = prompt.splitlines()

    # フェーズ1: render_instruction ブロック（このYAMLは〜で始まる段落）を除去
    def _is_ri_line(line: str) -> bool:
        triggers = (
            "このYAMLを、漫画1ページ分の作画依頼書として扱う",
            "panels[]の順番とpanel_idを守り",
            "character_snapshotsの外見",
            "text.dialogue",
            "1枚の完成漫画ページとして",
            "prompt_tagsは各コマの",
            "technical.negative_tags",
            "sceneはページ共通の",
            "render_instruction",
            "作画補助:",
            "panel_policy:",
            "character_policy:",
            "text_policy:",
            "output_policy:",
            "notes:",
            "- prompt_tags",
            "- technical",
            "- sceneは",
        )
        s = line.strip()
        return any(s.startswith(t) or t in s for t in triggers)

    trimmed = [l for l in lines if not _is_ri_line(l)]
    if len("\n".join(trimmed).encode("utf-8")) <= max_bytes:
        return "\n".join(trimmed)

    # フェーズ2: 「- tag:」行を除去（キャラ固定タグはanchor_blockで補完）
    trimmed = [l for l in trimmed if not l.strip().startswith("- tag:")]
    if len("\n".join(trimmed).encode("utf-8")) <= max_bytes:
        return "\n".join(trimmed)

    # フェーズ3: 「- 日本語訳:」行を除去（summaryと重複）
    trimmed = [l for l in trimmed if not l.strip().startswith("- 日本語訳:")]
    if len("\n".join(trimmed).encode("utf-8")) <= max_bytes:
        return "\n".join(trimmed)

    # フェーズ4: バイト上限での末尾カット（最終手段）
    encoded = "\n".join(trimmed).encode("utf-8")
    truncated = encoded[:max_bytes].decode("utf-8", errors="ignore")
    last_nl = truncated.rfind("\n")
    return truncated[:last_nl] + "\n[...省略]" if last_nl > 0 else truncated


def yaml_page_step1_text(
    page: dict,
    characters: dict[str, dict],
    page_number: int,
    *,
    color_mode_override: str | None = None,
) -> str:
    meta = page.get("meta") or {}
    manga = page.get("manga") or {}
    scene = page.get("scene") or {}
    loc_s, tod_s, _wx_s = scene_prompt_location_time_weather(scene)
    panels = as_list(page.get("panels"))
    reading_order = meta.get("reading_order", "right_to_left")
    panel_layout = manga.get("panel_layout") or f"{len(panels)}コマ構成"
    instruction_block = yaml_render_instruction_block(page)
    color_label = page_color_mode_label(page, override=color_mode_override)
    lines = [
        f"Page {page_number}",
        instruction_block,
        f"{color_label}、日本の漫画のコマ割り、1ページ{len(panels)}コマ、読み順: {reading_order}",
        f"ページ構成: {panel_layout}",
        f"共通舞台: {loc_s} / {tod_s} / {scene_prompt_background_notes(scene)}",
        "",
    ]
    lines = [line for line in lines if line]
    for panel in panels:
        if not isinstance(panel, dict):
            continue
        subjects = [
            subject_text_from_ir(subject, characters)
            for subject in as_list(panel.get("subjects"))
            if isinstance(subject, dict)
        ]
        comp = panel.get("composition") or {}
        camera = panel.get("camera") or {}
        lines.extend(
            [
                f"コマ{panel.get('panel_id', '?')}: {panel.get('summary', '')}",
                f"- 人物・対象: {' / '.join(subjects)}",
                f"- 構図: {comp.get('layout', '')} / {comp.get('framing', '')} / {comp.get('focus', '')} / {camera.get('angle', '')}",
                *yaml_text_lines(panel),
                f"- tag: {join_tags(yaml_panel_tags(page, panel, characters))}",
                f"- 日本語訳: {panel.get('translation') or panel.get('summary', '')}",
                "",
            ]
        )
    return "\n".join(lines).strip()


def yaml_page_step2_text(
    page: dict,
    page_number: int,
    characters: dict[str, dict],
    *,
    apply_paraphrase: bool | None = None,
) -> str:
    meta = page.get("meta") or {}
    manga = page.get("manga") or {}
    panels = as_list(page.get("panels"))
    reading_order = meta.get("reading_order", "right_to_left")
    panel_layout = manga.get("panel_layout") or f"{len(panels)}コマ構成"
    lines = [
        f"Page {page_number}",
        f"1ページ{len(panels)}コマ。{panel_layout}。読み順は {reading_order}。",
    ]
    for panel in panels:
        if isinstance(panel, dict):
            lines.append(
                build_step2_panel_line(page, panel, characters, apply_paraphrase=apply_paraphrase)
            )
    return "\n".join(lines).strip()


def yaml_background_concept_jobs(
    page: dict,
    stem: str,
    page_num: int,
    yaml_path: Path,
    *,
    cli_negative_prompt: str,
    prompt_formatter: str,
) -> list[dict[str, object]]:
    scene = page.get("scene") or {}
    meta = page.get("meta") or {}
    loc_bg, tod_bg, _wx_bg = scene_prompt_location_time_weather(scene)
    scene_background_notes = scene_prompt_background_notes(scene)
    technical = page.get("technical") or {}
    page_negative = join_tags(as_list(technical.get("negative_tags")))
    jobs: list[dict[str, object]] = []
    for index, concept in enumerate(as_list(page.get("background_concepts")), start=1):
        if not isinstance(concept, dict):
            continue
        concept_id = str(concept.get("concept_id") or f"bg{index:02d}")
        title = str(concept.get("title") or concept_id)
        description = str(concept.get("description") or "")
        prompt = str(concept.get("prompt") or description)
        if not prompt:
            continue
        negative = join_tags(as_list(concept.get("negative_tags")))
        negative_line = ", ".join(
            v for v in [cli_negative_prompt, page_negative, negative] if v
        )
        legacy_body = "\n".join(
            line
            for line in [
                "背景コンセプト生成。人物を主役にせず、漫画ページで使う背景・空間設計として描く。",
                f"Page {page_num} / {title}",
                f"共通舞台: {loc_bg} / {tod_bg} / {scene_background_notes}",
                f"説明: {description}" if description else "",
                f"背景プロンプト: {prompt}",
                f"用途: {concept.get('usage', '')}" if concept.get("usage") else "",
                f"避ける要素: {negative_line}" if negative_line else "",
            ]
            if line
        )
        bundle = format_background_prompt(
            page,
            concept,
            page_num=page_num,
            scene_location=loc_bg,
            scene_time=tod_bg,
            scene_background_notes=scene_background_notes,
            legacy_prompt=legacy_body,
            negative_prompt=negative_line,
            formatter=prompt_formatter,
        )
        jobs.append(
            {
                "stem": stem,
                "page": str(page_num),
                "koma": "0",
                "prefix": f"{stem}_p{page_num:02d}_{concept_id}",
                "prompt": bundle.prompt,
                "negative_prompt": bundle.negative_prompt,
                "prompt_formatter": bundle.formatter,
                "negative_mode": bundle.negative_mode,
                "output_subdir": "backgrounds",
                "metadata": {
                    "kind": "background-reference",
                    "source": "background-concepts",
                    "manga_yaml": yaml_path.as_posix(),
                    "source_text_file": meta.get("source_text_file"),
                    "page": page_num,
                    "manga_stem": stem,
                    "concept_id": concept_id,
                    "concept_title": title,
                    "scene_name": scene.get("name") or scene.get("location"),
                    "scene_location": scene.get("location"),
                    "scene_location_en": scene.get("location_en"),
                    "usage": concept.get("usage"),
                    "provider_hint": concept.get("provider_hint"),
                },
            }
        )
    return jobs


def yaml_character_anchor_block(page: dict, characters: dict[str, dict]) -> str:
    lines = ["キャラクター固定特徴（tag/characters/*.yaml 準拠）:"]
    seen: set[str] = set()
    for panel in as_list(page.get("panels")):
        if not isinstance(panel, dict):
            continue
        for subject in as_list(panel.get("subjects")):
            if not isinstance(subject, dict):
                continue
            cid = subject.get("character_id")
            if not cid or cid in seen:
                continue
            snapshot = subject_snapshot(page, subject)
            if not snapshot and cid not in characters:
                continue
            seen.add(cid)
            character = characters.get(cid, {})
            tags = join_tags(snapshot_tags(snapshot) if snapshot else character_ir_tags(character, selected_subject_variant_id(subject)))
            if tags:
                variant_id = selected_subject_variant_id(subject)
                label_base = str(snapshot.get("name") or snapshot.get("name_en") or cid) if snapshot else character_display_name(character, cid)
                label = f"{label_base} / {variant_id}" if variant_id else label_base
                lines.append(f"- {label}: {tags}")
    return "\n".join(lines) if len(lines) > 1 else ""


def alias_matches_text(alias: str, text: str, lowered: str) -> bool:
    alias = alias.strip()
    if not alias:
        return False
    if re.search(r"[A-Za-z0-9_]", alias):
        pattern = rf"(?<![A-Za-z0-9_]){re.escape(alias.lower())}(?![A-Za-z0-9_])"
        return re.search(pattern, lowered) is not None
    return alias in text


def detect_relevant_anchors(
    anchors: Iterable[dict[str, object]],
    text: str,
) -> list[dict[str, object]]:
    relevant: list[dict[str, object]] = []
    lowered = text.lower()
    for anchor in anchors:
        aliases = as_list(anchor.get("aliases"))
        if any(isinstance(alias, str) and alias_matches_text(alias, text, lowered) for alias in aliases):
            relevant.append(anchor)
    return relevant


def build_character_anchor_block(
    anchors: list[dict[str, object]],
    text: str,
) -> str:
    relevant = detect_relevant_anchors(anchors, text)
    if not relevant:
        return ""
    lines = ["キャラクター固定特徴（tag/*.md 準拠）:"]
    for anchor in relevant:
        selected = select_anchor_variant(anchor, text)
        lines.append(
            f"- {anchor['display']} / {selected['title']}: {selected['danbooru']}"
        )
    return "\n".join(lines)


def select_anchor_variant(anchor: dict[str, object], context_text: str) -> dict[str, object]:
    lowered = context_text.lower()
    variants = [variant for variant in as_list(anchor.get("variants")) if isinstance(variant, dict)]
    best_variant = variants[0] if variants else {"title": "通常時", "danbooru": anchor["danbooru"]}
    best_score = -1
    for variant in variants:
        score = 0
        title = str(variant.get("title", ""))
        if title and title in context_text:
            score += 6
        for keyword in as_list(variant.get("keywords")):
            if keyword and (keyword in context_text or keyword in lowered):
                score += 1
        if score > best_score:
            best_score = score
            best_variant = variant
    return best_variant


def build_character_anchor_csv(
    anchors: list[dict[str, object]],
    text: str,
) -> str:
    relevant = detect_relevant_anchors(anchors, text)
    if not relevant:
        return ""
    parts: list[str] = []
    seen: set[str] = set()
    for anchor in relevant:
        selected = select_anchor_variant(anchor, text)
        for token in [t.strip() for t in str(selected["danbooru"]).split(",")]:
            if token and token not in seen:
                seen.add(token)
                parts.append(token)
    return ", ".join(parts)


def remove_text_element_lines(text: str) -> str:
    return "\n".join(
        line
        for line in text.splitlines()
        if not re.match(r"\s*-\s*(セリフ|モノローグ|ナレーション|効果音)[：:]", line)
    )


def resolve_page_style_helper(
    provider: str,
    source: str,
    style_helper: str | None,
) -> str:
    if style_helper is not None:
        return style_helper.strip()
    if provider in _GROK_FAMILY and source == "step2-pages":
        return STEP2_GROK_STYLE_HELPER.strip()
    if provider in _GROK_FAMILY and source == "step1-pages":
        return STEP1_PAGE_GROK_STYLE_HELPER.strip()
    return ""


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
    # `和訳:` または `（日本語訳：`（manga_*.md の運用両対応）
    for m in re.finditer(
        r"tag:\s*\r?\n([\s\S]*?)(?:\r?\n和訳[：:]|\r?\n（日本語訳[：:])",
        step1,
    ):
        body = normalize_tag_body(m.group(1))
        if body:
            tags.append(body)
    return tags


def extract_panel_context_entries(step1: str) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    # `**コマ2:` のように Markdown 太字が付く行も区切りとして扱う
    matches = list(
        re.finditer(
            r"(?ms)コマ(\d+):\s*(.*?)(?=^\s*\*{0,2}コマ\d+:|\Z)",
            step1,
        )
    )
    for match in matches:
        body = match.group(2).strip()
        tag_match = re.search(
            r"(?ms)-\s*\*\*tag\*\*[：:]\s*\r?\n\s*`([^`]+)`",
            body,
        )
        if tag_match:
            prompt = normalize_tag_body(tag_match.group(1))
            context = re.sub(
                r"(?ms)-\s*\*\*tag\*\*[：:]\s*\r?\n\s*`[^`]+`\s*\r?\n（日本語訳[：:][^\n]*）?",
                "",
                body,
            ).strip()
            if prompt:
                entries.append({"prompt": prompt, "context": context})
            continue
        tag_match = re.search(
            r"(?ms)tag:\s*\r?\n([\s\S]*?)(?:\r?\n和訳[：:]|\r?\n（日本語訳[：:])",
            body,
        )
        if not tag_match:
            continue
        prompt = normalize_tag_body(tag_match.group(1))
        context = re.sub(
            r"(?ms)tag:\s*\r?\n[\s\S]*?(?:\r?\n和訳[：:]|\r?\n（日本語訳[：:])[^\n]*",
            "",
            body,
        ).strip()
        entries.append(
            {
                "koma": match.group(1),
                "prompt": prompt,
                "context": context or body,
            }
        )
    return entries


def extract_step1_block(page_body: str) -> str | None:
    """`### Step1` / `## step1` から次の Step2 手前まで。"""
    m = re.search(
        r"(?is)^\s*#{1,3}\s*step1[^\n]*\r?\n(.*?)(?=^\s*#{1,3}\s*step2[^\n]*\r?\n|\Z)",
        page_body,
    )
    if m:
        return m.group(1)
    fallback = re.split(
        r"(?im)^\s*#{1,3}\s*step2[^\n]*\r?\n",
        page_body,
        maxsplit=1,
    )[0].strip()
    return fallback or None


def extract_step2_block(page_body: str) -> str | None:
    """`### Step2` / `## step2` から次の Page 手前まで。"""
    m = re.search(
        r"(?ms)^#{1,3}\s*Step2[^\n]*\r?\n(.*)$",
        page_body,
        flags=re.IGNORECASE,
    )
    return m.group(1) if m else None


def extract_manga_jobs_for_file(
    md_path: Path,
    *,
    character_anchors: list[dict[str, object]],
) -> list[dict[str, str]]:
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
        panel_entries = extract_panel_context_entries(step1)
        if panel_entries:
            source_entries = panel_entries
        else:
            source_entries = [
                {
                    "koma": str(idx + 1),
                    "prompt": body,
                    "context": step1,
                }
                for idx, body in enumerate(extract_tags_from_step1(step1))
            ]
        koma_idx = 0
        for entry in source_entries:
            koma_idx += 1
            body = entry["prompt"]
            context = entry["context"]
            anchor_context = f"{body}\n{remove_text_element_lines(context)}"
            anchor_csv = build_character_anchor_csv(character_anchors, anchor_context)
            prefix = f"{stem}_p{page_num:02d}_k{koma_idx:02d}"
            full_prompt = (
                f"{STYLE_PREFIX}{anchor_csv}, {body}"
                if anchor_csv
                else STYLE_PREFIX + body
            )
            jobs.append(
                {
                    "stem": stem,
                    "page": str(page_num),
                    "koma": str(koma_idx),
                    "prefix": prefix,
                    "prompt": full_prompt,
                }
            )
    return jobs


def extract_step2_page_jobs_for_file(
    md_path: Path,
    *,
    provider: str,
    style_helper: str | None,
    character_anchors: list[dict[str, object]],
) -> list[dict[str, str]]:
    """
    1 つの manga_XX.md から、Page ごとの step2 全体を 1 ジョブとして抽出。
    Grok など、ページ単位でレイアウト込みの漫画画像を出したいケース向け。
    """
    stem = md_path.stem
    text = md_path.read_text(encoding="utf-8")
    jobs: list[dict[str, str]] = []
    page_iter = re.finditer(
        r"## Page\s+(\d+)\s*[^\n]*\r?\n([\s\S]*?)(?=\r?\n## Page\s+\d+|\Z)",
        text,
    )
    for pm in page_iter:
        page_num = int(pm.group(1))
        page_body = pm.group(2)
        step2 = extract_step2_block(page_body)
        if not step2:
            continue
        body = normalize_step2_block(step2)
        if not body:
            continue
        helper = resolve_page_style_helper(provider, "step2-pages", style_helper)
        anchor_block = build_character_anchor_block(character_anchors, page_body)
        extra_blocks = [blk for blk in (helper, anchor_block) if blk]
        extra_text = "\n\n".join(extra_blocks)
        prompt = (
            f"以下は漫画1ページ分の構成指示です。"
            f"日本の漫画のコマ割りとして、ページ全体を1枚で生成してください。\n\n"
            f"{extra_text}\n\n## Page {page_num}\n{body}" if extra_text else
            f"以下は漫画1ページ分の構成指示です。"
            f"日本の漫画のコマ割りとして、ページ全体を1枚で生成してください。\n\n"
            f"## Page {page_num}\n{body}"
        )
        jobs.append(
            {
                "stem": stem,
                "page": str(page_num),
                "koma": "00",
                "prefix": f"{stem}_p{page_num:02d}",
                "prompt": prompt,
            }
        )
    return jobs


def extract_step1_page_jobs_for_file(
    md_path: Path,
    *,
    provider: str,
    style_helper: str | None,
    character_anchors: list[dict[str, object]],
) -> list[dict[str, str]]:
    """
    1 つの manga_XX.md から、Page ごとの step1 全体を 1 ジョブとして抽出。
    各コマの詳細指示をそのままページ全体生成へ渡したいケース向け。
    """
    stem = md_path.stem
    text = md_path.read_text(encoding="utf-8")
    jobs: list[dict[str, str]] = []
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
        body = normalize_step2_block(step1)
        if not body:
            continue
        helper = resolve_page_style_helper(provider, "step1-pages", style_helper)
        anchor_block = build_character_anchor_block(character_anchors, page_body)
        extra_blocks = [blk for blk in (helper, anchor_block) if blk]
        extra_text = "\n\n".join(extra_blocks)
        prompt = (
            f"以下は漫画1ページ分の詳細指示です。"
            f"各コマの人物、行動、背景、表情、構図差をできるだけ保持しつつ、"
            f"日本の漫画のコマ割りとして、ページ全体を1枚で精密に生成してください。\n\n"
            f"{extra_text}\n\n## Page {page_num}\n{body}" if extra_text else
            f"以下は漫画1ページ分の詳細指示です。"
            f"各コマの人物、行動、背景、表情、構図差をできるだけ保持しつつ、"
            f"日本の漫画のコマ割りとして、ページ全体を1枚で精密に生成してください。\n\n"
            f"## Page {page_num}\n{body}"
        )
        jobs.append(
            {
                "stem": stem,
                "page": str(page_num),
                "koma": "00",
                "prefix": f"{stem}_p{page_num:02d}_step1page",
                "prompt": prompt,
            }
        )
    return jobs


def iter_manga_jobs(
    novel_dir: Path,
    only_stem: str | None,
    source: str,
    provider: str,
    style_helper: str | None,
    *,
    no_character_anchors: bool = False,
) -> list[dict[str, str]]:
    manga_dir = novel_dir / "manga"
    if not manga_dir.is_dir():
        raise FileNotFoundError(f"manga/ がありません: {manga_dir}")
    all_jobs: list[dict[str, Any]] = []
    character_anchors: list[dict[str, object]] = (
        [] if no_character_anchors else load_character_anchors(novel_dir)
    )
    paths = sorted(manga_dir.glob("manga_*.md"))
    if only_stem:
        paths = [p for p in paths if p.stem == only_stem]
        if not paths:
            raise FileNotFoundError(
                f"manga/{only_stem}.md が見つかりません: {manga_dir}"
            )
    for md_path in paths:
        stem = md_path.stem
        comic_dir = resolve_manga_comic_output_dir(manga_dir, stem)
        if source == "step2-pages":
            extracted = extract_step2_page_jobs_for_file(
                md_path,
                provider=provider,
                style_helper=style_helper,
                character_anchors=character_anchors,
            )
        elif source == "step1-pages":
            extracted = extract_step1_page_jobs_for_file(
                md_path,
                provider=provider,
                style_helper=style_helper,
                character_anchors=character_anchors,
            )
        else:
            extracted = extract_manga_jobs_for_file(
                md_path,
                character_anchors=character_anchors,
            )
        for j in extracted:
            j["output_dir"] = comic_dir.as_posix()
            all_jobs.append(j)
    return all_jobs


def iter_yaml_manga_jobs(
    novel_dir: Path,
    only_stem: str | None,
    source: str,
    provider: str,
    style_helper: str | None,
    *,
    cli_negative_prompt: str,
    prompt_formatter: str,
    use_novelai_pipe_split: bool = False,
    step2_paraphrase: bool | None = None,
    color_mode_override: str | None = None,
    omit_panel_background: bool = False,
    include_panel_summary: bool = False,
) -> list[dict[str, str]]:
    manga_dir = novel_dir / "manga"
    pages_dir = manga_dir / "pages"
    if not pages_dir.is_dir():
        raise FileNotFoundError(f"manga/pages/ がありません: {pages_dir}")
    characters = load_character_ir_map(novel_dir)
    # プロバイダごとのプロンプトバイト上限を config から取得
    # novel_dir = novels/<作品名>/ → 2階層上がプロジェクトルート
    _project_root = novel_dir.resolve()
    for _ in range(4):
        if (_project_root / "config" / "image_generation.json").is_file():
            break
        _project_root = _project_root.parent
    try:
        root_cfg = load_root_config(_project_root)
    except (FileNotFoundError, ValueError):
        root_cfg = {}
    max_prompt_bytes: int | None = (
        root_cfg.get("providers", {}).get(provider, {}).get("max_prompt_bytes")
    )
    paths = sorted(pages_dir.glob("*.yaml"))
    if only_stem:
        paths = [
            path for path in paths
            if re.match(rf"{re.escape(only_stem)}(?:_p\d+)?$", path.stem)
        ]
        if not paths:
            raise FileNotFoundError(
                f"manga/pages/{only_stem}_p*.yaml が見つかりません: {pages_dir}"
            )

    all_jobs: list[dict[str, Any]] = []
    for index, path in enumerate(paths, start=1):
        page = load_yaml(path)
        panels = [panel for panel in as_list(page.get("panels")) if isinstance(panel, dict)]
        if not panels:
            continue
        stem = yaml_page_stem(path, page)
        page_num = yaml_page_number(path, index)
        stem_assets = resolve_manga_assets_stem_dir(manga_dir, stem)
        comic_dir = stem_assets / MANGA_ASSET_SUBDIR_COMIC
        color_label = page_color_mode_label(page, override=color_mode_override)
        if source == "background-concepts":
            for job in yaml_background_concept_jobs(
                page,
                stem,
                page_num,
                path,
                cli_negative_prompt=cli_negative_prompt,
                prompt_formatter=prompt_formatter,
            ):
                output_subdir_any = job.pop("output_subdir", "backgrounds")
                output_subdir = (
                    output_subdir_any
                    if isinstance(output_subdir_any, str)
                    else str(output_subdir_any)
                )
                job["output_dir"] = (stem_assets / output_subdir).as_posix()
                prompt_text = str(job.get("prompt") or "")
                if max_prompt_bytes and len(prompt_text.encode("utf-8")) > max_prompt_bytes:
                    job["prompt"] = trim_prompt_to_byte_limit(prompt_text, max_prompt_bytes)
                all_jobs.append(job)
        elif source == "step2-pages":
            body = yaml_page_step2_text(
                page, page_num, characters, apply_paraphrase=step2_paraphrase
            )
            helper = resolve_page_style_helper(provider, "step2-pages", style_helper)
            anchor_block = yaml_character_anchor_block(page, characters)
            instruction_block = yaml_render_instruction_block(page)
            extra_text = "\n\n".join(blk for blk in (instruction_block, helper, anchor_block) if blk)
            prompt = (
                f"以下は{color_label}1ページ分の構成指示です。"
                f"日本の漫画のコマ割りとして、ページ全体を1枚で生成してください。\n\n"
                f"{extra_text}\n\n{body}" if extra_text else
                f"以下は{color_label}1ページ分の構成指示です。"
                f"日本の漫画のコマ割りとして、ページ全体を1枚で生成してください。\n\n"
                f"{body}"
            )
            technical = page.get("technical") or {}
            page_negative = merge_panel_negative_prompt(
                cli_negative_prompt, as_list(technical.get("negative_tags")), [], []
            )
            bundle = format_manga_page_prompt(
                page,
                source=source,
                existing_prompt=prompt,
                negative_prompt=page_negative,
                formatter=prompt_formatter,
            )
            prompt = bundle.prompt
            if max_prompt_bytes and len(prompt.encode("utf-8")) > max_prompt_bytes:
                prompt = trim_prompt_to_byte_limit(prompt, max_prompt_bytes)
            all_jobs.append(
                {
                    "stem": stem,
                    "page": str(page_num),
                    "koma": "00",
                    "prefix": f"{stem}_p{page_num:02d}",
                    "prompt": prompt,
                    "negative_prompt": bundle.negative_prompt,
                    "prompt_formatter": bundle.formatter,
                    "negative_mode": bundle.negative_mode,
                    "output_dir": comic_dir.as_posix(),
                }
            )
        elif source == "step1-pages":
            body = yaml_page_step1_text(
                page,
                characters,
                page_num,
                color_mode_override=color_mode_override,
            )
            helper = resolve_page_style_helper(provider, "step1-pages", style_helper)
            anchor_block = yaml_character_anchor_block(page, characters)
            extra_text = "\n\n".join(blk for blk in (helper, anchor_block) if blk)
            intro = (
                f"以下は{color_label}1ページ分の詳細指示です。"
                f"各コマの人物、行動、背景、表情、構図差をできるだけ保持しつつ、"
                f"日本の漫画のコマ割りとして、ページ全体を1枚で精密に生成してください。"
            )
            prompt = f"{intro}\n\n{extra_text}\n\n{body}" if extra_text else f"{intro}\n\n{body}"
            if max_prompt_bytes and len(prompt.encode("utf-8")) > max_prompt_bytes:
                prompt = trim_prompt_to_byte_limit(prompt, max_prompt_bytes)
            technical = page.get("technical") or {}
            page_negative = merge_panel_negative_prompt(
                cli_negative_prompt, as_list(technical.get("negative_tags")), [], []
            )
            bundle = format_manga_page_prompt(
                page,
                source=source,
                existing_prompt=prompt,
                negative_prompt=page_negative,
                formatter=prompt_formatter,
            )
            prompt = bundle.prompt
            if max_prompt_bytes and len(prompt.encode("utf-8")) > max_prompt_bytes:
                prompt = trim_prompt_to_byte_limit(prompt, max_prompt_bytes)
            all_jobs.append(
                {
                    "stem": stem,
                    "page": str(page_num),
                    "koma": "00",
                    "prefix": f"{stem}_p{page_num:02d}_step1page",
                    "prompt": prompt,
                    "negative_prompt": bundle.negative_prompt,
                    "prompt_formatter": bundle.formatter,
                    "negative_mode": bundle.negative_mode,
                    "output_dir": comic_dir.as_posix(),
                }
            )
        else:
            technical = page.get("technical") or {}
            tech_neg = as_list(technical.get("negative_tags"))
            for panel_index, panel in enumerate(panels, start=1):
                if use_novelai_pipe_split:
                    btags, char_segs = yaml_panel_tags_novelai_split(
                        page,
                        panel,
                        characters,
                        single_panel=True,
                        omit_panel_background=omit_panel_background,
                        include_panel_summary=include_panel_summary,
                    )
                    tags = join_novelai_pipe_tag_line(btags, char_segs)
                else:
                    tags = join_tags(
                        yaml_panel_tags(
                            page,
                            panel,
                            characters,
                            single_panel=True,
                            omit_panel_background=omit_panel_background,
                            include_panel_summary=include_panel_summary,
                        )
                    )
                if not tags:
                    continue
                panel_neg = as_list(panel.get("negative_tags"))
                panel_omit = as_list(panel.get("omit_negative_tags"))
                extra_neg = (
                    list(OMIT_PANEL_BACKGROUND_NEGATIVE_FRAGMENTS)
                    if omit_panel_background
                    else []
                )
                merged_neg = merge_panel_negative_prompt(
                    cli_negative_prompt,
                    tech_neg + extra_neg,
                    panel_neg,
                    panel_omit,
                )
                bundle = format_manga_panel_prompt(
                    page,
                    panel,
                    tag_prompt=tags,
                    negative_prompt=merged_neg,
                    formatter=prompt_formatter,
                    style_prefix=STYLE_PREFIX,
                )
                job_meta: dict[str, object] = {
                    "kind": "manga-panel",
                    "source": source,
                }
                if omit_panel_background:
                    job_meta["omit_panel_background"] = True
                if include_panel_summary:
                    job_meta["include_panel_summary"] = True
                all_jobs.append(
                    {
                        "stem": stem,
                        "page": str(page_num),
                        "koma": str(panel_index),
                        "prefix": f"{stem}_p{page_num:02d}_k{panel_index:02d}",
                        "prompt": bundle.prompt,
                        "negative_prompt": bundle.negative_prompt,
                        "prompt_formatter": bundle.formatter,
                        "negative_mode": bundle.negative_mode,
                        "output_dir": comic_dir.as_posix(),
                        "metadata": job_meta,
                    }
                )
    return all_jobs


def iter_jobs_by_input(
    novel_dir: Path,
    only_stem: str | None,
    source: str,
    provider: str,
    style_helper: str | None,
    input_kind: str,
    *,
    cli_negative_prompt: str,
    prompt_formatter: str,
    no_character_anchors: bool = False,
    use_novelai_pipe_split: bool = False,
    step2_paraphrase: bool | None = None,
    color_mode_override: str | None = None,
    omit_panel_background: bool = False,
    include_panel_summary: bool = False,
) -> tuple[str, list[dict[str, str]]]:
    if input_kind == "yaml":
        return "yaml", iter_yaml_manga_jobs(
            novel_dir,
            only_stem,
            source,
            provider,
            style_helper,
            cli_negative_prompt=cli_negative_prompt,
            prompt_formatter=prompt_formatter,
            use_novelai_pipe_split=use_novelai_pipe_split,
            step2_paraphrase=step2_paraphrase,
            color_mode_override=color_mode_override,
            omit_panel_background=omit_panel_background,
            include_panel_summary=include_panel_summary,
        )
    if input_kind == "markdown":
        if source == "background-concepts":
            raise ValueError("background-concepts は YAML 入力専用です")
        return "markdown", iter_manga_jobs(
            novel_dir,
            only_stem,
            source,
            provider,
            style_helper,
            no_character_anchors=no_character_anchors,
        )
    raise ValueError(f"unsupported input kind: {input_kind}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="manga/pages/*.yaml または manga/manga_*.md の Step1/Step2 相当を使って画像生成"
    )
    p.add_argument(
        "novel_dir",
        type=Path,
        help="作品フォルダ（例: novels/051_タイトル）",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="image provider に送らず、抽出したジョブだけ表示",
    )
    p.add_argument(
        "--manga-stem",
        default=None,
        metavar="STEM",
        help="1 系列だけ（例: manga_01。YAMLなら manga_01_p*.yaml、Markdownなら manga_01.md）",
    )
    p.add_argument(
        "--input",
        choices=INPUT_CHOICES,
        default="yaml",
        help=(
            "入力形式。既定は yaml で、manga/pages/*.yaml を必須入力として読む。"
            " 旧Markdown運用が必要な場合だけ markdown を明示する"
        ),
    )
    p.add_argument(
        "--source",
        "--mode",
        dest="source",
        choices=("step1-panels", "step1-pages", "step2-pages", "background-concepts"),
        default=None,
        help=(
            "生成モード（--mode は同義の別名。ルール・チャットの「コマ生成」等と対応）。"
            "YAML入力では step1-panels は panels[].prompt_tags 等をコマ単位で使用、"
            "step1-pages はYAMLから組み立てた詳細ページ指示を使用、"
            "step2-pages はYAMLから組み立てた抽象ページ指示を使用、"
            "background-concepts は background_concepts[] を背景案として使用。"
            "Markdown入力では従来どおり Step1/Step2 を読む"
        ),
    )
    p.add_argument(
        "--negative-prompt",
        default=DEFAULT_NEGATIVE,
        help="negative_prompt（既定は汎用）",
    )
    p.add_argument(
        "--provider",
        choices=PROVIDER_CHOICES,
        default=None,
        help=(
            "生成プロバイダ。未指定時は source に応じて .env の "
            f"{MANGA_STEP1_PROVIDER_ENV} / {MANGA_STEP2_PROVIDER_ENV} を参照し、"
            "無ければ config/image_generation.json の default_provider を使う"
        ),
    )
    p.add_argument(
        "--aspect-ratio",
        default=None,
        help=(
            "Forge/Grok 用の比率 preset 名または比率文字列（例: manga_b5_portrait, portrait, 3:4, 9:16）。"
            f" 未指定かつ provider=grok_pro のときは環境変数 {MANGA_GROK_PRO_DEFAULT_ASPECT_ENV} で上書き可能"
        ),
    )
    p.add_argument(
        "--resolution",
        default=None,
        help="Grok 用の解像度（例: 1k, 2k）",
    )
    p.add_argument(
        "--subdir-by-page",
        action="store_true",
        help="保存先を manga/_assets/<stem>/comic/p01, p02, ...（Page 番号）の下に分ける",
    )
    p.add_argument(
        "--no-character-anchors",
        action="store_true",
        help=(
            "作品フォルダの tag/*.md からキャラ固定特徴を読み込まず、"
            "prompt への自動注入も行わない（step1 の tag: 本文と STYLE_PREFIX のみ）"
        ),
    )
    p.add_argument(
        "--omit-panel-background",
        action="store_true",
        help=(
            "step1-panels（コマ生成）のみ: 舞台・背景・場所・照明タグをプロンプトから外し、"
            "simple_background 等を付与。背景資料と合成する前提。"
            f" 環境変数 {MANGA_STEP1_OMIT_PANEL_BACKGROUND_ENV}=1 でも有効"
        ),
    )
    p.add_argument(
        "--no-include-panel-summary",
        action="store_true",
        help=(
            "step1-panels: panels[].summary_en をベースタグ列に載せない（既定は載せる）。"
            f" 環境変数 {MANGA_STEP1_INCLUDE_PANEL_SUMMARY_ENV}=0 でも無効化"
        ),
    )
    p.add_argument(
        "--no-novelai-pipe-character-tags",
        action="store_true",
        help=(
            "provider=novelai かつ YAML・source=step1-panels のとき、"
            "「ベース | キャラ」形式にせず従来どおり1本のタグ列にする"
        ),
    )
    p.add_argument(
        "--style-helper",
        default=None,
        help=(
            "step1-pages / step2-pages 用の追加画風補助文。未指定時は"
            " provider=grok ならページ生成向け補助文を自動付与"
        ),
    )
    p.add_argument(
        "--prompt-formatter",
        choices=(
            "tag_csv",
            "novelai_pipe",
            "natural_sections",
            "manga_page_instruction",
            "background_brief",
        ),
        default=None,
        help=(
            "provider別プロンプト整形の上書き。未指定時は "
            "config/image_generation.json の providers.*.prompt_formatter を参照"
        ),
    )
    p.add_argument("--min-page", type=int, default=None, help="処理する Page 番号の下限（含む）")
    p.add_argument("--max-page", type=int, default=None, help="処理する Page 番号の上限（含む）")
    p.add_argument("--min-koma", type=int, default=None, help="処理するコマ番号の下限（含む）。ページ生成ジョブは koma=0")
    p.add_argument("--max-koma", type=int, default=None, help="処理するコマ番号の上限（含む）。ページ生成ジョブは koma=0")
    p.add_argument(
        "--step2-paraphrase",
        action="store_true",
        help=(
            "source=step2-pages かつ YAML 入力時、Step2 要約へ manga_tag_step2 と同期した置換ルールを適用。"
            " 環境変数 MONOCRI_STEP2_PARAPHRASE=1 でも有効"
        ),
    )
    p.add_argument(
        "--no-step2-paraphrase",
        action="store_true",
        help="Step2 自動置換を無効にする（環境変数より優先）",
    )
    p.add_argument(
        "--color-mode",
        choices=VALID_COLOR_MODES,
        default=None,
        help=(
            "このバッチ実行だけの色モード上書き。YAML は書き換えず、"
            "YAML由来のページ指示文にだけ反映する"
        ),
    )
    p.add_argument(
        "--novelai-reference-image-path",
        action="append",
        default=[],
        dest="novelai_reference_image_paths",
        metavar="PATH",
        help=(
            "provider=novelai 時: Vibe Transfer / ポーション（.naiv4vibe / .naiv4vibebundle 等）。"
            " 複数指定可。未指定時は作品 _meta.yaml の novelai.portions、"
            f" 無ければ .env の {MANGA_NOVELAI_REFERENCE_PATHS_ENV}（; 区切り）"
        ),
    )
    p.add_argument(
        "--novelai-portion-id",
        default=None,
        metavar="ID",
        help=(
            "作品 _meta.yaml の novelai.portions から使う ID。"
            " 未指定時は portion_default"
        ),
    )
    p.add_argument(
        "--novelai-reference-strength",
        type=float,
        default=None,
        help=(
            "バンドル内 importInfo.strength への乗数（既定 1.0）。"
            f" .env の {MANGA_NOVELAI_REFERENCE_STRENGTH_ENV} でも指定可"
        ),
    )
    p.add_argument(
        "--novelai-reference-information-extracted",
        type=float,
        default=None,
        help=(
            "バンドル内 importInfo.information_extracted への乗数（既定 1.0）。"
            f" .env の {MANGA_NOVELAI_REFERENCE_IE_ENV} でも指定可"
        ),
    )
    p.add_argument(
        "--workflow",
        default=None,
        metavar="ID",
        help=(
            "作品 _meta.yaml の workflows セクションに登録した名前付きレシピ ID。"
            " CLI 明示フラグで個別に上書き可能。"
            " 利用可能な ID は --list-workflows で確認できる"
        ),
    )
    p.add_argument(
        "--list-workflows",
        action="store_true",
        help="作品 _meta.yaml に登録された workflows 一覧を表示して終了",
    )
    args = p.parse_args(argv)

    root = repo_root()
    novel = args.novel_dir
    if not novel.is_absolute():
        novel = (root / novel).resolve()
    if not novel.is_dir():
        print(f"error: ディレクトリがありません: {novel}", file=sys.stderr)
        return 2

    # ── --list-workflows: 一覧表示して終了
    from novel_meta_yaml import list_workflows, resolve_workflow  # noqa: E402
    if args.list_workflows:
        wfs = list_workflows(novel)
        if not wfs:
            print("(workflows が _meta.yaml に未登録です)", file=sys.stderr)
            return 0
        for wf_id, entry in wfs.items():
            label = (entry or {}).get("label", "")
            suffix = f"  # {label}" if label else ""
            print(f"  {wf_id}{suffix}")
        return 0

    # ── --workflow: レシピ設定を args の未設定フィールドに適用
    # 優先順位: CLI 明示フラグ > workflow 設定 > 元の既定値
    if args.workflow:
        try:
            wf = resolve_workflow(novel, args.workflow)
        except (FileNotFoundError, ValueError, KeyError) as e:
            print(f"error: --workflow: {e}", file=sys.stderr)
            return 2
        # source: CLI 未指定（None）のときだけ workflow から補完
        if args.source is None and "source" in wf:
            args.source = wf["source"]
        # bool フラグ: False（store_true の暗黙デフォルト）かつ workflow が True のとき補完
        if not args.omit_panel_background and wf.get("omit_panel_background"):
            args.omit_panel_background = True
        # None フィールド群
        for wf_key, attr in (
            ("color_mode", "color_mode"),
            ("novelai_portion_id", "novelai_portion_id"),
            ("strength", "novelai_reference_strength"),
            ("information_extracted", "novelai_reference_information_extracted"),
            ("provider", "provider"),
            ("aspect_ratio", "aspect_ratio"),
        ):
            if getattr(args, attr) is None and wf_key in wf:
                setattr(args, attr, wf[wf_key])
        print(f"workflow={args.workflow!r} を適用しました", file=sys.stderr)

    # source の最終デフォルト（CLI/workflow どちらも未指定なら step1-panels）
    if args.source is None:
        args.source = "step1-panels"

    try:
        provider = resolve_batch_provider(root, args.source, args.provider)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    try:
        prompt_formatter = resolve_prompt_formatter(
            provider,
            args.source,
            provider_cfg=provider_config_from_root(root, provider),
            cli_formatter=args.prompt_formatter,
        )
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    if (
        provider == "novelai"
        and args.input == "yaml"
        and args.source == "step1-panels"
        and args.no_novelai_pipe_character_tags
        and prompt_formatter == NOVELAI_PIPE
    ):
        prompt_formatter = TAG_CSV
    use_novelai_pipe = (
        args.input == "yaml"
        and args.source == "step1-panels"
        and prompt_formatter == NOVELAI_PIPE
    )
    from manga_prompt_ir.step2_paraphrase import (
        effective_paraphrase,
        resolve_step2_paraphrase_flag,
    )

    step2_px = resolve_step2_paraphrase_flag(
        bool(args.step2_paraphrase),
        bool(args.no_step2_paraphrase),
    )
    omit_panel_background = resolve_omit_panel_background(
        bool(args.omit_panel_background), root
    )
    try:
        novelai_ref = resolve_novelai_reference(
            list(args.novelai_reference_image_paths or []),
            root,
            novel_dir=novel,
            portion_id=args.novelai_portion_id,
            cli_strength=args.novelai_reference_strength,
            cli_information_extracted=args.novelai_reference_information_extracted,
        )
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    novelai_ref_paths = novelai_ref.paths
    novelai_ref_strength = novelai_ref.strength
    novelai_ref_ie = novelai_ref.information_extracted
    novelai_ref_source = novelai_ref.source
    novelai_ref_fields = novelai_reference_job_fields(
        novelai_ref_paths if provider == "novelai" else [],
        strength=novelai_ref_strength,
        information_extracted=novelai_ref_ie,
        root=root,
    )
    if novelai_ref_paths and provider != "novelai":
        print(
            f"warning: --novelai-reference-image-path は provider={provider} では無視します",
            file=sys.stderr,
        )
    if omit_panel_background and args.source != "step1-panels":
        print(
            "warning: --omit-panel-background は step1-panels のみ有効です（無視します）",
            file=sys.stderr,
        )
        omit_panel_background = False
    include_panel_summary = resolve_include_panel_summary(
        cli_no_flag=bool(args.no_include_panel_summary),
        root=root,
        source=args.source,
    )
    try:
        input_used, jobs = iter_jobs_by_input(
            novel,
            args.manga_stem,
            args.source,
            provider,
            args.style_helper,
            args.input,
            cli_negative_prompt=args.negative_prompt,
            prompt_formatter=prompt_formatter,
            no_character_anchors=args.no_character_anchors,
            use_novelai_pipe_split=use_novelai_pipe,
            step2_paraphrase=step2_px,
            color_mode_override=args.color_mode,
            omit_panel_background=omit_panel_background,
            include_panel_summary=include_panel_summary,
        )
    except (FileNotFoundError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    if not jobs:
        print(
            "error: ジョブが0件です（YAML入力なら manga/pages/*.yaml の panels、"
            "Markdown入力なら source=step1-panels は tag:/和訳:、"
            "source=step1-pages は Step1 本文、source=step2-pages は Step2 本文の形式を確認）",
            file=sys.stderr,
        )
        return 2
    jobs = [
        job for job in jobs
        if (
            (args.min_page is None or int(job["page"]) >= args.min_page)
            and (args.max_page is None or int(job["page"]) <= args.max_page)
            and (args.min_koma is None or int(job["koma"]) >= args.min_koma)
            and (args.max_koma is None or int(job["koma"]) <= args.max_koma)
        )
    ]
    if not jobs:
        print("error: 指定範囲に該当するジョブが0件です", file=sys.stderr)
        return 2

    aspect_effective = manga_grok_pro_effective_aspect_ratio(
        args.aspect_ratio, provider, root=root
    )

    provider_cli = root / "tools" / "image_provider_generate.py"
    if not provider_cli.is_file():
        print(f"error: {provider_cli} がありません", file=sys.stderr)
        return 2

    print(f"novel: {novel}")
    print(f"input: {input_used}")
    print(f"provider: {provider}")
    print(f"prompt_formatter: {prompt_formatter}")
    if aspect_effective is not None:
        if args.aspect_ratio is not None:
            print(f"aspect_ratio: {aspect_effective} (--aspect-ratio)")
        else:
            print(
                f"aspect_ratio: {aspect_effective} "
                f"(env {MANGA_GROK_PRO_DEFAULT_ASPECT_ENV})"
            )
    print(f"jobs: {len(jobs)}")
    if omit_panel_background:
        print("omit_panel_background: true (step1-panels)")
    if include_panel_summary and args.source == "step1-panels":
        print("include_panel_summary: true (panels[].summary_en をベースタグに併用)")
    if novelai_ref_paths:
        print(
            f"novelai_reference: {len(novelai_ref_paths)} file(s) "
            f"(source={novelai_ref_source})"
        )
        for ref in novelai_ref_paths:
            print(f"  - {ref}")
        print(
            f"  strength_multiplier={novelai_ref_strength} "
            f"ie_multiplier={novelai_ref_ie}"
        )
        if novelai_ref_fields:
            rs = novelai_ref_fields.get("reference_strength_multiple", [])
            ri = novelai_ref_fields.get("reference_information_extracted_multiple", [])
            print(f"  resolved slots: {len(rs)} normalize={novelai_ref_fields.get('normalize_reference_strength_multiple')}")
            if rs:
                print(f"  reference_strength_multiple={rs}")
            if ri:
                print(f"  reference_information_extracted_multiple={ri}")
    if args.source == "step2-pages" and input_used == "yaml":
        print(f"step2_paraphrase (effective): {effective_paraphrase(step2_px)}")

    for job in jobs:
        out_dir = Path(job["output_dir"])
        if args.subdir_by_page:
            out_dir = out_dir / f"p{int(job['page']):02d}"
        out_dir_posix = out_dir.as_posix()

        payload = {
            "provider": provider,
            "prompt": job["prompt"],
            "negative_prompt": job.get("negative_prompt", args.negative_prompt),
            "output_dir": out_dir_posix,
            "file_prefix": job["prefix"],
            "count": 1,
            "seed": None,
            "prompt_formatter": job.get("prompt_formatter", prompt_formatter),
            "negative_mode": job.get("negative_mode", NATIVE_NEGATIVE),
        }
        if job.get("metadata"):
            payload["metadata"] = job["metadata"]
        if aspect_effective is not None:
            payload["aspect_ratio_preset"] = aspect_effective
        if args.resolution is not None:
            payload["resolution"] = args.resolution
        if novelai_ref_fields:
            payload.update(novelai_ref_fields)
        if args.dry_run:
            print(f"  [{job['prefix']}] -> {out_dir_posix}")
            print(
                f"    formatter: {payload['prompt_formatter']} "
                f"({payload['negative_mode']})"
            )
            print(f"    prompt[:100]: {payload['prompt'][:100]}...")
            neg_show = payload["negative_prompt"]
            if len(neg_show) > 160:
                neg_show = neg_show[:160] + "..."
            print(f"    negative: {neg_show}")
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

        import time
        r = None
        for retry_i in range(10):
            try:
                r = subprocess.run(
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
                if r.returncode == 4: # Concurrent generation is locked
                    wait_sec = 20 if retry_i >= 5 else 10
                    print(f"info: {job['prefix']} (retry {retry_i+1}/10) - HTTP 429 Concurrent generation is locked. Waiting {wait_sec}s...", file=sys.stderr)
                    time.sleep(wait_sec)
                    continue
                break
            except Exception as e:
                print(f"warning: subprocess error: {e}", file=sys.stderr)
                break

        tf_path.unlink(missing_ok=True)

        if r is None or r.returncode != 0:
            if r is not None:
                print(r.stderr or r.stdout, file=sys.stderr)
                print(
                    f"error: image provider が失敗しました ({job['prefix']}) code={r.returncode}",
                    file=sys.stderr,
                )
                return r.returncode or 1
            else:
                print(f"error: image provider の実行に失敗しました ({job['prefix']})", file=sys.stderr)
                return 1
        _safe_print_stdout(r.stdout.strip())

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
