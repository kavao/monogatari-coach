from __future__ import annotations

from pathlib import Path
from typing import Any, TypeVar

import yaml
from pydantic import BaseModel

from ..schemas.manga_page import MangaPagePrompt

ModelT = TypeVar("ModelT", bound=BaseModel)


def load_yaml(path: str | Path) -> dict[str, Any]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"YAML root must be a mapping: {path}")
    return data


def load_model(path: str | Path, model_type: type[ModelT]) -> ModelT:
    return model_type.model_validate(load_yaml(path))


def load_manga_page(path: str | Path) -> MangaPagePrompt:
    """Load either schema 1.0 or 1.1 without dumping away omitted keys."""
    return MangaPagePrompt.model_validate(load_yaml(path))


def validate_manga_page_data(data: dict[str, Any]) -> MangaPagePrompt:
    """Validate raw page data while keeping the caller's mapping unchanged."""
    return MangaPagePrompt.model_validate(data)
