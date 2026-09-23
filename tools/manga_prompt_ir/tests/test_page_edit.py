from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest
import yaml
from PIL import Image

_TOOLS_ROOT = Path(__file__).resolve().parents[2]
if str(_TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(_TOOLS_ROOT))

from manga_prompt_ir.page_edit import (  # noqa: E402
    PageEditError,
    _verticalize_text,
    bind_actual_geometry,
    composite_masked_region,
    composite_panel,
    crop_panel,
    letter_page,
    refuse_region_edit_provider,
    project_design_geometry,
    sha256_file,
)

_PAGES = _TOOLS_ROOT / "manga_prompt_ir" / "examples" / "p4_compare" / "manga" / "pages"


def _page() -> dict:
    return yaml.safe_load((_PAGES / "manga_01_p01.yaml").read_text(encoding="utf-8"))


def _bind_sha(image: Path, geometry: dict) -> dict:
    bound = dict(geometry)
    bound["source_sha256"] = sha256_file(image)
    return bound


def test_design_geometry_is_not_actual() -> None:
    geometry = project_design_geometry(_page(), image_size=(100, 200))
    assert geometry["kind"] == "design_projected"
    assert all(item["kind"] == "design_projected" for item in geometry["panels"])
    assert geometry["panels"][0]["panel_id"] == 10


def test_actual_geometry_rejects_stale_hash(tmp_path: Path) -> None:
    image = tmp_path / "page.png"
    Image.new("RGB", (64, 64), (10, 20, 30)).save(image)
    with pytest.raises(PageEditError, match="再利用"):
        bind_actual_geometry(
            {
                "kind": "actual",
                "source_sha256": "0" * 64,
                "panels": [{"panel_id": 10, "rect_px": [1, 1, 10, 10]}],
            },
            image_path=image,
        )


def test_design_projected_cannot_bind_as_actual(tmp_path: Path) -> None:
    image = tmp_path / "page.png"
    Image.new("RGB", (64, 64), (1, 2, 3)).save(image)
    digest = sha256_file(image)
    with pytest.raises(PageEditError, match="design_projected"):
        bind_actual_geometry(
            {
                "kind": "design_projected",
                "source_sha256": digest,
                "panels": [{"panel_id": 10, "rect_px": [1, 1, 10, 10]}],
            },
            image_path=image,
        )


def test_composite_keeps_pixels_outside_panel(tmp_path: Path) -> None:
    page_image = tmp_path / "page.png"
    Image.new("RGB", (40, 40), (9, 9, 9)).save(page_image)
    geometry = {
        "kind": "actual",
        "panels": [{"panel_id": 10, "rect_px": [5, 5, 15, 15]}],
    }
    crop = crop_panel(page_image, geometry, 10, tmp_path / "panel.png")
    edited = Image.new("RGB", (10, 10), (200, 0, 0))
    edited.save(crop["path"])
    result = composite_panel(
        page_image,
        crop["path"],
        geometry,
        10,
        tmp_path / "composed.png",
    )
    assert result["outside_pixels_unchanged"] is True
    assert result["complete"] is True
    composed = Image.open(result["path"])
    assert composed.getpixel((0, 0)) == (9, 9, 9)
    assert composed.getpixel((6, 6)) == (200, 0, 0)


def test_masked_region_keeps_pixels_outside_mask(tmp_path: Path) -> None:
    page = tmp_path / "page.png"
    Image.new("RGB", (20, 12), (1, 2, 3)).save(page)
    replacement = tmp_path / "replacement.png"
    Image.new("RGB", (20, 12), (9, 9, 9)).save(replacement)
    mask = Image.new("L", (20, 12), 0)
    for x in range(4, 8):
        for y in range(3, 7):
            mask.putpixel((x, y), 255)
    mask_path = tmp_path / "mask.png"
    mask.save(mask_path)
    result = composite_masked_region(
        page,
        replacement,
        mask_path,
        tmp_path / "edited.png",
        source_sha256=sha256_file(page),
    )
    assert result["complete"] is True
    assert result["outside_pixels_unchanged"] is True
    assert result["changed_pixels"] == 16
    edited = Image.open(result["path"])
    assert edited.getpixel((0, 0)) == (1, 2, 3)
    assert edited.getpixel((5, 4)) == (9, 9, 9)


def test_masked_region_rejects_stale_hash(tmp_path: Path) -> None:
    page = tmp_path / "page.png"
    Image.new("RGB", (8, 8), (1, 1, 1)).save(page)
    Image.new("RGB", (8, 8), (2, 2, 2)).save(tmp_path / "replacement.png")
    Image.new("L", (8, 8), 0).save(tmp_path / "mask.png")
    with pytest.raises(PageEditError, match="再利用"):
        composite_masked_region(
            page,
            tmp_path / "replacement.png",
            tmp_path / "mask.png",
            tmp_path / "edited.png",
            source_sha256="0" * 64,
        )


def test_region_edit_provider_is_refused() -> None:
    with pytest.raises(PageEditError, match="未対応"):
        refuse_region_edit_provider("novelai")


def test_lettering_without_font_is_incomplete(tmp_path: Path) -> None:
    image = tmp_path / "page.png"
    Image.new("RGB", (200, 300), (255, 255, 255)).save(image)
    geometry = {
        "kind": "actual",
        "panels": [{"panel_id": 10, "rect_px": [1, 1, 50, 50]}],
        "texts": [{"text_id": "p10-dialogue-01", "rect_px": [10, 10, 80, 80]}],
    }
    with pytest.raises(PageEditError, match="フォント"):
        letter_page(
            _page(),
            image,
            tmp_path / "lettered.png",
            font_path=tmp_path / "missing.ttf",
            geometry=_bind_sha(image, geometry),
        )


def _test_font() -> Path:
    for candidate in (
        Path(r"C:\Windows\Fonts\YuGothR.ttc"),
        Path(r"C:\Windows\Fonts\msgothic.ttc"),
        Path(r"C:\Windows\Fonts\arial.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ):
        if candidate.is_file():
            return candidate
    pytest.skip("写植テスト用フォントがありません")


def test_lettering_rejects_design_projected(tmp_path: Path) -> None:
    image = tmp_path / "page.png"
    Image.new("RGB", (200, 300), (255, 255, 255)).save(image)
    geometry = project_design_geometry(_page(), image_size=(200, 300))
    with pytest.raises(PageEditError, match="design_projected"):
        letter_page(
            _page(),
            image,
            tmp_path / "lettered.png",
            font_path=_test_font(),
            geometry=geometry,
        )


def test_lettering_unplaced_and_overflow_are_incomplete(tmp_path: Path) -> None:
    image = tmp_path / "page.png"
    Image.new("RGB", (200, 300), (255, 255, 255)).save(image)
    geometry = {
        "kind": "actual",
        "panels": [{"panel_id": 10, "rect_px": [1, 1, 50, 50]}],
        "texts": [
            {"text_id": "p10-dialogue-01", "rect_px": [8, 8, 180, 120]},
            {"text_id": "p20-dialogue-01", "rect_px": [8, 80, 20, 92]},
        ],
    }
    result = letter_page(
        _page(),
        image,
        tmp_path / "lettered.png",
        font_path=_test_font(),
        geometry=_bind_sha(image, geometry),
        font_size=28,
    )
    assert result["complete"] is False
    assert "p10-dialogue-01" in {item["text_id"] for item in result["placed"]}
    assert "p20-dialogue-01" in result["overflow"]
    assert "p30-dialogue-01" in result["unplaced"]
    assert "p40-dialogue-01" in result["unplaced"]
    pixels = Image.open(result["path"])
    assert pixels.getpixel((0, 0)) == (255, 255, 255)


def test_lettering_ink_stays_inside_rect(tmp_path: Path) -> None:
    page = yaml.safe_load((_PAGES / "manga_02_p01.yaml").read_text(encoding="utf-8"))
    image = tmp_path / "page.png"
    Image.new("RGB", (400, 500), (255, 255, 255)).save(image)
    rect = [40, 40, 220, 320]
    result = letter_page(
        page,
        image,
        tmp_path / "lettered.png",
        font_path=_test_font(),
        geometry=_bind_sha(
            image,
            {
            "kind": "actual",
            "panels": [{"panel_id": 10, "rect_px": [1, 1, 390, 490]}],
            "texts": [{"text_id": "p10-sfx-01", "rect_px": rect}],
        },
        ),
        font_size=160,
    )
    assert any(item["text_id"] == "p10-sfx-01" for item in result["placed"])
    pixels = Image.open(result["path"])
    left, top, right, bottom = rect
    outside = 0
    inside = 0
    for y in range(pixels.height):
        for x in range(pixels.width):
            if sum(pixels.getpixel((x, y))) >= 750:
                continue
            if left <= x < right and top <= y < bottom:
                inside += 1
            else:
                outside += 1
    assert inside > 0
    assert outside == 0


def test_lettering_size_ratio_scales_fitted_size(tmp_path: Path) -> None:
    page = yaml.safe_load((_PAGES / "manga_02_p01.yaml").read_text(encoding="utf-8"))
    image = tmp_path / "page.png"
    Image.new("RGB", (400, 500), (255, 255, 255)).save(image)
    geometry = {
        "kind": "actual",
        "panels": [{"panel_id": 10, "rect_px": [1, 1, 390, 490]}],
        "texts": [{"text_id": "p10-sfx-01", "rect_px": [40, 40, 220, 320]}],
    }
    full = letter_page(
        page,
        image,
        tmp_path / "full.png",
        font_path=_test_font(),
        geometry=_bind_sha(image, geometry),
        font_size=160,
    )
    reduced = letter_page(
        page,
        image,
        tmp_path / "reduced.png",
        font_path=_test_font(),
        geometry=_bind_sha(image, geometry),
        font_size=160,
        size_ratio=0.7,
    )
    full_size = next(item["font_size"] for item in full["placed"] if item["text_id"] == "p10-sfx-01")
    reduced_size = next(item["font_size"] for item in reduced["placed"] if item["text_id"] == "p10-sfx-01")
    assert reduced_size == max(12, int(round(full_size * 0.7)))


def test_lettering_vertical_scale_stretches_height_only(tmp_path: Path) -> None:
    page = yaml.safe_load((_PAGES / "manga_02_p01.yaml").read_text(encoding="utf-8"))
    image = tmp_path / "page.png"
    Image.new("RGB", (400, 500), (255, 255, 255)).save(image)
    geometry = {
        "kind": "actual",
        "panels": [{"panel_id": 10, "rect_px": [1, 1, 390, 490]}],
        "texts": [{"text_id": "p10-sfx-01", "rect_px": [40, 40, 220, 360]}],
    }
    full = letter_page(
        page,
        image,
        tmp_path / "full.png",
        font_path=_test_font(),
        geometry=_bind_sha(image, geometry),
        font_size=80,
        size_ratio=0.7,
    )
    tall = letter_page(
        page,
        image,
        tmp_path / "tall.png",
        font_path=_test_font(),
        geometry=_bind_sha(image, geometry),
        font_size=80,
        size_ratio=0.7,
        vertical_scale=1.08,
    )
    full_box = next(item["box_px"] for item in full["placed"] if item["text_id"] == "p10-sfx-01")
    tall_box = next(item["box_px"] for item in tall["placed"] if item["text_id"] == "p10-sfx-01")
    full_w = full_box[2] - full_box[0]
    full_h = full_box[3] - full_box[1]
    tall_w = tall_box[2] - tall_box[0]
    tall_h = tall_box[3] - tall_box[1]
    assert tall_w == full_w
    assert tall_h == max(1, int(round(full_h * 1.08)))


def test_lettering_uses_page_style_and_uniform_base_size(tmp_path: Path) -> None:
    page = _page()
    image = tmp_path / "page.png"
    Image.new("RGB", (400, 800), (255, 255, 255)).save(image)
    geometry = {
        "kind": "actual",
        "panels": [{"panel_id": 10, "rect_px": [1, 1, 390, 790]}],
        "texts": [
            {"text_id": "p10-dialogue-01", "rect_px": [20, 20, 180, 220]},
            {"text_id": "p20-dialogue-01", "rect_px": [200, 20, 380, 220]},
            {"text_id": "p30-dialogue-01", "rect_px": [20, 260, 180, 460]},
            {"text_id": "p40-dialogue-01", "rect_px": [200, 260, 380, 460]},
        ],
    }
    result = letter_page(
        page,
        image,
        tmp_path / "lettered.png",
        font_path=_test_font(),
        geometry=_bind_sha(image, geometry),
    )
    assert result["complete"] is True
    assert {item["writing_direction"] for item in result["placed"]} == {"vertical"}
    assert {item["font_size"] for item in result["placed"]} == {30}


def test_vertical_writing_uses_vertical_presentation_forms() -> None:
    assert _verticalize_text("「これ、見て？」…（駅）") == "﹁これ︑見て？﹂︙︵駅︶"


def test_horizontal_writing_keeps_original_punctuation(tmp_path: Path) -> None:
    page = _page()
    page["manga"]["lettering"]["direction"] = "horizontal"
    page["panels"][0]["text"]["dialogue"][0]["content"] = "「これ、見て。」"
    image = tmp_path / "page.png"
    Image.new("RGB", (400, 800), (255, 255, 255)).save(image)
    result = letter_page(
        page,
        image,
        tmp_path / "lettered.png",
        font_path=_test_font(),
        geometry=_bind_sha(
            image,
            {
            "kind": "actual",
            "panels": [{"panel_id": 10, "rect_px": [1, 1, 390, 790]}],
            "texts": [
                {"text_id": "p10-dialogue-01", "rect_px": [20, 20, 180, 220]},
                {"text_id": "p20-dialogue-01", "rect_px": [200, 20, 380, 220]},
                {"text_id": "p30-dialogue-01", "rect_px": [20, 260, 180, 460]},
                {"text_id": "p40-dialogue-01", "rect_px": [200, 260, 380, 460]},
            ],
        },
        ),
    )
    assert result["complete"] is True
    first = next(item for item in result["placed"] if item["text_id"] == "p10-dialogue-01")
    assert first["rendered_content"] == "「これ、見て。」"


def test_bind_actual_geometry_keeps_text_rects(tmp_path: Path) -> None:
    image = tmp_path / "page.png"
    Image.new("RGB", (64, 64), (8, 8, 8)).save(image)
    digest = sha256_file(image)
    bound = bind_actual_geometry(
        {
            "kind": "actual",
            "source_sha256": digest,
            "panels": [{"panel_id": 10, "rect_px": [1, 1, 10, 10]}],
            "texts": [
                {
                    "text_id": "p10-dialogue-01",
                    "panel_id": 10,
                    "rect_px": [2, 2, 9, 9],
                }
            ],
        },
        image_path=image,
    )
    assert bound["kind"] == "actual"
    assert bound["texts"][0]["text_id"] == "p10-dialogue-01"
    assert bound["texts"][0]["rect_px"] == [2, 2, 9, 9]


def test_lettering_rejects_stale_image_hash(tmp_path: Path) -> None:
    image = tmp_path / "page.png"
    other = tmp_path / "other.png"
    Image.new("RGB", (200, 300), (255, 255, 255)).save(image)
    Image.new("RGB", (200, 300), (10, 10, 10)).save(other)
    geometry = _bind_sha(
        other,
        {
            "kind": "actual",
            "panels": [{"panel_id": 10, "rect_px": [1, 1, 50, 50]}],
            "texts": [{"text_id": "p10-dialogue-01", "rect_px": [10, 10, 80, 80]}],
        },
    )
    with pytest.raises(PageEditError, match="再利用"):
        letter_page(
            _page(),
            image,
            tmp_path / "lettered.png",
            font_path=_test_font(),
            geometry=geometry,
        )
