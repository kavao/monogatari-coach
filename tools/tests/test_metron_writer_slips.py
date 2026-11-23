"""書き手の稿の崩れの補助の印（計画 §16.6）と、§16.4・§16.5 の指示の文面。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from metron.writer_slips import detect_slips, is_third_person, new_slips  # noqa: E402


def test_instruction_leak_and_intent_copy():
    intent = "村人は初めて湯に浸かり、悠希は個人の風呂は立たないと知る"
    text = ("　村人は初めて湯に浸かり、悠希は個人の風呂は立たないと知る。\n"
            "　ノラの内心は短くする方針に従い、彼女は筆を置いた。\n")
    slips = detect_slips(text, intent=intent)
    assert any(item.startswith("作業指示の漏れ") for item in slips)
    assert any(item.startswith("意図の写し") for item in slips)


def test_duplicated_sentence_even_when_paragraph_heads_differ():
    long = "悠希は自分の風呂を村の洗い物の順に回すか自分の湯だけ残すか迷った。"
    text = f"　ノラの声は棚の隙間へ沈んだ。{long}\n　ノラの言葉は短かった。{long}\n"
    assert any(item.startswith("文の二重書き") for item in detect_slips(text))


def test_honorific_and_first_person_only_in_narration():
    text = ("　ノラさんが筆を置いた。俺は桶を見た。\n"
            "「ノラさん、俺が運びます」\n"
            "　私人の風呂は立たない。\n")
    slips = detect_slips(text, third_person=True)
    assert "地の文の敬称: 「ノラさん」" in slips
    assert sum(item.startswith("視点の崩れ") for item in slips) == 1  # 会話の「俺」と「私人」は数えない
    assert not any(item.startswith("視点の崩れ") for item in detect_slips(text, third_person=False))


def test_new_slips_skip_marks_already_in_the_original():
    original = "　ノラさんが筆を置いた。\n"
    candidate = "　ノラさんが筆を置いた。ルーベンさんは炭を数えた。\n"
    assert new_slips(original, candidate) == ["地の文の敬称: 「ルーベンさん」"]


def test_clean_text_has_no_marks():
    text = "　悠希は桶を棚へ返した。取っ手にはまだ湯の温みが残っていた。\n「湯を棚に返します」\n"
    assert detect_slips(text, intent="悠希が桶を棚へ返す", third_person=True) == []


def test_third_person_reading_of_config():
    assert is_third_person("- 作家は 000。近距離三人称。")
    assert not is_third_person("- 一人称。三人称の章は無い。")
    assert not is_third_person("")


def test_intent_only_fill_prompt_drops_new_facts():
    from test_metron import _beat
    from metron.prompt import build_beat_prompt

    beat = _beat("a", chars_hint=10)
    beat.budget.new_facts = 2
    plain = build_beat_prompt(beat)
    assert "新規事実を 2 件導入する" in plain
    fill = build_beat_prompt(beat, include_new_facts=False, intent_only=True)
    assert "新規事実を" not in fill
    assert "意図にない事実・出来事は足さない" in fill


def test_length_fill_uses_intent_only_prompt_only_for_new_sessions():
    from test_length_phase4 import _missing_session, _recap_state
    from metron.models import LengthTarget
    from metron.repair_steps import next_job

    old = _missing_session(max_passes=1)
    assert "意図にない事実" not in next_job(old).prompt
    state = _recap_state(LengthTarget(target_chars=300))
    state.length.fill_intent_only = True
    job = next_job(state)
    assert job.operation == "regenerate" and "意図にない事実・出来事は足さない" in job.prompt


def test_new_slips_ignore_existing_leaks_when_nearby_text_changes():
    """Codex 2回目の指摘: 抜粋の一致で除いていたため、近くに言葉が足されると再報告していた。"""
    assert new_slips("　ノラは方針に従う", "　ノラは方針に従う。") == []
    assert new_slips("　ノラは方針に従い、筆を置いた。",
                     "　ノラは方針に従い、静かに筆を置いた。湯気が立った。") == []
    # 同じ語が新しくもう一度出たときは報告する
    again = new_slips("　ノラは方針に従い、筆を置いた。",
                      "　ノラは方針に従い、筆を置いた。悠希も方針に従った。")
    assert len(again) == 1 and again[0].startswith("作業指示の漏れ")
    assert new_slips("　ノラさんが来た。", "　ノラさんが来た。湯が沸いた。ノラさんが笑った。") == ["地の文の敬称: 「ノラさん」"]


def test_new_slips_are_counted_per_group_not_by_position():
    """Codex 3回目の指摘: 「私的」の私を数えていた／前に挿入すると既存の印の番号がずれていた。"""
    assert new_slips("　私は桶を見た。", "　私的な記録を確認し、私は桶を見た。", third_person=True) == []
    inserted = new_slips("　ノラは方針に従い、筆を置いた。",
                         "　悠希は方針に従った。ノラは方針に従い、筆を置いた。")
    assert len(inserted) == 1 and "悠希は方針に従った" in inserted[0]


def test_new_slip_is_the_inserted_one_even_when_it_comes_after():
    inserted = new_slips("　ノラは方針に従い、筆を置いた。",
                         "　ノラは方針に従い、筆を置いた。悠希は方針に従った。")
    assert len(inserted) == 1 and "悠希は方針に従った" in inserted[0]


def test_identical_new_marks_keep_their_count():
    """Codex 4回目の指摘: 同じ表示の新しい印が重複除去で1件になっていた。"""
    chunk = "　abcdefgh方針に従1234567890123456。"
    marks = new_slips("", chunk + chunk)
    leaks = [item for item in marks if item.startswith("作業指示の漏れ")]
    assert len(leaks) == 1 and leaks[0].endswith("（2件）")
    assert any(item.startswith("文の二重書き") for item in marks)  # 同じ文が二度あるので
    assert new_slips("", "　ノラさんが来た。ノラさんが笑った。") == ["地の文の敬称: 「ノラさん」（2件）"]


def test_detect_slips_also_keeps_the_count():
    """Codex 5回目の指摘: detect_slips だけ件数を落としていた。"""
    assert detect_slips("　ノラさんが来た。ノラさんが笑った。") == ["地の文の敬称: 「ノラさん」（2件）"]
