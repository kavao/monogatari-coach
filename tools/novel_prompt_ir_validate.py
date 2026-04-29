#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Validate manga-prompt-ir YAML files with the Pydantic schemas."""

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


def load_yaml(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"YAML root must be a mapping: {path}")
    return data


def collect_files(args: argparse.Namespace) -> tuple[list[Path], list[Path]]:
    character_files = [Path(p) for p in args.character]
    manga_page_files = [Path(p) for p in args.manga_page]
    if args.novel_dir:
        novel_dir = Path(args.novel_dir)
        if not novel_dir.is_absolute():
            novel_dir = (repo_root() / novel_dir).resolve()
        character_files.extend(sorted((novel_dir / "tag" / "characters").glob("*.yaml")))
        manga_page_files.extend(sorted((novel_dir / "manga" / "pages").glob("*.yaml")))
    return character_files, manga_page_files


def has_text(value: str | None) -> bool:
    return bool(value and value.strip())


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


def quality_warnings_for_page(path: Path, page, character_variants: dict[str, set[str]]) -> list[str]:
    warnings: list[str] = []
    label = path.as_posix()
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
        warnings.append(f"{label}: render_instruction.panel_policy が空です（コマ割り指示が弱くなります）")
    if not has_text(render_instruction.character_policy):
        warnings.append(f"{label}: render_instruction.character_policy が空です（キャラクター外見継承が弱くなります）")
    if not has_text(page.manga.panel_layout):
        warnings.append(f"{label}: manga.panel_layout が空です（ページ内の段・大小・読み順が弱くなります）")

    declared_ids = set(page.character_ids)
    used_ids: set[str] = set()
    snapshot_keys = page_snapshot_keys(page)
    snapshot_ids = {snapshot.character_id for snapshot in page.character_snapshots}
    for panel in page.panels:
        prefix = f"{label}: panel {panel.panel_id}"
        if panel.summary.strip() in ABSTRACT_ONLY_SUMMARIES:
            warnings.append(f"{prefix}: summary が抽象語のみです: {panel.summary!r}")
        if any(word in panel.summary for word in PARTIAL_CUT_WORDS):
            has_owner = any(
                has_text(subject.character_id) or any(name in subject.description for name in ("の", "が", "を"))
                for subject in panel.subjects
            )
            if not has_owner:
                warnings.append(f"{prefix}: 部分アップらしいsummaryですが、所有者や意味づけが弱い可能性があります")

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
                comp.framing,
                comp.focus,
                comp.perspective,
                camera.angle,
                camera.shot_size,
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
    parser = argparse.ArgumentParser(description="Validate manga-prompt-ir YAML files")
    parser.add_argument("novel_dir", nargs="?", help="Novel directory containing tag/characters and manga/pages")
    parser.add_argument("--character", action="append", default=[], help="Character YAML file")
    parser.add_argument("--manga-page", action="append", default=[], help="Manga page YAML file")
    parser.add_argument(
        "--strict-quality",
        action="store_true",
        help="意味品質の警告も失敗扱いにする",
    )
    args = parser.parse_args(argv)

    CharacterPrompt, MangaPagePrompt = load_models()
    character_files, manga_page_files = collect_files(args)
    if not character_files and not manga_page_files:
        parser.error("provide novel_dir, --character, or --manga-page")

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

    for path in manga_page_files:
        try:
            page = MangaPagePrompt.model_validate(load_yaml(path))
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
            warnings.extend(quality_warnings_for_page(path, page, character_variants))
            print(f"OK manga_page: {path}")
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
        f"validated characters={len(character_files)} manga_pages={len(manga_page_files)} "
        f"quality_warnings={len(warnings)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
