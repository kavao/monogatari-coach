#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
小説本文の句読点指標を集計する。

地の文と会話文を分離し、読点密度・一文あたり読点数・平均文長・
接続助詞後読点率・句点誤配置を出す。既定は計測のみ。
--gate を付けたときだけ、短文かつ高密度の合否を終了コードで返す。
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import unicodedata
from pathlib import Path
from typing import Any

from novel_char_count import (
    _PUBLISHING_DIRECTIVE,
    collect_targets,
    discover_all_novel_text,
    strip_yaml_front_matter,
)

OPEN_TO_CLOSE = {"「": "」", "『": "』"}
SENTENCE_END = frozenset("。！？")
COMMA = "、"
CONJ_AFTER_COMMA = re.compile(
    r"(?:けれども|けれど|けど|ので|のに|ても|でも|から|が|て|で|し)、"
)
HEADING_OR_META = re.compile(r"^\s*(?:#|<!--|---)")

# 短文かつ高密度だけを落とす。片方だけの逸脱は通す。
GATE_DENSITY_MAX = 36.0
GATE_MEAN_LEN_MIN = 28.0
GATE_MIN_NARRATION_CHARS = 800


def extract_body(text: str) -> str:
    body = strip_yaml_front_matter(text)
    body = _PUBLISHING_DIRECTIVE.sub("", body)
    kept: list[str] = []
    for line in body.splitlines():
        if HEADING_OR_META.match(line):
            continue
        kept.append(line)
    return unicodedata.normalize("NFC", "\n".join(kept))


def split_narration_dialogue(text: str) -> tuple[str, list[str]]:
    narration_parts: list[str] = []
    dialogues: list[str] = []
    stack: list[str] = []
    buf: list[str] = []
    for ch in text:
        if not stack and ch in OPEN_TO_CLOSE:
            narration_parts.append("".join(buf))
            buf = []
            stack.append(OPEN_TO_CLOSE[ch])
            continue
        if stack and ch == stack[-1]:
            stack.pop()
            if not stack:
                dialogues.append("".join(buf))
                buf = []
            else:
                buf.append(ch)
            continue
        if stack and ch in OPEN_TO_CLOSE:
            stack.append(OPEN_TO_CLOSE[ch])
        buf.append(ch)
    if stack:
        dialogues.append("".join(buf))
    else:
        narration_parts.append("".join(buf))
    return "".join(narration_parts), dialogues


def iter_sentences(text: str) -> list[str]:
    sentences: list[str] = []
    buf: list[str] = []
    for ch in text:
        buf.append(ch)
        if ch in SENTENCE_END:
            sentence = "".join(buf).strip().lstrip("　 \t")
            if sentence:
                sentences.append(sentence)
            buf = []
    tail = "".join(buf).strip().lstrip("　 \t")
    if tail:
        sentences.append(tail)
    return sentences


def _percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    rank = (len(ordered) - 1) * (p / 100.0)
    lo = int(rank)
    hi = min(lo + 1, len(ordered) - 1)
    frac = rank - lo
    return float(ordered[lo] + (ordered[hi] - ordered[lo]) * frac)


def _ratio(numer: int, denom: int) -> float | None:
    if denom <= 0:
        return None
    return numer / denom


def _density_per_1000(count: int, chars: int) -> float | None:
    ratio = _ratio(count, chars)
    if ratio is None:
        return None
    return ratio * 1000.0


def measure_text(text: str) -> dict[str, Any]:
    body = extract_body(text)
    narration, dialogues = split_narration_dialogue(body)
    dialogue_text = "".join(dialogues)

    chars_total = len(body)
    chars_narration = len(narration)
    chars_dialogue = len(dialogue_text)

    comma_narration = narration.count(COMMA)
    comma_dialogue = dialogue_text.count(COMMA)
    comma_total = body.count(COMMA)

    sentences = iter_sentences(narration)
    sentence_lens = [len(s) for s in sentences]
    commas_per_sentence = [float(s.count(COMMA)) for s in sentences]

    conj_count = len(CONJ_AFTER_COMMA.findall(body))
    period_before_close = body.count("。」")
    period_inside_dialogue = sum(d.count("。") for d in dialogues)

    return {
        "chars_total": chars_total,
        "chars_narration": chars_narration,
        "chars_dialogue": chars_dialogue,
        "dialogue_ratio": _ratio(chars_dialogue, chars_total),
        "comma_total": comma_total,
        "comma_narration": comma_narration,
        "comma_dialogue": comma_dialogue,
        "comma_density_narration": _density_per_1000(comma_narration, chars_narration),
        "comma_density_total": _density_per_1000(comma_total, chars_total),
        "sentence_count_narration": len(sentences),
        "sentence_mean_len_narration": (
            statistics.fmean(sentence_lens) if sentence_lens else None
        ),
        "commas_per_sentence": {
            "median": _percentile(commas_per_sentence, 50),
            "p75": _percentile(commas_per_sentence, 75),
            "p90": _percentile(commas_per_sentence, 90),
            "max": max(commas_per_sentence) if commas_per_sentence else None,
        },
        "conjunction_after_comma_count": conj_count,
        "conjunction_after_comma_rate": _ratio(conj_count, comma_total),
        "period_before_close": period_before_close,
        "period_inside_dialogue": period_inside_dialogue,
        "_sentence_lens": sentence_lens,
        "_commas_per_sentence": commas_per_sentence,
    }


def _novel_key(path: Path, repo_root: Path) -> str:
    try:
        rel = path.relative_to(repo_root)
    except ValueError:
        return path.parent.name
    parts = rel.parts
    if len(parts) >= 2 and parts[0] == "novels":
        return parts[1]
    return path.parent.name


def measure_file(path: Path, repo_root: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    metrics = measure_text(text)
    try:
        rel = path.relative_to(repo_root).as_posix()
    except ValueError:
        rel = path.as_posix()
    metrics["path"] = rel
    metrics["novel"] = _novel_key(path, repo_root)
    return metrics


def public_metrics(row: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if not key.startswith("_")}


def evaluate_gate(metrics: dict[str, Any]) -> dict[str, Any]:
    """短文かつ高密度なら fail。地の文が短い場合は skip。"""
    density = metrics.get("comma_density_narration")
    mean_len = metrics.get("sentence_mean_len_narration")
    narration = metrics.get("chars_narration") or 0
    label = metrics.get("path") or metrics.get("label") or metrics.get("novel") or ""
    result: dict[str, Any] = {
        "label": label,
        "chars_narration": narration,
        "comma_density_narration": density,
        "sentence_mean_len_narration": mean_len,
        "rule": (
            f"comma_density_narration > {GATE_DENSITY_MAX} "
            f"and sentence_mean_len_narration < {GATE_MEAN_LEN_MIN}"
        ),
    }
    if narration < GATE_MIN_NARRATION_CHARS:
        result["status"] = "skip"
        result["reason"] = f"地の文が {GATE_MIN_NARRATION_CHARS} 字未満"
        return result
    if density is None or mean_len is None:
        result["status"] = "skip"
        result["reason"] = "密度または平均文長を計算できない"
        return result
    if density > GATE_DENSITY_MAX and mean_len < GATE_MEAN_LEN_MIN:
        result["status"] = "fail"
        result["reason"] = "短文かつ高密度"
        return result
    result["status"] = "pass"
    result["reason"] = "閾値内"
    return result


def evaluate_gates(rows: list[dict[str, Any]]) -> dict[str, Any]:
    results = [evaluate_gate(row) for row in rows]
    failed = [row for row in results if row["status"] == "fail"]
    return {
        "results": results,
        "fail_count": len(failed),
        "status": "fail" if failed else "pass",
    }


def merge_metrics(rows: list[dict[str, Any]], *, label: str) -> dict[str, Any]:
    if not rows:
        raise ValueError("merge_metrics: rows が空です")
    chars_total = sum(r["chars_total"] for r in rows)
    chars_narration = sum(r["chars_narration"] for r in rows)
    chars_dialogue = sum(r["chars_dialogue"] for r in rows)
    comma_total = sum(r["comma_total"] for r in rows)
    comma_narration = sum(r["comma_narration"] for r in rows)
    comma_dialogue = sum(r["comma_dialogue"] for r in rows)
    sentence_count = sum(r["sentence_count_narration"] for r in rows)
    conj_count = sum(r["conjunction_after_comma_count"] for r in rows)
    sentence_lens: list[int] = []
    commas_per_sentence: list[float] = []
    for row in rows:
        sentence_lens.extend(row.get("_sentence_lens") or [])
        commas_per_sentence.extend(row.get("_commas_per_sentence") or [])
    return {
        "label": label,
        "file_count": len(rows),
        "chars_total": chars_total,
        "chars_narration": chars_narration,
        "chars_dialogue": chars_dialogue,
        "dialogue_ratio": _ratio(chars_dialogue, chars_total),
        "comma_total": comma_total,
        "comma_narration": comma_narration,
        "comma_dialogue": comma_dialogue,
        "comma_density_narration": _density_per_1000(comma_narration, chars_narration),
        "comma_density_total": _density_per_1000(comma_total, chars_total),
        "sentence_count_narration": sentence_count,
        "sentence_mean_len_narration": (
            statistics.fmean(sentence_lens) if sentence_lens else None
        ),
        "commas_per_sentence": {
            "median": _percentile(commas_per_sentence, 50),
            "p75": _percentile(commas_per_sentence, 75),
            "p90": _percentile(commas_per_sentence, 90),
            "max": max(commas_per_sentence) if commas_per_sentence else None,
        },
        "conjunction_after_comma_count": conj_count,
        "conjunction_after_comma_rate": _ratio(conj_count, comma_total),
        "period_before_close": sum(r["period_before_close"] for r in rows),
        "period_inside_dialogue": sum(r["period_inside_dialogue"] for r in rows),
    }


def _fmt(value: Any, digits: int = 2) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def _fmt_pct(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value * 100:.1f}%"


def print_table(rows: list[dict[str, Any]], *, title_key: str) -> None:
    headers = (
        f"{'対象':<40}",
        "字",
        "地の文",
        "読点密度",
        "平均文長",
        "読点p50",
        "読点p90",
        "読点max",
        "接続助詞後",
        "会話比",
        "。」",
        "セリフ内。",
    )
    print("  ".join(headers))
    for row in rows:
        cps = row["commas_per_sentence"]
        title = str(row.get(title_key) or row.get("label") or "")
        if len(title) > 40:
            title = "…" + title[-39:]
        print(
            f"{title:<40}  "
            f"{row['chars_total']:6d}  "
            f"{row['chars_narration']:6d}  "
            f"{_fmt(row['comma_density_narration']):>8}  "
            f"{_fmt(row['sentence_mean_len_narration']):>8}  "
            f"{_fmt(cps['median']):>7}  "
            f"{_fmt(cps['p90']):>7}  "
            f"{_fmt(cps['max'], 0):>7}  "
            f"{_fmt_pct(row['conjunction_after_comma_rate']):>8}  "
            f"{_fmt_pct(row['dialogue_ratio']):>6}  "
            f"{row['period_before_close']:4d}  "
            f"{row['period_inside_dialogue']:6d}"
        )


def print_summary(merged: dict[str, Any]) -> None:
    cps = merged["commas_per_sentence"]
    print("")
    print("要約")
    print(f"  ファイル数: {merged['file_count']}")
    print(f"  総文字数: {merged['chars_total']}")
    print(f"  地の文文字数: {merged['chars_narration']}")
    print(f"  読点絶対数: {merged['comma_total']}（地の文 {merged['comma_narration']}）")
    print(f"  読点密度（地の文/1000字）: {_fmt(merged['comma_density_narration'])}")
    print(f"  平均文長（地の文）: {_fmt(merged['sentence_mean_len_narration'])}")
    print(
        "  一文あたり読点: "
        f"中央値 {_fmt(cps['median'])} / p90 {_fmt(cps['p90'])} / max {_fmt(cps['max'], 0)}"
    )
    print(f"  接続助詞後読点率: {_fmt_pct(merged['conjunction_after_comma_rate'])}")
    print(f"  会話文比率: {_fmt_pct(merged['dialogue_ratio'])}")
    print(
        f"  句点誤配置: 閉じ括弧直前 {merged['period_before_close']} / "
        f"セリフ内 {merged['period_inside_dialogue']}"
    )


def _print_gate(report: dict[str, Any]) -> None:
    print("")
    print("句読点ゲート")
    print(
        f"  判定: 地の文読点密度 > {GATE_DENSITY_MAX} かつ "
        f"平均文長 < {GATE_MEAN_LEN_MIN} なら fail"
    )
    for row in report["results"]:
        density = _fmt(row["comma_density_narration"])
        mean_len = _fmt(row["sentence_mean_len_narration"])
        print(
            f"  {row['status']}: {row['label'] or '（無題）'} "
            f"密度 {density} / 文長 {mean_len} / {row['reason']}"
        )
    print(f"  合計: {report['status']}（fail {report['fail_count']}）")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="小説本文の句読点指標を集計する。既定は計測のみ。"
    )
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="ファイル、作品フォルダ、または novels 配下のパス",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="novels/ 以下の全作品の _novel_text/novel_text*.md を対象にする",
    )
    parser.add_argument(
        "--by-novel",
        action="store_true",
        help="作品単位で集約して表示する",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="JSON を標準出力する",
    )
    parser.add_argument(
        "--gate",
        action="store_true",
        help="短文かつ高密度なら終了コード 1（計測と分離した合否）",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="リポジトリルート（未指定時は本スクリプトの親の親）",
    )
    args = parser.parse_args()

    script_dir = Path(__file__).resolve().parent
    repo_root = (args.repo_root or script_dir.parent).resolve()
    sys.path.insert(0, str(script_dir))

    if args.all:
        targets = discover_all_novel_text(repo_root)
    elif args.paths:
        targets = collect_targets(args.paths, repo_root)
    else:
        parser.print_help()
        print(
            "\n例: python tools/novel_punctuation_metrics.py novels/102_作品名",
            file=sys.stderr,
        )
        print(
            "    python tools/novel_punctuation_metrics.py --all --by-novel",
            file=sys.stderr,
        )
        return 2

    if not targets:
        print("対象となる novel_text*.md が見つかりません。", file=sys.stderr)
        return 1

    files: list[dict[str, Any]] = []
    for md in targets:
        try:
            files.append(measure_file(md, repo_root))
        except OSError as exc:
            print(f"読み込み失敗: {md}: {exc}", file=sys.stderr)
            return 1

    novels: list[dict[str, Any]] = []
    by_novel: dict[str, list[dict[str, Any]]] = {}
    for row in files:
        by_novel.setdefault(row["novel"], []).append(row)
    for name, rows in sorted(by_novel.items()):
        merged = merge_metrics(rows, label=name)
        merged["novel"] = name
        novels.append(merged)

    totals = merge_metrics(files, label="合計")
    gate_report = evaluate_gates(files) if args.gate else None
    payload = {
        "files": [public_metrics(row) for row in files],
        "novels": [public_metrics(row) for row in novels],
        "totals": public_metrics(totals),
    }
    if gate_report is not None:
        payload["gate"] = gate_report

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        if args.gate and gate_report["status"] == "fail":
            return 1
        return 0

    if args.by_novel or len(novels) > 1:
        print_table(novels, title_key="novel")
    else:
        print_table(files, title_key="path")
    print_summary(totals)
    if gate_report is not None:
        _print_gate(gate_report)
        if gate_report["status"] == "fail":
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
