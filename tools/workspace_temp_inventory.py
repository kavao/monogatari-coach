"""作業領域の一時物を読み取り専用で一覧する。"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
import sys


ROOT = Path(__file__).resolve().parent.parent
RETENTION_DAYS = 30
PROTECTED_NAMES = frozenset({"_novel_text_re", "_manga_ir_backup", "novelai_manga_tests"})
EXCLUDED_TOP_LEVEL_NAMES = PROTECTED_NAMES | {".gitkeep"}
JAPAN_TIME = timezone(timedelta(hours=9))


def is_link(info: os.stat_result) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )


def inspect_path(path: Path) -> tuple[int, int, float]:
    """リンクをたどらず、ファイル数・サイズ・最新更新日時を求める。"""
    info = path.lstat()
    if is_link(info):
        raise ValueError("リンクまたはジャンクションを含む")
    latest = info.st_mtime
    if stat.S_ISREG(info.st_mode):
        return 1, info.st_size, latest
    if not stat.S_ISDIR(info.st_mode):
        raise ValueError("通常のファイルまたはフォルダではない")
    count = 0
    size = 0
    with os.scandir(path) as entries:
        for entry in entries:
            if entry.name in PROTECTED_NAMES:
                raise ValueError("保護する名前を含む")
            if entry.name == ".run.json":
                metadata = entry.stat(follow_symlinks=False)
                if is_link(metadata) or not stat.S_ISREG(metadata.st_mode):
                    raise ValueError("保留情報が通常のファイルではない")
                continue
            child_count, child_size, child_latest = inspect_path(Path(entry.path))
            count += child_count
            size += child_size
            latest = max(latest, child_latest)
    return count, size, latest


def fingerprint_path(path: Path, *, ignore_root_ctime: bool = False) -> str:
    """内容を開かず、全項目の名前と属性から変更検出用の値を作る。"""
    digest = hashlib.sha256()

    def visit(current: Path, relative: str) -> None:
        info = current.lstat()
        if is_link(info):
            raise ValueError("リンクまたはジャンクションを含む")
        if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
            raise ValueError("通常のファイルまたはフォルダではない")
        change_time = None if ignore_root_ctime and relative == "." else info.st_ctime_ns
        entry = [relative, info.st_mode, info.st_size, info.st_mtime_ns, change_time,
                 info.st_dev, info.st_ino]
        digest.update(json.dumps(entry, ensure_ascii=True, separators=(",", ":")).encode("ascii"))
        digest.update(b"\n")
        if stat.S_ISDIR(info.st_mode):
            with os.scandir(current) as found:
                children = sorted(found, key=lambda child: child.name)
            for child in children:
                if child.name in PROTECTED_NAMES:
                    raise ValueError("保護する名前を含む")
                visit(Path(child.path), f"{relative}/{child.name}")

    visit(path, ".")
    return digest.hexdigest()


def read_hold(path: Path, now: datetime) -> dict[str, object] | None:
    if not path.is_dir():
        return None
    hold_file = path / ".run.json"
    try:
        info = hold_file.lstat()
    except FileNotFoundError:
        return None
    except OSError as exc:
        return {"reason": f"保留情報を確認できない: {exc}", "hold_days": None}
    try:
        if is_link(info) or not stat.S_ISREG(info.st_mode):
            raise ValueError("保留情報が通常のファイルではない")
        data = json.loads(hold_file.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("hold"), bool):
            raise ValueError("hold は真偽値で指定する")
        if not data["hold"]:
            return None
        reason = data.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            reason = "不明"
        since = data.get("hold_since")
        days = None
        if isinstance(since, str):
            try:
                parsed = datetime.fromisoformat(since)
                if parsed.tzinfo is not None and parsed <= now:
                    days = (now - parsed).days
            except ValueError:
                pass
        return {"reason": reason, "hold_days": days}
    except (OSError, UnicodeError, ValueError) as exc:
        return {"reason": f"保留情報が不正または読取不能: {exc}", "hold_days": None}


def entries(root: Path, now: datetime) -> list[dict[str, object]]:
    workspace = root / "_workingspace"
    runs = workspace / "tmp" / "runs"
    selected: list[tuple[Path, str]] = []
    for directory in (workspace, workspace / "tmp", runs):
        try:
            info = directory.lstat()
        except FileNotFoundError:
            continue
        if is_link(info) or not stat.S_ISDIR(info.st_mode):
            raise ValueError(f"一覧の起点が通常のフォルダではない: {directory}")
        with os.scandir(directory) as found:
            for entry in found:
                name = entry.name
                if directory == workspace:
                    include = name.startswith(("tmp_", "_tmp_")) or name in {
                        "_intended_meta.md", "__pycache__"
                    }
                    category = "旧配置"
                elif directory == workspace / "tmp":
                    include = name not in {"runs", "_quarantine"} and not name.startswith(".env")
                    category = "旧配置"
                else:
                    include = not name.startswith(".env")
                    category = "runs"
                if name in EXCLUDED_TOP_LEVEL_NAMES:
                    include = False
                if include:
                    selected.append((Path(entry.path), category))

    rows: list[dict[str, object]] = []
    for path, category in sorted(selected, key=lambda item: str(item[0]).casefold()):
        row: dict[str, object] = {"path": path.relative_to(root).as_posix(), "category": category}
        try:
            count, size, modified = inspect_path(path)
            fingerprint = fingerprint_path(path)
            last = datetime.fromtimestamp(modified, JAPAN_TIME)
            expiry = last + timedelta(days=RETENTION_DAYS)
            hold = read_hold(path, now) if category == "runs" else None
            row.update(files=count, bytes=size, modified=last.isoformat(), expires=expiry.isoformat(), fingerprint=fingerprint)
            if hold:
                row.update(status="保留", reason=hold["reason"], hold_days=hold["hold_days"])
            elif category == "旧配置":
                row.update(status="要確認", reason="旧配置の用途と参照先を確認")
            elif now >= expiry:
                row.update(status="期限切れ", reason=f"最新更新から{RETENTION_DAYS}日経過")
            else:
                row.update(status="保存中", reason=f"最新更新から{RETENTION_DAYS}日未満")
        except (OSError, ValueError, OverflowError) as exc:
            row.update(status="要確認", reason=str(exc))
        rows.append(row)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="作業領域の一時物を読み取り専用で一覧します")
    parser.add_argument("--json", action="store_true", help="JSON形式で表示")
    args = parser.parse_args()
    try:
        rows = entries(ROOT, datetime.now(timezone.utc))
    except (OSError, ValueError) as exc:
        print(f"一覧を作れません: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        for row in rows:
            print("\t".join(str(row.get(key, "-")) for key in (
                "status", "category", "path", "files", "bytes", "modified", "expires", "hold_days", "reason", "fingerprint"
            )))
        print(f"合計 {len(rows)} 件。ファイルの変更はありません。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
