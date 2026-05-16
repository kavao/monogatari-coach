#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Validate manga/illustration prompt IR YAML files with the Pydantic schemas."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml


ABSTRACT_ONLY_SUMMARIES = {
    "接触",
    "忍耐",
    "緊張",
    "不穏",
    "対立",
    "葛藤",
    "沈黙",
    "驚き",
    "疑念",
    "決意",
}

PARTIAL_CUT_WORDS = ("手元", "手", "足", "口元", "目元", "横顔", "スマホ画面", "画面", "close-up", "アップ")


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def load_models():
    tools_dir = Path(__file__).resolve().parent
    sys.path.insert(0, str(tools_dir))
    from manga_prompt_ir.schemas.character import CharacterPrompt
    from manga_prompt_ir.schemas.manga_page import MangaPagePrompt

    return CharacterPrompt, MangaPagePrompt


def load_color_validator():
    tools_dir = Path(__file__).resolve().parent
    sys.path.insert(0, str(tools_dir))
    from manga_prompt_ir.color_mode import validate_color_consistency

    return validate_color_consistency


def load_yaml(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"YAML root must be a mapping: {path}")
    return data


def collect_files(args: argparse.Namespace) -> tuple[list[Path], list[Path]]:
    character_files = [Path(p) for p in args.character]
    page_files = [Path(p) for p in args.manga_page]
    page_files.extend(Path(p) for p in args.illustration_page)
    if args.novel_dir:
        novel_dir = Path(args.novel_dir)
        if not novel_dir.is_absolute():
            novel_dir = (repo_root() / novel_dir).resolve()
        character_files.extend(sorted((novel_dir / "tag" / "characters").glob("*.yaml")))
        page_files.extend(sorted((novel_dir / "manga" / "pages").glob("*.yaml")))
        page_files.extend(sorted((novel_dir / "illustrations" / "pages").glob("*.yaml")))
    return character_files, page_files


def has_text(value: str | None) -> bool:
    return bool(value and value.strip())


def effective_step2_summary_text(panel) -> str:
    """Step2 互換行に載る要約。`step2_summary` があれば優先、なければ `summary`。"""
    s2 = getattr(panel, "step2_summary", None)
    if s2 is not None and str(s2).strip():
        return str(s2).strip()
    return str(panel.summary or "").strip()


def is_human_subject(subject) -> bool:
    subject_type = str(getattr(subject, "type", "human") or "human").lower()
    return subject_type in {"human", "person", "character"}


def subject_variant_id(subject) -> str | None:
    return subject.prompt_variant_id or subject.costume_variant or subject.variant_id


def snapshot_key(character_id: str | None, variant_id: str | None) -> tuple[str, str]:
    return (str(character_id or ""), str(variant_id or ""))


def page_snapshot_keys(page) -> set[tuple[str, str]]:
    keys: set[tuple[str, str]] = set()
    for snapshot in page.character_snapshots:
        keys.add(snapshot_key(snapshot.character_id, snapshot.selected_variant_id))
        keys.add(snapshot_key(snapshot.character_id, None))
    return keys


def _user_directive_warnings_for_page(label: str, page) -> list[str]:
    """`render_instruction.user_directives` と panel 上書きの整合性を点検する。"""
    warnings: list[str] = []
    directives = page.render_instruction.user_directives
    defaults = directives.defaults
    page_required = [str(t) for t in defaults.required_prompt_tags if t]
    page_omit = [str(t) for t in defaults.omit_prompt_tags if t]
    page_required_set = set(page_required)
    page_omit_set = set(page_omit)

    overlap = sorted(page_required_set & page_omit_set)
    if overlap:
        warnings.append(
            f"{label}: render_instruction.user_directives.defaults で "
            f"required_prompt_tags と omit_prompt_tags の両方に同じタグがあります: "
            f"{', '.join(overlap)}"
        )

    for panel in page.panels:
        prefix = f"{label}: panel {panel.panel_id}"
        panel_required = [str(t) for t in panel.required_prompt_tags if t]
        panel_omit = [str(t) for t in panel.omit_prompt_tags if t]
        panel_required_set = set(panel_required)
        panel_omit_set = set(panel_omit)

        panel_overlap = sorted(panel_required_set & panel_omit_set)
        if panel_overlap:
            warnings.append(
                f"{prefix}: required_prompt_tags と omit_prompt_tags の両方に同じタグがあります: "
                f"{', '.join(panel_overlap)}"
            )

        cross_overlap = sorted(panel_required_set & page_omit_set)
        if cross_overlap:
            warnings.append(
                f"{prefix}: required_prompt_tags にページ既定の omit_prompt_tags と衝突するタグがあります: "
                f"{', '.join(cross_overlap)}"
            )

        cross_omit = sorted(panel_omit_set & page_required_set)
        if cross_omit:
            warnings.append(
                f"{prefix}: omit_prompt_tags にページ既定の required_prompt_tags と衝突するタグがあります: "
                f"{', '.join(cross_omit)}"
            )

        prompt_tags = [str(t) for t in panel.prompt_tags if t]
        merged_omit = panel_omit_set | page_omit_set
        in_prompt = sorted({t for t in prompt_tags if t in merged_omit})
        if in_prompt:
            warnings.append(
                f"{prefix}: prompt_tags に omit_prompt_tags のタグが含まれています "
                f"（生成時に自動除去されますが、指示の二重記載です）: "
                f"{', '.join(in_prompt)}"
            )

    return warnings


def quality_warnings_for_page(
    path: Path,
    page,
    character_variants: dict[str, set[str]],
    *,
    validate_color_consistency,
    color_page_data: dict | None = None,
) -> list[str]:
    warnings: list[str] = []
    label = path.as_posix()
    is_illustration = getattr(page.meta, "intent", None) == "illustration"
    warnings.extend(_user_directive_warnings_for_page(label, page))
    render_instruction = page.render_instruction
    has_render_instruction = any(
        has_text(value)
        for value in [
            render_instruction.task,
            render_instruction.prompt_header,
            render_instruction.panel_policy,
            render_instruction.character_policy,
            render_instruction.text_policy,
            render_instruction.output_policy,
        ]
    ) or bool(render_instruction.notes)
    if not has_render_instruction:
        warnings.append(f"{label}: render_instruction が空です（YAML単体の作画依頼として弱くなります）")
    if not has_text(render_instruction.prompt_header):
        warnings.append(f"{label}: render_instruction.prompt_header が空です（外部の冒頭依頼文に依存します）")
    if not has_text(render_instruction.panel_policy):
        if is_illustration:
            warnings.append(f"{label}: render_instruction.panel_policy が空です（構成セルの扱いが弱くなります）")
        else:
            warnings.append(f"{label}: render_instruction.panel_policy が空です（コマ割り指示が弱くなります）")
    if not has_text(render_instruction.character_policy):
        warnings.append(f"{label}: render_instruction.character_policy が空です（キャラクター外見継承が弱くなります）")
    if not has_text(page.manga.panel_layout):
        if is_illustration:
            warnings.append(f"{label}: manga.panel_layout が空です（一枚絵としての空間配置・枠線有無が弱くなります）")
        else:
            warnings.append(f"{label}: manga.panel_layout が空です（ページ内の段・大小・読み順が弱くなります）")
    if is_illustration and len(page.panels) > 1:
        warnings.append(
            f"{label}: illustration の panels[] が複数あります。群像・複合構図なら問題ありませんが、単体挿絵は1セルを推奨します"
        )
    if is_illustration:
        layout_text = str(page.manga.panel_layout or "")
        negative_tags = {str(tag).lower() for tag in page.technical.negative_tags}
        omitted_tags = {
            str(tag).lower()
            for tag in page.render_instruction.user_directives.defaults.omit_prompt_tags
        }
        suppresses_borders = any(
            "comic panel" in tag or "panel border" in tag or "panel borders" in tag
            for tag in negative_tags | omitted_tags
        )
        declares_no_borders = any(
            word in layout_text
            for word in ("枠線なし", "枠なし", "パネル境界なし", "セル境界なし")
        )
        declares_borders = any(word in layout_text for word in ("枠あり", "装飾枠", "分割画面", "split screen"))
        if declares_borders and suppresses_borders:
            warnings.append(
                f"{label}: 枠線を使う意図が manga.panel_layout にありますが、omit/negative 側で枠線系タグを抑止しています"
            )
        if not declares_borders and not declares_no_borders and not suppresses_borders:
            warnings.append(
                f"{label}: illustration は既定で枠線なしです。manga.panel_layout か omit/negative_tags で枠線方針を明示してください"
            )
    for color_warning in validate_color_consistency(color_page_data or page, root=repo_root()):
        warnings.append(f"{label}: {color_warning}")

    declared_ids = set(page.character_ids)
    used_ids: set[str] = set()
    snapshot_keys = page_snapshot_keys(page)
    snapshot_ids = {snapshot.character_id for snapshot in page.character_snapshots}
    for panel in page.panels:
        prefix = f"{label}: panel {panel.panel_id}"
        step2_text = effective_step2_summary_text(panel)
        if step2_text in ABSTRACT_ONLY_SUMMARIES:
            summary_label = "セル要約" if is_illustration else "Step2 用要約（step2_summary 優先、なければ summary）"
            warnings.append(
                f"{prefix}: {summary_label}が抽象語のみです: {step2_text!r}"
            )
        if any(word in step2_text for word in PARTIAL_CUT_WORDS):
            has_owner = any(
                has_text(subject.character_id) or any(name in subject.description for name in ("の", "が", "を"))
                for subject in panel.subjects
            )
            if not has_owner:
                warnings.append(
                    f"{prefix}: 部分アップらしい Step2 用要約ですが、所有者や意味づけが弱い可能性があります"
                )

        if not panel.subjects:
            warnings.append(f"{prefix}: subjects[] が空です")
        for index, subject in enumerate(panel.subjects, start=1):
            subject_prefix = f"{prefix}: subject {index}"
            if subject.character_id:
                used_ids.add(subject.character_id)
                variant_id = subject_variant_id(subject)
                if variant_id and variant_id not in character_variants.get(subject.character_id, set()):
                    warnings.append(
                        f"{subject_prefix}: variant_id {variant_id!r} が tag/characters/{subject.character_id}.yaml の prompt_variants にありません"
                    )
                if snapshot_key(subject.character_id, variant_id) not in snapshot_keys:
                    warnings.append(
                        f"{subject_prefix}: character_snapshots に character_id={subject.character_id!r}, variant_id={variant_id!r} のスナップショットがありません"
                    )
            if is_human_subject(subject) and not has_text(subject.character_id):
                warnings.append(f"{subject_prefix}: 人物subjectに character_id がありません")
            if not has_text(subject.description):
                warnings.append(f"{subject_prefix}: description が空です")
            if not has_text(subject.pose_action):
                warnings.append(f"{subject_prefix}: pose_action が空です（何をしている瞬間かが弱くなります）")

        comp = panel.composition
        camera = panel.camera
        has_composition = any(
            has_text(value)
            for value in [
                comp.layout,
                comp.layout_en,
                comp.framing,
                comp.framing_en,
                comp.focus,
                comp.focus_en,
                comp.perspective,
                comp.perspective_en,
                camera.angle,
                camera.angle_en,
                camera.shot_size,
                camera.shot_size_en,
            ]
        )
        if not has_composition:
            warnings.append(f"{prefix}: composition/camera の構図情報が空です")

        if not panel.prompt_tags:
            warnings.append(f"{prefix}: prompt_tags が空です（生成時の個別演出が弱くなります）")

        for dialogue_index, dialogue in enumerate(panel.text.dialogue, start=1):
            if not has_text(dialogue.speaker):
                warnings.append(f"{prefix}: dialogue {dialogue_index} の speaker が空です")
            if not has_text(dialogue.content):
                warnings.append(f"{prefix}: dialogue {dialogue_index} の content が空です")

    missing_from_declaration = sorted(used_ids - declared_ids)
    unused_declaration = sorted(declared_ids - used_ids)
    if missing_from_declaration:
        warnings.append(
            f"{label}: panels[].subjects[].character_id が character_ids にありません: {', '.join(missing_from_declaration)}"
        )
    if unused_declaration:
        warnings.append(
            f"{label}: character_ids に宣言されていますが、このページのsubjectsで未使用です: {', '.join(unused_declaration)}"
        )
    missing_snapshot_ids = sorted(used_ids - snapshot_ids)
    if missing_snapshot_ids:
        warnings.append(
            f"{label}: 使用キャラクターに対する character_snapshots がありません: {', '.join(missing_snapshot_ids)}"
        )
    return warnings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate manga/illustration prompt IR YAML files")
    parser.add_argument("novel_dir", nargs="?", help="Novel directory containing tag/characters, manga/pages, and illustrations/pages")
    parser.add_argument("--character", action="append", default=[], help="Character YAML file")
    parser.add_argument("--manga-page", action="append", default=[], help="Manga page YAML file")
    parser.add_argument("--illustration-page", action="append", default=[], help="Illustration YAML file")
    parser.add_argument(
        "--strict-quality",
        action="store_true",
        help="意味品質の警告も失敗扱いにする",
    )
    args = parser.parse_args(argv)

    CharacterPrompt, MangaPagePrompt = load_models()
    validate_color_consistency = load_color_validator()
    character_files, page_files = collect_files(args)
    if not character_files and not page_files:
        parser.error("provide novel_dir, --character, --manga-page, or --illustration-page")

    character_ids: set[str] = set()
    character_variants: dict[str, set[str]] = {}
    errors: list[str] = []
    warnings: list[str] = []

    for path in character_files:
        try:
            character = CharacterPrompt.model_validate(load_yaml(path))
            character_ids.add(character.character_id)
            character_variants[character.character_id] = {
                variant.variant_id for variant in character.prompt_variants
            }
            print(f"OK character: {path}")
        except Exception as exc:
            errors.append(f"{path}: {exc}")

    page_counts: dict[str, int] = {"manga_page": 0, "manga_panel": 0, "illustration": 0}
    for path in page_files:
        try:
            page_data = load_yaml(path)
            page = MangaPagePrompt.model_validate(page_data)
            page_counts[str(page.meta.intent)] = page_counts.get(str(page.meta.intent), 0) + 1
            missing = [cid for cid in page.character_ids if cid not in character_ids]
            subject_missing = [
                subject.character_id
                for panel in page.panels
                for subject in panel.subjects
                if subject.character_id and subject.character_id not in character_ids
            ]
            if missing or subject_missing:
                unknown = sorted(set(missing + subject_missing))
                raise ValueError(f"unknown character_id reference: {', '.join(unknown)}")
            warnings.extend(
                quality_warnings_for_page(
                    path,
                    page,
                    character_variants,
                    validate_color_consistency=validate_color_consistency,
                    color_page_data=page_data,
                )
            )
            print(f"OK {page.meta.intent}: {path}")
        except Exception as exc:
            errors.append(f"{path}: {exc}")

    if warnings:
        print("Quality warnings:", file=sys.stderr)
        for warning in warnings:
            print(f"- {warning}", file=sys.stderr)

    if errors:
        print("Validation failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    if args.strict_quality and warnings:
        print("Validation failed: strict quality warnings were found", file=sys.stderr)
        return 1

    print(
        f"validated characters={len(character_files)} manga_pages={page_counts.get('manga_page', 0)} "
        f"manga_panels={page_counts.get('manga_panel', 0)} illustrations={page_counts.get('illustration', 0)} "
        f"quality_warnings={len(warnings)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
