"""--panel-aspect frame（コマ単体の生成を枠の比率に寄せる）。計画 20260930_manga-panel-assembly-psd の C9。"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pytest

_TOOLS = Path(__file__).resolve().parents[2]
_ROOT = _TOOLS.parent
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

from manga_prompt_ir.frame_aspect import (  # noqa: E402
    FrameAspectError,
    NovelAISizePolicy,
    choose_novelai_size,
    frame_ratio,
    frame_sizes_for_page,
)

_P4 = _ROOT / "tools" / "manga_prompt_ir" / "examples" / "p4_compare"


def test_frame_ratio_uses_b5_paper() -> None:
    # 正規化で正方形でも、B5（182×257）では縦長になる
    assert frame_ratio({"x": 0, "y": 0, "w": 0.5, "h": 0.5}) == pytest.approx(182 / 257)


@pytest.mark.parametrize(
    "ratio, expected",
    [(0.38, (832, 1216)), (0.61, (832, 1216)), (1.1, (1024, 1024)), (1.99, (1216, 832)), (3.09, (1216, 832))],
)
def test_presets_choose_closest_ratio(ratio: float, expected: tuple[int, int]) -> None:
    assert choose_novelai_size(ratio, NovelAISizePolicy()) == expected


@pytest.mark.parametrize("ratio", [0.24, 0.38, 0.61, 1.0, 1.46, 2.0, 2.91, 3.09])
def test_pixel_budget_respects_limits_and_tracks_ratio(ratio: float) -> None:
    policy = NovelAISizePolicy(mode="pixel_budget")
    width, height = choose_novelai_size(ratio, policy)
    assert width * height <= 1_048_576
    assert width % 64 == 0 and height % 64 == 0
    assert 512 <= width <= 1728 and 512 <= height <= 1728
    limit = 1728 / 512
    target = min(max(ratio, 1 / limit), limit)
    assert abs(math.log(width / height) - math.log(target)) <= 0.05


def test_pixel_budget_prefers_larger_area_for_nearly_same_ratio() -> None:
    width, height = choose_novelai_size(0.38, NovelAISizePolicy(mode="pixel_budget"))
    assert (width, height) == (576, 1536)


def test_policy_from_config_validates() -> None:
    cfg = json.loads((_ROOT / "config" / "image_generation.json").read_text(encoding="utf-8"))
    policy = NovelAISizePolicy.from_config(cfg["providers"]["novelai"]["panel_frame_sizes"])
    assert policy.mode == "pixel_budget"  # 2026-10-01 に Anlas 0 を確認して切り替えた
    assert all(w * h <= policy.max_pixels for w, h in policy.presets)
    with pytest.raises(FrameAspectError, match="mode"):
        NovelAISizePolicy.from_config({"mode": "free"})
    with pytest.raises(FrameAspectError, match="上限"):
        NovelAISizePolicy.from_config({"presets": [[1536, 1024]]})


def test_frame_sizes_match_panels_by_panel_id() -> None:
    geometry = [
        {"panel_id": 10, "rect": {"x": 0.04, "y": 0.03, "w": 0.92, "h": 0.28}},
        {"panel_id": 20, "rect": {"x": 0.52, "y": 0.34, "w": 0.44, "h": 0.3}},
    ]
    sizes = frame_sizes_for_page(geometry, [10, 20], NovelAISizePolicy())
    assert [s["panel_id"] for s in sizes] == [10, 20]
    assert sizes[0]["requested_size"] == [1216, 832]
    with pytest.raises(FrameAspectError, match="panel_id=\\[30\\]"):
        frame_sizes_for_page(geometry, [10, 30], NovelAISizePolicy())


# ── バッチ（dry-run。API は呼ばない）──────────────────


def _batch(argv: list[str]) -> int:
    from image_provider_novel_manga_batch import main

    return main(argv)


def _base_args() -> list[str]:
    return [str(_P4), "--manga-stem", "manga_01", "--source", "step1-panels", "--provider", "novelai", "--dry-run"]


def test_batch_dry_run_shows_per_panel_frame_sizes(capsys) -> None:
    assert _batch(_base_args() + ["--panel-aspect", "frame"]) == 0
    out = capsys.readouterr().out
    assert out.count("panel_frame: 枠の比") >= 4
    assert "pixel_budget" in out


def test_batch_without_panel_aspect_is_unchanged(capsys) -> None:
    assert _batch(_base_args()) == 0
    assert "panel_frame" not in capsys.readouterr().out


@pytest.mark.parametrize(
    "extra, message",
    [
        (["--aspect-ratio", "portrait"], "--aspect-ratio とは併用できません"),
        (["--size", "1024x1024"], "--size"),
    ],
)
def test_batch_rejects_conflicting_options(extra: list[str], message: str, capsys) -> None:
    assert _batch(_base_args() + ["--panel-aspect", "frame"] + extra) == 2
    assert message in capsys.readouterr().err


def test_batch_rejects_non_novelai_and_page_sources(capsys) -> None:
    args = [str(_P4), "--manga-stem", "manga_01", "--source", "step1-panels", "--provider", "grok", "--dry-run"]
    assert _batch(args + ["--panel-aspect", "frame"]) == 2
    assert "provider=novelai 専用" in capsys.readouterr().err
    args = [str(_P4), "--manga-stem", "manga_01", "--source", "step1-pages", "--provider", "novelai", "--dry-run"]
    assert _batch(args + ["--panel-aspect", "frame"]) == 2
    assert "step1-panels 専用" in capsys.readouterr().err


def test_batch_stops_on_page_without_layout_geometry(tmp_path: Path, capsys) -> None:
    import shutil

    import yaml

    novel = tmp_path / "novel"
    shutil.copytree(_P4, novel, ignore=shutil.ignore_patterns("_assets"))
    for page in (novel / "manga" / "pages").glob("manga_01_p*.yaml"):
        data = yaml.safe_load(page.read_text(encoding="utf-8"))
        data.pop("layout_geometry", None)
        data.get("manga", {}).pop("layout_template_id", None)
        page.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    args = [str(novel), "--manga-stem", "manga_01", "--source", "step1-panels", "--provider", "novelai", "--dry-run"]
    assert _batch(args + ["--panel-aspect", "frame"]) == 2
    assert "layout_geometry が要ります" in capsys.readouterr().err


def test_batch_records_requested_and_actual_size_after_generation(tmp_path: Path, monkeypatch, capsys) -> None:
    """生成（子プロセス）を差し替え、要求サイズと実寸が JSON に分けて記録されることを確かめる。"""
    import shutil
    import types

    from PIL import Image

    import image_provider_novel_manga_batch as batch

    novel = tmp_path / "novel"
    shutil.copytree(_P4, novel, ignore=shutil.ignore_patterns("_assets"))
    monkeypatch.setenv("NOVELAI_ACCESS_TOKEN", "dummy")

    sent: list[tuple[str, object, object]] = []

    def fake_run(cmd, **kwargs):
        params = json.loads(Path(cmd[cmd.index("--params") + 1]).read_text(encoding="utf-8"))
        sent.append((params["file_prefix"], params.get("width"), params.get("height")))
        out_dir = Path(params["output_dir"])
        out_dir.mkdir(parents=True, exist_ok=True)
        png = out_dir / f"{params['file_prefix']}_fake.png"
        # 要求どおりのサイズを返さない provider を模して、わざと 1024x1024 で保存する
        Image.new("RGB", (1024, 1024), (10, 20, 30)).save(png)
        side = out_dir / f"{params['file_prefix']}_fake.json"
        side.write_text(json.dumps({"param_merged": {"width": params.get("width"), "height": params.get("height")}}), encoding="utf-8")
        stdout = json.dumps({"ok": True, "saved": [{"png": str(png), "json": str(side)}]})
        return types.SimpleNamespace(returncode=0, stdout=stdout, stderr="")

    monkeypatch.setattr(batch.subprocess, "run", fake_run)
    code = batch.main(
        [str(novel), "--manga-stem", "manga_01", "--source", "step1-panels", "--provider", "novelai",
         "--panel-aspect", "frame"]
    )
    assert code == 0
    # コマごとの幅・高さが、生成ツールへ渡るペイロードに載っている
    # 設定（既定 pixel_budget）で決まった幅・高さがペイロードに載る
    assert all(isinstance(w, int) and isinstance(h, int) and w * h <= 1_048_576 for _p, w, h in sent)
    assert len(sent) >= 4
    sides = sorted((novel / "manga" / "_assets" / "manga_01" / "comic").glob("manga_01_p01_k01_fake.json"))
    assert sides, "生成結果の JSON がありません"
    record = json.loads(sides[0].read_text(encoding="utf-8"))["panel_frame"]
    k01 = [item for item in sent if item[0] == "manga_01_p01_k01"][0]
    assert record["requested_size"] == [k01[1], k01[2]]
    assert record["actual_size"] == [1024, 1024]
    assert f"要求 {record['requested_size']} と実寸 [1024, 1024] が違います" in capsys.readouterr().err


def test_pixel_budget_does_not_shrink_when_an_exact_small_size_exists() -> None:
    # 比率ぴったりの小さいサイズ（704x832）があっても、3% 以内で画素数の大きい方を選ぶ
    assert choose_novelai_size(0.8434, NovelAISizePolicy(mode="pixel_budget")) == (896, 1088)


@pytest.mark.parametrize("ratio", [0.34, 0.61, 0.84, 1.08, 1.42, 1.76, 2.47, 3.09])
def test_pixel_budget_keeps_area_near_budget(ratio: float) -> None:
    width, height = choose_novelai_size(ratio, NovelAISizePolicy(mode="pixel_budget"))
    assert width * height >= 880_000
