"""既知エンティティ辞書と未知エンティティ候補（計画書 §21〜22、Phase 1 Minimum Guard）。

- 辞書は人物名（character.md の「名前」欄と見出し: 姓名・姓・名・読み）と、設定の本文（world.md など）から作る。
  設定の本文に出てくる語は既知として扱う（地名・組織・物の名前を個別に登録しなくても拾える）。
- 未知の候補は、形態素解析を使わない規則で拾う（依存を増やさない Phase 1 の近似）。
  1. 敬称付きの名前（「森先生」「田中さん」）
  2. 場所・組織の接尾辞を持つ語（「〜駅」「〜高校」「〜病院」）
  3. カタカナ語（語彙の追加も拾うので、確度は低い）
  4. 名前らしい漢字（末尾が 子・郎・太 など。「椅子」「様子」のような普通名詞は除く。確度は低い）
  5. 人物・場所を表す普通名詞（「駅員」「見知らぬ女」「倉庫」「閲覧室」）。名前を持たない新しい人物・場所の手がかり
     （Validator Fixture で名前の規則だけでは拾えなかった形）。確度は低い
- 候補は違反ではない（§22）。元の本文・設定・辞書にあれば候補から外す。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

Kind = Literal["person", "place_org", "katakana", "name_like", "role", "place_noun"]
Confidence = Literal["high", "low"]

_KANJI = r"[一-龥々〆ヵヶ]"
_HONORIFIC = re.compile(rf"(?P<name>{_KANJI}{{1,4}}|[ァ-ヴー]{{2,8}})(?P<suffix>さん|くん|君|ちゃん|様|さま|先生|先輩|殿|氏|課長|部長|社長)")
_PLACE_ORG = re.compile(
    rf"(?<!{_KANJI})(?P<name>{_KANJI}{{1,6}}(?:駅|町|村|市|県|区|国|城|寺|神社|学園|高校|中学|小学校|大学|病院|会社|商店|銀行|警察署|署|図書館|公園|港|島))"
)
_KATAKANA = re.compile(r"[ァ-ヴ][ァ-ヴー・]{1,}")
_NAME_LIKE = re.compile(rf"(?<!{_KANJI})(?P<name>{_KANJI}{{1,2}}(?:子|郎|太|介|也|斗|菜|奈|美|香))(?=[はがをにのとも、。」！？]|さん|くん|ちゃん)")
# 人物・場所を表す普通名詞（元の本文にないときだけ候補にする）
_ROLE_NOUNS = ("駅員", "車掌", "店員", "店主", "警官", "警察官", "医者", "医師", "看護師", "司書", "教師", "先生", "老人",
               "老婆", "老婦人", "少女", "少年", "青年", "女性", "男性", "女", "男", "子ども", "子供", "赤ん坊", "客",
               "見知らぬ", "知らない人", "管理人", "運転手", "兵士", "騎士", "魔法使い", "仲間")
_PLACE_NOUNS = ("倉庫", "閲覧室", "書庫", "駐車場", "屋上", "地下室", "地下", "校門", "改札", "商店街", "路地", "病室",
                "教室", "職員室", "体育館", "裏庭", "納屋", "蔵", "離れ", "小屋", "海辺", "浜辺", "砂浜", "川沿い", "酒場",
                "バー", "宿屋", "城", "塔", "洞窟", "広場", "階段の下", "二階", "三階", "一階")
_ROLE_RE = re.compile("|".join(sorted(map(re.escape, _ROLE_NOUNS), key=len, reverse=True)))
_PLACE_NOUN_RE = re.compile("|".join(sorted(map(re.escape, _PLACE_NOUNS), key=len, reverse=True)))
# 「名前らしい漢字」の規則に当たる普通名詞
_COMMON_NAME_LIKE = frozenset({
    "椅子", "様子", "調子", "帽子", "息子", "菓子", "扇子", "弟子", "双子", "冊子", "障子", "団子", "原子", "電子",
    "男子", "女子", "王子", "格子", "拍子", "梯子", "硝子", "種子", "粒子", "迷子", "茄子", "餃子", "親子", "面子",
    "因子", "分子", "利子", "骨子", "様子", "子", "丸太", "図太", "紹介", "仲介", "厄介", "媒介", "野菜", "前菜",
    "白菜", "山菜", "惣菜", "奈落", "優美", "賛美", "甘美", "審美", "芳香", "線香", "香", "美",
})
# よく出る普通のカタカナ語（Phase 0 で出たもの中心。網羅はしない）
_COMMON_KATAKANA = frozenset({
    "スマートフォン", "スマホ", "テレビ", "リモコン", "ホーム", "ベンチ", "ドア", "ノブ", "ピアノ", "ポケット",
    "ハンカチ", "カーテン", "ポスター", "トースト", "パン", "バター", "インク", "スタンプ", "テーブル", "ソファ",
    "コーヒー", "カップ", "メール", "メッセージ", "ボタン", "スイッチ", "システム", "モニター", "ホログラム",
    "エンジン", "カバー", "レバー", "コンソール", "ブザー", "アイコン", "ルート", "スピード", "キロ", "メートル",
    "センチ", "グラム", "ページ", "ノート", "ペン", "リボン", "ハンドル", "ガラス", "コンクリート", "ゴム",
})


@dataclass(frozen=True)
class EntityCandidate:
    text: str
    kind: Kind
    confidence: Confidence
    start: int
    end: int


@dataclass
class KnownEntityDictionary:
    names: dict[str, str] = field(default_factory=dict)
    """語 → 種類（character / location / organization / item / lore）。"""
    corpus: list[str] = field(default_factory=list)
    """この本文に出てくる語は既知とみなす（world.md など）。"""

    def add(self, term: str, kind: str) -> None:
        term = term.strip()
        if term:
            self.names[term] = kind

    def add_corpus(self, text: str) -> None:
        if text:
            self.corpus.append(text)

    def knows(self, term: str) -> bool:
        return term in self.names or any(term in text for text in self.corpus)

    @classmethod
    def from_work(cls, work_dir: Path, *, extra_files: tuple[str, ...] = ()) -> KnownEntityDictionary:
        """作品フォルダの character.md と world.md（あれば）から作る。"""
        d = cls()
        character = work_dir / "character.md"
        if character.is_file():
            text = character.read_text(encoding="utf-8")
            for name in parse_character_names(text):
                d.add(name, "character")
            d.add_corpus(text)
        for name in ("world.md", *extra_files):
            path = work_dir / name
            if path.is_file():
                d.add_corpus(path.read_text(encoding="utf-8"))
        return d


_NAME_FIELD = re.compile(r"^(?:##\s+|-\s+\*\*名前\*\*\s*[:：]\s*)(?P<value>.+)$", re.MULTILINE)


def parse_character_names(text: str) -> set[str]:
    """「吉田 彩花（よしだ あやか）」から 吉田彩花・吉田・彩花・よしだ・あやか などを取り出す。"""
    names: set[str] = set()
    for m in _NAME_FIELD.finditer(text):
        value = m.group("value").strip()
        main, _, rest = value.partition("（")
        if not main or main.startswith(("登場人物", "#")):
            continue
        reading = rest.split("）", 1)[0] if rest else ""
        for part in (main, reading):
            tokens = [t for t in re.split(r"[\s　・]+", part.strip()) if t]
            if tokens:
                names.add("".join(tokens))
                names.update(tokens)
    return {n for n in names if len(n) >= 1 and not n.startswith("-")}


def extract_candidates(text: str) -> list[EntityCandidate]:
    """規則で固有名らしい語を拾う（既知かどうかは見ない）。同じ範囲は確度の高い規則を優先する。"""
    found: list[EntityCandidate] = []
    taken: list[tuple[int, int]] = []

    def add(name: str, kind: Kind, conf: Confidence, start: int, reserve_end: int | None = None) -> None:
        end = start + len(name)
        if any(s < (reserve_end or end) and start < e for s, e in taken):
            return
        taken.append((start, reserve_end or end))  # 敬称まで押さえ、「先生」を別の候補にしない
        found.append(EntityCandidate(name, kind, conf, start, end))

    for m in _HONORIFIC.finditer(text):
        add(m.group("name"), "person", "high", m.start("name"), m.end())
    for m in _PLACE_ORG.finditer(text):
        add(m.group("name"), "place_org", "high", m.start("name"))
    for m in _NAME_LIKE.finditer(text):
        if m.group("name") not in _COMMON_NAME_LIKE:
            add(m.group("name"), "name_like", "low", m.start("name"))
    for m in _ROLE_RE.finditer(text):
        add(m.group(0), "role", "low", m.start())
    for m in _PLACE_NOUN_RE.finditer(text):
        add(m.group(0), "place_noun", "low", m.start())
    for m in _KATAKANA.finditer(text):
        word = m.group(0)
        if word not in _COMMON_KATAKANA:
            add(word, "katakana", "low", m.start())
    return sorted(found, key=lambda c: c.start)


def unknown_candidates(output: str, *, known: KnownEntityDictionary, sources: tuple[str, ...]) -> list[EntityCandidate]:
    """出力に出た候補のうち、辞書・設定の本文・元の本文のどれにもないもの（Entity Delta の「増えた側」）。"""
    out = []
    for c in extract_candidates(output):
        if known.knows(c.text) or any(c.text in s for s in sources):
            continue
        out.append(c)
    return out
