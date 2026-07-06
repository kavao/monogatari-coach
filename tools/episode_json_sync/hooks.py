"""Parse episode hooks MD (## subcategory + bullet scenarios) into JSON nodes."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

_BULLET_RE = re.compile(r"^[\t ]*[-*]\s+(.+)$")
_HEADING2_RE = re.compile(r"^##\s+(.+)$")
_SPLIT_DESC_RE = re.compile(r"\s+[—｜|]\s+")


def _split_scenario_line(text: str) -> tuple[str, str]:
    text = text.strip()
    if not text:
        return "", ""
    parts = _SPLIT_DESC_RE.split(text, maxsplit=1)
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()
    return text, ""


def _bullet_item(line: str) -> dict[str, Any] | None:
    m = _BULLET_RE.match(line)
    if not m:
        return None
    scenario, description = _split_scenario_line(m.group(1))
    if not scenario:
        return None
    item: dict[str, Any] = {"シチュエーション": scenario, "確率": 1.0}
    if description:
        item["説明"] = description
    return item


def parse_hooks_md(path: Path) -> dict[str, dict[str, Any]]:
    """
    Parse hooks MD into subcategory dicts.

    - ``## 軸名`` → subcategory key
    - Paragraph lines before bullets → ``解説`` (joined)
    - ``- ...`` → ``内訳[]``
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    subcategories: dict[str, dict[str, Any]] = {}
    current_key: str | None = None
    prose_lines: list[str] = []

    def flush_prose() -> None:
        nonlocal prose_lines
        if current_key and prose_lines:
            text = " ".join(prose_lines).strip()
            if text:
                subcategories[current_key]["解説"] = text
        prose_lines = []

    for raw in lines:
        line = raw.rstrip()
        if not line or line.startswith("<!--"):
            continue
        if line.startswith("# ") and not line.startswith("## "):
            continue

        h2 = _HEADING2_RE.match(line)
        if h2:
            flush_prose()
            current_key = h2.group(1).strip()
            subcategories.setdefault(current_key, {"内訳": []})
            continue

        item = _bullet_item(line)
        if item is not None:
            if current_key is None:
                continue
            flush_prose()
            subcategories[current_key]["内訳"].append(item)
            continue

        if current_key and not line.startswith("#"):
            stripped = line.strip()
            if stripped and not stripped.startswith("-"):
                prose_lines.append(stripped)

    flush_prose()
    return subcategories


def build_hooks_section(
    *,
    subcategories: dict[str, dict[str, Any]],
    overview: str,
) -> dict[str, Any]:
    """Build top-level hooks node (schema 1.1 shape)."""
    return {
        "大分類解説": overview,
        "サブカテゴリ": subcategories,
    }
