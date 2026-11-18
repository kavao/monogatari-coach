#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import novel_beat_intent_check as nbic  # noqa: E402

BEATS = """generation:
  granularity: auto
  chars_floor: 600
beats:
  - id: a_look
    type: action
    intent: 悠希が桶を二か所に置き、翌朝に手を入れて温度を比べる
    budget: {paragraphs: [2, 4], dialogue_turns: [0, 2], sensory: 1, interiority: 1, new_facts: 1, chars_hint: 300}
  - id: b_know
    type: action
    intent: 悠希が炉だけでは風呂にならないと分かる
    budget: {paragraphs: [2, 4], dialogue_turns: [0, 2], sensory: 1, interiority: 1, new_facts: 1, chars_hint: 300}
  - id: c_say
    type: dialogue
    intent: ノラが桶が足りないと口にする。ノラは知らせを持って来た
    budget: {paragraphs: [2, 4], dialogue_turns: [1, 3], sensory: 1, interiority: 1, new_facts: 1, chars_hint: 300}
"""


def _work(tmp_path: Path) -> Path:
    work = tmp_path / "998_湯"
    scene = work / "_work" / "metron" / "ch01-001"
    scene.mkdir(parents=True)
    (scene / "beats.yaml").write_text(BEATS, encoding="utf-8")
    return work


def test_find_cognitive_verbs_skips_lookalikes() -> None:
    assert nbic.find_cognitive_verbs("村人が知らせを受け、道が分かれる") == []
    assert nbic.find_cognitive_verbs("湯が立ったと知る") == ["知る"]
    assert nbic.find_cognitive_verbs("足りないと口にし、置き場がないと気づく") == ["口にし", "気づく"]


def test_check_novel_reports_beats_with_cognitive_verbs(tmp_path: Path) -> None:
    report = nbic.check_novel(_work(tmp_path))

    assert report.scenes == ["ch01-001"]
    assert report.beat_count == 3
    assert [(f.beat_id, f.word) for f in report.findings] == [("b_know", "分かる"), ("c_say", "口にす")]
    assert report.findings[0].beats_path == "_work/metron/ch01-001/beats.yaml"


def test_ignore_removes_beat_and_cli_is_advisory(tmp_path: Path, capsys) -> None:
    work = _work(tmp_path)
    before = {p: p.read_bytes() for p in work.rglob("*") if p.is_file()}

    assert nbic.main([str(work), "--ignore", "ch01-001/b_know", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert [f["beat_id"] for f in payload["findings"]] == ["c_say"]
    assert payload["ignored"] == ["ch01-001/b_know"]
    assert {p: p.read_bytes() for p in work.rglob("*") if p.is_file()} == before


def test_missing_work_returns_2(tmp_path: Path) -> None:
    assert nbic.main([str(tmp_path / "none")]) == 2
