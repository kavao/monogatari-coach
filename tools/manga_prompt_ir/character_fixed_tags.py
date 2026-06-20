"""Shared helpers for character fixed tags (000_base canonical)."""

from __future__ import annotations

from typing import Any


def dedupe_tags(tags: list[str]) -> list[str]:
    return list(dict.fromkeys(str(t).strip() for t in tags if str(t).strip()))


def variants_by_id(variants: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for variant in variants:
        if not isinstance(variant, dict):
            continue
        vid = str(variant.get("variant_id") or "").strip()
        if vid:
            out[vid] = variant
    return out


def prompt_variants_from_char(char: dict[str, Any]) -> list[dict[str, Any]]:
    return [v for v in char.get("prompt_variants") or [] if isinstance(v, dict)]


def base_fixed_tags_from(char: dict[str, Any], variants: list[dict[str, Any]] | None = None) -> list[str]:
    """Return ``000_base.danbooru_tags`` only (empty if missing or empty)."""
    if variants is None:
        variants = prompt_variants_from_char(char)
    ref = variants_by_id(variants).get("000_base")
    if ref:
        return [str(t) for t in ref.get("danbooru_tags") or [] if t]
    return []


def resolve_variant_danbooru_tags(char: dict[str, Any], variant_id: str | None = None) -> list[str]:
    """Resolve tags as ``000_base`` + variant + ``combines_with`` (manga batch compatible)."""
    variants = prompt_variants_from_char(char)
    by_id = variants_by_id(variants)
    if not variant_id:
        return base_fixed_tags_from(char, variants)
    vid = str(variant_id).strip()
    variant = by_id.get(vid)
    if not variant:
        return base_fixed_tags_from(char, variants)
    variant_tags = [str(t) for t in variant.get("danbooru_tags") or [] if t]
    combines = str(variant.get("combines_with") or "").strip()
    if combines:
        ref = by_id.get(combines)
        if ref:
            base = base_fixed_tags_from(char, variants)
            ref_tags = [str(t) for t in ref.get("danbooru_tags") or [] if t]
            inherited = dedupe_tags([*base, *ref_tags])
            return dedupe_tags([*inherited, *variant_tags])
    base = base_fixed_tags_from(char, variants)
    return dedupe_tags([*base, *variant_tags])
