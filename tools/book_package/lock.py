"""Create a hash-locked publishing input snapshot after export-gate review."""

from __future__ import annotations

from datetime import datetime
import hashlib
from pathlib import Path
from typing import Any, Literal

import yaml

from .paths import resolve_package_path
from .references import extract_illustration_directives, extract_scene_anchors
from .review import ReviewResult, review_package
from .schemas import (
    BookPackage,
    ManuscriptEntry,
    RightsPackage,
    load_book_package,
    load_cover_layout,
    load_rights_package,
)


Target = Literal["paper", "ebook", "web"]
LOCK_VERSION = 1
TOOL_VERSION = "monocri 0.0.0"


class LockError(ValueError):
    """Raised when a package cannot safely be frozen into a lockfile."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative(package_root: Path, path: Path) -> str:
    return path.resolve().relative_to(package_root.resolve()).as_posix()


def _add_file(
    records: dict[str, dict[str, Any]],
    package_root: Path,
    path: Path,
    *,
    scenes: list[str] | None = None,
) -> None:
    if not path.is_file():
        raise LockError(f"Lock input does not exist: {_relative(package_root, path)}")
    relative = _relative(package_root, path)
    record: dict[str, Any] = {"path": relative, "sha256": sha256_file(path)}
    if scenes:
        record["scenes"] = scenes
    records[relative] = record


def _manuscript_entries(
    book: BookPackage,
) -> list[tuple[Literal["frontmatter", "chapters", "backmatter"], ManuscriptEntry]]:
    return [
        *(("frontmatter", entry) for entry in book.manuscript.frontmatter),
        *(("chapters", entry) for entry in book.manuscript.chapters),
        *(("backmatter", entry) for entry in book.manuscript.backmatter),
    ]


def collect_lock_files(
    package_root: Path, book: BookPackage
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Collect the current declared input files and illustration asset hashes."""

    root = package_root.resolve()
    records: dict[str, dict[str, Any]] = {}
    _add_file(records, root, root / "book.yaml")
    _add_file(records, root, root / "rights.yaml")

    # cover.yaml and its package-local assets alter composed front covers just
    # as directly as manuscript or illustration inputs.  Freeze them so a
    # later logo/layout change is visible through book_diff and P-E02.
    cover_path = root / "cover.yaml"
    if cover_path.is_file():
        _add_file(records, root, cover_path)
        cover = load_cover_layout(cover_path)
        for layer in cover.layers:
            if layer.asset is not None:
                _add_file(records, root, resolve_package_path(root, layer.asset))
        for face in cover.fonts.values():
            if face.file is not None and not Path(face.file).expanduser().is_absolute():
                _add_file(records, root, resolve_package_path(root, face.file))

    illustrations = {item.id: item for item in book.illustrations}
    locked_illustrations: list[dict[str, str]] = []
    for illustration in book.illustrations:
        if illustration.asset is None:
            continue
        asset = resolve_package_path(root, illustration.asset)
        _add_file(records, root, asset)
        locked_illustrations.append(
            {
                "id": illustration.id,
                "asset": illustration.asset,
                "sha256": sha256_file(asset),
            }
        )

    for section_name, entry in _manuscript_entries(book):
        for raw_path in entry.source_files():
            path = resolve_package_path(root, raw_path)
            text = path.read_text(encoding="utf-8")
            scenes = (
                [anchor.id for anchor in extract_scene_anchors(text)]
                if section_name == "chapters"
                else []
            )
            _add_file(records, root, path, scenes=scenes)
            for directive in extract_illustration_directives(text):
                illustration = illustrations.get(directive.illustration_id)
                if illustration is None or illustration.asset is None:
                    raise LockError(
                        "Illustration directive cannot be locked without an asset: "
                        f"{directive.illustration_id}"
                    )
                _add_file(
                    records,
                    root,
                    resolve_package_path(root, illustration.asset),
                )

    if book.export.ebook.cover_image is not None:
        _add_file(
            records,
            root,
            resolve_package_path(root, book.export.ebook.cover_image),
        )

    return (
        [records[key] for key in sorted(records)],
        sorted(locked_illustrations, key=lambda item: item["id"]),
    )


def build_lock(package_root: str | Path, *, target: Target) -> dict[str, Any]:
    """Build, but do not write, a lockfile after a successful export-gate review."""

    root = Path(package_root).resolve()
    review = review_package(root, gate="export", target=target)
    if review.has_errors:
        raise LockError("Export-gate review contains errors.")

    book = load_book_package(root / "book.yaml")
    rights = load_rights_package(root / "rights.yaml")
    files, illustrations = collect_lock_files(root, book)
    return {
        "lock_version": LOCK_VERSION,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "export_target": target,
        "tool_version": TOOL_VERSION,
        "book_snapshot": {
            "title": book.book.title,
            "volume": book.book.volume,
            "edition": book.colophon.edition,
        },
        "files": files,
        "illustrations": illustrations,
        "review_result": _review_summary(review),
        "rights_snapshot": {
            "copyright_notice": rights.copyright.notice,
        },
    }


def _review_summary(review: ReviewResult) -> dict[str, int | str]:
    return {
        "mode": "export_gate",
        "errors": sum(finding.severity == "error" for finding in review.findings),
        "warnings": sum(finding.severity == "warning" for finding in review.findings),
    }


def write_lock(package_root: str | Path, *, target: Target) -> Path:
    """Create or replace book.lock.yaml with the current reviewed snapshot."""

    root = Path(package_root).resolve()
    payload = build_lock(root, target=target)
    lock_path = root / "book.lock.yaml"
    lock_path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False, width=120),
        encoding="utf-8",
    )
    return lock_path
