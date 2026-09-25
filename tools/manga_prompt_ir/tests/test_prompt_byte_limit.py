from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

_TOOLS_ROOT = Path(__file__).resolve().parents[2]
if str(_TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(_TOOLS_ROOT))

from image_provider_novel_manga_batch import (  # noqa: E402
    iter_yaml_manga_jobs,
    trim_prompt_to_byte_limit,
)
from manga_prompt_ir.page_render_plan import PageRenderPlanError  # noqa: E402


def _page_text_contents(page: dict) -> list[str]:
    contents: list[str] = []
    for panel in page.get("panels") or []:
        if not isinstance(panel, dict):
            continue
        text = panel.get("text") or {}
        if not isinstance(text, dict):
            continue
        for kind in ("dialogue", "monologue", "narration", "sfx"):
            for item in text.get(kind) or []:
                if isinstance(item, dict):
                    content = str(item.get("content") or "").strip()
                else:
                    content = str(item).strip()
                if content:
                    contents.append(content)
    return contents


def test_trim_drops_tags_before_lettering() -> None:
    tags = "- tag: " + ",".join(["token"] * 400)
    lettering = "- セリフ: 結「最後まで残る。」"
    prompt = f"Page 1\n{tags}\n{lettering}\n"
    assert len(prompt.encode("utf-8")) > 400
    trimmed = trim_prompt_to_byte_limit(prompt, 400)
    assert "最後まで残る。" in trimmed
    assert "- tag:" not in trimmed
    assert "[...省略]" not in trimmed
    assert len(trimmed.encode("utf-8")) <= 400


def test_trim_keeps_compiler_text_block() -> None:
    tags = "- tag: " + ",".join(["token"] * 400)
    prompt = (
        f"Source Page Instructions:\n{tags}\n\n"
        "Text:\n- panel 1 dialogue (speaker=aydan): 残す台詞\n"
    )
    trimmed = trim_prompt_to_byte_limit(prompt, 500)
    assert "残す台詞" in trimmed
    assert "Text:" in trimmed
    assert "- tag:" not in trimmed


def test_trim_raises_when_lettering_alone_exceeds_limit() -> None:
    prompt = "- セリフ: " + ("あ" * 200)
    with pytest.raises(PageRenderPlanError, match="文字要素は省略しません"):
        trim_prompt_to_byte_limit(prompt, 40)


def test_trim_may_cut_tail_when_lettering_is_not_required() -> None:
    prompt = "\n".join(f"line-{index:03d} " + ("x" * 40) for index in range(40))
    trimmed = trim_prompt_to_byte_limit(prompt, 200, preserve_lettering=False)
    assert len(trimmed.encode("utf-8")) <= 220
    assert "[...省略]" in trimmed


def test_098_grok_page_render_plan_fits_and_keeps_lettering() -> None:
    novel_dir = _TOOLS_ROOT.parent / "novels" / "辺境工房の魔導リノベーション"
    # folder is 098_...
    novels = _TOOLS_ROOT.parent / "novels"
    matches = list(novels.glob("098_*"))
    if not matches:
        pytest.skip("098 作品フォルダがありません")
    novel_dir = matches[0]
    jobs = iter_yaml_manga_jobs(
        novel_dir,
        "manga_01",
        "step1-pages",
        "grok",
        None,
        cli_negative_prompt="",
        prompt_formatter="manga_page_instruction",
        page_compiler="page_render_plan",
    )
    assert len(jobs) == 12
    pages_dir = novel_dir / "manga" / "pages"
    for job in jobs:
        prompt = str(job["prompt"])
        assert len(prompt.encode("utf-8")) <= 7800
        page_num = int(job["page"])
        page = yaml.safe_load(
            (pages_dir / f"manga_01_p{page_num:02d}.yaml").read_text(encoding="utf-8")
        )
        missing = [item for item in _page_text_contents(page) if item not in prompt]
        assert not missing, f"p{page_num:02d} missing {missing}"
