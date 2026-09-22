from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from image_provider_generate import (  # noqa: E402
    GROK_IMAGINE_2_MODEL,
    build_grok_payload,
    load_root_config,
    merge_provider_defaults,
    overlay_cli_on_params,
    save_grok_response,
)
from image_provider_novel_illustration_batch import build_job_payload  # noqa: E402
from image_provider_novel_manga_batch import main as manga_main  # noqa: E402


def _grok_cfg() -> dict:
    return load_root_config(ROOT / "config" / "image_generation.json")["providers"]["grok"]


def _grok_pro_cfg() -> dict:
    return load_root_config(ROOT / "config" / "image_generation.json")["providers"]["grok_pro"]


def test_aliases_resolve_imagine_2() -> None:
    merged = merge_provider_defaults(
        "grok_pro",
        _grok_pro_cfg(),
        {"prompt": "p", "output_dir": "outputs", "model": "v2"},
    )
    assert merged["model"] == GROK_IMAGINE_2_MODEL
    merged2 = merge_provider_defaults(
        "grok",
        _grok_cfg(),
        {"prompt": "p", "output_dir": "outputs", "model": "imagine2"},
    )
    assert merged2["model"] == GROK_IMAGINE_2_MODEL


def test_grok_defaults_are_imagine_2() -> None:
    for provider, cfg in (
        ("grok", _grok_cfg()),
        ("grok_pro", _grok_pro_cfg()),
    ):
        merged = merge_provider_defaults(
            provider,
            cfg,
            {"prompt": "p", "output_dir": "outputs"},
        )
        assert merged["model"] == GROK_IMAGINE_2_MODEL
        assert "grok_image_quality" not in merged
        assert "quality" not in build_grok_payload(merged)


def test_imagine_2_payload_includes_quality() -> None:
    merged = merge_provider_defaults(
        "grok_pro",
        _grok_pro_cfg(),
        {
            "prompt": "p",
            "output_dir": "outputs",
            "model": "v2",
            "grok_image_quality": "medium",
        },
    )
    payload = build_grok_payload(merged)
    assert payload["model"] == GROK_IMAGINE_2_MODEL
    assert payload["quality"] == "medium"


def test_quality_on_1x_is_rejected() -> None:
    with pytest.raises(ValueError, match="grok-imagine-image-2.0 専用"):
        merge_provider_defaults(
            "grok_pro",
            _grok_pro_cfg(),
            {
                "prompt": "p",
                "output_dir": "outputs",
                "model": "quality",
                "grok_image_quality": "low",
            },
        )


def test_openai_high_quality_is_rejected_for_grok() -> None:
    with pytest.raises(ValueError, match="low / medium / auto"):
        merge_provider_defaults(
            "grok",
            _grok_cfg(),
            {
                "prompt": "p",
                "output_dir": "outputs",
                "model": "v2",
                "grok_image_quality": "high",
            },
        )


def test_cli_overrides_params_json() -> None:
    params = overlay_cli_on_params(
        {"model": "quality", "grok_image_quality": "low"},
        model="v2",
        grok_image_quality="medium",
    )
    assert params["model"] == "v2"
    assert params["grok_image_quality"] == "medium"


def test_save_grok_response_writes_response_model(tmp_path: Path) -> None:
    from PIL import Image

    image = tmp_path / "src.png"
    Image.new("RGB", (8, 8), (9, 9, 9)).save(image)
    import base64

    resp = {
        "model": GROK_IMAGINE_2_MODEL,
        "data": [{"b64_json": base64.b64encode(image.read_bytes()).decode("ascii")}],
    }
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    saved = save_grok_response(
        resp=resp,
        merged={"file_prefix": "t", "prompt": "p"},
        payload={"model": GROK_IMAGINE_2_MODEL},
        provider_cfg={"min_png_bytes": 8},
        out_dir=out_dir,
        timeout=1,
    )
    meta = json.loads(Path(saved[0]["json"]).read_text(encoding="utf-8"))
    assert meta["response_model"] == GROK_IMAGINE_2_MODEL
    assert "response_item" in meta


def test_save_grok_response_keeps_image_when_model_absent(tmp_path: Path) -> None:
    import base64

    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40
    encoded = base64.b64encode(png).decode("ascii")
    saved = save_grok_response(
        resp={"data": [{"b64_json": encoded}], "usage": {"cost_in_usd_ticks": 1}},
        merged={"file_prefix": "t", "prompt": "p"},
        payload={},
        provider_cfg={"min_png_bytes": 1},
        out_dir=tmp_path,
        timeout=1,
    )
    meta = json.loads(Path(saved[0]["json"]).read_text(encoding="utf-8"))
    assert meta["response_model"] is None
    assert Path(saved[0]["png"]).is_file()
    outline = "\n".join(meta["response_key_outline"])
    assert "data[].b64_json:" in outline
    assert "usage.cost_in_usd_ticks:" in outline
    assert encoded not in outline


def test_save_grok_response_reads_model_from_data_item(tmp_path: Path) -> None:
    import base64

    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
    saved = save_grok_response(
        resp={
            "data": [
                {
                    "model": GROK_IMAGINE_2_MODEL,
                    "b64_json": base64.b64encode(png).decode("ascii"),
                }
            ]
        },
        merged={"file_prefix": "t", "prompt": "p"},
        payload={},
        provider_cfg={"min_png_bytes": 1},
        out_dir=tmp_path,
        timeout=1,
    )
    meta = json.loads(Path(saved[0]["json"]).read_text(encoding="utf-8"))
    assert meta["response_model"] == GROK_IMAGINE_2_MODEL
    assert "response_key_outline" not in meta


def test_illustration_payload_keeps_v2_model() -> None:
    payload = build_job_payload(
        "grok_pro",
        {
            "prompt": "p",
            "negative_prompt": "n",
            "prompt_formatter": "natural_sections",
            "negative_mode": "inline",
            "output_dir": "/out",
            "prefix": "illustration_01_p01",
        },
        aspect_ratio="book_cover",
        model="v2",
        resolution="2k",
        novelai_ref_fields={},
        grok_image_quality="low",
    )
    assert payload["model"] == "v2"
    assert payload["grok_image_quality"] == "low"


def test_empty_grok_image_quality_is_rejected() -> None:
    with pytest.raises(ValueError, match="low / medium / auto"):
        merge_provider_defaults(
            "grok",
            _grok_cfg(),
            {
                "prompt": "p",
                "output_dir": "outputs",
                "model": "v2",
                "grok_image_quality": "  ",
            },
        )


def test_non_grok_rejects_grok_image_quality() -> None:
    config = load_root_config(ROOT / "config" / "image_generation.json")
    with pytest.raises(ValueError, match="Grok 専用"):
        merge_provider_defaults(
            "openai",
            config["providers"]["openai"],
            {
                "prompt": "p",
                "output_dir": "outputs",
                "grok_image_quality": "low",
            },
        )


def test_save_grok_response_blank_model_is_absent(tmp_path: Path) -> None:
    import base64

    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
    saved = save_grok_response(
        resp={
            "model": "   ",
            "data": [{"b64_json": base64.b64encode(png).decode("ascii")}],
        },
        merged={"file_prefix": "t", "prompt": "p"},
        payload={},
        provider_cfg={"min_png_bytes": 1},
        out_dir=tmp_path,
        timeout=1,
    )
    meta = json.loads(Path(saved[0]["json"]).read_text(encoding="utf-8"))
    assert meta["response_model"] is None
    assert Path(saved[0]["png"]).is_file()


def test_manga_batch_cli_accepts_model(capsys: pytest.CaptureFixture[str]) -> None:
    code = manga_main(
        [
            str(ROOT / "tools" / "manga_prompt_ir" / "examples" / "p4_compare"),
            "--dry-run",
            "--source",
            "step1-pages",
            "--manga-stem",
            "manga_01",
            "--min-page",
            "1",
            "--max-page",
            "1",
            "--provider",
            "grok_pro",
            "--model",
            "v2",
            "--grok-image-quality",
            "medium",
            "--aspect-ratio",
            "manga_b5_portrait",
            "--resolution",
            "2k",
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "model: v2" in out
    assert "resolved_model: grok-imagine-image-2.0" in out
    assert "grok_image_quality: medium" in out


def test_manga_batch_dry_run_rejects_quality_on_1x() -> None:
    code = manga_main(
        [
            str(ROOT / "tools" / "manga_prompt_ir" / "examples" / "p4_compare"),
            "--dry-run",
            "--source",
            "step1-pages",
            "--manga-stem",
            "manga_01",
            "--min-page",
            "1",
            "--max-page",
            "1",
            "--provider",
            "grok_pro",
            "--model",
            "quality",
            "--grok-image-quality",
            "low",
        ]
    )
    assert code == 2
