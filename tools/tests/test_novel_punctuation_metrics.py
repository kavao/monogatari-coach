#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from novel_punctuation_metrics import (  # noqa: E402
    GATE_MIN_NARRATION_CHARS,
    evaluate_gate,
    extract_body,
    iter_sentences,
    measure_text,
    merge_metrics,
    split_narration_dialogue,
)


def _pad_narration(sentence: str, minimum: int = GATE_MIN_NARRATION_CHARS) -> str:
    parts = [sentence]
    while sum(len(part) for part in parts) < minimum:
        parts.append(sentence)
    return "".join(parts)


def test_split_keeps_nested_quotes_inside_dialogue() -> None:
    narration, dialogues = split_narration_dialogue(
        "地の文。「外『内』続き」また地の文。"
    )
    assert narration == "地の文。また地の文。"
    assert dialogues == ["外『内』続き"]


def test_extract_body_drops_heading_and_front_matter() -> None:
    text = "---\ntitle: x\n---\n# 第1章\n　本文である。\n"
    assert extract_body(text) == "　本文である。"


def test_iter_sentences_splits_on_japanese_terminators() -> None:
    sentences = iter_sentences("短い。長い文だ！終わり？残り")
    assert sentences == ["短い。", "長い文だ！", "終わり？", "残り"]


def test_measure_text_density_and_conjunction_rate() -> None:
    text = (
        "　彼は窓を開けて、風を入れて、それから椅子に座った。\n"
        "「そうね。私たちなら大丈夫」\n"
        "　雨が、屋根を叩いていた。\n"
    )
    metrics = measure_text(text)
    assert metrics["comma_narration"] == 3
    assert metrics["chars_narration"] > 0
    expected = 3 / metrics["chars_narration"] * 1000
    assert metrics["comma_density_narration"] == expected
    assert metrics["conjunction_after_comma_count"] == 3
    assert metrics["period_before_close"] == 0
    assert metrics["period_inside_dialogue"] == 1
    assert metrics["commas_per_sentence"]["max"] == 2


def test_measure_text_counts_trailing_period_before_close() -> None:
    metrics = measure_text("　彼は言った。\n「こんにちは。」\n")
    assert metrics["period_before_close"] == 1
    assert metrics["period_inside_dialogue"] == 1


def test_merge_metrics_pools_sentence_commas() -> None:
    first = measure_text("　短い。\n")
    second = measure_text("　長く、長く、長く、続く文である。\n")
    merged = merge_metrics([first, second], label="合計")
    assert merged["file_count"] == 2
    assert merged["comma_narration"] == 3
    assert merged["commas_per_sentence"]["max"] == 3
    assert merged["commas_per_sentence"]["median"] == 1.5


def test_cli_json_omits_private_keys(tmp_path: Path, monkeypatch) -> None:
    novel = tmp_path / "novels" / "001_demo" / "_novel_text"
    novel.mkdir(parents=True)
    (novel / "novel_text01.md").write_text("　彼は歩き、止まって、見た。\n", encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "novel_punctuation_metrics.py",
            str(novel.parent),
            "--json",
            "--repo-root",
            str(tmp_path),
        ],
    )
    from novel_punctuation_metrics import main

    monkeypatch.chdir(tmp_path)
    # repo_root は novels の親である必要がある
    import io
    from contextlib import redirect_stdout

    buf = io.StringIO()
    with redirect_stdout(buf):
        code = main()
    assert code == 0
    payload = json.loads(buf.getvalue())
    assert "totals" in payload
    assert payload["totals"]["comma_narration"] == 2
    assert not any(key.startswith("_") for key in payload["files"][0])


def test_evaluate_gate_fails_short_high_density() -> None:
    text = _pad_narration("　朝の光は、白い。身体は、軽い。")
    result = evaluate_gate(measure_text(text))
    assert result["status"] == "fail"
    assert result["comma_density_narration"] > 36
    assert result["sentence_mean_len_narration"] < 28


def test_evaluate_gate_passes_long_sentences_even_with_commas() -> None:
    sentence = (
        "　東向きの窓から差し込む朝の光は、昨夜の薄い間接照明とは対照的に白く澄み、"
        "カーテンの端を伝って床まで届いた涼しさが時計の針と重なって部屋を開いていた。"
    )
    result = evaluate_gate(measure_text(_pad_narration(sentence)))
    assert result["status"] == "pass"
    assert result["sentence_mean_len_narration"] >= 28


def test_evaluate_gate_passes_short_sentences_with_low_density() -> None:
    result = evaluate_gate(measure_text(_pad_narration("　朝の光は白い。身体は軽い。")))
    assert result["status"] == "pass"
    assert result["comma_density_narration"] <= 36


def test_evaluate_gate_skips_short_narration() -> None:
    result = evaluate_gate(measure_text("　朝の光は、白い。"))
    assert result["status"] == "skip"


def test_cli_gate_fails_on_short_high_density(tmp_path: Path, monkeypatch) -> None:
    novel = tmp_path / "novels" / "001_demo" / "_novel_text"
    novel.mkdir(parents=True)
    (novel / "novel_text01.md").write_text(
        _pad_narration("　朝の光は、白い。身体は、軽い。"),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "novel_punctuation_metrics.py",
            str(novel / "novel_text01.md"),
            "--gate",
            "--repo-root",
            str(tmp_path),
        ],
    )
    from novel_punctuation_metrics import main

    monkeypatch.chdir(tmp_path)
    assert main() == 1
