"""Phase 0 API Spike の検査項目と実行（計画書 §50）。

各検査は短い生成を1回だけ送る（``subscription`` は生成なし）。既定は dry-run で、
``--execute`` を付けたときだけ通信する。結果は ``_workingspace/ai_writer/phase0/<run>/`` に
検査ごとの JSON と ``summary.md`` を書く。トークンは出力しない。
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from . import novelai as nai

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_ROOT = REPO_ROOT / "_workingspace" / "ai_writer" / "phase0"

SCENE = (
    "　駅のホームには誰もいなかった。錆びた時刻表が風に揺れ、最終列車の時刻だけが"
    "赤いペンで丸く囲まれている。悠真はベンチの下に手を伸ばし、湿った落ち葉をかき分けた。"
)
CONTINUE_INSTRUCTION = "次の日本語の小説本文の続きを、地の文で200字ほど書いてください。前置きや説明は書かず、本文だけを出力してください。\n\n"
STANDARD_SAMPLING: dict[str, Any] = {"temperature": 0.8, "top_p": 0.9}
EXTRA_SAMPLING: dict[str, Any] = {"temperature": 0.8, "top_p": 0.9, "top_k": 40, "min_p": 0.05, "frequency_penalty": 0.2, "presence_penalty": 0.1}


@dataclass(frozen=True)
class Probe:
    name: str
    purpose: str
    models: tuple[str, ...]
    build: Callable[[str], tuple[str, str, dict[str, Any] | None, dict[str, Any]]]
    """model -> (method, url, body, call options)"""


def _chat(model: str, messages: list[dict[str, str]], *, max_tokens: int = 300, stream: bool = True,
          sampling: dict[str, Any] | None = None, stop: list[str] | None = None,
          **opts: Any) -> tuple[str, str, dict[str, Any] | None, dict[str, Any]]:
    body = nai.build_chat_body(model, messages, max_tokens=max_tokens, stream=stream,
                               sampling=sampling or STANDARD_SAMPLING, stop=stop)
    return "POST", nai.TEXT_HOST + nai.CHAT_PATH, body, {"stream": stream, **opts}


def _user(text: str) -> list[dict[str, str]]:
    return [{"role": "user", "content": text}]


def _with_usage(built: tuple[str, str, dict[str, Any] | None, dict[str, Any]]) -> tuple[str, str, dict[str, Any] | None, dict[str, Any]]:
    """ストリームでも usage を返させる OpenAI 互換の指定を足す。"""
    method, url, body, opts = built
    return method, url, {**(body or {}), "stream_options": {"include_usage": True}}, opts


# 前回 Spike の実測（指示＋場面 140 字で prompt_tokens 117）から、約 0.84 トークン/字
TOKENS_PER_CHAR_ESTIMATE = 0.84
CONTEXT_TARGETS = (8000, 20000, 28000, 40000)
_FILLER_LINES = (
    "駅のホームには誰もいなかった。錆びた時刻表が風に揺れていた。",
    "悠真はベンチの下に手を伸ばし、湿った落ち葉をかき分けた。",
    "遠くで踏切の警報が鳴り、すぐにやんだ。線路の先は霧に沈んでいる。",
    "妹のリボンは、たしかにこの駅で失くしたはずだった。",
)


def context_filler(target_tokens: int) -> str:
    """推定トークン数がおよそ ``target_tokens`` になる段落番号付きの本文。"""
    target_chars = int(target_tokens / TOKENS_PER_CHAR_ESTIMATE)
    parts: list[str] = []
    total = 0
    i = 0
    while total < target_chars:
        line = f"【{i + 1}】{_FILLER_LINES[i % len(_FILLER_LINES)]}\n"
        parts.append(line)
        total += len(line)
        i += 1
    return "".join(parts)


def _context_probe(target: int) -> Probe:
    return Probe(f"context-{target // 1000}k", f"入力約 {target} トークンで受け付けるか（usage.prompt_tokens を記録）", nai.CHAT_MODELS,
                 lambda m: _chat(m, _user(context_filler(target) + "\n上の【1】の文を、そのまま書き写してください。"),
                                 max_tokens=16, stream=False))


PROBES: tuple[Probe, ...] = (
    Probe("subscription", "認証と契約ティアの確認（生成なし）", ("-",),
          lambda m: ("GET", nai.SUBSCRIPTION_URL, None, {"stream": False})),
    Probe("chat-stream", "chat エンドポイントのストリーミング生成と日本語の続き", nai.CHAT_MODELS,
          lambda m: _chat(m, _user(CONTINUE_INSTRUCTION + SCENE))),
    Probe("chat-nonstream", "非ストリーム応答で本文が空になる報告の確認", nai.CHAT_MODELS,
          lambda m: _chat(m, _user(CONTINUE_INSTRUCTION + SCENE), stream=False)),
    Probe("system-role", "system メッセージを受け付けるか", nai.CHAT_MODELS,
          lambda m: _chat(m, [{"role": "system", "content": "あなたは日本語の小説家です。本文だけを出力します。"},
                              {"role": "user", "content": CONTINUE_INSTRUCTION + SCENE}])),
    Probe("assistant-prefill", "assistant 末尾に本文を置き、続きとして書くか（Continue の本命）", nai.CHAT_MODELS,
          lambda m: _chat(m, [{"role": "user", "content": "日本語の小説本文を書いてください。"},
                              {"role": "assistant", "content": SCENE}])),
    Probe("completions", "/oa/v1/completions（素の補完）が使えるか", nai.CHAT_MODELS,
          lambda m: ("POST", nai.TEXT_HOST + nai.COMPLETIONS_PATH,
                     nai.build_completions_body(m, SCENE, max_tokens=300, sampling=STANDARD_SAMPLING),
                     {"stream": True})),
    Probe("stop", "stop 指定で「。」の直後に止まるか", nai.CHAT_MODELS,
          lambda m: _chat(m, _user(CONTINUE_INSTRUCTION + SCENE), stop=["。"])),
    Probe("cancel", "ストリームを途中で閉じて部分出力を残せるか", nai.CHAT_MODELS,
          lambda m: _chat(m, _user(CONTINUE_INSTRUCTION + SCENE), max_tokens=600, cancel_after_chars=40)),
    Probe("extra-sampling", "top_k / min_p / penalty を受け付けるか、拒否されるか", nai.CHAT_MODELS,
          lambda m: _chat(m, _user(CONTINUE_INSTRUCTION + SCENE), sampling=EXTRA_SAMPLING)),
    Probe("long-output", "max_tokens 1500 で出力上限と usage（トークン数）を見る", nai.CHAT_MODELS,
          lambda m: _chat(m, _user("次の日本語の小説本文の続きを、地の文で2000字ほど書いてください。本文だけを出力してください。\n\n" + SCENE),
                          max_tokens=1500)),
    # 追加確認（Phase 0 段階3）
    Probe("stream-usage-chat", "chat のストリームで stream_options.include_usage により usage が返るか", nai.CHAT_MODELS,
          lambda m: _with_usage(_chat(m, _user(CONTINUE_INSTRUCTION + SCENE)))),
    Probe("stream-usage-completions", "completions のストリームで usage が返るか", nai.CHAT_MODELS,
          lambda m: _with_usage(("POST", nai.TEXT_HOST + nai.COMPLETIONS_PATH,
                                 nai.build_completions_body(m, SCENE, max_tokens=300, sampling=STANDARD_SAMPLING),
                                 {"stream": True}))),
    *(_context_probe(t) for t in CONTEXT_TARGETS),
    Probe("parallel-3", "同じモデルへ3本を同時に送り、拒否や待たされ方を見る", nai.CHAT_MODELS,
          lambda m: _chat(m, _user(CONTINUE_INSTRUCTION + SCENE), max_tokens=150, parallel=3)),
)


def _select(names: list[str] | None, models: list[str] | None) -> list[tuple[Probe, str]]:
    known = {p.name for p in PROBES}
    unknown = [n for n in names or [] if n not in known]
    if unknown:
        raise SystemExit(f"未知の検査: {', '.join(unknown)}（plan で一覧）")
    pairs: list[tuple[Probe, str]] = []
    for probe in PROBES:
        if names and probe.name not in names:
            continue
        for model in probe.models:
            if models and model != "-" and model not in models:
                continue
            pairs.append((probe, model))
    return pairs


def _run_one(probe: Probe, model: str, token: str, headers: dict[str, str]) -> dict[str, Any]:
    method, url, body, opts = probe.build(model)
    if method == "GET":
        result = nai.call_json(url, token, None, method="GET", headers=headers, timeout=30)
        if isinstance(result.raw_json, dict):
            # 契約情報のうち判断に要る欄だけ残す
            keep = ("tier", "active", "expiresAt", "perks")
            result.raw_json = {k: result.raw_json.get(k) for k in keep}
    elif opts.get("parallel"):
        n = int(opts["parallel"])
        with ThreadPoolExecutor(max_workers=n) as pool:
            futures = [pool.submit(nai.call_stream, url, token, body or {}, headers=headers) for _ in range(n)]
            results = [f.result().to_dict() for f in futures]
        return {"probe": probe.name, "model": model, "purpose": probe.purpose,
                "request": {"method": method, "url": url, "headers": nai.redacted_headers(), "body": body, "parallel": n},
                "result": {"parallel": results}}
    elif opts.get("stream"):
        result = nai.call_stream(url, token, body or {}, headers=headers,
                                 cancel_after_chars=opts.get("cancel_after_chars"))
    else:
        result = nai.call_json(url, token, body, headers=headers)
    return {"probe": probe.name, "model": model, "purpose": probe.purpose,
            "request": {"method": method, "url": url, "headers": nai.redacted_headers(), "body": body},
            "result": result.to_dict()}


def _summary_row(rec: dict[str, Any]) -> str:
    r = rec["result"]
    if "parallel" in r:
        cells = [f"{x.get('status')}:{len(x.get('text') or '')}字:{x.get('total_sec')}s" for x in r["parallel"]]
        return f"| {rec['probe']} | {rec['model']} | 並列 | - | - | - | - | {' / '.join(cells)} |"
    text =(r.get("text") or "").replace("\n", "⏎")
    preview = text[:40] + ("…" if len(text) > 40 else "")
    err = (r.get("error") or "").replace("\n", " ")[:80]
    usage = r.get("usage") or {}
    tokens = usage.get("completion_tokens") if isinstance(usage, dict) else None
    if tokens is None and r.get("output_tokens"):
        tokens = r["output_tokens"]
    if rec["probe"].startswith("context-") and isinstance(usage, dict):
        tokens = f"in {usage.get('prompt_tokens')}"
    return (f"| {rec['probe']} | {rec['model']} | {r.get('status')} | {len(r.get('text') or '')} | {tokens if tokens is not None else '-'} "
            f"| {r.get('finish_reason') or '-'} | {r.get('first_chunk_sec') or '-'} / {r.get('total_sec')} | {preview or err or '-'} |")


def _abbreviate(value: Any, limit: int = 300) -> Any:
    """dry-run 表示用に長い文字列を詰める（送信内容は変えない）。"""
    if isinstance(value, str) and len(value) > limit:
        return f"{value[:120]}…（中略 計 {len(value)} 字）…{value[-60:]}"
    if isinstance(value, dict):
        return {k: _abbreviate(v, limit) for k, v in value.items()}
    if isinstance(value, list):
        return [_abbreviate(v, limit) for v in value]
    return value


def cmd_plan(args: argparse.Namespace) -> int:
    pairs = _select(args.probe, args.model)
    print(f"検査 {len(pairs)} 件（生成を伴う呼び出し {sum(1 for p, _ in pairs if p.name != 'subscription')} 件）")
    for probe, model in pairs:
        method, url, body, opts = probe.build(model)
        print(f"\n## {probe.name} / {model}: {probe.purpose}")
        print(f"{method} {url}")
        print(f"headers: {json.dumps(nai.redacted_headers())}")
        if body is not None:
            print(json.dumps(_abbreviate(body), ensure_ascii=False, indent=2))
        extra = {k: v for k, v in opts.items() if k != "stream"}
        if extra:
            print(f"options: {extra}")
    print("\n本番実行には run --execute を付けてください。")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    if not args.execute:
        return cmd_plan(args)
    pairs = _select(args.probe, args.model)
    token = nai.load_token(REPO_ROOT)
    headers = nai.load_request_headers(REPO_ROOT)
    out_dir = OUT_ROOT / datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    rows: list[str] = []
    for probe, model in pairs:
        print(f"実行: {probe.name} / {model}", flush=True)
        rec = _run_one(probe, model, token, headers)
        safe_model = model.replace("/", "_").replace("-", "_") if model != "-" else "none"
        (out_dir / f"{probe.name}__{safe_model}.json").write_text(
            json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
        rows.append(_summary_row(rec))
        print("  " + rows[-1], flush=True)
    header = ("| 検査 | モデル | HTTP | 文字数 | 出力tok | 終了理由 | 初回/合計秒 | 冒頭または誤り |\n"
              "| --- | --- | --- | --- | --- | --- | --- | --- |")
    (out_dir / "summary.md").write_text(f"# Phase 0 API Spike {out_dir.name}\n\n{header}\n" + "\n".join(rows) + "\n",
                                        encoding="utf-8")
    print(f"\n保存先: {out_dir}")
    return 0


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    parser = argparse.ArgumentParser(description="NovelAI テキスト API の Phase 0 Spike（既定は dry-run）")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name, func in (("plan", cmd_plan), ("run", cmd_run)):
        sp = sub.add_parser(name, help="検査内容を表示する" if name == "plan" else "検査を実行する（--execute で通信）")
        sp.add_argument("--probe", action="append", help="検査名（複数可。省略で全件）")
        sp.add_argument("--model", action="append", help="モデル ID（複数可。省略で全件）")
        if name == "run":
            sp.add_argument("--execute", action="store_true", help="実際に NovelAI へ送信する")
        sp.set_defaults(func=func)
    args = parser.parse_args(argv)
    return args.func(args)
