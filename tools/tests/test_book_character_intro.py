"""人物紹介は character.md の派生（P-M05、info）。計画 20261024_work-folder-layout.md M9。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from book_package.review import _character_names  # noqa: E402

CHARACTER_MD = """# 登場人物

## マリエ・ベル（記憶修復師見習い）
- **名前**: マリエ・ベル
- **年齢**: 17

## 異世界語・コミュニケーション（本作で確定）
- 言語は通じない

## イーサン・カーター（監査官）
- **名前**: イーサン・カーター（36歳）
"""


def test_character_names_come_from_name_fields_only() -> None:
    assert _character_names(CHARACTER_MD) == ["マリエ・ベル", "イーサン・カーター"]
