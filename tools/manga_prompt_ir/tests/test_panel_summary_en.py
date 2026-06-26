"""Tests for panels[].summary_en translation helpers and tag merge."""

from __future__ import annotations

import sys
from pathlib import Path

_TOOLS = Path(__file__).resolve().parents[2]
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

from image_provider_novel_manga_batch import (  # noqa: E402
    yaml_panel_tags,
    yaml_panel_tags_novelai_split,
)
from manga_prompt_ir.summary_en import (  # noqa: E402
    needs_summary_en_translation,
    panel_summary_en_tag_tokens,
    parse_translate_response,
    sanitize_summary_en_for_tags,
    summary_en_is_stale,
    summary_en_quality_issues,
)


def test_panel_summary_en_tag_tokens_in_base() -> None:
    panel = {
        "summary": "湯気の中、悠真。",
        "summary_en": "Yuma relaxes alone in soft steam.",
        "prompt_tags": ["bathroom", "steam"],
    }
    page = {"manga": {}, "scene": {}, "panels": [panel]}
    base, _ = yaml_panel_tags_novelai_split(
        page,
        panel,
        {},
        include_panel_summary=True,
    )
    joined = ", ".join(base)
    assert "Yuma relaxes alone in soft steam" in joined
    assert "bathroom" in joined
    idx_en = joined.index("Yuma")
    idx_tag = joined.index("bathroom")
    assert idx_en < idx_tag


def test_include_panel_summary_off_skips() -> None:
    panel = {"summary_en": "Yuma in steam.", "prompt_tags": ["steam"]}
    page = {"manga": {}, "scene": {}}
    tags = yaml_panel_tags(page, panel, {}, include_panel_summary=False)
    assert "Yuma in steam" not in ", ".join(tags)


def test_sanitize_removes_pipe() -> None:
    assert "|" not in sanitize_summary_en_for_tags("foo | bar")


def test_needs_translation_when_stale() -> None:
    panel = {
        "summary": "新しい要約",
        "summary_en": "old english",
        "summary_en_source": "古い要約",
    }
    assert needs_summary_en_translation(panel) is True
    assert summary_en_is_stale(panel) is True


def test_parse_translate_response() -> None:
    raw = '[{"panel_id": 1, "summary_en": "Yuma rests."}, {"panel_id": 2, "summary_en": "Miu enters."}]'
    out = parse_translate_response(raw, [1, 2])
    assert out[1] == "Yuma rests."
    assert out[2] == "Miu enters."


def test_quality_strict_missing_summary_en() -> None:
    panel = {"summary": "日本語のみ"}
    warn, err = summary_en_quality_issues(
        panel,
        panel_label="p1",
        require_for_manga=True,
        strict=True,
    )
    assert warn == []
    assert len(err) == 1
    assert "エージェントが summary_en" in err[0]


def test_quality_warns_pipe_in_summary_en() -> None:
    panel = {
        "summary": "蓮がつぼみを慰める。",
        "summary_en": "Ren comforts | Tsubomi.",
        "summary_en_source": "蓮がつぼみを慰める。",
    }
    warn, err = summary_en_quality_issues(
        panel,
        panel_label="p1",
        require_for_manga=True,
        strict=False,
    )
    assert err == []
    assert any("パイプ" in w for w in warn)


def test_quality_warns_long_summary_en() -> None:
    long_en = "word " * 60  # 300 chars
    panel = {
        "summary": "長いシーン。",
        "summary_en": long_en.strip(),
        "summary_en_source": "長いシーン。",
    }
    warn, err = summary_en_quality_issues(
        panel,
        panel_label="p1",
        require_for_manga=True,
        strict=False,
    )
    assert err == []
    assert any("長すぎます" in w for w in warn)


def test_quality_strict_missing_summary_en_source() -> None:
    panel = {
        "summary": "蓮がつぼみを慰める。",
        "summary_en": "Ren gently comforts Tsubomi at the table.",
    }
    warn, err = summary_en_quality_issues(
        panel,
        panel_label="p1",
        require_for_manga=True,
        strict=True,
    )
    assert warn == []
    assert len(err) == 1
    assert "summary_en_source が未設定" in err[0]
