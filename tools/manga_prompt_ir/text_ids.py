"""Stable text_id assignment shared by compiler, geometry, and lettering."""

from __future__ import annotations

from typing import Any


def assigned_text_id(
    item: Any,
    *,
    panel_id: Any,
    kind: str,
    index: int,
) -> str:
    """Return the explicit text_id, or a page-local fallback.

    Fallback form is ``p{panel_id}-{kind}-{index:02d}`` (example: ``p2-dialogue-01``).
    Page hashes are not part of the id so geometry and lettering can join on it.
    """
    raw = None
    if isinstance(item, dict):
        raw = item.get("text_id")
    elif item is not None:
        raw = getattr(item, "text_id", None)
    text = str(raw or "").strip()
    if text:
        return text
    return f"p{panel_id}-{kind}-{index:02d}"
