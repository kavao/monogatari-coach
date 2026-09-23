"""Compare the current publishing package inputs with book.lock.yaml."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .lock import collect_lock_files
from .paths import ManuscriptSource, resolve_manuscript_source
from .schemas import load_book_package


class LockDiffError(ValueError):
    """Raised when book.lock.yaml cannot be loaded or compared."""


def diff_against_lock(
    package_root: str | Path,
    *,
    manuscript_source: ManuscriptSource | None = None,
) -> dict[str, list[str]]:
    root = Path(package_root).resolve()
    lock_path = root / "book.lock.yaml"
    if not lock_path.is_file():
        raise LockDiffError("book.lock.yaml がありません。先に book_lock.py を実行してください。")
    try:
        data = yaml.safe_load(lock_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise LockDiffError(f"book.lock.yaml が不正です: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("files"), list):
        raise LockDiffError("book.lock.yaml の files が不正です。")

    book = load_book_package(root / "book.yaml")
    resolved_source = resolve_manuscript_source(
        cli=manuscript_source, book_source=book.manuscript.source
    )
    current_files, _ = collect_lock_files(
        root, book, manuscript_source=resolved_source
    )
    locked = {
        item["path"]: item["sha256"]
        for item in data["files"]
        if isinstance(item, dict)
        and isinstance(item.get("path"), str)
        and isinstance(item.get("sha256"), str)
    }
    current = {item["path"]: item["sha256"] for item in current_files}

    return {
        "added": sorted(set(current) - set(locked)),
        "removed": sorted(set(locked) - set(current)),
        "changed": sorted(
            path for path in set(current) & set(locked) if current[path] != locked[path]
        ),
    }
