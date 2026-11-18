#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import local_writer_cli as lw  # noqa: E402


def _fake_request(responses: list[dict], calls: list):
    def fake(path, body=None, timeout=600):
        calls.append((path, body))
        if path == "/models":
            return {"data": [{"id": "gyro-gyro-s", "meta": {"label": "Qwen3.8-Flash-Next Gyro-S", "aliases": ["gyro-gyro-s"]}}]}
        return responses.pop(0)

    return fake


def _chat(content: str, finish: str = "stop", reasoning: str = "") -> dict:
    return {
        "model": "gyro-gyro-s",
        "choices": [{"message": {"content": content, "reasoning_content": reasoning}, "finish_reason": finish}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }


def test_rejects_non_local_base_url(monkeypatch) -> None:
    monkeypatch.setenv("MONOCRI_LOCAL_LLM_BASE_URL", "https://api.example.com/v1")
    with pytest.raises(lw.LocalWriterError):
        lw.base_url()


def test_build_body_disables_thinking_by_default() -> None:
    body = lw.build_body("書いて", system=None, model="m", max_tokens=10, temperature=0.5, thinking=False, seed=None)
    assert body["chat_template_kwargs"] == {"enable_thinking": False}
    assert body["messages"] == [{"role": "user", "content": "書いて"}]
    assert "chat_template_kwargs" not in lw.build_body(
        "書いて", system="s", model="m", max_tokens=10, temperature=0.5, thinking=True, seed=1
    )


def test_generate_writes_output_and_record_without_key(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("MONOCRI_LOCAL_LLM_API_KEY", "secret-should-not-appear")
    calls: list = []
    monkeypatch.setattr(lw, "_request", _fake_request([_chat("　本文です。", reasoning="考え")], calls))
    prompt = tmp_path / "prompt.md"
    prompt.write_text("第1章を書く", encoding="utf-8")
    out = tmp_path / "trial" / "tier0.md"

    code = lw.main(["generate", "--prompt", str(prompt), "--out", str(out), "--condition", "tier0", "--keep-reasoning"])

    assert code == 0
    assert out.read_text(encoding="utf-8") == "　本文です。\n"
    record = json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))
    assert record["model_label"] == "Qwen3.8-Flash-Next Gyro-S"
    assert record["condition"] == "tier0"
    assert record["params"]["thinking"] is False
    assert record["prompt_sha256"].startswith("sha256:")
    assert "secret-should-not-appear" not in out.with_suffix(".json").read_text(encoding="utf-8")
    assert out.with_suffix(".reasoning.txt").read_text(encoding="utf-8") == "考え"
    assert calls[-1][1]["messages"][0]["content"] == "第1章を書く"


def test_generate_refuses_novel_text_and_existing_output(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(lw, "_request", _fake_request([], []))
    prompt = tmp_path / "prompt.md"
    prompt.write_text("x", encoding="utf-8")

    assert lw.main(["generate", "--prompt", str(prompt), "--out", str(tmp_path / "_novel_text" / "novel_text01.md")]) == 2
    existing = tmp_path / "a.md"
    existing.write_text("old", encoding="utf-8")
    assert lw.main(["generate", "--prompt", str(prompt), "--out", str(existing)]) == 2
    assert existing.read_text(encoding="utf-8") == "old"


def test_generate_empty_content_is_error(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(lw, "_request", _fake_request([_chat("", finish="length", reasoning="長い思考")], []))
    prompt = tmp_path / "prompt.md"
    prompt.write_text("x", encoding="utf-8")
    out = tmp_path / "b.md"

    assert lw.main(["generate", "--prompt", str(prompt), "--out", str(out)]) == 1
    assert not out.exists()
