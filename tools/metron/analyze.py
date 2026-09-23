"""Beat境界に対応したV0の決定的metrics計測。"""

from __future__ import annotations

from dataclasses import dataclass
import re
from collections.abc import Iterable

from novel_char_count import count_chars

from .markers import MarkerParseResult, parse_markers
from .models import (
    Beat,
    BeatMetrics,
    BeatPlan,
    GeneratorInfo,
    MetricsDocument,
    MetricsPayload,
    SceneMetrics,
    SpansDocument,
)


MEASUREMENT_METHODS = {
    "paragraphs": "line_v0",
    "dialogue_turns": "line_dialogue_v0",
    "sensory": "ja_lexicon_v0",
    "interiority": "ja_lexicon_v0",
    "summary_markers": "ja_summary_v0",
    "new_facts": "annotation_v0",
}

_SENSORY_PATTERNS = (
    r"視界|目|瞳|見え|見つめ|耳|音|声|聞こ|匂い|香り|鼻腔|味|舌|甘い|苦い|触れ|肌|指先|冷たい|熱い|痛み|震え",
)
_INTERIORITY_PATTERNS = (
    r"思う|思った|考え|感じ|不安|恐れ|怒り|苛立|期待|疑問|決意|迷い|記憶|意識|心|胸の奥",
)
_SUMMARY_MARKERS = (
    "一方その頃",
    "しばらくして",
    "数日後",
    "翌日",
    "その後",
    "やがて",
    "それから",
)
_HTML_COMMENT_RE = re.compile(r"^\s*<!--.*-->\s*$")


@dataclass(frozen=True)
class AnalysisResult:
    metrics: MetricsDocument
    spans: SpansDocument
    clean_text: str
    marker_result: MarkerParseResult


def _body_lines(text: str) -> list[str]:
    lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or _HTML_COMMENT_RE.fullmatch(stripped):
            continue
        lines.append(line)
    return lines


def _count_regex_hits(lines: Iterable[str], patterns: Iterable[str]) -> int:
    compiled = [re.compile(pattern) for pattern in patterns]
    return sum(len(pattern.findall(line)) for line in lines for pattern in compiled)


def _summary_marker_hits(text: str) -> list[str]:
    hits: list[str] = []
    for marker in _SUMMARY_MARKERS:
        hits.extend(marker for _ in re.finditer(re.escape(marker), text))
    return hits


def _dialogue_turns(lines: Iterable[str]) -> int:
    return sum(1 for line in lines if line.lstrip().startswith(("「", "『")))


def _beat_metrics(beat: Beat, body: str, fact_ids: tuple[str, ...]) -> BeatMetrics:
    lines = _body_lines(body)
    chars = count_chars(body, strip_fm=False)
    return BeatMetrics(
        id=beat.id,
        chars=chars,
        budget_ratio=chars / beat.budget.chars_hint,
        paragraphs=len(lines),
        dialogue_turns=_dialogue_turns(lines),
        sensory=_count_regex_hits(lines, _SENSORY_PATTERNS),
        interiority=_count_regex_hits(lines, _INTERIORITY_PATTERNS),
        new_facts=len(fact_ids) if fact_ids else None,
        new_facts_source="annotation" if fact_ids else "unmeasured",
        measurement_methods=dict(MEASUREMENT_METHODS),
        summary_markers=_summary_marker_hits(body),
        time_density=None,
    )


def _head_tail_ratio(beat_metrics: list[BeatMetrics], beats: list[Beat]) -> float | None:
    if len(beats) < 4:
        return None
    by_id = {item.id: item for item in beat_metrics}
    head = beats[:2]
    tail = beats[-2:]

    def group_ratio(group: list[Beat]) -> float:
        chars = sum(by_id[beat.id].chars for beat in group)
        hints = sum(beat.budget.chars_hint for beat in group)
        return chars / hints

    head_ratio = group_ratio(head)
    if head_ratio == 0:
        return None
    return group_ratio(tail) / head_ratio


def analyze_marked_text(
    text: str,
    beat_plan: BeatPlan,
    *,
    run: int,
    finish_reason: str | None = None,
    generator: GeneratorInfo | None = None,
) -> AnalysisResult:
    """マーカー付き本文を解析し、spans と metrics を同時に返す。"""

    beats = beat_plan.beats
    marker_result = parse_markers(text, expected_beats=[beat.id for beat in beats])
    spans_document = marker_result.to_document(run=run, generator=generator)
    span_by_id = {span.beat: span for span in marker_result.spans}

    beat_metrics: list[BeatMetrics] = []
    for beat in beats:
        span = span_by_id.get(beat.id)
        body = "" if span is None else marker_result.clean_text[span.start : span.end]
        facts = marker_result.fact_annotations.get(beat.id, ())
        beat_metrics.append(_beat_metrics(beat, body, facts))

    total_hints = sum(beat.budget.chars_hint for beat in beats)
    scene_chars = count_chars(marker_result.clean_text, strip_fm=False)
    metrics = MetricsDocument(
        metrics=MetricsPayload(
            run=run,
            finish_reason=finish_reason,
            beats=beat_metrics,
            scene=SceneMetrics(
                chars=scene_chars,
                overall_budget_ratio=scene_chars / total_hints if total_hints else None,
                head_tail_ratio=_head_tail_ratio(beat_metrics, beats),
                coverage=marker_result.coverage
                and len(marker_result.spans) == len(beats),
            ),
        )
    )
    return AnalysisResult(
        metrics=metrics,
        spans=spans_document,
        clean_text=marker_result.clean_text,
        marker_result=marker_result,
    )
