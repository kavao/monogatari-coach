#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
足切り評価ファイルの必須項目チェック（Monogatari Coach）。

_reader/YYYYMMDD_HHMM.md の新形式（6項目100点）に必要な見出し・値が
揃っているかを機械確認する。

終了コード:
  0  全チェック通過
  1  1件以上の ERROR がある（必須欠落）
  2  ERROR はないが WARNING がある（推奨欠落）
  3  対象ファイルが見つからない・引数エラー

運用: .rulesync/skills/novel-reader-output/SKILL.md を参照。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# ─── 必須チェック項目 ──────────────────────────────────────────────────────
# (名称, 正規表現, レベル, 説明)
_CHECKS: list[tuple[str, re.Pattern, str, str]] = [
    (
        "判定",
        re.compile(r"読むべき|読まなくていい"),
        "ERROR",
        "「読むべき」または「読まなくていい」が見つかりません",
    ),
    (
        "総合点/100",
        re.compile(r"(?<!\d)\d{1,3}\s*/\s*100(?!\d)"),
        "ERROR",
        "XX / 100 形式の総合点が見つかりません（新形式必須）",
    ),
    (
        "5段階評価/5.0",
        re.compile(r"\d+\.?\d*\s*/\s*5\.?0?"),
        "WARN",
        "5段階換算（XX.X / 5.0）が見つかりません",
    ),
    (
        "ゲート段階G1/G2/G3",
        re.compile(r"G[123]"),
        "WARN",
        "ゲート段階（G1/G2/G3）の記載が見つかりません",
    ),
    (
        "評価項目:冒頭の牽引力",
        re.compile(r"冒頭の牽引力|冒頭.*牽引"),
        "ERROR",
        "評価内訳の「冒頭の牽引力」が見つかりません",
    ),
    (
        "評価項目:キャラクター",
        re.compile(r"キャラクター"),
        "ERROR",
        "評価内訳の「キャラクター」が見つかりません",
    ),
    (
        "評価項目:プロット期待値",
        re.compile(r"プロット"),
        "ERROR",
        "評価内訳の「プロット期待値」が見つかりません",
    ),
    (
        "評価項目:文章力",
        re.compile(r"文章力"),
        "ERROR",
        "評価内訳の「文章力」が見つかりません",
    ),
    (
        "評価項目:わかりやすさ",
        re.compile(r"わかりやすさ"),
        "ERROR",
        "評価内訳の「わかりやすさ」が見つかりません",
    ),
    (
        "評価項目:独創性",
        re.compile(r"独創性"),
        "ERROR",
        "評価内訳の「独創性」が見つかりません",
    ),
    (
        "判定理由 or 足切り理由",
        re.compile(r"判定理由|足切り理由"),
        "ERROR",
        "「判定理由」または「足切り理由」セクションが見つかりません",
    ),
    (
        "改善点",
        re.compile(r"改善"),
        "WARN",
        "「改善点」セクションが見つかりません",
    ),
]

_NEW_FORMAT_PATTERN = re.compile(r"^\d{8}_\d{4}\.md$")


def _strip_frontmatter(text: str) -> str:
    if not text.startswith("---"):
        return text
    lines = text.splitlines(keepends=True)
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return "".join(lines[i + 1:])
    return text


def lint_file(path: Path, *, strict: bool = False) -> list[dict]:
    """単一ファイルをチェックし、問題リストを返す。"""
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return [{"level": "ERROR", "check": "ファイル読み込み", "message": str(e)}]

    body = _strip_frontmatter(raw)
    full = raw  # フロントマター込みでも検索（ゲート段階など）

    issues = []
    for name, pattern, level, message in _CHECKS:
        if not pattern.search(full):
            if level == "ERROR" or strict:
                issues.append({"level": level, "check": name, "message": message})
    return issues


def _resolve_targets(path_arg: Path) -> list[Path]:
    """引数からチェック対象ファイルのリストを返す。"""
    p = path_arg.resolve()
    if p.is_file():
        return [p]
    reader_dir = p / "_reader"
    if not reader_dir.is_dir():
        return []
    # 最新の YYYYMMDD_HHMM.md のみ対象（1ファイル）
    candidates = sorted(
        [f for f in reader_dir.glob("*.md") if _NEW_FORMAT_PATTERN.match(f.name)],
        reverse=True,
    )
    return candidates[:1] if candidates else []


def run(targets: list[Path], *, strict: bool, json_out: bool) -> int:
    if not targets:
        print("対象の評価ファイルが見つかりません。", file=sys.stderr)
        return 3

    import json as _json

    all_results = []
    has_error = False
    has_warn = False

    for path in targets:
        issues = lint_file(path, strict=strict)
        errors = [i for i in issues if i["level"] == "ERROR"]
        warns = [i for i in issues if i["level"] == "WARN"]
        if errors:
            has_error = True
        if warns:
            has_warn = True
        all_results.append({"file": path.name, "issues": issues})

    if json_out:
        print(_json.dumps(all_results, ensure_ascii=False, indent=2))
        return 1 if has_error else (2 if has_warn else 0)

    # ─── 人間向け出力 ──────────────────────────────────────────
    total_checks = len(_CHECKS)
    for result in all_results:
        path_name = result["file"]
        issues = result["issues"]
        errors = [i for i in issues if i["level"] == "ERROR"]
        warns = [i for i in issues if i["level"] == "WARN"]
        passed = total_checks - len(issues)

        print(f"\n=== {path_name} lint ===")
        print(f"    通過: {passed}/{total_checks}  ERROR: {len(errors)}  WARN: {len(warns)}")

        if not issues:
            print("    ✓ 全チェック通過")
        else:
            for issue in sorted(issues, key=lambda x: (x["level"] != "ERROR", x["check"])):
                mark = "✗" if issue["level"] == "ERROR" else "△"
                print(f"    {mark} [{issue['level']}] {issue['check']}")
                print(f"         {issue['message']}")

    if has_error:
        return 1
    if has_warn:
        return 2
    return 0


def main(argv: list[str] | None = None) -> int:
    from console_io import configure_stdio_utf8

    configure_stdio_utf8()

    p = argparse.ArgumentParser(
        description="First Reader 評価ファイルの必須項目を機械チェックする。"
    )
    p.add_argument(
        "target",
        type=Path,
        help="評価ファイル（_reader/YYYYMMDD_HHMM.md）または作品フォルダ（最新ファイルを自動選択）",
    )
    p.add_argument(
        "--strict",
        action="store_true",
        help="WARN 項目も ERROR として扱い、終了コード 1 で返す",
    )
    p.add_argument("--json", action="store_true", help="JSON で出力")

    args = p.parse_args(argv)
    targets = _resolve_targets(args.target)
    return run(targets, strict=args.strict, json_out=args.json)


if __name__ == "__main__":
    raise SystemExit(main())
