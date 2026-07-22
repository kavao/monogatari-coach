#!/usr/bin/env python3
"""Build a locked publishing package into a local paper proof PDF."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys

from book_package.build import BuildError, build_manifest, write_manifest
from book_package.preflight import PreflightError, preflight_paper_pdf
from book_package.render import RenderError, render_paper_proof


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def resolve_novel_dir(value: str) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (repo_root() / path).resolve()


def _build_id() -> str:
    return "paper-jis_b5-" + datetime.now().astimezone().strftime("%Y%m%dT%H%M%S%z")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="lock 済みの出版パッケージから JIS B5 の本文 proof PDF を生成する。"
    )
    parser.add_argument("novel", help="作品フォルダ")
    parser.add_argument("--target", choices=("paper",), default="paper")
    parser.add_argument("--profile", choices=("jis_b5",), default="jis_b5")
    parser.add_argument(
        "--build-id",
        default=None,
        help="出力先 _publication_output/<build-id>/ を明示する（省略時は時刻ベース）。",
    )
    parser.add_argument("--json", action="store_true", help="成果物の要約を JSON で出力する。")
    args = parser.parse_args(argv)

    root = resolve_novel_dir(args.novel)
    build_dir = root / "_publication_output" / (args.build_id or _build_id())
    if build_dir.exists():
        print(f"error: 出力先が既にあります: {build_dir}", file=sys.stderr)
        return 2

    try:
        manifest = build_manifest(root, target=args.target, profile=args.profile)
        build_dir.mkdir(parents=True)
        manifest_path = build_dir / "manifest.json"
        write_manifest(manifest_path, manifest)

        pdf_path = build_dir / "interior.pdf"
        render_paper_proof(manifest, pdf_path)
        write_manifest(manifest_path, manifest)

        preflight = preflight_paper_pdf(pdf_path, manifest)
        preflight_path = build_dir / "preflight.json"
        preflight_path.write_text(
            json.dumps(preflight, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except (BuildError, RenderError, PreflightError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    result = {
        "build_dir": str(build_dir),
        "manifest": str(manifest_path),
        "pdf": str(pdf_path),
        "preflight": str(preflight_path),
        "preflight_summary": preflight["summary"],
        "conformance": preflight["conformance"],
    }
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"build: {build_dir}")
        print(f"pdf: {pdf_path}")
        print(
            "preflight: "
            f"errors={preflight['summary']['errors']} warnings={preflight['summary']['warnings']}"
        )
    return 0 if preflight["summary"]["errors"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
