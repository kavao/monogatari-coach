"""規定量調整（目標字数への伸縮）。出来事を変えない OP-R / OP-T だけを扱う。

基準は ``_how_to.example/length_ops.md``。許容帯に入ったら止め、増減を往復しない。
増量で上限を超えたときだけ引き締めで戻す。届かなければ報告して止め、出来事の
追加（加筆工程）や削除（改稿工程）はここでは行わない。provider は呼ばない。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from difflib import SequenceMatcher
import math
import re
import unicodedata

from novel_char_count import count_chars

from pydantic import Field

from .analyze import analyze_marked_text
from .calibrate import ModelCalibration
from .classify import classify_metrics
from .episodes import (
    ChildEpisode, EpisodeError, build_condense_prompt, condense_priority, locate_span, splice,
)
from .models import Beat, BeatPlan, LengthTarget, MetricsDocument, SpansDocument, StrictModel
from .prompt import current_beat_chars


LENGTH_TOKEN = "__length__"
# D19: 清書で削られる分の余地（043 第2章の実測で清書が -8.6%）。
DEFAULT_FINISH_MARGIN = 0.08
# 清書後が仕上がり目標から数%ずれる程度は誤差として扱い、無理に合わせない（床は別。ルールで厳守）。
FINISH_SLACK = 0.05
# D21: Deepen（OP-R）で埋めてよい不足の上限。これ以上の不足は、出来事を足す設計追加へ回す。
DESIGN_SHORTAGE_LIMIT = 0.10


def shortage_ratio(target_chars: int, current_chars: int) -> float:
    """同じ対象範囲の目標 T と本文字数 C から max(0, T - C) / T を出す（D21）。"""

    if target_chars <= 0:
        return 0.0
    return max(0, target_chars - current_chars) / target_chars
# 引き締め候補の各文の文字が、元文のどれかの文へこの割合以上、順序どおりに含まれること。
# 迂言の圧縮（「走るという行動を開始した」→「走り出した」）は通し、新しい文を検出する。
TIGHTEN_CONTAINMENT = 0.6
# 1 回の引き締めで Beat がこれより短くなる候補は、出来事の欠落を疑って受けない。
TIGHTEN_MIN_RATIO = 0.5
MAX_ATTEMPTS_PER_BEAT = 2
_WEIGHT_ORDER = {"heavy": 0, "normal": 1, "light": 2}
_KATAKANA_RE = re.compile(r"[ァ-ヴー]{2,}")
_STRIP_RE = re.compile(r"[\s　。、．，！？!?…・「」『』（）()\[\]【】]")
_SENTENCE_RE = re.compile(r".+?(?:[。！？!?]|$)", re.DOTALL)


class LengthConfigError(ValueError):
    """許容帯と床が両立しないなど、規定量調整を始められない設定。"""


class LengthSpec(StrictModel):
    target: LengthTarget
    known_facts: str = ""
    # 減量で収束（OP-C）してよい子エピソード。作者が episodes.yaml に登録したものだけ。
    episodes: list[ChildEpisode] = Field(default_factory=list)


@dataclass(frozen=True)
class LengthBounds:
    lower_chars: int
    upper_chars: int
    effective_lower: int
    floor: int
    scene_floor: int
    floor_raised: bool


def resolve_bounds(target: LengthTarget, plan: BeatPlan) -> LengthBounds:
    """許容帯を字数にし、床と照合する。両立しない設定は受け付けない。"""

    if target.scope == "chapter":
        raise LengthConfigError("chapter scope is not supported by METRON; adjust each scene")
    scene_floor = plan.generation.chars_floor
    if target.scope == "beat":
        beat = next((item for item in plan.beats if item.id == target.beat_id), None)
        if beat is None:
            raise LengthConfigError(f"unknown beat_id: {target.beat_id}")
        floor = beat.budget.chars_hint
    else:
        floor = scene_floor
    # 浮動小数の誤差で 4000×0.97 が 3881 にならないよう丸めてから切り上げる。
    lower = math.ceil(round(target.target_chars * target.tolerance.lower, 6))
    upper = math.floor(round(target.target_chars * target.tolerance.upper, 6))
    if upper < floor:
        raise LengthConfigError(
            f"length band upper {upper} is below the floor {floor}; the band and floor cannot both hold"
        )
    effective = max(lower, floor)
    if target.finish_chars is not None:
        finish = finish_bounds(target, plan)
        if finish is not None and finish[0] > finish[1]:
            raise LengthConfigError(
                f"finish band upper {finish[1]} is below the floor {floor}; "
                "the finished length and the floor cannot both hold")
    return LengthBounds(lower, upper, effective, floor, scene_floor, effective > lower)


def finish_target(finish_chars: int, *, margin: float = DEFAULT_FINISH_MARGIN,
                  **fields) -> LengthTarget:
    """仕上がり目標から、余地を足した増量の目標を作る（D19）。"""

    if not 0 <= margin < 1:
        raise LengthConfigError("finish margin must be between 0 and 1")
    return LengthTarget(target_chars=round(finish_chars * (1 + margin)),
                        finish_chars=finish_chars, **fields)


def finish_bounds(target: LengthTarget, plan: BeatPlan) -> tuple[int, int] | None:
    """清書後の仕上がりの帯（下限は床まで引き上げる）。仕上がり目標が無ければ None。"""

    if target.finish_chars is None:
        return None
    floor = plan.generation.chars_floor
    if target.scope == "beat":
        beat = next(item for item in plan.beats if item.id == target.beat_id)
        floor = beat.budget.chars_hint
    lower = math.ceil(round(target.finish_chars * target.tolerance.lower, 6))
    upper = math.floor(round(target.finish_chars * target.tolerance.upper, 6))
    return max(lower, floor), upper


def assembled_chars(plan: BeatPlan, texts: dict[str, str]) -> int:
    """Beat 本文の合計字数（Beat 外の章見出しなどは含めない）。"""

    newline = "\n"
    joined = "\n\n".join(texts.get(beat.id, "").strip(newline) for beat in plan.beats)
    return count_chars(joined, strip_fm=False)


def beat_chars(text: str) -> int:
    """結合時と同じく前後の改行を除いた Beat の字数。"""

    return count_chars(text.strip("\n"), strip_fm=False)


def measured_chars(target: LengthTarget, plan: BeatPlan, texts: dict[str, str]) -> int:
    if target.scope == "beat":
        return beat_chars(texts.get(target.beat_id or "", ""))
    return assembled_chars(plan, texts)


def band_state(chars: int, bounds: LengthBounds) -> str:
    if chars < bounds.effective_lower:
        return "short"
    if chars > bounds.upper_chars:
        return "over"
    return "in_band"


def _sentences(text: str) -> list[str]:
    normalized = unicodedata.normalize("NFC", text)
    return [
        part.strip()
        for line in normalized.splitlines()
        for part in _SENTENCE_RE.findall(line)
        if part.strip()
    ]


def _compact(text: str) -> str:
    return _STRIP_RE.sub("", unicodedata.normalize("NFC", text))


def _best_source(sentence: str, sources: list[str]) -> tuple[int, float]:
    """候補文の文字を順序どおり最もよく含む元文の位置と、その割合を返す。"""

    compact = _compact(sentence)
    if not compact:
        return -1, 1.0
    best_index, best_score = -1, 0.0
    for index, source in enumerate(sources):
        matcher = SequenceMatcher(None, compact, _compact(source), autojunk=False)
        score = sum(block.size for block in matcher.get_matching_blocks()) / len(compact)
        if score > best_score:
            best_index, best_score = index, score
    return best_index, best_score


@dataclass(frozen=True)
class TighteningCheck:
    accepted: bool
    reason: str


def validate_tightening(original: str, candidate: str, *, min_chars: int = 0) -> TighteningCheck:
    """引き締め候補の形の検査。出来事の欠落は検出できないため著者確認を別に要する。"""

    original_n = unicodedata.normalize("NFC", original)
    candidate_n = unicodedata.normalize("NFC", candidate)
    if not candidate_n.strip():
        return TighteningCheck(False, "candidate is empty")
    if original_n.strip() == candidate_n.strip():
        return TighteningCheck(False, "candidate is identical to the original")
    before = beat_chars(original_n)
    after = beat_chars(candidate_n)
    if after >= before:
        return TighteningCheck(False, "candidate does not decrease length")
    if after < before * TIGHTEN_MIN_RATIO:
        return TighteningCheck(False, "tightening removed too much; suspect lost events")
    if after < min_chars:
        return TighteningCheck(False, "tightening falls below the effective lower bound or floor")
    sources = _sentences(original_n)
    last = -1
    for sentence in _sentences(candidate_n):
        index, score = _best_source(sentence, sources)
        if score < TIGHTEN_CONTAINMENT:
            return TighteningCheck(False, "candidate adds a sentence not found in the original")
        if index < last:
            return TighteningCheck(False, "candidate changes the sentence order")
        last = index
    return TighteningCheck(True, "accepted")


@dataclass(frozen=True)
class CanonReviewDigest:
    """著者による事実確認に出すもの。印は補助であり、合否の判定ではない。"""

    new_sentences: tuple[str, ...]
    removed_sentences: tuple[str, ...]
    new_terms: tuple[str, ...]
    removed_terms: tuple[str, ...]
    # 前後の両方にあるが、順序が変わった文（存在の比較だけでは見えない並べ替え）。
    moved_sentences: tuple[str, ...] = ()


def moved_sentences(before: list[str], after: list[str]) -> tuple[str, ...]:
    """両方にある文のうち、最長の共通の並びから外れた文を、調整後の順で返す。"""

    common_before = [item for item in before if item in after]
    common_after = [item for item in after if item in before]
    matcher = SequenceMatcher(None, common_before, common_after, autojunk=False)
    kept: set[int] = set()
    for block in matcher.get_matching_blocks():
        kept.update(range(block.b, block.b + block.size))
    return tuple(item for index, item in enumerate(common_after) if index not in kept)


def canon_review_digest(
    original: str,
    candidate: str,
    *,
    known_text: str = "",
    names: tuple[str, ...] = (),
) -> CanonReviewDigest:
    before = _sentences(original)
    after = _sentences(candidate)
    new = tuple(item for item in after if item not in before)
    removed = tuple(item for item in before if item not in after)
    known = unicodedata.normalize("NFC", original + "\n" + known_text)
    new_terms: list[str] = []
    for sentence in new:
        for term in _KATAKANA_RE.findall(sentence):
            if term not in known and term not in new_terms:
                new_terms.append(term)
    candidate_n = unicodedata.normalize("NFC", candidate)
    original_n = unicodedata.normalize("NFC", original)
    watched = list(dict.fromkeys([*_KATAKANA_RE.findall(original_n), *names]))
    moved = moved_sentences(before, after)
    removed_terms = tuple(
        term for term in watched if term and term in original_n and term not in candidate_n
    )
    return CanonReviewDigest(new, removed, tuple(new_terms), removed_terms, moved)


def build_length_deepen_prompt(
    beat: Beat,
    current_text: str,
    *,
    need_chars: int,
    room_chars: int,
    bounds: LengthBounds,
    known_facts: str,
    avoid: tuple[str, ...] = (),
) -> str:
    from .repetition import style_rules_text

    return "\n".join(
        [
            f"Beat {beat.id} の規定量調整（増量）。",
            f"意図: {beat.intent}",
            f"この Beat の現在の字数は {current_beat_chars(current_text)}字。",
            f"あと {need_chars}字を目安に足す。{room_chars}字を超えて足さない（許容帯 {bounds.effective_lower}〜{bounds.upper_chars}字）。",
            "使ってよい過去・因果は、次の既出事実リストの範囲に限る:",
            known_facts or "（調整前の本文に書かれていることだけ）",
            "新しい出来事・人物・過去・選択・所持品を追加しない。",
            "増やすのは既にある出来事の解像度だけ: 動作の分解／感覚描写／人物の迷い・判断／相手の反応／その人物らしい癖。",
            "必要な字数を満たす分だけ増やし、すべての項目を埋めようとしない。",
            "同じ内容の言い換えや、段落末のまとめ直しで字数を稼がない。",
            "現在の本文を残したまま書き足す。既存文の削除・要約・書き直しはしない。",
            "許容帯に届かない場合は無理に増やさない。",
            style_rules_text(avoid),
            "現在の Beat 本文:",
            current_text,
            "この Beat の本文だけを出力する。",
        ]
    )


def build_tighten_prompt(beat: Beat, current_text: str, *, reduce_chars: int, min_chars: int) -> str:
    return "\n".join(
        [
            f"Beat {beat.id} の規定量調整（引き締め）。",
            f"この Beat の現在の字数は {current_beat_chars(current_text)}字。",
            f"{reduce_chars}字を目安に減らす。{min_chars}字より短くしない。",
            "同義反復・まとめ直し・前置き・迂言と、冗長な修飾だけを削る（意図的な繰り返しは残す）。",
            "出来事・人物・所持品・情報の授受・心境の変化は一つも消さない。",
            "文の順序と段落の区切りを変えない。新しい文を足さない。",
            "範囲に入った時点で削るのをやめる。",
            "現在の Beat 本文:",
            current_text,
            "この Beat の本文だけを出力する。",
        ]
    )


def _deepen_order(plan: BeatPlan, texts: dict[str, str], target: LengthTarget) -> list[Beat]:
    if target.scope == "beat":
        return [beat for beat in plan.beats if beat.id == target.beat_id and beat.expandable]
    index = {beat.id: position for position, beat in enumerate(plan.beats)}
    candidates = [beat for beat in plan.beats if beat.expandable]
    # 山場（heavy）を先に、計画に対して薄い Beat から配る。
    return sorted(
        candidates,
        key=lambda beat: (
            _WEIGHT_ORDER[beat.weight],
            current_beat_chars(texts.get(beat.id, "")) / beat.budget.chars_hint,
            index[beat.id],
        ),
    )


def _tighten_order(plan: BeatPlan, texts: dict[str, str], target: LengthTarget) -> list[Beat]:
    if target.scope == "beat":
        return [beat for beat in plan.beats if beat.id == target.beat_id]
    index = {beat.id: position for position, beat in enumerate(plan.beats)}
    return sorted(
        plan.beats,
        key=lambda beat: (-current_beat_chars(texts.get(beat.id, "")), index[beat.id]),
    )


def tighten_min_chars(
    beat_id: str,
    plan: BeatPlan,
    texts: dict[str, str],
    target: LengthTarget,
    bounds: LengthBounds,
) -> int:
    """この Beat を引き締めても実効下限と場面の床を割らない最小字数。"""

    rest = assembled_chars(plan, texts) - beat_chars(texts.get(beat_id, ""))
    if target.scope == "beat":
        return max(bounds.effective_lower, bounds.scene_floor - rest, 0)
    return max(bounds.effective_lower - rest, 0)


def length_adjust_impl(
    metrics: MetricsDocument,
    beat_plan: BeatPlan,
    calibration: ModelCalibration,
    *,
    clean_text: str,
    spans: SpansDocument,
    length: LengthSpec,
    # (operation, beat_id, prompt[, episode_id]) -> 候補本文。episode_id は子エピソードの収束だけが渡す
    dispatch: Callable[..., str],
    checkpoint: Callable[[dict[str, str]], None] | None = None,
    allowed_repeats: tuple[str, ...] = (),
):
    """一方向の伸縮を ``max_passes`` 回まで行う。却下された候補も回数に数える。"""

    from .repair import SceneRepairResult, _text_by_beat, assemble_beat_texts, marked_text_for_measurement
    from .repair import _previous_text, strip_generation_markers
    from .models import Failure
    from .prompt import build_beat_prompt

    classification = classify_metrics(metrics, beat_plan, calibration, spans=spans)
    target = length.target
    bounds = resolve_bounds(target, beat_plan)
    texts = _text_by_beat(clean_text, beat_plan, spans)
    if checkpoint:
        checkpoint(dict(texts))
    by_id = {beat.id: beat for beat in beat_plan.beats}
    attempts: dict[tuple[str, str], int] = {}
    passes = 0
    notes: list[str] = []
    escalated: set[str] = set()
    if bounds.floor_raised:
        notes.append(
            f"LENGTH_LOWER_RAISED: band lower {bounds.lower_chars} raised to floor {bounds.floor}"
        )

    def current() -> int:
        return measured_chars(target, beat_plan, texts)

    def run(operation: str, beat: Beat, prompt: str, episode: ChildEpisode | None = None) -> None:
        nonlocal passes
        key = (operation, episode.id if episode else beat.id)
        attempts[key] = attempts.get(key, 0) + 1
        passes += 1
        if checkpoint:
            checkpoint(dict(texts))
        if episode is None:
            candidate = dispatch(operation, beat.id, prompt)
        else:
            candidate = dispatch(operation, beat.id, prompt, episode.id)
        if not candidate.strip():
            return
        cleaned = strip_generation_markers(candidate)
        texts[beat.id] = splice(texts[beat.id], episode, cleaned) if episode else cleaned

    def pick(order: list[Beat], operation: str) -> Beat | None:
        for beat in order:
            if attempts.get((operation, beat.id), 0) < MAX_ATTEMPTS_PER_BEAT:
                return beat
        return None

    def tighten_until_upper(*, reserve: int = 0) -> None:
        while current() > bounds.upper_chars and passes < target.max_passes - reserve:
            beat = pick(_tighten_order(beat_plan, texts, target), "tighten")
            if beat is None:
                return
            text = texts[beat.id]
            minimum = tighten_min_chars(beat.id, beat_plan, texts, target, bounds)
            reduce = current() - bounds.upper_chars
            run("tighten", beat, build_tighten_prompt(beat, text, reduce_chars=reduce, min_chars=minimum))

    def condense_until_upper() -> None:
        # 引き締めで届かないときだけ、登録された子エピソードを要約へ畳む（持ち帰りは残す）。
        order = sorted(
            enumerate(length.episodes), key=lambda pair: (condense_priority(pair[1]), pair[0])
        )
        for _, episode in order:
            if current() <= bounds.upper_chars or passes >= target.max_passes:
                return
            if target.scope == "beat" and episode.beat_id != target.beat_id:
                continue
            if attempts.get(("condense", episode.id)):
                continue
            beat = by_id[episode.beat_id]
            try:
                start, end = locate_span(texts[beat.id], episode)
            except EpisodeError as error:
                notes.append(f"CONDENSE_SKIPPED: {error}")
                continue
            span_text = texts[beat.id][start:end]
            reduce = current() - bounds.upper_chars
            keep_min = max(1, bounds.effective_lower - (current() - beat_chars(span_text)))
            run("condense", beat, build_condense_prompt(
                episode, span_text, reduce_chars=reduce, keep_min_chars=keep_min), episode)

    # D17: 欠落 Beat を先に再生成してから分量を合わせる。max_passes には数えない。
    missing = list(dict.fromkeys(
        item.beat_id for item in classification.findings
        if item.failure == Failure.BEAT_MISSING and item.beat_id
    ))
    unrepaired: list[str] = []
    for beat_id in missing:
        index = next(position for position, beat in enumerate(beat_plan.beats) if beat.id == beat_id)
        prompt = build_beat_prompt(
            by_id[beat_id], previous_context=_previous_text(index, beat_plan, texts))
        if checkpoint:
            checkpoint(dict(texts))
        candidate = dispatch("regenerate", beat_id, prompt)
        if candidate.strip():
            texts[beat_id] = strip_generation_markers(candidate)
        else:
            unrepaired.append(beat_id)
    if missing:
        # 採用した稿でもまだ欠落に当たることがある。分類をやり直し、残れば分量は合わせない。
        refilled = analyze_marked_text(
            marked_text_for_measurement(beat_plan, texts), beat_plan, run=metrics.metrics.run + 1)
        still = {
            item.beat_id for item in classify_metrics(
                refilled.metrics, beat_plan, calibration, spans=refilled.spans).findings
            if item.failure == Failure.BEAT_MISSING and item.beat_id
        }
        unrepaired.extend(beat_id for beat_id in missing
                          if beat_id in still and beat_id not in unrepaired)
        notes.append("LENGTH_MISSING_FILLED: " + ", ".join(b for b in missing if b not in unrepaired))
    if unrepaired:
        escalated.add(LENGTH_TOKEN)
        notes.append("LENGTH_REQUIRED_UNREPAIRED: missing beats were not filled: "
                     + ", ".join(unrepaired))

    start_state = "blocked" if unrepaired else band_state(current(), bounds)
    if missing and start_state == "short":
        # D21: 欠落を埋めたあとも大きく足りない稿は、Deepen へ進まず設計追加へ回す。
        filled = current()
        ratio = shortage_ratio(target.target_chars, filled)
        if ratio >= DESIGN_SHORTAGE_LIMIT:
            escalated.add(LENGTH_TOKEN)
            notes.append(
                f"DESIGN_DENSITY: short by {target.target_chars - filled} chars ({ratio:.0%}) of "
                f"{target.target_chars} after filling missing beats; Deepen is for gaps under "
                f"{DESIGN_SHORTAGE_LIMIT:.0%}. Propose adding design items or child episodes"
            )
            start_state = "design"
    if start_state == "short" and not _deepen_order(beat_plan, texts, target):
        notes.append("LENGTH_NO_ELIGIBLE: no expandable beat in scope (expandable=false)")
    if start_state == "short":
        while current() < bounds.effective_lower and passes < target.max_passes:
            beat = pick(_deepen_order(beat_plan, texts, target), "deepen")
            if beat is None:
                break
            now = current()
            from .repetition import frequent_phrases

            prompt = build_length_deepen_prompt(
                beat,
                texts[beat.id],
                need_chars=bounds.effective_lower - now,
                room_chars=bounds.upper_chars - now,
                bounds=bounds,
                known_facts=length.known_facts,
                avoid=tuple(frequent_phrases(texts.values(), allowed=allowed_repeats)),
            )
            run("deepen", beat, prompt)
        if current() > bounds.upper_chars:
            # 増量で上限を超えたときに使えるのは引き締めだけ（減量へは転じない）。
            tighten_until_upper()
    elif start_state == "over":
        reserve = 0
        if target.max_passes > 1:
            for episode in length.episodes:
                if target.scope == "beat" and episode.beat_id != target.beat_id:
                    continue
                try:
                    locate_span(texts[episode.beat_id], episode)
                except EpisodeError:
                    continue
                reserve = 1
                break
        # 引き締めを試したあと、登録済みの収束対象に少なくとも1回を残す。
        tighten_until_upper(reserve=reserve)
        condense_until_upper()

    final = current()
    state = band_state(final, bounds)
    scene_total = assembled_chars(beat_plan, texts)
    if unrepaired:
        pass  # 欠落を埋められないまま分量を合わせない（上で記録済み）。
    elif state == "in_band" and scene_total < bounds.scene_floor:
        # Beat 指定では Beat の帯に入っても場面の床は満たされないことがある。
        escalated.add(LENGTH_TOKEN)
        notes.append(
            f"LENGTH_SCENE_FLOOR: beat in band at {final} chars but the scene has {scene_total} "
            f"chars, below the floor {bounds.scene_floor}"
        )
    elif state == "in_band":
        notes.append(
            f"LENGTH_IN_BAND: {final} chars ({bounds.effective_lower}-{bounds.upper_chars}); passes {passes}"
        )
    else:
        escalated.add(LENGTH_TOKEN)
        gap = bounds.effective_lower - final if state == "short" else final - bounds.upper_chars
        where = f"beat {target.beat_id}" if target.scope == "beat" else "scene"
        label = "short" if state == "short" else "over"
        if passes >= target.max_passes:
            notes.append(f"LENGTH_MAX_PASSES: {label} by {gap} chars in {where}; passes {passes}")
        if state == "short":
            candidates = [beat.id for beat in _deepen_order(beat_plan, texts, target)] or [
                beat.id for beat in beat_plan.beats
            ]
            notes.append(
                f"LENGTH_ESCALATE_ADD: short by {gap} chars in {where}; "
                f"propose the addition step (OP-E, user approval) at beats {', '.join(candidates[:3])}"
            )
        else:
            notes.append(
                f"LENGTH_ESCALATE_REVISE: over by {gap} chars in {where}; "
                "register child episodes to condense, or propose the revision step "
                "(OP-S, user approval)"
            )
    if checkpoint:
        checkpoint(dict(texts))
    verification = analyze_marked_text(
        marked_text_for_measurement(beat_plan, texts), beat_plan, run=metrics.metrics.run + 1
    )
    return SceneRepairResult(
        classification=classification,
        beat_texts=texts,
        final_text=assemble_beat_texts(beat_plan, texts),
        expansions={},
        regenerated_beats=(),
        seam_correction_applied=False,
        escalated_beats=tuple(sorted(escalated)),
        notes=tuple(notes),
        verification_metrics=verification.metrics,
        verification_classification=classify_metrics(
            verification.metrics, beat_plan, calibration, spans=verification.spans
        ),
    )
