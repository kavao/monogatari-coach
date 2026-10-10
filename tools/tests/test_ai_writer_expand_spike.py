from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from ai_writer import novelai as nai  # noqa: E402
from ai_writer.expand_spike import (  # noqa: E402
    FIXTURES,
    clean_insertion,
    common_metrics,
    insertion_metrics,
    main,
    rewrite_metrics,
)


def test_fixture_splice_keeps_original_and_places_insertions() -> None:
    fx = FIXTURES[0]
    assert fx.gap_count == 2
    assert fx.splice(["", ""]) == fx.original
    spliced = fx.splice(["Ａ。", "Ｂ。"])
    assert spliced.index("Ａ。") < spliced.index("Ｂ。")
    assert "【ここに挿入】" in fx.marked_for_gap(1)


def test_insertion_metrics_keeps_full_retention_and_flags_next_sentence_copy() -> None:
    fx = FIXTURES[0]
    copy_next = "悠真はベンチの下に手を伸ばし、湿った落ち葉をかき分けた。"
    m = insertion_metrics(fx, [copy_next, "風が冷たかった。"])
    assert m["retention_ratio"] == 1.0
    assert m["per_gap"][0]["next_sentence_jaccard"] == 1.0
    assert m["per_gap"][1]["next_sentence_jaccard"] < 0.5


def test_rewrite_metrics_counts_deleted_modified_and_dialogue() -> None:
    original = "雨が降っていた。\n「待って」\n彼は傘を開いた。"
    candidate = "冷たい雨が降っていた。\n「待ってよ」\n遠くで雷が鳴った。"
    m = rewrite_metrics(original, candidate)
    assert m["retention_ratio"] == 0.0
    assert m["modified_count"] >= 1
    assert m["deleted_count"] >= 1
    assert m["dialogue_preservation"] == 0.0


def test_common_metrics_detects_new_katakana_and_markdown() -> None:
    fx = FIXTURES[0]
    m = common_metrics(fx, fx.original + "**スマートフォン**が鳴った。")
    assert m["new_katakana"] == ["スマートフォン"]
    assert m["markdown"] is True
    assert all(m["names_kept"].values())


def test_clean_insertion_strips_marker_and_space() -> None:
    assert clean_insertion("\n【ここに挿入】風が鳴った。\n") == "風が鳴った。"


def test_run_without_execute_is_dry_run(capsys, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def fail(*_a, **_k):  # type: ignore[no-untyped-def]
        raise AssertionError("dry-run で通信した")

    monkeypatch.setattr(nai, "call_stream", fail)
    monkeypatch.setattr(nai, "load_token", fail)
    assert main(["run"]) == 0
    out = capsys.readouterr().out
    assert "生成 40 回" in out


def test_clean_insertion_drops_cut_off_tail() -> None:
    assert clean_insertion("風が鳴った。遠くで踏切が") == "風が鳴った。"
    assert clean_insertion("途中で切れた") == "途中で切れた"


def test_insertion_budget_matches_rewrite_ratio() -> None:
    for fx in FIXTURES:
        assert abs(fx.insert_chars_per_gap * fx.gap_count - len(fx.original) * 0.5) <= fx.gap_count


def test_clean_insertion_keeps_first_paragraph_only() -> None:
    raw = "\n陽太は照れくさそうに微笑んだ。\n***\n[採点結果]\n・合計評価: A\n"
    assert clean_insertion(raw) == "陽太は照れくさそうに微笑んだ。"


def test_clean_rewrite_cuts_trailer() -> None:
    from ai_writer.expand_spike import clean_rewrite

    raw = "\n　本文一。\n　本文二。\n***\n[ Style: チャット ]\n[21:54]　黒鷹：お疲れ様です\n"
    assert clean_rewrite(raw) == "　本文一。\n　本文二。"


def test_cut_trailer_cuts_translation_block() -> None:
    from ai_writer.expand_spike import cut_trailer

    raw = "本文の最後。\n【中文翻译】\n夜晚的旧教学楼"
    assert cut_trailer(raw) == "本文の最後。\n"
