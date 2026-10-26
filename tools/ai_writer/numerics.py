"""数値の正規化と抽出（計画書 §23、Phase 1 Minimum Guard）。

- 算用数字・全角数字・漢数字（位取り「千九百四十五」と桁並び「二〇二六」）を同じ値にする。
- 数値は助数詞・単位が付いたものだけを拾う（「3人／３人／三人」は同じ (3, 人)）。算用数字は単位なしも拾う。
- 漢数字は語の一部になりやすいので、慣用句（「十分（じゅうぶん）」「一番」「三日月」「一人称」など）は除く。

語の切り出しは規則による近似で、形態素解析ではない。結果は Guard の「候補」に使い、違反の確定には使わない。
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

_DIGITS = {"〇": 0, "零": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
           "壱": 1, "弐": 2, "参": 3}
_SMALL = {"十": 10, "百": 100, "千": 1000}
_BIG = {"万": 10 ** 4, "億": 10 ** 8}
_KANJI_NUM = "〇零一二三四五六七八九十百千万億壱弐参"

# 長いものを先に並べる（「時間」を「時」より先に、「光年」を「年」より先に）
COUNTERS: tuple[str, ...] = (
    "光年", "年生", "年間", "か月", "ヶ月", "カ月", "箇月", "週間", "日間", "時間", "分間", "秒間",
    "キロ", "メートル", "センチ", "グラム", "ページ",
    "歳", "才", "年", "月", "週", "日", "時", "分", "秒", "人", "名", "円", "枚", "本", "冊", "回", "階",
    "個", "匹", "頭", "台", "件", "通", "番", "号", "字", "頁", "杯", "軒", "社", "発", "倍",
    "km", "kg", "%", "％", "m",
)
_UNIT_ALIASES = {"ヶ月": "か月", "カ月": "か月", "箇月": "か月", "才": "歳", "％": "%", "頁": "ページ"}

# 漢数字＋助数詞でも数量ではない語（後ろの文字まで見て除く）
_IDIOMS = re.compile(
    r"十分(?!間)|一番(?![目線地])|三日月|一人称|一時(?=的|期|停|保)|一日中(?=に)|一月(?=遅れ)|一本(?=気|調子|道)"
    r"|一回(?=り)|二人称|三人称|一頭(?=地)|一通(?=り)|一発(?=屋)|千夏"
)
_COUNTER_RE = "|".join(re.escape(c) for c in COUNTERS)
_NUMBER_RE = re.compile(
    rf"(?P<arabic>[0-9０-９]+(?:[.．][0-9０-９]+)?)(?P<big>[万億])?(?P<unit1>{_COUNTER_RE})?"
    rf"|(?P<kanji>[{_KANJI_NUM}]+)(?P<unit2>{_COUNTER_RE})"
)


def kanji_to_int(text: str) -> int:
    """漢数字を整数にする。位取り（千九百四十五）と桁並び（二〇二六）の両方を読む。"""
    if not text or any(ch not in _DIGITS and ch not in _SMALL and ch not in _BIG for ch in text):
        raise ValueError(f"漢数字ではない: {text}")
    if all(ch in _DIGITS for ch in text) and len(text) > 1:
        return int("".join(str(_DIGITS[ch]) for ch in text))
    total = section = 0
    digit: int | None = None
    for ch in text:
        if ch in _DIGITS:
            digit = _DIGITS[ch]
        elif ch in _SMALL:
            section += (1 if digit is None else digit) * _SMALL[ch]
            digit = None
        else:
            section += digit or 0
            total += (section or 1) * _BIG[ch]
            section, digit = 0, None
    return total + section + (digit or 0)


def normalize_unit(unit: str) -> str:
    return _UNIT_ALIASES.get(unit, unit)


@dataclass(frozen=True)
class NumberMention:
    value: float
    unit: str
    text: str
    start: int
    end: int

    @property
    def key(self) -> tuple[float, str]:
        return (self.value, self.unit)


def extract_numbers(text: str) -> list[NumberMention]:
    """数値と単位を拾う。位置は ``text`` 上の添字。"""
    excluded = [(m.start(), m.end()) for m in _IDIOMS.finditer(text)]
    out: list[NumberMention] = []
    for m in _NUMBER_RE.finditer(text):
        if any(s <= m.start() < e for s, e in excluded):
            continue
        if m.group("arabic"):
            raw = unicodedata.normalize("NFKC", m.group("arabic"))
            value = float(raw)
            if m.group("big"):
                value *= _BIG[m.group("big")]
            unit = m.group("unit1") or ""
        else:
            try:
                value = float(kanji_to_int(m.group("kanji")))
            except ValueError:
                continue
            unit = m.group("unit2")
        out.append(NumberMention(value=value, unit=normalize_unit(unit), text=m.group(0), start=m.start(), end=m.end()))
    return out
