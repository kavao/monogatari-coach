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
from .prompt import build_beat_prompt
from .storage import atomic_write_text


_SENTENCE_RE = re.compile(r".+?(?:[。！？!?]|$)", re.DOTALL)


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
    """既存部分の書き直しを誘発しない Expand 指示を組み立てる。"""

    return (
        build_beat_prompt(beat)
        + "\n現在の Beat 本文:\n"
        + current_text
        + "\n\nExpand 指示:\n"
        + "現在の出来事・結末・視点を変更せず、現在の本文を残したまま、"
        + "会話・行動・知覚描写を追加して不足している構造要素を補うこと。"
        + "書き直し、要約、既存文の削除は禁止する。"
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
    ratio = original_retention_ratio(original, candidate)
    if ratio < retention_threshold:
        return ExpansionCheck(
            False,
            ratio,
            "original sentence retention is below the calibrated threshold",
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


@dataclass(frozen=True)
class MarkedSeamCorrection:
    clean_text: str
    marked_text: str
    accepted: bool
    reason: str


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
    if (missing_ids or thin_ids or ending) and expander is None and regenerator is None:
        raise ValueError("a generation callback is required for V1 repair findings")
    if (missing_ids or thin_ids or ending) and seam_corrector is None:
        raise ValueError("a seam correction callback is required for V1 repair")

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

    for beat_id in thin_ids:
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

    source_marked = embed_beat_markers(
        [(beat.id, beat_texts[beat.id]) for beat in beat_plan.beats]
    )
    joined = assemble_beat_texts(beat_plan, beat_texts)
    seam_applied = False
    verification_marked = source_marked
    if seam_corrector is not None:
        seam = run_marked_seam_correction(beat_plan, beat_texts, seam_corrector)
        joined = seam.clean_text
        seam_applied = seam.accepted
        if seam.accepted:
            verification_marked = seam.marked_text
    verification = analyze_marked_text(
        verification_marked,
        beat_plan,
        run=metrics.metrics.run + 1,
    ).metrics
    return SceneRepairResult(
        classification=classification,
        beat_texts=beat_texts,
        final_text=joined,
        expansions=expansions,
        regenerated_beats=tuple(dict.fromkeys(regenerated)),
        seam_correction_applied=seam_applied,
        escalated_beats=tuple(sorted(escalated)),
        verification_metrics=verification,
    )


def _retention_threshold(calibration: ModelCalibration) -> float:
    """V1 の元文残存閾値はキャリブレーション設定に置く。"""

    value = calibration.expand_retention_threshold
    if value is None:
        raise ValueError("calibration requires expand_retention_threshold for Expand")
    return value


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
    return separator.join(texts[beat.id] for beat in beat_plan.beats)


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
        )
    if count_chars(candidate_clean, strip_fm=False) < count_chars(
        source_clean, strip_fm=False
    ):
        return MarkedSeamCorrection(
            clean_text=source_clean,
            marked_text=source_marked,
            accepted=False,
            reason="seam correction shortened the joined text",
        )
    if original_retention_ratio(source_clean, candidate_clean) < 1.0:
        return MarkedSeamCorrection(
            clean_text=source_clean,
            marked_text=source_marked,
            accepted=False,
            reason="seam correction removed original sentences",
        )
    return MarkedSeamCorrection(
        clean_text=candidate_clean,
        marked_text=candidate_marked,
        accepted=True,
        reason="accepted",
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
    atomic_write_text(target, strip_generation_markers(text))
