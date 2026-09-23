from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

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
from manga_prompt_ir.schemas.manga_page import Camera, MangaPagePrompt

from image_provider_novel_manga_batch import filter_single_panel_tags
from novel_prompt_ir_validate import _schema_1_1_advisories, quality_warnings_for_page


def test_character_yaml_validates() -> None:
    character = load_model(_EXAMPLES / "character.yaml", CharacterPrompt)
    assert character.character_id == "kazuki"
    assert "black_hair" in character.fixed_prompt_tags()
    assert "1boy" in character.fixed_prompt_tags()


def test_manga_page_yaml_validates_and_renders() -> None:
    page = load_model(_EXAMPLES / "manga_page.yaml", MangaPagePrompt)
    character = load_model(_EXAMPLES / "character.yaml", CharacterPrompt)
    rendered = render_page_prompt(page, {character.character_id: character})
    assert "漫画1ページ分の作画指示" in rendered.prompt
    assert "panel 1" in rendered.prompt
    assert "black_hair" in rendered.tags
    assert "bad_hands" in rendered.negative_tags


def test_camera_view_fields_remain_free_strings() -> None:
    camera = Camera(view="任意の視点メモ", view_en="custom view")
    assert camera.view == "任意の視点メモ"
    assert camera.view_en == "custom view"


def test_illustration_page_yaml_validates() -> None:
    page = load_model(_EXAMPLES / "illustration_page.yaml", MangaPagePrompt)
    assert page.meta.intent == "illustration"
    assert page.meta.illustration_type == "chapter_illustration"
    assert len(page.panels) == 1


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


def _schema_1_1_page() -> dict:
    page = yaml.safe_load((_EXAMPLES / "manga_page.yaml").read_text(encoding="utf-8"))
    page["schema_version"] = "1.1"
    page["render_instruction"]["text_mode"] = "generate"
    page["dramaturgy"] = {
        "purpose": "手紙の発見で次の選択を予告する",
        "purpose_en": "Foreshadow the next choice through the discovered letter.",
        "emotional_arc": "戸惑いから決意へ",
        "emotional_arc_en": "From confusion to resolve.",
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
        {
            "entity_id": "kazuki",
            "panel_id": page["panels"][0]["panel_id"],
            "state": "holding the phone",
        }
    ]
    page["asset_references"] = [
        {"asset_id": "kazuki-001", "role": "character", "character_id": "kazuki"}
    ]
    for panel in page["panels"]:
        for index, subject in enumerate(panel["subjects"], start=1):
            if subject.get("character_id"):
                subject["subject_id"] = f"p{panel['panel_id']}-s{index:02d}"
        text = panel["text"]
        for kind in ("dialogue", "sfx"):
            for index, item in enumerate(text.get(kind, []), start=1):
                item["text_id"] = f"p{panel['panel_id']}-{kind}-{index:02d}"
        for kind in ("monologue", "narration"):
            if text.get(kind):
                item = text[kind][0]
                text[kind][0] = {
                    "text_id": f"p{panel['panel_id']}-{kind}-01",
                    "content": item,
                }
    return page


def test_schema_1_1_reads_new_fields_and_structured_text() -> None:
    page = _schema_1_1_page()
    model = MangaPagePrompt.model_validate(page)

    assert model.schema_version == "1.1"
    assert model.render_instruction.text_mode == "generate"
    assert model.dramaturgy is not None
    assert model.layout_geometry is not None
    assert model.panels[0].subjects[0].subject_id
    assert model.panels[1].text.monologue[0].content
    assert model.panels[1].text.monologue[0].text_id
    rendered = render_page_prompt(model)
    assert any(item.get("text_id") == "p2-monologue-01" for item in rendered.text_elements)


def test_schema_1_0_rejects_schema_1_1_fields() -> None:
    page = _schema_1_1_page()
    page["schema_version"] = "1.0"

    with pytest.raises(ValueError, match="schema 1.0"):
        MangaPagePrompt.model_validate(page)


def test_schema_1_1_requires_english_for_japanese_dramaturgy() -> None:
    page = _schema_1_1_page()
    page["dramaturgy"].pop("purpose_en")

    with pytest.raises(ValueError, match="purpose_en"):
        MangaPagePrompt.model_validate(page)


def test_schema_1_1_rejects_text_mode_policy_conflict() -> None:
    page = _schema_1_1_page()
    page["render_instruction"]["text_mode"] = "none"
    page["render_instruction"]["text_policy"] = "Japanese text must be legible"

    with pytest.raises(ValueError, match="text_mode"):
        MangaPagePrompt.model_validate(page)


@pytest.mark.parametrize(
    "mutate, expected",
    [
        (lambda page: page["layout_geometry"]["panels"][0]["rect"].update({"x": 1.1}), "0〜1"),
        (
            lambda page: page["layout_geometry"]["panels"][1]["rect"].update({"y": 0.0}),
            "重複",
        ),
        (
            lambda page: page["layout_geometry"]["panels"].append(
                {"panel_id": 999, "rect": {"x": 0.0, "y": 0.0, "w": 0.1, "h": 0.1}}
            ),
            "未知のpanel_id",
        ),
        (
            lambda page: page["layout_geometry"]["panels"].reverse(),
            "第二の読み順",
        ),
    ],
)
def test_schema_1_1_rejects_invalid_geometry(mutate, expected: str) -> None:
    page = _schema_1_1_page()
    mutate(page)

    with pytest.raises(ValueError, match=expected):
        MangaPagePrompt.model_validate(page)


def test_schema_1_1_rejects_duplicate_persistent_ids() -> None:
    page = _schema_1_1_page()
    page["panels"][1]["subjects"][0]["subject_id"] = page["panels"][0]["subjects"][0]["subject_id"]

    with pytest.raises(ValueError, match="subject_id"):
        MangaPagePrompt.model_validate(page)


@pytest.mark.parametrize(
    "reference_update, expected",
    [
        ({"character_id": "unknown"}, "character_id"),
        ({"character_id": "kazuki", "variant_id": "unknown"}, "variant_id"),
        ({"variant_id": "unknown"}, "character_id"),
        ({"concept_id": "unknown"}, "concept_id"),
    ],
)
def test_schema_1_1_rejects_unresolved_asset_references(reference_update, expected: str) -> None:
    page = _schema_1_1_page()
    page["asset_references"] = [{"asset_id": "ref-001", "role": "reference", **reference_update}]

    with pytest.raises(ValueError, match=expected):
        MangaPagePrompt.model_validate(page)


def test_schema_1_1_advisories_are_not_quality_warnings() -> None:
    page = _schema_1_1_page()
    page["dramaturgy"] = None
    page["render_instruction"]["text_mode"] = None
    for panel in page["panels"]:
        for subject in panel["subjects"]:
            subject["subject_id"] = None
        for kind in ("dialogue", "sfx"):
            for item in panel["text"].get(kind, []):
                item["text_id"] = None
        for kind in ("monologue", "narration"):
            for item in panel["text"].get(kind, []):
                item["text_id"] = None
    model = MangaPagePrompt.model_validate(page)

    warnings, _errors = quality_warnings_for_page(
        Path("schema_1_1.yaml"),
        model,
        {"kazuki": set()},
        validate_color_consistency=lambda *_args, **_kwargs: [],
        color_page_data=page,
        summary_en_quality_issues=lambda *_args, **_kwargs: ([], []),
    )
    advisories = _schema_1_1_advisories("schema_1_1.yaml", model)

    assert not any("dramaturgy" in warning or "text_mode" in warning for warning in warnings)
    assert any("dramaturgy" in advisory for advisory in advisories)
    assert any("text_mode" in advisory for advisory in advisories)
    assert any("subject_id" in advisory for advisory in advisories)
    assert any("text_id" in advisory for advisory in advisories)
