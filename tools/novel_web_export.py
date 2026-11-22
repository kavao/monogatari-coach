#!/usr/bin/env python3
"""Web 投稿稿の書き出し：本文から章末ステータスの印だけを外し、`_novel_text_re/` へ写す。

正本は `.rulesync/rules/workflow-specification.md`「章末ステータスの表示（CHAPTER_STATUS）」の「出力」。
`_novel_text/novel_text*.md` を読み、`<!-- status:begin -->` / `<!-- status:end -->` の行と、
行頭の `<!-- status:line -->` だけを外して中身を残す。本文は書き換えない。投稿先ごとの変換
（カクヨムのルビなど）はこのあとに `_novel_text_re/` を入力として重ねる。

既存の `_novel_text_re/` のファイルは既定では上書きしない。`--overwrite` のときは、旧版を
`_novel_text_re/_old/<YYYYMMDD_HHMMSS>/` へ退避してから書き換える。

例:
  uv run python tools/novel_web_export.py novels/050_作品名 --dry-run
  uv run python tools/novel_web_export.py novels/050_作品名
  uv run python tools/novel_web_export.py novels/050_作品名 --overwrite
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from chapter_status import scan, unmark_for_output  # noqa: E402

OUTPUT_SUBDIR = "_novel_text_re"
BACKUP_SUBDIR = "_old"


def export_work(
    work: Path,
    *,
    overwrite: bool = False,
    dry_run: bool = False,
    now: datetime | None = None,
) -> dict[str, object]:
    """作品の本文を印なしで `_novel_text_re/` へ書き出す。結果を辞書で返す。"""

    source_dir = work / "_novel_text"
    if not source_dir.is_dir():
        raise FileNotFoundError(f"_novel_text がありません: {source_dir}")
    out_dir = work / OUTPUT_SUBDIR
    stamp = (now or datetime.now()).strftime("%Y%m%d_%H%M%S")
    written: list[str] = []
    skipped: list[str] = []
    backed_up: list[str] = []
    errors: list[str] = []
    for source in sorted(source_dir.glob("novel_text*.md")):
        text = source.read_text(encoding="utf-8")
        result = scan(text)
        if result.errors:
            errors.extend(f"{source.name}: {error}" for error in result.errors)
            continue
        target = out_dir / source.name
        if target.exists() and not overwrite:
            skipped.append(source.name)
            continue
        if dry_run:
            written.append(source.name)
            continue
        out_dir.mkdir(parents=True, exist_ok=True)
        if target.exists():
            backup = out_dir / BACKUP_SUBDIR / stamp / source.name
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, backup)
            backed_up.append(backup.relative_to(work).as_posix())
        with target.open("w", encoding="utf-8", newline="") as stream:
            stream.write(unmark_for_output(text))
        written.append(source.name)
    return {
        "work": work.as_posix(),
        "output_dir": out_dir.as_posix(),
        "dry_run": dry_run,
        "written": written,
        "skipped_existing": skipped,
        "backed_up": backed_up,
        "errors": errors,
        "ok": not errors,
    }


def main(argv: list[str] | None = None) -> int:
    from console_io import configure_stdio_utf8

    configure_stdio_utf8()
    parser = argparse.ArgumentParser(
        description="章末ステータスの印を外した Web 投稿稿を _novel_text_re/ へ書き出す"
    )
    parser.add_argument("work", type=Path, help="novels/NNN_作品名")
    parser.add_argument("--overwrite", action="store_true",
                        help="既存の _novel_text_re のファイルを、旧版を _old/<日時>/ へ退避してから書き換える")
    parser.add_argument("--dry-run", action="store_true", help="書かずに対象だけ表示する")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = export_work(args.work.resolve(), overwrite=args.overwrite, dry_run=args.dry_run)
    except FileNotFoundError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        label = "書き出し予定" if args.dry_run else "書き出し"
        print(f"{label}: {len(result['written'])} ファイル → {result['output_dir']}")
        for name in result["written"]:
            print(f"  + {name}")
        for name in result["skipped_existing"]:
            print(f"  = {name}（既存。上書きは --overwrite）")
        for path in result["backed_up"]:
            print(f"  旧版を退避: {path}")
        for error in result["errors"]:
            print(f"  ! 印の壊れ: {error}（書き出さない）")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
