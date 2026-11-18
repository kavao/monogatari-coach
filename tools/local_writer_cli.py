#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ローカルの OpenAI 互換サーバー（strata など）に、用意したプロンプトのファイルを送り、書き手の出力を保存する。

Kilo Code を手で操作せずに、Claude Code から書き手だけをローカルのモデルに任せるための呼び出し口
（計画 _workingspace/plans/20261114_model-adaptive-writing-support.md §15・§16）。

- 送り先はパソコンの中のサーバーだけ（既定 http://127.0.0.1:47831/v1）。外部の URL は拒否する。
- 本文の正本（_novel_text/）には書き込まない。出力は --out のファイルと、同じ名前の .json の記録。
- 記録には、サーバーが返すモデル名、プロンプトのハッシュ、生成の設定、トークン数を残す。API キーは残さない。
- 受け取ったあとの receive / inspect / publish は writing_bridge の手順で行う（このツールは呼ばない）。

環境変数（任意）:
  MONOCRI_LOCAL_LLM_BASE_URL  既定 http://127.0.0.1:47831/v1
  MONOCRI_LOCAL_LLM_MODEL     既定 gyro-gyro-s
  MONOCRI_LOCAL_LLM_API_KEY   サーバーがキーを求めるときだけ（表示・記録しない）

終了コード: 0 = 保存した / 1 = サーバーの誤り・出力が空 / 2 = 引数・パスの誤り
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

DEFAULT_BASE_URL = "http://127.0.0.1:47831/v1"
DEFAULT_MODEL = "gyro-gyro-s"
LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
PROTECTED_DIR = "_novel_text"


class LocalWriterError(RuntimeError):
    pass


def base_url() -> str:
    url = os.environ.get("MONOCRI_LOCAL_LLM_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    host = urlparse(url).hostname or ""
    if host not in LOCAL_HOSTS:
        raise LocalWriterError(f"ローカル以外の送り先は使わない: {host or url}")
    return url


def _headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json; charset=utf-8"}
    key = os.environ.get("MONOCRI_LOCAL_LLM_API_KEY")
    if key:
        headers["Authorization"] = f"Bearer {key}"
    return headers


def _request(path: str, body: dict[str, Any] | None = None, timeout: float = 600) -> dict[str, Any]:
    url = base_url() + path
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers=_headers(), method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace")[:200]
        raise LocalWriterError(f"HTTP {error.code}: {detail}") from error
    except urllib.error.URLError as error:
        raise LocalWriterError(f"サーバーに接続できない（strata の起動とモデルの読み込みを確認）: {error.reason}") from error


def list_models() -> list[dict[str, Any]]:
    return list(_request("/models").get("data") or [])


def model_label(model: str) -> str:
    """サーバーが返す表示名（strata は meta.label）。取れなければモデルIDのまま。"""
    try:
        for entry in list_models():
            aliases = (entry.get("meta") or {}).get("aliases") or []
            if entry.get("id") == model or model in aliases:
                return str((entry.get("meta") or {}).get("label") or entry.get("id"))
    except LocalWriterError:
        pass
    return model


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _check_out(out: Path) -> None:
    if PROTECTED_DIR in out.resolve().parts:
        raise LocalWriterError(f"{PROTECTED_DIR}/ には書き込まない（正本は writing_bridge の publish で反映する）: {out}")
    if out.suffix.lower() != ".md":
        raise LocalWriterError(f"出力は .md にする: {out}")


def build_body(
    prompt: str,
    *,
    system: str | None,
    model: str,
    max_tokens: int,
    temperature: float,
    thinking: bool,
    seed: int | None,
) -> dict[str, Any]:
    messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
    body: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if not thinking:
        body["chat_template_kwargs"] = {"enable_thinking": False}
    if seed is not None:
        body["seed"] = seed
    return body


def complete(
    prompt: str,
    *,
    system: str | None = None,
    model: str = DEFAULT_MODEL,
    max_tokens: int = 8000,
    temperature: float = 0.7,
    thinking: bool = False,
    seed: int | None = None,
    timeout: float = 900,
) -> dict[str, Any]:
    """プロンプトを送り、本文と記録の材料を返す（ファイルは書かない）。他のツールから呼ぶための口。"""
    body = build_body(
        prompt, system=system, model=model, max_tokens=max_tokens, temperature=temperature, thinking=thinking, seed=seed
    )
    started = time.time()
    label = model_label(model)
    response = _request("/chat/completions", body, timeout=timeout)
    choice = (response.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    # 段落頭の全角空白（　）は本文の一部なので残す。前後の改行と半角空白だけを取る。
    content = (message.get("content") or "").strip("\r\n \t")
    return {
        "content": content,
        "reasoning": message.get("reasoning_content") or "",
        "model": model,
        "model_label": label,
        "server_model": response.get("model"),
        "base_url": base_url(),
        "prompt_sha256": _sha256(prompt.encode("utf-8")),
        "params": {"max_tokens": max_tokens, "temperature": temperature, "thinking": thinking, "seed": seed},
        "finish_reason": choice.get("finish_reason"),
        "usage": response.get("usage"),
        "elapsed_seconds": round(time.time() - started, 1),
    }


def generate(args: argparse.Namespace) -> int:
    prompt_path = Path(args.prompt)
    out = Path(args.out)
    if not prompt_path.is_file():
        print(f"[ERROR] プロンプトのファイルがない: {prompt_path}", file=sys.stderr)
        return 2
    try:
        _check_out(out)
        if out.exists() and not args.overwrite:
            raise LocalWriterError(f"出力が既にある（上書きは --overwrite）: {out}")
    except LocalWriterError as error:
        print(f"[ERROR] {error}", file=sys.stderr)
        return 2

    prompt_bytes = prompt_path.read_bytes()
    system_text = Path(args.system).read_text(encoding="utf-8") if args.system else None
    try:
        result = complete(
            prompt_bytes.decode("utf-8"),
            system=system_text,
            model=args.model,
            max_tokens=args.max_tokens,
            temperature=args.temperature,
            thinking=args.thinking,
            seed=args.seed,
            timeout=args.timeout,
        )
    except LocalWriterError as error:
        print(f"[ERROR] {error}", file=sys.stderr)
        return 1
    content = result["content"]
    reasoning = result["reasoning"]
    label = result["model_label"]
    elapsed = result["elapsed_seconds"]
    record = {
        "schema": 1,
        "created_at": dt.datetime.now().isoformat(timespec="seconds"),
        "base_url": result["base_url"],
        "model": args.model,
        "model_label": label,
        "server_model": result["server_model"],
        "prompt_path": prompt_path.as_posix(),
        "prompt_sha256": _sha256(prompt_bytes),
        "system_path": Path(args.system).as_posix() if args.system else None,
        "system_sha256": _sha256(system_text.encode("utf-8")) if system_text else None,
        "condition": args.condition,
        "params": result["params"],
        "finish_reason": result["finish_reason"],
        "usage": result["usage"],
        "elapsed_seconds": elapsed,
        "output_path": out.as_posix(),
        "output_chars": len(content),
        "reasoning_chars": len(reasoning),
    }
    if not content:
        print(f"[ERROR] 出力の本文が空（finish_reason={record['finish_reason']}）。max_tokens か thinking を見直す", file=sys.stderr)
        return 1
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(content + "\n", encoding="utf-8", newline="\n")
    record["output_sha256"] = _sha256(out.read_bytes())
    if args.keep_reasoning and reasoning:
        out.with_suffix(".reasoning.txt").write_text(reasoning, encoding="utf-8", newline="\n")
    out.with_suffix(".json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"保存: {out}（{len(content)}字・{record['finish_reason']}・{elapsed}s・{label}）\n記録: {out.with_suffix('.json')}"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        from console_io import configure_stdio_utf8

        configure_stdio_utf8()
    except ImportError:
        pass
    parser = argparse.ArgumentParser(description="ローカルの書き手（strata など）にプロンプトを送り、出力を保存する")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("models", help="サーバーのモデル一覧を出す")
    gen = sub.add_parser("generate", help="プロンプトのファイルを送り、出力を保存する")
    gen.add_argument("--prompt", required=True, help="送るプロンプト（UTF-8 のテキスト）")
    gen.add_argument("--system", help="system に入れるテキスト（任意）")
    gen.add_argument("--out", required=True, help="出力の .md（_novel_text/ の下は不可）。記録は同じ名前の .json")
    gen.add_argument("--model", default=os.environ.get("MONOCRI_LOCAL_LLM_MODEL", DEFAULT_MODEL))
    gen.add_argument("--max-tokens", type=int, default=8000)
    gen.add_argument("--temperature", type=float, default=0.7)
    gen.add_argument("--seed", type=int)
    gen.add_argument("--thinking", action="store_true", help="思考を有効にする（既定は無効。条件として記録する）")
    gen.add_argument("--keep-reasoning", action="store_true", help="思考の文を .reasoning.txt に残す")
    gen.add_argument("--condition", help="比較の条件名（例: tier0 / tier1）。記録に残す")
    gen.add_argument("--timeout", type=float, default=900)
    gen.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)

    if args.command == "models":
        try:
            for entry in list_models():
                meta = entry.get("meta") or {}
                print(f"{entry.get('id')}\t{meta.get('label', '')}\t{','.join(meta.get('aliases') or [])}")
        except LocalWriterError as error:
            print(f"[ERROR] {error}", file=sys.stderr)
            return 1
        return 0
    return generate(args)


if __name__ == "__main__":
    sys.exit(main())
