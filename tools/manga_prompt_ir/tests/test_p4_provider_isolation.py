from __future__ import annotations

import copy
import hashlib
import json
import shutil
import sys
from pathlib import Path

import pytest
import yaml

_TOOLS_ROOT = Path(__file__).resolve().parents[2]
if str(_TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(_TOOLS_ROOT))

import image_provider_novel_manga_batch as manga_batch  # noqa: E402
import manga_prompt_ir.page_render_plan as page_render_plan  # noqa: E402
from image_provider_novel_manga_batch import (  # noqa: E402
    DEFAULT_NEGATIVE,
    iter_yaml_manga_jobs,
)
from manga_prompt_ir.page_render_plan import (  # noqa: E402
    PageRenderPlanError,
    compile_page_render_plan,
)

_P4 = _TOOLS_ROOT / "manga_prompt_ir" / "examples" / "p4_compare"
_PAGE = _P4 / "manga" / "pages" / "manga_01_p01.yaml"


def _page() -> dict:
    return yaml.safe_load(_PAGE.read_text(encoding="utf-8"))


def _novel(tmp_path: Path) -> Path:
    novel = tmp_path / "p4_provider_isolation"
    pages = novel / "manga" / "pages"
    chars = novel / "tag" / "characters"
    pages.mkdir(parents=True)
    chars.mkdir(parents=True)
    shutil.copy2(_PAGE, pages / _PAGE.name)
    for source in (_P4 / "tag" / "characters").glob("*.yaml"):
        shutil.copy2(source, chars / source.name)
    return novel


def _characters() -> dict[str, dict]:
    out = {}
    for source in (_P4 / "tag" / "characters").glob("*.yaml"):
        data = yaml.safe_load(source.read_text(encoding="utf-8"))
        out[data["character_id"]] = data
    return out


@pytest.mark.parametrize("provider", ["grok", "openai", "openrouter"])
def test_compaction_mode_is_rejected_for_non_novelai_compiler(
    provider: str,
) -> None:
    extra = {"resolved_profile": "nano_banana_2"} if provider == "openrouter" else {}
    with pytest.raises(PageRenderPlanError, match="NovelAI"):
        compile_page_render_plan(
            _page(),
            source="step1-pages",
            provider=provider,
            existing_prompt="baseline page prompt",
            negative_prompt="",
            prompt_compaction="safe",
            **extra,
        )


def test_batch_rejects_compaction_for_novelai_legacy_panel_mode(
    tmp_path: Path,
) -> None:
    with pytest.raises(PageRenderPlanError, match="黙ってlegacyへ戻しません"):
        iter_yaml_manga_jobs(
            _novel(tmp_path),
            "manga_01",
            "step1-panels",
            "novelai",
            None,
            cli_negative_prompt=DEFAULT_NEGATIVE,
            prompt_formatter="novelai_pipe",
            page_compiler="legacy",
            prompt_compaction="safe",
        )


def test_batch_without_manga_stem_ignores_bubble_sidecars(
    tmp_path: Path,
) -> None:
    novel = _novel(tmp_path)
    (novel / "manga" / "pages" / "manga_01_p01.bubbles.yaml").write_text(
        "bubbles: []\n",
        encoding="utf-8",
    )

    jobs = iter_yaml_manga_jobs(
        novel,
        None,
        "step1-pages",
        "grok",
        None,
        cli_negative_prompt=DEFAULT_NEGATIVE,
        prompt_formatter="manga_page_instruction",
        page_compiler="legacy",
        prompt_compaction="off",
    )

    assert len(jobs) == 1
    assert jobs[0]["page"] == "1"


@pytest.mark.parametrize(
    ("provider", "page_compiler"),
    [
        ("grok", "page_render_plan"),
        ("openai", "page_render_plan"),
        ("openrouter", "page_render_plan"),
        ("forge", "legacy"),
    ],
)
def test_compaction_off_does_not_call_common_core(
    provider: str,
    page_compiler: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_if_called(*args, **kwargs):
        raise AssertionError("prompt compaction core must not run in off mode")

    monkeypatch.setattr(page_render_plan, "compact_page_prompt", fail_if_called)
    jobs = iter_yaml_manga_jobs(
        _novel(tmp_path),
        "manga_01",
        "step1-pages",
        provider,
        None,
        cli_negative_prompt=DEFAULT_NEGATIVE,
        prompt_formatter="manga_page_instruction",
        page_compiler=page_compiler,
        prompt_compaction="off",
    )

    assert len(jobs) == 1
    assert "prompt_compaction" not in str(jobs[0].get("metadata") or {})
    if page_compiler == "page_render_plan":
        plan = jobs[0]["page_render_plan"]
        assert "prompt_compaction" not in plan.effective_settings
    else:
        assert "page_render_plan" not in jobs[0]


@pytest.mark.parametrize(
    ("provider", "source", "page_compiler", "formatter", "prompt_sha256", "payload_sha256"),
    [
        (
            "grok",
            "step1-pages",
            "page_render_plan",
            "manga_page_instruction",
            "501d308b3bd85e24af5f82cbe8962b6374ae28b2c5b25a2ad6d08069ece83f8e",
            "f6be44f24c5d985dddcffdab02d75761667e822df29df16f4857b6dcfe3cacd2",
        ),
        (
            "openai",
            "step1-pages",
            "page_render_plan",
            "manga_page_instruction",
            "a77dfdd9a0241bd911f895a7e4f52d24f40cbc31cde476850a02aab942721ab5",
            "bf22c9d8bf46d451fa4a85c11fd2e302bda9edff2fd3fa0d625ffd721522ac95",
        ),
        (
            "openrouter",
            "step1-pages",
            "page_render_plan",
            "manga_page_instruction",
            "612470cfa5da3b5f382667208d5db65858588ac140955503e7f25875d03751aa",
            "d703da0f95fc3d856defdb6e8a4c954321b621308fc8d52b180e4edb84ded8a3",
        ),
        (
            "forge",
            "step1-panels",
            "legacy",
            "tag_csv",
            "b29bd0753fde55851117a95bfaec2943b1f26964476f26f54a1ea6a723dec488",
            "6abf1e8f492a1a9cc7bfdbdc66fb06625034320279c4a7be358d25c618cd821a",
        ),
    ],
)
def test_compaction_off_golden_prompt_and_payload_are_provider_stable(
    provider: str,
    source: str,
    page_compiler: str,
    formatter: str,
    prompt_sha256: str,
    payload_sha256: str,
) -> None:
    jobs = iter_yaml_manga_jobs(
        _P4,
        "manga_01",
        source,
        provider,
        None,
        cli_negative_prompt=DEFAULT_NEGATIVE,
        prompt_formatter=formatter,
        page_compiler=page_compiler,
        prompt_compaction="off",
    )
    job = jobs[0]
    payload = {
        "provider": provider,
        "prompt": job["prompt"],
        "negative_prompt": job.get("negative_prompt", DEFAULT_NEGATIVE),
        "output_dir": "OUT",
        "file_prefix": job["prefix"],
        "count": 1,
        "seed": 20260924,
        "prompt_formatter": job.get("prompt_formatter", formatter),
        "negative_mode": job.get("negative_mode", "native_negative"),
    }
    merged = manga_batch.preview_merged_params(manga_batch.repo_root(), provider, payload)
    stable = {
        key: value
        for key, value in merged.items()
        if key not in {"output_dir", "file_prefix", "seed"}
    }
    assert hashlib.sha256(job["prompt"].encode("utf-8")).hexdigest() == prompt_sha256
    assert hashlib.sha256(
        json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest() == payload_sha256


def test_novelai_legacy_panel_prompt_keeps_base_pipe_character_shape(
    tmp_path: Path,
) -> None:
    jobs = iter_yaml_manga_jobs(
        _novel(tmp_path),
        "manga_01",
        "step1-panels",
        "novelai",
        None,
        cli_negative_prompt=DEFAULT_NEGATIVE,
        prompt_formatter="novelai_pipe",
        page_compiler="legacy",
        prompt_compaction="off",
        use_novelai_pipe_split=True,
    )

    assert len(jobs) == 4
    prompt = jobs[0]["prompt"]
    assert prompt.count(" | ") == 2
    assert prompt.endswith(
        "Yui, 1girl, young_woman, brown_hair, green_eyes, fair_skin, "
        "small_mole_near_the_left_eye, cream_cardigan, v_neck_collar, "
        "button_front, no_hood, white_blouse, brown_plaid_skirt, "
        "canvas_tote, holding_out_a_paper_ticket, smile, midground"
    )
    assert "page_render_plan" not in jobs[0]


def test_compacted_text_contract_keeps_manifest_identity_and_dialogue_only_text() -> None:
    page = _page()
    page["schema_version"] = "1.1"
    page.pop("layout_geometry", None)
    page.pop("continuity_tracks", None)
    panel = copy.deepcopy(page["panels"][0])
    panel["panel_id"] = 1
    panel["subjects"] = [
        {
            "description": "作業台",
            "description_en": "workbench",
            "type": "object",
        }
    ]
    panel["text"] = {
        "dialogue": [{"text_id": "speech-01", "speaker": "kazuki", "content": "確認します。"}],
        "monologue": [{"text_id": "thought-01", "content": "ここから始めよう。"}],
        "narration": [{"text_id": "caption-01", "content": "工房の朝。"}],
        "sfx": [{"text_id": "sound-01", "content": "カチッ"}],
    }
    page["panels"] = [panel]
    plan = compile_page_render_plan(
        page,
        source="step1-pages",
        provider="novelai",
        existing_prompt="baseline page prompt",
        negative_prompt="",
        characters=_characters(),
        prompt_compaction="safe",
    )

    assert [item["type"] for item in plan.text_manifest] == [
        "dialogue",
        "monologue",
        "narration",
        "sfx",
    ]
    assert [item["text_id"] for item in plan.text_manifest] == [
        "speech-01",
        "thought-01",
        "caption-01",
        "sound-01",
    ]
    assert plan.text_manifest[0]["speaker"] == "kazuki"
    assert plan.prompt.count("Text:") == 1
    text_block = plan.prompt.split("Text:", 1)[1]
    assert "確認します。" in text_block
    assert "ここから始めよう。" not in text_block
    assert "工房の朝。" not in text_block
    assert "カチッ" not in text_block

    cues = plan.prompt.split("Panel Text Cues:", 1)[1].split("Text:", 1)[0]
    assert "panel 1 monologue: ここから始めよう。" in cues
    assert "panel 1 narration: 工房の朝。" in cues
    assert "panel 1 sfx: カチッ" in cues
    assert cues.index("monologue") < cues.index("narration") < cues.index("sfx")


def test_schema_1_1_slots_keep_text_out_of_text_block() -> None:
    page = _page()
    plan = compile_page_render_plan(
        page,
        source="step1-pages",
        provider="novelai",
        existing_prompt="baseline page prompt",
        negative_prompt="",
        characters=_characters(),
        prompt_compaction="safe",
    )
    assert plan.character_slots
    assert "Text:" not in plan.prompt
    slot_text = "\n".join(slot["prompt"] for slot in plan.character_slots)
    assert "白い吹き出し「これ、見て。」" in slot_text
