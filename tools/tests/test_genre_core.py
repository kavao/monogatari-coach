"""ジャンルの芯（genre 葉の「起草での芯」）を Beat ごとに選び分ける（計画 20261124_genre-core-notes §4.2）。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import novel_beat_draft as nbd  # noqa: E402
from metron.models import Beat  # noqa: E402
from writing_bridge.context_build import (  # noqa: E402
    CORE_ALWAYS,
    extract_core_lines,
    extract_usage_notes,
    render_context_md,
    select_core_lines,
)
from writing_bridge.models import ContextDocument  # noqa: E402

LEAF = """# 葉

## Monogatari Coach での使い方

企画で読む段落。

### 起草での芯

<!-- 追加の日付 -->
context_usage:
芯の使い方: 当たる項だけを使う。
見せ場: 工夫の場面では、不便から驚きまで。
関係: 人物どうしの場面では、行いで深める。
避けること: どの場面でも、報告で済ませない。

### 起草での注意

context_usage:
別の使い方の段落。

## 0. 本文

本文の段落。
"""


def _budget() -> dict:
    return {
        "paragraphs": [2, 6],
        "dialogue_turns": [0, 3],
        "sensory": 1,
        "interiority": 1,
        "new_facts": 1,
        "chars_hint": 300,
    }


def test_beat_core_optional_and_validated() -> None:
    base = {"id": "b1", "type": "action", "intent": "修が石を並べる", "budget": _budget()}
    assert Beat.model_validate(base).core is None
    assert Beat.model_validate({**base, "core": []}).core == []
    assert Beat.model_validate({**base, "core": [" 見せ場 ", "驚き"]}).core == ["見せ場", "驚き"]
    with pytest.raises(ValidationError):
        Beat.model_validate({**base, "core": ["見せ場", "見せ場"]})
    with pytest.raises(ValidationError):
        Beat.model_validate({**base, "core": ["  "]})


def test_core_lines_are_split_from_usage_notes() -> None:
    lines = extract_core_lines(LEAF)
    assert [line["label"] for line in lines] == ["芯の使い方", "見せ場", "関係", "避けること"]
    assert lines[1]["text"].startswith("見せ場: 工夫の場面では")
    notes = extract_usage_notes(LEAF)
    assert notes == ["別の使い方の段落。"]
    assert not any("見せ場" in note for note in notes)


def test_select_core_lines() -> None:
    lines = extract_core_lines(LEAF)
    assert select_core_lines(lines, None) == lines
    assert [line["label"] for line in select_core_lines(lines, [])] == list(CORE_ALWAYS)
    assert [line["label"] for line in select_core_lines(lines, ["関係"])] == ["芯の使い方", "関係", "避けること"]


def _context(beats: list[dict]) -> ContextDocument:
    return ContextDocument(
        schema=1,
        request_id="WRQ-0001",
        run_id="run-0001",
        input_hashes=[],
        beats=beats,
        core_lines=extract_core_lines(LEAF),
    )


def test_render_context_shows_core_per_beat() -> None:
    beats = [
        {"id": "b1", "intent": "工夫を見せる", "chars_hint": 300, "chars_instruction": 420, "core": ["見せ場"]},
        {"id": "b2", "intent": "眠れない夜", "chars_hint": 300, "chars_instruction": 420, "core": []},
        {"id": "b3", "intent": "欄なし", "chars_hint": 300, "chars_instruction": 420, "core": None},
        {"id": "b4", "intent": "名前違い", "chars_hint": 300, "chars_instruction": 420, "core": ["称賛"]},
    ]
    text = render_context_md(_context(beats))
    assert "ジャンルの芯" in text
    assert "- 見せ場: 工夫の場面では" in text
    lines = {line.split(":")[0]: line for line in text.splitlines() if line.startswith("- beat ")}
    assert "芯: 見せ場" in lines["- beat b1"]
    assert "芯: 使わない" in lines["- beat b2"]
    assert "芯:" not in lines["- beat b3"]
    assert "称賛（芯に無い項）" in lines["- beat b4"]


def test_render_context_without_core_lines_is_unchanged() -> None:
    context = ContextDocument(
        schema=1,
        request_id="WRQ-0001",
        run_id="run-0001",
        input_hashes=[],
        beats=[{"id": "b1", "intent": "工夫", "chars_hint": 300, "chars_instruction": 420, "core": ["見せ場"]}],
    )
    text = render_context_md(context)
    assert "ジャンルの芯" not in text
    assert "芯:" not in text


def test_beat_prompt_passes_only_selected_core_lines(tmp_path: Path) -> None:
    materials = nbd.Materials(
        work=tmp_path,
        chapter=1,
        title_line="# 第1章",
        forbidden=[],
        character_md="",
        parts_before_characters=[],
        parts_after_characters=[],
    )
    core = extract_core_lines(LEAF)
    beat = {"id": "b1", "intent": "人物どうしの場面", "core": ["関係"]}
    prompt = nbd.beat_prompt(materials, set(), "", beat, 300, True, craft_notes=["表現の助言。"], core_lines=core)
    assert "- 表現の助言。" in prompt
    assert "- 関係: 人物どうしの場面では" in prompt
    assert "- 芯の使い方:" in prompt and "- 避けること:" in prompt
    assert "見せ場:" not in prompt
    quiet = nbd.beat_prompt(materials, set(), "", {"id": "b2", "intent": "夜", "core": []}, 300, True, core_lines=core)
    assert "関係:" not in quiet and "見せ場:" not in quiet and "芯の使い方:" in quiet
    every = nbd.beat_prompt(materials, set(), "", {"id": "b3", "intent": "欄なし"}, 300, True, core_lines=core)
    assert "見せ場:" in every and "関係:" in every


def test_isekai_craft_leaf_has_core_section() -> None:
    text = (ROOT / "_how_to.example" / "genre" / "isekai_craft.md").read_text(encoding="utf-8")
    labels = [line["label"] for line in extract_core_lines(text)]
    assert labels == ["芯の使い方", "見せ場", "説明の仕方", "驚き", "現地の技", "関係", "避けること"]
    assert not any(note.startswith(("見せ場", "芯の使い方")) for note in extract_usage_notes(text))


def test_unlabeled_or_long_label_lines_are_not_dropped() -> None:
    leaf = """## 使い方

### 起草での芯

context_usage:
芯の使い方: 当たる項だけを使う。
主人公が自分以外の技術に驚いて見入る場面: 見入る側に回る。
名前の無い行。どの Beat にも載る。
"""
    lines = extract_core_lines(leaf)
    assert [line["label"] for line in lines] == ["芯の使い方", "主人公が自分以外の技術に驚いて見入る場面", ""]
    chosen = select_core_lines(lines, ["主人公が自分以外の技術に驚いて見入る場面"])
    assert len(chosen) == 3
    assert [line["text"] for line in select_core_lines(lines, [])] == ["芯の使い方: 当たる項だけを使う。", "名前の無い行。どの Beat にも載る。"]
