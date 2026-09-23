"""Manga Prompt IR の画角語彙・隣接コマ検査（advisory 専用）。

機械集合の正本は ``data/camera_shot_vocab.yaml``。
``page_notes`` は読まない（計画: 例外スキップは実装しない）。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

import yaml

_VOCAB_PATH = Path(__file__).resolve().parent / "data" / "camera_shot_vocab.yaml"


def _has_cjk(s: str) -> bool:
    for ch in s:
        if "\u3040" <= ch <= "\u30ff" or "\u4e00" <= ch <= "\u9fff":
            return True
    return False


def normalize_camera_token(raw: str | None) -> str | None:
    """trim・空白畳み・``_``→空白・大小無視。空なら None。"""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    s = s.replace("_", " ")
    s = " ".join(s.split())
    return s.casefold()


def _as_mapping(obj: Any) -> Mapping[str, Any]:
    if obj is None:
        return {}
    if isinstance(obj, Mapping):
        return obj
    dump = getattr(obj, "model_dump", None)
    if callable(dump):
        data = dump()
        if isinstance(data, Mapping):
            return data
    out: dict[str, Any] = {}
    for key in ("angle", "angle_en", "shot_size", "shot_size_en", "view", "view_en"):
        if hasattr(obj, key):
            out[key] = getattr(obj, key)
    return out


def resolve_camera_en_token(camera: Mapping[str, Any] | None, en_key: str, legacy_key: str) -> str | None:
    """``*_en`` を優先。無ければ CJK を含まない英語の旧キー。空は対象外。"""
    cam = camera or {}
    en_raw = cam.get(en_key)
    if en_raw is not None:
        en = str(en_raw).strip()
        if en:
            return en
    legacy_raw = cam.get(legacy_key)
    if legacy_raw is None:
        return None
    legacy = str(legacy_raw).strip()
    if not legacy or _has_cjk(legacy):
        return None
    return legacy


@lru_cache(maxsize=1)
def load_camera_shot_vocab(path: str | None = None) -> dict[str, set[str]]:
    vocab_path = Path(path) if path else _VOCAB_PATH
    data = yaml.safe_load(vocab_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"camera shot vocab root must be a mapping: {vocab_path}")
    vocabulary = data.get("vocabulary") or {}
    out: dict[str, set[str]] = {"angle_en": set(), "shot_size_en": set(), "view_en": set()}
    for field in ("angle_en", "shot_size_en", "view_en"):
        tokens: set[str] = set()
        for item in vocabulary.get(field) or []:
            if not isinstance(item, Mapping):
                continue
            norm = normalize_camera_token(item.get("token"))
            if norm:
                tokens.add(norm)
        out[field] = tokens
    return out


def camera_shot_advisories_for_page(
    label: str,
    page: Any,
    *,
    vocab: dict[str, set[str]] | None = None,
) -> list[str]:
    """同一 YAML 内の未知語彙と、panel_id 順の隣接同一画角を advisory 文で返す。

    ``page_notes`` は参照しない。空の角度・距離・視点は未知語検査の対象外。
    """
    intent = str(getattr(getattr(page, "meta", None), "intent", "") or "")
    if not intent and isinstance(page, Mapping):
        intent = str((page.get("meta") or {}).get("intent") or "")
    if intent not in {"manga_page", "manga_panel"}:
        return []

    panels = list(getattr(page, "panels", None) or [])
    if not panels and isinstance(page, Mapping):
        panels = list(page.get("panels") or [])
    if len(panels) < 1:
        return []

    vocab = vocab or load_camera_shot_vocab()
    angle_vocab = vocab.get("angle_en") or set()
    shot_vocab = vocab.get("shot_size_en") or set()
    view_vocab = vocab.get("view_en") or set()

    resolved: list[tuple[int, str | None, str | None]] = []
    advisories: list[str] = []

    def _panel_id(panel: Any) -> int:
        raw = getattr(panel, "panel_id", None)
        if raw is None and isinstance(panel, Mapping):
            raw = panel.get("panel_id")
        return int(raw)

    for panel in sorted(panels, key=_panel_id):
        pid = _panel_id(panel)
        camera = _as_mapping(getattr(panel, "camera", None) if not isinstance(panel, Mapping) else panel.get("camera"))
        prefix = f"{label}: panel {pid}"
        angle = resolve_camera_en_token(camera, "angle_en", "angle")
        shot = resolve_camera_en_token(camera, "shot_size_en", "shot_size")
        view = resolve_camera_en_token(camera, "view_en", "view")
        angle_n = normalize_camera_token(angle)
        shot_n = normalize_camera_token(shot)
        view_n = normalize_camera_token(view)
        if angle_n and angle_n not in angle_vocab:
            advisories.append(
                f"{prefix}: camera.angle_en '{angle}' は camera_shot_vocab.yaml にありません"
            )
        if shot_n and shot_n not in shot_vocab:
            advisories.append(
                f"{prefix}: camera.shot_size_en '{shot}' は camera_shot_vocab.yaml にありません"
            )
        if view_n and view_n not in view_vocab:
            advisories.append(
                f"{prefix}: camera.view_en '{view}' は camera_shot_vocab.yaml にありません"
            )
        resolved.append((pid, angle_n, shot_n))

    for (pid_a, angle_a, shot_a), (pid_b, angle_b, shot_b) in zip(resolved, resolved[1:]):
        if not (angle_a and shot_a and angle_b and shot_b):
            continue
        if angle_a == angle_b and shot_a == shot_b:
            advisories.append(
                f"{label}: panel {pid_a} と panel {pid_b} の angle と shot_size が両方同じです"
                f"（{angle_a} / {shot_a}）"
            )
    return advisories
