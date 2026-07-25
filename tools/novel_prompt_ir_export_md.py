#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Export manga-prompt-ir YAML/JSON into legacy Markdown-compatible files."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import yaml

_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))
from image_provider_novel_manga_batch import (
    build_step2_panel_line,
    comma_split_tags,
    filter_single_panel_tags,
    join_novelai_pipe_tag_line,
    yaml_panel_tags,
    yaml_panel_tags_novelai_split,
)
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
from manga_prompt_ir.color_mode import (
    VALID_COLOR_MODES,
    page_color_mode_label,
)
from manga_prompt_ir.user_directives import (
    apply_to_tags as apply_user_directives_to_tags,
)

STYLE_TAGS = ["best_quality", "very_aesthetic", "ultra-detailed", "manga"]


def load_data(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        data = json.loads(text)
    else:
        data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError(f"IR root must be a mapping: {path}")
    return data


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def normalize_tag(value: Any) -> str:
    return str(value).strip().replace(" ", "_")


def join_tags(values: list[Any]) -> str:
    return ", ".join(unique([normalize_tag(value) for value in values if value]))


def selected_subject_variant_id(subject: dict[str, Any]) -> str | None:
    for key in ("prompt_variant_id", "costume_variant", "variant_id"):
        value = subject.get(key)
        if value:
            return str(value)
    return None


def find_character_variant(character: dict[str, Any], variant_id: str | None) -> dict[str, Any] | None:
    if not variant_id:
        return None
    for variant in as_list(character.get("prompt_variants")):
        if isinstance(variant, dict) and variant.get("variant_id") == variant_id:
            return variant
    return None


def base_danbooru_tags(character: dict[str, Any]) -> list[str]:
    """固定外見の正本は ``000_base``（_how_to.example/tag.md）。"""
    from manga_prompt_ir.character_fixed_tags import base_fixed_tags_from

    return unique([normalize_tag(t) for t in base_fixed_tags_from(character)])


def resolve_variant_danbooru_tags(character: dict[str, Any], variant_id: str | None = None) -> list[str]:
    from manga_prompt_ir.character_fixed_tags import resolve_variant_danbooru_tags as _resolve

    return unique([normalize_tag(t) for t in _resolve(character, variant_id)])


def snapshot_key(character_id: str | None, variant_id: str | None) -> tuple[str, str]:
    return (str(character_id or ""), str(variant_id or ""))


def page_snapshot_map(page: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    snapshots: dict[tuple[str, str], dict[str, Any]] = {}
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


def subject_snapshot(page: dict[str, Any], subject: dict[str, Any]) -> dict[str, Any] | None:
    cid = subject.get("character_id")
    if not cid:
        return None
    snapshots = page_snapshot_map(page)
    variant_id = selected_subject_variant_id(subject)
    return snapshots.get(snapshot_key(str(cid), variant_id)) or snapshots.get(snapshot_key(str(cid), None))


def snapshot_tags(snapshot: dict[str, Any]) -> list[str]:
    tags: list[str] = []
    tags.extend(str(v) for v in as_list(snapshot.get("fixed_tags")))
    tags.extend(str(v) for v in as_list(snapshot.get("variant_tags")))
    return unique(tags)


_VARIANT_ID_NUM = re.compile(r"^(\d+)_")


def variant_heading_index(variant: dict[str, Any], one_based_fallback: int) -> int:
    """`00_base` → 0, `01_normal` → 1。番号なし ID は従来どおり 1 始まりの連番。"""
    vid = str(variant.get("variant_id") or "")
    m = _VARIANT_ID_NUM.match(vid)
    if m:
        return int(m.group(1))
    return one_based_fallback


def character_variant_danbooru_line(
    variant: dict[str, Any],
    variants: list[Any],
    character: dict[str, Any],
    *,
    novelai_pipe_tags: bool,
) -> str:
    """バッチ実出力と同じ合成結果を記載する（image_provider_novel_tag_batch.compose_job_prompt 準拠）。

    - 100番台 + combines_with + NovelAI: ``資料 | 000_base+結合先``（パイプ）
    - それ以外の combines_with 持ち（000番台等）: ``状況タグ, 000_base, 結合先`` のカンマ合成
    - combines_with なし: 状況タグのみ（000〜099 は生成時に 000_base が前置される）
    """
    tags = as_list(variant.get("danbooru_tags"))
    combines_raw = variant.get("combines_with")
    combines = str(combines_raw).strip() if combines_raw else ""
    vid = str(variant.get("variant_id") or "")
    if combines:
        from image_provider_novel_tag_batch import (  # noqa: E402
            danbooru_for_combines_with,
            is_reference_slot,
        )

        right = danbooru_for_combines_with(
            [v for v in variants if isinstance(v, dict)],
            combines,
            character,
        )
        if novelai_pipe_tags and is_reference_slot(vid):
            return join_novelai_pipe_tag_line(tags, [right])
        return join_tags(unique([*[str(t) for t in tags], *right]))
    return join_tags(tags)


def render_character_md(
    character: dict[str, Any],
    *,
    novelai_pipe_tags: bool = False,
) -> str:
    character_id = character["character_id"]
    name = character.get("name") or character_id
    name_en = character.get("name_en") or character_id
    role = character.get("role") or ""
    appearance = character.get("appearance") or {}
    costume = character.get("costume") or {}
    personality = character.get("personality") or {}
    rules = character.get("manga_rules") or {}
    variants = as_list(character.get("prompt_variants"))
    base_tags = base_danbooru_tags(character)
    summary_parts = [
        f"役割: {role}" if role else "",
        f"外見: {appearance.get('age_range')}, {appearance.get('body_type')}, {appearance.get('hair_color')} hair, {appearance.get('eye_color')} eyes",
        f"衣装: {costume.get('main_outfit')}",
        f"口調: {personality.get('speech_style')}",
    ]
    summary = " / ".join(part for part in summary_parts if part and "None" not in part)
    do_not_change = as_list(rules.get("do_not_change"))

    lines = [
        f"# {name}（{name_en}）",
        "",
        "## 構造化IR由来メモ",
        f"- character_id: `{character_id}`",
        f"- 概要: {summary or '構造化IRから生成'}",
        f"- 固定特徴（000_base 正本）: {', '.join(str(v) for v in base_tags) or 'なし'}",
        "- バッチ合成: 000〜099 は 000_base + 状況タグ（combines_with 持ちは 状況タグ + 000_base + 結合先を合成済みで記載）。100番台は 資料タグ | combines_with（000_base+結合先）",
        f"- 変更禁止: {', '.join(str(v) for v in do_not_change) or 'なし'}",
        f"- Negative Tags: {', '.join(str(v) for v in as_list(character.get('negative_tags'))) or 'なし'}",
        "",
    ]
    if variants:
        for index, variant in enumerate(variants, start=1):
            if not isinstance(variant, dict):
                continue
            heading_n = variant_heading_index(variant, index)
            tag_line = character_variant_danbooru_line(
                variant,
                variants,
                character,
                novelai_pipe_tags=novelai_pipe_tags,
            )
            block = [
                f"## {heading_n}. {variant.get('title') or variant.get('variant_id') or '状況'}",
                f"説明: {variant.get('description') or '構造化IRの状況別タグ。'}",
            ]
            combines = variant.get("combines_with")
            if combines:
                block.append(f"**組み合わせ**: `{combines}`")
            block.extend(
                [
                    "",
                    "**Danbooru Tags:**",
                    tag_line,
                    "",
                    "**Caption:**",
                    str(variant.get("caption") or f"{name_en}, consistent character design."),
                    "",
                    "**和訳:**",
                    str(variant.get("translation") or f"{name}の状況別描写。"),
                    "",
                ]
            )
            lines.extend(block)
        return "\n".join(lines).rstrip() + "\n"

    normal_tags = join_tags(STYLE_TAGS + [name_en] + base_tags)
    closeup_tags = join_tags(STYLE_TAGS + [name_en, "portrait", "close-up", "detailed_eyes"] + base_tags)
    lines.extend(
        [
            "## 1. 通常時",
            "説明: 構造化IRの 000_base / variant を統合した通常立ち絵。",
            "",
            "**Danbooru Tags:**",
            normal_tags,
            "",
            "**Caption:**",
            f"{name_en}, {summary or 'character reference sheet'}, consistent character design.",
            "",
            "**和訳:**",
            f"{name}の通常時。固定特徴と衣装を優先して描写する。",
            "",
            "## 2. 表情アップ",
            "説明: 顔・目元・固定特徴を確認するためのアップ。髪色、目色、肌、固定小物を維持する。",
            "",
            "**Danbooru Tags:**",
            closeup_tags,
            "",
            "**Caption:**",
            f"Close-up portrait of {name_en}, stable face, clear eyes, consistent fixed features.",
            "",
            "**和訳:**",
            f"{name}の表情アップ。別人化を防ぐため固定特徴を残す。",
        ]
    )
    return "\n".join(lines) + "\n"


def subject_text(subject: dict[str, Any], characters: dict[str, dict[str, Any]]) -> str:
    cid = subject.get("character_id")
    if cid and cid in characters:
        character = characters[cid]
        base = f"{character.get('name') or cid}（{character.get('name_en') or cid}）"
    else:
        base = str(subject.get("description") or subject.get("type") or "subject")
    details = [
        str(subject.get("description") or ""),
        str(subject.get("pose_action") or ""),
        str(subject.get("expression") or ""),
        str(subject.get("position") or ""),
    ]
    return "、".join([base] + [value for value in details if value])


def panel_tags(page: dict[str, Any], panel: dict[str, Any], characters: dict[str, dict[str, Any]]) -> list[str]:
    """互換 Markdown の Step1 タグ行用。生成バッチの yaml_panel_tags に委譲（人名単独タグなし）。"""
    return yaml_panel_tags(page, panel, characters, single_panel=True)


def panel_tag_line_for_export(
    page: dict[str, Any],
    panel: dict[str, Any],
    characters: dict[str, dict[str, Any]],
    *,
    novelai_pipe_tags: bool,
) -> str:
    """Step1 のタグ1行。novelai_pipe_tags 時は image provider と同じ base | キャラごとのセグメント分割。"""
    if novelai_pipe_tags:
        btags, char_segs = yaml_panel_tags_novelai_split(page, panel, characters, single_panel=True)
        return join_novelai_pipe_tag_line(btags, char_segs)
    return join_tags(panel_tags(page, panel, characters))


def render_text_block(panel: dict[str, Any]) -> list[str]:
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


def illustration_asset_stem(path: Path) -> str:
    return re.sub(r"_p\d+$", "", path.stem)


def render_illustration_page_section(
    page_path: Path | None,
    page: dict[str, Any],
    characters: dict[str, dict[str, Any]],
    *,
    novelai_pipe_tags: bool = False,
    color_mode_override: str | None = None,
) -> str:
    meta = page.get("meta") or {}
    manga = page.get("manga") or {}
    scene = page.get("scene") or {}
    render_inst = page.get("render_instruction") or {}
    technical = page.get("technical") or {}
    loc_s, tod_s, _wx_s = scene_prompt_location_time_weather(scene)
    panels = as_list(page.get("panels"))
    panel = panels[0] if panels and isinstance(panels[0], dict) else {}
    color_label = page_color_mode_label(page, override=color_mode_override)
    page_label = page_path.stem if page_path else "page"
    lines = [
        f"## {page_label}",
        "",
        f"- intent: {meta.get('intent', 'illustration')}",
    ]
    for key in ("source_anchor", "illustration_type", "aspect_ratio"):
        value = meta.get(key)
        if value:
            lines.append(f"- {key}: {value}")
    lines.extend(
        [
            f"- 色モード: {color_label}",
            f"- 舞台: {loc_s} / {tod_s} / {scene_prompt_background_notes(scene)}",
        ]
    )
    if manga.get("panel_layout"):
        lines.append(f"- 構図方針: {manga.get('panel_layout')}")
    for label, key in (
        ("生成タスク", "task"),
        ("プロンプト冒頭", "prompt_header"),
        ("出力方針", "output_policy"),
    ):
        value = render_inst.get(key)
        if value:
            lines.extend(["", f"**{label}:**", str(value)])
    if panel:
        subjects = [
            subject_text(subject, characters)
            for subject in as_list(panel.get("subjects"))
            if isinstance(subject, dict)
        ]
        comp = panel.get("composition") or {}
        camera = panel.get("camera") or {}
        lines.extend(
            [
                "",
                f"**概要:** {panel.get('summary', '')}",
                f"- 人物・対象: {' / '.join(subjects) if subjects else '—'}",
                f"- 構図: {comp.get('layout', '')} / {comp.get('framing', '')} / {comp.get('focus', '')} / {camera.get('angle', '')}",
                "",
                "**Danbooru Tags:**",
                f"`{panel_tag_line_for_export(page, panel, characters, novelai_pipe_tags=novelai_pipe_tags)}`",
            ]
        )
        translation = panel.get("translation") or panel.get("summary", "")
        if translation:
            lines.append(f"（日本語訳：{translation}）")
    neg = technical.get("negative_tags")
    if neg:
        lines.extend(["", "**Negative Tags:**", join_tags(as_list(neg))])
    return "\n".join(lines) + "\n"


def render_illustration_md(
    pages: Sequence[tuple[Path | None, dict[str, Any]]],
    characters: dict[str, dict[str, Any]],
    *,
    title: str,
    novelai_pipe_tags: bool = False,
    color_mode_override: str | None = None,
) -> str:
    lines = [f"# {title}", ""]
    ir_paths = [path for path, _page in pages if path is not None]
    if ir_paths:
        lines.extend(
            [
                "<!-- illustration-prompt-ir互換ヘッダ: この illustration_XX.md は既存バッチ向けMarkdown互換出力です。構造化IR正本は illustrations/pages/*.yaml を参照してください。 -->",
                "",
                "## IR正本",
                "",
            ]
        )
        for path in ir_paths:
            lines.append(f"- `{path.as_posix()}`")
        lines.append("")
    for page_path, page in pages:
        lines.append(
            render_illustration_page_section(
                page_path,
                page,
                characters,
                novelai_pipe_tags=novelai_pipe_tags,
                color_mode_override=color_mode_override,
            ).rstrip()
        )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def group_illustration_pages(
    pages: Sequence[tuple[Path, dict[str, Any]]],
) -> dict[str, list[tuple[Path | None, dict[str, Any]]]]:
    groups: dict[str, list[tuple[Path | None, dict[str, Any]]]] = {}
    for path, page in pages:
        stem = illustration_asset_stem(path)
        groups.setdefault(stem, []).append((path, page))
    for stem in groups:
        groups[stem].sort(key=lambda item: (item[0].name if item[0] else ""))
    return groups


def render_manga_page_section(
    page: dict[str, Any],
    characters: dict[str, dict[str, Any]],
    *,
    page_number: int,
    novelai_pipe_tags: bool = False,
    apply_paraphrase: bool | None = None,
    color_mode_override: str | None = None,
) -> str:
    meta = page.get("meta") or {}
    manga = page.get("manga") or {}
    scene = page.get("scene") or {}
    loc_s, tod_s, _wx_s = scene_prompt_location_time_weather(scene)
    panels = as_list(page.get("panels"))
    reading_order = meta.get("reading_order", "right_to_left")
    panel_layout = manga.get("panel_layout") or f"{len(panels)}コマ構成"
    color_label = page_color_mode_label(page, override=color_mode_override)
    lines = [
        f"## Page {page_number}",
        "",
        "### Step1",
        f"{color_label}、日本の漫画のコマ割り、1ページ{len(panels)}コマ、読み順: {reading_order}",
        f"ページ構成: {panel_layout}",
        f"共通舞台: {loc_s} / {tod_s} / {scene_prompt_background_notes(scene)}",
        "",
    ]
    for panel in panels:
        if not isinstance(panel, dict):
            continue
        panel_id = panel.get("panel_id", "?")
        subjects = [subject_text(subject, characters) for subject in as_list(panel.get("subjects")) if isinstance(subject, dict)]
        comp = panel.get("composition") or {}
        camera = panel.get("camera") or {}
        lines.extend(
            [
                f"**コマ{panel_id}: {panel.get('summary', '')}**",
                f"- 人物・対象: {' / '.join(subjects)}",
                f"- 構図: {comp.get('layout', '')} / {comp.get('framing', '')} / {comp.get('focus', '')} / {camera.get('angle', '')}",
                *render_text_block(panel),
                "- **tag**：",
                f"`{panel_tag_line_for_export(page, panel, characters, novelai_pipe_tags=novelai_pipe_tags)}`",
                f"（日本語訳：{panel.get('translation') or panel.get('summary', '')}）",
                "",
            ]
        )
    lines.extend(["### Step2", f"{color_label}、日本の漫画のコマ割り、1ページ{len(panels)}コマ。{panel_layout}。numbered panels、読み順は {reading_order}。"])
    for panel in panels:
        if isinstance(panel, dict):
            lines.append(
                build_step2_panel_line(page, panel, characters, apply_paraphrase=apply_paraphrase)
            )
    return "\n".join(lines) + "\n"


def render_manga_md(
    pages: list[tuple[Path | None, dict[str, Any]]],
    characters: dict[str, dict[str, Any]],
    *,
    title: str,
    novelai_pipe_tags: bool = False,
    apply_paraphrase: bool | None = None,
    color_mode_override: str | None = None,
) -> str:
    lines = [f"# {title}", ""]
    ir_paths = [path for path, _page in pages if path is not None]
    if ir_paths:
        lines.extend(
            [
                "<!-- manga-prompt-ir互換ヘッダ: このmanga_XX.mdは既存バッチ向けMarkdown互換出力です。構造化IR正本は manga/pages/*.yaml を参照してください。 -->",
                "",
                "## IR正本",
                "",
            ]
        )
        for path in ir_paths:
            lines.append(f"- `{path.as_posix()}`")
        lines.append("")
    for index, (_path, page) in enumerate(pages, start=1):
        lines.append(
            render_manga_page_section(
                page,
                characters,
                page_number=index,
                novelai_pipe_tags=novelai_pipe_tags,
                apply_paraphrase=apply_paraphrase,
                color_mode_override=color_mode_override,
            ).rstrip()
        )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_or_print(path: Path | None, text: str) -> None:
    if path is None:
        print(text)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    print(f"wrote: {path}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export manga-prompt-ir YAML/JSON to legacy Markdown")
    parser.add_argument("--character", type=Path, action="append", default=[])
    parser.add_argument("--manga-page", type=Path, action="append", default=[])
    parser.add_argument("--illustration-page", type=Path, action="append", default=[])
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--manga-stem", default="manga_01")
    parser.add_argument(
        "--illustration-stem",
        default=None,
        help="出力ファイル名 stem（illustration_XX）。未指定時は YAML ファイル名から自動判定",
    )
    parser.add_argument("--title", default="IR互換漫画ページ")
    parser.add_argument(
        "--illustration-title",
        default=None,
        help="挿絵 MD の見出し（未指定時は illustration stem から生成）",
    )
    parser.add_argument(
        "--no-character-output",
        action="store_true",
        help="--character は漫画タグ参照にだけ使い、tag/<character_id>.md を出力しない",
    )
    parser.add_argument(
        "--novelai-pipe-tags",
        action="store_true",
        help=(
            "Step1 の tag 行を NovelAI 向け「ベース | キャラクター」形式で出力する"
            "（image_provider_novel_manga_batch の YAML step1-panels・novelai と同じ分割）"
        ),
    )
    parser.add_argument(
        "--step2-paraphrase",
        action="store_true",
        help=(
            "Step2 行へ manga_tag_step2 と同期した置換ルールを適用。"
            " 環境変数 MONOCRI_STEP2_PARAPHRASE=1 でも有効"
        ),
    )
    parser.add_argument(
        "--no-step2-paraphrase",
        action="store_true",
        help="Step2 自動置換を無効にする（環境変数より優先）",
    )
    parser.add_argument(
        "--color-mode",
        choices=VALID_COLOR_MODES,
        default=None,
        help=(
            "この export 実行だけの色モード上書き。YAML は書き換えず、"
            "Step1/Step2 の冒頭文にだけ反映する"
        ),
    )
    args = parser.parse_args(argv)

    characters: dict[str, dict[str, Any]] = {}
    for character_path in args.character:
        character = load_data(character_path)
        if "character_id" not in character:
            raise ValueError(f"invalid character IR: {character_path}")
        characters[str(character["character_id"])] = character
        if args.output_dir and not args.no_character_output:
            write_or_print(
                args.output_dir / "tag" / f"{character['character_id']}.md",
                render_character_md(character, novelai_pipe_tags=args.novelai_pipe_tags),
            )
        elif not args.output_dir:
            write_or_print(
                None,
                render_character_md(character, novelai_pipe_tags=args.novelai_pipe_tags),
            )

    if args.manga_page:
        from manga_prompt_ir.step2_paraphrase import resolve_step2_paraphrase_flag

        step2_px = resolve_step2_paraphrase_flag(
            bool(args.step2_paraphrase),
            bool(args.no_step2_paraphrase),
        )
        pages: list[tuple[Path | None, dict[str, Any]]] = []
        for manga_page_path in args.manga_page:
            page = load_data(manga_page_path)
            if "panels" not in page:
                raise ValueError(f"invalid manga page IR: {manga_page_path}")
            pages.append((manga_page_path, page))
        out_path = args.output_dir / "manga" / f"{args.manga_stem}.md" if args.output_dir else None
        write_or_print(
            out_path,
            render_manga_md(
                pages,
                characters,
                title=args.title,
                novelai_pipe_tags=args.novelai_pipe_tags,
                apply_paraphrase=step2_px,
                color_mode_override=args.color_mode,
            ),
        )
    elif args.illustration_page:
        ill_pages: list[tuple[Path, dict[str, Any]]] = []
        for illustration_page_path in args.illustration_page:
            page = load_data(illustration_page_path)
            if "panels" not in page:
                raise ValueError(f"invalid illustration page IR: {illustration_page_path}")
            meta = page.get("meta") or {}
            if meta.get("intent") not in (None, "illustration"):
                raise ValueError(
                    f"meta.intent must be illustration (or omitted): {illustration_page_path}"
                )
            ill_pages.append((illustration_page_path, page))
        if args.illustration_stem:
            stem = args.illustration_stem
            grouped = {stem: [(p, pg) for p, pg in ill_pages]}
        else:
            grouped = group_illustration_pages(ill_pages)
        for stem, group in sorted(grouped.items()):
            title = args.illustration_title or f"挿絵 {stem}"
            out_path = (
                args.output_dir / "illustrations" / f"{stem}.md" if args.output_dir else None
            )
            write_or_print(
                out_path,
                render_illustration_md(
                    group,
                    characters,
                    title=title,
                    novelai_pipe_tags=args.novelai_pipe_tags,
                    color_mode_override=args.color_mode,
                ),
            )
    elif not characters:
        parser.error("--character or --manga-page or --illustration-page is required")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
