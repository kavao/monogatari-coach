from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

_TOOLS_ROOT = Path(__file__).resolve().parents[2]
if str(_TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(_TOOLS_ROOT))

from manga_prompt_ir.page_render_plan import compile_page_render_plan  # noqa: E402
from manga_prompt_ir.schemas.character import CharacterPrompt  # noqa: E402
from manga_prompt_ir.schemas.manga_page import MangaPagePrompt  # noqa: E402

_P4 = _TOOLS_ROOT / "manga_prompt_ir" / "examples" / "p4_compare"
_PAGES = _P4 / "manga" / "pages"


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "name",
    ["manga_01_p01.yaml", "manga_02_p01.yaml", "manga_03_p01.yaml", "manga_03_p02.yaml"],
)
def test_p4_compare_pages_validate_as_schema_1_1(name: str) -> None:
    page = _load(_PAGES / name)
    model = MangaPagePrompt.model_validate(page)
    assert model.schema_version == "1.1"
    assert model.layout_geometry is not None
    assert model.dramaturgy is not None


def test_p4_character_yaml_validates() -> None:
    for name in ("kazuki.yaml", "yui.yaml"):
        CharacterPrompt.model_validate(
            yaml.safe_load((_P4 / "tag" / "characters" / name).read_text(encoding="utf-8"))
        )


def test_p4_page_a_compiles_for_page_providers_and_letter_later() -> None:
    page = _load(_PAGES / "manga_01_p01.yaml")
    assert page["manga"]["lettering"] == {
        "direction": "vertical",
        "base_font_size": 30,
        "size_policy": "uniform_then_shrink",
    }
    for provider in ("novelai", "openai", "openrouter", "grok"):
        plan = compile_page_render_plan(
            page,
            source="step1-pages",
            provider=provider,
            existing_prompt="Page A comparison fixture",
            negative_prompt="watermark",
        )
        assert [item["panel_id"] for item in plan.text_manifest] == [10, 20, 30, 40]
        assert all(item["writing_direction"] == "vertical" for item in plan.text_manifest)
        if provider == "novelai":
            assert plan.text_mode == "generate"
            slot_text = "\n".join(slot["prompt"] for slot in plan.character_slots)
            assert "白い吹き出し「これ、見て。」" in slot_text
            assert "白い吹き出し「……行こう。」" in slot_text
            assert "speaker=" not in plan.prompt
            assert "Text:" not in plan.prompt
            assert all(len(slot["centers"]) == 1 for slot in plan.character_slots)
        else:
            assert "これ、見て。" in plan.prompt
        assert plan.ordered_image_inputs == []
    later = compile_page_render_plan(
        page,
        source="step1-pages",
        provider="grok",
        existing_prompt="Page A comparison fixture",
        negative_prompt="",
        text_mode="letter_later",
    )
    assert later.text_mode == "letter_later"
    assert "これ、見て。" not in later.prompt
    assert later.text_manifest[0]["content"] == "これ、見て。"
    assert "baseline lettering direction: vertical Japanese writing" in later.prompt
    assert "lettering direction: vertical" in later.prompt
    assert later.prompt.count("exactly 1 empty speech bubble") == 4
    assert "assigned speaker(s): Yui" in later.prompt
    assert "assigned speaker(s): Kazuki" in later.prompt
    assert "Do not add any additional speech bubbles" in later.prompt
