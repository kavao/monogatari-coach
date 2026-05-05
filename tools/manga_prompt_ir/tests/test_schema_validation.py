from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytest.importorskip("pydantic")
pytest.importorskip("yaml")

# tools/ を sys.path に追加してパッケージ参照を有効にする
_TOOLS_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_TOOLS_ROOT))

_PKG_ROOT = Path(__file__).resolve().parents[1]  # tools/manga_prompt_ir/
_EXAMPLES = _PKG_ROOT / "examples"

from manga_prompt_ir.converters.prompt_renderer import extract_text_elements, render_page_prompt
from manga_prompt_ir.converters.yaml_loader import load_model
from manga_prompt_ir.schemas.character import CharacterPrompt
from manga_prompt_ir.schemas.manga_page import MangaPagePrompt

from image_provider_novel_manga_batch import filter_single_panel_tags


def test_character_yaml_validates() -> None:
    character = load_model(_EXAMPLES / "character.yaml", CharacterPrompt)
    assert character.character_id == "kazuki"
    assert "black_hair" in character.fixed_prompt_tags()


def test_manga_page_yaml_validates_and_renders() -> None:
    page = load_model(_EXAMPLES / "manga_page.yaml", MangaPagePrompt)
    character = load_model(_EXAMPLES / "character.yaml", CharacterPrompt)
    rendered = render_page_prompt(page, {character.character_id: character})
    assert "漫画1ページ分の作画指示" in rendered.prompt
    assert "panel 1" in rendered.prompt
    assert "black_hair" in rendered.tags
    assert "bad_hands" in rendered.negative_tags


def test_text_elements_are_extractable() -> None:
    page = load_model(_EXAMPLES / "manga_page.yaml", MangaPagePrompt)
    elements = extract_text_elements(page)
    kinds = {item["type"] for item in elements}
    assert {"dialogue", "narration", "monologue", "sfx"} <= kinds


def test_single_panel_filter_removes_page_layout_tags() -> None:
    tags = filter_single_panel_tags(
        [
            "japanese manga panel layout",
            "horizontal top panel",
            "large bottom panel",
            "clear panel borders",
            "close-up",
            "Shiraishi Kazuki looking down at smartphone",
        ]
    )
    assert "japanese manga panel layout" not in tags
    assert "horizontal top panel" not in tags
    assert "large bottom panel" not in tags
    assert "clear panel borders" not in tags
    assert "close-up" in tags
    assert "Shiraishi Kazuki looking down at smartphone" in tags
