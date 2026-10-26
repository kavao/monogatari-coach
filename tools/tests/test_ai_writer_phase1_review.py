"""Phase 1 コードレビュー（Codex、2026-10-09、_workingspace/ai_writer/phase1_review_codex_20261009.md）の回帰試験。"""

from __future__ import annotations

import json
import sys
import threading
import urllib.request
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from ai_writer import writer_cli  # noqa: E402
from ai_writer.candidates import CandidateError, CandidateStore  # noqa: E402
from ai_writer.manifest import build_manifest  # noqa: E402
from ai_writer.postprocess import clean_for  # noqa: E402
from ai_writer.prompt_renderer import ContinueInput, render  # noqa: E402
from ai_writer.provider import NovelAIProvider  # noqa: E402
from ai_writer.testing import FakeTransport, sse  # noqa: E402
from ai_writer.transport import UrllibTransport  # noqa: E402
from ai_writer.writer import CoreWriter  # noqa: E402

TOKEN = "pst-review-test"


def _kept(raw: str, removals: list[Any]) -> str:
    out, pos = "", 0
    for r in removals:
        out += raw[pos:r.start]
        pos = r.end
    return out + raw[pos:]


# ---- 1. 空白だけの応答 ------------------------------------------------------------

@pytest.mark.parametrize("raw", ["", " ", "   ", "\n", "\n\t", "　", " \n　 ", "\n\n\t  "])
@pytest.mark.parametrize("op", ["continue", "directed_continue", "expand_insertion"])
def test_whitespace_only_output_cleans_to_empty_without_overlap(raw: str, op: str) -> None:
    result = clean_for(op, raw)
    assert result.text == ""
    assert _kept(raw, result.removals) == ""
    for a, b in zip(result.removals, result.removals[1:]):
        assert a.end <= b.start


@pytest.mark.parametrize("raw", ["\n", "   ", "\n\t"])
def test_whitespace_only_generation_is_returned_and_saved(raw: str, tmp_path: Path) -> None:
    t = FakeTransport(sse(raw))
    w = CoreWriter(NovelAIProvider(TOKEN, transport=t, slot=threading.BoundedSemaphore(1), sleep=lambda _s: None))
    out = w.run("continue", ContinueInput("　本文。"))
    assert out.generation.status == "complete" and out.text == ""
    cand = CandidateStore(tmp_path).save(out, build_manifest(out))
    assert cand.text == "" and cand.raw_text == raw


# ---- 2. 接続開始時のタイムアウト ----------------------------------------------------

class _FakeResp:
    def __init__(self, lines: list[bytes]) -> None:
        self._lines = lines

    def __iter__(self):  # type: ignore[no-untyped-def]
        return iter(self._lines)

    def close(self) -> None:
        pass


def test_connect_timeout_becomes_error_result_and_releases_slot(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    def urlopen(*_a: object, **_k: object) -> _FakeResp:
        calls["n"] += 1
        if calls["n"] == 1:
            raise TimeoutError("timed out")
        return _FakeResp(sse("届いた。"))

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    slot = threading.BoundedSemaphore(1)
    p = NovelAIProvider(TOKEN, transport=UrllibTransport(), slot=slot, sleep=lambda _s: None)
    first = p.generate(render("continue", ContinueInput("本文。"), "glm-4-6", sampling={}).request)
    assert first.status == "error" and first.http_status is None and first.attempts == 1
    assert first.error and "timeout" in first.error
    assert calls["n"] == 1  # タイムアウトは自動で再送しない
    assert slot.acquire(blocking=False)
    slot.release()
    out = CoreWriter(p).run("continue", ContinueInput("本文。"))  # 後続の生成はできる
    assert out.generation.status == "complete" and out.text == "届いた。"


def test_core_writer_records_connect_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    def urlopen(*_a: object, **_k: object) -> None:
        raise TimeoutError("timed out")

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    p = NovelAIProvider(TOKEN, transport=UrllibTransport(), slot=threading.BoundedSemaphore(1))
    out = CoreWriter(p).run("continue", ContinueInput("本文。"))
    assert out.generation.status == "error" and "timeout" in (out.generation.error or "")


# ---- 3. Writer CLI が Guard・Manifest・Candidate Store を通す -----------------------------

def test_writer_cli_execute_runs_guard_and_saves_candidate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                           capsys: pytest.CaptureFixture[str]) -> None:
    # 冒頭で本文の文を繰り返す出力（字数比較実験 B#2 と同じ形）
    t = FakeTransport(sse("振り向きざまに剣を振るうが、硬い毛皮に弾かれる。", "魔獣が倒れた。"))
    provider = NovelAIProvider(TOKEN, transport=t, slot=threading.BoundedSemaphore(1), sleep=lambda _s: None)
    monkeypatch.setattr(writer_cli, "_provider", lambda: provider)
    monkeypatch.setattr(writer_cli, "OUT_ROOT", tmp_path / "phase1")
    monkeypatch.setattr(writer_cli, "STORE_ROOT", tmp_path / "candidates")
    assert writer_cli.main(["--scene", "battle", "--op", "directed_continue", "--execute"]) == 0
    assert "guard=warning" in capsys.readouterr().out

    [out_file] = list((tmp_path / "phase1").glob("*/writer_directed_continue.json"))
    record = json.loads(out_file.read_text(encoding="utf-8"))
    assert record["guard"]["version"] == "mg-2"
    assert [f["check"] for f in record["guard"]["findings"]] == ["opening_repetition"]
    assert record["render_params"]["target_chars"] == 400 and record["render_params"]["instruction_chars"] == 600

    store = CandidateStore(tmp_path / "candidates")
    cand = store.load(record["candidate_id"])
    assert cand.generation_status == "complete" and store.review(cand.candidate_id).status == "unreviewed"
    assert cand.guard and cand.guard["status"] == "warning"
    m = cand.manifest
    assert m["scene_id"] == "battle" and m["guard_version"] == "mg-2" and m["renderer_version"] == "nai-r2"
    assert [r["kind"] for r in m["refs"]] == ["scene", "source_text"]
    assert m["refs"][0]["path"] == "tools/ai_writer/fixtures/benchmark/scenes.yaml"
    assert TOKEN not in out_file.read_text(encoding="utf-8")


# ---- 4. 候補 ID で保存先の外へ出られない -------------------------------------------------

@pytest.mark.parametrize("bad", ["C:outside", "C:", "C:\\x", "c../x", "../x", "a/b", ".hidden", "", "c20261009T030000-ZZZZZZZZ",
                                 "c20261009T030000-0123abcd/../x"])
def test_candidate_id_must_match_generated_form(tmp_path: Path, bad: str) -> None:
    store = CandidateStore(tmp_path)
    # ファイルがないからではなく、ID 自体を拒むこと（旧い検査では "C:outside" が C ドライブを指した）
    rejected = "不正な候補 ID|保存先の外"
    with pytest.raises(CandidateError, match=rejected):
        store.load(bad)
    with pytest.raises(CandidateError, match=rejected):
        store.review(bad)


def test_absolute_path_is_rejected_and_generated_id_round_trips(tmp_path: Path) -> None:
    store = CandidateStore(tmp_path)
    with pytest.raises(CandidateError, match="不正な候補 ID"):
        store.load(str(tmp_path / "candidates" / "x"))
    t = FakeTransport(sse("一。"))
    w = CoreWriter(NovelAIProvider(TOKEN, transport=t, slot=threading.BoundedSemaphore(1), sleep=lambda _s: None))
    out = w.run("continue", ContinueInput("本文。"))
    cand = store.save(out, build_manifest(out))
    assert store.load(cand.candidate_id) == cand
