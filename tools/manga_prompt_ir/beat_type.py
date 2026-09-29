"""Manga Prompt IR の拍子の種類（panels[].beat_type）の語彙。

機械集合の正本は ``data/beat_type_vocab.yaml``。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

_VOCAB_PATH = Path(__file__).resolve().parent / "data" / "beat_type_vocab.yaml"


@lru_cache(maxsize=1)
def load_beat_type_vocab() -> dict[str, dict[str, Any]]:
    """beat_type の id → 項目（label_ja / default_weight / size_class / usage）。"""
    data = yaml.safe_load(_VOCAB_PATH.read_text(encoding="utf-8")) or {}
    return {str(item["id"]): dict(item) for item in data.get("vocabulary") or []}


def beat_type_warnings_for_page(label: str, page: Any) -> list[str]:
    """語彙に無い beat_type を報告する（通常は警告、--strict-quality で失敗）。"""
    vocab = load_beat_type_vocab()
    warnings: list[str] = []
    for panel in getattr(page, "panels", None) or []:
        beat_type = getattr(panel, "beat_type", None)
        if beat_type is None:
            continue
        if str(beat_type) not in vocab:
            allowed = ", ".join(vocab)
            warnings.append(
                f"{label}: panel {panel.panel_id}: beat_type '{beat_type}' は語彙にありません"
                f"（{allowed}。語彙は tools/manga_prompt_ir/data/beat_type_vocab.yaml）"
            )
    return warnings
