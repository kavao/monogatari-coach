"""作品ルート相対パス。

`_writing/` と `_metron/` の場面は、`work_paths`（tools/work_paths.py）の組の規則で古い置き場か
新しい置き場（`_work/writing/`・`_work/metron/`）へ解決する。保存済みの参照は書き換えず、
読むときに参照先の組を解決する。新しく書く場所は `writing_scene_dir` / `metron_scene_dir` で決め、
記録に書くパスは `unit_rel` で実際の置き場から作る。
"""

from __future__ import annotations

from pathlib import Path

from work_paths import (
    WorkPathError,
    canonical_reference,
    record_reference,
    resolve_reference,
    resolve_unit,
)

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


def _bridge_error(error: WorkPathError, *, field: str) -> BridgeError:
    code = {
        "CONFLICT": "LAYOUT_CONFLICT",
        "MIGRATING": "LAYOUT_MIGRATING",
        "OUT_OF_ROOT": "PATH_OUT_OF_ROOT",
    }.get(error.code, "BAD_ID")
    return BridgeError(code, str(error), refs={"key": field, **error.refs})


def resolve_work_path(work_root: Path, relative: str, *, field: str = "path") -> Path:
    rel = work_rel_path(relative, field=field)
    root = work_root.resolve()
    try:
        located = resolve_reference(root, rel)
    except WorkPathError as error:
        raise _bridge_error(error, field=field) from error
    target = located.resolve()
    try:
        target.relative_to(root)
    except ValueError as error:
        raise BridgeError(
            "PATH_OUT_OF_ROOT",
            f"{field} escapes the work root",
            refs={"key": field, "value": rel},
        ) from error
    return target


def _scene_dir(work_root: Path, kind: str, scene_id: str) -> Path:
    try:
        return resolve_unit(work_root.resolve(), kind, scene_id).base
    except WorkPathError as error:
        raise _bridge_error(error, field=f"{kind}.scene_id") from error


def writing_scene_dir(work_root: Path, scene_id: str) -> Path:
    """執筆接続の場面フォルダ（組の実際の置き場。無ければ新しく始める置き場）。"""
    return _scene_dir(work_root, "writing", scene_id)


def metron_scene_dir(work_root: Path, scene_id: str) -> Path:
    """METRON の場面フォルダ（組の実際の置き場。無ければ新しく始める置き場）。"""
    return _scene_dir(work_root, "metron", scene_id)


def unit_rel(work_root: Path, kind: str, scene_id: str, *parts: str) -> str:
    """記録に書く作品ルート相対パス。参照先の組の実際の置き場を指す。"""
    try:
        return record_reference(work_root.resolve(), kind, scene_id, *parts)
    except WorkPathError as error:
        raise _bridge_error(error, field=f"{kind}.scene_id") from error


def canonical_rel(relative: str) -> str:
    """照合の鍵に使う、置き場によらない形（`@writing/...`・`@metron/...`）。"""
    try:
        return canonical_reference(relative)
    except WorkPathError as error:
        raise _bridge_error(error, field="path") from error
