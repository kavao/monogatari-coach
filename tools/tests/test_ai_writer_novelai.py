from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from ai_writer import novelai as nai  # noqa: E402
from ai_writer.spike import PROBES, main  # noqa: E402


def test_iter_sse_payloads_reads_data_lines_and_done() -> None:
    lines = [
        b": keep-alive\n",
        b'data: {"choices":[{"delta":{"content":"\xe9\xa7\x85"}}]}\n',
        b"\n",
        b"data: not-json\n",
        b"data: [DONE]\n",
    ]
    events = list(nai.iter_sse_payloads(lines))
    assert events[0] == {"choices": [{"delta": {"content": "駅"}}]}
    assert events[1] == {"_unparsed": "not-json"}
    assert events[2] == nai.DONE


def test_delta_text_reads_chat_and_completions() -> None:
    assert nai.delta_text({"choices": [{"delta": {"content": "あ"}}]}) == "あ"
    assert nai.delta_text({"choices": [{"text": "い"}]}) == "い"
    assert nai.delta_text({"choices": []}) == ""


def test_build_chat_body_merges_sampling_and_stop() -> None:
    body = nai.build_chat_body("glm-4-6", [{"role": "user", "content": "x"}], max_tokens=10,
                               sampling={"temperature": 0.8}, stop=["。"])
    assert body == {"model": "glm-4-6", "messages": [{"role": "user", "content": "x"}],
                    "max_tokens": 10, "stream": True, "temperature": 0.8, "stop": ["。"]}


def test_redacted_headers_hide_token() -> None:
    assert nai.redacted_headers()["Authorization"] == "Bearer ***"


def test_probe_names_are_unique() -> None:
    names = [p.name for p in PROBES]
    assert len(names) == len(set(names))


def test_run_without_execute_is_dry_run(capsys, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def fail(*_a, **_k):  # type: ignore[no-untyped-def]
        raise AssertionError("dry-run で通信した")

    monkeypatch.setattr(nai, "call_stream", fail)
    monkeypatch.setattr(nai, "call_json", fail)
    monkeypatch.setattr(nai, "load_token", fail)
    assert main(["run", "--probe", "chat-stream", "--model", "glm-4-6"]) == 0
    out = capsys.readouterr().out
    assert "/oa/v1/chat/completions" in out
    assert "Bearer ***" in out


def test_load_request_headers_reads_browser_like_user_agent() -> None:
    headers = nai.load_request_headers(ROOT)
    assert headers.get("User-Agent", "").startswith("Mozilla/")


def test_context_filler_scales_with_target() -> None:
    from ai_writer.spike import TOKENS_PER_CHAR_ESTIMATE, context_filler

    text = context_filler(8000)
    assert text.startswith("【1】")
    assert abs(len(text) * TOKENS_PER_CHAR_ESTIMATE - 8000) < 100


def test_stream_usage_probe_adds_stream_options() -> None:
    probe = next(p for p in PROBES if p.name == "stream-usage-chat")
    _, _, body, opts = probe.build("glm-4-6")
    assert body is not None and body["stream_options"] == {"include_usage": True}
    assert opts["stream"] is True


def test_chunk_token_count_skips_stop_only_chunk() -> None:
    body = {"choices": [{"delta": {"content": "もの"}, "token_ids": [129418], "finish_reason": None}]}
    stop = {"choices": [{"delta": {"content": ""}, "token_ids": [151336], "finish_reason": "stop"}]}
    completion = {"choices": [{"text": "き", "token_ids": [49416], "finish_reason": "length"}]}
    assert nai.chunk_token_count(body) == 1
    assert nai.chunk_token_count(stop) == 0
    assert nai.chunk_token_count(completion) == 1
