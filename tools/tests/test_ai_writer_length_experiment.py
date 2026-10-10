from __future__ import annotations

import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from ai_writer import length_experiment as le  # noqa: E402
from ai_writer import novelai as nai  # noqa: E402
from ai_writer.bench import load_scenes  # noqa: E402
from ai_writer.guard import MinimumGuard  # noqa: E402
from ai_writer.provider import NovelAIProvider  # noqa: E402
from ai_writer.testing import FakeTransport, sse  # noqa: E402
from ai_writer.writer import CoreWriter  # noqa: E402


def writer(*scripts: object) -> tuple[CoreWriter, FakeTransport]:
    t = FakeTransport(*scripts)
    p = NovelAIProvider("pst-length-test", transport=t, slot=threading.BoundedSemaphore(1), sleep=lambda _s: None)
    return CoreWriter(p, guard=MinimumGuard()), t


def test_conditions_scale_instructed_chars_and_max_tokens() -> None:
    scene = load_scenes()[0]
    w, _ = writer()
    bodies = {c: w.plan("directed_continue", le.directed_input(scene, r))["request"]["body"] for c, r in le.CONDITIONS.items()}
    assert "約400字" in bodies["A"]["messages"][1]["content"] and bodies["A"]["max_tokens"] == 492
    assert "約600字" in bodies["B"]["messages"][1]["content"] and bodies["B"]["max_tokens"] == 738
    assert "約800字" in bodies["C"]["messages"][1]["content"] and bodies["C"]["max_tokens"] == 984


def test_gap_positions_split_at_sentence_ends() -> None:
    text = "一つ目の文。二つ目の文。三つ目の文。四つ目の文。五つ目の文。六つ目の文。"
    pos = le.gap_positions(text)
    assert len(pos) == 2 and all(text[p - 1] == "。" for p in pos)
    # 「。」」の間（5）では切らず、閉じ括弧の後（6）と次の句点の後（11）で切る。末尾（15）は選ばない
    assert le.gap_positions("「待って。」と言った。終わり。") == [6, 11]
    assert le.gap_positions("句点のない文") == []


def test_expand_complement_inserts_in_order_and_marks() -> None:
    scene = load_scenes()[0]
    base = "　一つ目の文。二つ目の文。三つ目の文。四つ目の文。五つ目の文。六つ目の文。"
    w, t = writer(sse("〈挿入一〉。"), sse("〈挿入二〉。"))
    text, inserts = le.expand_complement(w, scene, base)
    assert len(t.calls) == 2 and len(inserts) == 2
    assert text.count("〈挿入一〉。") == 1 and text.index("〈挿入一〉") < text.index("〈挿入二〉")
    assert text.replace("〈挿入一〉。", "").replace("〈挿入二〉。", "") == base
    # 2 か所目の要求は、1 か所目を入れた後の本文で組み立てる
    assert "〈挿入一〉。" in t.calls[1]["body"]["messages"][1]["content"]
    rec = {"condition": "D", "text": text, "detail": {"base_text": base, "inserts": inserts}}
    marked = le._marked(rec)  # noqa: SLF001
    assert marked.replace("〔＋〈挿入一〉。〕", "").replace("〔＋〈挿入二〉。〕", "") == base
    assert "〔＋〈挿入一〉。〕" in marked and "〔＋〈挿入二〉。〕" in marked


def test_expand_complement_skips_when_long_enough() -> None:
    scene = load_scenes()[0]
    w, t = writer()
    base = "あ。" * 250
    assert le.expand_complement(w, scene, base) == (base, [])
    assert t.calls == []


def test_run_sample_d_reuses_a_and_counts_calls(tmp_path: Path) -> None:
    scene = load_scenes()[0]
    a_text = "　一つ目の文。二つ目の文。三つ目の文。"
    w, t = writer(sse(a_text), sse("足した。"), sse("足した二。"))
    a = le.run_sample(w, le.Sample(scene, "A", 1), {})
    assert a["calls"] == 1 and a["text"] == a_text and a["ratio"] == round(len(a_text) / 400, 3)
    d = le.run_sample(w, le.Sample(scene, "D", 1), {a["id"]: a})
    assert d["calls"] == 2 and d["detail"]["base_id"] == a["id"] and d["chars"] > a["chars"]
    assert len(t.calls) == 3


def test_plan_is_dry_run(capsys, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def fail(*_a, **_k):  # type: ignore[no-untyped-def]
        raise AssertionError("dry-run で送信した")

    monkeypatch.setattr(nai, "load_token", fail)
    monkeypatch.setattr("ai_writer.transport.UrllibTransport.open_stream", fail)
    assert le.main(["run"]) == 0
    out = capsys.readouterr().out
    assert "Directed Continue 42 回 + Expand 最大 28 回 = 最大 70 回" in out
