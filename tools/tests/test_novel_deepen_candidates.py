"""深める候補の候補出し（計画 20261121_metron-length-relaxation §17）。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import novel_deepen_candidates as nd  # noqa: E402
from test_metron import _beat, _plan  # noqa: E402

NL = chr(10)

BEAT_TEXTS = {
    "arrive": ["　悠希は桶を道具小屋へ運んだ。", "　やがて湯が沸いた。"],
    "talk": ["「湯は沸きました」", "「桶に移します」", "「棚に戻します」", "　ノラは頁を折った。"],
    "end": ["　悠希は筆を置いた。"],
}


def _work(tmp_path: Path, *, marked: bool = True, weights=("normal", "heavy", "normal")) -> Path:
    work = tmp_path / "novels" / "001_試し"
    (work / "_novel_text").mkdir(parents=True)
    body = ["# 第1章「湯」", ""]
    marked_lines = ["# 第1章「湯」", ""]
    for beat_id, lines in BEAT_TEXTS.items():
        body.extend(lines)
        marked_lines.append(f"<!--beat:{beat_id}-->" + lines[0])
        marked_lines.extend(lines[1:])
        marked_lines.append(f"<!--/beat:{beat_id}-->")
    (work / "_novel_text" / "novel_text01.md").write_text(NL.join(body) + NL, encoding="utf-8")
    scene = work / "_work" / "metron" / "ch01-001"
    scene.mkdir(parents=True)
    plan = _plan(*[_beat(beat_id, chars_hint=40, weight=weight, dialogue_turns=(2, None))
                   for beat_id, weight in zip(BEAT_TEXTS, weights)])
    (scene / "beats.yaml").write_text(yaml.safe_dump(plan.model_dump(mode="json", exclude_none=True),
                                                     allow_unicode=True), encoding="utf-8")
    if marked:
        (scene / "marked.001.md").write_text(NL.join(marked_lines) + NL, encoding="utf-8")
    return work


def test_candidates_are_mapped_to_beats_with_quotes_in_the_text(tmp_path):
    work = _work(tmp_path)
    report = nd.find_candidates(work, 1)
    kinds = {(item.kind, item.beat_id) for item in report.candidates}
    assert (nd.KIND_SUMMARY, "arrive") in kinds
    assert (nd.KIND_SKELETON, "talk") in kinds  # 重い Beat で台詞が3つ続く
    text = (work / "_novel_text" / "novel_text01.md").read_text(encoding="utf-8")
    assert all(item.quote in text for item in report.candidates)
    # 重い Beat を先に並べる
    assert report.candidates[0].beat_id == "talk"


def test_skeleton_is_only_for_heavy_beats_when_beats_are_known(tmp_path):
    work = _work(tmp_path, weights=("normal", "normal", "normal"))
    report = nd.find_candidates(work, 1)
    assert not any(item.kind == nd.KIND_SKELETON for item in report.candidates)


def test_without_a_matching_marked_draft_candidates_have_no_beat(tmp_path):
    work = _work(tmp_path, marked=False)
    report = nd.find_candidates(work, 1)
    assert report.candidates and all(item.beat_id is None for item in report.candidates)
    assert any("印つきの稿が無い" in note for note in report.notes)


def test_non_temporal_markers_and_mid_sentence_sorekara_are_not_summaries():
    assert not nd._has_summary_marker("行はその後の欄へ置かれた。")
    assert not nd._has_summary_marker("エルはきょとんとして、それから笑った。")
    assert nd._has_summary_marker("それから三日が過ぎた。")
    assert nd._has_summary_marker("やがて施術の終局が来た。")


def test_unknown_beat_candidates_are_capped_per_kind(tmp_path):
    work = tmp_path / "novels" / "002_METRONなし"
    (work / "_novel_text").mkdir(parents=True)
    lines = ["　やがて一つ目が来た。", "　やがて二つ目が来た。", "　やがて三つ目が来た。"]
    (work / "_novel_text" / "novel_text01.md").write_text(NL.join(lines) + NL, encoding="utf-8")
    assert len(nd.candidates_for_text(NL.join(lines))) == 3  # 絞り込み前は全部
    report = nd.find_candidates(work, 1)
    summaries = [item for item in report.candidates if item.kind == nd.KIND_SUMMARY]
    assert len(summaries) == nd.UNKNOWN_PER_KIND
    assert any("METRON の場面が無い" in note for note in report.notes)


def test_status_block_is_not_read(tmp_path):
    work = _work(tmp_path)
    path = work / "_novel_text" / "novel_text01.md"
    path.write_text(path.read_text(encoding="utf-8")
                    + NL.join(["<!-- status:begin -->", "やがて能力が上がった。", "<!-- status:end -->"]) + NL,
                    encoding="utf-8")
    report = nd.find_candidates(work, 1)
    assert not any("能力" in item.quote for item in report.candidates)


def test_cli_json_and_missing_chapter(tmp_path, capsys):
    work = _work(tmp_path)
    assert nd.main([str(work), "--chapter", "1", "--json", "--limit", "2"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["chapter"] == 1 and len(payload["candidates"]) <= 2
    assert nd.main([str(work), "--chapter", "9"]) == 2


def _two_scene_work(tmp_path: Path, *, second_marked: bool = True) -> Path:
    """一つの章に二つの場面。どちらも Beat ID は arrive / talk / end（場面の中だけで一意）。"""
    work = tmp_path / "novels" / "003_二場面"
    (work / "_novel_text").mkdir(parents=True)
    scenes = {
        "ch01-001": {"arrive": ["　やがて一つ目の湯が沸いた。悠希は桶を道具小屋へ運び、棚の札を数えた。"],
                     "talk": ["　ノラは頁を折り、返り表の欄を指で押さえてから、桶の名を最初に出した。"],
                     "end": ["　筆を置いた。"]},
        "ch01-002": {"arrive": ["　やがて二つ目の湯が沸いた。ルーベンは炉の口の灰を指でならし、火を見た。"],
                     "talk": ["　悠希は鍋の縁を触り、湯が桶へ溜まるまで、炉の熱が腕に残るのを待った。"],
                     "end": ["　桶を返した。"]},
    }
    body = ["# 第1章「湯」", ""]
    for index, (scene_id, beats) in enumerate(scenes.items()):
        marked = ["# 第1章「湯」", ""] if index == 0 else []
        for beat_id, lines in beats.items():
            body.extend(lines)
            marked.append(f"<!--beat:{beat_id}-->" + lines[0])
            marked.extend(lines[1:])
            marked.append(f"<!--/beat:{beat_id}-->")
        scene = work / "_work" / "metron" / scene_id
        scene.mkdir(parents=True)
        plan = _plan(*[_beat(beat_id, chars_hint=40) for beat_id in beats])
        (scene / "beats.yaml").write_text(yaml.safe_dump(plan.model_dump(mode="json", exclude_none=True),
                                                         allow_unicode=True), encoding="utf-8")
        if index == 0 or second_marked:
            (scene / "marked.001.md").write_text(NL.join(marked) + NL, encoding="utf-8")
    (work / "_novel_text" / "novel_text01.md").write_text(NL.join(body) + NL, encoding="utf-8")
    return work


def test_same_beat_ids_in_two_scenes_are_kept_apart(tmp_path):
    """Codex 6回目の指摘2・3: Beat ID を場面をまたいで重複除去していた／終盤の候補を1場面しか出さなかった。"""
    report = nd.find_candidates(_two_scene_work(tmp_path), 1, limit=20)
    summaries = {(item.scene_id, item.beat_id) for item in report.candidates if item.kind == nd.KIND_SUMMARY}
    assert summaries == {("ch01-001", "arrive"), ("ch01-002", "arrive")}
    endings = {item.scene_id for item in report.candidates if item.kind == nd.KIND_ENDING}
    assert endings == {"ch01-001", "ch01-002"}


def test_unmatched_scene_text_is_still_searched_without_beats(tmp_path):
    """Codex 6回目の指摘1: 一部の場面だけ印つきの稿があると、残りの場面の本文を見ていなかった。"""
    report = nd.find_candidates(_two_scene_work(tmp_path, second_marked=False), 1, limit=20)
    quotes = [item for item in report.candidates if item.kind == nd.KIND_SUMMARY]
    assert any(item.scene_id == "ch01-001" for item in quotes)
    assert any(item.beat_id is None and "二つ目" in item.quote for item in quotes)
    assert any("ch01-002" in note for note in report.notes)
