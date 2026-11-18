#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""書き手のモデルの段（config/writer_profiles.yaml）を読む。

段はモデル名から推測しない。設定に無いモデルは「未登録」として返し、呼ぶ側が既定の手順（standard）で扱う。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

DEFAULT_PATH = Path(__file__).resolve().parents[1] / "config" / "writer_profiles.yaml"
TIERS = frozenset({"low_context", "standard"})
BACKENDS = frozenset({"local_openai", "grok_cli"})
# 書き手を表さない名前。writing_bridge の prepare は --model を省くとこの名前を記録し、METRON の校正の名前にも
# 使われている。どの書き手で書いても同じ名前になるので、段の表に載せない（載せると通常の執筆まで段が切り替わる）。
UNSPECIFIED_IDS = frozenset({"local-writer"})


class WriterProfileError(ValueError):
    pass


@dataclass(frozen=True)
class WriterProfile:
    model_id: str
    tier: str
    backend: str
    model: str
    label: str
    context_tokens: int | None


def load_profiles(path: Path = DEFAULT_PATH) -> dict[str, WriterProfile]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as error:
        raise WriterProfileError(f"書き手の設定を読めない: {path}: {error}") from error
    writers = data.get("writers")
    if not isinstance(writers, dict):
        raise WriterProfileError(f"writers の表が無い: {path}")
    out: dict[str, WriterProfile] = {}
    for model_id, entry in writers.items():
        if str(model_id) in UNSPECIFIED_IDS:
            raise WriterProfileError(f"{model_id}: prepare の既定の名前で、書き手を表さないので載せられない（書き手ごとの名前を付ける）")
        if not isinstance(entry, dict):
            raise WriterProfileError(f"{model_id}: 値が表になっていない")
        unknown = set(entry) - {"tier", "backend", "model", "label", "context_tokens"}
        if unknown:
            raise WriterProfileError(f"{model_id}: 知らない欄 {sorted(unknown)}")
        tier, backend = entry.get("tier"), entry.get("backend")
        if tier not in TIERS:
            raise WriterProfileError(f"{model_id}: tier は {sorted(TIERS)} のどれか（{tier!r}）")
        if backend not in BACKENDS:
            raise WriterProfileError(f"{model_id}: backend は {sorted(BACKENDS)} のどれか（{backend!r}）")
        ctx = entry.get("context_tokens")
        if ctx is not None and (not isinstance(ctx, int) or ctx <= 0):
            raise WriterProfileError(f"{model_id}: context_tokens は正の整数か null")
        out[str(model_id)] = WriterProfile(
            model_id=str(model_id),
            tier=tier,
            backend=backend,
            model=str(entry.get("model") or model_id),
            label=str(entry.get("label") or model_id),
            context_tokens=ctx,
        )
    return out


def get_profile(model_id: str, path: Path = DEFAULT_PATH) -> WriterProfile | None:
    return load_profiles(path).get(model_id)
