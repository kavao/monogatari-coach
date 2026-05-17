#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""作品フォルダ ``_meta.yaml`` の読み込み（画像生成の機械可読メタ）。

現行スコープ: ``novelai.portions``（Vibe Transfer / ポーション）のみ。
散文・進捗は ``_meta.md`` のまま。
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

META_YAML_FILENAME = "_meta.yaml"
LEGACY_META_YML_FILENAME = "_meta.yml"
SUPPORTED_VERSION = 1
META_YAML_TEMPLATE = Path("_how_to.example") / "_meta.yaml.example"


@dataclass(frozen=True)
class NovelaiPortion:
    id: str
    paths: list[str]
    strength: float
    information_extracted: float
    label: str = ""
    source: str = "_meta.yaml"


def find_meta_yaml_path(novel_dir: Path) -> Path | None:
    yaml_path = novel_dir / META_YAML_FILENAME
    if yaml_path.is_file():
        return yaml_path
    legacy = novel_dir / LEGACY_META_YML_FILENAME
    if legacy.is_file():
        return legacy
    return None


def load_meta_yaml(novel_dir: Path) -> dict[str, Any] | None:
    path = find_meta_yaml_path(novel_dir)
    if path is None:
        return None
    if path.name == LEGACY_META_YML_FILENAME:
        warnings.warn(
            f"{path} は非推奨です。{META_YAML_FILENAME} にリネームしてください。",
            DeprecationWarning,
            stacklevel=2,
        )
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"{path}: root must be a mapping")
    version = data.get("version", 1)
    if int(version) != SUPPORTED_VERSION:
        raise ValueError(
            f"{path}: unsupported version={version!r} (supported: {SUPPORTED_VERSION})"
        )
    return data


# 後方互換エイリアス
load_meta_yml = load_meta_yaml


def resolve_meta_path(raw: str, *, novel_dir: Path, root: Path) -> Path:
    text = str(raw).strip()
    if not text:
        raise ValueError("empty path")
    path = Path(text)
    if path.is_absolute():
        return path.resolve()
    if text.replace("\\", "/").startswith("_how_to/"):
        return (root / path).resolve()
    return (novel_dir / path).resolve()


def _portion_entry(
    portion_id: str,
    entry: dict[str, Any],
    *,
    novel_dir: Path,
    root: Path,
) -> NovelaiPortion:
    if not isinstance(entry, dict):
        raise ValueError(f"portion {portion_id!r}: must be a mapping")

    raw_paths = entry.get("paths")
    if raw_paths is None:
        single = entry.get("path")
        raw_paths = [single] if single else []
    if isinstance(raw_paths, str):
        raw_paths = [raw_paths]
    if not isinstance(raw_paths, list) or not raw_paths:
        raise ValueError(f"portion {portion_id!r}: path or paths is required")

    resolved: list[str] = []
    for raw in raw_paths:
        p = resolve_meta_path(str(raw), novel_dir=novel_dir, root=root)
        if not p.is_file():
            raise FileNotFoundError(f"portion {portion_id!r}: file not found: {p}")
        resolved.append(p.as_posix())

    strength = float(entry.get("strength", 1.0))
    ie = float(entry.get("information_extracted", 1.0))
    label = str(entry.get("label", "") or "").strip()
    return NovelaiPortion(
        id=portion_id,
        paths=resolved,
        strength=strength,
        information_extracted=ie,
        label=label,
    )


def resolve_novelai_portion(
    novel_dir: Path,
    root: Path,
    *,
    portion_id: str | None = None,
) -> NovelaiPortion | None:
    """``_meta.yaml`` から NovelAI ポーションを解決。無ければ ``None``。"""
    meta = load_meta_yaml(novel_dir)
    if meta is None:
        return None

    novelai = meta.get("novelai")
    if not isinstance(novelai, dict):
        return None

    portions = novelai.get("portions")
    if not isinstance(portions, dict) or not portions:
        return None

    default_id = str(novelai.get("portion_default", "") or "").strip()
    fallback_id = str(novelai.get("portion_fallback", "") or "").strip()
    chosen = (portion_id or default_id or "").strip()
    if not chosen:
        chosen = next(iter(portions.keys()))

    try_ids: list[str] = [chosen]
    if fallback_id and fallback_id not in try_ids:
        try_ids.append(fallback_id)
    if default_id and default_id not in try_ids:
        try_ids.append(default_id)

    last_err: FileNotFoundError | None = None
    for pid in try_ids:
        entry = portions.get(pid)
        if entry is None:
            continue
        try:
            return _portion_entry(pid, entry, novel_dir=novel_dir, root=root)
        except FileNotFoundError as e:
            last_err = e
            continue

    meta_path = find_meta_yaml_path(novel_dir) or (novel_dir / META_YAML_FILENAME)
    if last_err is not None:
        raise last_err
    raise ValueError(
        f"{meta_path}: portion {chosen!r} not found in novelai.portions"
    )
