from __future__ import annotations

import copy
import json
import shutil
import sys
from types import SimpleNamespace
from pathlib import Path

import pytest
import yaml
from PIL import Image

_TOOLS_ROOT = Path(__file__).resolve().parents[2]
if str(_TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(_TOOLS_ROOT))

import image_provider_novel_manga_batch as manga_batch  # noqa: E402
from image_provider_generate import _novelai_augment_page_prompt  # noqa: E402
from image_provider_novel_manga_batch import iter_yaml_manga_jobs  # noqa: E402
from manga_prompt_ir.page_render_plan import (  # noqa: E402
    PageRenderPlanError,
    compile_page_render_plan,
)
from manga_prompt_ir.name_renderer import render_name_assets  # noqa: E402
from manga_prompt_ir.schemas.manga_page import MangaPagePrompt  # noqa: E402


_FIXTURE = _TOOLS_ROOT / "manga_prompt_ir" / "examples" / "manga_provider_direction_fixture.yaml"


def _page() -> dict:
    return yaml.safe_load(_FIXTURE.read_text(encoding="utf-8"))


def _existing_prompt() -> str:
    return (
        "Page 1\n"
        "コマ10: 主人公の導入。\n"
        "- セリフ: hero「これは……？」\n"
        "- モノローグ: 見覚えのない行き先だ。\n"
        "- ナレーション: 発車ベルのない夕暮れだった。\n"
        "- 効果音: ぎいっ（立ち上がる動き）"
    )


def test_provider_direction_fixture_is_schema_1_0_and_keeps_edge_cases() -> None:
    page = _page()
    model = MangaPagePrompt.model_validate(page)

    assert model.schema_version == "1.0"
    assert [panel.panel_id for panel in model.panels] == [10, 30, 50, 80]
    assert model.meta.reading_order.value == "left_to_right"
    assert model.panels[1].subjects[0].character_id is None
    assert page["manga"].get("text_policy") is None
    assert page["render_instruction"].get("text_policy") is None


def test_legacy_yaml_text_lines_extract_structured_text_content() -> None:
    lines = manga_batch.yaml_text_lines(
        {
            "text": {
                "monologue": [{"text_id": "m-001", "content": "独白の本文"}],
                "narration": [{"text_id": "n-001", "content": "ナレーションの本文"}],
            }
        }
    )

    assert lines == ["- モノローグ: 独白の本文", "- ナレーション: ナレーションの本文"]
    assert "text_id" not in "\n".join(lines)


@pytest.mark.parametrize("provider", ["novelai", "openai", "openrouter", "grok"])
@pytest.mark.parametrize("source", ["step1-pages", "step2-pages"])
def test_page_render_plan_compiles_three_providers_without_mutating_1_0(
    provider: str, source: str
) -> None:
    page = _page()
    before = copy.deepcopy(page)

    extra = {}
    if provider == "openrouter":
        extra["resolved_profile"] = "nano_banana_2"
    plan = compile_page_render_plan(
        page,
        source=source,
        provider=provider,
        existing_prompt=_existing_prompt(),
        negative_prompt="watermark",
        **extra,
    )

    assert page == before
    assert plan.schema_version == "1.0"
    assert plan.source_mode == source
    assert plan.provider == provider
    assert plan.formatter == "manga_page_instruction"
    if provider == "novelai":
        assert plan.negative_prompt == "watermark"
        assert plan.negative_mode == "native"
        assert plan.text_mode == "generate"
    else:
        assert plan.negative_prompt == ""
        assert plan.negative_mode == "inline_do_not_include"
        assert plan.text_mode == "generate"
    assert len(plan.text_manifest) == 4
    assert plan.text_manifest[0]["text_id"] == "p10-dialogue-01"
    assert {item["type"] for item in plan.text_manifest} == {
        "dialogue",
        "monologue",
        "narration",
        "sfx",
    }
    assert [item["panel_id"] for item in plan.text_manifest] == [10, 30, 50, 80]
    assert plan.ordered_image_inputs == []
    assert plan.name_images == []
    assert len(plan.unsupported) == (0 if provider == "openrouter" else 2)
    if provider == "novelai":
        assert "Page Structure:" not in plan.prompt
        assert "Source Page Instructions:" not in plan.prompt
        assert "Create one complete Japanese manga page" not in plan.prompt
    else:
        assert "Do not include:" in plan.prompt
        assert "- watermark" in plan.prompt
        assert "Page Structure:" in plan.prompt
        assert "Panel Outline:" in plan.prompt
    if provider == "novelai":
        assert "Text:" in plan.prompt
        assert "speaker=" not in plan.prompt
        assert "これは……？" in plan.prompt
        assert "exactly 1 empty" not in plan.prompt
        assert "Text Layout (structural; no lettering):" not in plan.prompt
        assert "text, speech bubble" in plan.prompt
        assert "白い吹き出し" not in plan.prompt
    else:
        assert "Text:" in plan.prompt
        assert plan.prompt.rstrip().endswith("ぎいっ")
        assert "text, speech bubble" not in plan.prompt
        assert "白い吹き出し" not in plan.prompt
    assert plan.metadata()["ordered_image_inputs"] == []
    assert plan.metadata()["name_images"] == []
    assert plan.metadata()["text_manifest_count"] == 4
    if provider == "novelai":
        assert plan.metadata()["effective_settings"]["quality_text_policy"] == (
            "preserve_text_block; visual_quality_suffix_may_contain_no_text"
        )


def test_page_step1_text_omits_repeated_quality_tags() -> None:
    from image_provider_novel_manga_batch import yaml_page_step1_text

    text = yaml_page_step1_text(_page(), {}, 1)

    assert "best_quality" not in text
    assert "very_aesthetic" not in text
    assert "ultra-detailed" not in text
    assert "ページ構成:" in text


def test_novelai_and_grok_page_sends_omit_japanese_gloss(tmp_path: Path) -> None:
    from image_provider_novel_manga_batch import omit_page_japanese_gloss_lines

    text = manga_batch.yaml_page_step1_text(_page(), {}, 1)
    assert "- 日本語訳:" in text
    stripped = omit_page_japanese_gloss_lines(text)
    assert "- 日本語訳:" not in stripped
    assert "コマ10:" in stripped

    novel_dir = tmp_path / "001_fixture"
    pages_dir = novel_dir / "manga" / "pages"
    pages_dir.mkdir(parents=True)
    (pages_dir / "manga_01_p01.yaml").write_text(
        yaml.safe_dump(_page(), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    common = {
        "cli_negative_prompt": "",
        "prompt_formatter": "manga_page_instruction",
        "page_compiler": "page_render_plan",
    }
    for provider in ("novelai", "grok", "grok_pro"):
        jobs = iter_yaml_manga_jobs(
            novel_dir, "manga_01", "step1-pages", provider, None, **common
        )
        assert "- 日本語訳:" not in jobs[0]["prompt"]
        assert "- 日本語訳:" not in jobs[0]["page_render_plan"].prompt
        assert "コマ10:" not in jobs[0]["prompt"]
        assert "panel_id" not in jobs[0]["prompt"]
        assert "上段いっぱい:" in jobs[0]["prompt"]
    openai_jobs = iter_yaml_manga_jobs(
        novel_dir, "manga_01", "step1-pages", "openai", None, **common
    )
    assert "- 日本語訳:" in openai_jobs[0]["prompt"]


def test_letter_later_keeps_full_manifest_but_removes_literal_text_from_prompt() -> None:
    page = _page()
    plan = compile_page_render_plan(
        page,
        source="step1-pages",
        provider="grok",
        existing_prompt=_existing_prompt(),
        negative_prompt="",
        text_mode="letter_later",
    )

    assert plan.text_mode == "letter_later"
    assert plan.text_manifest[0]["content"] == "これは……？"
    assert "これは……？" not in plan.prompt
    assert "見覚えのない行き先だ。" not in plan.prompt
    assert "発車ベルのない夕暮れだった。" not in plan.prompt
    assert "ぎいっ" not in plan.prompt
    assert "empty balloons" in plan.prompt
    assert "Text Layout (structural; no lettering):" in plan.prompt
    assert "exactly 1 empty speech bubble" in plan.prompt
    assert "Do not add any additional speech bubbles" in plan.prompt
    assert "do not render dialogue" in plan.text_policy
    assert plan.warnings == [
        "text_policy is omitted; the selected text_mode policy replaces the model default"
    ]


def test_letter_later_does_not_substring_replace_meaningful_summary_text() -> None:
    page = _page()
    page["panels"][0]["summary"] = "主人公が「これは……？」を見つめる導入。"

    plan = compile_page_render_plan(
        page,
        source="step1-pages",
        provider="grok",
        existing_prompt=_existing_prompt(),
        negative_prompt="",
        text_mode="letter_later",
    )

    assert "主人公が「これは……？」を見つめる導入。" in plan.prompt
    assert any("text content remains" in warning for warning in plan.warnings)


def test_none_keeps_manifest_but_compiles_a_text_free_prompt() -> None:
    plan = compile_page_render_plan(
        _page(),
        source="step1-pages",
        provider="grok",
        existing_prompt=_existing_prompt(),
        negative_prompt="",
        text_mode="none",
    )

    assert plan.text_mode == "none"
    assert len(plan.text_manifest) == 4
    assert all(item["content"] not in plan.prompt for item in plan.text_manifest)
    assert "Do not render text or lettering" in plan.prompt


def test_rtl_page_is_preserved_as_page_direction() -> None:
    page = _page()
    page["meta"]["reading_order"] = "right_to_left"

    plan = compile_page_render_plan(
        page,
        source="step2-pages",
        provider="grok",
        existing_prompt=_existing_prompt(),
        negative_prompt="",
    )

    assert "Non-rendered layout constraint:" in plan.prompt
    assert "right-to-left" in plan.prompt
    assert "Do not draw arrows, labels" in plan.prompt
    assert "Reading order: right_to_left" not in plan.prompt


def test_grok_layout_constraint_does_not_repeat_visible_reading_order_hints() -> None:
    page = _page()
    page["meta"]["reading_order"] = "right_to_left"
    page["render_instruction"]["output_policy"] = "コマ境界と右から左の読み順を明確にする。"
    existing = (
        "カラー漫画、1ページ4コマ、読み順: right_to_left\n"
        "コマ境界と右から左の読み順を明確にする。\n"
        "bottom panel: two characters"
    )
    grok = compile_page_render_plan(
        page,
        source="step1-pages",
        provider="grok_pro",
        existing_prompt=existing,
        negative_prompt="",
        text_mode="letter_later",
    )
    assert "Non-rendered layout constraint:" in grok.prompt
    assert "right-to-left" in grok.prompt
    assert "読み順:" not in grok.prompt
    assert "右から左" not in grok.prompt
    assert "Do not draw arrows, labels" in grok.prompt

    openai = compile_page_render_plan(
        page,
        source="step1-pages",
        provider="openai",
        existing_prompt=existing,
        negative_prompt="",
        text_mode="letter_later",
    )
    assert "Reading order: right_to_left" in openai.prompt
    assert "読み順: right_to_left" in openai.prompt


def test_generate_without_dialogue_keeps_novelai_text_marker() -> None:
    page = _page()
    for panel in page["panels"]:
        panel["text"] = {}

    plan = compile_page_render_plan(
        page,
        source="step1-pages",
        provider="novelai",
        existing_prompt="Page 1\nA silent page with empty acting space.",
        negative_prompt="",
        text_mode="generate",
    )

    assert plan.text_manifest == []
    assert "text, speech bubble" in plan.prompt
    assert plan.prompt.endswith("\n\nText:\n")
    augmented = _novelai_augment_page_prompt(
        "nai-diffusion-5-full",
        plan.prompt,
        metadata={"page_render_plan": plan.metadata()},
    )
    assert augmented.rstrip().endswith("Text:")
    assert "no text\n\nText:" in augmented


@pytest.mark.parametrize("overflow", ["panels", "fixed_tags"])
def test_page_compiler_rejects_formatter_budget_overflow(overflow: str) -> None:
    page = _page()
    if overflow == "panels":
        page["panels"] = page["panels"] * 4
        expected = "Panel Outline"
    else:
        page["character_snapshots"] = [{"character_id": "hero"}]
        page["character_snapshots"][0]["fixed_tags"] = [f"tag-{i}" for i in range(65)]
        expected = "character_line"

    with pytest.raises(PageRenderPlanError, match=expected):
        compile_page_render_plan(
            page,
            source="step1-pages",
            provider="grok",
            existing_prompt=_existing_prompt(),
            negative_prompt="",
        )


def test_page_compiler_keeps_fourteen_fixed_tags() -> None:
    page = _page()
    page["character_snapshots"] = [{"character_id": "hero"}]
    page["character_snapshots"][0]["fixed_tags"] = [f"tag-{i}" for i in range(14)]
    plan = compile_page_render_plan(
        page,
        source="step1-pages",
        provider="grok",
        existing_prompt=_existing_prompt(),
        negative_prompt="",
    )
    assert "tag-13" in plan.prompt


def test_explicit_text_policy_is_recorded_and_conflicts_are_rejected() -> None:
    page = _page()
    page["manga"]["text_policy"] = "Japanese text must be legible"
    page["render_instruction"]["text_policy"] = "No text in image"

    with pytest.raises(PageRenderPlanError, match="text_policy"):
        compile_page_render_plan(
            page,
            source="step2-pages",
            provider="openai",
            existing_prompt=_existing_prompt(),
            negative_prompt="",
        )

    page["render_instruction"].pop("text_policy")
    plan = compile_page_render_plan(
        page,
        source="step2-pages",
        provider="openai",
        existing_prompt=_existing_prompt(),
        negative_prompt="",
    )
    assert plan.text_mode == "generate"
    assert plan.declared_text_policies == [
        {
            "path": "manga.text_policy",
            "value": "Japanese text must be legible",
            "classified_as": "generate",
        }
    ]


def test_omitted_text_policy_is_distinguished_from_unclassifiable_explicit_policy() -> None:
    page = _page()
    plan = compile_page_render_plan(
        page,
        source="step1-pages",
        provider="grok",
        existing_prompt=_existing_prompt(),
        negative_prompt="",
    )
    assert plan.warnings == [
        "text_policy is omitted; the selected text_mode policy replaces the model default"
    ]

    page["render_instruction"]["text_policy"] = "文字要素の配置余白を確保する"
    plan = compile_page_render_plan(
        page,
        source="step1-pages",
        provider="grok",
        existing_prompt=_existing_prompt(),
        negative_prompt="",
    )
    assert plan.warnings == [
        "text_policy is explicit but not classifiable; the selected text_mode policy is used"
    ]


@pytest.mark.parametrize("provider", ["forge"])
def test_legacy_providers_are_rejected_by_new_page_compiler(provider: str) -> None:
    with pytest.raises(PageRenderPlanError, match="legacy"):
        compile_page_render_plan(
            _page(),
            source="step1-pages",
            provider=provider,
            existing_prompt=_existing_prompt(),
            negative_prompt="",
        )


def test_cli_rejects_page_compiler_for_forge(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    novel_dir = tmp_path / "001_fixture"
    pages_dir = novel_dir / "manga" / "pages"
    pages_dir.mkdir(parents=True)
    shutil.copy2(_FIXTURE, pages_dir / "manga_01_p01.yaml")

    rc = manga_batch.main(
        [
            str(novel_dir),
            "--manga-stem",
            "manga_01",
            "--source",
            "step1-pages",
            "--provider",
            "forge",
            "--page-compiler",
            "page_render_plan",
            "--dry-run",
        ]
    )
    captured = capsys.readouterr()

    assert rc == 2
    assert "provider=forge" in captured.err
    assert "legacy" in captured.err


def test_page_compiler_rejects_panel_mode_and_compiles_schema_1_1() -> None:
    with pytest.raises(PageRenderPlanError, match="ページ生成専用"):
        compile_page_render_plan(
            _page(),
            source="step1-panels",
            provider="grok",
            existing_prompt=_existing_prompt(),
            negative_prompt="",
        )

    page = _page()
    page["schema_version"] = "1.1"
    page["dramaturgy"] = {
        "purpose": "手紙の発見で次の選択を予告する",
        "purpose_en": "Foreshadow the next choice through the discovered letter.",
    }
    page["layout_geometry"] = {
        "panels": [
            {
                "panel_id": panel["panel_id"],
                "rect": {"x": 0.0, "y": index * 0.24, "w": 0.8, "h": 0.2},
            }
            for index, panel in enumerate(page["panels"])
        ]
    }
    page["continuity_tracks"] = [
        {"entity_id": "hero", "panel_id": 10, "state": "holding the envelope"}
    ]
    page["asset_references"] = [
        {"asset_id": "hero-001", "role": "character", "character_id": "hero"}
    ]
    for panel in page["panels"]:
        for index, subject in enumerate(panel["subjects"], start=1):
            if subject.get("character_id"):
                subject["subject_id"] = f"p{panel['panel_id']}-s{index:02d}"

    plan = compile_page_render_plan(
        page,
        source="step1-pages",
        provider="grok",
        existing_prompt=_existing_prompt(),
        negative_prompt="",
    )

    assert plan.schema_version == "1.1"
    assert "Foreshadow the next choice" in plan.prompt
    assert "Character Slots:" in plan.prompt
    assert "p10-s01" not in plan.prompt
    assert "panel_id" not in plan.prompt
    assert "slot_id" not in plan.prompt
    assert "character_id" not in plan.prompt
    assert "variant_id" not in plan.prompt
    assert "上段いっぱい" in plan.prompt
    assert "holding the envelope" in plan.prompt
    assert "Continuity Tracks:" in plan.prompt
    assert "p10-s01" in "\n".join(plan.page_context)
    assert plan.metadata()["character_slot_count"] == 2
    assert plan.metadata()["effective_settings"]["schema_1_1_context"] == (
        "common_prompt_sections"
    )


def test_image_prompt_drops_generic_text_ban_and_includes_costume_tags() -> None:
    page = _page()
    page["schema_version"] = "1.1"
    page["character_snapshots"] = [
        {
            "character_id": "hero",
            "name_en": "Hero",
            "selected_variant_id": "001_normal",
        }
    ]
    characters = {
        "hero": {
            "character_id": "hero",
            "prompt_variants": [
                {"variant_id": "000_base", "danbooru_tags": ["1boy", "black_hair"]},
                {"variant_id": "001_normal", "danbooru_tags": ["casual_jacket"]},
            ],
        }
    }

    plan = compile_page_render_plan(
        page,
        source="step1-pages",
        provider="grok",
        existing_prompt=_existing_prompt(),
        negative_prompt="watermark, text, logo",
        characters=characters,
    )

    omitted = plan.prompt.split("Do not include:", 1)[1]
    assert "- text\n" not in omitted
    assert "- panel numbers" in omitted
    assert "- watermark" in omitted
    assert "casual_jacket" in plan.prompt
    assert "black_hair" in plan.prompt
    assert "001_normal" not in plan.prompt
    assert "コマ10:" not in plan.prompt


def test_schema_1_1_novelai_slots_use_layout_centers_and_panel_negative(tmp_path: Path) -> None:
    novel_dir = tmp_path / "001_fixture"
    pages_dir = novel_dir / "manga" / "pages"
    pages_dir.mkdir(parents=True)
    page = _page()
    page["schema_version"] = "1.1"
    page["layout_geometry"] = {
        "panels": [
            {
                "panel_id": panel["panel_id"],
                "rect": {"x": 0.0, "y": index * 0.24, "w": 0.8, "h": 0.2},
            }
            for index, panel in enumerate(page["panels"])
        ]
    }
    page["panels"][0]["negative_tags"] = ["bad hands", "watermark"]
    page["panels"][0]["omit_negative_tags"] = ["watermark"]
    for panel in page["panels"]:
        for index, subject in enumerate(panel["subjects"], start=1):
            if subject.get("character_id"):
                subject["subject_id"] = f"p{panel['panel_id']}-s{index:02d}"
    (pages_dir / "manga_01_p01.yaml").write_text(
        yaml.safe_dump(page, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )

    jobs = iter_yaml_manga_jobs(
        novel_dir,
        "manga_01",
        "step2-pages",
        "novelai",
        None,
        cli_negative_prompt="",
        prompt_formatter="manga_page_instruction",
        page_compiler="page_render_plan",
        text_mode="generate",
    )

    assert len(jobs) == 1
    slots = jobs[0]["character_prompts"]
    assert len(slots) == 2
    assert slots[0]["center"] == {"x": 0.4, "y": 0.1}
    assert slots[0]["centers"] == [{"x": 0.4, "y": 0.1}]
    assert slots[1]["centers"] == [slots[1]["center"]]
    assert slots[0]["uc"] == "bad hands"
    assert "1コマ目" in slots[0]["prompt"]
    assert "白い吹き出し「これは……？」" in slots[0]["prompt"]
    assert "4コマ目" in slots[1]["prompt"]
    plan = jobs[0]["page_render_plan"]
    appearances = plan.character_slots
    assert [slot["character_id"] for slot in appearances] == ["hero", "hero"]
    assert [slot["panel_id"] for slot in appearances] == [10, 80]
    assert all(slot["centers"] == [slot["center"]] for slot in appearances)
    assert plan.metadata()["character_slot_count"] == 2


def test_novelai_slots_share_character_and_split_panel_centers() -> None:
    page = _page()
    page["schema_version"] = "1.1"
    page["layout_geometry"] = {
        "panels": [
            {"panel_id": 10, "rect": {"x": 0.04, "y": 0.03, "w": 0.92, "h": 0.28}}
        ]
    }
    page["panels"] = [page["panels"][0]]
    page["panels"][0]["subjects"] = [
        {
            "character_id": "kazuki",
            "variant_id": "001_normal",
            "description": "座る和紀",
            "pose_action_en": "looking at the ticket",
        },
        {
            "character_id": "yui",
            "variant_id": "001_normal",
            "description": "切符を持つ結",
            "pose_action_en": "holding out a paper ticket",
        },
    ]
    page["character_snapshots"] = [
        {"character_id": "kazuki", "name_en": "Kazuki"},
        {"character_id": "yui", "name_en": "Yui"},
    ]
    characters = {
        "kazuki": {
            "character_id": "kazuki",
            "prompt_variants": [
                {"variant_id": "000_base", "danbooru_tags": ["1boy", "black_hair"]},
                {"variant_id": "001_normal", "danbooru_tags": ["casual_jacket"]},
            ],
        }
    }

    slots = compile_page_render_plan(
        page,
        source="step1-pages",
        provider="novelai",
        existing_prompt=_existing_prompt(),
        negative_prompt="",
        characters=characters,
    ).character_slots

    assert [slot["character_id"] for slot in slots] == ["kazuki", "yui"]
    assert slots[0]["centers"] == [slots[0]["center"]]
    assert slots[0]["center"]["x"] != slots[1]["center"]["x"]
    assert "black_hair" in slots[0]["prompt"]
    assert "casual_jacket" in slots[0]["prompt"]
    assert "looking at the ticket" in slots[0]["prompt"]
    assert slots[0]["prompt"].startswith("1コマ目")


def test_schema_1_1_novelai_dialogue_stays_in_the_panel_slot() -> None:
    page = _page()
    page["schema_version"] = "1.1"
    long_line = "あ" * 751
    page["panels"][0]["text"]["dialogue"][0]["content"] = long_line

    plan = compile_page_render_plan(
        page,
        source="step1-pages",
        provider="novelai",
        existing_prompt=_existing_prompt(),
        negative_prompt="",
        text_mode="generate",
    )

    assert f"白い吹き出し「{long_line}」" in plan.character_slots[0]["prompt"]
    assert "Text:" not in plan.prompt


def test_schema_1_1_manifest_preserves_persistent_text_id() -> None:
    page = _page()
    page["schema_version"] = "1.1"
    page["panels"][0]["text"]["dialogue"][0]["text_id"] = "text-p10-dialogue-01"

    plan = compile_page_render_plan(
        page,
        source="step2-pages",
        provider="grok",
        existing_prompt=_existing_prompt(),
        negative_prompt="",
    )

    assert plan.text_manifest[0]["text_id"] == "text-p10-dialogue-01"


def test_schema_1_1_novelai_slot_dialogue_is_not_a_page_text_block() -> None:
    page = _page()
    page["schema_version"] = "1.1"
    line = "あ" * 370
    page["panels"][0]["text"]["dialogue"][0]["content"] = line

    plan = compile_page_render_plan(
        page,
        source="step1-pages",
        provider="novelai",
        existing_prompt=_existing_prompt(),
        negative_prompt="",
        text_mode="generate",
        novelai_model="nai-diffusion-5-curated",
    )

    assert f"白い吹き出し「{line}」" in plan.character_slots[0]["prompt"]
    assert "Text:" not in plan.prompt


def test_schema_1_1_novelai_slot_limit_stops_without_trimming() -> None:
    page = _page()
    page["schema_version"] = "1.1"
    subject_template = page["panels"][0]["subjects"][0]
    page["panels"][0]["subjects"] = [
        {
            **copy.deepcopy(subject_template),
            "character_id": f"hero-{index}",
            "subject_id": f"p10-s{index:02d}",
        }
        for index in range(1, 24)
    ]

    with pytest.raises(PageRenderPlanError, match="22"):
        compile_page_render_plan(
            page,
            source="step1-pages",
            provider="novelai",
            existing_prompt=_existing_prompt(),
            negative_prompt="",
        )


def test_page_render_plan_manifest_is_full_and_json_serializable(tmp_path: Path) -> None:
    plan = compile_page_render_plan(
        _page(),
        source="step2-pages",
        provider="novelai",
        existing_prompt=_existing_prompt(),
        negative_prompt="",
    )
    manifest_path = tmp_path / "page_render_plan.json"
    plan.write_manifest(manifest_path)
    saved = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert saved["page_hash"] == plan.page_hash
    assert len(saved["text_manifest"]) == 4
    assert saved["ordered_image_inputs"] == []
    assert saved["name_images"] == []
    assert saved["unsupported"] == plan.unsupported


def test_legacy_step1_panels_and_page_paths_remain_promptbundle_jobs(tmp_path: Path) -> None:
    novel_dir = tmp_path / "001_fixture"
    pages_dir = novel_dir / "manga" / "pages"
    pages_dir.mkdir(parents=True)
    shutil.copy2(_FIXTURE, pages_dir / "manga_01_p01.yaml")

    panel_jobs = iter_yaml_manga_jobs(
        novel_dir,
        "manga_01",
        "step1-panels",
        "forge",
        None,
        cli_negative_prompt="",
        prompt_formatter="tag_csv",
    )
    assert len(panel_jobs) == 4
    assert all("page_render_plan" not in job for job in panel_jobs)

    for provider, formatter in (("forge", "tag_csv"), ("openrouter", "manga_page_instruction")):
        page_jobs = iter_yaml_manga_jobs(
            novel_dir,
            "manga_01",
            "step1-pages",
            provider,
            None,
            cli_negative_prompt="",
            prompt_formatter=formatter,
        )
        assert len(page_jobs) == 1
        assert "page_render_plan" not in page_jobs[0]


def test_legacy_page_batch_reads_schema_1_1_without_compiler(tmp_path: Path) -> None:
    novel_dir = tmp_path / "001_fixture"
    pages_dir = novel_dir / "manga" / "pages"
    pages_dir.mkdir(parents=True)
    page = _page()
    page["schema_version"] = "1.1"
    page["render_instruction"]["text_mode"] = "letter_later"
    (pages_dir / "manga_01_p01.yaml").write_text(
        yaml.safe_dump(page, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )

    jobs = iter_yaml_manga_jobs(
        novel_dir,
        "manga_01",
        "step1-pages",
        "grok",
        None,
        cli_negative_prompt="",
        prompt_formatter="manga_page_instruction",
    )

    assert len(jobs) == 1
    assert "page_render_plan" not in jobs[0]


def test_cli_dry_run_reports_unsupported_inputs_without_writing_or_sending(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    novel_dir = tmp_path / "001_fixture"
    pages_dir = novel_dir / "manga" / "pages"
    pages_dir.mkdir(parents=True)
    shutil.copy2(_FIXTURE, pages_dir / "manga_01_p01.yaml")

    rc = manga_batch.main(
        [
            str(novel_dir),
            "--manga-stem",
            "manga_01",
            "--source",
            "step1-pages",
            "--provider",
            "grok",
            "--page-compiler",
            "page_render_plan",
            "--text-mode",
            "letter_later",
            "--negative-prompt",
            "",
            "--dry-run",
        ]
    )
    captured = capsys.readouterr()

    assert rc == 0
    assert "ordered_image_inputs: [] (none declared; not sent)" in captured.out
    assert "name_images: [] (none declared; not sent)" in captured.out
    assert "text_mode=letter_later" in captured.out
    assert "not written in dry-run" in captured.out
    assert not (novel_dir / "manga" / "_assets").exists()


def test_openrouter_page_compiler_cli_dry_run_uses_image_api_bridge(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    novel_dir = tmp_path / "001_fixture"
    pages_dir = novel_dir / "manga" / "pages"
    pages_dir.mkdir(parents=True)
    shutil.copy2(_FIXTURE, pages_dir / "manga_01_p01.yaml")

    rc = manga_batch.main(
        [
            str(novel_dir),
            "--manga-stem",
            "manga_01",
            "--source",
            "step1-pages",
            "--provider",
            "openrouter",
            "--page-compiler",
            "page_render_plan",
            "--text-mode",
            "letter_later",
            "--aspect-ratio",
            "manga_b5_portrait",
            "--dry-run",
        ]
    )
    captured = capsys.readouterr()

    assert rc == 0
    assert "provider: openrouter" in captured.out
    assert "transport: OpenRouter Image API (/images)" in captured.out
    assert "aspect_ratio: 3:4" in captured.out
    assert "text_mode=letter_later" in captured.out
    assert "capability_key=nano_banana_2" in captured.out
    assert "resolved_model: google/gemini-3.1-flash-image" in captured.out
    assert "openrouter_profile: nano_banana_2" in captured.out
    assert "unsupported:" in captured.out
    assert not (novel_dir / "manga" / "_assets").exists()


def test_openrouter_page_compiler_cli_dry_run_shows_gpt_image_profile(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    novel_dir = tmp_path / "001_fixture"
    pages_dir = novel_dir / "manga" / "pages"
    pages_dir.mkdir(parents=True)
    shutil.copy2(_FIXTURE, pages_dir / "manga_01_p01.yaml")

    rc = manga_batch.main(
        [
            str(novel_dir),
            "--manga-stem",
            "manga_01",
            "--source",
            "step1-pages",
            "--provider",
            "openrouter",
            "--page-compiler",
            "page_render_plan",
            "--text-mode",
            "letter_later",
            "--aspect-ratio",
            "manga_b5_portrait",
            "--model",
            "gpt_image_2",
            "--image-quality",
            "high",
            "--dry-run",
        ]
    )
    captured = capsys.readouterr()

    assert rc == 0
    assert "resolved_model: openai/gpt-image-2" in captured.out
    assert "openrouter_profile: gpt_image_2 parameter_family=quality" in captured.out
    assert "capability_key=gpt_image_2" in captured.out
    assert "image_quality: high" in captured.out
    assert not (novel_dir / "manga" / "_assets").exists()


def test_cli_writes_page_manifest_separately_from_provider_payload(
    tmp_path: Path, monkeypatch
) -> None:
    novel_dir = tmp_path / "001_fixture"
    pages_dir = novel_dir / "manga" / "pages"
    pages_dir.mkdir(parents=True)
    shutil.copy2(_FIXTURE, pages_dir / "manga_01_p01.yaml")

    monkeypatch.setattr(
        manga_batch.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )
    rc = manga_batch.main(
        [
            str(novel_dir),
            "--manga-stem",
            "manga_01",
            "--source",
            "step2-pages",
            "--provider",
            "grok",
            "--page-compiler",
            "page_render_plan",
            "--negative-prompt",
            "",
        ]
    )

    manifest_path = (
        novel_dir
        / "manga"
        / "_assets"
        / "manga_01"
        / "comic"
        / "manga_01_p01_page_render_plan.json"
    )
    assert rc == 0
    assert manifest_path.is_file()
    saved = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert len(saved["text_manifest"]) == 4
    assert saved["ordered_image_inputs"] == []
    assert saved["name_images"] == []


def test_p3_resolves_name_and_role_references_in_declared_order(tmp_path: Path) -> None:
    page = _page()
    page["schema_version"] = "1.1"
    Image.new("RGB", (320, 180), (240, 240, 240)).save(tmp_path / "name.png")
    Image.new("RGB", (128, 128), (80, 100, 120)).save(tmp_path / "hero.png")
    page["asset_references"] = [
        {"asset_id": "page-name", "role": "layout", "path": "name.png"},
        {
            "asset_id": "hero-ref",
            "role": "character",
            "path": "hero.png",
            "character_id": "hero",
            "variant_id": "001_normal",
        },
    ]
    plan = compile_page_render_plan(
        page,
        source="step1-pages",
        provider="grok",
        existing_prompt=_existing_prompt(),
        negative_prompt="",
        asset_base_dir=tmp_path,
    )
    assert [item["order"] for item in plan.ordered_image_inputs] == [1, 2]
    assert [item["role"] for item in plan.ordered_image_inputs] == [
        "layout",
        "character",
    ]
    assert [item["asset_id"] for item in plan.name_images] == ["page-name"]
    assert "attachment=image 1 (layout)" in "\n".join(plan.page_context)
    assert plan.effective_settings["image_reference_contract"]["ordered_count"] == 2
    assert plan.unsupported == []


def test_openrouter_page_compiler_accepts_schema_1_1_and_keeps_reference_order(
    tmp_path: Path,
) -> None:
    page = _page()
    page["schema_version"] = "1.1"
    Image.new("RGB", (320, 180), (240, 240, 240)).save(tmp_path / "name.png")
    Image.new("RGB", (128, 128), (80, 100, 120)).save(tmp_path / "hero.png")
    page["asset_references"] = [
        {"asset_id": "page-name", "role": "layout", "path": "name.png"},
        {
            "asset_id": "hero-ref",
            "role": "character",
            "path": "hero.png",
            "character_id": "hero",
            "variant_id": "001_normal",
        },
    ]

    plan = compile_page_render_plan(
        page,
        source="step1-pages",
        provider="openrouter",
        existing_prompt=_existing_prompt(),
        negative_prompt="watermark",
        text_mode="letter_later",
        asset_base_dir=tmp_path,
        resolved_profile="gpt_image_2",
    )

    assert plan.provider == "openrouter"
    assert plan.schema_version == "1.1"
    assert plan.text_mode == "letter_later"
    assert [item["order"] for item in plan.ordered_image_inputs] == [1, 2]
    assert [item["role"] for item in plan.ordered_image_inputs] == [
        "layout",
        "character",
    ]
    assert plan.unsupported == []
    assert plan.metadata()["effective_settings"]["schema_1_1_context"] == (
        "common_prompt_sections"
    )


def test_p3_missing_explicit_reference_stops_before_provider_payload(tmp_path: Path) -> None:
    page = _page()
    page["schema_version"] = "1.1"
    page["asset_references"] = [
        {"asset_id": "missing", "role": "layout", "path": "missing.png"}
    ]
    with pytest.raises(PageRenderPlanError, match="参照画像が見つかりません"):
        compile_page_render_plan(
            page,
            source="step2-pages",
            provider="openai",
            existing_prompt=_existing_prompt(),
            negative_prompt="",
            asset_base_dir=tmp_path,
        )


def test_p3_novelai_rejects_resolved_page_inputs_at_batch_boundary(tmp_path: Path) -> None:
    page = _page()
    page["schema_version"] = "1.1"
    novel_dir = tmp_path / "novel"
    novel_dir.mkdir()
    Image.new("RGB", (64, 64), (0, 0, 0)).save(novel_dir / "name.png")
    page["asset_references"] = [
        {"asset_id": "page-name", "role": "layout", "path": "name.png"}
    ]
    pages_dir = novel_dir / "manga" / "pages"
    pages_dir.mkdir(parents=True)
    (pages_dir / "manga_01_p01.yaml").write_text(
        yaml.safe_dump(page, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    with pytest.raises(PageRenderPlanError, match="OpenAI/OpenRouter/Grok"):
        iter_yaml_manga_jobs(
            novel_dir,
            "manga_01",
            "step1-pages",
            "novelai",
            "page_render_plan",
            cli_negative_prompt="",
            prompt_formatter="manga_page_instruction",
            page_compiler="page_render_plan",
        )


def test_openrouter_batch_keeps_resolved_page_inputs_at_batch_boundary(
    tmp_path: Path,
) -> None:
    page = _page()
    page["schema_version"] = "1.1"
    novel_dir = tmp_path / "novel"
    novel_dir.mkdir()
    Image.new("RGB", (64, 64), (0, 0, 0)).save(novel_dir / "name.png")
    page["asset_references"] = [
        {"asset_id": "page-name", "role": "layout", "path": "name.png"}
    ]
    pages_dir = novel_dir / "manga" / "pages"
    pages_dir.mkdir(parents=True)
    (pages_dir / "manga_01_p01.yaml").write_text(
        yaml.safe_dump(page, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )

    jobs = iter_yaml_manga_jobs(
        novel_dir,
        "manga_01",
        "step1-pages",
        "openrouter",
        "page_render_plan",
        cli_negative_prompt="",
        prompt_formatter="manga_page_instruction",
        page_compiler="page_render_plan",
    )

    assert len(jobs) == 1
    assert [item["order"] for item in jobs[0]["image_inputs"]] == [1]
    assert jobs[0]["image_inputs"][0]["role"] == "layout"
    assert jobs[0]["page_render_plan"].unsupported == []


def test_p3_name_renderer_uses_geometry_order_and_emits_numbered_proof(tmp_path: Path) -> None:
    page = _page()
    page["schema_version"] = "1.1"
    page["layout_geometry"] = {
        "panels": [
            {"panel_id": 10, "rect": {"x": 0.05, "y": 0.05, "w": 0.4, "h": 0.4}},
            {"panel_id": 30, "rect": {"x": 0.55, "y": 0.55, "w": 0.4, "h": 0.4}},
            {"panel_id": 50, "rect": {"x": 0.55, "y": 0.05, "w": 0.4, "h": 0.4}},
            {"panel_id": 80, "rect": {"x": 0.05, "y": 0.55, "w": 0.4, "h": 0.4}},
        ]
    }
    rendered = render_name_assets(page, tmp_path, prefix="manga_01_p01")
    assert rendered["numbered"]["panel_ids"] == [10, 30, 50, 80]
    assert rendered["model"]["kind"] == "model_name_input"
    assert Path(rendered["numbered"]["path"]).is_file()
    assert Path(rendered["model"]["path"]).is_file()
    assert rendered["numbered"]["sha256"] != rendered["model"]["sha256"]


def test_local_frame_mode_is_novelai_page_render_plan_only() -> None:
    page = _page()
    page["schema_version"] = "1.1"
    with pytest.raises(PageRenderPlanError, match="NovelAI"):
        compile_page_render_plan(
            page,
            source="step1-pages",
            provider="grok",
            existing_prompt=_existing_prompt(),
            negative_prompt="",
            bubble_frame_mode="local",
        )
    with pytest.raises(PageRenderPlanError, match="NovelAI"):
        compile_page_render_plan(
            page,
            source="step1-pages",
            provider="openai",
            existing_prompt=_existing_prompt(),
            negative_prompt="",
            bubble_frame_mode="local",
        )
    with pytest.raises(PageRenderPlanError, match="併用"):
        compile_page_render_plan(
            page,
            source="step1-pages",
            provider="novelai",
            existing_prompt=_existing_prompt(),
            negative_prompt="",
            text_mode="letter_later",
            bubble_frame_mode="local",
        )


def test_novelai_local_strips_slot_balloons_and_text_layout() -> None:
    page = _page()
    page["schema_version"] = "1.1"
    plan = compile_page_render_plan(
        page,
        source="step1-pages",
        provider="novelai",
        existing_prompt=_existing_prompt(),
        negative_prompt="",
        bubble_frame_mode="local",
    )
    assert plan.bubble_frame_mode == "local"
    assert plan.text_mode == "none"
    assert plan.capability_key == "novelai_v5"
    assert plan.effective_settings["capability"]["postprocess_recommended"] is True
    assert plan.effective_settings["bubbles_suppressed"] is True
    assert plan.effective_settings["resolved_model"] in {None, "nai-diffusion-5-full"}
    assert plan.character_slots
    assert all("白い吹き出し" not in slot["prompt"] for slot in plan.character_slots)
    assert "exactly 1 empty speech bubble" not in plan.prompt
    assert "Text Layout" not in plan.prompt
    grok = compile_page_render_plan(
        page,
        source="step1-pages",
        provider="grok",
        existing_prompt=_existing_prompt(),
        negative_prompt="",
        text_mode="letter_later",
    )
    assert grok.capability_key == "grok_imagine_2"
    assert grok.bubble_frame_mode == "provider"
    assert grok.effective_settings["capability"]["provisional"] is True
    assert grok.effective_settings["bubbles_suppressed"] is False
    assert "exactly 1 empty speech bubble" in grok.prompt


def test_novelai_omitted_text_mode_is_generate_t1() -> None:
    page = _page()
    page["schema_version"] = "1.1"
    plan = compile_page_render_plan(
        page,
        source="step1-pages",
        provider="novelai",
        existing_prompt=_existing_prompt(),
        negative_prompt="",
    )
    assert plan.text_mode == "generate"
    assert plan.bubble_frame_mode == "provider"
    assert plan.effective_settings["bubbles_suppressed"] is False
    slot_text = "\n".join(slot["prompt"] for slot in plan.character_slots)
    assert "白い吹き出し「これは……？」" in slot_text
    assert "text, speech bubble" in plan.prompt
    assert "exactly 1 empty speech bubble" not in plan.prompt
    grok = compile_page_render_plan(
        page,
        source="step1-pages",
        provider="grok",
        existing_prompt=_existing_prompt(),
        negative_prompt="",
    )
    assert grok.text_mode == "generate"
    assert grok.bubble_frame_mode == "provider"
    grok_slots = "\n".join(slot["prompt"] for slot in grok.character_slots)
    assert "白い吹き出し" not in grok.prompt
    assert "白い吹き出し" not in grok_slots
    assert "text, speech bubble" not in grok.prompt


def test_unregistered_resolved_models_stop_at_compiler() -> None:
    page = _page()
    with pytest.raises(PageRenderPlanError, match="未登録"):
        compile_page_render_plan(
            page,
            source="step1-pages",
            provider="openai",
            existing_prompt=_existing_prompt(),
            negative_prompt="",
            resolved_model="gpt-image-1.5",
        )
    with pytest.raises(PageRenderPlanError, match="未登録"):
        compile_page_render_plan(
            page,
            source="step1-pages",
            provider="grok",
            existing_prompt=_existing_prompt(),
            negative_prompt="",
            resolved_model="grok-imagine-image",
        )
    with pytest.raises(PageRenderPlanError, match="未登録"):
        compile_page_render_plan(
            page,
            source="step1-pages",
            provider="novelai",
            existing_prompt=_existing_prompt(),
            negative_prompt="",
            resolved_model="nai-diffusion-4-5-full",
        )


def test_yaml_text_mode_beats_work_lettering_flag(tmp_path: Path) -> None:
    novel_dir = tmp_path / "001_fixture"
    pages_dir = novel_dir / "manga" / "pages"
    pages_dir.mkdir(parents=True)
    src = (
        _TOOLS_ROOT
        / "manga_prompt_ir"
        / "examples"
        / "p4_compare"
        / "manga"
        / "pages"
        / "manga_01_p01.yaml"
    )
    shutil.copy2(src, pages_dir / "manga_01_p01.yaml")
    char_src = (
        _TOOLS_ROOT / "manga_prompt_ir" / "examples" / "p4_compare" / "tag" / "characters"
    )
    char_dst = novel_dir / "tag" / "characters"
    shutil.copytree(char_src, char_dst)
    (novel_dir / "_meta.yaml").write_text(
        "version: 1\nmanga_lettering:\n  enabled: true\n",
        encoding="utf-8",
    )
    jobs = iter_yaml_manga_jobs(
        novel_dir,
        "manga_01",
        "step1-pages",
        "grok",
        None,
        cli_negative_prompt="",
        prompt_formatter="manga_page_instruction",
        page_compiler="page_render_plan",
    )
    assert len(jobs) == 1
    assert jobs[0]["page_render_plan"].text_mode == "generate"


def test_lettering_flag_hides_legacy_grok_text_when_yaml_omits_mode(
    tmp_path: Path,
) -> None:
    novel_dir = tmp_path / "001_fixture"
    pages_dir = novel_dir / "manga" / "pages"
    pages_dir.mkdir(parents=True)
    shutil.copy2(_FIXTURE, pages_dir / "manga_01_p01.yaml")
    (novel_dir / "_meta.yaml").write_text(
        "version: 1\nmanga_lettering:\n  enabled: true\n",
        encoding="utf-8",
    )
    jobs = iter_yaml_manga_jobs(
        novel_dir,
        "manga_01",
        "step1-pages",
        "grok",
        None,
        cli_negative_prompt="",
        prompt_formatter="manga_page_instruction",
        page_compiler="legacy",
    )
    assert len(jobs) == 1
    assert "page_render_plan" not in jobs[0]
    assert "これは……？" not in jobs[0]["prompt"]
