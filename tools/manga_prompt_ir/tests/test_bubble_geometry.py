from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest
import yaml
from PIL import Image

_TOOLS_ROOT = Path(__file__).resolve().parents[2]
if str(_TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(_TOOLS_ROOT))

from manga_prompt_ir.bubble_geometry import (  # noqa: E402
    BubbleGeometryError,
    bind_bubble_actual,
    project_bubble_design,
    validate_bubble_design,
)
from manga_prompt_ir.page_edit import PageEditError, bind_actual_geometry, sha256_file  # noqa: E402
from manga_prompt_ir.page_render_plan import compile_page_render_plan  # noqa: E402

_PAGES = _TOOLS_ROOT / "manga_prompt_ir" / "examples" / "p4_compare" / "manga" / "pages"
_CHARACTERS = _TOOLS_ROOT / "manga_prompt_ir" / "examples" / "p4_compare" / "tag" / "characters"


def _page() -> dict:
    return yaml.safe_load((_PAGES / "manga_01_p01.yaml").read_text(encoding="utf-8"))


def _bubbles() -> dict:
    return yaml.safe_load((_PAGES / "manga_01_p01.bubbles.yaml").read_text(encoding="utf-8"))


def _characters() -> dict:
    out = {}
    for name in ("kazuki.yaml", "yui.yaml"):
        data = yaml.safe_load((_CHARACTERS / name).read_text(encoding="utf-8"))
        out[data["character_id"]] = data
    return out


def _clean_source() -> dict:
    return {
        "bubble_frame_mode": "local",
        "text_mode": "none",
        "bubbles_suppressed": True,
    }


def test_p4_bubble_sidecar_validates_four_dialogue_ids() -> None:
    document = validate_bubble_design(_page(), _bubbles(), source_generation=_clean_source())
    assert [bubble.text_id for bubble in document.bubbles] == [
        "p10-dialogue-01",
        "p20-dialogue-01",
        "p30-dialogue-01",
        "p40-dialogue-01",
    ]


def test_unknown_duplicate_missing_and_panel_mismatch_stop() -> None:
    page = _page()
    extra = _bubbles()
    extra["bubbles"][0]["text_id"] = "p99-missing"
    with pytest.raises(BubbleGeometryError, match="未知"):
        validate_bubble_design(page, extra, source_generation=_clean_source())

    missing = _bubbles()
    missing["bubbles"] = missing["bubbles"][:3]
    with pytest.raises(BubbleGeometryError, match="不足"):
        validate_bubble_design(page, missing, source_generation=_clean_source())

    duplicate = _bubbles()
    duplicate["bubbles"][1]["text_id"] = "p10-dialogue-01"
    with pytest.raises(Exception, match="重複"):
        validate_bubble_design(page, duplicate, source_generation=_clean_source())

    mismatched = _bubbles()
    mismatched["bubbles"][0]["panel_id"] = 40
    with pytest.raises(BubbleGeometryError, match="panel_id"):
        validate_bubble_design(page, mismatched, source_generation=_clean_source())


def test_text_rect_outside_frame_and_overlap_stop() -> None:
    outside = _bubbles()
    outside["bubbles"][0]["text_rect"] = {
        "x": 0.10,
        "y": 0.05,
        "width": 0.20,
        "height": 0.10,
    }
    with pytest.raises(Exception, match="内側"):
        validate_bubble_design(_page(), outside, source_generation=_clean_source())

    overlap = _bubbles()
    overlap["bubbles"][1]["frame_rect"] = copy.deepcopy(overlap["bubbles"][0]["frame_rect"])
    overlap["bubbles"][1]["text_rect"] = copy.deepcopy(overlap["bubbles"][0]["text_rect"])
    with pytest.raises(Exception, match="重なって"):
        validate_bubble_design(_page(), overlap, source_generation=_clean_source())

    overlap["bubbles"][0]["allow_overlap"] = True
    overlap["bubbles"][1]["allow_overlap"] = True
    validate_bubble_design(_page(), overlap, source_generation=_clean_source())


def test_all_text_kinds_use_bubble_design_coordinates() -> None:
    page = _page()
    page["panels"][0]["text"]["monologue"] = [
        {"text_id": "p10-monologue-01", "content": "内心"}
    ]
    page["panels"][1]["text"]["sfx"] = [
        {"text_id": "p20-sfx-01", "content": "ドン"}
    ]
    sidecar = _bubbles()
    sidecar["bubbles"].extend(
        [
            {
                "text_id": "p10-monologue-01",
                "panel_id": 10,
                "bubble_type": "thought",
                "frame_rect": {"x": 0.08, "y": 0.22, "width": 0.22, "height": 0.10},
                "text_rect": {"x": 0.10, "y": 0.24, "width": 0.18, "height": 0.06},
            },
            {
                "text_id": "p20-sfx-01",
                "panel_id": 20,
                "bubble_type": "sfx",
                "frame_rect": {"x": 0.08, "y": 0.56, "width": 0.20, "height": 0.10},
                "text_rect": {"x": 0.10, "y": 0.58, "width": 0.16, "height": 0.06},
            },
        ]
    )
    document = validate_bubble_design(page, sidecar, source_generation=_clean_source())
    assert [bubble.bubble_type for bubble in document.bubbles[-2:]] == ["thought", "sfx"]


def test_dirty_source_still_stops() -> None:

    with pytest.raises(BubbleGeometryError, match="生成記録"):
        validate_bubble_design(_page(), _bubbles())
    with pytest.raises(BubbleGeometryError, match="生成記録"):
        validate_bubble_design(_page(), _bubbles(), source_generation={})
    with pytest.raises(BubbleGeometryError, match="bubbles_suppressed"):
        validate_bubble_design(
            _page(),
            _bubbles(),
            source_generation={"bubble_frame_mode": "local", "text_mode": "none"},
        )
    with pytest.raises(BubbleGeometryError, match="text_mode=none"):
        validate_bubble_design(
            _page(),
            _bubbles(),
            source_generation={"text_mode": "letter_later"},
        )
    with pytest.raises(BubbleGeometryError, match="併用"):
        validate_bubble_design(
            _page(),
            _bubbles(),
            source_generation={
                "bubble_frame_mode": "local",
                "text_mode": "letter_later",
                "bubbles_suppressed": True,
            },
        )


def test_image_requires_matching_source_sha256(tmp_path: Path) -> None:
    image = tmp_path / "clean.png"
    Image.new("RGB", (64, 64), (12, 34, 56)).save(image)
    digest = sha256_file(image)
    other = tmp_path / "other.png"
    Image.new("RGB", (64, 64), (200, 10, 10)).save(other)
    record = {**_clean_source(), "source_sha256": digest}
    validate_bubble_design(_page(), _bubbles(), source_generation=record, image_path=image)
    with pytest.raises(BubbleGeometryError, match="source_sha256"):
        validate_bubble_design(
            _page(),
            _bubbles(),
            source_generation=_clean_source(),
            image_path=image,
        )
    with pytest.raises(BubbleGeometryError, match="一致しません"):
        validate_bubble_design(
            _page(),
            _bubbles(),
            source_generation=record,
            image_path=other,
        )


def test_project_and_bind_keeps_text_inside_frame(tmp_path: Path) -> None:
    page = _page()
    projected = project_bubble_design(
        page, _bubbles(), image_size=(832, 1216), source_generation=_clean_source()
    )
    assert projected["kind"] == "design_projected"
    assert projected["coordinate_space"] == "pixel"
    assert len(projected["bubbles"]) == 4
    for bubble in projected["bubbles"]:
        frame = bubble["frame_rect_px"]
        text = bubble["text_rect_px"]
        assert frame[0] <= text[0] <= text[2] <= frame[2]
        assert frame[1] <= text[1] <= text[3] <= frame[3]

    image = tmp_path / "clean.png"
    Image.new("RGB", (832, 1216), (240, 240, 240)).save(image)
    bound = bind_bubble_actual(projected, image_path=image, page=page)
    assert bound["kind"] == "actual"
    assert bound["source_sha256"] == sha256_file(image)
    assert [item["text_id"] for item in bound["texts"]] == [
        "p10-dialogue-01",
        "p20-dialogue-01",
        "p30-dialogue-01",
        "p40-dialogue-01",
    ]
    with pytest.raises(PageEditError, match="design_projected"):
        bind_actual_geometry(projected, image_path=image, page=page)


def test_bind_bubble_actual_allows_schema_page_without_layout_geometry(tmp_path: Path) -> None:
    page = _page()
    page.pop("layout_geometry", None)
    image = tmp_path / "clean.png"
    Image.new("RGB", (832, 1216), (240, 240, 240)).save(image)
    projected = project_bubble_design(
        page, _bubbles(), image_size=(832, 1216), source_generation=_clean_source()
    )
    bound = bind_bubble_actual(projected, image_path=image, page=page)
    assert bound["kind"] == "actual"
    assert bound["panels"] == []
    assert len(bound["texts"]) == 4


def test_bind_actual_rejects_duplicate_and_unknown_text_id(tmp_path: Path) -> None:
    image = tmp_path / "page.png"
    Image.new("RGB", (64, 64), (8, 8, 8)).save(image)
    digest = sha256_file(image)
    base = {
        "kind": "actual",
        "source_sha256": digest,
        "panels": [{"panel_id": 10, "rect_px": [1, 1, 10, 10]}],
        "texts": [
            {"text_id": "p10-dialogue-01", "panel_id": 10, "rect_px": [2, 2, 9, 9]},
            {"text_id": "p10-dialogue-01", "panel_id": 10, "rect_px": [3, 3, 8, 8]},
        ],
    }
    with pytest.raises(PageEditError, match="重複"):
        bind_actual_geometry(base, image_path=image)
    unknown = copy.deepcopy(base)
    unknown["texts"] = [{"text_id": "not-in-page", "panel_id": 10, "rect_px": [2, 2, 9, 9]}]
    with pytest.raises(PageEditError, match="未知"):
        bind_actual_geometry(unknown, image_path=image, page=_page())


def test_local_frame_does_not_change_letter_later_compile() -> None:
    page = _page()
    later = compile_page_render_plan(
        page,
        source="step1-pages",
        provider="novelai",
        existing_prompt="Page A comparison fixture",
        negative_prompt="",
        text_mode="letter_later",
        characters=_characters(),
    )
    assert later.text_mode == "letter_later"
    assert "exactly 1 empty speech bubble" in later.prompt
    assert "白い吹き出し" in "\n".join(slot["prompt"] for slot in later.character_slots)
