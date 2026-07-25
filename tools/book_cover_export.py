#!/usr/bin/env python3
"""Export composed cover products (ebook front now; paper wrap later)."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
import tempfile

from reportlab.pdfgen.canvas import Canvas

from book_package.build import profile_definition
from book_package.cover import (
    CoverComposeError,
    compose_cover_page,
    has_cover_layout,
    load_package_cover,
    page_size_from_profile_mm,
)
from book_package.fonts import FontError
from book_package.schemas import load_book_package


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def resolve_novel_dir(value: str) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (repo_root() / path).resolve()


def _build_id(target: str) -> str:
    stamp = datetime.now().astimezone().strftime("%Y%m%dT%H%M%S%z")
    return f"cover-{target}-{stamp}"


def _export_ebook_cover_pdf(
    package_root: Path, output: Path, *, profile_name: str = "jis_b5"
) -> dict:
    """Compose a single-page PDF cover (PNG rasterization is deferred to C2 tooling)."""

    if not has_cover_layout(package_root):
        raise CoverComposeError(
            "cover.yaml がありません。電子書籍表紙のレイヤー合成には cover.yaml が必要です。"
        )
    layout = load_package_cover(package_root)
    if layout is None:  # pragma: no cover
        raise CoverComposeError("cover.yaml を読み込めません。")
    book = load_book_package(package_root / "book.yaml")
    profile = profile_definition(profile_name)  # type: ignore[arg-type]
    width, height = page_size_from_profile_mm(
        float(profile["width_mm"]), float(profile["height_mm"])
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    # Use a temp path then rename so partial files are not left as final.
    with tempfile.NamedTemporaryFile(
        mode="wb",
        suffix=".pdf",
        prefix=f".{output.stem}-",
        dir=output.parent,
        delete=False,
    ) as temporary:
        temp_path = Path(temporary.name)
    try:
        canvas = Canvas(
            str(temp_path),
            pagesize=(width, height),
            pageCompression=1,
            invariant=1,
            pdfVersion=(1, 4),
        )
        canvas.setTitle(book.book.title)
        canvas.setAuthor(book.book.author.name)
        canvas.setCreator("Monogatari Coach cover export")
        composition = compose_cover_page(
            canvas,
            package_root=package_root,
            book=book,
            layout=layout,
            page_width_pt=width,
            page_height_pt=height,
        )
        canvas.showPage()
        canvas.save()
        temp_path.replace(output)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise

    return {
        "output": str(output),
        "format": "pdf",
        "note": (
            "C1 では ebook 表紙を PDF 1ページとして出力する。"
            "ストア向け PNG/JPEG と寸法プロファイルは Phase C2。"
        ),
        "cover": composition.to_manifest_cover(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "表紙レイヤーを合成して用途別成果物を出す。"
            "ebook=前面表紙、paper=印刷用巻カバー（印刷所プロファイル必須）。"
        )
    )
    parser.add_argument("novel", help="作品フォルダ")
    parser.add_argument(
        "--target",
        choices=("ebook", "paper"),
        required=True,
        help="ebook=前面表紙、paper=表1・背・表4（要プリンタプロファイル）。",
    )
    parser.add_argument(
        "--profile",
        choices=("jis_b5", "bunko"),
        default="jis_b5",
        help="仕上がり寸法プロファイル（ebook 前面の既定キャンバス）。",
    )
    parser.add_argument(
        "--printer-profile",
        default=None,
        help="印刷所 YAML（paper ターゲットで必須。未指定なら入力未確定で停止）。",
    )
    parser.add_argument(
        "--build-id",
        default=None,
        help="出力先 _publication_output/<build-id>/ を明示する。",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    root = resolve_novel_dir(args.novel)
    build_dir = root / "_publication_output" / (args.build_id or _build_id(args.target))

    try:
        if args.target == "paper":
            if not args.printer_profile:
                print(
                    "error: 印刷用 cover.pdf は印刷所プロファイルが未確定です。"
                    " --printer-profile config/printers/<printer>.yaml を指定してください"
                    "（未実装ではなく入力未確定）。",
                    file=sys.stderr,
                )
                return 2
            printer = Path(args.printer_profile)
            if not printer.is_file():
                print(
                    f"error: 印刷所プロファイルがありません: {printer}",
                    file=sys.stderr,
                )
                return 2
            print(
                "error: 印刷用巻カバー（表1・背・表4）は Phase C3 です。"
                " プリンタプロファイルは受け付けましたが生成はまだ実装していません。",
                file=sys.stderr,
            )
            return 2

        if build_dir.exists():
            print(f"error: 出力先が既にあります: {build_dir}", file=sys.stderr)
            return 2
        build_dir.mkdir(parents=True)
        output = build_dir / "ebook-cover.pdf"
        result = _export_ebook_cover_pdf(root, output, profile_name=args.profile)
        meta_path = build_dir / "cover-export.json"
        meta_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except (CoverComposeError, FontError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(
            json.dumps(
                {"build_dir": str(build_dir), **result},
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
    else:
        print(f"build: {build_dir}")
        print(f"ebook cover: {output}")
        print(f"layers: {len(result['cover'].get('layers') or [])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
