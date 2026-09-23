#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from novel_character_md_check import check_character_file  # noqa: E402


def _write_character(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "character.md"
    path.write_text(body, encoding="utf-8")
    return path


def test_appearance_identity_requires_three_children(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MONOCRI_CHARACTER_CHECKLIST", raising=False)
    md = """# 登場人物

## テスト花子（てすと はなこ）
- **名前**: テスト花子
- **身長**: 約160cm
- **外見**: 黒髪の肩下ボブ。灰色の瞳。きちんとした制服姿。
- **外見の個性**:
  - 黒髪ボブと灰色の瞳
  - 端的な態度
"""
    path = _write_character(tmp_path, md)
    result = check_character_file(path, profile="visual")
    assert result["ok"] is False
    messages = [i["message"] for i in result["errors"] + result["warnings"]]
    assert any("子項目が少ない" in msg for msg in messages)


def test_appearance_identity_passes_with_three_children(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MONOCRI_CHARACTER_CHECKLIST", raising=False)
    md = """# 登場人物

## テスト花子（てすと はなこ）
- **名前**: テスト花子
- **身長**: 約160cm
- **外見**: 黒髪の肩下ボブ。灰色の瞳。きちんとした制服姿。
- **外見の個性**:
  - 黒髪ボブと灰色の瞳
  - 端的な態度
  - 袖口を少し長めにしているこだわり
"""
    path = _write_character(tmp_path, md)
    result = check_character_file(path, profile="visual")
    messages = [i["message"] for i in result["errors"] + result["warnings"]]
    assert not any("子項目が少ない" in msg for msg in messages)
