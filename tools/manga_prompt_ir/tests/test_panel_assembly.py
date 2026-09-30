from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest
import yaml
from PIL import Image

_TOOLS_ROOT = Path(__file__).resolve().parents[2]
if str(_TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(_TOOLS_ROOT))

from manga_prompt_ir.panel_assembly import (  # noqa: E402
    PanelAssemblyError,
    PanelInput,
    cover_placement,
    write_assembly,
)

_EXAMPLES = _TOOLS_ROOT / "manga_prompt_ir" / "examples"


# ── 配置の計算（psd-tools 不要）──────────────────────────


@pytest.mark.parametrize(
    "source, frame",
    [
        ((1024, 1024), (10, 20, 310, 820)),  # 縦長の枠に正方形
        ((1024, 1024), (0, 0, 900, 300)),  # 横長の枠に正方形
        ((832, 1216), (5, 5, 505, 405)),  # 縦長の画像を横長の枠へ
        ((1216, 832), (5, 5, 205, 605)),  # 横長の画像を縦長の枠へ
    ],
)
def test_cover_placement_fills_frame_keeps_aspect_and_centers(source, frame) -> None:
    place = cover_placement(source, frame)
    left, top, right, bottom = frame
    # 枠を隙間なく埋める（白が出ない）
    assert place.left <= left and place.top <= top
    assert place.left + place.width >= right and place.top + place.height >= bottom
    # 縦横のどちらかは枠にぴったり
    assert place.width == right - left or place.height == bottom - top
    # 縦横比を保つ（丸めの誤差のみ）
    assert abs(place.width / place.height - source[0] / source[1]) < 0.01
    # 中央合わせ
    assert abs((place.left + place.width / 2) - (left + right) / 2) <= 1
    assert abs((place.top + place.height / 2) - (top + bottom) / 2) <= 1


def test_cover_placement_rejects_empty_frame() -> None:
    with pytest.raises(PanelAssemblyError):
        cover_placement((100, 100), (10, 10, 10, 50))


# ── PSD の書き出し（psd-tools が要る）────────────────────


def _panel_image(path: Path, size: tuple[int, int], color: tuple[int, int, int]) -> Path:
    image = Image.new("RGB", size, color)
    # 位置の取り違えを見分けるため、左上だけ色を変える
    image.paste((0, 0, 255), (0, 0, size[0] // 4, size[1] // 4))
    image.save(path)
    return path


def test_write_assembly_structure_locks_and_png_match(tmp_path: Path) -> None:
    psd_tools = pytest.importorskip("psd_tools")
    import numpy as np

    canvas = (400, 600)
    panels = [
        PanelInput(_panel_image(tmp_path / "a.png", (256, 256), (200, 30, 30)), (210, 20, 380, 580), "コマ 1"),
        PanelInput(_panel_image(tmp_path / "b.png", (256, 256), (30, 200, 30)), (20, 20, 190, 290), "コマ 2"),
    ]
    result = write_assembly(
        canvas,
        panels,
        psd_path=tmp_path / "out" / "p.psd",
        png_path=tmp_path / "out" / "p.png",
        frame_width=4,
        name_reference=Image.new("RGB", canvas, (255, 255, 255)),
    )
    assert result.psd_path.is_file() and result.png_path.is_file()
    assert not list((tmp_path / "out").glob("*.tmp"))

    psd = psd_tools.PSDImage.open(result.psd_path)
    top = [(layer.name, layer.kind) for layer in psd]
    assert top == [
        ("背景", "pixel"),
        ("コマ 1", "group"),
        ("コマ 2", "group"),
        ("枠線", "pixel"),
        ("ネーム（参考）", "pixel"),
    ]
    locks = {layer.name: int(layer.locks or 0) for layer in psd.descendants()}
    for name in ("背景", "コマ 1の枠（土台）", "コマ 2の枠（土台）", "枠線", "ネーム（参考）"):
        assert locks[name], name
    for name in ("コマ 1", "コマ 2", "コマ 1の画像", "コマ 2の画像"):
        assert not locks[name], name
    for layer in psd.descendants():
        # 余計なマスクが付かない（RGBA モードで作っているため）
        assert not layer.has_mask(), layer.name
    group = [layer for layer in psd if layer.name == "コマ 1"][0]
    base, image = list(group)
    assert not base.clipping and image.clipping
    # コマ画像は切られずにまるごと残る（枠 170×560 に正方形 → 560×560）
    assert image.width == 560 and image.height == 560
    assert [layer for layer in psd if layer.name == "ネーム（参考）"][0].visible is False

    composite = np.asarray(psd.composite().convert("RGB"), dtype=int)
    flat = np.asarray(Image.open(result.png_path).convert("RGB"), dtype=int)
    assert np.abs(composite - flat).max() == 0


def test_write_assembly_rejects_frame_outside_canvas(tmp_path: Path) -> None:
    pytest.importorskip("psd_tools")
    panel = PanelInput(_panel_image(tmp_path / "a.png", (64, 64), (1, 2, 3)), (0, 0, 500, 100), "コマ 1")
    with pytest.raises(PanelAssemblyError, match="キャンバスの外"):
        write_assembly(
            (400, 600), [panel], psd_path=tmp_path / "p.psd", png_path=tmp_path / "p.png", frame_width=4
        )
    assert not (tmp_path / "p.psd").exists()


# ── CLI（つなぎの層）──────────────────────────────────


def _novel(tmp_path: Path, *, candidates: int = 1, geometry: bool = True) -> Path:
    novel = tmp_path / "novel"
    pages = novel / "manga" / "pages"
    pages.mkdir(parents=True)
    data = yaml.safe_load((_EXAMPLES / "manga_page.yaml").read_text(encoding="utf-8"))
    if not geometry:
        data.pop("layout_geometry")
        data["manga"].pop("layout_template_id", None)
    (pages / "manga_01_p01.yaml").write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    comic = novel / "manga" / "_assets" / "manga_01" / "comic"
    comic.mkdir(parents=True)
    for koma in range(1, len(data["panels"]) + 1):
        for n in range(candidates):
            _panel_image(comic / f"manga_01_p01_k{koma:02d}_2026093{n}_000000_{koma}.png", (128, 128), (koma * 60, 90, 90))
    return novel


def _cli(argv: list[str]) -> int:
    from novel_manga_assemble_psd import main

    return main(argv)


def test_cli_dry_run_writes_nothing(tmp_path: Path) -> None:
    novel = _novel(tmp_path)
    assert _cli([str(novel)]) == 0
    assert not (novel / "manga" / "_assets" / "manga_01" / "assembled").exists()


def test_cli_apply_writes_psd_png_and_record_then_keeps_existing(tmp_path: Path, capsys) -> None:
    pytest.importorskip("psd_tools")
    novel = _novel(tmp_path)
    out = novel / "manga" / "_assets" / "manga_01" / "assembled"
    assert _cli([str(novel), "--apply", "--dpi", "72"]) == 0
    assert (out / "manga_01_p01_assembled.psd").is_file()
    assert (out / "manga_01_p01_assembled.png").is_file()
    record = json.loads((out / "manga_01_p01_assembly.json").read_text(encoding="utf-8"))
    assert [p["koma"] for p in record["panels"]] == [1, 2, 3]
    assert all(p["image"].startswith("comic/manga_01_p01_k") and len(p["sha256"]) == 64 for p in record["panels"])
    assert record["canvas"]["size"] == [round(182 / 25.4 * 72), round(257 / 25.4 * 72)]

    before = (out / "manga_01_p01_assembled.psd").read_bytes()
    assert _cli([str(novel), "--apply", "--dpi", "72"]) == 0
    assert (out / "manga_01_p01_assembled.psd").read_bytes() == before
    assert "[既存]" in capsys.readouterr().out


def test_cli_uses_recorded_image_and_stops_on_hash_mismatch(tmp_path: Path, capsys) -> None:
    pytest.importorskip("psd_tools")
    novel = _novel(tmp_path, candidates=2)
    assert _cli([str(novel), "--apply", "--dpi", "72"]) == 0
    out = capsys.readouterr().out
    assert "候補が2枚あるので最新を使います" in out

    assets = novel / "manga" / "_assets" / "manga_01"
    record = json.loads((assets / "assembled" / "manga_01_p01_assembly.json").read_text(encoding="utf-8"))
    chosen = assets / record["panels"][0]["image"]
    _panel_image(chosen, (128, 128), (1, 1, 1))  # 採用画像の中身をすり替える
    assert _cli([str(novel), "--apply", "--overwrite", "--dpi", "72"]) == 1
    assert "中身が記録と違います" in capsys.readouterr().out


def test_cli_skips_page_without_layout_geometry(tmp_path: Path, capsys) -> None:
    novel = _novel(tmp_path, geometry=False)
    assert _cli([str(novel)]) == 0
    assert "layout_geometry がありません" in capsys.readouterr().out


def test_cli_reports_missing_panel_image(tmp_path: Path, capsys) -> None:
    novel = _novel(tmp_path)
    comic = novel / "manga" / "_assets" / "manga_01" / "comic"
    for path in comic.glob("manga_01_p01_k02_*"):
        path.unlink()
    assert _cli([str(novel)]) == 1
    assert "k02: コマ画像がありません" in capsys.readouterr().out


def test_cli_reselect_picks_latest_instead_of_record(tmp_path: Path, capsys) -> None:
    pytest.importorskip("psd_tools")
    novel = _novel(tmp_path)
    assets = novel / "manga" / "_assets" / "manga_01"
    assert _cli([str(novel), "--apply", "--dpi", "72"]) == 0
    first = json.loads((assets / "assembled" / "manga_01_p01_assembly.json").read_text(encoding="utf-8"))
    # コマ1を作り直した（新しい日時の画像が増えた）
    _panel_image(assets / "comic" / "manga_01_p01_k01_20261001_000000_9.png", (128, 64), (9, 9, 9))
    # 記録を使う既定では、古い画像のまま
    assert _cli([str(novel), "--apply", "--overwrite", "--dpi", "72"]) == 0
    kept = json.loads((assets / "assembled" / "manga_01_p01_assembly.json").read_text(encoding="utf-8"))
    assert kept["panels"][0]["image"] == first["panels"][0]["image"]
    # --reselect で最新に選び直す
    assert _cli([str(novel), "--apply", "--overwrite", "--reselect", "--dpi", "72"]) == 0
    new = json.loads((assets / "assembled" / "manga_01_p01_assembly.json").read_text(encoding="utf-8"))
    assert new["panels"][0]["image"] == "comic/manga_01_p01_k01_20261001_000000_9.png"
    assert new["panels"][0]["source_size"] == [128, 64]


def test_cli_overwrite_moves_previous_version_to_old(tmp_path: Path, capsys) -> None:
    pytest.importorskip("psd_tools")
    novel = _novel(tmp_path)
    out = novel / "manga" / "_assets" / "manga_01" / "assembled"
    assert _cli([str(novel), "--apply", "--dpi", "72"]) == 0
    first_psd = (out / "manga_01_p01_assembled.psd").read_bytes()
    assert _cli([str(novel), "--apply", "--overwrite", "--dpi", "80"]) == 0
    runs = [d for d in (out / "old").iterdir() if d.is_dir()]
    assert len(runs) == 1
    assert (runs[0] / "manga_01_p01_assembled.psd").read_bytes() == first_psd
    assert (runs[0] / "manga_01_p01_assembled.png").is_file()
    assert (runs[0] / "manga_01_p01_assembly.json").is_file()
    assert (out / "manga_01_p01_assembled.psd").read_bytes() != first_psd
    assert "前の版を退避しました" in capsys.readouterr().out


def test_cli_restores_previous_version_when_write_fails(tmp_path: Path, monkeypatch, capsys) -> None:
    pytest.importorskip("psd_tools")
    import novel_manga_assemble_psd as cli

    novel = _novel(tmp_path)
    out = novel / "manga" / "_assets" / "manga_01" / "assembled"
    assert _cli([str(novel), "--apply", "--dpi", "72"]) == 0
    before = (out / "manga_01_p01_assembled.psd").read_bytes()

    def broken(*_args, **_kwargs):
        raise PanelAssemblyError("書き出しの失敗を模す")

    monkeypatch.setattr(cli, "write_assembly", broken)
    assert _cli([str(novel), "--apply", "--overwrite", "--dpi", "72"]) == 1
    assert (out / "manga_01_p01_assembled.psd").read_bytes() == before
    assert (out / "manga_01_p01_assembly.json").is_file()
    assert "前の版はそのまま残しています" in capsys.readouterr().out


# ── 見せる位置（focus）と拡大しすぎの警告 ────────────────


def test_focus_moves_point_toward_frame_center_without_gaps() -> None:
    frame = (100, 100, 400, 200)  # 300x100 の横長の枠
    centered = cover_placement((1000, 1000), frame)
    top_focus = cover_placement((1000, 1000), frame, focus=(0.5, 0.1))
    # 上寄りの点を見せる → 画像が下へずれる（top が大きくなる）
    assert top_focus.top > centered.top
    # それでも枠を埋める（白が出ない）
    assert top_focus.top <= 100 and top_focus.top + top_focus.height >= 200
    # 端を指定しても、枠の外に隙間を作る位置までは動かない
    edge = cover_placement((1000, 1000), frame, focus=(0.5, 0.0))
    assert edge.top == 100


def test_focus_out_of_range_is_rejected() -> None:
    with pytest.raises(PanelAssemblyError, match="focus"):
        cover_placement((100, 100), (0, 0, 50, 50), focus=(1.2, 0.5))


def test_cli_focus_is_applied_recorded_and_reused(tmp_path: Path) -> None:
    pytest.importorskip("psd_tools")
    novel = _novel(tmp_path)
    record_path = novel / "manga" / "_assets" / "manga_01" / "assembled" / "manga_01_p01_assembly.json"
    assert _cli([str(novel), "--apply", "--dpi", "72", "--focus", "manga_01_p01:1=0.5,0.1"]) == 0
    first = json.loads(record_path.read_text(encoding="utf-8"))["panels"][0]
    assert first["focus"] == [0.5, 0.1]
    # 次回は --focus なしでも記録から引き継ぐ
    assert _cli([str(novel), "--apply", "--overwrite", "--dpi", "72"]) == 0
    second = json.loads(record_path.read_text(encoding="utf-8"))["panels"][0]
    assert second["focus"] == [0.5, 0.1]
    assert second["placement"] == first["placement"]


def test_cli_reselect_drops_focus_when_image_changes(tmp_path: Path, capsys) -> None:
    pytest.importorskip("psd_tools")
    novel = _novel(tmp_path)
    assets = novel / "manga" / "_assets" / "manga_01"
    assert _cli([str(novel), "--apply", "--dpi", "72", "--focus", "manga_01_p01:1=0.5,0.1"]) == 0
    _panel_image(assets / "comic" / "manga_01_p01_k01_20261001_000000_9.png", (128, 64), (9, 9, 9))
    capsys.readouterr()
    assert _cli([str(novel), "--apply", "--overwrite", "--reselect", "--dpi", "72"]) == 0
    assert "前の見せる位置（focus）は外しました" in capsys.readouterr().out
    record = json.loads((assets / "assembled" / "manga_01_p01_assembly.json").read_text(encoding="utf-8"))
    assert "focus" not in record["panels"][0]


def test_cli_rejects_bad_focus(tmp_path: Path, capsys) -> None:
    novel = _novel(tmp_path)
    assert _cli([str(novel), "--focus", "manga_01_p01:1=1.5,0.1"]) == 2
    assert "0〜1" in capsys.readouterr().err


def test_cli_warns_when_panel_is_enlarged_too_much(tmp_path: Path, capsys) -> None:
    novel = _novel(tmp_path)  # 128px の画像を 200dpi のキャンバスに置くと大きく拡大される
    assert _cli([str(novel), "--max-scale", "1.5"]) == 0
    out = capsys.readouterr().out
    assert "拡大率" in out and "を超えています" in out


def test_write_assembly_records_dpi_in_psd_and_png(tmp_path: Path) -> None:
    psd_tools = pytest.importorskip("psd_tools")
    from psd_tools.constants import Resource

    panel = PanelInput(_panel_image(tmp_path / "a.png", (64, 64), (1, 2, 3)), (10, 10, 190, 290), "コマ 1")
    result = write_assembly(
        (200, 300), [panel], psd_path=tmp_path / "p.psd", png_path=tmp_path / "p.png", frame_width=2, dpi=200
    )
    info = psd_tools.PSDImage.open(result.psd_path).image_resources.get_data(Resource.RESOLUTION_INFO)
    assert info.horizontal == 200 << 16 and info.vertical == 200 << 16
    assert info.horizontal_unit == 1 and info.vertical_unit == 1
    with Image.open(result.png_path) as png:
        assert tuple(round(v) for v in png.info["dpi"]) == (200, 200)


def test_write_assembly_lettering_groups_per_bubble(tmp_path: Path) -> None:
    psd_tools = pytest.importorskip("psd_tools")
    from manga_prompt_ir.panel_assembly import LetteringItem

    canvas = (200, 300)
    balloon = Image.new("RGBA", canvas, (0, 0, 0, 0))
    balloon.paste((255, 255, 255, 255), (20, 20, 80, 60))
    text = Image.new("RGBA", canvas, (0, 0, 0, 0))
    text.paste((0, 0, 0, 255), (40, 30, 50, 50))
    panel = PanelInput(_panel_image(tmp_path / "a.png", (64, 64), (1, 2, 3)), (10, 10, 190, 290), "コマ 1")
    result = write_assembly(
        canvas,
        [panel],
        psd_path=tmp_path / "p.psd",
        png_path=tmp_path / "p.png",
        frame_width=2,
        lettering=[LetteringItem("フキダシ 1", balloon=balloon, text=text), LetteringItem("効果音 1", text=text)],
    )
    psd = psd_tools.PSDImage.open(result.psd_path)
    group = [layer for layer in psd if layer.name == "写植"][0]
    bubbles = list(group)
    assert [b.name for b in bubbles] == ["フキダシ 1", "効果音 1"]
    # 画像が下、文字が上。写植はロックしない
    assert [c.name for c in bubbles[0]] == ["フキダシ 1の画像", "フキダシ 1の文字"]
    assert [c.name for c in bubbles[1]] == ["効果音 1の文字"]
    assert all(not int(layer.locks or 0) for layer in group.descendants())
    # 透明な外側は切り詰めて置く
    assert bubbles[0][0].bbox == (20, 20, 80, 60)


# ── 写植（CLI）───────────────────────────────────────


_P4 = _TOOLS_ROOT / "manga_prompt_ir" / "examples" / "p4_compare"


def _p4_novel(tmp_path: Path) -> Path:
    novel = tmp_path / "p4"
    shutil.copytree(_P4, novel, ignore=shutil.ignore_patterns("_assets"))
    comic = novel / "manga" / "_assets" / "manga_01" / "comic"
    comic.mkdir(parents=True)
    for koma in range(1, 5):
        _panel_image(comic / f"manga_01_p01_k{koma:02d}_20261001_000000_{koma}.png", (256, 256), (koma * 50, 120, 160))
    return novel


def _require_font() -> None:
    from novel_manga_assemble_psd import resolve_font

    if resolve_font(None) is None:
        pytest.skip("日本語フォントが見つからない環境")


def test_cli_lettering_groups_text_list_and_single_column(tmp_path: Path) -> None:
    psd_tools = pytest.importorskip("psd_tools")
    _require_font()
    novel = _p4_novel(tmp_path)
    assert _cli([str(novel), "--page", "manga/pages/manga_01_p01.yaml", "--apply"]) == 0
    out = novel / "manga" / "_assets" / "manga_01" / "assembled"

    psd = psd_tools.PSDImage.open(out / "manga_01_p01_assembled.psd")
    lettering = [layer for layer in psd if layer.name == "写植"][0]
    groups = list(lettering)
    assert [g.name for g in groups] == ["フキダシ 1", "フキダシ 2", "フキダシ 3", "フキダシ 4"]
    first = list(groups[0])
    assert first[0].name == "フキダシ 1の画像"
    assert first[1].name == "フキダシ 1の文字：これ、見て。"
    # 短い台詞は縦1列に収まる（折り返して1〜2文字があふれない）
    for group in groups:
        text_layer = list(group)[1]
        assert text_layer.width < 80, (group.name, text_layer.bbox)

    listing = (out / "manga_01_p01_lettering.txt").read_text(encoding="utf-8")
    assert "フキダシ 1（コマ 10・台詞・yui）\nこれ、見て。" in listing
    assert listing.index("フキダシ 2") < listing.index("フキダシ 3")
    record = json.loads((out / "manga_01_p01_assembly.json").read_text(encoding="utf-8"))
    assert record["lettering"]["items"] == 4
    assert record["outputs"]["lettering"] == "manga_01_p01_lettering.txt"


def test_cli_without_bubbles_writes_text_list_only(tmp_path: Path) -> None:
    psd_tools = pytest.importorskip("psd_tools")
    novel = _novel(tmp_path)  # manga_page.yaml の例: text_mode generate、.bubbles.yaml なし
    assert _cli([str(novel), "--apply", "--dpi", "72"]) == 0
    out = novel / "manga" / "_assets" / "manga_01" / "assembled"
    assert (out / "manga_01_p01_lettering.txt").is_file()
    psd = psd_tools.PSDImage.open(out / "manga_01_p01_assembled.psd")
    assert "写植" not in [layer.name for layer in psd]


def test_cli_text_mode_none_and_no_lettering_skip_everything(tmp_path: Path) -> None:
    pytest.importorskip("psd_tools")
    novel = _novel(tmp_path)
    page = novel / "manga" / "pages" / "manga_01_p01.yaml"
    data = yaml.safe_load(page.read_text(encoding="utf-8"))
    data["render_instruction"]["text_mode"] = "none"
    data["render_instruction"]["text_policy"] = "No text in the image."
    data["manga"]["text_policy"] = "No text in the image."
    page.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    assert _cli([str(novel), "--apply", "--dpi", "72"]) == 0
    out = novel / "manga" / "_assets" / "manga_01" / "assembled"
    assert not (out / "manga_01_p01_lettering.txt").exists()

    novel2 = _novel(tmp_path / "second")
    assert _cli([str(novel2), "--apply", "--dpi", "72", "--no-lettering"]) == 0
    assert not (novel2 / "manga" / "_assets" / "manga_01" / "assembled" / "manga_01_p01_lettering.txt").exists()


# ── 一式での置き換え（レビュー指摘 1） ─────────────────────


def test_replace_together_restores_everything_when_a_move_fails(tmp_path: Path, monkeypatch) -> None:
    import manga_prompt_ir.panel_assembly as pa

    finals = [tmp_path / name for name in ("a.psd", "a.png", "a.json", "a.txt")]
    for final in finals:
        final.write_text(f"old {final.name}", encoding="utf-8")
    staging = tmp_path / "staging"
    staging.mkdir()
    staged = []
    for final in finals[:3]:
        path = staging / final.name
        path.write_text(f"new {final.name}", encoding="utf-8")
        staged.append(path)
    keep = tmp_path / "old" / "run"
    real_move = shutil.move

    def flaky(src, dst):
        if Path(src).name == "a.json" and Path(src).parent == staging:
            raise OSError("置き換えの失敗を模す")
        return real_move(src, dst)

    monkeypatch.setattr(pa.shutil, "move", flaky)
    with pytest.raises(OSError):
        pa.replace_together([*zip(staged, finals[:3]), (None, finals[3])], keep_dir=keep)
    # 4つとも前の版のまま（新旧が混ざらない）
    assert [f.read_text(encoding="utf-8") for f in finals] == [f"old {f.name}" for f in finals]


def test_replace_together_moves_old_files_including_dropped_ones(tmp_path: Path) -> None:
    from manga_prompt_ir.panel_assembly import replace_together

    final, dropped = tmp_path / "a.psd", tmp_path / "a.txt"
    final.write_text("old", encoding="utf-8")
    dropped.write_text("old list", encoding="utf-8")
    new = tmp_path / "new.psd"
    new.write_text("new", encoding="utf-8")
    keep = tmp_path / "old"
    moves = replace_together([(new, final), (None, dropped)], keep_dir=keep)
    assert final.read_text(encoding="utf-8") == "new" and not dropped.exists()
    assert {backup.name for _orig, backup in moves} == {"a.psd", "a.txt"}
    assert (keep / "a.txt").read_text(encoding="utf-8") == "old list"


def test_cli_keeps_all_four_previous_files_when_commit_fails(tmp_path: Path, monkeypatch, capsys) -> None:
    pytest.importorskip("psd_tools")
    import manga_prompt_ir.panel_assembly as pa

    novel = _novel(tmp_path)
    out = novel / "manga" / "_assets" / "manga_01" / "assembled"
    assert _cli([str(novel), "--apply", "--dpi", "72"]) == 0
    names = ["manga_01_p01_assembled.psd", "manga_01_p01_assembled.png", "manga_01_p01_assembly.json", "manga_01_p01_lettering.txt"]
    before = {name: (out / name).read_bytes() for name in names}
    real_move = shutil.move

    def flaky(src, dst):
        if Path(src).name == "manga_01_p01_assembly.json" and ".staging_" in str(src):
            raise OSError("置き換えの失敗を模す")
        return real_move(src, dst)

    monkeypatch.setattr(pa.shutil, "move", flaky)
    assert _cli([str(novel), "--apply", "--overwrite", "--dpi", "80"]) == 1
    assert {name: (out / name).read_bytes() for name in names} == before
    assert not list(out.glob(".staging_*"))
    assert "前の版はそのまま残しています" in capsys.readouterr().out


# ── 古いフキダシの下書き（レビュー指摘 2） ───────────────────


def _draft(novel: Path) -> None:
    from novel_manga_bubbles_draft import main as draft_main

    assert draft_main([str(novel), "--apply"]) == 0


def _edit_page(novel: Path, edit) -> None:
    page = novel / "manga" / "pages" / "manga_01_p01.yaml"
    data = yaml.safe_load(page.read_text(encoding="utf-8"))
    edit(data)
    page.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _first_dialogue(data: dict) -> dict:
    return next(panel for panel in data["panels"] if (panel.get("text") or {}).get("dialogue"))["text"]["dialogue"][0]


def test_draft_records_source_digest(tmp_path: Path) -> None:
    from manga_prompt_ir.bubble_geometry import bubble_source_digest

    novel = _novel(tmp_path)
    _draft(novel)
    pages = novel / "manga" / "pages"
    sidecar = yaml.safe_load((pages / "manga_01_p01.bubbles.yaml").read_text(encoding="utf-8"))
    page = yaml.safe_load((pages / "manga_01_p01.yaml").read_text(encoding="utf-8"))
    assert sidecar["source"] == {"page": "manga_01_p01.yaml", "page_digest": bubble_source_digest(page)}


def test_digest_ignores_unrelated_fields_but_follows_text_and_frames(tmp_path: Path) -> None:
    from manga_prompt_ir.bubble_geometry import bubble_source_digest

    data = yaml.safe_load((_EXAMPLES / "manga_page.yaml").read_text(encoding="utf-8"))
    base = bubble_source_digest(data)
    data["panels"][0]["summary"] = "別の説明"
    assert bubble_source_digest(data) == base
    _first_dialogue(data)["content"] = "書き換えた台詞"
    changed_text = bubble_source_digest(data)
    assert changed_text != base
    data["layout_geometry"]["panels"][0]["rect"]["h"] = round(data["layout_geometry"]["panels"][0]["rect"]["h"] - 0.01, 4)
    assert bubble_source_digest(data) != changed_text


@pytest.mark.parametrize(
    "edit, message",
    [
        (lambda data: _first_dialogue(data).update(content="書き換えた台詞"), "台詞か枠が変わっています"),
        (
            lambda data: data["layout_geometry"]["panels"][0]["rect"].update(
                h=round(data["layout_geometry"]["panels"][0]["rect"]["h"] - 0.01, 4)
            ),
            "台詞か枠が変わっています",
        ),
        (lambda data: next(p for p in data["panels"] if (p.get("text") or {}).get("dialogue"))["text"]["dialogue"].pop(0), "対応しません"),
    ],
)
def test_cli_stops_on_stale_bubbles(tmp_path: Path, capsys, edit, message) -> None:
    pytest.importorskip("psd_tools")
    novel = _novel(tmp_path)
    _draft(novel)
    _edit_page(novel, edit)
    capsys.readouterr()
    assert _cli([str(novel), "--apply", "--dpi", "72"]) == 1
    output = capsys.readouterr().out
    assert message in output and "--overwrite" in output
    assert not (novel / "manga" / "_assets" / "manga_01" / "assembled" / "manga_01_p01_assembled.psd").exists()


def test_cli_accepts_fresh_draft_and_warns_on_handwritten_design(tmp_path: Path, capsys) -> None:
    pytest.importorskip("psd_tools")
    novel = _novel(tmp_path)
    _draft(novel)
    assert _cli([str(novel), "--apply", "--dpi", "72"]) == 0
    # p4_compare の例は手書きの設計（source なし）。対応だけ確かめ、警告して続ける
    p4 = _p4_novel(tmp_path)
    capsys.readouterr()
    assert _cli([str(p4), "--page", "manga/pages/manga_01_p01.yaml", "--apply", "--dpi", "72"]) == 0
    assert "更新元（source）が無い" in capsys.readouterr().out
