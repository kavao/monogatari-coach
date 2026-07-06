"""Shared parsers for episode MD → JSON sync."""

from __future__ import annotations

from typing import Any, cast

from .hooks import build_hooks_section, parse_hooks_md

__all__ = ["build_hooks_section", "coerce_json_dict", "parse_hooks_md"]


def coerce_json_dict(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return cast(dict[str, Any], value)
    return {}
