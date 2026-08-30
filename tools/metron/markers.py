"""Beat / fact マーカーの埋め込みとパース。"""

from __future__ import annotations

from dataclasses import dataclass
import re
from collections.abc import Iterable, Sequence
import unicodedata

from .models import GeneratorInfo, SpanRecord, SpansDocument


_MARKER_ID = r"[A-Za-z][A-Za-z0-9_-]*"
_TOKEN_RE = re.compile(
    rf"(?P<open><!--beat:(?P<open_id>{_MARKER_ID})-->)|"
    rf"(?P<close><!--/beat:(?P<close_id>{_MARKER_ID})-->)|"
    rf"(?P<fact><!--fact:(?P<fact_id>{_MARKER_ID})-->)"
)
_ID_RE = re.compile(rf"^{_MARKER_ID}$")


@dataclass(frozen=True)
class MarkerParseResult:
    """マーカーを除去した本文と、検査に必要な構造情報。"""

    clean_text: str
    spans: tuple[SpanRecord, ...]
    missing_markers: tuple[str, ...]
    errors: tuple[str, ...]
    fact_annotations: dict[str, tuple[str, ...]]

    @property
    def coverage(self) -> bool:
        return not self.errors and not self.missing_markers

    def to_document(
        self,
        *,
        run: int,
        generator: GeneratorInfo | None = None,
    ) -> SpansDocument:
        return SpansDocument(
            run=run,
            generator=generator,
            spans=list(self.spans),
            missing_markers=list(self.missing_markers),
            parse_errors=list(self.errors),
            fact_annotations={
                beat_id: list(facts)
                for beat_id, facts in self.fact_annotations.items()
            },
        )


def _clean_offset(raw_position: int, removals: Sequence[tuple[int, int]]) -> int:
    removed = sum(end - start for start, end in removals if end <= raw_position)
    return raw_position - removed


def parse_markers(
    text: str,
    *,
    expected_beats: Iterable[str] = (),
) -> MarkerParseResult:
    """Beat マーカーを検証し、NFC済み・マーカー除去後のスパンを返す。

    ``start`` / ``end`` は UTF-8 バイトではなく、マーカー除去後の Python
    文字列におけるコードポイント位置である。
    """

    normalized = unicodedata.normalize("NFC", text)
    expected = tuple(expected_beats)
    errors: list[str] = []
    removals: list[tuple[int, int]] = []
    stack: list[tuple[str, int]] = []
    completed: list[tuple[str, int, int]] = []
    seen_completed: set[str] = set()
    facts: dict[str, list[str]] = {}

    for match in _TOKEN_RE.finditer(normalized):
        removals.append(match.span())
        if match.group("open") is not None:
            beat_id = match.group("open_id")
            if stack:
                errors.append(
                    f"nested Beat marker: {beat_id!r} inside {stack[-1][0]!r}"
                )
            if beat_id in seen_completed or any(
                active_id == beat_id for active_id, _ in stack
            ):
                errors.append(f"duplicate Beat marker: {beat_id!r}")
            stack.append((beat_id, match.end()))
            continue

        if match.group("close") is not None:
            beat_id = match.group("close_id")
            if not stack:
                errors.append(f"closing marker without opening marker: {beat_id!r}")
                continue
            active_id, content_start = stack.pop()
            if active_id != beat_id:
                errors.append(
                    f"mismatched closing marker: expected {active_id!r}, got {beat_id!r}"
                )
                continue
            if beat_id in seen_completed:
                errors.append(f"duplicate completed Beat: {beat_id!r}")
                continue
            seen_completed.add(beat_id)
            completed.append((beat_id, content_start, match.start()))
            continue

        fact_id = match.group("fact_id")
        if not stack:
            errors.append(f"fact marker outside Beat: {fact_id!r}")
        else:
            facts.setdefault(stack[-1][0], []).append(fact_id)

    for beat_id, _ in stack:
        errors.append(f"unclosed Beat marker: {beat_id!r}")

    expected_set = set(expected)
    completed_set = set(seen_completed)
    missing = tuple(beat_id for beat_id in expected if beat_id not in completed_set)
    unexpected = sorted(completed_set - expected_set) if expected else []
    if unexpected:
        errors.extend(f"unexpected Beat marker: {beat_id!r}" for beat_id in unexpected)

    removals.sort()
    clean_parts: list[str] = []
    cursor = 0
    for start, end in removals:
        clean_parts.append(normalized[cursor:start])
        cursor = end
    clean_parts.append(normalized[cursor:])
    clean_text = "".join(clean_parts)

    spans = tuple(
        SpanRecord(
            beat=beat_id,
            start=_clean_offset(content_start, removals),
            end=_clean_offset(content_end, removals),
        )
        for beat_id, content_start, content_end in completed
    )
    return MarkerParseResult(
        clean_text=clean_text,
        spans=spans,
        missing_markers=missing,
        errors=tuple(errors),
        fact_annotations={beat_id: tuple(ids) for beat_id, ids in facts.items()},
    )


def embed_beat_markers(
    segments: Sequence[tuple[str, str]],
    *,
    separator: str = "\n",
) -> str:
    """Beat本文の列を、Writer向けの開閉マーカー付きMarkdownにする。"""

    seen: set[str] = set()
    rendered: list[str] = []
    for beat_id, body in segments:
        if _ID_RE.fullmatch(beat_id) is None:
            raise ValueError(f"invalid Beat ID: {beat_id!r}")
        if beat_id in seen:
            raise ValueError(f"duplicate Beat ID: {beat_id!r}")
        seen.add(beat_id)
        rendered.append(f"<!--beat:{beat_id}-->\n{body}\n<!--/beat:{beat_id}-->")
    return separator.join(rendered)


def fact_marker(fact_id: str) -> str:
    if _ID_RE.fullmatch(fact_id) is None:
        raise ValueError(f"invalid fact ID: {fact_id!r}")
    return f"<!--fact:{fact_id}-->"
