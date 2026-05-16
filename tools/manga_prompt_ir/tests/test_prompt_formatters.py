from __future__ import annotations

import sys
from pathlib import Path

_TOOLS_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_TOOLS_ROOT))

from manga_prompt_ir.prompt_formatters import (  # noqa: E402
    INLINE_DO_NOT_INCLUDE,
    MANGA_PAGE_INSTRUCTION,
    NATURAL_SECTIONS,
    NOVELAI_PIPE,
    TAG_CSV,
    format_illustration_prompt,
    format_manga_panel_prompt,
    format_manga_page_prompt,
    resolve_prompt_formatter,
)


def _sample_illustration_page() -> dict:
    return {
        "meta": {"intent": "illustration", "illustration_type": "cover"},
        "render_instruction": {
            "prompt_header": "A cover about a tired office worker entering a divine dungeon.",
            "user_directives": {
                "defaults": {"omit_prompt_tags": ["comic panel borders"]}
            },
        },
        "manga": {
            "panel_layout": "vertical cover, title safe area at top",
        },
        "scene": {
            "location_en": "divine dungeon lobby",
            "time_of_day_en": "late night",
            "background_notes_en": "white stone floor, blue divine interface",
        },
        "character_snapshots": [
            {
                "character_id": "kazuki",
                "name_en": "Shiraishi Kazuki",
                "appearance_summary": "adult Japanese man, short black hair",
                "costume_summary": "business suit, loosened necktie",
                "fixed_tags": ["male", "black hair", "business suit"],
                "do_not_change": ["do not make him a muscular hero"],
            }
        ],
        "panels": [
            {
                "panel_id": 1,
                "summary": "Kazuki holds a glowing smartphone in the divine lobby.",
                "subjects": [
                    {
                        "character_id": "kazuki",
                        "pose_action_en": "holding a glowing smartphone",
                        "expression_en": "cautious tired expression",
                        "position": "foreground",
                    }
                ],
                "composition": {
                    "framing_en": "vertical cover composition",
                    "focus_en": "glowing smartphone screen",
                },
                "lighting": {
                    "quality_en": "cold divine light",
                },
                "mood_atmosphere_en": ["dry comedy"],
            }
        ],
    }


def test_tag_csv_formatter_preserves_native_negative_prompt() -> None:
    bundle = format_illustration_prompt(
        _sample_illustration_page(),
        tag_prompt="cover illustration, no text",
        negative_prompt="bad hands, logo",
        formatter=TAG_CSV,
        style_prefix="best quality, ",
    )
    assert bundle.prompt == "best quality, cover illustration, no text"
    assert bundle.negative_prompt == "bad hands, logo"
    assert bundle.formatter == TAG_CSV


def test_natural_sections_moves_negative_to_do_not_include() -> None:
    bundle = format_illustration_prompt(
        _sample_illustration_page(),
        tag_prompt="cover illustration, no text",
        negative_prompt="bad hands, logo",
        formatter=NATURAL_SECTIONS,
    )
    assert "Composition:" in bundle.prompt
    assert "Characters:" in bundle.prompt
    assert "Do not include:" in bundle.prompt
    assert "- bad hands" in bundle.prompt
    assert "- logo" in bundle.prompt
    assert "- comic panel borders" in bundle.prompt
    assert bundle.negative_prompt == ""
    assert bundle.negative_mode == INLINE_DO_NOT_INCLUDE


def test_natural_sections_keeps_composition_cells_for_multi_cell_illustration() -> None:
    page = _sample_illustration_page()
    page["panels"].append(
        {
            "panel_id": 2,
            "summary": "El stands behind Kazuki with a floating interface.",
            "composition": {"focus_en": "El's apologetic smile"},
        }
    )
    bundle = format_illustration_prompt(
        page,
        tag_prompt="cover illustration",
        negative_prompt="",
        formatter=NATURAL_SECTIONS,
    )
    assert "Composition Cells:" in bundle.prompt
    assert "Cell 1" in bundle.prompt
    assert "Cell 2" in bundle.prompt


def test_resolve_prompt_formatter_uses_provider_config() -> None:
    formatter = resolve_prompt_formatter(
        "grok_pro",
        "illustration",
        provider_cfg={
            "prompt_formatter": {
                "default": "natural_sections",
                "step1-pages": "manga_page_instruction",
            }
        },
    )
    assert formatter == NATURAL_SECTIONS


def test_manga_page_instruction_wraps_existing_prompt_and_inlines_negative() -> None:
    page = _sample_illustration_page()
    page["meta"]["intent"] = "manga_page"
    page["meta"]["reading_order"] = "right_to_left"
    page["manga"]["panel_layout"] = "three panels, top wide then two lower panels"
    bundle = format_manga_page_prompt(
        page,
        source="step1-pages",
        existing_prompt="以下は白黒1ページ分の詳細指示です。\n\nコマ1: Kazuki enters.",
        negative_prompt="watermark, logo",
        formatter=MANGA_PAGE_INSTRUCTION,
    )
    assert "Create one complete Japanese manga page" in bundle.prompt
    assert "Page Structure:" in bundle.prompt
    assert "Panel Outline:" in bundle.prompt
    assert "Source Page Instructions:" in bundle.prompt
    assert "コマ1: Kazuki enters." in bundle.prompt
    assert "- watermark" in bundle.prompt
    assert "- logo" in bundle.prompt
    assert bundle.negative_prompt == ""
    assert bundle.negative_mode == INLINE_DO_NOT_INCLUDE


def test_manga_panel_natural_sections_inlines_negative_and_keeps_panel_context() -> None:
    page = _sample_illustration_page()
    page["meta"]["intent"] = "manga_page"
    panel = page["panels"][0]
    panel["text"] = {"dialogue": [{"speaker": "kazuki", "text": "What is this place?"}]}
    bundle = format_manga_panel_prompt(
        page,
        panel,
        tag_prompt="manga panel, glowing smartphone, tired expression",
        negative_prompt="watermark, unreadable text",
        formatter=NATURAL_SECTIONS,
        style_prefix="best quality, ",
    )
    assert "Draw one polished Japanese manga panel" in bundle.prompt
    assert "Panel Context:" in bundle.prompt
    assert "Characters:" in bundle.prompt
    assert "Text Elements:" in bundle.prompt
    assert "What is this place?" in bundle.prompt
    assert "- watermark" in bundle.prompt
    assert "- unreadable text" in bundle.prompt
    assert bundle.negative_prompt == ""
    assert bundle.negative_mode == INLINE_DO_NOT_INCLUDE


def test_manga_panel_novelai_pipe_preserves_native_negative() -> None:
    page = _sample_illustration_page()
    panel = page["panels"][0]
    bundle = format_manga_panel_prompt(
        page,
        panel,
        tag_prompt="base tags | character tags",
        negative_prompt="bad hands",
        formatter=NOVELAI_PIPE,
        style_prefix="best quality, ",
    )
    assert bundle.prompt == "best quality, base tags | character tags"
    assert bundle.negative_prompt == "bad hands"
    assert bundle.negative_mode == "native"
