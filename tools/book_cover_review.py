#!/usr/bin/env python3
"""Review cover.yaml layout, base art, fonts, and rights for a novel package."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from book_package.cover import has_cover_layout, load_package_cover
from book_package.review import review_package


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def resolve_novel_dir(value: str) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (repo_root() / path).resolve()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "表紙構成（cover.yaml）と書誌・書体・権利を検査する。"
            "cover.yaml が無い作品は従来の publishing review のみ行う。"
        )
    )
    parser.add_argument("novel", help="作品フォルダ")
    parser.add_argument(
        "--target",
        choices=("reader", "paper", "ebook", "web"),
        default="reader",
        help="検査ターゲット（reader は paper ゲート相当で表紙中心に見る）。",
    )
    parser.add_argument(
        "--gate",
        choices=("writing", "export"),
        default="writing",
        help="writing=情報提示、export=公開・販売前の厳格ゲート。",
    )
    parser.add_argument("--json", action="store_true", help="結果を JSON で出力する。")
    args = parser.parse_args(argv)

    root = resolve_novel_dir(args.novel)
    if not (root / "book.yaml").is_file():
        print(f"error: book.yaml がありません: {root}", file=sys.stderr)
        return 2

    target = "paper" if args.target == "reader" else args.target
    result = review_package(root, gate=args.gate, target=target)
    cover_findings = [
        finding
        for finding in result.findings
        if finding.rule.startswith("P-V")
        or finding.rule in {"P-E01", "P-R01", "P-R03"}
    ]
    layout_present = has_cover_layout(root)
    layout_summary: dict | None = None
    if layout_present:
        try:
            layout = load_package_cover(root)
            if layout is not None:
                layout_summary = {
                    "base_art": layout.base_art.illustration_id,
                    "layer_count": len(layout.layers),
                    "font_refs": sorted(layout.fonts.keys()),
                    "profiles": sorted(layout.profiles.keys()),
                }
        except ValueError as exc:
            layout_summary = {"error": str(exc)}

    payload = {
        "package_root": str(root),
        "target": args.target,
        "gate": args.gate,
        "cover_yaml": layout_present,
        "layout": layout_summary,
        "cover_findings": [
            {
                "rule": f.rule,
                "severity": f.severity,
                "message": f.message,
                "suggested_action": f.suggested_action,
            }
            for f in cover_findings
        ],
        "all_findings_count": len(result.findings),
        "has_errors": result.has_errors
        or any(f.severity == "error" for f in cover_findings),
    }

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"package: {root}")
        print(f"cover.yaml: {'yes' if layout_present else 'no (art-only compat)'}")
        if layout_summary and "error" not in layout_summary:
            print(
                f"base_art: {layout_summary['base_art']} "
                f"layers={layout_summary['layer_count']} "
                f"fonts={','.join(layout_summary['font_refs']) or '-'}"
            )
        elif layout_summary and "error" in layout_summary:
            print(f"layout error: {layout_summary['error']}")
        if not cover_findings:
            print("cover findings: (none)")
        for finding in cover_findings:
            print(
                f"[{finding.severity}] {finding.rule}: {finding.message}"
            )
        if payload["has_errors"]:
            print("result: FAIL")
        else:
            print("result: OK")

    return 1 if payload["has_errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
