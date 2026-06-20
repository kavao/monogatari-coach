from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytest.importorskip("pydantic")
pytest.importorskip("yaml")

_TOOLS_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_TOOLS_ROOT))

_PKG_ROOT = Path(__file__).resolve().parents[1]
_EXAMPLES = _PKG_ROOT / "examples"

from manga_prompt_ir.character_fixed_tags import base_fixed_tags_from, resolve_variant_danbooru_tags
from manga_prompt_ir.converters.yaml_loader import load_model
from manga_prompt_ir.schemas.character import CharacterPrompt


def test_character_yaml_validates_and_uses_000_base() -> None:
    character = load_model(_EXAMPLES / "character.yaml", CharacterPrompt)
    assert character.character_id == "kazuki"
    assert "black_hair" in character.fixed_prompt_tags()
    assert "1boy" in character.fixed_prompt_tags()
    assert "casual_jacket" not in character.fixed_prompt_tags()


def test_legacy_character_tags_key_rejected() -> None:
    raw = load_model(_EXAMPLES / "character.yaml", CharacterPrompt).model_dump()
    raw["character_tags"] = ["1boy"]
    with pytest.raises(Exception):
        CharacterPrompt.model_validate(raw)


def test_resolve_variant_danbooru_tags_merges_base_and_variant() -> None:
    character = load_model(_EXAMPLES / "character.yaml", CharacterPrompt)
    data = character.model_dump()
    tags = resolve_variant_danbooru_tags(data, "001_normal")
    assert "black_hair" in tags
    assert "casual_jacket" in tags


def test_base_fixed_tags_from_empty_without_000_base() -> None:
    char = {"prompt_variants": [{"variant_id": "001_normal", "danbooru_tags": ["dress"]}]}
    assert base_fixed_tags_from(char) == []
