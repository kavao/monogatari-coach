#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""本文の候補を機械で比べるための指標（計画 _workingspace/plans/20261114_model-adaptive-writing-support.md §21〜§24）。

小さな書き手が、渡した文や自分の前の文を地の文へ写す崩れを数える。どの値も読みやすさそのものではなく、
「ひどい候補を外す」ための代わりの物差し（§23.2 の7）。閾値は試験作品140の第1章で決めた仮の値。

- narration / sentences: 地の文（「」の中を除く）と、その文
- trait_phrases / trait_copy_per_k: character.md の外見・癖・口調の句が、地の文に6字の並びで出る回数
- tell_per_k: 結論を告げる文末（「と知った」「と気づいた」など）の数
- overlaps: 候補の中で、これまでの本文と n 字以上一致する部分
- appearance_lines / redescribed: すでに出た人物の外見の行と、6字以上一致する部分（外見の描き直し）
- lookahead: 後の Beat の出来事と8字以上一致し、今の出来事に無い部分（先取り）
- forbidden_terms / forbidden_hits: 場面契約で書かないと決めた語と、候補に出たその語
- repeated_lines: 同じ形の台詞（丸写し・頭と結びが同じ型）が場面で3回目以上になるもの（口癖の繰り返し）
"""

from __future__ import annotations

import re

TELL_RE = re.compile(r"(と知った|と知る|と気づいた|と気付いた|と認めた|と分かった|とわかった|と口にした|と口にし)")
HEADING_RE = re.compile(r"^##\s+([^（(\s]+)")
FIELD_RE = re.compile(r"^- \*\*([^*]+)\*\*:\s*(.*)$")
TRAIT_FIELD_RE = re.compile(r"(ワンポイント特徴|外見|癖|口調)")

OVERLAP_CHARS = 12
REDESCRIBE_CHARS = 6
LOOKAHEAD_CHARS = 8
# 先取りの比べで外す記号（intent は要約の文で台詞の括弧も読点も揃わないので、字だけで比べる）
_LOOKAHEAD_STRIP = re.compile(r"[\s「」『』（）()、。，！？!?…・]")
FORBIDDEN_TERM_RE = re.compile(r"^(.+?)という語を(?:本文に)?書く")
# 台詞の繰り返し: 場面全体で同じ形がこの回数に達していたら、次の1回を外す（3回目以上。Deepen の語句反復と同じ数）
REPEAT_LIMIT = 2
REPEAT_CONTAIN_CHARS = 6  # 丸写しとみなす短い方の台詞の字数の下限（「直せる物は残します」に呼びかけが付いた形も拾う）
REPEAT_HEAD_CHARS = 3  # 型の頭（「別に、」）
REPEAT_TAIL_CHARS = 4  # 型の結び（「だけです」）
_DIALOGUE_RE = re.compile(r"「([^」]*)」")


def narration(text: str) -> str:
    """見出しと HTML コメントと「」の中を除いた地の文。"""
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    text = re.sub(r"^#.*$", "", text, flags=re.M)
    return re.sub(r"「[^」]*」", "", text)


def sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"[。\n]", text) if len(s.strip()) >= 4]


def _per_k(count: float, chars: int) -> float:
    return count * 1000 / max(chars, 1)


def trait_phrases(character_md: str) -> list[str]:
    """外見・癖・口調などの欄と、その下の箇条書きから、5〜30字の句を取り出す。"""
    out: set[str] = set()
    for line in character_md.splitlines():
        if TRAIT_FIELD_RE.search(line) or re.match(r"\s+- ", line):
            body = re.sub(r"^\s*-\s*(\*\*[^*]+\*\*:)?", "", line)
            for part in re.split(r"[、。「」]", body):
                part = part.strip()
                if 5 <= len(part) <= 30:
                    out.add(part)
    return sorted(out)


def trait_copy_per_k(narr: str, phrases: list[str]) -> float:
    hits = sum(narr.count(ph[i : i + 6]) for ph in phrases for i in range(len(ph) - 5))
    return _per_k(hits, len(narr))


def tell_per_k(narr: str) -> float:
    return _per_k(sum(1 for s in sentences(narr) if TELL_RE.search(s)), len(narr))


def overlaps(candidate: str, prior: str, n: int = OVERLAP_CHARS) -> list[str]:
    """候補の中で、prior と n 字以上一致する部分（空白を除いて比べ、続く一致は一つに畳む）。

    台詞の括弧をまたぐ一致は数えない（「…す」ノラは言った。「…」のような、話し手の決まり文句が
    台詞の端とつながっただけの一致を外す）。括弧は、候補と prior で別の、一致しない字に置き換えて比べる。
    """
    c = re.sub(r"[「」『』]", "\x00", re.sub(r"\s", "", candidate))
    p = re.sub(r"[「」『』]", "\x01", re.sub(r"\s", "", prior))
    hits: list[str] = []
    i = 0
    while i <= len(c) - n:
        if c[i : i + n] in p:
            j = i + n
            while j < len(c) and c[i : j + 1] in p:
                j += 1
            hits.append(c[i:j])
            i = j
        else:
            i += 1
    return hits


def dialogue_lines(text: str) -> list[str]:
    """「」の中身（空白を除く）。空の台詞は除く。"""
    return [s for s in (re.sub(r"\s", "", m) for m in _DIALOGUE_RE.findall(text)) if s]


def same_line_form(a: str, b: str) -> bool:
    """二つの台詞が同じ形か。丸写し（短い方が6字以上で、長い方に含まれる）か、
    頭3字と結び4字がどちらも同じ型（「別に、見ただけです」と「別に、布を折っただけです」）。"""
    short, long_ = sorted((a, b), key=len)
    if short == long_ or (len(short) >= REPEAT_CONTAIN_CHARS and short in long_):
        return True
    span = REPEAT_HEAD_CHARS + REPEAT_TAIL_CHARS
    return len(short) > span and a[:REPEAT_HEAD_CHARS] == b[:REPEAT_HEAD_CHARS] and a[-REPEAT_TAIL_CHARS:] == b[-REPEAT_TAIL_CHARS:]


def repeated_lines(candidate: str, prior: str, limit: int = REPEAT_LIMIT) -> list[str]:
    """候補の台詞のうち、同じ形の台詞がこれまでの本文と候補の前の部分に limit 回以上出ているもの。

    8〜12字の一致では捕まらない言い換え（口癖の型に別の動詞を入れた形）を拾う。1〜2回目は残す。
    """
    seen = dialogue_lines(prior)
    hits: list[str] = []
    for line in dialogue_lines(candidate):
        if sum(1 for s in seen if same_line_form(line, s)) >= limit:
            hits.append(line)
        seen.append(line)
    return hits


def lookahead(candidate: str, later: str, current: str, prior: str = "", n: int = LOOKAHEAD_CHARS) -> list[str]:
    """候補の中で、後の出来事（later。後の Beat の intent）と n 字以上一致し、今の出来事（current）にも
    これまでの本文（prior）にも無い部分。書き手が次の Beat の出来事や台詞を先に書いた跡（先取り）。

    台詞も含めて、記号を除いた字だけで比べる。続く一致は一つに畳む。
    """
    c = _LOOKAHEAD_STRIP.sub("", candidate)
    lat, cur, pri = (_LOOKAHEAD_STRIP.sub("", t) for t in (later, current, prior))
    hits: list[str] = []
    i = 0
    while i <= len(c) - n:
        gram = c[i : i + n]
        if gram in lat and gram not in cur and gram not in pri:
            j = i + n
            while j < len(c) and c[i : j + 1] in lat and c[i : j + 1] not in cur:
                j += 1
            hits.append(c[i:j])
            i = j
        else:
            i += 1
    return hits


def forbidden_terms(forbidden: list[str]) -> list[str]:
    """場面契約の forbidden のうち「〇〇という語を書くこと」の形から、語だけを取り出す（行動の禁止は語で測れないので除く）。"""
    out = []
    for item in forbidden:
        m = FORBIDDEN_TERM_RE.match(str(item).strip())
        if m:
            out.append(m.group(1).strip("「」『』 "))
    return out


def forbidden_hits(text: str, terms: list[str]) -> list[str]:
    return [t for t in terms if t and t in text]


def character_blocks(character_md: str) -> dict[str, list[str]]:
    """「## 名（読み）」の見出しごとの行。名は括弧の前まで。"""
    blocks: dict[str, list[str]] = {}
    current: str | None = None
    for line in character_md.splitlines():
        m = HEADING_RE.match(line)
        if m:
            current = str(m.group(1))
            blocks[current] = []
        elif current is not None:
            blocks[current].append(line)
    return blocks


def appearance_lines(character_md: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for name, lines in character_blocks(character_md).items():
        for line in lines:
            m = FIELD_RE.match(line)
            if m and m.group(1) == "外見":
                out[name] = m.group(2).strip()
    return out


def redescribed(candidate: str, names: set[str], appearance: dict[str, str], n: int = REDESCRIBE_CHARS) -> list[str]:
    """names の人物の外見の行と、n 字以上一致する部分（人物ごと・句ごとに一つ）。"""
    out: list[str] = []
    for name in sorted(names):
        for part in re.split(r"[、。]", appearance.get(name, "")):
            for k in range(len(part) - n + 1):
                if part[k : k + n] in candidate:
                    out.append(f"{name}:{part[k:k + n]}")
                    break
    return out
