"""Phase 0 Expand 方式 Spike（計画書 §51）。

Insertion Expand（元文を残し、文と文の間へ描写を足す）と Rewrite Expand（範囲全体を
書き直して膨らませる）を、GLM-4.6 / Xialong で比べる。

方式:
- ``insertion-chat``: 本文全体に挿入位置の印を付けて渡し、挟む文だけを書かせる
- ``insertion-completions``: 挿入位置までの本文を渡し、改行までの続きを書かせる
- ``rewrite-chat``: 本文全体を約 1.5 倍に書き直させる

自動指標（元文保持率・削除文・改変文・台詞保持率・新しいカタカナ語・後文の先取り）を出し、
自然度・追加描写の質・指示遵守は ``review.md`` で人が採点する。既定は dry-run。
同時生成は 1 本までなので直列に送り、429 は少し待って再送する。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from metron.repair import original_retention_ratio, sentence_char_ngram_jaccard, split_sentences

from . import novelai as nai
from .spike import REPO_ROOT, STANDARD_SAMPLING, _abbreviate

OUT_ROOT = REPO_ROOT / "_workingspace" / "ai_writer" / "phase0_expand"
GAP = "◆"
REWRITE_RATIO = 1.5
"""Insertion も Rewrite も、足す量を原文の (REWRITE_RATIO - 1) 倍に揃えて比べる。"""
MODIFIED_JACCARD = 0.5
RETRY_429 = 3


@dataclass(frozen=True)
class Fixture:
    id: str
    label: str
    marked: str
    """挿入位置を ``◆`` で示した原文。"""
    names: tuple[str, ...]

    @property
    def original(self) -> str:
        return self.marked.replace(GAP, "")

    @property
    def gap_count(self) -> int:
        return self.marked.count(GAP)

    def prefix_before_gap(self, index: int) -> str:
        parts = self.marked.split(GAP)
        return "".join(parts[: index + 1])

    def suffix_after_gap(self, index: int) -> str:
        parts = self.marked.split(GAP)
        return "".join(parts[index + 1:])

    def marked_for_gap(self, index: int) -> str:
        parts = self.marked.split(GAP)
        return "".join(parts[: index + 1]) + "【ここに挿入】" + "".join(parts[index + 1:])

    @property
    def insert_chars_per_gap(self) -> int:
        return max(20, int(len(self.original) * (REWRITE_RATIO - 1) / self.gap_count))

    def splice(self, insertions: list[str]) -> str:
        parts = self.marked.split(GAP)
        out = parts[0]
        for text, part in zip(insertions, parts[1:]):
            out += text + part
        return out


FIXTURES: tuple[Fixture, ...] = (
    Fixture(
        "explore", "不穏な探索（台詞なし）",
        "　駅のホームには誰もいなかった。錆びた時刻表が風に揺れ、最終列車の時刻だけが赤いペンで丸く囲まれている。◆"
        "悠真はベンチの下に手を伸ばし、湿った落ち葉をかき分けた。指先が、布の端に触れた。\n"
        "　引き出したのは、色の褪せた水色のリボンだった。◆妹の美緒が、あの日の朝に結んでいたものだ。"
        "悠真はリボンを握りしめたまま、しばらく動けなかった。",
        ("悠真", "美緒"),
    ),
    Fixture(
        "dialogue", "日常会話（台詞あり）",
        "　放課後の図書室は、窓から差す西日でオレンジ色に染まっていた。\n"
        "「また同じ本、借りるの？」\n"
        "　カウンターの向こうで、早紀が首をかしげた。◆\n"
        "「続きが気になって、眠れないんだよ」\n"
        "　陽太は貸出カードを差し出した。◆早紀は小さく笑って、判子を押した。\n"
        "「返却は来週の金曜日まで。延滞したら、次は貸さないからね」",
        ("早紀", "陽太"),
    ),
)

INSERTION_RULES = (
    "条件:\n"
    "- 新しい出来事、新しい人物、新しい場所、新しい事実を足さない。\n"
    "- 足してよいのは、情景、感情、動作の細部だけ。\n"
    "- 前後の文を繰り返したり、先の展開を書いたりしない。\n"
    "- 地の文で書く。台詞は足さない。\n"
)


def _chat_body(model: str, user: str, max_tokens: int) -> dict[str, Any]:
    return nai.build_chat_body(
        model,
        [{"role": "system", "content": "あなたは日本語の小説の編集者です。指示された出力だけを返し、前置きや説明は書きません。"},
         {"role": "user", "content": user}],
        max_tokens=max_tokens, sampling=STANDARD_SAMPLING)


def _insertion_chat_request(fx: Fixture, model: str, gap: int) -> tuple[str, dict[str, Any]]:
    user = (f"次の小説本文の【ここに挿入】の位置に入れる文を、{fx.insert_chars_per_gap}字ほど（1〜2文）で書いてください。"
            "挿入する文だけを出力してください。\n\n" + INSERTION_RULES + "\n本文:\n" + fx.marked_for_gap(gap))
    return nai.TEXT_HOST + nai.CHAT_PATH, _chat_body(model, user, max_tokens=300)


def _insertion_completions_request(fx: Fixture, model: str, gap: int) -> tuple[str, dict[str, Any]]:
    body = nai.build_completions_body(model, fx.prefix_before_gap(gap), max_tokens=int(fx.insert_chars_per_gap * 1.5 / 1.3),
                                      sampling=STANDARD_SAMPLING, stop=["\n"])
    return nai.TEXT_HOST + nai.COMPLETIONS_PATH, body


def _rewrite_request(fx: Fixture, model: str) -> tuple[str, dict[str, Any]]:
    target = int(len(fx.original) * REWRITE_RATIO)
    user = (f"次の小説本文を、約{target}字（元の約{REWRITE_RATIO}倍）に膨らませて書き直してください。"
            "書き直した本文だけを出力してください。\n\n"
            "条件:\n"
            "- 元の出来事、事実、人物、順序をすべて残す。\n"
            "- 台詞（「」の中）は一字一句変えない。台詞を足さない。\n"
            "- 新しい出来事、新しい人物、新しい場所、新しい事実を足さない。\n"
            "- 情景、感情、動作の細部を足して膨らませる。\n"
            "\n本文:\n" + fx.original)
    return nai.TEXT_HOST + nai.CHAT_PATH, _chat_body(model, user, max_tokens=900)


@dataclass(frozen=True)
class Method:
    name: str
    mode: str  # insertion / rewrite
    per_gap: bool
    build: Callable[..., tuple[str, dict[str, Any]]]


METHODS: tuple[Method, ...] = (
    Method("insertion-chat", "insertion", True, _insertion_chat_request),
    Method("insertion-completions", "insertion", True, _insertion_completions_request),
    Method("rewrite-chat", "rewrite", False, _rewrite_request),
)


# ---- 指標 -------------------------------------------------------------------

_DIALOGUE_RE = re.compile(r"「[^「」]*」")
_KATAKANA_RE = re.compile(r"[ァ-ヴー]{2,}")


_SENTENCE_END = "。！？」"


_TRAILER_RE = re.compile(r"^\s*(?:\*{3,}|-{3,}|【解説】|【中文翻译】|【翻訳】|\[|書き手の意図|解説[:：])", re.MULTILINE)


def cut_trailer(text: str) -> str:
    """本文の後ろに続く区切り（``***`` など）や解説・自己採点を切り落とす。"""
    match = _TRAILER_RE.search(text)
    return text[: match.start()] if match else text


def clean_insertion(text: str) -> str:
    """挿入文の前後の空白・改行と挿入印を落とし、最初の段落だけを残して、途中で切れた末尾の文を除く。

    挿入は 1〜2 文なので、2 段落目以降は解説や自己採点とみなす（Xialong で観測）。
    """
    text = text.strip().strip("　").strip()
    text = next((line.strip() for line in text.splitlines() if line.strip()), "")
    if text.startswith("【ここに挿入】"):
        text = text[len("【ここに挿入】"):].strip()
    if text and text[-1] not in _SENTENCE_END:
        cut = max(text.rfind(c) for c in _SENTENCE_END)
        if cut >= 0:
            text = text[: cut + 1]
    return text


def rewrite_metrics(original: str, candidate: str) -> dict[str, Any]:
    """Rewrite Expand 用（計画書 §19 Original Preservation Guard の試作）。"""
    src = split_sentences(original)
    cand = split_sentences(candidate)
    cand_set = set(cand)
    deleted: list[str] = []
    modified: list[dict[str, Any]] = []
    for sentence in src:
        if sentence in cand_set:
            continue
        best = max(cand, key=lambda c: sentence_char_ngram_jaccard(sentence, c), default="")
        score = sentence_char_ngram_jaccard(sentence, best) if best else 0.0
        if score >= MODIFIED_JACCARD:
            modified.append({"original": sentence, "candidate": best, "jaccard": round(score, 3)})
        else:
            deleted.append(sentence)
    dialogues = _DIALOGUE_RE.findall(original)
    kept = [d for d in dialogues if d in candidate]
    return {
        "retention_ratio": round(original_retention_ratio(original, candidate), 3),
        "expansion_ratio": round(len(candidate) / len(original), 3) if original else None,
        "deleted_count": len(deleted),
        "modified_count": len(modified),
        "deleted": deleted,
        "modified": modified,
        "dialogue_preservation": round(len(kept) / len(dialogues), 3) if dialogues else None,
        "dialogue_added": len(_DIALOGUE_RE.findall(candidate)) - len(dialogues),
    }


def insertion_metrics(fx: Fixture, insertions: list[str]) -> dict[str, Any]:
    """Insertion Expand 用。元文は構造上すべて残るので、挿入文の逸脱を見る。"""
    per_gap = []
    for gap, text in enumerate(insertions):
        following = split_sentences(fx.suffix_after_gap(gap))
        nxt = following[0] if following else ""
        per_gap.append({
            "gap": gap,
            "chars": len(text),
            "next_sentence_jaccard": round(sentence_char_ngram_jaccard(text, nxt), 3) if nxt and text else 0.0,
            "dialogue_added": len(_DIALOGUE_RE.findall(text)),
        })
    candidate = fx.splice(insertions)
    return {
        "retention_ratio": round(original_retention_ratio(fx.original, candidate), 3),
        "added_chars": sum(len(t) for t in insertions),
        "expansion_ratio": round(len(candidate) / len(fx.original), 3),
        "per_gap": per_gap,
    }


def common_metrics(fx: Fixture, candidate: str) -> dict[str, Any]:
    new_katakana = sorted({w for w in _KATAKANA_RE.findall(candidate) if w not in fx.original})
    return {
        "names_kept": {n: (n in candidate) for n in fx.names},
        "new_katakana": new_katakana,
        "markdown": "**" in candidate or "***" in candidate,
    }


# ---- 実行 -------------------------------------------------------------------

def clean_rewrite(text: str) -> str:
    """書き直し本文の前後の改行と、後ろに続く区切り・解説を落とす。"""
    return cut_trailer(text).strip("\n").rstrip()


def score_cell(fx: Fixture, method: Method, outputs: list[str]) -> tuple[list[str], str, dict[str, Any]]:
    """生の出力から、整形済みの挿入文・候補本文・指標を作る。"""
    if method.mode == "insertion":
        insertions = [clean_insertion(t) for t in outputs]
        candidate = fx.splice(insertions)
        metrics = insertion_metrics(fx, insertions)
        trimmed = sum(len(t.strip()) - len(i) for t, i in zip(outputs, insertions))
    else:
        insertions = []
        candidate = clean_rewrite(outputs[0])
        metrics = rewrite_metrics(fx.original, candidate)
        trimmed = len(outputs[0].strip()) - len(candidate.strip())
    metrics.update(common_metrics(fx, candidate))
    metrics["trimmed_chars"] = max(0, trimmed)
    return insertions, candidate, metrics


def _cells(fixtures: list[str] | None, models: list[str] | None, methods: list[str] | None) -> list[tuple[Fixture, str, Method]]:
    known = {m.name for m in METHODS}
    bad = [m for m in methods or [] if m not in known]
    if bad:
        raise SystemExit(f"未知の方式: {', '.join(bad)}")
    return [(fx, model, method)
            for fx in FIXTURES if not fixtures or fx.id in fixtures
            for model in nai.CHAT_MODELS if not models or model in models
            for method in METHODS if not methods or method.name in methods]


def _requests(fx: Fixture, model: str, method: Method) -> list[tuple[str, dict[str, Any]]]:
    if method.per_gap:
        return [method.build(fx, model, gap) for gap in range(fx.gap_count)]
    return [method.build(fx, model)]


def _call(url: str, token: str, body: dict[str, Any], headers: dict[str, str]) -> nai.CallResult:
    result = nai.call_stream(url, token, body, headers=headers)
    for attempt in range(RETRY_429):
        if result.status != 429:
            break
        time.sleep(2.0 * (attempt + 1))
        result = nai.call_stream(url, token, body, headers=headers)
    return result


def run_cell(fx: Fixture, model: str, method: Method, sample: int, token: str, headers: dict[str, str]) -> dict[str, Any]:
    calls = []
    outputs: list[str] = []
    for url, body in _requests(fx, model, method):
        res = _call(url, token, body, headers)
        calls.append({"url": url, "body": body, "result": res.to_dict()})
        outputs.append(res.text)
    ok = all(c["result"]["status"] == 200 for c in calls)
    insertions, candidate, metrics = score_cell(fx, method, outputs)
    return {"fixture": fx.id, "model": model, "method": method.name, "mode": method.mode, "sample": sample, "ok": ok,
            "original": fx.original, "insertions": insertions, "candidate": candidate, "metrics": metrics,
            "calls": [{**c, "body": c["body"]} for c in calls]}


def _review_md(records: list[dict[str, Any]], run_id: str) -> str:
    lines = [f"# Expand 方式比較 {run_id}", "",
             "自然度・追加描写の質・指示遵守は 1〜5、新規の出来事は 有/無 で記入する。", "",
             "| 原文 | モデル | 方式 | # | 保持率 | 膨張率 | 削除 | 改変 | 台詞保持 | 新カタカナ | 切落字数 | 自然度 | 描写 | 遵守 | 新出来事 |",
             "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for r in records:
        m = r["metrics"]
        lines.append(f"| {r['fixture']} | {r['model']} | {r['method']} | {r['sample']} | {m.get('retention_ratio')} | "
                     f"{m.get('expansion_ratio')} | {m.get('deleted_count', '-')} | {m.get('modified_count', '-')} | "
                     f"{m.get('dialogue_preservation', '-') if m.get('dialogue_preservation') is not None else '-'} | "
                     f"{'、'.join(m.get('new_katakana') or []) or '-'} | {m.get('trimmed_chars', '-')} |  |  |  |  |")
    for r in records:
        lines += ["", f"## {r['fixture']} / {r['model']} / {r['method']} / #{r['sample']}", ""]
        if not r["ok"]:
            errs = [c["result"].get("error") for c in r["calls"] if c["result"]["status"] != 200]
            lines += [f"失敗: {errs}", ""]
        if r["insertions"]:
            for i, text in enumerate(r["insertions"]):
                lines.append(f"- 挿入{i + 1}: {text or '（空）'}")
            lines.append("")
        lines += ["```text", r["candidate"], "```"]
    return "\n".join(lines) + "\n"


def cmd_plan(args: argparse.Namespace) -> int:
    cells = _cells(args.fixture, args.model, args.method)
    n_calls = sum(len(_requests(fx, model, m)) for fx, model, m in cells) * args.samples
    print(f"セル {len(cells)} 件 × {args.samples} 回、生成 {n_calls} 回（直列）")
    for fx in FIXTURES:
        if args.fixture and fx.id not in args.fixture:
            continue
        print(f"\n# 原文 {fx.id}（{fx.label}、{len(fx.original)} 字、挿入位置 {fx.gap_count}）\n{fx.marked}")
    shown: set[str] = set()
    for fx, model, method in cells:
        if method.name in shown:
            continue
        shown.add(method.name)
        url, body = _requests(fx, model, method)[0]
        print(f"\n## 例: {method.name} / {fx.id} / {model}\nPOST {url}")
        print(json.dumps(_abbreviate(body, 600), ensure_ascii=False, indent=2))
    print("\n本番実行には run --execute を付けてください。")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    if not args.execute:
        return cmd_plan(args)
    cells = _cells(args.fixture, args.model, args.method)
    token = nai.load_token(REPO_ROOT)
    headers = nai.load_request_headers(REPO_ROOT)
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = OUT_ROOT / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    records = []
    for sample in range(1, args.samples + 1):
        for fx, model, method in cells:
            print(f"実行: {fx.id} / {model} / {method.name} / #{sample}", flush=True)
            rec = run_cell(fx, model, method, sample, token, headers)
            (out_dir / f"{fx.id}__{model}__{method.name}__{sample}.json").write_text(
                json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
            m = rec["metrics"]
            print(f"  ok={rec['ok']} 保持率={m.get('retention_ratio')} 膨張率={m.get('expansion_ratio')} "
                  f"削除={m.get('deleted_count', '-')} 改変={m.get('modified_count', '-')} 新カタカナ={m.get('new_katakana')}", flush=True)
            records.append(rec)
    (out_dir / "review.md").write_text(_review_md(records, run_id), encoding="utf-8")
    print(f"\n保存先: {out_dir}")
    return 0


def cmd_rescore(args: argparse.Namespace) -> int:
    """保存済みの生出力から整形と指標をやり直し、review.md を作り直す（通信しない）。"""
    run_dir = Path(args.run_dir)
    fixtures = {fx.id: fx for fx in FIXTURES}
    methods = {m.name: m for m in METHODS}
    order = [fx.id for fx in FIXTURES]
    records = []
    for path in sorted(run_dir.glob("*.json")):
        rec = json.loads(path.read_text(encoding="utf-8"))
        outputs = [c["result"]["text"] for c in rec["calls"]]
        rec["insertions"], rec["candidate"], rec["metrics"] = score_cell(
            fixtures[rec["fixture"]], methods[rec["method"]], outputs)
        path.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
        records.append(rec)
    records.sort(key=lambda r: (r["sample"], order.index(r["fixture"]), r["model"], r["method"]))
    (run_dir / "review.md").write_text(_review_md(records, run_dir.name), encoding="utf-8")
    print(f"再採点 {len(records)} 件: {run_dir / 'review.md'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    parser = argparse.ArgumentParser(description="Phase 0 Expand 方式比較（既定は dry-run）")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name, func in (("plan", cmd_plan), ("run", cmd_run)):
        sp = sub.add_parser(name)
        sp.add_argument("--fixture", action="append", help="原文 ID（explore / dialogue）")
        sp.add_argument("--model", action="append", help="モデル ID")
        sp.add_argument("--method", action="append", help="方式名")
        sp.add_argument("--samples", type=int, default=2, help="各セルの試行回数（既定 2）")
        if name == "run":
            sp.add_argument("--execute", action="store_true", help="実際に NovelAI へ送信する")
        sp.set_defaults(func=func)
    rs = sub.add_parser("rescore", help="保存済みの結果を通信せずに整形・再採点する")
    rs.add_argument("run_dir", help="_workingspace/ai_writer/phase0_expand/<run>")
    rs.set_defaults(func=cmd_rescore)
    args = parser.parse_args(argv)
    return args.func(args)
