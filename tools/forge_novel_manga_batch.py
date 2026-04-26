#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
作品フォルダの manga/manga_*.md から、各 Page の Step1 / Step2 を抽出し、
画像生成プロバイダへ連続実行する。

保存先: manga/_assets/<manga_stem>/ （既定・file_prefix は <stem>_p<page>_k<koma>）。
  --subdir-by-page 指定時は manga/_assets/<manga_stem>/p<page>/ に保存（8ページなどをフォルダ分割）。
  novel_image_layout の k01.. は「1ページ内のコマ用スロット」用の任意フォルダで、本スクリプト既定では未使用。
前提: config/image_generation.json・各 provider の準備完了（tools/forge_generate.py と同じ）

`tag/*.md` からのキャラ固定特徴の自動注入は、**`--no-character-anchors`** で無効化できる（NovelAI 等でポリシー拒否が出るとき、step1 の `tag:` だけを送りたいとき）。
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Iterable

PROVIDER_CHOICES = ("forge", "novelai", "grok")
MANGA_STEP1_PROVIDER_ENV = "MONOCRI_MANGA_STEP1_PROVIDER_DEFAULT"
MANGA_STEP2_PROVIDER_ENV = "MONOCRI_MANGA_STEP2_PROVIDER_DEFAULT"


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


STYLE_PREFIX = (
    "best quality, very aesthetic, ultra-detailed, best illustration, "
)

DEFAULT_NEGATIVE = (
    "lowres, worst quality, jpeg artifacts, blurry, bad hands, bad anatomy, "
    "extra fingers, watermark, username, text, logo"
)

STEP2_GROK_STYLE_HELPER = """\
画風補助:
- 日本の商業カラーマンガ風
- 読みやすいコマ割りと明快な視線誘導
- キャラクターの顔は安定して描写
- 背景は情報量を保ちつつ主役を邪魔しない
- 各コマの役割差が一目で分かる
- 吹き出しや文字は必要最小限で、絵として破綻しない構成
- ページ全体を1枚で完成させ、裁ち切れやコマ欠けを避ける
"""

STEP1_PAGE_GROK_STYLE_HELPER = """\
画風補助:
- 日本の商業カラーマンガ風
- 各コマ情報をなるべく落とさず精密に反映
- 各コマの人物、表情、構図、背景、距離感の差を明確に描き分ける
- コマごとの役割差が伝わるように密度と抜きを作る
- 吹き出しや文字は必要最小限で、絵として破綻しない構成
- ページ全体を1枚で完成させ、裁ち切れやコマ欠けを避ける
"""


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
    env_name = (
        MANGA_STEP2_PROVIDER_ENV
        if source == "step2-pages"
        else MANGA_STEP1_PROVIDER_ENV
    )
    env_provider = dotenv_map.get(env_name)
    if env_provider:
        return validate_provider(env_provider, source=f".env {env_name}")
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
        aliases = anchor.get("aliases", [])
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
    variants = anchor.get("variants", [])
    best_variant = variants[0] if variants else {"title": "通常時", "danbooru": anchor["danbooru"]}
    best_score = -1
    for variant in variants:
        score = 0
        title = str(variant.get("title", ""))
        if title and title in context_text:
            score += 6
        for keyword in variant.get("keywords", []):
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
    if provider == "grok" and source == "step2-pages":
        return STEP2_GROK_STYLE_HELPER.strip()
    if provider == "grok" and source == "step1-pages":
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
    all_jobs: list[dict[str, str]] = []
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
        base = (manga_dir / "_assets" / stem).resolve()
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
            j["output_dir"] = base.as_posix()
            all_jobs.append(j)
    return all_jobs


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="manga/manga_*.md の Step1/Step2 を使って画像生成"
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
        "--source",
        choices=("step1-panels", "step1-pages", "step2-pages"),
        default="step1-panels",
        help=(
            "入力元。step1-panels は Step1 の tag: をコマ単位で使用、"
            "step1-pages は Step1 全体を精密ページ生成の1ジョブとして使用、"
            "step2-pages は Step2 全体をページ単位の1ジョブとして使用"
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
        help="Forge/Grok 用の比率 preset 名または比率文字列（例: manga_b5_portrait, portrait, 3:4, 9:16）",
    )
    p.add_argument(
        "--resolution",
        default=None,
        help="Grok 用の解像度（例: 1k, 2k）",
    )
    p.add_argument(
        "--subdir-by-page",
        action="store_true",
        help="保存先を manga/_assets/<stem>/p01, p02, ...（Page 番号）の下に分ける",
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
        "--style-helper",
        default=None,
        help=(
            "step1-pages / step2-pages 用の追加画風補助文。未指定時は"
            " provider=grok ならページ生成向け補助文を自動付与"
        ),
    )
    p.add_argument("--min-page", type=int, default=None, help="処理する Page 番号の下限（含む）")
    p.add_argument("--max-page", type=int, default=None, help="処理する Page 番号の上限（含む）")
    p.add_argument("--min-koma", type=int, default=None, help="処理するコマ番号の下限（含む）。ページ生成ジョブは koma=0")
    p.add_argument("--max-koma", type=int, default=None, help="処理するコマ番号の上限（含む）。ページ生成ジョブは koma=0")
    args = p.parse_args(argv)

    root = repo_root()
    novel = args.novel_dir
    if not novel.is_absolute():
        novel = (root / novel).resolve()
    if not novel.is_dir():
        print(f"error: ディレクトリがありません: {novel}", file=sys.stderr)
        return 2
    try:
        provider = resolve_batch_provider(root, args.source, args.provider)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    try:
        jobs = iter_manga_jobs(
            novel,
            args.manga_stem,
            args.source,
            provider,
            args.style_helper,
            no_character_anchors=args.no_character_anchors,
        )
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    if not jobs:
        print(
            "error: ジョブが0件です（source=step1-panels なら tag:/和訳:、"
            "source=step1-pages なら Step1 本文、source=step2-pages なら"
            " Step2 本文の形式を確認）",
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

    forge = root / "tools" / "forge_generate.py"
    if not forge.is_file():
        print(f"error: {forge} がありません", file=sys.stderr)
        return 2

    print(f"novel: {novel}")
    print(f"provider: {provider}")
    print(f"jobs: {len(jobs)}")

    for job in jobs:
        out_dir = Path(job["output_dir"])
        if args.subdir_by_page:
            out_dir = out_dir / f"p{int(job['page']):02d}"
        out_dir_posix = out_dir.as_posix()

        payload = {
            "provider": provider,
            "prompt": job["prompt"],
            "negative_prompt": args.negative_prompt,
            "output_dir": out_dir_posix,
            "file_prefix": job["prefix"],
            "count": 1,
            "seed": None,
        }
        if args.aspect_ratio is not None:
            payload["aspect_ratio_preset"] = args.aspect_ratio
        if args.resolution is not None:
            payload["resolution"] = args.resolution
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
