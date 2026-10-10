from __future__ import annotations

import json
import sys
import threading
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from ai_writer.profiles import ProfileError, default_model_for, load_profile, load_profiles  # noqa: E402
from ai_writer.provider import (  # noqa: E402
    ConcurrencyBusyError,
    ContextLimitError,
    GenerationRequest,
    NovelAIProvider,
    ProviderError,
    account_slot,
)
from ai_writer.testing import FakeHandle, FakeTransport, sse  # noqa: E402
from ai_writer.transport import TransportError  # noqa: E402

TOKEN = "pst-test-token"


# 模擬の通信は ai_writer.testing（Core Writer・探索機能のテストと共有）


def provider(transport: FakeTransport, **kwargs: Any) -> NovelAIProvider:
    kwargs.setdefault("slot", threading.BoundedSemaphore(1))
    return NovelAIProvider(TOKEN, headers={"User-Agent": "Mozilla/5.0"}, transport=transport,
                           sleep=lambda _s: None, **kwargs)


def chat(text: str = "続きを書いて", **kwargs: Any) -> GenerationRequest:
    return GenerationRequest(model="glm-4-6", endpoint="chat", max_tokens=kwargs.pop("max_tokens", 100),
                             messages=({"role": "user", "content": text},), **kwargs)


def slot_free(p: NovelAIProvider) -> bool:
    ok = p._slot.acquire(blocking=False)  # noqa: SLF001
    if ok:
        p._slot.release()  # noqa: SLF001
    return ok


# ---- Capability Profile -------------------------------------------------------

def test_real_profiles_load_with_phase0_values() -> None:
    profiles = load_profiles()
    assert set(profiles) == {"glm-4-6", "xialong-v1"}
    glm = profiles["glm-4-6"]
    assert glm.context_limit_tokens == 36864
    assert glm.concurrency == 1
    assert glm.chars_per_token("p10") == 1.087
    assert glm.expand_modes["insertion"].supported is True
    assert glm.supports("streaming") and not glm.supports("non_streaming")
    for op in ("continue", "directed_continue", "expand_insertion"):
        assert default_model_for(op, profiles) == "glm-4-6"
    assert default_model_for("expand_rewrite", profiles) is None


def _write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


BASE = """id: x
provider: novelai
model: {model}
family: glm
revision: 1
endpoints: {{chat: https://example.invalid/chat}}
capabilities:
  streaming: {cap}
preferred_operations: {ops}
"""


def test_verified_capability_requires_source_and_date(tmp_path: Path) -> None:
    path = _write(tmp_path, "a.yaml", BASE.format(model="m", cap="{supported: true, verified: true}", ops="[]"))
    with pytest.raises(ProfileError, match="source と verified_at"):
        load_profile(path)
    ok = _write(tmp_path, "b.yaml", BASE.format(model="m", cap="{supported: unknown, verified: false}", ops="[]"))
    assert load_profile(ok).capabilities["streaming"].supported == "unknown"


def test_profile_rejects_unknown_operation_and_duplicate_model(tmp_path: Path) -> None:
    bad = _write(tmp_path, "a.yaml", BASE.format(model="m", cap="{verified: false}", ops="[polish]"))
    with pytest.raises(ProfileError, match="未知の操作"):
        load_profile(bad)
    bad.unlink()
    _write(tmp_path, "a.yaml", BASE.format(model="m", cap="{verified: false}", ops="[]"))
    _write(tmp_path, "b.yaml", BASE.format(model="m", cap="{verified: false}", ops="[]"))
    with pytest.raises(ProfileError, match="重複"):
        load_profiles(tmp_path)


# ---- generate / stream ---------------------------------------------------------

def test_generate_joins_chunks_and_sends_expected_request() -> None:
    t = FakeTransport(sse("駅の", "ホームに", "風"))
    p = provider(t)
    result = p.generate(chat(sampling={"temperature": 0.8}, stop=("***",)))
    assert result.status == "complete"
    assert result.text == "駅のホームに風"
    assert result.output_tokens == 7
    assert result.finish_reason == "stop"
    call = t.calls[0]
    assert call["url"] == "https://text.novelai.net/oa/v1/chat/completions"
    assert call["headers"]["Authorization"] == f"Bearer {TOKEN}"
    assert call["headers"]["Accept"] == "text/event-stream"
    assert call["headers"]["User-Agent"] == "Mozilla/5.0"
    assert call["body"]["stream"] is True and call["body"]["stop"] == ["***"] and call["body"]["temperature"] == 0.8
    assert slot_free(p)


def test_stream_without_terminator_is_incomplete() -> None:
    p = provider(FakeTransport(sse("途中まで", finish=None, done=False)))
    result = p.generate(chat())
    assert result.status == "incomplete" and result.text == "途中まで" and not result.cancelled


def test_connection_reset_keeps_partial_text() -> None:
    p = provider(FakeTransport(FakeHandle(sse("一つ目", "二つ目"), fail_after=1)))
    result = p.generate(chat())
    assert result.status == "incomplete"
    assert result.text == "一つ目"
    assert result.error and "connection reset" in result.error
    assert slot_free(p)


# ---- cancel --------------------------------------------------------------------

def test_cancel_in_same_thread_keeps_partial_output() -> None:
    t = FakeTransport(FakeHandle(sse("一つ目", "二つ目", "三つ目"), hold=True))
    p = provider(t)
    gen = p.stream(chat())
    first = next(iter(gen))
    assert first.text == "一つ目"
    p.cancel(gen)
    result = gen.result()
    assert result.status == "incomplete" and result.cancelled
    assert result.text == "一つ目"
    assert t.active == 0 and slot_free(p)


def test_cancel_from_another_thread_while_waiting_for_data() -> None:
    handle = FakeHandle(sse("一つ目", "二つ目", finish=None, done=False), hold=True)  # 2 片のあと応答が止まる
    p = provider(FakeTransport(handle))
    gen = p.stream(chat())
    received: list[str] = []
    two = threading.Event()

    def reader() -> None:
        for chunk in gen:
            received.append(chunk.text)
            if len(received) == 2:
                two.set()

    th = threading.Thread(target=reader)
    th.start()
    assert two.wait(5)
    p.cancel(gen)  # 読み取りスレッドは次の行を待っている
    th.join(5)
    assert not th.is_alive()
    result = gen.result()
    assert result.status == "incomplete" and result.cancelled
    assert result.text == "一つ目二つ目"
    assert handle.closed.is_set() and slot_free(p)


def test_cancel_before_reading_releases_slot() -> None:
    p = provider(FakeTransport(FakeHandle(sse("本文"), hold=True)))
    gen = p.stream(chat())
    gen.cancel()
    result = gen.result()
    assert result.status == "incomplete" and result.text == "" and slot_free(p)


def test_breaking_out_then_result_reads_the_rest() -> None:
    p = provider(FakeTransport(sse("一", "二", "三")))
    gen = p.stream(chat())
    for _ in gen:
        break
    result = gen.result()
    assert result.status == "complete" and result.text == "一二三" and slot_free(p)


def test_leaving_with_block_cancels_and_releases() -> None:
    t = FakeTransport(FakeHandle(sse("一", "二"), hold=True))
    p = provider(t)
    with p.stream(chat()) as gen:
        next(iter(gen))
    assert gen.cancelled and t.active == 0 and slot_free(p)


# ---- 同時生成 1 本 ---------------------------------------------------------------

def test_second_stream_waits_for_the_slot_and_times_out() -> None:
    t = FakeTransport(FakeHandle(sse("一"), hold=True), sse("二"))
    p = provider(t, acquire_timeout=0.05)
    first = p.stream(chat())
    with pytest.raises(ConcurrencyBusyError):
        p.stream(chat())
    assert len(t.calls) == 1  # 2 本目は送っていない
    first.cancel()
    assert p.generate(chat()).text == "二"


def test_providers_sharing_an_account_never_overlap() -> None:
    token = "pst-shared-" + threading.current_thread().name
    t = FakeTransport(*[sse(f"本文{i}") for i in range(6)])
    providers = [NovelAIProvider(token, transport=t, slot=account_slot(token, 1), sleep=lambda _s: None, acquire_timeout=5)
                 for _ in range(2)]
    results: list[str] = []

    def work(pv: NovelAIProvider) -> None:
        for _ in range(3):
            results.append(pv.generate(chat()).status)

    threads = [threading.Thread(target=work, args=(pv,)) for pv in providers]
    for th in threads:
        th.start()
    for th in threads:
        th.join(10)
    assert results.count("complete") == 6
    assert t.max_active == 1


def test_server_side_429_is_retried_then_succeeds() -> None:
    waits: list[float] = []
    locked = TransportError(429, '{"statusCode":429,"message":"Concurrent generation is locked"}')
    t = FakeTransport(locked, TransportError(429, "locked"), sse("通った"))
    p = NovelAIProvider(TOKEN, transport=t, slot=threading.BoundedSemaphore(1), sleep=waits.append, retry_wait=2.0)
    result = p.generate(chat())
    assert result.status == "complete" and result.attempts == 3
    assert waits == [2.0, 4.0]


def test_429_retries_exhausted_and_http_error_release_the_slot() -> None:
    t = FakeTransport(*[TransportError(429, "locked") for _ in range(4)], TransportError(400, "bad request"))
    p = provider(t, retry_429=3)
    r1 = p.generate(chat())
    assert r1.status == "error" and r1.http_status == 429 and r1.attempts == 4
    r2 = p.generate(chat())
    assert r2.status == "error" and r2.http_status == 400 and r2.error == "bad request"
    assert slot_free(p)


# ---- 送る前の検査・dry-run ---------------------------------------------------------

def test_check_rejects_before_sending() -> None:
    t = FakeTransport()
    p = provider(t)
    with pytest.raises(ProviderError, match="未知のモデル"):
        p.stream(GenerationRequest(model="llama-3-erato-v1", endpoint="completions", max_tokens=10, prompt="x"))
    with pytest.raises(ContextLimitError):
        p.stream(chat("あ" * 40000, max_tokens=100))
    with pytest.raises(ProviderError, match="max_tokens"):
        p.stream(chat(max_tokens=0))
    with pytest.raises(ProviderError, match="prompt"):
        p.stream(GenerationRequest(model="glm-4-6", endpoint="completions", max_tokens=10))
    assert t.calls == [] and slot_free(p)


def test_count_tokens_is_conservative_benchmark_estimate() -> None:
    p = provider(FakeTransport())
    est = p.count_tokens("あ" * 1087, "glm-4-6")
    assert est.method == "benchmark_estimate" and est.chars_per_token == 1.087 and est.tokens == 1001
    assert p.count_tokens("あ" * 1200, "glm-4-6", conservative=False).chars_per_token == 1.2


def test_preview_and_repr_hide_the_token() -> None:
    p = provider(FakeTransport())
    pv = p.preview(GenerationRequest(model="glm-4-6", endpoint="completions", max_tokens=50, prompt="駅のホーム"))
    assert pv["headers"]["Authorization"] == "Bearer ***"
    assert pv["url"].endswith("/oa/v1/completions") and pv["body"]["prompt"] == "駅のホーム"
    assert TOKEN not in json.dumps(pv, ensure_ascii=False) and TOKEN not in repr(p)
    assert p.list_models() == ["glm-4-6", "xialong-v1"]


def test_provider_cli_dry_run_does_not_load_token_or_send(capsys, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from ai_writer import novelai as nai
    from ai_writer import provider_cli

    def fail(*_a, **_k):  # type: ignore[no-untyped-def]
        raise AssertionError("dry-run でトークンを読んだ／送信した")

    monkeypatch.setattr(nai, "load_token", fail)
    monkeypatch.setattr("ai_writer.transport.UrllibTransport.open_stream", fail)
    assert provider_cli.main([]) == 0
    out = capsys.readouterr().out
    assert "確認 2 件" in out and "Bearer ***" in out and "40 字で cancel" in out


def test_provider_cli_check_reports_cancel_and_slot() -> None:
    from ai_writer.provider_cli import build_request, run_check

    p = provider(FakeTransport(FakeHandle(sse("あ" * 30, "い" * 30, "う" * 30), hold=True)))
    rec = run_check(p, "cancel", build_request("glm-4-6", "chat", 200), 40)
    assert rec["result"]["status"] == "incomplete" and rec["result"]["text"] == "あ" * 30 + "い" * 30
    assert rec["slot_released"] is True
    assert rec["request"]["headers"]["Authorization"] == "Bearer ***"
