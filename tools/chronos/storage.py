"""CHRONOS の YAML 入出力と原子的書き込み。"""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
from typing import Any, TypeVar

import yaml
from pydantic import BaseModel


ModelT = TypeVar("ModelT", bound=BaseModel)
_YAML_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)


def load_yaml(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    try:
        data = yaml.load(source.read_text(encoding="utf-8"), Loader=_YAML_LOADER)
    except yaml.YAMLError as error:
        raise ValueError(f"invalid YAML: {source}: {error}") from error
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"YAML root must be a mapping: {source}")
    return data


def load_model(path: str | Path, model_type: type[ModelT]) -> ModelT:
    return model_type.model_validate(load_yaml(path))


def model_to_yaml(model: BaseModel) -> str:
    data = model.model_dump(mode="json", exclude_none=True, by_alias=True)
    _omit_empty_state_containers(data)
    return yaml.safe_dump(
        data,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    )


def _omit_empty_state_containers(data: Any) -> None:
    """状態未使用時に空の character_state / effects_on などを増やさない。"""

    if not isinstance(data, dict):
        return
    character_state = data.get("character_state")
    if isinstance(character_state, dict):
        if not character_state.get("dimensions") and not character_state.get("transitions") and not character_state.get(
            "illustration_bind"
        ):
            del data["character_state"]
        else:
            if not character_state.get("transitions"):
                character_state.pop("transitions", None)
            if not character_state.get("illustration_bind"):
                character_state.pop("illustration_bind", None)
    for event in data.get("events") or []:
        if not isinstance(event, dict):
            continue
        if event.get("effects_on") == {}:
            event.pop("effects_on", None)
        source = event.get("source")
        if isinstance(source, dict) and source.get("illustrations") == []:
            source.pop("illustrations", None)
    for character in data.get("characters") or []:
        if isinstance(character, dict) and character.get("initial_state") == {}:
            character.pop("initial_state", None)


def atomic_write_text(path: str | Path, text: str) -> None:
    """同一ディレクトリ内の一時ファイルから原子的に置換する。"""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=f".{target.name}.",
            suffix=".tmp",
            dir=target.parent,
            delete=False,
        ) as handle:
            temporary = handle.name
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        temporary = None
    finally:
        if temporary is not None:
            try:
                Path(temporary).unlink()
            except FileNotFoundError:
                pass


def atomic_write_model(path: str | Path, model: BaseModel) -> None:
    atomic_write_text(path, model_to_yaml(model))


def commit_replacements(pairs: list[tuple[Path, Path]]) -> None:
    """一時ファイル群を書き出したあと、一括で ``os.replace`` する。

    途中で失敗した場合は未置換の一時ファイルを破棄する。既に置換済みの
    ファイルは戻さない（同一ディレクトリの原子置換の限界）。
    """

    pending = list(pairs)
    replaced: list[Path] = []
    try:
        for temporary, target in pending:
            os.replace(temporary, target)
            replaced.append(target)
    except OSError:
        for temporary, target in pending[len(replaced) :]:
            try:
                Path(temporary).unlink()
            except FileNotFoundError:
                pass
        raise
