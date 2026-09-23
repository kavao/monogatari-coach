from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest
import yaml
from PIL import Image

_TOOLS_ROOT = Path(__file__).resolve().parents[2]
if str(_TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(_TOOLS_ROOT))

from manga_prompt_ir.bubble_frame_render import render_local_bubble_frames  # noqa: E402
from manga_prompt_ir.bubble_geometry import BubbleGeometryError  # noqa: E402
from manga_prompt_ir.page_edit import sha256_file  # noqa: E402

_PAGES = _TOOLS_ROOT / "manga_prompt_ir" / "examples" / "p4_compare" / "manga" / "pages"
_IMAGE_SIZE = (832, 1216)
_BG = (18, 42, 90)


def _page() -> dict:
    return yaml.safe_load((_PAGES / "manga_01_p01.yaml").read_text(encoding="utf-8"))


def _bubbles() -> dict:
    return yaml.safe_load((_PAGES / "manga_01_p01.bubbles.yaml").read_text(encoding="utf-8"))


def _clean_png(path: Path) -> tuple[Path, dict]:
    Image.new("RGB", _IMAGE_SIZE, _BG).save(path)
    record = {
        "bubble_frame_mode": "local",
        "text_mode": "none",
        "bubbles_suppressed": True,
        "source_sha256": sha256_file(path),
    }
    return path, record


def _center(rect_px: list[int]) -> tuple[int, int]:
    return ((rect_px[0] + rect_px[2]) // 2, (rect_px[1] + rect_px[3]) // 2)


def test_p4_renders_four_speech_frames_without_overwrite(tmp_path: Path) -> None:
    source, record = _clean_png(tmp_path / "clean.png")
    before = sha256_file(source)
    out = tmp_path / "framed.png"
    result = render_local_bubble_frames(
        _page(),
        _bubbles(),
        image_path=source,
        out_path=out,
        source_generation=record,
    )
    assert result["complete"] is True
    assert result["frame_count"] == 4
    assert [item["text_id"] for item in result["bubbles"]] == [
        "p10-dialogue-01",
        "p20-dialogue-01",
        "p30-dialogue-01",
        "p40-dialogue-01",
    ]
    assert sha256_file(source) == before
    assert result["source_sha256"] == before
    assert result["output_sha256"] == sha256_file(out)
    assert result["output_sha256"] != before
    with Image.open(out) as framed:
        assert framed.size == _IMAGE_SIZE
        assert framed.getpixel((2, 2)) == _BG
        for item in result["bubbles"]:
            assert framed.getpixel(_center(item["frame_rect_px"])) == (255, 255, 255)


def test_narration_uses_rounded_rect(tmp_path: Path) -> None:
    page = _page()
    page["panels"][0]["text"]["narration"] = [
        {"text_id": "p10-narration-01", "content": "地の文"}
    ]
    sidecar = _bubbles()
    sidecar["bubbles"].insert(
        1,
        {
            "text_id": "p10-narration-01",
            "panel_id": 10,
            "bubble_type": "narration",
            "frame_rect": {"x": 0.08, "y": 0.05, "width": 0.22, "height": 0.10},
            "text_rect": {"x": 0.10, "y": 0.06, "width": 0.18, "height": 0.08},
        },
    )
    source, record = _clean_png(tmp_path / "clean.png")
    result = render_local_bubble_frames(
        page,
        sidecar,
        image_path=source,
        out_path=tmp_path / "framed.png",
        source_generation=record,
    )
    assert result["frame_count"] == 5
    narration = next(item for item in result["bubbles"] if item["bubble_type"] == "narration")
    with Image.open(tmp_path / "framed.png") as framed:
        assert framed.getpixel(_center(narration["frame_rect_px"])) == (255, 255, 255)
        left, top, right, bottom = narration["frame_rect_px"]
        assert framed.getpixel((left, top)) == _BG


def test_render_refuses_overwrite_and_hash_mismatch(tmp_path: Path) -> None:
    source, record = _clean_png(tmp_path / "clean.png")
    with pytest.raises(BubbleGeometryError, match="上書き"):
        render_local_bubble_frames(
            _page(),
            _bubbles(),
            image_path=source,
            out_path=source,
            source_generation=record,
        )
    wrong = copy.deepcopy(record)
    wrong["source_sha256"] = "0" * 64
    with pytest.raises(BubbleGeometryError, match="一致しません"):
        render_local_bubble_frames(
            _page(),
            _bubbles(),
            image_path=source,
            out_path=tmp_path / "framed.png",
            source_generation=wrong,
        )


def test_render_rejects_jpeg_input_and_output(tmp_path: Path) -> None:
    jpeg = tmp_path / "clean.jpg"
    Image.new("RGB", _IMAGE_SIZE, _BG).save(jpeg, format="JPEG")
    png, record = _clean_png(tmp_path / "clean.png")
    with pytest.raises(BubbleGeometryError, match="PNG"):
        render_local_bubble_frames(
            _page(),
            _bubbles(),
            image_path=jpeg,
            out_path=tmp_path / "framed.png",
            source_generation=record,
        )
    with pytest.raises(BubbleGeometryError, match="PNG"):
        render_local_bubble_frames(
            _page(),
            _bubbles(),
            image_path=png,
            out_path=tmp_path / "framed.jpg",
            source_generation=record,
        )
    from io import BytesIO

    disguised = tmp_path / "clean.png"
    buffer = BytesIO()
    Image.new("RGB", _IMAGE_SIZE, _BG).save(buffer, format="JPEG")
    disguised.write_bytes(buffer.getvalue())
    bad_record = {
        "bubble_frame_mode": "local",
        "text_mode": "none",
        "bubbles_suppressed": True,
        "source_sha256": sha256_file(disguised),
    }
    with pytest.raises(BubbleGeometryError, match="PNG"):
        render_local_bubble_frames(
            _page(),
            _bubbles(),
            image_path=disguised,
            out_path=tmp_path / "framed.png",
            source_generation=bad_record,
        )


def test_cli_render_bubbles(tmp_path: Path) -> None:
    source, record = _clean_png(tmp_path / "clean.png")
    generation = tmp_path / "generation.json"
    generation.write_text(json.dumps(record), encoding="utf-8")
    out = tmp_path / "framed.png"
    result_json = tmp_path / "result.json"
    from novel_manga_lettering import main

    code = main(
        [
            "render-bubbles",
            "--page",
            str(_PAGES / "manga_01_p01.yaml"),
            "--bubbles",
            str(_PAGES / "manga_01_p01.bubbles.yaml"),
            "--generation-json",
            str(generation),
            "--image",
            str(source),
            "--out",
            str(out),
            "--result-json",
            str(result_json),
        ]
    )
    assert code == 0
    payload = json.loads(result_json.read_text(encoding="utf-8"))
    assert payload["frame_count"] == 4
    assert out.is_file()


def test_local_frame_source_record_matches_png_hash(tmp_path: Path) -> None:
    from manga_prompt_ir.local_frame_source import build_local_frame_source_record

    source, _record = _clean_png(tmp_path / "clean.png")
    record = build_local_frame_source_record(
        image_path=source,
        plan={
            "bubble_frame_mode": "local",
            "text_mode": "none",
            "capability_key": "novelai_v5",
            "effective_settings": {"resolved_model": "nai-diffusion-5-full"},
        },
        resolved_model="nai-diffusion-5-full",
    )
    assert record["bubble_frame_mode"] == "local"
    assert record["text_mode"] == "none"
    assert record["bubbles_suppressed"] is True
    assert record["source_sha256"] == sha256_file(source)
