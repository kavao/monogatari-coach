from __future__ import annotations

import sys
from pathlib import Path

_TOOLS_ROOT = Path(__file__).resolve().parents[2]
if str(_TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(_TOOLS_ROOT))

from image_provider_novel_manga_batch import (  # noqa: E402
    yaml_page_step1_text,
    yaml_page_step2_text,
)


def _page() -> dict:
    return {
        "meta": {"reading_order": "right_to_left"},
        "manga": {"panel_layout": "2 panels"},
        "scene": {},
        "panels": [
            {
                "panel_id": 1,
                "summary": "主人公が工房で確認する。",
                "composition": {"layout": "large panel"},
                "text": {
                    "dialogue": [{"speaker": "主人公", "content": "確認します。"}],
                    "monologue": [{"content": "ここから始めよう。"}],
                    "narration": [{"content": "工房の朝。"}],
                    "sfx": [{"content": "カチッ", "meaning": "道具を操作する音"}],
                },
            }
        ],
    }


def test_step2_can_embed_yaml_text_elements_for_grok_legacy_prompt() -> None:
    prompt = yaml_page_step2_text(
        _page(),
        1,
        {},
        include_text_elements=True,
    )

    assert "文字要素（YAMLのtextをそのまま反映）:" in prompt
    assert "- セリフ: 主人公「確認します。」" in prompt
    assert "- モノローグ: ここから始めよう。" in prompt
    assert "- ナレーション: 工房の朝。" in prompt
    assert "- 効果音: カチッ（道具を操作する音）" in prompt


def test_page_text_elements_can_be_omitted_for_letter_later() -> None:
    page = _page()

    step1_prompt = yaml_page_step1_text(
        page,
        {},
        1,
        include_text_elements=False,
    )
    step2_prompt = yaml_page_step2_text(
        page,
        1,
        {},
        include_text_elements=False,
    )

    assert "確認します。" not in step1_prompt
    assert "確認します。" not in step2_prompt
    assert "カチッ" not in step1_prompt
    assert "カチッ" not in step2_prompt
