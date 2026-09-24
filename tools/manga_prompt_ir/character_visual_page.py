"""Page-side 1.1 visual snapshot and variant matching."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from manga_prompt_ir.character_visual_resolver import (
    VisualResolverError,
    character_source_sha256,
    is_character_schema_1_1,
    resolve_character_visual,
)
from manga_prompt_ir.schemas.character import CharacterPrompt


class CharacterVisualPageError(ValueError):
    """Snapshot hash / variant mismatch for CharacterPrompt 1.1."""


def declared_subject_variant_ids(subject: dict[str, Any]) -> list[str]:
    return list(
        dict.fromkeys(
            str(value).strip()
            for value in (
                subject.get("prompt_variant_id"),
                subject.get("costume_variant"),
                subject.get("variant_id"),
            )
            if value and str(value).strip()
        )
    )


def selected_subject_variant_id(subject: dict[str, Any]) -> str | None:
    ids = declared_subject_variant_ids(subject)
    if len(ids) > 1:
        raise CharacterVisualPageError(
            "prompt_variant_id / costume_variant / variant_id が食い違っています: "
            + ", ".join(ids)
        )
    return ids[0] if ids else None


def snapshot_for_pair(
    page: dict[str, Any],
    character_id: str,
    variant_id: str | None,
) -> dict[str, Any] | None:
    for snapshot in page.get("character_snapshots") or []:
        if not isinstance(snapshot, dict):
            continue
        if str(snapshot.get("character_id") or "") != character_id:
            continue
        selected = snapshot.get("selected_variant_id")
        if variant_id is None:
            if selected in (None, ""):
                return snapshot
            continue
        if str(selected or "") == variant_id:
            return snapshot
    return None


def reject_duplicate_snapshots(page: dict[str, Any]) -> None:
    seen: set[tuple[str, str]] = set()
    for snapshot in page.get("character_snapshots") or []:
        if not isinstance(snapshot, dict):
            continue
        cid = str(snapshot.get("character_id") or "")
        if not cid:
            continue
        key = (cid, str(snapshot.get("selected_variant_id") or ""))
        if key in seen:
            raise CharacterVisualPageError(
                "character_snapshots が (character_id, selected_variant_id) で重複しています: "
                f"{key[0]}/{key[1]}"
            )
        seen.add(key)


def snapshot_declares_character_1_1(snapshot: dict[str, Any]) -> bool:
    if str(snapshot.get("character_schema_version") or "").strip() == "1.1":
        return True
    return bool(snapshot.get("character_source_sha256") or snapshot.get("visual_natural"))


def page_has_visual_snapshots(page: dict[str, Any]) -> bool:
    return any(
        isinstance(snapshot, dict) and snapshot_declares_character_1_1(snapshot)
        for snapshot in (page.get("character_snapshots") or [])
    )


def page_requires_character_yaml(page: dict[str, Any]) -> bool:
    snapshots = page.get("character_snapshots") or []
    if str(page.get("schema_version") or "1.0") == "1.1" and snapshots:
        return True
    return page_has_visual_snapshots(page)


def validated_character_map(
    characters: Mapping[str, Mapping[str, Any] | CharacterPrompt] | None,
) -> dict[str, CharacterPrompt]:
    validated: dict[str, CharacterPrompt] = {}
    if not characters:
        return validated
    for cid, raw in characters.items():
        if isinstance(raw, CharacterPrompt):
            validated[str(cid)] = raw
            if raw.character_id:
                validated[str(raw.character_id)] = raw
            continue
        data = raw if isinstance(raw, dict) else None
        if data is None:
            raise CharacterVisualPageError(f"キャラクター YAML を解決できません: {cid}")
        if is_character_schema_1_1(data):
            try:
                model = CharacterPrompt.model_validate(data)
            except Exception as exc:
                raise CharacterVisualPageError(
                    f"キャラクター YAML の検証に失敗しました: {cid}: {exc}"
                ) from exc
            validated[str(cid)] = model
            if model.character_id:
                validated[str(model.character_id)] = model
            continue
        try:
            model = CharacterPrompt.model_validate(data)
        except Exception:
            continue
        validated[str(cid)] = model
        if model.character_id:
            validated[str(model.character_id)] = model
    return validated


def _list_equal(left: list[Any], right: list[Any]) -> bool:
    return [str(item) for item in left] == [str(item) for item in right]


def compare_snapshot_to_resolved(
    snapshot: dict[str, Any],
    resolved: Any,
    *,
    character_id: str,
    variant_id: str,
) -> None:
    expected_variant = [*resolved.costume_tags, *resolved.state_tags]
    checks = (
        ("fixed_tags", _list_equal(snapshot.get("fixed_tags") or [], resolved.identity_tags)),
        ("variant_tags", _list_equal(snapshot.get("variant_tags") or [], expected_variant)),
        ("visual_natural", str(snapshot.get("visual_natural") or "") == str(resolved.natural or "")),
        (
            "costume_summary",
            str(snapshot.get("costume_summary") or "") == str(resolved.costume_summary or ""),
        ),
    )
    mismatches = [name for name, ok in checks if not ok]
    if mismatches:
        raise CharacterVisualPageError(
            "snapshot が visual resolver 出力と不一致です: "
            f"{character_id}/{variant_id} ({', '.join(mismatches)})"
        )


def apply_resolved_snapshot(snapshot: dict[str, Any], resolved: Any) -> None:
    snapshot["fixed_tags"] = list(resolved.identity_tags)
    snapshot["variant_tags"] = [*resolved.costume_tags, *resolved.state_tags]
    snapshot["visual_natural"] = resolved.natural
    snapshot["character_schema_version"] = "1.1"
    if resolved.costume_summary:
        snapshot["costume_summary"] = resolved.costume_summary
    elif "costume_summary" in snapshot and not resolved.costume_summary:
        snapshot["costume_summary"] = ""


def rebuild_resolved_snapshots(
    page: dict[str, Any],
    characters: Mapping[str, Mapping[str, Any] | CharacterPrompt] | None,
) -> None:
    validated = validated_character_map(characters)
    for snapshot in page.get("character_snapshots") or []:
        if not isinstance(snapshot, dict):
            continue
        cid = str(snapshot.get("character_id") or "")
        character = validated.get(cid)
        if character is None or character.schema_version != "1.1":
            continue
        variant_id = str(snapshot.get("selected_variant_id") or "").strip()
        if not variant_id:
            continue
        resolved = resolve_character_visual(character, variant_id)
        apply_resolved_snapshot(snapshot, resolved)
        snapshot["character_source_sha256"] = character_source_sha256(character)


def validate_page_character_visual(
    page: dict[str, Any],
    characters: Mapping[str, Mapping[str, Any] | CharacterPrompt] | None,
) -> dict[str, CharacterPrompt]:
    reject_duplicate_snapshots(page)
    validated = validated_character_map(characters)
    needs_yaml = page_requires_character_yaml(page)
    subject_ids: list[tuple[str, str | None]] = []
    for panel in page.get("panels") or []:
        if not isinstance(panel, dict):
            continue
        for subject in panel.get("subjects") or []:
            if not isinstance(subject, dict) or not subject.get("character_id"):
                continue
            cid = str(subject["character_id"])
            subject_ids.append((cid, selected_subject_variant_id(subject)))
            character = validated.get(cid)
            if character is not None and character.schema_version == "1.1":
                needs_yaml = True

    if needs_yaml and not characters:
        raise CharacterVisualPageError(
            "CharacterPrompt 1.1 のページにキャラクター YAML がありません"
        )

    for cid, variant_id in subject_ids:
        character = validated.get(cid)
        snapshot_marker = any(
            isinstance(item, dict)
            and str(item.get("character_id") or "") == cid
            and snapshot_declares_character_1_1(item)
            for item in (page.get("character_snapshots") or [])
        )
        if character is None:
            if snapshot_marker:
                raise CharacterVisualPageError(f"キャラクター YAML を解決できません: {cid}")
            continue
        if character.schema_version != "1.1":
            continue
        if not variant_id:
            raise CharacterVisualPageError(
                f"1.1 キャラクターに variant_id がありません: {cid}"
            )
        snapshot = snapshot_for_pair(page, cid, variant_id)
        if snapshot is None:
            raise CharacterVisualPageError(
                f"snapshot が (character_id, selected_variant_id) と一致しません: "
                f"{cid}/{variant_id}"
            )
        expected_hash = character_source_sha256(character)
        got_hash = str(snapshot.get("character_source_sha256") or "").strip()
        got_natural = str(snapshot.get("visual_natural") or "").strip()
        if not got_hash or not got_natural:
            raise CharacterVisualPageError(
                "1.1 の snapshot は character_source_sha256 と visual_natural が必要です"
                f"（embed_snapshots を実行してください）: {cid}/{variant_id}"
            )
        if got_hash != expected_hash:
            raise CharacterVisualPageError(
                f"character_source_sha256 が不一致です: {cid}/{variant_id}"
            )
        try:
            resolved = resolve_character_visual(character, variant_id)
        except VisualResolverError as exc:
            raise CharacterVisualPageError(str(exc)) from exc
        compare_snapshot_to_resolved(
            snapshot, resolved, character_id=cid, variant_id=variant_id
        )
    return validated
