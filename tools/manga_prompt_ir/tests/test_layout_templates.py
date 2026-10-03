from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import pytest
import yaml

_TOOLS_ROOT = Path(__file__).resolve().parents[2]
if str(_TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(_TOOLS_ROOT))

from manga_prompt_ir.layout_templates import (  # noqa: E402
    LayoutTemplateError,
    choose_layout_template,
    load_layout_templates,
    template_fit,
)
from manga_prompt_ir.schemas.manga_page import MangaPagePrompt  # noqa: E402
from novel_manga_layout_apply import main as layout_apply_main  # noqa: E402

_EXAMPLES = _TOOLS_ROOT / "manga_prompt_ir" / "examples"


def _panels(weights: list[int | None], beats: list[str | None] | None = None) -> list[dict]:
    beats = beats or [None] * len(weights)
    return [
        {"panel_id": index, "weight": weight, "beat_type": beat}
        for index, (weight, beat) in enumerate(zip(weights, beats), start=1)
    ]


def test_all_templates_self_validate_and_cover_one_to_five_panels() -> None:
    templates = load_layout_templates()
    counts = Counter(t.panel_count for t in templates.values())
    assert set(counts) == {1, 2, 3, 4, 5}
    assert all(counts[n] >= 2 for n in counts)
    assert 15 <= len(templates) <= 25
    for template in templates.values():
        for slot in template.slots:
            rect = slot.rect
            assert 0 <= rect.x and rect.x + rect.w <= 1
            assert 0 <= rect.y and rect.y + rect.h <= 1


def test_every_template_passes_page_schema() -> None:
    base = yaml.safe_load((_EXAMPLES / "manga_page_5panel.yaml").read_text(encoding="utf-8"))
    for template in load_layout_templates().values():
        page = dict(base)
        page["panels"] = [dict(p) for p in base["panels"][: template.panel_count]]
        page["manga"] = dict(base["manga"], layout_template_id=template.template_id)
        page["layout_geometry"] = {
            "panels": [
                {"panel_id": panel["panel_id"], "rect": slot.rect.model_dump()}
                for panel, slot in zip(page["panels"], template.slots)
            ]
        }
        MangaPagePrompt.model_validate(page)


def test_selection_is_deterministic_for_the_same_seed() -> None:
    panels = _panels([None, None, None, None])
    first = choose_layout_template(panels, seed="s1")
    for _ in range(5):
        assert choose_layout_template(panels, seed="s1").template.template_id == first.template.template_id


def test_equal_weights_spread_across_templates() -> None:
    panels = _panels([None, None, None, None])
    chosen = {choose_layout_template(panels, seed=f"page{i}").template.template_id for i in range(40)}
    assert len(chosen) >= 3


def test_heaviest_panel_gets_the_largest_slot() -> None:
    for weights in ([5, 2, 2], [2, 2, 5], [2, 5, 2]):
        choice = choose_layout_template(_panels(weights), seed="w")
        areas = [slot.area for slot in choice.template.slots]
        assert areas.index(max(areas)) == weights.index(max(weights))
        assert choice.fit == pytest.approx(1.0)


def test_beat_type_default_weight_is_used_when_weight_is_missing() -> None:
    choice = choose_layout_template(
        _panels([None, None, None], ["dialogue", "reaction", "climax"]), seed="b"
    )
    areas = [slot.area for slot in choice.template.slots]
    assert areas.index(max(areas)) == 2


def test_previous_template_is_avoided() -> None:
    panels = _panels([None, None, None])
    for i in range(20):
        first = choose_layout_template(panels, seed=f"p{i}")
        second = choose_layout_template(
            panels, seed=f"p{i}", previous_template_ids=[first.template.template_id]
        )
        assert second.template.template_id != first.template.template_id


def test_geometry_keeps_reading_order() -> None:
    choice = choose_layout_template(_panels([5, 2, 2, 1, 3]), seed="r")
    geometry = choice.layout_geometry([10, 20, 30, 40, 50])
    assert [item["panel_id"] for item in geometry["panels"]] == [10, 20, 30, 40, 50]


def test_unsupported_panel_count_is_rejected() -> None:
    with pytest.raises(LayoutTemplateError, match="6コマ"):
        choose_layout_template(_panels([None] * 6))


def test_template_fit_prefers_matching_order() -> None:
    templates = load_layout_templates()
    top_large = templates["p3_top_large_bottom_pair"]
    assert template_fit(top_large, [5, 2, 2]) > template_fit(top_large, [2, 2, 5])


def _write_page(pages_dir: Path, name: str, *, schema: str = "1.1", keep_geometry: bool = False) -> Path:
    source = "manga_page.yaml" if schema == "1.1" else "manga_page_v1_0.yaml"
    data = yaml.safe_load((_EXAMPLES / source).read_text(encoding="utf-8"))
    if not keep_geometry:
        data.pop("layout_geometry", None)
        data.get("manga", {}).pop("layout_template_id", None)
    path = pages_dir / name
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def test_cli_dry_run_does_not_write(tmp_path: Path) -> None:
    pages = tmp_path / "manga" / "pages"
    pages.mkdir(parents=True)
    path = _write_page(pages, "manga_01_p01.yaml")
    before = path.read_text(encoding="utf-8")

    assert layout_apply_main([str(tmp_path)]) == 0
    assert path.read_text(encoding="utf-8") == before


def test_cli_apply_writes_valid_geometry_and_renders_name(tmp_path: Path) -> None:
    pages = tmp_path / "manga" / "pages"
    pages.mkdir(parents=True)
    path = _write_page(pages, "manga_01_p01.yaml")

    assert layout_apply_main([str(tmp_path), "--apply", "--name-dir", str(tmp_path / "names")]) == 0

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    model = MangaPagePrompt.model_validate(data)
    assert model.manga.layout_template_id in load_layout_templates()
    assert model.layout_geometry is not None
    areas = [p.rect.w * p.rect.h for p in model.layout_geometry.panels]
    assert areas.index(max(areas)) == 0  # 例の panel 1 は weight 5
    assert (tmp_path / "names" / "manga_01_p01_name_numbered.png").is_file()


def test_cli_keeps_existing_geometry_unless_overwrite(tmp_path: Path) -> None:
    pages = tmp_path / "manga" / "pages"
    pages.mkdir(parents=True)
    path = _write_page(pages, "manga_01_p01.yaml", keep_geometry=True)
    before = path.read_text(encoding="utf-8")

    assert layout_apply_main([str(tmp_path), "--apply"]) == 0
    assert path.read_text(encoding="utf-8") == before

    assert layout_apply_main([str(tmp_path), "--apply", "--overwrite"]) == 0
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert data["manga"]["layout_template_id"] in load_layout_templates()


def test_cli_skips_schema_1_0_pages(tmp_path: Path) -> None:
    pages = tmp_path / "manga" / "pages"
    pages.mkdir(parents=True)
    path = _write_page(pages, "manga_01_p01.yaml", schema="1.0")
    before = path.read_text(encoding="utf-8")

    assert layout_apply_main([str(tmp_path), "--apply"]) == 0
    assert path.read_text(encoding="utf-8") == before


def test_cli_avoids_repeating_the_previous_page_template(tmp_path: Path) -> None:
    pages = tmp_path / "manga" / "pages"
    pages.mkdir(parents=True)
    for num in range(1, 4):
        _write_page(pages, f"manga_01_p0{num}.yaml")

    assert layout_apply_main([str(tmp_path), "--apply"]) == 0

    ids = [
        yaml.safe_load((pages / f"manga_01_p0{num}.yaml").read_text(encoding="utf-8"))["manga"][
            "layout_template_id"
        ]
        for num in range(1, 4)
    ]
    assert ids[0] != ids[1] and ids[1] != ids[2]


@pytest.mark.parametrize(
    "weights",
    [[1, 1, 2, 3], [3, 1, 1, 2], [1, 2, 5, 3, 2], [2, 3], [3, 2], [1, 1, 3], [2, 2, 2, 2]],
)
def test_chosen_template_puts_heaviest_panel_in_largest_slot(weights: list[int]) -> None:
    from manga_prompt_ir.layout_templates import heaviest_is_largest, weight_area_inversions

    for seed in range(15):
        choice = choose_layout_template(_panels(weights), seed=f"h{seed}")
        assert not choice.mismatch
        assert heaviest_is_largest(choice.template, choice.panel_weights)
        fewest = min(
            weight_area_inversions(t, choice.panel_weights)
            for t in load_layout_templates().values()
            if t.panel_count == len(weights) and heaviest_is_largest(t, choice.panel_weights)
        )
        assert choice.inversions == fewest


def test_reported_case_heaviest_fourth_panel_is_largest() -> None:
    for seed in range(20):
        choice = choose_layout_template(_panels([1, 1, 2, 3]), seed=f"r{seed}")
        areas = [slot.area for slot in choice.template.slots]
        assert areas[3] >= max(areas) - 0.01


def test_no_template_for_heavy_second_panel_is_mismatch() -> None:
    choice = choose_layout_template(_panels([1, 5, 1, 1, 1]), seed="m")
    assert choice.mismatch


def test_cli_apply_syncs_layout_text_with_template(tmp_path: Path) -> None:
    pages = tmp_path / "manga" / "pages"
    pages.mkdir(parents=True)
    path = _write_page(pages, "manga_01_p01.yaml")

    assert layout_apply_main([str(tmp_path), "--apply"]) == 0

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    template = load_layout_templates()[data["manga"]["layout_template_id"]]
    assert data["manga"]["panel_layout"] == template.panel_layout_ja
    for panel, slot in zip(data["panels"], template.slots):
        assert panel["composition"]["layout"] == slot.layout_ja
        assert panel["composition"]["layout_en"] == slot.layout_en


def test_cli_does_not_apply_mismatched_page_without_flag(tmp_path: Path) -> None:
    pages = tmp_path / "manga" / "pages"
    pages.mkdir(parents=True)
    path = pages / "manga_01_p01.yaml"
    data = yaml.safe_load((_EXAMPLES / "manga_page_5panel.yaml").read_text(encoding="utf-8"))
    data.pop("layout_geometry")
    for panel, weight in zip(data["panels"], [1, 5, 1, 1, 1]):
        panel["weight"] = weight
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    before = path.read_text(encoding="utf-8")

    assert layout_apply_main([str(tmp_path), "--apply"]) == 0
    assert path.read_text(encoding="utf-8") == before

    assert layout_apply_main([str(tmp_path), "--apply", "--allow-mismatch"]) == 0
    assert "layout_template_id" in yaml.safe_load(path.read_text(encoding="utf-8"))["manga"]


def test_cli_page_option_reads_chapter_history(tmp_path: Path) -> None:
    pages = tmp_path / "manga" / "pages"
    pages.mkdir(parents=True)
    p01 = _write_page(pages, "manga_01_p01.yaml")
    p02 = _write_page(pages, "manga_01_p02.yaml")
    p03 = _write_page(pages, "manga_01_p03.yaml")
    assert layout_apply_main([str(tmp_path), "--apply", "--page", "manga/pages/manga_01_p01.yaml"]) == 0
    first = yaml.safe_load(p01.read_text(encoding="utf-8"))["manga"]["layout_template_id"]
    p01_after = p01.read_text(encoding="utf-8")
    p03_before = p03.read_text(encoding="utf-8")

    for seed in range(10):
        assert layout_apply_main(
            [str(tmp_path), "--apply", "--overwrite", "--seed", str(seed), "--page", "manga/pages/manga_01_p02.yaml"]
        ) == 0
        second = yaml.safe_load(p02.read_text(encoding="utf-8"))["manga"]["layout_template_id"]
        assert second != first
    assert p01.read_text(encoding="utf-8") == p01_after
    assert p03.read_text(encoding="utf-8") == p03_before


def test_cli_rejects_page_outside_manga_pages(tmp_path: Path) -> None:
    pages = tmp_path / "manga" / "pages"
    pages.mkdir(parents=True)
    _write_page(pages, "manga_01_p01.yaml")
    stray = _write_page(tmp_path, "manga_01_p09.yaml")
    assert layout_apply_main([str(tmp_path), "--page", str(stray)]) == 1


def test_cli_name_failure_leaves_yaml_unchanged(tmp_path: Path) -> None:
    pages = tmp_path / "manga" / "pages"
    pages.mkdir(parents=True)
    path = _write_page(pages, "manga_01_p01.yaml")
    before = path.read_text(encoding="utf-8")
    blocker = tmp_path / "names"
    blocker.write_text("not a directory", encoding="utf-8")

    assert layout_apply_main([str(tmp_path), "--apply", "--name-dir", str(blocker)]) == 1
    assert path.read_text(encoding="utf-8") == before


def test_cli_name_failure_does_not_enter_chapter_history(tmp_path: Path) -> None:
    pages = tmp_path / "manga" / "pages"
    pages.mkdir(parents=True)
    p01 = _write_page(pages, "manga_01_p01.yaml")
    p02 = _write_page(pages, "manga_01_p02.yaml")
    p01_before = p01.read_text(encoding="utf-8")
    p02_panels = yaml.safe_load(p02.read_text(encoding="utf-8"))["panels"]
    names = tmp_path / "names"
    # p01 のネーム画像の保存先をディレクトリで塞ぎ、p01 だけ失敗させる
    (names / "manga_01_p01_name_numbered.png").mkdir(parents=True)

    for seed in range(8):
        p02.write_text(_write_page(pages, "manga_01_p02.yaml").read_text(encoding="utf-8"), encoding="utf-8")
        code = layout_apply_main(
            [str(tmp_path), "--apply", "--seed", str(seed), "--name-dir", str(names)]
        )
        assert code == 1
        assert p01.read_text(encoding="utf-8") == p01_before
        written = yaml.safe_load(p02.read_text(encoding="utf-8"))["manga"]["layout_template_id"]
        expected = choose_layout_template(
            p02_panels, previous_template_ids=[""], seed=f"{seed}|manga_01_p02.yaml"
        ).template.template_id
        assert written == expected
