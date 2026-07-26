"""Publishing-package schemas and deterministic reference helpers."""

from .paths import (
    ManuscriptSource,
    PackagePathError,
    apply_manuscript_source,
    iter_book_file_references,
    normalize_package_path,
    resolve_manuscript_source,
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
    "ManuscriptSource",
    "PackagePathError",
    "apply_manuscript_source",
    "resolve_manuscript_source",
    "normalize_package_path",
    "resolve_package_path",
    "iter_book_file_references",
    "validate_book_file_references",
    "SceneAnchor",
    "IllustrationDirective",
    "extract_scene_anchors",
    "extract_illustration_directives",
]
