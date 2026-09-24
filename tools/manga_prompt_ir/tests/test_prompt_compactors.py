from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest
import yaml

_TOOLS_ROOT = Path(__file__).resolve().parents[2]
if str(_TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(_TOOLS_ROOT))

from image_provider_generate import _novelai_augment_page_prompt  # noqa: E402
from manga_prompt_ir.page_render_plan import (  # noqa: E402
    PageRenderPlanError,
    compile_page_render_plan,
)
from manga_prompt_ir.prompt_compactors import compact_page_prompt  # noqa: E402


_FIXTURE = _TOOLS_ROOT / "manga_prompt_ir" / "examples" / "manga_provider_direction_fixture.yaml"


def _page() -> dict:
    return yaml.safe_load(_FIXTURE.read_text(encoding="utf-8"))


def test_common_compactor_is_deterministic_and_promotes_page_tags() -> None:
    page = _page()
    before = copy.deepcopy(page)

    first = compact_page_prompt(page, source="step1-pages", mode="safe")
    second = compact_page_prompt(page, source="step1-pages", mode="safe")

    assert first == second
    assert page == before
    assert "manga" in first.page_common_tags
    assert all("manga" not in delta.tags for delta in first.panel_deltas)
    assert first.panel_outlines[0].text == "主人公がベンチで封筒を見つめる導入。"
    assert [item.type for item in first.text_manifest] == [
        "dialogue",
        "monologue",
        "narration",
        "sfx",
    ]
    assert first.negative_tags == ("watermark", "unreadable text")


def test_step2_compactor_uses_step2_summary_without_duplicating_step1_summary() -> None:
    page = _page()
    page["panels"][0]["step2_summary"] = "Step2用の短い構成要約。"

    result = compact_page_prompt(page, source="step2-pages", mode="safe")

    assert result.panel_outlines[0].text == "Step2用の短い構成要約。"
    assert all(item.text != page["panels"][0]["summary"] for item in result.panel_outlines)


def test_variant_fixed_tag_mismatch_stops_without_union() -> None:
    page = _page()
    page["panels"][0]["subjects"][0]["variant_id"] = "001_normal"
    page["panels"][0]["subjects"][0]["character_id"] = "hero"
    page["panels"][0]["subjects"][0]["description"] = "hero"
    page["panels"][3]["subjects"][0]["variant_id"] = "002_changed"
    page["character_snapshots"] = [
        {
            "character_id": "hero",
            "selected_variant_id": "001_normal",
            "fixed_tags": ["black_hair"],
            "variant_tags": ["casual_jacket"],
        },
        {
            "character_id": "hero",
            "selected_variant_id": "002_changed",
            "fixed_tags": ["white_hair"],
            "variant_tags": ["formal_coat"],
        },
    ]

    with pytest.raises(ValueError, match="固定タグ集合"):
        compact_page_prompt(page, source="step1-pages", mode="safe")


def test_novelai_compaction_replaces_old_body_and_keeps_text_order() -> None:
    plan = compile_page_render_plan(
        _page(),
        source="step1-pages",
        provider="novelai",
        existing_prompt="OLD BODY MUST NOT BE COPIED",
        negative_prompt="watermark",
        prompt_compaction="safe",
    )

    assert "OLD BODY MUST NOT BE COPIED" not in plan.prompt
    assert "Page Common:" in plan.prompt
    assert "Panel Text Cues:" in plan.prompt
    assert plan.prompt.index("Panel Text Cues:") < plan.prompt.index("Text:")
    assert "これは……？" in plan.prompt.split("Text:", 1)[1]
    assert "見覚えのない行き先だ。" in plan.prompt.split("Panel Text Cues:", 1)[1]
    assert "masterpiece" not in plan.prompt
    assert plan.effective_settings["prompt_compaction"] == "safe"


def test_promote_fixed_removes_identity_from_slot_but_keeps_variant_clothing() -> None:
    root = _TOOLS_ROOT / "manga_prompt_ir" / "examples" / "p4_compare"
    page = yaml.safe_load(
        (root / "manga" / "pages" / "manga_01_p01.yaml").read_text(encoding="utf-8")
    )
    characters = {}
    for path in sorted((root / "tag" / "characters").glob("*.yaml")):
        item = yaml.safe_load(path.read_text(encoding="utf-8"))
        characters[item["character_id"]] = item

    safe = compile_page_render_plan(
        page,
        source="step1-pages",
        provider="novelai",
        existing_prompt="old",
        negative_prompt="",
        characters=characters,
        prompt_compaction="safe",
    )
    promoted = compile_page_render_plan(
        page,
        source="step1-pages",
        provider="novelai",
        existing_prompt="old",
        negative_prompt="",
        characters=characters,
        prompt_compaction="promote-fixed",
    )

    safe_prompt = safe.character_slots[0]["prompt"]
    promoted_prompt = promoted.character_slots[0]["prompt"]
    assert "black_hair" in safe_prompt
    assert "black_hair" not in promoted_prompt
    assert "navy_harrington_jacket" in safe_prompt
    assert "navy_harrington_jacket" in promoted_prompt
    assert promoted.character_slots[0]["uc"] == safe.character_slots[0]["uc"]
    assert promoted.character_slots[0]["center"] == safe.character_slots[0]["center"]
    assert "Text:" not in promoted.prompt


def test_schema_1_0_novelai_text_limit_stops_without_cutting() -> None:
    page = _page()
    page["panels"][0]["text"]["dialogue"][0]["content"] = "あ" * 751

    with pytest.raises(PageRenderPlanError, match="文字を省略しません"):
        compile_page_render_plan(
            page,
            source="step1-pages",
            provider="novelai",
            existing_prompt="old",
            negative_prompt="",
            prompt_compaction="safe",
        )


def test_panel_text_cues_are_not_counted_against_dialogue_limit() -> None:
    page = _page()
    page["panels"][1]["text"]["monologue"][0] = "い" * 2000

    plan = compile_page_render_plan(
        page,
        source="step1-pages",
        provider="novelai",
        existing_prompt="old",
        negative_prompt="",
        prompt_compaction="safe",
    )

    assert "い" * 2000 in plan.prompt
    assert "Text:" in plan.prompt


def test_compacted_letter_later_keeps_empty_region_layout_without_literal_text() -> None:
    page = _page()
    plan = compile_page_render_plan(
        page,
        source="step1-pages",
        provider="novelai",
        existing_prompt="old",
        negative_prompt="",
        text_mode="letter_later",
        prompt_compaction="safe",
    )

    assert "Text Layout (structural; no lettering):" in plan.prompt
    assert "これは……？" not in plan.prompt
    assert "見覚えのない行き先だ。" not in plan.prompt
    assert "Text:" not in plan.prompt


def test_generate_no_text_conflict_stops_before_rendering() -> None:
    page = _page()
    page["panels"][0]["prompt_tags"] = ["no text"]

    with pytest.raises(PageRenderPlanError, match="no text"):
        compile_page_render_plan(
            page,
            source="step1-pages",
            provider="novelai",
            existing_prompt="old",
            negative_prompt="",
            prompt_compaction="safe",
        )


def test_novelai_quality_suffix_stays_before_panel_cues_and_text() -> None:
    prompt = "visual body\n\nPanel Text Cues:\n- panel 1 narration: cue\n\nText:\n台詞"
    result = _novelai_augment_page_prompt(
        "nai-diffusion-4-5-full",
        prompt,
        metadata={"page_render_plan": {"text_mode": "generate"}},
    )

    assert result.index("no text") < result.index("Panel Text Cues:")
    assert result.index("Panel Text Cues:") < result.index("Text:")
    assert result.endswith("Text:\n台詞")
