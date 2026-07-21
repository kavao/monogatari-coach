"""Package-relative path normalization for publishing declarations."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path, PurePosixPath, PureWindowsPath

from .schemas import BookPackage


class PackagePathError(ValueError):
    """Raised when a declaration path is not safely relative to its novel."""


def normalize_package_path(raw_path: str) -> str:
    """Return a portable relative path, rejecting absolute and parent traversal."""

    value = raw_path.strip()
    if not value:
        raise PackagePathError("Package path must not be empty.")
    if "\\" in value:
        raise PackagePathError("Use forward slashes in package paths.")
    if value == "." or value.startswith("./"):
        raise PackagePathError("Package paths must not start with ./.")

    posix = PurePosixPath(value)
    windows = PureWindowsPath(value)
    if posix.is_absolute() or windows.is_absolute() or windows.drive:
        raise PackagePathError(f"Package path must be relative: {raw_path}")
    if any(part in {".", ".."} for part in posix.parts):
        raise PackagePathError(f"Package path must not contain . or ..: {raw_path}")
    return posix.as_posix()


def resolve_package_path(package_root: str | Path, raw_path: str) -> Path:
    """Resolve a normalized path and verify that it remains inside package_root."""

    root = Path(package_root).resolve()
    normalized = normalize_package_path(raw_path)
    candidate = (root / Path(normalized)).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise PackagePathError(f"Package path escapes its root: {raw_path}") from exc
    return candidate


def iter_book_file_references(book: BookPackage) -> Iterator[tuple[str, str]]:
    """Yield every file path declared by book.yaml with its logical label."""

    for section_name, entries in (
        ("frontmatter", book.manuscript.frontmatter),
        ("chapters", book.manuscript.chapters),
        ("backmatter", book.manuscript.backmatter),
    ):
        for entry in entries:
            for index, source_file in enumerate(entry.source_files(), start=1):
                yield (f"manuscript.{section_name}.{entry.id}.{index}", source_file)

    for illustration in book.illustrations:
        if illustration.asset is not None:
            yield (f"illustrations.{illustration.id}.asset", illustration.asset)

    if book.export.ebook.cover_image is not None:
        yield ("export.ebook.cover_image", book.export.ebook.cover_image)


def validate_book_file_references(book: BookPackage) -> None:
    """Validate every declared file reference without requiring it to exist yet."""

    for label, raw_path in iter_book_file_references(book):
        try:
            normalize_package_path(raw_path)
        except PackagePathError as exc:
            raise PackagePathError(f"{label}: {exc}") from exc
