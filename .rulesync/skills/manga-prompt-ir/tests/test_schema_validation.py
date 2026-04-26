from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytest.importorskip("pydantic")
pytest.importorskip("yaml")

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT))

from converters.prompt_renderer import extract_text_elements, render_page_prompt
from converters.yaml_loader import load_model
from schemas.character import CharacterPrompt
from schemas.manga_page import MangaPagePrompt


def test_character_yaml_validates() -> None:
    character = load_model(SKILL_ROOT / "examples" / "character.yaml", CharacterPrompt)
    assert character.character_id == "kazuki"
    assert "black_hair" in character.fixed_prompt_tags()


def test_manga_page_yaml_validates_and_renders() -> None:
    page = load_model(SKILL_ROOT / "examples" / "manga_page.yaml", MangaPagePrompt)
    character = load_model(SKILL_ROOT / "examples" / "character.yaml", CharacterPrompt)
    rendered = render_page_prompt(page, {character.character_id: character})
    assert "panel 1" in rendered.prompt
    assert "black_hair" in rendered.tags
    assert "bad_hands" in rendered.negative_tags


def test_text_elements_are_extractable() -> None:
    page = load_model(SKILL_ROOT / "examples" / "manga_page.yaml", MangaPagePrompt)
    elements = extract_text_elements(page)
    kinds = {item["type"] for item in elements}
    assert {"dialogue", "narration", "monologue", "sfx"} <= kinds
