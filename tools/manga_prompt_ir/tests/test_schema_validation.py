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
from novel_prompt_ir_validate import (
    _schema_1_1_advisories,
    discover_page_yaml_files,
    quality_warnings_for_page,
)


def test_character_yaml_validates() -> None:
    character = load_model(_EXAMPLES / "character.yaml", CharacterPrompt)
    assert character.character_id == "kazuki"
    assert "black_hair" in character.fixed_prompt_tags()
    assert "1boy" in character.fixed_prompt_tags()


def test_page_discovery_ignores_bubble_sidecars(tmp_path: Path) -> None:
    pages = tmp_path / "manga" / "pages"
    pages.mkdir(parents=True)
    page = pages / "manga_01_p01.yaml"
    sidecar = pages / "manga_01_p01.bubbles.yaml"
    page.write_text("meta: {}\n", encoding="utf-8")
    sidecar.write_text("bubbles: []\n", encoding="utf-8")

    assert discover_page_yaml_files(pages, "manga_") == [page]


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


@pytest.mark.parametrize("name", ["manga_page.yaml", "manga_page_5panel.yaml"])
def test_new_page_examples_are_schema_1_1_complete(name: str) -> None:
    page = load_model(_EXAMPLES / name, MangaPagePrompt)
    assert page.schema_version == "1.1"
    assert page.render_instruction.text_mode is not None
    assert page.layout_geometry is not None
    assert [item.panel_id for item in page.layout_geometry.panels] == [
        panel.panel_id for panel in page.panels
    ]
    assert page.background_concepts


def test_new_page_examples_are_not_all_four_panels() -> None:
    counts = {
        len(load_model(_EXAMPLES / name, MangaPagePrompt).panels)
        for name in ("manga_page.yaml", "manga_page_5panel.yaml")
    }
    assert 4 not in counts
    assert len(counts) == 2


def test_schema_1_0_compat_example_still_validates() -> None:
    page = load_model(_EXAMPLES / "manga_page_v1_0.yaml", MangaPagePrompt)
    assert page.schema_version == "1.0"


def _schema_1_1_page() -> dict:
    # 1.0 の例を 1.1 へ手で書き換える移行フィクスチャ。新規の手本は manga_page.yaml。
    page = yaml.safe_load((_EXAMPLES / "manga_page_v1_0.yaml").read_text(encoding="utf-8"))
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

    assert not any("dramaturgy" in warning for warning in warnings)
    assert any("dramaturgy" in advisory for advisory in advisories)
    assert any("subject_id" in advisory for advisory in advisories)
    assert any("text_id" in advisory for advisory in advisories)
    # 漫画ページの text_mode 欠落は新規ページの完了条件なので、advisory ではなく警告（strict で失敗）。
    assert any("text_mode" in warning for warning in warnings)
    assert not any("text_mode" in advisory for advisory in advisories)


@pytest.mark.parametrize(
    "policy, expected",
    [
        ("文字を描かない", "none"),
        ("日本語の文字を描かない", "none"),
        ("画像内に会話、看板、効果音などの文字を入れない。", "none"),
        ("文字は描画しない", "none"),
        ("No text in the image.", "none"),
        ("文字を入れる", "generate"),
        ("Japanese text must be legible", "generate"),
        ("Lettering later. 空吹き出しで。", "letter_later"),
        # 「文字が崩れる場合は…別処理／後入れ」は保険の一文で、方針ではない
        (
            "text.dialogue、monologue、narration、sfxは吹き出し・独白・ナレーション・効果音として扱い、"
            "日本語文字が崩れる場合は文字要素を別処理できる余白を残す。",
            None,
        ),
        ("dialogue/monologue/narration/sfxを分離。文字崩れ時は別処理余白を残す。", None),
        ("日本語文字は正確な文言で描く。文字が崩れる場合は後入れできる余白を残す。", "generate"),
        # 「日本語」「読める」だけでは方針にしない
        ("日本語のナレーション・効果音。", None),
        ("画像内に会話、テロップ、教材画面の読める文字、効果音を入れない。", "none"),
        ("文字要素は別処理する。", "letter_later"),
        ("日本語の台詞は後載せ。", "letter_later"),
        ("Japanese text must be legible. Lettering later.", "conflict"),
        # 保険の句の後ろに続く明示指示は残す
        ("文字が崩れる場合は別処理できる余白を残すが、台詞は正確な文言で描く。", "generate"),
        ("文字が崩れる場合は余白を残すけど、基本は後載せ。", "letter_later"),
        # no text は単語として一致させる（no texture は別語）
        ("no texture", None),
        ("without textures", None),
    ],
)
def test_text_policy_is_classified_consistently(policy: str, expected: str | None) -> None:
    from manga_prompt_ir.page_render_plan import _policy_class
    from manga_prompt_ir.schemas.manga_page import _raw_text_policy_mode

    assert _policy_class(policy) == expected
    if expected == "conflict":
        with pytest.raises(ValueError, match="衝突"):
            _raw_text_policy_mode(policy)
    else:
        assert _raw_text_policy_mode(policy) == expected


def test_schema_1_1_rejects_none_mode_with_generate_after_fallback_clause() -> None:
    page = _schema_1_1_page()
    page["render_instruction"]["text_mode"] = "none"
    page["render_instruction"]["text_policy"] = (
        "文字が崩れる場合は別処理できる余白を残すが、台詞は正確な文言で描く。"
    )
    page["manga"].pop("text_policy", None)
    with pytest.raises(ValueError, match="text_mode"):
        MangaPagePrompt.model_validate(page)


def test_negative_no_texture_does_not_conflict_with_generate() -> None:
    from manga_prompt_ir.page_render_plan import compile_page_render_plan

    page = yaml.safe_load((_EXAMPLES / "manga_page.yaml").read_text(encoding="utf-8"))
    page["technical"]["negative_tags"].append("no texture")
    plan = compile_page_render_plan(
        page, source="step1-pages", provider="grok_pro", existing_prompt="x", negative_prompt=""
    )
    assert plan.text_mode == "generate"


def test_page_with_fallback_clause_resolves_to_generate() -> None:
    from manga_prompt_ir.page_render_plan import resolve_text_mode

    page = yaml.safe_load((_EXAMPLES / "manga_page_v1_0.yaml").read_text(encoding="utf-8"))
    mode, _policy, _warnings = resolve_text_mode(page)
    assert mode == "generate"


def test_schema_1_1_accepts_japanese_no_text_policy_with_text_mode_none() -> None:
    page = _schema_1_1_page()
    page["render_instruction"]["text_mode"] = "none"
    page["render_instruction"]["text_policy"] = "画像に文字を描かない。台詞はYAMLだけに残す。"
    page["manga"]["text_policy"] = "日本語の文字を描かない"
    model = MangaPagePrompt.model_validate(page)
    assert model.render_instruction.text_mode == "none"


def _quality_warnings(page: dict) -> list[str]:
    model = MangaPagePrompt.model_validate(page)
    warnings, _errors = quality_warnings_for_page(
        Path("schema_1_1.yaml"),
        model,
        {"kazuki": set()},
        validate_color_consistency=lambda *_args, **_kwargs: [],
        color_page_data=page,
        summary_en_quality_issues=lambda *_args, **_kwargs: ([], []),
    )
    return warnings


def test_schema_1_1_manga_page_without_layout_geometry_is_quality_warning() -> None:
    page = _schema_1_1_page()
    page.pop("layout_geometry")
    assert any("layout_geometry" in warning for warning in _quality_warnings(page))


def test_schema_1_1_complete_manga_page_has_no_required_field_warning() -> None:
    warnings = _quality_warnings(_schema_1_1_page())
    assert not any("layout_geometry" in w or "text_mode" in w for w in warnings)


def test_schema_1_1_illustration_keeps_text_mode_as_advisory() -> None:
    page = _schema_1_1_page()
    page["meta"]["intent"] = "illustration"
    page.pop("layout_geometry")
    page["render_instruction"]["text_mode"] = None
    model = MangaPagePrompt.model_validate(page)
    warnings = _quality_warnings(page)
    assert not any("layout_geometry" in w or "text_mode" in w for w in warnings)
    assert any("text_mode" in a for a in _schema_1_1_advisories("schema_1_1.yaml", model))


def test_schema_1_0_manga_page_is_not_asked_for_1_1_fields() -> None:
    page = yaml.safe_load((_EXAMPLES / "manga_page_v1_0.yaml").read_text(encoding="utf-8"))
    warnings = _quality_warnings(page)
    assert not any("layout_geometry" in w or "text_mode" in w for w in warnings)


def _page_with_layout_weights() -> dict:
    page = _schema_1_1_page()
    page["manga"]["layout_template_id"] = "p4_top_wide_mid_pair_bottom_wide"
    weights = [3, 2, 1, 5]
    beats = ["establishing", "dialogue", "reaction", "showcase"]
    sizes = ["medium", "small", "small", "large"]
    for panel, weight, beat, size in zip(page["panels"], weights, beats, sizes):
        panel["weight"] = weight
        panel["beat_type"] = beat
        panel["size_class"] = size
    return page


def test_schema_1_1_accepts_layout_weight_fields() -> None:
    model = MangaPagePrompt.model_validate(_page_with_layout_weights())
    assert model.manga.layout_template_id == "p4_top_wide_mid_pair_bottom_wide"
    assert [panel.weight for panel in model.panels] == [3, 2, 1, 5]
    assert model.panels[3].size_class == "large"
    assert model.panels[3].beat_type == "showcase"
    assert not any("beat_type" in w for w in _quality_warnings(_page_with_layout_weights()))


@pytest.mark.parametrize(
    "mutate",
    [
        lambda page: page["panels"][0].update({"weight": 3}),
        lambda page: page["panels"][0].update({"size_class": "small"}),
        lambda page: page["panels"][0].update({"beat_type": "showcase"}),
        lambda page: page["manga"].update({"layout_template_id": "any"}),
    ],
)
def test_schema_1_0_rejects_layout_weight_fields(mutate) -> None:
    page = yaml.safe_load((_EXAMPLES / "manga_page_v1_0.yaml").read_text(encoding="utf-8"))
    mutate(page)
    with pytest.raises(ValueError, match="schema 1.0"):
        MangaPagePrompt.model_validate(page)


@pytest.mark.parametrize(
    "mutate, expected",
    [
        (lambda page: page["panels"][0].update({"weight": 0}), "greater than or equal"),
        (lambda page: page["panels"][0].update({"weight": 6}), "less than or equal"),
        (lambda page: page["panels"][0].update({"size_class": "huge"}), "size_class"),
        (lambda page: page.pop("layout_geometry"), "layout_template_id"),
    ],
)
def test_schema_1_1_rejects_out_of_range_layout_weight_fields(mutate, expected: str) -> None:
    page = _page_with_layout_weights()
    mutate(page)
    with pytest.raises(ValueError, match=expected):
        MangaPagePrompt.model_validate(page)


def test_unknown_beat_type_is_quality_warning() -> None:
    page = _page_with_layout_weights()
    page["panels"][0]["beat_type"] = "splash_page"
    warnings = _quality_warnings(page)
    assert any("beat_type 'splash_page'" in w for w in warnings)


def test_beat_type_vocab_matches_size_class_literal() -> None:
    from typing import get_args

    from manga_prompt_ir.beat_type import load_beat_type_vocab
    from manga_prompt_ir.schemas.manga_page import Panel

    allowed_sizes = set(get_args(get_args(Panel.model_fields["size_class"].annotation)[0]))
    vocab = load_beat_type_vocab()
    assert set(vocab) == {
        "establishing", "dialogue", "reaction", "action", "showcase", "climax", "transition"
    }
    for item in vocab.values():
        assert 1 <= int(item["default_weight"]) <= 5
        assert item["size_class"] in allowed_sizes


def test_unknown_layout_template_id_is_quality_warning() -> None:
    page = _page_with_layout_weights()
    page["manga"]["layout_template_id"] = "no_such_template"
    assert any("型ライブラリにありません" in w for w in _quality_warnings(page))


def _page_with_applied_template(template_id: str) -> dict:
    from manga_prompt_ir.layout_templates import (
        LayoutChoice,
        apply_layout_choice,
        load_layout_templates,
    )

    page = _page_with_layout_weights()
    template = load_layout_templates()[template_id]
    choice = LayoutChoice(
        template=template, fit=1.0, panel_weights=(), candidates=(), inversions=0, mismatch=False
    )
    return apply_layout_choice(page, choice)


def test_applied_layout_template_has_no_warning() -> None:
    page = _page_with_applied_template("p4_top_wide_mid_pair_bottom_wide")
    warnings = _quality_warnings(page)
    assert not any("layout_template_id" in w or "型の" in w or "型 '" in w for w in warnings)


def test_layout_text_differing_from_template_is_quality_warning() -> None:
    page = _page_with_applied_template("p4_top_wide_mid_pair_bottom_wide")
    page["manga"]["panel_layout"] = "上段大ゴマ・下段2コマ"
    page["panels"][1]["composition"]["layout"] = "下段右の小コマ"
    warnings = _quality_warnings(page)
    assert any("manga.panel_layout が型" in w for w in warnings)
    assert any("panel 2: composition.layout が型" in w for w in warnings)


def test_layout_template_id_panel_count_mismatch_is_quality_warning() -> None:
    page = _page_with_layout_weights()
    page["manga"]["layout_template_id"] = "p3_top_large_bottom_pair"
    assert any("3コマの型" in w for w in _quality_warnings(page))


def test_layout_en_differing_from_template_is_quality_warning() -> None:
    page = _page_with_applied_template("p4_top_wide_mid_pair_bottom_wide")
    page["panels"][1]["composition"]["layout_en"] = "full-width bottom large panel"
    warnings = _quality_warnings(page)
    assert any("panel 2: composition.layout_en が型" in w for w in warnings)


def test_empty_layout_en_is_not_a_template_mismatch() -> None:
    page = _page_with_applied_template("p4_top_wide_mid_pair_bottom_wide")
    page["panels"][1]["composition"].pop("layout_en")
    warnings = _quality_warnings(page)
    assert not any("layout_en" in w for w in warnings)
