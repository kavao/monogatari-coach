"""Character tag quality checks for Nude Base (3-tier inheritance) rules."""

from __future__ import annotations

import re
from typing import Any

from manga_prompt_ir.character_token_filter import (
    is_standalone_tag_token,
    normalize_character_token_key,
)

# Danbooru tokens that belong in 006_nude (Level 2), not fixed injection paths.
EXPOSURE_TAG_RE = re.compile(
    r"(^|_)(nude|uncensored|penis|pussy|vagina|pubic|hymen|erection|nipples|"
    r"areola|genital|testicles|clitoris|labia|anus|breasts_exposed|"
    r"large_penis|thick_penis|smooth_penis|no_pubic_hair|pussy_hymen|"
    r"detailed_pussy|pussy_spread|erection_penis)(_|$)",
    re.IGNORECASE,
)

NUDE_BODY_CANONICAL_IDS = frozenset({"006_nude", "06_nude"})

# 000-band situation variants that must inherit 006_nude when present in NSFW works.
LEVEL3_VARIANT_PREFIXES = ("007_", "008_", "103_", "104_", "110_", "111_", "112_")


def normalize_tag(tag: str) -> str:
    return str(tag or "").strip().lower().replace(" ", "_")


def is_exposure_tag(tag: str) -> bool:
    normalized = normalize_tag(tag)
    if not normalized:
        return False
    return bool(EXPOSURE_TAG_RE.search(normalized))


def find_exposure_tags(tags: list[str]) -> list[str]:
    return [t for t in tags if is_exposure_tag(t)]


def variant_number(variant_id: str) -> int | None:
    vid = (variant_id or "").strip()
    if not vid or vid == "000_base":
        return None
    head = vid.split("_", 1)[0]
    if head.isdigit():
        return int(head)
    return None


def is_nude_body_canonical(variant_id: str) -> bool:
    return (variant_id or "").strip() in NUDE_BODY_CANONICAL_IDS


def requires_nude_combines_with(variant_id: str) -> bool:
    vid = (variant_id or "").strip()
    if is_nude_body_canonical(vid):
        return False
    if vid.startswith(LEVEL3_VARIANT_PREFIXES):
        return True
    num = variant_number(vid)
    if num is not None and 7 <= num <= 99 and not vid.startswith("100_"):
        return True
    return False


def character_nude_base_warnings(character: Any, label: str) -> list[str]:
    """Return quality warnings for Nude Base rules on a validated CharacterPrompt."""
    warnings: list[str] = []
    appearance = character.appearance
    rules = character.manga_rules

    for field_name, tags in (
        ("000_base", _base_tags(character)),
        ("appearance.distinctive_features", list(appearance.distinctive_features)),
        ("manga_rules.consistency_tags", list(rules.consistency_tags)),
    ):
        hits = find_exposure_tags([str(t) for t in tags])
        if hits:
            warnings.append(
                f"{label}: {field_name} に露出・性器タグがあります: {', '.join(hits)}"
            )

    variant_ids = {v.variant_id for v in character.prompt_variants}
    has_nude_canonical = bool(variant_ids & NUDE_BODY_CANONICAL_IDS)

    for variant in character.prompt_variants:
        vid = variant.variant_id
        tags = [str(t) for t in variant.danbooru_tags]
        combines = (variant.combines_with or "").strip()

        if vid != "000_base" and not is_nude_body_canonical(vid) and not combines:
            hits = find_exposure_tags(tags)
            if hits and variant_number(vid) is not None and variant_number(vid) != 6:
                warnings.append(
                    f"{label}: {vid} の danbooru_tags に露出タグがありますが "
                    f"combines_with がありません: {', '.join(hits)}"
                )

        if requires_nude_combines_with(vid) and has_nude_canonical:
            if combines not in NUDE_BODY_CANONICAL_IDS:
                warnings.append(
                    f"{label}: {vid} は身体的正本を継承するため "
                    f"combines_with: 006_nude が必要です（現在: {combines or '(なし)'}）"
                )

    return warnings


def _base_tags(character: Any) -> list[str]:
    for variant in character.prompt_variants:
        if variant.variant_id == "000_base":
            return [str(t) for t in variant.danbooru_tags]
    return []


def character_base_required_errors(character: Any, label: str) -> list[str]:
    """Return errors when ``000_base`` is missing or empty."""
    errors: list[str] = []
    base_variant = None
    for variant in character.prompt_variants:
        if variant.variant_id == "000_base":
            base_variant = variant
            break
    if base_variant is None:
        errors.append(f"{label}: 000_base が prompt_variants にありません（Tag Mode 必須）")
    elif not base_variant.danbooru_tags:
        errors.append(f"{label}: 000_base.danbooru_tags が空です")
    return errors


def character_height_warnings(character: Any, label: str) -> list[str]:
    """Return warnings when ``appearance.height`` is missing (character.md 必須項目の YAML 写し)."""
    height = getattr(character.appearance, "height", None)
    if height is None or not str(height).strip():
        return [
            f"{label}: appearance.height が空です（character.md の身長を YAML に写してください）"
        ]
    return []


def collect_character_blocked_tokens(character: Any) -> frozenset[str]:
    """Normalized keys for character_id / name_en / name on this character."""
    raw: set[str] = set()
    for key in ("character_id", "name_en", "name"):
        value = getattr(character, key, None)
        if value is not None and str(value).strip():
            raw.add(str(value).strip())
    return frozenset(
        normalize_character_token_key(token) for token in raw if str(token).strip()
    )


def is_blocked_name_tag(tag: str, blocked: frozenset[str], character: Any) -> bool:
    """True when tag is a standalone or full-phrase match for character meta names."""
    text = str(tag).strip()
    if not text:
        return False
    if is_standalone_tag_token(text) and normalize_character_token_key(text) in blocked:
        return True
    for field in (getattr(character, "name_en", None), getattr(character, "name", None)):
        if field is None or not str(field).strip():
            continue
        field_s = str(field).strip()
        if text.lower() == field_s.lower():
            return True
        if normalize_character_token_key(text) == normalize_character_token_key(field_s):
            return True
    return False


def _filter_name_tokens(tags: list[str], blocked: frozenset[str], character: Any) -> tuple[list[str], list[str]]:
    kept: list[str] = []
    removed: list[str] = []
    for tag in tags:
        if is_blocked_name_tag(tag, blocked, character):
            removed.append(str(tag))
        else:
            kept.append(tag)
    return kept, removed


def character_name_token_warnings(character: Any, label: str) -> list[str]:
    """Return warnings when danbooru tag lists contain character_id / name / name_en tokens."""
    blocked = collect_character_blocked_tokens(character)
    if not blocked:
        return []

    warnings: list[str] = []
    appearance = character.appearance
    rules = character.manga_rules

    for field_name, tags in (
        ("000_base", _base_tags(character)),
        ("appearance.distinctive_features", list(appearance.distinctive_features)),
        ("manga_rules.consistency_tags", list(rules.consistency_tags)),
    ):
        for tag in tags:
            if is_blocked_name_tag(tag, blocked, character):
                warnings.append(
                    f"{label}: {field_name} に人名トークンがあります: {tag!r} "
                    "（character_id / name / name_en はメタ情報のみ。danbooru_tags から除去）"
                )

    for variant in character.prompt_variants:
        vid = variant.variant_id
        for tag in variant.danbooru_tags:
            if is_blocked_name_tag(str(tag), blocked, character):
                warnings.append(
                    f"{label}: {vid}.danbooru_tags に人名トークンがあります: {tag!r} "
                    "（character_id / name / name_en はメタ情報のみ。danbooru_tags から除去）"
                )
    return warnings


def strip_name_tokens_from_character(character: Any) -> tuple[Any, list[str]]:
    """Remove blocked name tokens from tag lists on a validated CharacterPrompt."""
    blocked = collect_character_blocked_tokens(character)
    if not blocked:
        return character, []

    removed: list[str] = []
    appearance = character.appearance
    rules = character.manga_rules

    kept, dropped = _filter_name_tokens(
        [str(t) for t in appearance.distinctive_features], blocked, character
    )
    appearance.distinctive_features = kept
    removed.extend(dropped)

    kept, dropped = _filter_name_tokens(
        [str(t) for t in rules.consistency_tags], blocked, character
    )
    rules.consistency_tags = kept
    removed.extend(dropped)

    for variant in character.prompt_variants:
        kept, dropped = _filter_name_tokens(
            [str(t) for t in variant.danbooru_tags], blocked, character
        )
        variant.danbooru_tags = kept
        removed.extend(dropped)

    return character, removed
