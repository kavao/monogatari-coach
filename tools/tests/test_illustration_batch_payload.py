"""挿絵バッチ: payload 組み立てと provider 別 resolution のテスト。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from image_provider_novel_illustration_batch import (  # noqa: E402
    build_job_payload,
    iter_illustration_jobs,
    page_prompt_tags,
)
from manga_prompt_ir.prompt_formatters import format_illustration_prompt  # noqa: E402
from tag_prompt_mask import MaskRuleSet, apply_mask  # noqa: E402


def test_build_job_payload_novelai_includes_reference_fields() -> None:
    ref = {
        "reference_image_paths": ["/tmp/a.naiv4vibebundle"],
        "reference_strength_multiple": [0.3],
        "reference_information_extracted_multiple": [0.5],
    }
    job = {
        "prompt": "p",
        "negative_prompt": "n",
        "prompt_formatter": "tag_csv",
        "negative_mode": "native",
        "output_dir": "/out",
        "prefix": "illustration_00_p01",
    }
    payload = build_job_payload(
        "novelai",
        job,
        aspect_ratio="book_cover",
        model=None,
        resolution="2k",
        novelai_ref_fields=ref,
    )
    assert payload["reference_image_paths"] == ref["reference_image_paths"]
    assert payload["aspect_ratio_preset"] == "book_cover"
    assert "resolution" not in payload


def test_build_job_payload_grok_includes_resolution() -> None:
    job = {
        "prompt": "p",
        "negative_prompt": "n",
        "prompt_formatter": "natural_sections",
        "negative_mode": "inline",
        "output_dir": "/out",
        "prefix": "illustration_01_p01",
    }
    payload = build_job_payload(
        "grok_pro",
        job,
        aspect_ratio="book_cover",
        model="quality",
        resolution="2k",
        novelai_ref_fields={},
    )
    assert payload["resolution"] == "2k"
    assert payload["model"] == "quality"


def test_illustration_page_prompt_tags_omit_character_names() -> None:
    page = {
        "meta": {"intent": "illustration"},
        "manga": {"genre_tags": ["illustration"], "visual_tags": ["anime illustration"]},
        "scene": {"location_en": "bathroom"},
        "character_ids": ["tsumugi", "yuto"],
        "character_snapshots": [
            {
                "character_id": "tsumugi",
                "name": "紬",
                "name_en": "Tsumugi",
                "fixed_tags": ["1girl", "black_hair", "twin_tails"],
                "variant_tags": ["nude"],
            },
            {
                "character_id": "yuto",
                "name": "悠斗",
                "name_en": "Yuto",
                "fixed_tags": ["1boy", "slim", "black_hair"],
                "variant_tags": ["nude"],
            },
        ],
        "panels": [
            {
                "panel_id": 1,
                "summary": "壺を掲げる",
                "subjects": [
                    {"character_id": "tsumugi", "pose_action_en": "holding jar"},
                    {"character_id": "yuto", "pose_action_en": "reaching"},
                ],
                "prompt_tags": ["bathtub", "size_difference"],
                "composition": {"framing_en": "medium shot", "focus_en": "tsumugi"},
            }
        ],
    }
    characters = {
        "tsumugi": {"character_id": "tsumugi", "name_en": "Tsumugi"},
        "yuto": {"character_id": "yuto", "name_en": "Yuto"},
    }
    tags = page_prompt_tags(page, characters)
    assert "Tsumugi" not in tags
    assert "Yuto" not in tags
    assert "tsumugi" not in tags
    assert "yuto" not in tags
    assert "black_hair" in tags
    assert "bathtub" in tags
    bundle = format_illustration_prompt(
        page,
        tag_prompt=", ".join(tags),
        negative_prompt="bad anatomy",
        formatter="tag_csv",
        style_prefix="best quality, ",
    )
    assert "Tsumugi" not in bundle.prompt
    assert "Yuto" not in bundle.prompt


def test_illustration_mask_applies_character_tag_batch_rules() -> None:
    tags = [
        "1girl",
        "childlike_mature",
        "pointed ears",
        "black_hair",
        "twin_tails",
    ]
    rules = MaskRuleSet(
        omit_tags=("pointed ears",),
        replace_pairs=(("childlike_mature", "toddler, Short stack, loli"),),
    )
    masked = apply_mask(tags, rules).tags
    assert "childlike_mature" not in masked
    assert "pointed ears" not in masked
    assert "pointed_ears" not in {t.replace(" ", "_").lower() for t in masked}
    assert "toddler" in masked
    assert "Short stack" in masked
    assert "loli" in masked
    assert "black_hair" in masked


def test_iter_illustration_jobs_respects_mask_rules(tmp_path: Path, monkeypatch, capsys) -> None:
    novel = tmp_path / "088_test"
    pages = novel / "illustrations" / "pages"
    pages.mkdir(parents=True)
    (novel / "tag" / "characters").mkdir(parents=True)
    (pages / "illustration_00_p01.yaml").write_text(
        """
schema_version: "1.0"
meta:
  intent: illustration
  aspect_ratio: "2:3"
manga:
  panel_layout: 枠線なし・一枚絵
technical:
  negative_tags: [tech_bad, keep_tech]
scene:
  location: 浴室
  location_en: bathroom
character_ids: [tsumugi]
character_snapshots:
  - character_id: tsumugi
    name_en: Tsumugi
    fixed_tags: [1girl, childlike_mature, pointed ears, black_hair]
    variant_tags: [nude]
panels:
  - panel_id: 1
    summary: test
    summary_en: test panel
    summary_en_source: test panel
    subjects:
      - character_id: tsumugi
        description: 紬
        pose_action_en: standing
    prompt_tags: [bathtub]
    composition:
      framing_en: medium shot
    lighting:
      quality_en: soft light
color_palette:
  mode: full_color
""".strip(),
        encoding="utf-8",
    )
    rules = MaskRuleSet(
        omit_tags=("pointed ears",),
        replace_pairs=(("childlike_mature", "toddler"),),
    )
    jobs = iter_illustration_jobs(
        novel,
        None,
        cli_negative_prompt="bad anatomy, cli_bad",
        provider="novelai",
        prompt_formatter="tag_csv",
        mask_rules=rules,
        negative_omit=("tech_bad", "cli_bad"),
    )
    assert len(jobs) == 1
    prompt = jobs[0]["prompt"]
    assert "childlike_mature" not in prompt
    assert "pointed_ears" not in prompt
    assert "pointed ears" not in prompt
    assert "toddler" in prompt
    assert "black_hair" in prompt
    assert jobs[0]["negative_prompt"] == "bad anatomy, keep_tech"
    assert jobs[0]["negative_omitted"] == ["cli_bad", "tech_bad"]
    unchanged = iter_illustration_jobs(novel, None, cli_negative_prompt="cli_bad, keep", provider="novelai", prompt_formatter="tag_csv")
    assert unchanged[0]["negative_prompt"] == "cli_bad, keep, tech_bad, keep_tech"

    from types import SimpleNamespace
    import image_provider_novel_illustration_batch as batch
    (novel / "_meta.yaml").write_text("character_tag_batch:\n  omit_negative_tags: [tech_bad]\nillustration_tag_batch:\n  omit_negative_tags: [local_bad]\n", encoding="utf-8")
    monkeypatch.setattr(batch, "dotenv_or_env", lambda *a, **kw: None)
    monkeypatch.setattr(batch, "resolve_novelai_reference", lambda *a, **kw: SimpleNamespace(paths=[], source="none", strength=0.5, information_extracted=0.5))
    monkeypatch.setattr(batch, "preview_merged_params", lambda *a, **kw: {})
    assert batch.main([str(novel), "--provider", "forge", "--prompt-formatter", "tag_csv", "--dry-run", "--negative-prompt", "cli_bad, local_bad, keep", "--omit-negative-tags", "cli_bad"]) == 0
    out = capsys.readouterr().out
    assert "omit_negative_tags: tech_bad, local_bad, cli_bad" in out
    assert "negative omitted: cli_bad, local_bad, tech_bad" in out
    assert "negative: keep, keep_tech" in out
    natural = iter_illustration_jobs(novel, None, cli_negative_prompt="cli_bad, keep", provider="grok", prompt_formatter="natural_sections", negative_omit=("cli_bad", "tech_bad"))
    assert natural[0]["negative_prompt"] == ""
    assert "cli_bad" not in natural[0]["prompt"]
    assert "tech_bad" not in natural[0]["prompt"]
    assert "keep_tech" in natural[0]["prompt"]
