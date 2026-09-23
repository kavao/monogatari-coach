"""Offline contract tests for the explicit NovelAI restyle entry point."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from image_edit.restyle import (  # noqa: E402
    RestyleError,
    build_restyle_plan,
    execute_restyle,
    load_restyle_plan,
    save_restyle_plan,
)
from image_provider_edit import main  # noqa: E402
from codex_builtin_image_archive import latest_image  # noqa: E402
from novel_meta_yaml import (  # noqa: E402
    resolve_novelai_portion,
    resolve_novelai_portion_strict,
)


def _image(path: Path, *, mode: str = "RGB", size: tuple[int, int] = (128, 64)) -> Path:
    Image.new(mode, size, (20, 40, 60, 255) if "A" in mode else (20, 40, 60)).save(path)
    return path


def test_dry_run_img2img_redacts_source_and_keeps_txt2img_contract(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = _image(tmp_path / "source.png")
    (tmp_path / "source.json").write_text(
        json.dumps(
            {
                "prompt": "1girl, standing",
                "negative_prompt": "bad hands",
                "model": "nai-diffusion-5-full",
                "v4_prompt": {"secret": "must not be merged"},
                "characterPrompts": [{"prompt": "must not be merged"}],
                "seed": 999,
            }
        ),
        encoding="utf-8",
    )
    rc = main(
        [
            "--input",
            str(source),
            "--model",
            "v4-5-full",
            "--no-style-reference",
            "--output-dir",
            str(tmp_path / "out"),
            "--dry-run",
        ]
    )
    assert rc == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["action"] == "img2img"
    assert plan["model"] == "nai-diffusion-4-5-full"
    assert plan["style_references"] == []
    assert plan["payload"]["parameters"]["strength"] == 0.5
    assert plan["payload"]["parameters"]["noise"] == 0.0
    assert "add_original_image" not in plan["payload"]["parameters"]
    assert plan["payload"]["parameters"]["image"]["redacted"] is True
    assert plan["payload"]["parameters"]["image"]["length"] > 0
    assert plan["payload"]["input"].count("masterpiece") == 1
    assert "secret" not in json.dumps(plan, ensure_ascii=False)
    assert Path(plan["plan_path"]).is_file()
    assert "_restyle" in Path(plan["output_dir"]).parts
    assert Path(plan["plan_path"]).parent == Path(plan["output_dir"])


def test_dry_run_keeps_source_and_vibe_in_separate_payload_fields(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = _image(tmp_path / "source.png")
    vibe = _image(tmp_path / "style.png")
    options = tmp_path / "options.json"
    options.write_text(
        json.dumps(
            {
                "strength": 0.2,
                "noise": 0,
                "seed": 123,
                "add_original_image": False,
            }
        ),
        encoding="utf-8",
    )
    assert (
        main(
            [
                "--input",
                str(source),
                "--model",
                "nai-diffusion-4-5-full",
                "--style-reference",
                str(vibe),
                "--prompt",
                "1girl, standing",
                "--provider-options",
                str(options),
                "--output-dir",
                str(tmp_path / "out"),
                "--dry-run",
            ]
        )
        == 0
    )
    plan = json.loads(capsys.readouterr().out)
    params = plan["payload"]["parameters"]
    assert params["image"]["redacted"] is True
    assert params["reference_image_multiple"][0]["redacted"] is True
    assert params["add_original_image"] is False
    assert plan["style_references"][0]["kind"] == "image"


def test_rgba_input_stops_without_conversion(tmp_path: Path) -> None:
    source = _image(tmp_path / "source.png", mode="RGBA")
    with pytest.raises(RestyleError, match="RGBA/透過"):
        build_restyle_plan(
            root=ROOT,
            source_path=source,
            model="nai-diffusion-4-5-full",
            prompt="1girl",
            output_dir=str(tmp_path / "out"),
        )


def test_rgba_input_can_explicitly_flatten_to_white(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    Image.new("RGBA", (128, 64), (20, 40, 60, 128)).save(source)
    plan = build_restyle_plan(
        root=ROOT,
        source_path=source,
        model="nai-diffusion-4-5-full",
        prompt="1girl",
        output_dir=str(tmp_path / "out"),
        alpha_background="white",
    )
    assert plan["alpha_handling"] == {
        "kind": "flatten_to_rgb",
        "approved": True,
        "background": "#ffffff",
        "source_mode": "RGBA",
    }
    prepared = Path(plan["prepared_image"]["path"])
    with Image.open(prepared) as image:
        assert image.mode == "RGB"
        assert image.getpixel((0, 0)) == (137, 147, 157)
    assert plan["sendable"] is True


def test_palette_without_transparency_does_not_require_flattening(tmp_path: Path) -> None:
    source = tmp_path / "palette.png"
    image = Image.new("P", (128, 64))
    image.putpalette([20, 40, 60] + [0, 0, 0] * 255)
    image.save(source)
    plan = build_restyle_plan(
        root=ROOT,
        source_path=source,
        model="nai-diffusion-4-5-full",
        prompt="1girl",
        output_dir=str(tmp_path / "out"),
    )
    assert plan["alpha_handling"]["kind"] == "none"
    assert plan["preprocessed_image"]["status"] == "same_as_source"


def test_execute_rejects_changed_prepared_hash_before_auth(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    Image.new("RGBA", (128, 64), (20, 40, 60, 128)).save(source)
    plan = build_restyle_plan(
        root=ROOT,
        source_path=source,
        model="nai-diffusion-4-5-full",
        prompt="1girl",
        output_dir=str(tmp_path / "out"),
        alpha_background="white",
    )
    save_restyle_plan(plan)
    plan["prepared_image"]["sha256"] = "0" * 64
    with pytest.raises(RestyleError, match="前処理済み画像のhash"):
        execute_restyle(
            root=ROOT,
            plan=plan,
            provider_cfg={"auth_env": "MISSING_TEST_AUTH"},
        )


def test_nonwhite_alpha_background_with_letterbox_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    Image.new("RGBA", (200, 100), (20, 40, 60, 128)).save(source)
    with pytest.raises(RestyleError, match="非白のalpha-backgroundと寸法変換"):
        build_restyle_plan(
            root=ROOT,
            source_path=source,
            model="nai-diffusion-4-5-full",
            prompt="1girl",
            output_dir=str(tmp_path / "out"),
            alpha_background="#ff0000",
        )


def test_persisted_plan_rejects_nonwhite_alpha_with_letterbox(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    Image.new("RGBA", (200, 100), (20, 40, 60, 128)).save(source)
    plan = build_restyle_plan(
        root=ROOT,
        source_path=source,
        model="nai-diffusion-4-5-full",
        prompt="1girl",
        output_dir=str(tmp_path / "out"),
        alpha_background="white",
    )
    plan["alpha_handling"]["background"] = "#ff0000"
    plan_path = save_restyle_plan(plan)
    with pytest.raises(RestyleError, match="非白alpha-backgroundと寸法変換"):
        load_restyle_plan(plan_path)


def test_unknown_options_and_v5_model_are_rejected(tmp_path: Path) -> None:
    source = _image(tmp_path / "source.png")
    with pytest.raises(RestyleError, match="未知オプション"):
        build_restyle_plan(
            root=ROOT,
            source_path=source,
            model="nai-diffusion-4-5-full",
            prompt="1girl",
            options={"model": "nai-diffusion-5-full"},
            output_dir=str(tmp_path / "out"),
        )
    with pytest.raises(RestyleError, match="MVP"):
        build_restyle_plan(
            root=ROOT,
            source_path=source,
            model="nai-diffusion-5-full",
            prompt="1girl",
            output_dir=str(tmp_path / "out"),
        )


def test_partial_quality_suffix_requires_explicit_choice(tmp_path: Path) -> None:
    source = _image(tmp_path / "source.png")
    with pytest.raises(RestyleError, match="品質接尾辞"):
        build_restyle_plan(
            root=ROOT,
            source_path=source,
            model="nai-diffusion-4-5-full",
            prompt="1girl, no text",
            output_dir=str(tmp_path / "out"),
        )


def test_invalid_dimensions_stop_without_transform_approval(tmp_path: Path) -> None:
    source = _image(tmp_path / "source.png", size=(200, 100))
    plan = build_restyle_plan(
        root=ROOT,
        source_path=source,
        model="nai-diffusion-4-5-full",
        prompt="1girl",
        output_dir=str(tmp_path / "out"),
    )
    assert plan["sendable"] is False
    assert plan["transformation"]["approved"] is False
    assert plan["payload"]["parameters"]["width"] == 128
    assert plan["payload"]["parameters"]["height"] == 64


def test_execute_rejects_unapproved_letterbox(tmp_path: Path) -> None:
    source = _image(tmp_path / "source.png", size=(200, 100))
    plan = build_restyle_plan(
        root=ROOT,
        source_path=source,
        model="nai-diffusion-4-5-full",
        prompt="1girl",
        output_dir=str(tmp_path / "out"),
    )
    with pytest.raises(RestyleError, match="未承認"):
        execute_restyle(
            root=ROOT,
            plan=plan,
            provider_cfg={"auth_env": "MISSING_TEST_AUTH"},
        )


def test_execute_revalidates_source_hash_before_auth_or_network(tmp_path: Path) -> None:
    source = _image(tmp_path / "source.png")
    plan = build_restyle_plan(
        root=ROOT,
        source_path=source,
        model="nai-diffusion-4-5-full",
        prompt="1girl",
        output_dir=str(tmp_path / "out"),
    )
    _image(source, size=(192, 64))
    with pytest.raises(RestyleError, match="hash"):
        execute_restyle(
            root=ROOT,
            plan=plan,
            provider_cfg={"auth_env": "MISSING_TEST_AUTH"},
        )


def test_execute_reloads_persisted_plan_and_rejects_changed_source(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = _image(tmp_path / "source.png")
    assert (
        main(
            [
                "--input",
                str(source),
                "--model",
                "nai-diffusion-4-5-full",
                "--no-style-reference",
                "--prompt",
                "1girl",
                "--output-dir",
                str(tmp_path / "comic"),
                "--dry-run",
            ]
        )
        == 0
    )
    plan = json.loads(capsys.readouterr().out)
    plan_path = Path(plan["plan_path"])
    _image(source, size=(192, 64))
    assert main(["--execute", "--plan", str(plan_path)]) == 2
    assert "hash" in capsys.readouterr().err


def test_explicit_portion_does_not_fallback(tmp_path: Path) -> None:
    novel = tmp_path / "novel"
    novel.mkdir()
    _image(novel / "fallback.png")
    (novel / "_meta.yaml").write_text(
        """
version: 1
novelai:
  portions:
    work_manga:
      path: missing.naiv4vibe
    fallback:
      path: fallback.png
  portion_default: work_manga
  portion_fallback: fallback
""",
        encoding="utf-8",
    )
    with pytest.raises(FileNotFoundError, match="work_manga"):
        resolve_novelai_portion_strict(novel, ROOT, portion_id="work_manga")
    resolved = resolve_novelai_portion(novel, ROOT, portion_id="work_manga")
    assert resolved is not None
    assert resolved.id == "fallback"


def test_restyle_subdirectory_is_excluded_from_latest_image_search(tmp_path: Path) -> None:
    restyle = tmp_path / "comic" / "_restyle" / "run-1"
    restyle.mkdir(parents=True)
    restyle_image = _image(restyle / "candidate.png")
    with pytest.raises(FileNotFoundError):
        latest_image(tmp_path / "comic")
    regular = _image(tmp_path / "comic" / "accepted.png")
    assert latest_image(tmp_path / "comic") == regular
    assert restyle_image != regular
