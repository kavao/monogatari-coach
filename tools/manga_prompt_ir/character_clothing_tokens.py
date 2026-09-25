"""Costume-token detection for CharacterPrompt 1.1 gates."""

from __future__ import annotations

import re

AMBIGUOUS_COSTUME_TAGS = frozenset(
    {
        "casual_jacket",
        "dark_pants",
        "cute_outfit",
        "cute outfit",
        "student_look",
        "student look",
        "dark_clothes",
        "dark clothes",
    }
)

_CLOTHING_CATEGORY_RE = re.compile(
    r"(^|_)(jacket|hoodie|hooded|cardigan|coat|blazer|parka|windbreaker|"
    r"pants|trousers|jeans|shorts|skirt|dress|uniform|shirt|tshirt|"
    r"t-shirt|sweater|hoodie|hoodie|vest|blouse|kimono|hakama)(_|$)",
    re.IGNORECASE,
)


def normalize_costume_token(tag: str) -> str:
    return str(tag or "").strip().lower().replace("-", "_")


def is_ambiguous_costume_tag(tag: str) -> bool:
    raw = str(tag or "").strip().lower()
    normalized = normalize_costume_token(tag)
    return raw in AMBIGUOUS_COSTUME_TAGS or normalized in {
        item.replace(" ", "_") for item in AMBIGUOUS_COSTUME_TAGS
    }


def is_clothing_category_tag(tag: str) -> bool:
    normalized = normalize_costume_token(tag)
    if not normalized:
        return False
    if is_ambiguous_costume_tag(tag):
        return True
    return bool(_CLOTHING_CATEGORY_RE.search(normalized))


def find_forbidden_costume_tags(tags: list[str]) -> list[str]:
    return [tag for tag in tags if is_clothing_category_tag(str(tag))]
