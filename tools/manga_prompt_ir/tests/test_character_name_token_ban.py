"""Character YAML: block character_id / name / name_en in danbooru tag lists."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytest.importorskip("pydantic")

_TOOLS_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_TOOLS_ROOT))

from manga_prompt_ir.character_tag_quality import (  # noqa: E402
    character_name_token_warnings,
    strip_name_tokens_from_character,
)
from manga_prompt_ir.schemas.character import CharacterPrompt  # noqa: E402


def _minimal_character(**overrides: object) -> CharacterPrompt:
    base = {
        "schema_version": "1.0",
        "character_id": "yuna",
        "name": "田中結菜",
        "name_en": "Yuna Tanaka",
        "role": "heroine",
        "appearance": {
            "distinctive_features": ["blue_eyes"],
        },
        "costume": {"outfit_tags": ["school_uniform"]},
        "personality": {"personality_tags": ["kind"]},
        "manga_rules": {"consistency_tags": ["blue_eyes"]},
        "prompt_variants": [
            {
                "variant_id": "000_base",
                "title": "base",
                "description": "base",
                "danbooru_tags": ["1girl", "blue_eyes"],
            },
            {
                "variant_id": "001_normal",
                "title": "normal",
                "description": "normal",
                "danbooru_tags": ["school_uniform"],
                "caption": "Yuna Tanaka, school uniform.",
            },
        ],
    }
    base.update(overrides)
    return CharacterPrompt.model_validate(base)


def test_name_en_standalone_tag_warns() -> None:
    character = _minimal_character()
    character.prompt_variants[1].danbooru_tags = ["Yuna", "school_uniform"]
    warnings = character_name_token_warnings(character, "test.yaml")
    assert any("人名トークン" in w and "Yuna" in w for w in warnings)


def test_character_id_standalone_tag_warns() -> None:
    character = _minimal_character()
    character.prompt_variants[0].danbooru_tags = ["1girl", "yuna"]
    warnings = character_name_token_warnings(character, "test.yaml")
    assert any("000_base" in w and "yuna" in w for w in warnings)


def test_caption_not_inspected() -> None:
    character = _minimal_character()
    character.prompt_variants[1].caption = "Yuna Tanaka in uniform"
    warnings = character_name_token_warnings(character, "test.yaml")
    assert not warnings


def test_appearance_tags_not_warned() -> None:
    character = _minimal_character()
    character.appearance.distinctive_features = ["blue_eyes", "fair_skin"]
    warnings = character_name_token_warnings(character, "test.yaml")
    assert not warnings


def test_strip_removes_name_tokens() -> None:
    character = _minimal_character()
    character.prompt_variants[1].danbooru_tags = ["Yuna", "school_uniform"]
    character.manga_rules.consistency_tags = ["yuna", "blue_eyes"]
    updated, removed = strip_name_tokens_from_character(character)
    assert "Yuna" in removed
    assert "yuna" in removed
    assert "Yuna" not in updated.prompt_variants[1].danbooru_tags
    assert "school_uniform" in updated.prompt_variants[1].danbooru_tags
    assert character_name_token_warnings(updated, "test.yaml") == []
