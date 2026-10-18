"""場面単位の語句反復（D18）。Deepen の棄却、指示の「繰り返さない語句」、清書の材料に使う。

043 第2章の実測（10字の語句で場面内3回以上: 調整前 1種 → Deepen 後 36種 → 清書後 7種）
から、文ごとの10字の語句が場面全体で3回目以上になることを反復の目印にする。
語句は文の中だけで数え、文の境目をまたがない（短い文の連打を誤って拾わないため）。
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from difflib import SequenceMatcher
import re
import unicodedata

PHRASE_CHARS = 10
REPEAT_LIMIT = 3
AVOID_MIN_COUNT = 2

_SENTENCE_RE = re.compile(r".+?(?:[。！？!?]|$)", re.DOTALL)
_STRIP_RE = re.compile(r"[\s　。、．，！？!?…・「」『』（）()\[\]【】]")
_MARKER_RE = re.compile(r"<!--.*?-->")

# Deepen の指示に載せる禁止の型（§13.1 の類型を一般化したもの）。
STYLE_RULES = (
    "同じ修飾句・枕詞を場面の中で繰り返さない（印象的な語句ほど1〜2回に絞る）。",
    "心理の迷いや葛藤を Beat ごとにやり直さない。前の Beat までに進んだ気持ちの続きから書く。",
    "距離や時間を数値で測らない（「数十センチ」など）。息遣い・手触りなど身体の実感で書く。",
    "Beat の末尾を、同じ型の情景（季節の空気・設備の音など）で締めない。",
)


def sentences(text: str) -> list[str]:
    normalized = _MARKER_RE.sub("", unicodedata.normalize("NFC", text))
    return [
        part.strip()
        for line in normalized.splitlines()
        for part in _SENTENCE_RE.findall(line)
        if part.strip()
    ]


def _compact(sentence: str) -> str:
    return _STRIP_RE.sub("", sentence)


_MASK = "\0"


def sentence_phrases(sentence: str, n: int = PHRASE_CHARS,
                     allowed: Iterable[str] = ()) -> set[str]:
    """文の中の n 字の語句。意図した反復（allowed）に掛かる語句は数えない。"""

    compact = _compact(sentence)
    for item in allowed:
        token = _compact(item)
        if token:
            compact = compact.replace(token, _MASK * len(token))
    if len(compact) < n:
        return set()
    grams = (compact[index : index + n] for index in range(len(compact) - n + 1))
    return {gram for gram in grams if _MASK not in gram}


def _masked(sentence: str, allowed: Iterable[str]) -> str:
    compact = _compact(sentence)
    for item in allowed:
        token = _compact(item)
        if token:
            compact = compact.replace(token, _MASK * len(token))
    return compact


def _corpus(texts: Iterable[str], allowed: Iterable[str] = ()) -> list[str]:
    """語句をつないだ結果が実在するかを確かめるための、文ごとの詰めた本文。"""

    allowed = list(allowed)
    return [_masked(sentence, allowed) for text in texts for sentence in sentences(text)]


def phrase_counts(texts: Iterable[str], n: int = PHRASE_CHARS,
                  allowed: Iterable[str] = ()) -> Counter:
    """語句ごとに、その語句を含む文の数を数える（1文の中の重複は1回）。"""

    allowed = list(allowed)
    counts: Counter = Counter()
    for text in texts:
        for sentence in sentences(text):
            counts.update(sentence_phrases(sentence, n, allowed))
    return counts


def _overlaps(left: str, right: str) -> bool:
    """同じ語句をずらして切り出しただけか（共通部分が語句の長さの7割以上）。"""

    match = SequenceMatcher(None, left, right, autojunk=False).find_longest_match(
        0, len(left), 0, len(right))
    return match.size >= max(1, int(min(len(left), len(right)) * 0.7))


def count_phrase(texts: Iterable[str], phrase: str, allowed: Iterable[str] = ()) -> int:
    """語句そのものを含む文の数（1文の中の重複は1回）。

    つないだ長い語句も、構成する短い語句の回数からは推し量らず、文の中に実在する回数を数える。
    """

    return sum(1 for sentence in _corpus(texts, allowed) if phrase in sentence)


def _chains(ranked: list[tuple[str, int]], corpus: list[str]) -> list[tuple[str, int]]:
    """同じ回数の語句を、1字ずれの隣接（先頭の n-1 字が前の語句の末尾 n-1 字）でつなぐ。

    つないだ語句が、同じ回数だけ文の中に実在するときだけ伸ばす（別の文の語句を合成しない）。
    """

    def occurs(phrase: str) -> int:
        return sum(1 for sentence in corpus if phrase in sentence)

    by_count: dict[int, list[str]] = {}
    for phrase, count in ranked:
        by_count.setdefault(count, []).append(phrase)
    result: list[tuple[str, int]] = []
    for count, phrases in by_count.items():
        members = set(phrases)
        successors: dict[str, list[str]] = {}
        has_predecessor: set[str] = set()
        for phrase in phrases:
            nexts = [other for other in phrases
                     if other != phrase and other[:-1] == phrase[1:]]
            successors[phrase] = nexts
            has_predecessor.update(nexts)
        used: set[str] = set()
        for phrase in phrases:
            if phrase in used or phrase in has_predecessor:
                continue
            chain, current = phrase, phrase
            used.add(current)
            while len(successors.get(current, [])) == 1 and successors[current][0] not in used:
                following = successors[current][0]
                if occurs(chain + following[-1]) < count:
                    break
                current = following
                used.add(current)
                chain += current[-1]
            result.append((chain, count))
        result.extend((phrase, count) for phrase in phrases if phrase not in used and phrase in members)
    return sorted(result, key=lambda item: (-item[1], -len(item[0]), item[0]))


def _distinct(ranked: list[tuple[str, int]], limit: int | None,
              corpus: list[str]) -> list[tuple[str, int]]:
    """ずれて重なる語句を鎖にして最長の1つにし、残る重なり（包含など）は除く。"""

    kept: list[tuple[str, int]] = []
    for phrase, count in _chains(ranked, corpus):
        if any(_overlaps(phrase, other) for other, _ in kept):
            continue
        kept.append((phrase, count))
        if limit is not None and len(kept) >= limit:
            break
    return kept


def introduced_repeats(
    before_texts: Iterable[str],
    after_texts: Iterable[str],
    new_sentences: Iterable[str],
    *,
    allowed: Iterable[str] = (),
    n: int = PHRASE_CHARS,
    limit: int = REPEAT_LIMIT,
) -> list[tuple[str, int]]:
    """新しい文が持ち込み、場面全体で limit 回目以上になった語句（多い順）。"""

    allowed = list(allowed)
    after_texts = list(after_texts)
    before = phrase_counts(before_texts, n, allowed)
    after = phrase_counts(after_texts, n, allowed)
    hits: dict[str, int] = {}
    for sentence in new_sentences:
        for phrase in sentence_phrases(sentence, n, allowed):
            if after[phrase] >= limit and after[phrase] > before[phrase]:
                hits[phrase] = after[phrase]
    ranked = sorted(hits.items(), key=lambda item: (-item[1], item[0]))
    return _distinct(ranked, None, _corpus(after_texts, allowed))


def frequent_phrases(
    texts: Iterable[str],
    *,
    allowed: Iterable[str] = (),
    min_count: int = AVOID_MIN_COUNT,
    n: int = PHRASE_CHARS,
    limit: int = 8,
) -> list[str]:
    """場面内ですでに min_count 回以上使われた語句（Deepen の「繰り返さない語句」）。"""

    texts = list(texts)
    allowed = list(allowed)
    counts = phrase_counts(texts, n, allowed)
    ranked = sorted(((phrase, count) for phrase, count in counts.items() if count >= min_count),
                    key=lambda item: (-item[1], item[0]))
    return [phrase for phrase, _ in _distinct(ranked, limit, _corpus(texts, allowed))]


def repeat_report(
    before_texts: Iterable[str],
    after_texts: Iterable[str],
    *,
    n: int = PHRASE_CHARS,
    limit: int = REPEAT_LIMIT,
    top: int = 12,
) -> list[tuple[str, int, int]]:
    """後の稿で limit 回以上出る語句の、前後の回数（増えたもの・多い順）。"""

    before_texts = list(before_texts)
    after_texts = list(after_texts)
    before = phrase_counts(before_texts, n)
    after = phrase_counts(after_texts, n)
    ranked = sorted(((phrase, count) for phrase, count in after.items()
                     if count >= limit and count > before[phrase]),
                    key=lambda item: (-item[1], item[0]))
    return [(phrase, count_phrase(before_texts, phrase), count_phrase(after_texts, phrase))
            for phrase, _ in _distinct(ranked, top, _corpus(after_texts))]


def style_rules_text(avoid: Iterable[str]) -> str:
    avoid = list(avoid)
    lines = list(STYLE_RULES)
    if avoid:
        lines.append("この場面ですでに繰り返し使われている語句（これ以上使わない）: "
                     + "、".join(f"「{item}」" for item in avoid))
    return "\n".join(lines)


def repeated_phrase_lines(
    lines: Iterable[tuple[int, str]],
    *,
    n: int = PHRASE_CHARS,
    limit: int = REPEAT_LIMIT,
) -> list[tuple[str, int, int]]:
    """(行番号, 行) の並びから、limit 回以上出る語句と回数、limit 回目の行番号を返す（清書の材料）。"""

    lines = list(lines)
    seen: dict[str, list[int]] = {}
    for number, line in lines:
        for sentence in sentences(line):
            for phrase in sentence_phrases(sentence, n):
                seen.setdefault(phrase, []).append(number)
    ranked = sorted(((phrase, len(numbers)) for phrase, numbers in seen.items()
                     if len(numbers) >= limit), key=lambda item: (-item[1], item[0]))
    result = []
    corpus = _corpus(line for _, line in lines)
    for phrase, count in _distinct(ranked, None, corpus):
        # つないだ語句は元の語句の行を持たないので、先頭の n 字で行番号を引く。
        result.append((phrase, count, seen[phrase[:n]][limit - 1]))
    return result
