"""Filter standalone character-id / name tokens from NovelAI pipe **base** tag lists."""

from __future__ import annotations

from typing import Any, Mapping


def normalize_character_token_key(value: str) -> str:
    """Match ``image_provider_novel_manga_batch.normalize_tag`` casing for comparison."""
    return str(value).strip().replace(" ", "_").lower()


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def collect_blocked_character_tokens(
    page: Mapping[str, Any],
    panel: Mapping[str, Any] | None,
    characters: Mapping[str, Mapping[str, Any]],
) -> frozenset[str]:
    """Normalized keys for character_id / display names on this page."""
    raw: set[str] = set()
    for cid in _as_list(page.get("character_ids")):
        if cid:
            raw.add(str(cid))
    for snap in _as_list(page.get("character_snapshots")):
        if not isinstance(snap, dict):
            continue
        for key in ("character_id", "name_en", "name"):
            v = snap.get(key)
            if v:
                raw.add(str(v))
    if panel:
        for subject in _as_list(panel.get("subjects")):
            if not isinstance(subject, dict):
                continue
            cid = subject.get("character_id")
            if cid:
                raw.add(str(cid))
    for cid in list(raw):
        ch = characters.get(cid)
        if not isinstance(ch, dict):
            continue
        for key in ("character_id", "name_en", "name"):
            v = ch.get(key)
            if v:
                raw.add(str(v))
    return frozenset(
        normalize_character_token_key(t) for t in raw if str(t).strip()
    )


def is_standalone_tag_token(tag: str) -> bool:
    """Phrases with spaces are kept (e.g. summary_en, ``glowing phone screen``)."""
    s = str(tag).strip()
    return bool(s) and " " not in s


def filter_base_standalone_character_tokens(
    tags: list[str],
    blocked: frozenset[str],
) -> list[str]:
    """Drop base tags that are a single token equal to a blocked character key."""
    if not blocked:
        return tags
    out: list[str] = []
    for tag in tags:
        s = str(tag).strip()
        if not s:
            continue
        if is_standalone_tag_token(s) and normalize_character_token_key(s) in blocked:
            continue
        out.append(tag)
    return out
