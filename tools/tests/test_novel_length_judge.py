from __future__ import annotations

import shutil

import pytest

from test_writing_bridge import FIXTURE
from novel_length_judge import judge_chapter, main, parse_target


@pytest.mark.parametrize(("value", "expected"), [
    ("8,000字", 8000),
    ("8,000字以上", 8000),
    ("４０００字程度", 4000),
    ("4,000〜8,000文字程度", 4000),
    ("4,000字〜8,000字", 4000),
    ("約8000字", None),
    ("章ごとに調整", None),
    ("8000字未満", None),
    ("8000字（未満）", None),
    ("8000字前後", 8000),
    ("8000〜", None),
    ("8,000字以上（初稿は 7,983字）", 8000),
])
def test_target_value_reading(value, expected):
    assert parse_target(value) == expected


def _work(tmp_path, body_chars: int, design: str | None):
    work = tmp_path / "000_trip"
    (work / "_novel_text").mkdir(parents=True)
    body = "# 第一章\n\n" + "あ" * body_chars + "\n\n<!-- status:begin -->\n- 体力 9/10\n<!-- status:end -->\n"
    (work / "_novel_text" / "novel_text01.md").write_text(body, encoding="utf-8")
    if design is not None:
        (work / "design_specification.md").write_text(design, encoding="utf-8")
    return work


DESIGN = "## 章構成\n\n### 第1章　駅まで\n\n**分量目安**: 1,000字\n\n1. 母が鍵を確かめる。\n"


# 見出しと改行で 8 字。合計がちょうど 900（ok の下限）・860（reported）・849（below）になる。
@pytest.mark.parametrize(("chars", "status", "complete"), [
    (892, "ok", True), (852, "reported", True), (841, "below", False),
])
def test_chapter_target_tolerance_and_report_band(tmp_path, chars, status, complete):
    result = judge_chapter(_work(tmp_path, chars, DESIGN), 1)
    # 章末ステータスのブロック（「体力 9/10」など）は数えない。見出しと改行の 8 字は数える。
    assert result.chars == chars + 8
    assert result.target == 1000 and result.target_source == "設計の分量目安"
    assert result.target_status == status and result.complete is complete


def test_unreadable_target_is_on_hold_and_explicit_target_wins(tmp_path):
    work = _work(tmp_path, 500, DESIGN.replace("1,000字", "約千字"))
    held = judge_chapter(work, 1)
    assert held.target is None and held.target_source.startswith("保留") and held.target_status == "保留"
    # 目標も場面の床も無ければ、完了ではなく保留
    assert not held.judged and not held.complete
    assert main([str(work), "--chapter", "1"]) == 3
    explicit = judge_chapter(work, 1, target=2000)
    assert explicit.target_source == "明示" and explicit.target_status == "below" and not explicit.complete


def test_scene_floors_use_the_relaxed_floor(tmp_path):
    work = _work(tmp_path, 3700, None)
    shutil.copytree(FIXTURE / "ok_ch01_001" / "work" / "_metron", work / "_metron")
    result = judge_chapter(work, 1)
    assert result.floor_total is not None
    assert result.floor_status == ("ok" if result.chars >= result.floor_total else "below")


def test_cli_exit_codes(tmp_path, capsys):
    assert main([str(_work(tmp_path / "a", 892, DESIGN)), "--chapter", "1"]) == 0
    assert main([str(_work(tmp_path / "b", 800, DESIGN)), "--chapter", "1"]) == 1
    assert main([str(_work(tmp_path / "c", 800, DESIGN)), "--chapter", "2"]) == 2


def test_undecodable_design_is_on_hold_not_a_crash(tmp_path):
    work = _work(tmp_path, 500, None)
    (work / "design_specification.md").write_bytes(b"\xff\xfe\x00broken")
    result = judge_chapter(work, 1)
    assert result.target_status == "保留" and any("設計書を読めない" in note for note in result.notes)


def test_unreadable_scene_beats_put_the_floor_on_hold(tmp_path):
    work = _work(tmp_path, 3700, None)
    shutil.copytree(FIXTURE / "ok_ch01_001" / "work" / "_metron", work / "_metron")
    shutil.copytree(work / "_metron" / "ch01-001", work / "_metron" / "ch01-002")
    (work / "_metron" / "ch01-002" / "beats.yaml").write_text("generation: [", encoding="utf-8")
    result = judge_chapter(work, 1)
    assert result.floor_status == "保留" and not result.judged and not result.complete
    assert any("ch01-002" in note for note in result.notes)
    assert main([str(work), "--chapter", "1"]) == 3


def test_undecodable_body_is_an_error_not_a_traceback(tmp_path):
    work = _work(tmp_path, 500, DESIGN)
    (work / "_novel_text" / "novel_text01_2.md").write_bytes(b"\xff\xfebroken")
    assert main([str(work), "--chapter", "1"]) == 2


def test_other_headings_end_the_chapter_section(tmp_path):
    design = DESIGN.replace("**分量目安**: 1,000字\n", "") + "\n# 付録\n\n**分量目安**: 8000字\n"
    result = judge_chapter(_work(tmp_path, 500, design), 1)
    assert result.target is None and result.target_source == "なし"


def test_unreadable_body_path_is_an_error(tmp_path):
    work = _work(tmp_path, 500, DESIGN)
    (work / "_novel_text" / "novel_text01_3.md").mkdir()
    assert main([str(work), "--chapter", "1"]) == 2
