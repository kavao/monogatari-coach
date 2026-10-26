"""NovelAI Provider の実 API 確認（Phase 1）。既定は dry-run で、送る内容をトークンを伏せて表示する。

- ``complete``: 短い生成を最後まで受け取る（status / 本文 / 出力トークン数を確認）
- ``cancel``: 指定字数に達したら止め、部分出力が ``incomplete`` で残り、スロットが返ることを確認

``--execute`` を付けたときだけ送信する。結果は ``_workingspace/ai_writer/phase1/<実行日時>/`` に JSON で残す。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from typing import Any

from . import novelai as nai
from .provider import GenerationRequest, NovelAIProvider
from .spike import REPO_ROOT, SCENE, STANDARD_SAMPLING

OUT_ROOT = REPO_ROOT / "_workingspace" / "ai_writer" / "phase1"
INSTRUCTION = "次の日本語の小説本文の続きを、地の文で150字ほど書いてください。続きの本文だけを出力してください。\n\n"


def build_request(model: str, endpoint: str, max_tokens: int) -> GenerationRequest:
    if endpoint == "chat":
        return GenerationRequest(model=model, endpoint="chat", max_tokens=max_tokens, sampling=STANDARD_SAMPLING,
                                 stop=("***",), messages=({"role": "user", "content": INSTRUCTION + SCENE},))
    return GenerationRequest(model=model, endpoint="completions", max_tokens=max_tokens, sampling=STANDARD_SAMPLING,
                             stop=("***",), prompt=SCENE)


def _checks(args: argparse.Namespace) -> list[tuple[str, GenerationRequest, int | None]]:
    req = build_request(args.model, args.endpoint, args.max_tokens)
    out: list[tuple[str, GenerationRequest, int | None]] = []
    if "complete" in args.check:
        out.append(("complete", req, None))
    if "cancel" in args.check:
        out.append(("cancel", req, args.cancel_after))
    return out


def run_check(provider: NovelAIProvider, name: str, req: GenerationRequest, cancel_after: int | None) -> dict[str, Any]:
    gen = provider.stream(req)
    with gen:
        text = ""
        for chunk in gen:
            text += chunk.text
            if cancel_after is not None and len(text) >= cancel_after:
                provider.cancel(gen)
                break
        result = gen.result()
    slot_free = provider._slot.acquire(blocking=False)  # noqa: SLF001 - 確認のための参照
    if slot_free:
        provider._slot.release()  # noqa: SLF001
    return {"check": name, "request": provider.preview(req), "result": result.to_dict(), "slot_released": slot_free}


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    parser = argparse.ArgumentParser(description="NovelAI Provider の実 API 確認（既定は dry-run）")
    parser.add_argument("--model", default="glm-4-6", choices=nai.CHAT_MODELS)
    parser.add_argument("--endpoint", default="chat", choices=("chat", "completions"))
    parser.add_argument("--max-tokens", type=int, default=200)
    parser.add_argument("--check", action="append", choices=("complete", "cancel"), help="既定は両方")
    parser.add_argument("--cancel-after", type=int, default=40, help="cancel で止める字数")
    parser.add_argument("--execute", action="store_true", help="実際に NovelAI へ送信する")
    args = parser.parse_args(argv)
    args.check = args.check or ["complete", "cancel"]
    checks = _checks(args)

    if not args.execute:
        dry = NovelAIProvider("dry-run", headers=nai.load_request_headers(REPO_ROOT))
        print(f"確認 {len(checks)} 件（生成 {len(checks)} 回、直列）")
        for name, req, cancel_after in checks:
            note = f"（{cancel_after} 字で cancel）" if cancel_after else ""
            print(f"\n## {name}{note}")
            print(json.dumps(dry.preview(req), ensure_ascii=False, indent=2))
        print("\n本番実行には --execute を付けてください。")
        return 0

    provider = NovelAIProvider.from_repo(REPO_ROOT)
    out_dir = OUT_ROOT / datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    records = []
    for name, req, cancel_after in checks:
        rec = run_check(provider, name, req, cancel_after)
        r = rec["result"]
        print(f"{name}: status={r['status']} cancelled={r['cancelled']} {len(r['text'])}字 {r['output_tokens']}tok "
              f"finish={r['finish_reason']} http={r['http_status']} 試行={r['attempts']} スロット返却={rec['slot_released']}")
        print(f"  本文: {r['text'][:80]}")
        records.append(rec)
    (out_dir / "provider_check.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n保存先: {out_dir}")
    return 0
