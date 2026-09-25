from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

pytest.importorskip("pydantic")
pytest.importorskip("yaml")

_TOOLS_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_TOOLS_ROOT))

from manga_prompt_ir.character_visual_resolver import (
    VisualResolverError,
    character_source_sha256,
    resolve_character_visual,
)
from manga_prompt_ir.converters.yaml_loader import load_model
from manga_prompt_ir.page_render_plan import PageRenderPlanError, compile_page_render_plan
from manga_prompt_ir.prompt_formatters import character_line
from manga_prompt_ir.schemas.character import CharacterPrompt
from manga_prompt_ir.schemas.manga_page import MangaPagePrompt
from novel_prompt_ir_export_md import render_character_md

_PKG_ROOT = Path(__file__).resolve().parents[1]
_EXAMPLES = _PKG_ROOT / "examples"


def _character_1_1() -> CharacterPrompt:
    return load_model(_EXAMPLES / "character_1_1.yaml", CharacterPrompt)


def test_schema_1_0_still_loads() -> None:
    character = load_model(_EXAMPLES / "character.yaml", CharacterPrompt)
    assert character.schema_version == "1.0"
    assert "casual_jacket" in character.variant_danbooru_tags("001_normal")


def test_schema_1_1_kinds_and_resolver() -> None:
    character = _character_1_1()
    costume = resolve_character_visual(character, "001_normal")
    assert "navy_harrington_jacket" in costume.danbooru_tags
    assert "no_hood" in costume.danbooru_tags
    assert "fold_down_collar" in costume.danbooru_tags
    assert "zip_front" in costume.danbooru_tags
    assert "gray_crew_neck_tshirt" in costume.danbooru_tags
    assert "dark_navy_straight_pants" in costume.danbooru_tags
    assert "black_hair" in costume.danbooru_tags
    assert "pointed_ears" in costume.danbooru_tags
    assert "smartphone" in costume.danbooru_tags
    assert costume.natural.count("smartphone") == 1
    assert "tired but alert eyes" in costume.danbooru_tags
    state = resolve_character_visual(character, "002_jacket_open")
    assert "jacket_open" in state.danbooru_tags
    assert "navy_harrington_jacket" in state.danbooru_tags
    derived = resolve_character_visual(character, "007_wet")
    assert "wet_clothes" in derived.danbooru_tags
    assert "nude" in derived.danbooru_tags


def test_missing_visual_spec_stops() -> None:
    raw = _character_1_1().model_dump(mode="json")
    raw["prompt_variants"][1]["visual_spec"] = None
    with pytest.raises(Exception, match="visual_spec"):
        CharacterPrompt.model_validate(raw)


def test_legacy_costume_tags_stop() -> None:
    raw = _character_1_1().model_dump(mode="json")
    raw["costume"]["outfit_tags"] = ["casual_jacket"]
    with pytest.raises(Exception, match="costume"):
        CharacterPrompt.model_validate(raw)


def test_dark_pants_on_base_stops() -> None:
    raw = _character_1_1().model_dump(mode="json")
    raw["prompt_variants"][0]["danbooru_tags"].append("dark_pants")
    with pytest.raises(Exception, match="衣装語"):
        CharacterPrompt.model_validate(raw)


def test_duplicate_variant_stops() -> None:
    raw = _character_1_1().model_dump(mode="json")
    raw["prompt_variants"].append(copy.deepcopy(raw["prompt_variants"][1]))
    with pytest.raises(Exception, match="重複"):
        CharacterPrompt.model_validate(raw)


def test_unknown_variant_stops() -> None:
    character = _character_1_1()
    with pytest.raises(VisualResolverError, match="未知"):
        resolve_character_visual(character, "009_missing")


def test_combines_with_cycle_stops() -> None:
    raw = _character_1_1().model_dump(mode="json")
    raw["prompt_variants"][3]["combines_with"] = "007_wet"
    with pytest.raises(Exception, match="循環"):
        CharacterPrompt.model_validate(raw)


def test_danbooru_mismatch_stops() -> None:
    raw = _character_1_1().model_dump(mode="json")
    raw["prompt_variants"][1]["danbooru_tags"] = ["casual_jacket"]
    with pytest.raises(Exception, match="不一致"):
        CharacterPrompt.model_validate(raw)


def test_hash_ignores_yaml_key_order() -> None:
    character = _character_1_1()
    dumped = character.model_dump(mode="json")
    reordered = json.loads(json.dumps(dumped, sort_keys=True))
    assert character_source_sha256(dumped) == character_source_sha256(reordered)
    assert character_source_sha256(character) == character_source_sha256(dumped)


def _page_for(character: CharacterPrompt, variant_id: str, *, sha: str | None = None) -> dict:
    digest = sha if sha is not None else character_source_sha256(character)
    resolved = resolve_character_visual(character, variant_id)
    return {
        "schema_version": "1.0",
        "meta": {
            "intent": "manga_page",
            "reading_order": "right_to_left",
            "aspect_ratio": "2:3",
        },
        "scene": {"location": "待合室", "location_en": "waiting room"},
        "manga": {"panel_layout": "1 panel", "text_policy": "no text"},
        "render_instruction": {"task": "draw one manga page"},
        "character_ids": [character.character_id],
        "character_snapshots": [
            {
                "character_id": character.character_id,
                "name_en": character.name_en,
                "selected_variant_id": variant_id,
                "appearance_summary": "late teens",
                "costume_summary": resolved.costume_summary,
                "visual_natural": resolved.natural,
                "fixed_tags": resolved.identity_tags,
                "variant_tags": resolved.costume_tags + resolved.state_tags,
                "character_source_sha256": digest,
                "character_schema_version": "1.1",
            }
        ],
        "panels": [
            {
                "panel_id": 1,
                "summary": "会話",
                "summary_en": "talking",
                "subjects": [
                    {
                        "character_id": character.character_id,
                        "variant_id": variant_id,
                        "description": "standing",
                        "description_en": "standing",
                    }
                ],
            }
        ],
    }


def test_empty_character_map_compile_stops() -> None:
    character = _character_1_1()
    page = _page_for(character, "001_normal")
    with pytest.raises(PageRenderPlanError, match="キャラクター YAML がありません"):
        compile_page_render_plan(
            page,
            source="step1-pages",
            provider="grok_pro",
            existing_prompt="draw",
            negative_prompt="",
            characters={},
        )
    with pytest.raises(PageRenderPlanError, match="キャラクター YAML がありません"):
        compile_page_render_plan(
            page,
            source="step1-pages",
            provider="grok_pro",
            existing_prompt="draw",
            negative_prompt="",
        )


def test_duplicate_snapshot_pair_stops() -> None:
    character = _character_1_1()
    page = _page_for(character, "001_normal")
    page["character_snapshots"].append(copy.deepcopy(page["character_snapshots"][0]))
    with pytest.raises(Exception, match="重複"):
        MangaPagePrompt.model_validate(page)
    with pytest.raises(PageRenderPlanError, match="重複"):
        compile_page_render_plan(
            page,
            source="step1-pages",
            provider="grok_pro",
            existing_prompt="draw",
            negative_prompt="",
            characters={character.character_id: character.model_dump(mode="json")},
        )


def test_omitted_map_empty_snapshot_stops_on_1_1_path() -> None:
    character = _character_1_1()
    page = _page_for(character, "001_normal")
    page["character_snapshots"][0] = {
        "character_id": character.character_id,
        "name_en": character.name_en,
        "selected_variant_id": "001_normal",
        "character_schema_version": "1.1",
    }
    with pytest.raises(PageRenderPlanError, match="キャラクター YAML がありません"):
        compile_page_render_plan(
            page,
            source="step1-pages",
            provider="grok_pro",
            existing_prompt="draw",
            negative_prompt="",
        )


def test_1_1_snapshot_without_hash_and_natural_stops() -> None:
    character = _character_1_1()
    page = _page_for(character, "001_normal")
    page["character_snapshots"][0]["character_source_sha256"] = ""
    page["character_snapshots"][0]["visual_natural"] = ""
    with pytest.raises(PageRenderPlanError, match="embed_snapshots"):
        compile_page_render_plan(
            page,
            source="step1-pages",
            provider="grok_pro",
            existing_prompt="draw",
            negative_prompt="",
            characters={character.character_id: character.model_dump(mode="json")},
        )
    character = _character_1_1()
    page = _page_for(character, "001_normal")
    page["character_snapshots"][0]["variant_tags"] = ["casual_jacket"]
    with pytest.raises(PageRenderPlanError, match="snapshot が visual resolver"):
        compile_page_render_plan(
            page,
            source="step1-pages",
            provider="grok_pro",
            existing_prompt="draw",
            negative_prompt="",
            characters={character.character_id: character.model_dump(mode="json")},
        )


def test_combines_with_on_base_and_costume_stops() -> None:
    raw = _character_1_1().model_dump(mode="json")
    raw["prompt_variants"][0]["combines_with"] = "006_nude"
    with pytest.raises(Exception, match="combines_with"):
        CharacterPrompt.model_validate(raw)
    raw = _character_1_1().model_dump(mode="json")
    raw["prompt_variants"][1]["combines_with"] = "006_nude"
    with pytest.raises(Exception, match="combines_with"):
        CharacterPrompt.model_validate(raw)


def test_empty_visual_spec_field_stops() -> None:
    raw = _character_1_1().model_dump(mode="json")
    raw["prompt_variants"][1]["visual_spec"]["outer"]["type"] = "  "
    with pytest.raises(Exception, match="空"):
        CharacterPrompt.model_validate(raw)


def test_embed_and_export_hash_validated_model() -> None:
    from novel_prompt_ir_embed_snapshots import build_snapshot

    character = _character_1_1()
    dumped = character.model_dump(mode="json")
    snapshot = build_snapshot(dumped, "001_normal")
    assert snapshot["character_source_sha256"] == character_source_sha256(character)
    assert snapshot["character_schema_version"] == "1.1"
    text = render_character_md(dumped)
    assert "pointed_ears" in text
    assert "smartphone" in text
    character = _character_1_1()
    page = _page_for(character, "001_normal", sha="0" * 64)
    with pytest.raises(PageRenderPlanError, match="sha256"):
        compile_page_render_plan(
            page,
            source="step1-pages",
            provider="grok_pro",
            existing_prompt="draw",
            negative_prompt="",
            characters={character.character_id: character.model_dump(mode="json")},
        )


def test_snapshot_variant_mismatch_stops() -> None:
    character = _character_1_1()
    page = _page_for(character, "001_normal")
    page["character_snapshots"][0]["selected_variant_id"] = "000_base"
    with pytest.raises(PageRenderPlanError, match="一致しません"):
        compile_page_render_plan(
            page,
            source="step1-pages",
            provider="grok_pro",
            existing_prompt="draw",
            negative_prompt="",
            characters={character.character_id: character.model_dump(mode="json")},
        )


def test_alias_mismatch_stops() -> None:
    with pytest.raises(Exception, match="食い違"):
        MangaPagePrompt.model_validate(
            {
                "schema_version": "1.0",
                "meta": {"intent": "manga_page"},
                "scene": {"location_en": "room"},
                "manga": {"panel_layout": "1", "text_policy": "no text"},
                "render_instruction": {"task": "draw"},
                "panels": [
                    {
                        "panel_id": 1,
                        "summary": "x",
                        "subjects": [
                            {
                                "character_id": "kazuki",
                                "variant_id": "001_normal",
                                "prompt_variant_id": "002_jacket_open",
                                "description": "a",
                            }
                        ],
                    }
                ],
            }
        )


def test_natural_and_tags_share_costume_and_omit_ids() -> None:
    character = _character_1_1()
    resolved = resolve_character_visual(character, "001_normal")
    line = character_line(
        {
            "name_en": "Kazuki",
            "character_id": "kazuki",
            "appearance_summary": "late teens",
            "visual_natural": resolved.natural,
            "variant_tags": resolved.costume_tags,
            "fixed_tags": resolved.identity_tags,
            "character_source_sha256": character_source_sha256(character),
        }
    )
    assert "harrington jacket" in resolved.natural
    assert "no hood" in resolved.natural
    assert "navy_harrington_jacket" in resolved.danbooru_tags
    assert "kazuki" not in resolved.natural
    assert "001_normal" not in resolved.natural
    assert "navy_harrington_jacket" in line
    assert "no_hood" in line or "no hood" in line


def test_twelve_tag_limit_does_not_drop_costume() -> None:
    resolved = resolve_character_visual(_character_1_1(), "001_normal")
    identity = [f"id_{index}" for index in range(12)]
    line = character_line(
        {
            "name_en": "Kazuki",
            "visual_natural": resolved.natural,
            "fixed_tags": identity,
            "variant_tags": resolved.costume_tags,
            "character_source_sha256": "abc",
        }
    )
    assert "navy_harrington_jacket" in line
    assert "fold_down_collar" in line


def test_markdown_export_keeps_costume() -> None:
    text = render_character_md(_character_1_1().model_dump(mode="json"))
    assert "navy_harrington_jacket" in text
    assert "no_hood" in text
    assert "harrington jacket" in text.lower() or "navy harrington" in text.lower()
