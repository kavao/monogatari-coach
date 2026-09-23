#!/usr/bin/env python3
"""Re-run paper-proof preflight from a generated build directory."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from book_package.preflight import PreflightError, preflight_paper_build


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生成済み paper proof PDF を再検査する。")
    parser.add_argument("build_dir", type=Path, help="_publication_output/<build-id> ディレクトリ")
    parser.add_argument("--target", choices=("paper",), default="paper")
    parser.add_argument("--json", action="store_true", help="結果を JSON で標準出力する。")
    args = parser.parse_args(argv)

    build_dir = args.build_dir.resolve()
    manifest_path = build_dir / "manifest.json"
    pdf_path = build_dir / "interior.pdf"
    reader_proof_path = build_dir / "reader-proof.pdf"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        result = preflight_paper_build(pdf_path, reader_proof_path, manifest)
    except (OSError, json.JSONDecodeError, PreflightError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    output = build_dir / "preflight.json"
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(
            f"preflight: errors={result['summary']['errors']} "
            f"warnings={result['summary']['warnings']} ({output})"
        )
    return 0 if result["summary"]["errors"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
