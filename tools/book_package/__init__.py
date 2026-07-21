"""Publishing-package schemas and deterministic reference helpers."""

from .paths import (
    PackagePathError,
    iter_book_file_references,
    normalize_package_path,
    resolve_package_path,
    validate_book_file_references,
)
from .references import (
    IllustrationDirective,
    SceneAnchor,
    extract_illustration_directives,
    extract_scene_anchors,
)
from .schemas import BookPackage, RightsPackage, load_book_package, load_rights_package

__all__ = [
    "BookPackage",
    "RightsPackage",
    "load_book_package",
    "load_rights_package",
    "PackagePathError",
    "normalize_package_path",
    "resolve_package_path",
    "iter_book_file_references",
    "validate_book_file_references",
    "SceneAnchor",
    "IllustrationDirective",
    "extract_scene_anchors",
    "extract_illustration_directives",
]
