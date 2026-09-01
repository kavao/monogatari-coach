"""METRON V1 の局所 Expand、継ぎ目対策、修復ループ制御。"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
import re
import unicodedata

from novel_char_count import count_chars

from .markers import embed_beat_markers, parse_markers
from .analyze import analyze_marked_text
from .calibrate import ModelCalibration
from .classify import ClassificationResult, Finding, classify_metrics
from .models import Beat, BeatPlan, Failure, MetricsDocument, SpansDocument
from .prompt import build_beat_prompt, current_beat_chars, to_prompt_budget
from .storage import atomic_write_text


_SENTENCE_RE = re.compile(r".+?(?:[。！？!?]|$)", re.DOTALL)
_MULTI_BLANK_RE = re.compile(r"\n{3,}")
_NGRAM_STRIP_RE = re.compile(r"[\s　。、．，！？!?…・「」『』（）()\[\]【】]")

# Deepen の同義反復棄却。モデル別キャリブレーションには載せない政策床。
DEEPEN_PARAPHRASE_MIN_CHARS = 20
DEEPEN_PARAPHRASE_NGRAM = 2
DEEPEN_PARAPHRASE_JACCARD = 0.62


def split_sentences(text: str) -> list[str]:
    """日本語の終端記号を優先した、修復検査用の軽量な文分割。"""

    normalized = unicodedata.normalize("NFC", text)
    return [part.strip() for part in _SENTENCE_RE.findall(normalized) if part.strip()]


def sentence_tail(text: str, count: int = 5) -> str:
    if count < 1:
        raise ValueError("sentence count must be positive")
    return "\n".join(split_sentences(text)[-count:])


def build_beat_continuation_context(text: str, count: int = 5) -> str:
    tail = sentence_tail(text, count)
    return "直前 Beat の末尾文脈（この続きとして書く）:\n" + tail if tail else ""


def build_expand_prompt(beat: Beat, current_text: str) -> str:
    """既存部分の書き直しを誘発しない Deepen / Expand 指示を組み立てる。"""

    budget = to_prompt_budget(beat.budget)
    current = current_beat_chars(current_text)
    return (
        build_beat_prompt(beat)
        + "\n現在の Beat 本文:\n"
        + current_text
        + "\n\nDeepen 指示:\n"
        + f"現在 {current}字。下限 {budget.chars_floor}字。指示目標 {budget.chars_instruction}字。"
        + "現在の出来事・結末・視点を変更せず、現在の本文を残したまま、"
        + "不足している手順・制度・選択、感情の変化と身体の変化、感覚・内面・会話を、言い換えではなく固有の情報で深めて下限を超えること。"
        + "同じ内容の反復や埋草は禁止。書き直し、要約、既存文の削除は禁止する。"
    )


def _sentence_retention_ratio(original: str, candidate: str) -> float:
    source = split_sentences(original)
    if not source:
        return 1.0
    target = Counter(split_sentences(candidate))
    retained = 0
    for sentence in source:
        if target[sentence] > 0:
            retained += len(sentence)
            target[sentence] -= 1
    return retained / sum(len(sentence) for sentence in source)


def original_retention_ratio(original: str, candidate: str) -> float:
    """元文の文が候補へ何割残っているかを返す（NFCコードポイント基準）。"""

    return _sentence_retention_ratio(
        unicodedata.normalize("NFC", original),
        unicodedata.normalize("NFC", candidate),
    )


def _compact_for_ngram(text: str) -> str:
    return _NGRAM_STRIP_RE.sub("", unicodedata.normalize("NFC", text))


def _char_ngrams(text: str, n: int) -> set[str]:
    compact = _compact_for_ngram(text)
    if len(compact) < n:
        return set()
    return {compact[index : index + n] for index in range(len(compact) - n + 1)}


def sentence_char_ngram_jaccard(
    left: str,
    right: str,
    *,
    n: int = DEEPEN_PARAPHRASE_NGRAM,
) -> float:
    """句読点を除いた文字 n-gram の Jaccard 類似度。空なら 0。"""

    if n < 1:
        raise ValueError("n-gram size must be positive")
    left_grams = _char_ngrams(left, n)
    right_grams = _char_ngrams(right, n)
    if not left_grams or not right_grams:
        return 0.0
    return len(left_grams & right_grams) / len(left_grams | right_grams)


def unmatched_sentences(source: list[str], target: list[str]) -> list[str]:
    """target のうち、source の完全一致を使い切ったあとに残る文。"""

    remaining = Counter(source)
    extra: list[str] = []
    for sentence in target:
        if remaining[sentence] > 0:
            remaining[sentence] -= 1
        else:
            extra.append(sentence)
    return extra


@dataclass(frozen=True)
class ParaphraseHit:
    new_sentence: str
    reference_sentence: str
    jaccard: float


def find_deepen_paraphrase(
    original: str,
    candidate: str,
    *,
    min_chars: int = DEEPEN_PARAPHRASE_MIN_CHARS,
    threshold: float = DEEPEN_PARAPHRASE_JACCARD,
) -> ParaphraseHit | None:
    """新規文が既存文または他の新規文と高類似なら、最初の衝突を返す。"""

    if min_chars < 1:
        raise ValueError("min_chars must be positive")
    if not 0 <= threshold <= 1:
        raise ValueError("threshold must be between 0 and 1")
    original_n = unicodedata.normalize("NFC", original)
    candidate_n = unicodedata.normalize("NFC", candidate)
    original_sentences = split_sentences(original_n)
    new_sentences = unmatched_sentences(
        original_sentences, split_sentences(candidate_n)
    )
    seen_new: list[str] = []
    for sentence in new_sentences:
        if count_chars(sentence, strip_fm=False) < min_chars:
            seen_new.append(sentence)
            continue
        # 短い反応は新規文として見ない。参照側は n-gram が取れる文なら対象にする。
        references = [
            item
            for item in [*original_sentences, *seen_new]
            if len(_compact_for_ngram(item)) >= DEEPEN_PARAPHRASE_NGRAM
        ]
        for reference in references:
            score = sentence_char_ngram_jaccard(sentence, reference)
            if score >= threshold:
                return ParaphraseHit(sentence, reference, score)
        seen_new.append(sentence)
    return None


@dataclass(frozen=True)
class ExpansionCheck:
    accepted: bool
    retention_ratio: float
    reason: str


def validate_expansion(
    original: str,
    candidate: str,
    *,
    retention_threshold: float,
) -> ExpansionCheck:
    if not 0 <= retention_threshold <= 1:
        raise ValueError("retention_threshold must be between 0 and 1")
    if not candidate.strip():
        return ExpansionCheck(False, 0.0, "candidate is empty")
    original_n = unicodedata.normalize("NFC", original)
    candidate_n = unicodedata.normalize("NFC", candidate)
    ratio = original_retention_ratio(original_n, candidate_n)
    if original_n.strip() == candidate_n.strip():
        return ExpansionCheck(False, ratio, "candidate is identical to the original")
    if count_chars(candidate_n, strip_fm=False) <= count_chars(original_n, strip_fm=False):
        return ExpansionCheck(False, ratio, "candidate does not increase length")
    if ratio < retention_threshold:
        return ExpansionCheck(
            False,
            ratio,
            "original sentence retention is below the calibrated threshold",
        )
    hit = find_deepen_paraphrase(original_n, candidate_n)
    if hit is not None:
        return ExpansionCheck(
            False,
            ratio,
            "new sentence paraphrases existing or added text",
        )
    return ExpansionCheck(True, ratio, "accepted")


@dataclass(frozen=True)
class RepairResult:
    original_text: str
    final_text: str
    accepted: bool
    attempts: int
    escalated: bool
    checks: tuple[ExpansionCheck, ...]


@dataclass(frozen=True)
class SceneRepairResult:
    classification: ClassificationResult
    beat_texts: dict[str, str]
    final_text: str
    expansions: dict[str, RepairResult]
    regenerated_beats: tuple[str, ...]
    seam_correction_applied: bool
    escalated_beats: tuple[str, ...]
    verification_metrics: MetricsDocument
    verification_classification: ClassificationResult


@dataclass(frozen=True)
class MarkedSeamCorrection:
    clean_text: str
    marked_text: str
    accepted: bool
    reason: str
    beat_texts: dict[str, str] | None = None


@dataclass
class RepairState:
    """Beat ごとの Expand 上限を状態として明示する。"""

    max_attempts: int = 2
    attempts: int = 0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be positive")

    @property
    def can_expand(self) -> bool:
        return self.attempts < self.max_attempts

    def record_attempt(self) -> None:
        if not self.can_expand:
            raise RuntimeError("Expand attempt limit exceeded")
        self.attempts += 1


def run_expand_loop(
    beat: Beat,
    current_text: str,
    expander: Callable[[str], str],
    *,
    retention_threshold: float,
    max_attempts: int = 2,
) -> RepairResult:
    """provider を直接知らない Expand ループ。

    ``expander`` は prompt を受け取り候補本文を返す注入関数であり、実際の
    LLM 呼び出しやネットワークはこのモジュールから行わない。
    """

    state = RepairState(max_attempts=max_attempts)
    checks: list[ExpansionCheck] = []
    original = unicodedata.normalize("NFC", current_text)
    while state.can_expand:
        state.record_attempt()
        candidate = strip_generation_markers(
            unicodedata.normalize("NFC", expander(build_expand_prompt(beat, original)))
        )
        check = validate_expansion(
            original,
            candidate,
            retention_threshold=retention_threshold,
        )
        checks.append(check)
        if check.accepted:
            return RepairResult(
                original_text=original,
                final_text=candidate,
                accepted=True,
                attempts=state.attempts,
                escalated=False,
                checks=tuple(checks),
            )
    return RepairResult(
        original_text=original,
        final_text=original,
        accepted=False,
        attempts=state.attempts,
        escalated=True,
        checks=tuple(checks),
    )


def _text_by_beat(
    clean_text: str,
    beat_plan: BeatPlan,
    spans: SpansDocument,
) -> dict[str, str]:
    span_by_id: dict[str, list[tuple[int, int]]] = {}
    for span in spans.spans:
        span_by_id.setdefault(span.beat, []).append((span.start, span.end))
    texts: dict[str, str] = {}
    for beat in beat_plan.beats:
        candidates = span_by_id.get(beat.id, [])
        if len(candidates) == 1:
            start, end = candidates[0]
            texts[beat.id] = clean_text[start:end]
        else:
            texts[beat.id] = ""
    return texts


def _previous_text(beat_index: int, beat_plan: BeatPlan, texts: dict[str, str]) -> str:
    if beat_index == 0:
        return ""
    previous = beat_plan.beats[beat_index - 1]
    return build_beat_continuation_context(texts.get(previous.id, ""))


def _finding_beats(findings: list[Finding], failure: Failure) -> list[str]:
    return [
        finding.beat_id
        for finding in findings
        if finding.failure == failure
        and finding.auto_repair
        and finding.beat_id is not None
    ]


def repair_scene(
    metrics: MetricsDocument,
    beat_plan: BeatPlan,
    calibration: ModelCalibration,
    *,
    clean_text: str,
    spans: SpansDocument,
    expander: Callable[[str], str] | None = None,
    regenerator: Callable[[str], str] | None = None,
    seam_corrector: Callable[[str], str] | None = None,
) -> SceneRepairResult:
    """判定結果に応じて局所修復を適用する。

    コールバックは provider の実装を注入する境界であり、METRON 自体は外部
    サービスへ接続しない。修復後の本文は常に BeatPlan 順で再結合される。
    """

    classification = classify_metrics(metrics, beat_plan, calibration, spans=spans)
    beat_texts = _text_by_beat(clean_text, beat_plan, spans)
    by_id = {beat.id: beat for beat in beat_plan.beats}
    index_by_id = {beat.id: index for index, beat in enumerate(beat_plan.beats)}
    expansions: dict[str, RepairResult] = {}
    regenerated: list[str] = []
    escalated: set[str] = set()

    missing_ids = _finding_beats(classification.findings, Failure.BEAT_MISSING)
    missing_set = set(missing_ids)
    ending = any(
        finding.failure == Failure.ENDING_RUSH and finding.auto_repair
        for finding in classification.findings
    )
    ending_beat_id = beat_plan.beats[-1].id if ending else None
    thin_ids = [
        beat_id
        for beat_id in _finding_beats(classification.findings, Failure.BEAT_THIN)
        if beat_id not in missing_set and beat_id != ending_beat_id
    ]
    too_short_beat_ids = [
        beat_id
        for beat_id in _finding_beats(classification.findings, Failure.TOO_SHORT)
        if beat_id not in missing_set and beat_id != ending_beat_id
    ]
    scene_too_short = any(
        finding.failure == Failure.TOO_SHORT
        and finding.auto_repair
        and finding.beat_id is None
        for finding in classification.findings
    )
    required_deepen = list(dict.fromkeys([*thin_ids, *too_short_beat_ids]))
    deepen_ids = list(required_deepen)
    if scene_too_short:
        already = set(deepen_ids) | missing_set
        if ending_beat_id is not None:
            already.add(ending_beat_id)
        extras = [
            beat
            for beat in beat_plan.beats
            if beat.id not in already
        ]
        extras.sort(key=lambda beat: current_beat_chars(beat_texts.get(beat.id, "")))
        deepen_ids.extend(beat.id for beat in extras)
    needs_generation = bool(missing_ids or deepen_ids or ending)
    if needs_generation and expander is None and regenerator is None:
        raise ValueError("a generation callback is required for V1 repair findings")
    if needs_generation and seam_corrector is None:
        raise ValueError("a seam correction callback is required for V1 repair")
    if deepen_ids and expander is None:
        raise ValueError("TooShort / BeatThin Deepen requires an expander callback")

    for beat_id in missing_ids:
        beat = by_id[beat_id]
        generator = regenerator or expander
        assert generator is not None
        prompt = build_beat_prompt(
            beat,
            previous_context=_previous_text(index_by_id[beat_id], beat_plan, beat_texts),
        )
        beat_texts[beat_id] = strip_generation_markers(generator(prompt))
        regenerated.append(beat_id)

    required_deepen_set = set(required_deepen)
    scene_floor = beat_plan.generation.chars_floor
    for beat_id in deepen_ids:
        if (
            scene_too_short
            and beat_id not in required_deepen_set
            and _scene_chars(beat_plan, beat_texts) >= scene_floor
        ):
            continue
        beat = by_id[beat_id]
        if expander is None:
            escalated.add(beat_id)
            continue
        result = run_expand_loop(
            beat,
            beat_texts[beat_id],
            expander,
            retention_threshold=_retention_threshold(calibration),
        )
        expansions[beat_id] = result
        if result.accepted:
            beat_texts[beat_id] = strip_generation_markers(result.final_text)
        else:
            escalated.add(beat_id)

    if ending:
        final_beat = beat_plan.beats[-1]
        generator = regenerator or expander
        assert generator is not None
        prompt = build_beat_prompt(
            final_beat,
            previous_context=_previous_text(len(beat_plan.beats) - 1, beat_plan, beat_texts),
        )
        beat_texts[final_beat.id] = strip_generation_markers(generator(prompt))
        regenerated.append(final_beat.id)

    seam_applied = False
    if seam_corrector is not None:
        seam = run_marked_seam_correction(beat_plan, beat_texts, seam_corrector)
        seam_applied = seam.accepted
        if seam.accepted and seam.beat_texts is not None:
            beat_texts = seam.beat_texts
    joined = assemble_beat_texts(beat_plan, beat_texts)
    verification_marked = marked_text_for_measurement(beat_plan, beat_texts)
    verification = analyze_marked_text(
        verification_marked,
        beat_plan,
        run=metrics.metrics.run + 1,
    )
    return SceneRepairResult(
        classification=classification,
        beat_texts=beat_texts,
        final_text=joined,
        expansions=expansions,
        regenerated_beats=tuple(dict.fromkeys(regenerated)),
        seam_correction_applied=seam_applied,
        escalated_beats=tuple(sorted(escalated)),
        verification_metrics=verification.metrics,
        verification_classification=classify_metrics(
            verification.metrics,
            beat_plan,
            calibration,
            spans=verification.spans,
        ),
    )


def _scene_chars(beat_plan: BeatPlan, texts: dict[str, str]) -> int:
    return count_chars(assemble_beat_texts(beat_plan, texts), strip_fm=False)


def marked_text_for_measurement(beat_plan: BeatPlan, texts: dict[str, str]) -> str:
    """FINAL と同じ結合本文になるよう、余分な改行を付けずにマーカーを巻く。"""

    newline = "\n"
    chunks = [
        f"<!--beat:{beat.id}-->{texts[beat.id].strip(newline)}<!--/beat:{beat.id}-->"
        for beat in beat_plan.beats
    ]
    return "\n\n".join(chunks) + "\n"


def _retention_threshold(calibration: ModelCalibration) -> float:
    """V1 の元文残存閾値はキャリブレーション設定に置く。"""

    value = calibration.expand_retention_threshold
    if value is None:
        raise ValueError("calibration requires expand_retention_threshold for Expand")
    return value


def normalize_novel_body(text: str) -> str:
    """読者向け本文の連続空行を、場面転換用の空行1つまでに落とす。"""

    normalized = unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n")
    collapsed = _MULTI_BLANK_RE.sub("\n\n", normalized)
    return collapsed.strip("\n") + "\n"


def assemble_beat_texts(
    beat_plan: BeatPlan,
    texts: dict[str, str],
    *,
    separator: str = "\n\n",
) -> str:
    """BeatPlan 順で結合する。マーカーは追加せず、FINAL 向け本文を返す。"""

    missing = [beat.id for beat in beat_plan.beats if beat.id not in texts]
    if missing:
        raise ValueError("missing Beat texts: " + ", ".join(missing))
    joined = separator.join(texts[beat.id].strip("\n") for beat in beat_plan.beats)
    return normalize_novel_body(joined)


def build_seam_correction_prompt(text: str) -> str:
    return (
        "Beat 結合後の連結校正を1回だけ行う。\n"
        "短縮禁止・事象変更禁止・視点変更禁止。冒頭の状況再説明を追加しない。\n"
        "文と文の接続、重複する接続語、表記だけを最小限に整える。\n"
        "入力に Beat マーカーがある場合は、ID・開閉・境界を変更せず、そのまま残す。\n\n"
        "結合稿:\n"
        + text
    )


def repeated_beat_openings(beat_texts: dict[str, str]) -> tuple[str, ...]:
    """同一の冒頭文が Beat 境界をまたいで反復された ID を返す。"""

    counts: Counter[str] = Counter()
    repeated: list[str] = []
    for beat_id, text in beat_texts.items():
        sentences = split_sentences(text)
        if not sentences:
            continue
        opening = sentences[0]
        if counts[opening] > 0:
            repeated.append(beat_id)
        counts[opening] += 1
    return tuple(repeated)


def run_marked_seam_correction(
    beat_plan: BeatPlan,
    beat_texts: dict[str, str],
    corrector: Callable[[str], str],
) -> MarkedSeamCorrection:
    """Beat マーカーを保持したまま校正し、校正後の再計測を可能にする。"""

    source_marked = embed_beat_markers(
        [(beat.id, beat_texts[beat.id]) for beat in beat_plan.beats]
    )
    source_clean = assemble_beat_texts(beat_plan, beat_texts)
    candidate_marked = unicodedata.normalize(
        "NFC", corrector(build_seam_correction_prompt(source_marked))
    )
    parsed = parse_markers(
        candidate_marked,
        expected_beats=[beat.id for beat in beat_plan.beats],
    )
    if not parsed.coverage:
        return MarkedSeamCorrection(
            clean_text=source_clean,
            marked_text=source_marked,
            accepted=False,
            reason="seam correction changed or removed Beat markers",
            beat_texts=dict(beat_texts),
        )
    observed_order = [span.beat for span in parsed.spans]
    expected_order = [beat.id for beat in beat_plan.beats]
    if observed_order != expected_order:
        return MarkedSeamCorrection(
            clean_text=source_clean,
            marked_text=source_marked,
            accepted=False,
            reason="seam correction reordered Beats",
            beat_texts=dict(beat_texts),
        )
    candidate_clean = parsed.clean_text
    candidate_texts: dict[str, str] = {}
    for beat in beat_plan.beats:
        beat_spans = [span for span in parsed.spans if span.beat == beat.id]
        if len(beat_spans) != 1:
            return MarkedSeamCorrection(
                clean_text=source_clean,
                marked_text=source_marked,
                accepted=False,
                reason="seam correction produced an invalid Beat span",
                beat_texts=dict(beat_texts),
            )
        span = beat_spans[0]
        candidate_texts[beat.id] = candidate_clean[span.start : span.end]
    source_counts: Counter[str] = Counter()
    candidate_counts: Counter[str] = Counter()
    for texts, counts in ((beat_texts, source_counts), (candidate_texts, candidate_counts)):
        for text in texts.values():
            sentences = split_sentences(text)
            if sentences:
                counts[sentences[0]] += 1
    if any(
        candidate_counts[opening] > source_counts[opening]
        for opening in candidate_counts
    ):
        return MarkedSeamCorrection(
            clean_text=source_clean,
            marked_text=source_marked,
            accepted=False,
            reason="seam correction introduced a repeated Beat opening",
            beat_texts=dict(beat_texts),
        )
    if count_chars(candidate_clean, strip_fm=False) < count_chars(
        source_clean, strip_fm=False
    ):
        return MarkedSeamCorrection(
            clean_text=source_clean,
            marked_text=source_marked,
            accepted=False,
            reason="seam correction shortened the joined text",
            beat_texts=dict(beat_texts),
        )
    if original_retention_ratio(source_clean, candidate_clean) < 1.0:
        return MarkedSeamCorrection(
            clean_text=source_clean,
            marked_text=source_marked,
            accepted=False,
            reason="seam correction removed original sentences",
            beat_texts=dict(beat_texts),
        )
    return MarkedSeamCorrection(
        clean_text=assemble_beat_texts(beat_plan, candidate_texts),
        marked_text=marked_text_for_measurement(beat_plan, candidate_texts),
        accepted=True,
        reason="accepted",
        beat_texts=candidate_texts,
    )


def run_seam_correction(
    text: str,
    corrector: Callable[[str], str],
) -> tuple[str, bool, str]:
    """連結校正を最大1回実行し、短縮または元文消失なら棄却する。"""

    original = unicodedata.normalize("NFC", text)
    candidate = strip_generation_markers(
        unicodedata.normalize("NFC", corrector(build_seam_correction_prompt(original)))
    )
    if count_chars(candidate, strip_fm=False) < count_chars(original, strip_fm=False):
        return original, False, "seam correction shortened the joined text"
    if original_retention_ratio(original, candidate) < 1.0:
        return original, False, "seam correction removed original sentences"
    return candidate, True, "accepted"


def strip_generation_markers(text: str) -> str:
    """FINAL 反映前に Beat / fact コメントだけを除去する。"""

    return parse_markers(text).clean_text


def write_final(path: str | Path, text: str) -> None:
    """採用稿をマーカーなしで保存する。本文正本への反映は別ワークフロー。"""

    target = Path(path)
    if target.exists():
        raise FileExistsError(f"FINAL already exists and will not be overwritten: {target}")
    atomic_write_text(target, normalize_novel_body(strip_generation_markers(text)))
