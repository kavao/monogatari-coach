"""YAML / JSON / journal の読書き。本文正本は書かない。"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, TypeVar

import yaml
from pydantic import BaseModel, ValidationError

from .errors import BridgeError
from .models import SCHEMA, JournalEntry


ModelT = TypeVar("ModelT", bound=BaseModel)
_YAML_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
_JST = timezone(timedelta(hours=9))


def now_iso() -> str:
    return datetime.now(_JST).replace(microsecond=0).isoformat()


def load_yaml_mapping(path: Path) -> dict[str, Any]:
    try:
        data = yaml.load(path.read_text(encoding="utf-8"), Loader=_YAML_LOADER)
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise BridgeError(
            "SCHEMA_UNSUPPORTED",
            f"could not read YAML: {path}: {error}",
            refs={"path": str(path)},
        ) from error
    if not isinstance(data, dict):
        raise BridgeError(
            "SCHEMA_UNSUPPORTED",
            f"YAML root must be a mapping: {path}",
            refs={"path": str(path)},
        )
    return data


def load_model(path: Path, model_type: type[ModelT]) -> ModelT:
    data = load_yaml_mapping(path)
    schema = data.get("schema")
    if schema is None:
        raise BridgeError(
            "SCHEMA_UNSUPPORTED",
            "schema is missing",
            refs={"path": str(path)},
        )
    if schema != SCHEMA:
        raise BridgeError(
            "SCHEMA_UNSUPPORTED",
            f"unsupported schema {schema!r}",
            refs={"path": str(path), "schema": schema},
        )
    try:
        return model_type.model_validate(data)
    except ValidationError as error:
        return _reraise_validation(error, path)


def load_json_model(path: Path, model_type: type[ModelT]) -> ModelT:
    import json

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise BridgeError(
            "SCHEMA_UNSUPPORTED",
            f"could not read JSON: {path}: {error}",
            refs={"path": str(path)},
        ) from error
    if not isinstance(data, dict):
        raise BridgeError(
            "SCHEMA_UNSUPPORTED",
            f"JSON root must be a mapping: {path}",
            refs={"path": str(path)},
        )
    if data.get("schema") != SCHEMA:
        raise BridgeError(
            "SCHEMA_UNSUPPORTED",
            f"unsupported schema {data.get('schema')!r}",
            refs={"path": str(path)},
        )
    try:
        return model_type.model_validate(data)
    except ValidationError as error:
        return _reraise_validation(error, path)


def _reraise_validation(error: ValidationError, path: Path) -> Any:
    for item in error.errors():
        loc = ".".join(str(part) for part in item.get("loc", ()))
        kind = item.get("type", "")
        if kind == "extra_forbidden":
            raise BridgeError(
                "UNKNOWN_KEY",
                f"unknown key {loc}",
                refs={"path": str(path), "key": loc},
            ) from error
        if kind == "missing":
            raise BridgeError(
                "MISSING_FIELD",
                f"missing field {loc}",
                refs={"path": str(path), "key": loc},
            ) from error
        if "pattern" in kind or loc.endswith("id") or "enum" in kind or "literal" in kind:
            raise BridgeError(
                "BAD_ID",
                item.get("msg", "invalid value"),
                refs={"path": str(path), "key": loc},
            ) from error
        if "sha256" in str(item.get("msg", "")) or loc.endswith("sha256"):
            raise BridgeError(
                "BAD_HASH",
                item.get("msg", "invalid hash"),
                refs={"path": str(path), "key": loc},
            ) from error
    raise BridgeError(
        "SCHEMA_UNSUPPORTED",
        str(error),
        refs={"path": str(path)},
    ) from error


def dump_yaml(model: BaseModel) -> str:
    data = model.model_dump(mode="json", by_alias=True, exclude_none=True)
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False)


def dump_json(model: BaseModel) -> str:
    return model.model_dump_json(by_alias=True, indent=2) + "\n"


def write_text(path: Path, text: str, *, overwrite: bool = True) -> None:
    if path.exists() and not overwrite:
        raise BridgeError(
            "JOB_CONFLICT",
            f"refusing to overwrite {path}",
            refs={"path": str(path)},
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def write_model(path: Path, model: BaseModel, *, json_format: bool = False) -> None:
    if json_format or path.suffix == ".json":
        write_text(path, dump_json(model))
    else:
        write_text(path, dump_yaml(model))


def append_journal(path: Path, entry: JournalEntry) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = entry.model_dump_json(by_alias=True, exclude_none=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(line + "\n")


def read_journal(path: Path) -> list[JournalEntry]:
    if not path.is_file():
        return []
    entries: list[JournalEntry] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        entries.append(JournalEntry.model_validate_json(line))
    return entries


def next_index(existing: list[int]) -> int:
    return (max(existing) + 1) if existing else 1
