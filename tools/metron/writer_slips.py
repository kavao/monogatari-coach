"""書き手の稿の崩れを拾う補助の印（計画 §16.6）。判定・保存の条件にはしない。

拾うもの（作業者が意味の確認で読む前の目印）:

- 作業指示の漏れ: プロンプトの語（「方針に従」「指示目標」「本文下限」など）が地の文にある
- 意図の写し: Beat の ``intent`` の文と、ほぼ同じ文が本文にある
- 段落の二重書き: 同じ稿の中に、ほぼ同じ段落が二度ある
- 地の文の敬称: 会話（「」『』）の外で、名前に「さん」が付く
- 視点の崩れ: 三人称の作品で、会話の外に一人称（俺・僕・私は など）がある

LLM を呼ばない。数え方は決定的。
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

# プロンプトの見出し・指示の語。本文の語として普通に出にくいものだけを置く。
LEAK_TERMS = (
    "方針に従", "指示目標", "本文下限", "本文段落数", "感覚描写:", "内面描写:", "会話の往復数",
    "水増し", "Beat", "beat:", "意図:", "重要度:", "factマーカー", "検査の床", "既出事実",
    "許容帯", "規定量調整",
    # 執筆方針・見せ方軸の語（例: 「近距離三人称」）。地の文で「近距離で確認した」のように漏れる。
    "近距離",
)
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_DIALOGUE_RE = re.compile(r"「[^」]*」|『[^』]*』")
_SENTENCE_RE = re.compile(r"[^。！？!?\n]+[。！？!?]?")
_COMPACT_RE = re.compile(r"[\s　。、．，！？!?…・「」『』（）()]")
_HONORIFIC_RE = re.compile(r"([一-龥々ァ-ヴー]{2,6})さん")
# 「私人」「私的」などの語を一人称に数えない。助詞が続く「私」だけを数える。
_FIRST_PERSON_RE = re.compile(r"俺|僕|私(?=[はがをにのもへとでや、])")

SIMILAR = 0.9
MIN_PARAGRAPH = 20
MIN_SENTENCE = 12
EXCERPT = 24


def _compact(text: str) -> str:
    return _COMPACT_RE.sub("", text)


def _excerpt(text: str) -> str:
    text = text.strip()
    return text if len(text) <= EXCERPT else text[:EXCERPT] + "…"


def _narration(text: str) -> str:
    """会話と HTML コメントを除いた地の文。"""
    return _DIALOGUE_RE.sub("", _COMMENT_RE.sub("", text))


def _similar(left: str, right: str) -> bool:
    a, b = _compact(left), _compact(right)
    if not a or not b:
        return False
    return SequenceMatcher(None, a, b, autojunk=False).ratio() >= SIMILAR


def _grouped_slips(text: str, *, intent: str, third_person: bool) -> list[tuple[str, str, int, int, str]]:
    """(群, 座標, 始まり, 終わり, 表示) の一覧。

    群は種類と検出の単位（語・名前・正規化した文）で、位置を含めない。座標は ``narration``（会話と
    コメントを除いた地の文）か ``clean``（コメントだけ除いた本文）で、始まりと終わりはその中の位置。
    """

    clean = _COMMENT_RE.sub("", text)
    narration = _narration(text)
    found: list[tuple[str, str, int, int, str]] = []

    def window(index: int, before: int, after: int) -> str:
        return narration[max(0, index - before):index + after]

    for term in LEAK_TERMS:
        for match in re.finditer(re.escape(term), narration):
            found.append((f"leak:{term}", "narration", match.start(), match.end(),
                          f"作業指示の漏れ: 「{_excerpt(window(match.start(), 8, 16))}」"))

    sentence_spans = [(match.start(), match.end(), match.group(0)) for match in _SENTENCE_RE.finditer(clean)]
    if intent.strip():
        intents = [item for item in _SENTENCE_RE.findall(intent) if len(_compact(item)) >= MIN_SENTENCE]
        for begin, finish, sentence in sentence_spans:
            if len(_compact(sentence)) < MIN_SENTENCE:
                continue
            if any(_similar(sentence, item) for item in intents or [intent]):
                found.append((f"intent:{_compact(sentence)}", "clean", begin, finish,
                              f"意図の写し: 「{_excerpt(sentence)}」"))

    # 段落の頭が違っても、長い文がほぼそのまま二度出れば二重書きとして拾う。
    long_spans = [item for item in sentence_spans if len(_compact(item[2])) >= MIN_PARAGRAPH]
    for index, (begin, finish, sentence) in enumerate(long_spans):
        if any(_similar(sentence, earlier[2]) for earlier in long_spans[:index]):
            found.append((f"dup:{_compact(sentence)}", "clean", begin, finish,
                          f"文の二重書き: 「{_excerpt(sentence.strip())}」"))

    for match in _HONORIFIC_RE.finditer(narration):
        found.append((f"honorific:{match.group(0)}", "narration", match.start(), match.end(),
                      f"地の文の敬称: 「{match.group(0)}」"))

    if third_person:
        for match in _FIRST_PERSON_RE.finditer(narration):
            found.append((f"first:{match.group(0)}", "narration", match.start(), match.end(),
                          f"視点の崩れ（地の文の一人称）: 「{_excerpt(window(match.start(), 8, 12))}」"))
    return found


def detect_slips(text: str, *, intent: str = "", third_person: bool = False) -> list[str]:
    """崩れの印を「種類: 抜粋」の形で返す。無ければ空。"""

    return _with_counts([item[4] for item in _grouped_slips(text, intent=intent, third_person=third_person)])


def _with_counts(labels: list[str]) -> list[str]:
    """同じ表示を一つにまとめ、2件以上なら「（N件）」を添える。"""
    counts: dict[str, int] = {}
    for label in labels:
        counts[label] = counts.get(label, 0) + 1
    return [label if number == 1 else f"{label}（{number}件）" for label, number in counts.items()]


def _unchanged(original: str, candidate: str) -> list[tuple[int, int]]:
    """候補の中で、元の稿とそのまま同じ範囲。"""
    matcher = SequenceMatcher(None, original, candidate, autojunk=False)
    return [(block.b, block.b + block.size) for block in matcher.get_matching_blocks() if block.size]


def new_slips(original: str, candidate: str, *, intent: str = "", third_person: bool = False) -> list[str]:
    """候補で新しく出た印だけ。元の稿にすでにある印は出さない。

    群（種類と検出の単位）ごとに数を比べ、候補で増えた数だけを出す。どれを出すかは、元の稿と
    同じ範囲に収まらない一致（候補で足された・書き換わった所にかかる一致）を先にする。
    """

    kwargs = {"intent": intent, "third_person": third_person}
    before: dict[str, int] = {}
    for item in _grouped_slips(original, **kwargs):
        before[item[0]] = before.get(item[0], 0) + 1
    spaces = {
        "narration": _unchanged(_narration(original), _narration(candidate)),
        "clean": _unchanged(_COMMENT_RE.sub("", original), _COMMENT_RE.sub("", candidate)),
    }

    def kept(space: str, begin: int, finish: int) -> bool:
        return any(start <= begin and finish <= end for start, end in spaces[space])

    by_group: dict[str, list[tuple[bool, str]]] = {}
    for group, space, begin, finish, label in _grouped_slips(candidate, **kwargs):
        by_group.setdefault(group, []).append((kept(space, begin, finish), label))
    labels: list[str] = []
    for group, items in by_group.items():
        extra = len(items) - before.get(group, 0)
        if extra <= 0:
            continue
        ordered = [label for old, label in items if not old] + [label for old, label in items if old]
        labels.extend(ordered[:extra])
    return _with_counts(labels)  # 増えた数は件数で残す


def is_third_person(config_text: str) -> bool:
    """config.md の執筆方針が三人称で、一人称の指定が無いとき。読めなければ False（視点は見ない）。"""

    return "三人称" in config_text and "一人称" not in config_text
