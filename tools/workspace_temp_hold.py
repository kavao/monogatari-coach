"""一時作業フォルダの保留を設定・解除する。"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import stat
import sys
import tempfile

from workspace_temp_inventory import EXCLUDED_TOP_LEVEL_NAMES, ROOT, is_link
from workspace_temp_lock import operation_lock


def set_hold(root: Path, name: str, reason: str | None) -> Path:
    """runs 直下の作業フォルダに保留情報を保存する。"""
    with operation_lock(root):
        return _set_hold(root, name, reason)


def _set_hold(root: Path, name: str, reason: str | None) -> Path:
    if not name or name in {".", ".."} or any(c in name for c in "/\\:"):
        raise ValueError("作業フォルダ名を指定してください")
    if name in EXCLUDED_TOP_LEVEL_NAMES:
        raise ValueError("保護対象は変更できません")
    if reason is not None and not reason.strip():
        raise ValueError("保留理由を指定してください")
    runs = root / "_workingspace" / "tmp" / "runs"
    for directory in (root / "_workingspace", root / "_workingspace" / "tmp", runs, runs / name):
        info = directory.lstat()
        if is_link(info) or not stat.S_ISDIR(info.st_mode):
            raise ValueError(f"通常のフォルダではありません: {directory}")
    run = runs / name
    if run.resolve().parent != runs.resolve():
        raise ValueError("作業フォルダが runs の外です")
    metadata = run / ".run.json"
    data: dict[str, object] = {}
    try:
        info = metadata.lstat()
    except FileNotFoundError:
        if reason is None:
            raise ValueError("解除する保留情報がありません") from None
    else:
        if is_link(info) or not stat.S_ISREG(info.st_mode):
            raise ValueError("保留情報が通常のファイルではありません")
        loaded = json.loads(metadata.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict) or not isinstance(loaded.get("hold"), bool):
            raise ValueError("既存の保留情報を読めません")
        data = loaded
    if reason is None:
        data["hold"] = False
        data.pop("hold_since", None)
        data.pop("reason", None)
    else:
        data.update(
            hold=True,
            reason=reason.strip(),
            hold_since=datetime.now(timezone(timedelta(hours=9))).isoformat(timespec="seconds"),
        )
    payload = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=run, prefix=".run.", suffix=".tmp", delete=False
        ) as file:
            temporary = Path(file.name)
            file.write(payload)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, metadata)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return metadata


def main() -> int:
    parser = argparse.ArgumentParser(description="runs 直下の作業フォルダを保留または解除します")
    parser.add_argument("name", help="runs 直下の作業フォルダ名")
    parser.add_argument("--release", action="store_true", help="保留を解除する")
    parser.add_argument("--reason", help="保留理由")
    args = parser.parse_args()
    if args.release == (args.reason is not None):
        parser.error("--reason または --release のいずれかを指定してください")
    try:
        path = set_hold(ROOT, args.name, None if args.release else args.reason)
    except (OSError, ValueError, UnicodeError, RuntimeError) as exc:
        print(f"保留を変更できません: {exc}", file=sys.stderr)
        return 2
    print(f"保留情報を更新しました: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
