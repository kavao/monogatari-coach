"""作品ルート相対パス。"""

from __future__ import annotations

from pathlib import Path

from .errors import BridgeError


def work_rel_path(value: str, *, field: str = "path") -> str:
    normalized = value.replace("\\", "/").strip()
    if not normalized:
        raise BridgeError("PATH_OUT_OF_ROOT", f"{field} must not be empty", refs={"key": field})
    if normalized.startswith("/") or (len(normalized) >= 2 and normalized[1] == ":"):
        raise BridgeError(
            "PATH_OUT_OF_ROOT",
            f"{field} must be work-root relative",
            refs={"key": field, "value": normalized},
        )
    if ".." in Path(normalized).parts:
        raise BridgeError(
            "PATH_OUT_OF_ROOT",
            f"{field} must not contain '..'",
            refs={"key": field, "value": normalized},
        )
    return normalized


def resolve_work_path(work_root: Path, relative: str, *, field: str = "path") -> Path:
    rel = work_rel_path(relative, field=field)
    root = work_root.resolve()
    target = (root / Path(*rel.split("/"))).resolve()
    try:
        target.relative_to(root)
    except ValueError as error:
        raise BridgeError(
            "PATH_OUT_OF_ROOT",
            f"{field} escapes the work root",
            refs={"key": field, "value": rel},
        ) from error
    return target
