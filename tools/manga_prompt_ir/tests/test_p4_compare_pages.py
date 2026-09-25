from __future__ import annotations

import json
import shutil
import sys
from types import SimpleNamespace
from pathlib import Path

import pytest
import yaml
from PIL import Image

_TOOLS_ROOT = Path(__file__).resolve().parents[2]
if str(_TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(_TOOLS_ROOT))

from manga_prompt_ir.page_render_plan import PageRenderPlanError, compile_page_render_plan  # noqa: E402
from manga_prompt_ir.schemas.character import CharacterPrompt  # noqa: E402
from manga_prompt_ir.schemas.manga_page import MangaPagePrompt  # noqa: E402
from image_provider_novel_manga_batch import (  # noqa: E402
    DEFAULT_NEGATIVE,
    iter_yaml_manga_jobs,
)
import image_provider_novel_manga_batch as manga_batch  # noqa: E402

_P4 = _TOOLS_ROOT / "manga_prompt_ir" / "examples" / "p4_compare"
_PAGES = _P4 / "manga" / "pages"


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "name",
    ["manga_01_p01.yaml", "manga_02_p01.yaml", "manga_03_p01.yaml", "manga_03_p02.yaml"],
)
def test_p4_compare_pages_validate_as_schema_1_1(name: str) -> None:
    page = _load(_PAGES / name)
    model = MangaPagePrompt.model_validate(page)
    assert model.schema_version == "1.1"
    assert model.layout_geometry is not None
    assert model.dramaturgy is not None


def test_p4_character_yaml_validates() -> None:
    kazuki = yaml.safe_load((_P4 / "tag" / "characters" / "kazuki.yaml").read_text(encoding="utf-8"))
    yui = yaml.safe_load((_P4 / "tag" / "characters" / "yui.yaml").read_text(encoding="utf-8"))
    CharacterPrompt.model_validate(kazuki)
    CharacterPrompt.model_validate(yui)
    assert kazuki["schema_version"] == "1.1"
    assert "casual_jacket" not in str(kazuki)
    assert kazuki["prompt_variants"][1]["visual_spec"]["outer"]["hood"] is False


def _characters() -> dict:
    out = {}
    for name in ("kazuki.yaml", "yui.yaml"):
        data = _load(_P4 / "tag" / "characters" / name)
        out[data["character_id"]] = data
    return out


def test_p4_page_a_compiles_for_page_providers_and_letter_later() -> None:
    page = _load(_PAGES / "manga_01_p01.yaml")
    characters = _characters()
    assert page["manga"]["lettering"] == {
        "direction": "vertical",
        "base_font_size": 30,
        "size_policy": "uniform_then_shrink",
    }
    for provider in ("novelai", "openai", "openrouter", "grok"):
        extra = {}
        if provider == "openrouter":
            extra["resolved_profile"] = "nano_banana_2"
        plan = compile_page_render_plan(
            page,
            source="step1-pages",
            provider=provider,
            existing_prompt="Page A comparison fixture",
            negative_prompt="watermark",
            characters=characters,
            **extra,
        )
        assert [item["panel_id"] for item in plan.text_manifest] == [10, 20, 30, 40]
        assert all(item["writing_direction"] == "vertical" for item in plan.text_manifest)
        if provider == "novelai":
            assert plan.text_mode == "generate"
            slot_text = "\n".join(slot["prompt"] for slot in plan.character_slots)
            assert "白い吹き出し「これ、見て。」" in slot_text
            assert "text, speech bubble" in plan.prompt
            assert "exactly 1 empty speech bubble" not in plan.prompt
            assert "speaker=" not in plan.prompt
            assert "Text:" not in plan.prompt
            assert all(len(slot["centers"]) == 1 for slot in plan.character_slots)
        else:
            assert "これ、見て。" in plan.prompt
            assert "白い吹き出し" not in plan.prompt
            assert "text, speech bubble" not in plan.prompt
        assert plan.ordered_image_inputs == []
    later = compile_page_render_plan(
        page,
        source="step1-pages",
        provider="grok",
        existing_prompt="Page A comparison fixture",
        negative_prompt="",
        text_mode="letter_later",
        characters=characters,
    )
    assert later.text_mode == "letter_later"
    assert "これ、見て。" not in later.prompt
    assert later.text_manifest[0]["content"] == "これ、見て。"
    assert "baseline lettering direction: vertical Japanese writing" in later.prompt
    assert "lettering direction: vertical" in later.prompt
    assert later.prompt.count("exactly 1 empty speech bubble") == 4
    assert "assigned speaker(s): Yui" in later.prompt
    assert "assigned speaker(s): Kazuki" in later.prompt
    assert "Do not add any additional speech bubbles" in later.prompt


def test_p4_grok_page_batch_deduplicates_character_visual_prompt() -> None:
    all_jobs = []
    for stem in ("manga_01", "manga_02", "manga_03"):
        all_jobs.extend(
            iter_yaml_manga_jobs(
                _P4,
                stem,
                "step1-pages",
                "grok_pro",
                None,
                cli_negative_prompt=DEFAULT_NEGATIVE,
                prompt_formatter="manga_page_instruction",
                page_compiler="page_render_plan",
                text_mode="letter_later",
            )
        )

    for job in all_jobs:
        prompt = str(job["prompt"])
        assert len(prompt.encode("utf-8")) <= 7800
        assert "キャラクター固定特徴（tag/characters/*.yaml 準拠）:" not in prompt
        assert "navy_harrington_jacket" not in prompt
        assert prompt.count("navy harrington jacket") == 1

    assert "looking at the ticket" in str(all_jobs[0]["prompt"])

    openai_jobs = iter_yaml_manga_jobs(
        _P4,
        "manga_01",
        "step1-pages",
        "openai",
        None,
        cli_negative_prompt=DEFAULT_NEGATIVE,
        prompt_formatter="manga_page_instruction",
        page_compiler="page_render_plan",
        text_mode="letter_later",
    )
    openai_prompt = str(openai_jobs[0]["prompt"])
    assert "キャラクター固定特徴（tag/characters/*.yaml 準拠）:" in openai_prompt
    assert "navy_harrington_jacket" in openai_prompt


def test_p4_empty_snapshots_without_character_map_stop() -> None:
    page = _load(_PAGES / "manga_01_p01.yaml")
    for snapshot in page.get("character_snapshots") or []:
        snapshot.pop("character_source_sha256", None)
        snapshot.pop("visual_natural", None)
        snapshot.pop("character_schema_version", None)
    with pytest.raises(PageRenderPlanError, match="キャラクター YAML がありません"):
        compile_page_render_plan(
            page,
            source="step1-pages",
            provider="grok",
            existing_prompt="Page A comparison fixture",
            negative_prompt="watermark",
        )


def _p4_novel(tmp_path: Path) -> Path:
    novel = tmp_path / "p4_compare"
    pages = novel / "manga" / "pages"
    chars = novel / "tag" / "characters"
    pages.mkdir(parents=True)
    chars.mkdir(parents=True)
    shutil.copy2(_PAGES / "manga_01_p01.yaml", pages / "manga_01_p01.yaml")
    for name in ("kazuki.yaml", "yui.yaml"):
        shutil.copy2(_P4 / "tag" / "characters" / name, chars / name)
    return novel


def test_p4_grok_letter_later_and_novelai_local_dry_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    novel = _p4_novel(tmp_path)
    grok_rc = manga_batch.main(
        [
            str(novel),
            "--manga-stem",
            "manga_01",
            "--source",
            "step1-pages",
            "--provider",
            "grok_pro",
            "--page-compiler",
            "page_render_plan",
            "--text-mode",
            "letter_later",
            "--min-page",
            "1",
            "--max-page",
            "1",
            "--dry-run",
        ]
    )
    grok_out = capsys.readouterr()
    assert grok_rc == 0
    assert "capability_key=grok_imagine_2" in grok_out.out
    assert "text_mode=letter_later" in grok_out.out
    assert "bubble_frame_mode=provider" in grok_out.out
    assert "not written in dry-run" in grok_out.out

    nai_rc = manga_batch.main(
        [
            str(novel),
            "--manga-stem",
            "manga_01",
            "--source",
            "step1-pages",
            "--provider",
            "novelai",
            "--page-compiler",
            "page_render_plan",
            "--bubble-frame-mode",
            "local",
            "--novelai-portion-id",
            "none",
            "--min-page",
            "1",
            "--max-page",
            "1",
            "--dry-run",
        ]
    )
    nai_out = capsys.readouterr()
    assert nai_rc == 0
    assert "capability_key=novelai_v5" in nai_out.out
    assert "text_mode=none" in nai_out.out
    assert "bubble_frame_mode=local" in nai_out.out
    assert "bubbles_suppressed=True" in nai_out.out
    assert "resolved_model: nai-diffusion-5-full" in nai_out.out
    assert "aspect_ratio: manga_b5_portrait (manga page default)" in nai_out.out
    assert "image_size: 832x1216" in nai_out.out
    assert "白い吹き出し" not in nai_out.out
    assert "Text Layout" not in nai_out.out
    assert "not written in dry-run" in nai_out.out
    assert not (novel / "manga" / "_assets").exists()


def test_local_generation_writes_local_frame_json(tmp_path: Path, monkeypatch) -> None:
    novel = _p4_novel(tmp_path)

    def fake_run(cmd, **kwargs):
        params_path = Path(cmd[cmd.index("--params") + 1])
        payload = json.loads(params_path.read_text(encoding="utf-8"))
        out = Path(payload["output_dir"])
        out.mkdir(parents=True, exist_ok=True)
        png = out / f"{payload['file_prefix']}_fake.png"
        Image.new("RGB", (64, 64), (12, 24, 36)).save(png)
        gen = out / f"{payload['file_prefix']}_fake.json"
        gen.write_text(json.dumps({"provider": "novelai", "saved_png": str(png)}), encoding="utf-8")
        stdout = json.dumps(
            {
                "ok": True,
                "provider": "novelai",
                "saved": [{"png": str(png), "json": str(gen)}],
            }
        )
        return SimpleNamespace(returncode=0, stdout=stdout, stderr="")

    monkeypatch.setattr(manga_batch.subprocess, "run", fake_run)
    rc = manga_batch.main(
        [
            str(novel),
            "--manga-stem",
            "manga_01",
            "--source",
            "step1-pages",
            "--provider",
            "novelai",
            "--page-compiler",
            "page_render_plan",
            "--bubble-frame-mode",
            "local",
            "--novelai-portion-id",
            "none",
            "--min-page",
            "1",
            "--max-page",
            "1",
        ]
    )
    assert rc == 0
    comic = novel / "manga" / "_assets" / "manga_01" / "comic"
    sidecars = list(comic.glob("*.local_frame.json"))
    assert len(sidecars) == 1
    record = json.loads(sidecars[0].read_text(encoding="utf-8"))
    assert record["bubble_frame_mode"] == "local"
    assert record["text_mode"] == "none"
    assert record["bubbles_suppressed"] is True
    assert len(record["source_sha256"]) == 64
    gen_json = next(comic.glob("*_fake.json"))
    merged = json.loads(gen_json.read_text(encoding="utf-8"))
    assert merged["bubbles_suppressed"] is True
    assert merged["source_sha256"] == record["source_sha256"]


def test_local_generation_resolves_mojibake_saved_paths(
    tmp_path: Path, monkeypatch
) -> None:
    novel = _p4_novel(tmp_path)

    def fake_run(cmd, **kwargs):
        params_path = Path(cmd[cmd.index("--params") + 1])
        payload = json.loads(params_path.read_text(encoding="utf-8"))
        out = Path(payload["output_dir"])
        out.mkdir(parents=True, exist_ok=True)
        png = out / f"{payload['file_prefix']}_fake.png"
        Image.new("RGB", (64, 64), (12, 24, 36)).save(png)
        gen = out / f"{payload['file_prefix']}_fake.json"
        gen.write_text(json.dumps({"provider": "novelai"}), encoding="utf-8")
        broken = r"K:\\\ufffd\ufffdL\\missing\\" + png.name
        stdout = json.dumps(
            {
                "ok": True,
                "provider": "novelai",
                "saved": [
                    {
                        "png": broken,
                        "json": broken.replace(".png", ".json"),
                    }
                ],
            }
        )
        return SimpleNamespace(returncode=0, stdout=stdout, stderr="")

    monkeypatch.setattr(manga_batch.subprocess, "run", fake_run)
    rc = manga_batch.main(
        [
            str(novel),
            "--manga-stem",
            "manga_01",
            "--source",
            "step1-pages",
            "--provider",
            "novelai",
            "--page-compiler",
            "page_render_plan",
            "--bubble-frame-mode",
            "local",
            "--novelai-portion-id",
            "none",
            "--min-page",
            "1",
            "--max-page",
            "1",
        ]
    )
    assert rc == 0
    comic = novel / "manga" / "_assets" / "manga_01" / "comic"
    sidecar = next(comic.glob("*.local_frame.json"))
    record = json.loads(sidecar.read_text(encoding="utf-8"))
    png = next(comic.glob("*_fake.png"))
    assert Path(record["saved_png"]).resolve() == png.resolve()
    gen = json.loads(next(comic.glob("*_fake.json")).read_text(encoding="utf-8"))
    assert gen["source_sha256"] == record["source_sha256"]
