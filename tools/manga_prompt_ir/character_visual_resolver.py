"""Resolve CharacterPrompt 1.1 visual_spec / state_tags into tags and prose."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from manga_prompt_ir.character_fixed_tags import (
    base_fixed_tags_from,
    dedupe_tags,
    variants_by_id,
)


class VisualResolverError(ValueError):
    """Unknown variant, cycle, or 1.1 visual contract failure."""


CLOSURE_TAGS = {
    "zipper": "zip_front",
    "zip": "zip_front",
    "buttons": "button_front",
    "button": "button_front",
    "open": "open_front",
    "none": "no_front_closure",
}

COLLAR_TAGS = {
    "fold_down": "fold_down_collar",
    "stand": "stand_collar",
    "none": "no_collar",
}


@dataclass(frozen=True)
class ResolvedVisual:
    character_id: str
    variant_id: str
    identity_tags: list[str]
    costume_tags: list[str]
    state_tags: list[str]
    danbooru_tags: list[str]
    natural: str
    costume_summary: str
    metadata: dict[str, str] = field(default_factory=dict)


def is_character_schema_1_1(character: dict[str, Any] | Any) -> bool:
    if hasattr(character, "schema_version"):
        return str(character.schema_version) == "1.1"
    if isinstance(character, dict):
        return str(character.get("schema_version", "1.0")) == "1.1"
    return False


def _as_dict(character: dict[str, Any] | Any) -> dict[str, Any]:
    if isinstance(character, dict):
        return character
    dump = getattr(character, "model_dump", None)
    if dump is not None:
        return dump(mode="json")
    raise VisualResolverError("キャラクター定義をdictにできません")


def character_source_sha256(character: dict[str, Any] | Any) -> str:
    from manga_prompt_ir.schemas.character import CharacterPrompt

    if isinstance(character, CharacterPrompt):
        model = character
    else:
        model = CharacterPrompt.model_validate(_as_dict(character))
    data = model.model_dump(mode="json")
    payload = json.loads(json.dumps(data, ensure_ascii=False))
    for variant in payload.get("prompt_variants") or []:
        if not isinstance(variant, dict):
            continue
        if str(variant.get("variant_kind") or "") == "base":
            continue
        if str(variant.get("variant_id") or "") == "000_base":
            continue
        variant.pop("danbooru_tags", None)
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _color_type_tag(color: str, type_name: str) -> str:
    color_key = str(color or "").strip().replace(" ", "_")
    type_key = str(type_name or "").strip().replace(" ", "_")
    if not type_key:
        raise VisualResolverError("visual_spec の type が空です")
    if color_key and not type_key.startswith(f"{color_key}_"):
        return f"{color_key}_{type_key}"
    return type_key


def _humanize(token: str) -> str:
    return str(token).replace("_", " ").strip()


def visual_spec_tags(spec: dict[str, Any]) -> tuple[list[str], str]:
    outer = spec.get("outer") or {}
    inner = spec.get("inner") or {}
    bottom = spec.get("bottom") or {}
    tags: list[str] = []
    tags.append(_color_type_tag(str(outer.get("color") or ""), str(outer.get("type") or "")))
    collar = str(outer.get("collar") or "").strip()
    if not collar:
        raise VisualResolverError("visual_spec.outer.collar が空です")
    tags.append(COLLAR_TAGS.get(collar, f"{collar}_collar"))
    closure = str(outer.get("closure") or "").strip()
    if not closure:
        raise VisualResolverError("visual_spec.outer.closure が空です")
    tags.append(CLOSURE_TAGS.get(closure, f"{closure}_front"))
    tags.append("hood" if bool(outer.get("hood")) else "no_hood")
    tags.append(_color_type_tag(str(inner.get("color") or ""), str(inner.get("type") or "")))
    tags.append(_color_type_tag(str(bottom.get("color") or ""), str(bottom.get("type") or "")))
    shoes = spec.get("shoes")
    if isinstance(shoes, dict) and (shoes.get("type") or shoes.get("color")):
        tags.append(_color_type_tag(str(shoes.get("color") or ""), str(shoes.get("type") or "")))
    for accessory in spec.get("accessories") or []:
        if accessory:
            tags.append(str(accessory).strip().replace(" ", "_"))
    tags = dedupe_tags(tags)
    return tags, ", ".join(_humanize(tag) for tag in tags)


def _identity_tags(data: dict[str, Any]) -> list[str]:
    appearance = data.get("appearance") or {}
    rules = data.get("manga_rules") or {}
    return dedupe_tags(
        [
            *base_fixed_tags_from(data),
            *[str(tag) for tag in (appearance.get("species_features") or []) if tag],
            *[str(tag) for tag in (appearance.get("distinctive_features") or []) if tag],
            *[str(tag) for tag in (rules.get("consistency_tags") or []) if tag],
        ]
    )


def _variant_maps(character: dict[str, Any]) -> dict[str, dict[str, Any]]:
    variants = [item for item in (character.get("prompt_variants") or []) if isinstance(item, dict)]
    return variants_by_id(variants)


def _collect_combines_state(
    by_id: dict[str, dict[str, Any]],
    variant_id: str,
    visited: set[str],
) -> list[str]:
    vid = str(variant_id or "").strip()
    if not vid:
        return []
    if vid in visited:
        raise VisualResolverError(f"combines_with が循環しています: {vid}")
    variant = by_id.get(vid)
    if variant is None:
        raise VisualResolverError(f"combines_with の参照先がありません: {vid}")
    kind = str(variant.get("variant_kind") or "")
    if kind in {"base", "costume"}:
        raise VisualResolverError(f"{kind} variant に combines_with を置けません: {vid}")
    visited.add(vid)
    tags = [str(tag) for tag in (variant.get("state_tags") or []) if tag]
    combines = str(variant.get("combines_with") or "").strip()
    if combines:
        tags.extend(_collect_combines_state(by_id, combines, visited))
    return tags


def expected_nonbase_danbooru_tags(character: dict[str, Any], variant_id: str) -> list[str]:
    return resolve_character_visual(character, variant_id).danbooru_tags


def resolve_character_visual(
    character: dict[str, Any] | Any,
    variant_id: str | None,
) -> ResolvedVisual:
    data = _as_dict(character)
    if not is_character_schema_1_1(data):
        raise VisualResolverError("visual resolver は CharacterPrompt 1.1 専用です")
    cid = str(data.get("character_id") or "").strip()
    vid = str(variant_id or "").strip()
    if not vid:
        raise VisualResolverError("variant_id がありません")
    by_id = _variant_maps(data)
    variant = by_id.get(vid)
    if variant is None:
        raise VisualResolverError(f"未知の variant_id です: {vid}")
    kind = str(variant.get("variant_kind") or "").strip()
    identity = _identity_tags(data)
    costume_tags: list[str] = []
    costume_summary = ""
    state_tags = [str(tag) for tag in (variant.get("state_tags") or []) if tag]

    if kind == "base":
        if str(variant.get("combines_with") or "").strip():
            raise VisualResolverError(f"base variant に combines_with を置けません: {vid}")
        natural = ", ".join(_humanize(tag) for tag in identity)
        return ResolvedVisual(
            character_id=cid,
            variant_id=vid,
            identity_tags=identity,
            costume_tags=[],
            state_tags=[],
            danbooru_tags=list(identity),
            natural=natural,
            costume_summary="",
            metadata={"character_id": cid, "variant_id": vid},
        )

    if kind == "costume":
        if str(variant.get("combines_with") or "").strip():
            raise VisualResolverError(f"costume variant に combines_with を置けません: {vid}")
        spec = variant.get("visual_spec")
        if not isinstance(spec, dict):
            raise VisualResolverError(f"costume variant に visual_spec がありません: {vid}")
        costume_tags, costume_summary = visual_spec_tags(spec)
    elif kind in {"state", "derived"}:
        inherits = str(variant.get("inherits_costume") or "").strip()
        if not inherits:
            raise VisualResolverError(f"{kind} variant に inherits_costume がありません: {vid}")
        inherited = by_id.get(inherits)
        if inherited is None:
            raise VisualResolverError(f"inherits_costume の参照先がありません: {inherits}")
        if str(inherited.get("variant_kind") or "") != "costume":
            raise VisualResolverError(f"inherits_costume の参照先が costume ではありません: {inherits}")
        spec = inherited.get("visual_spec")
        if not isinstance(spec, dict):
            raise VisualResolverError(f"inherits_costume 先に visual_spec がありません: {inherits}")
        costume_tags, costume_summary = visual_spec_tags(spec)
    else:
        raise VisualResolverError(f"未知の variant_kind です: {kind}")

    combines = str(variant.get("combines_with") or "").strip()
    if combines:
        if combines == str(variant.get("inherits_costume") or "").strip():
            raise VisualResolverError("inherits_costume と combines_with が同じ id です")
        state_tags = dedupe_tags(
            [*state_tags, *_collect_combines_state(by_id, combines, {vid})]
        )

    danbooru = dedupe_tags([*identity, *costume_tags, *state_tags])
    natural_parts = [
        ", ".join(_humanize(tag) for tag in identity),
        costume_summary,
        ", ".join(_humanize(tag) for tag in state_tags),
    ]
    natural = "; ".join(part for part in natural_parts if part)
    return ResolvedVisual(
        character_id=cid,
        variant_id=vid,
        identity_tags=identity,
        costume_tags=costume_tags,
        state_tags=state_tags,
        danbooru_tags=danbooru,
        natural=natural,
        costume_summary=costume_summary,
        metadata={"character_id": cid, "variant_id": vid},
    )
