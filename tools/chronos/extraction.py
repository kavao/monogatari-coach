"""CHRONOS の候補取り込み・出典照合・承認記録。provider は呼び出さない。"""

from __future__ import annotations

from copy import copy
from hashlib import sha256
import json
import re
from pathlib import Path, PurePosixPath
import unicodedata
from typing import Any

from .graph import build_order_graph, incomparable_pairs, strongly_connected_component
from .models import (
    CandidateCache,
    CandidateProposal,
    CandidateProposalBatch,
    CandidateRecord,
    ChronosConfig,
    Event,
    EventFile,
    EventSource,
    ExtractReviewDocument,
    ExtractReviewRecord,
    ReviewStatus,
)
from .selection import select_effective_events
from .storage import atomic_write_model, load_yaml
from .store import (
    ChronosLoadError,
    ChronosStore,
    _validate_character_state,
    load_store,
    novel_root_for,
    write_event_file,
)


_CHAPTER_STEM = re.compile(r"^novel_text(?P<chapter>\d{2,})$")
_SCENE_MARKER = re.compile(r"<!-- scene: (?P<scene>ch\d{2,}-\d{3,}) -->")
_UPDATE_FIELDS = (
    "title", "type", "actors", "location", "time", "causes", "effects", "effects_on",
)


def normalize_source(text: str) -> str:
    return unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))


def _digest(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()


def _source_file(root: Path, relative: str) -> tuple[str, Path, str]:
    normalized = relative.replace("\\", "/")
    pure = PurePosixPath(normalized)
    if pure.is_absolute() or ".." in pure.parts or not normalized.startswith("_novel_text/"):
        raise ValueError("source_file must be a work-relative path under _novel_text/")
    if pure.suffix.lower() != ".md":
        raise ValueError("source_file must be a Markdown file")
    match = _CHAPTER_STEM.fullmatch(pure.stem)
    if match is None:
        raise ValueError("source_file must use novel_textNN.md naming")
    path = root.joinpath(*pure.parts)
    resolved_root = root.resolve()
    resolved_path = path.resolve()
    if resolved_root not in resolved_path.parents or not resolved_path.is_file():
        raise ValueError("source_file does not exist inside the novel folder")
    text = normalize_source(resolved_path.read_text(encoding="utf-8"))
    return normalized, resolved_path, text


def _positions(text: str, quote: str) -> list[int]:
    result: list[int] = []
    offset = 0
    while True:
        found = text.find(quote, offset)
        if found < 0:
            return result
        result.append(found)
        offset = found + 1


def _scene_region(text: str, scene_id: str | None) -> tuple[int, int]:
    if scene_id is None:
        return 0, len(text)
    markers = list(_SCENE_MARKER.finditer(text))
    matches = [index for index, marker in enumerate(markers) if marker.group("scene") == scene_id]
    if len(matches) != 1:
        raise ValueError(f"scene marker must occur exactly once in source: {scene_id}")
    index = matches[0]
    start = markers[index].end()
    end = markers[index + 1].start() if index + 1 < len(markers) else len(text)
    return start, end


def _scene_positions(text: str, quote: str, scene_id: str | None) -> list[int]:
    start, end = _scene_region(text, scene_id)
    return [start + offset for offset in _positions(text[start:end], quote)]


def _cache_path(store: ChronosStore, scene_id: str | None, source_file: str) -> Path:
    directory = store.root / ".cache" / "extract"
    if scene_id is not None:
        return directory / f"{scene_id}.yaml"
    return directory / f"{Path(source_file).stem}.unplaced.yaml"


def _load_reviews(store: ChronosStore) -> ExtractReviewDocument:
    path = store.root / "extract_reviews.yaml"
    if not path.is_file():
        return ExtractReviewDocument()
    return ExtractReviewDocument.model_validate(load_yaml(path))


def _write_reviews(store: ChronosStore, document: ExtractReviewDocument) -> None:
    atomic_write_model(store.root / "extract_reviews.yaml", document)


def _read_cache(path: Path) -> CandidateCache:
    if not path.is_file():
        return CandidateCache()
    return CandidateCache.model_validate(load_yaml(path))


def _write_cache(path: Path, document: CandidateCache) -> None:
    atomic_write_model(path, document)


def _record_for(records: list[ExtractReviewRecord], candidate_id: str) -> ExtractReviewRecord | None:
    return next((record for record in records if record.candidate_id == candidate_id), None)


def _next_candidate_id(store: ChronosStore, reviews: ExtractReviewDocument) -> str:
    values = [int(record.candidate_id[4:]) for record in reviews.records]
    cache_root = store.root / ".cache" / "extract"
    if cache_root.is_dir():
        for path in cache_root.glob("*.yaml"):
            try:
                cache = _read_cache(path)
            except (ValueError, OSError):
                continue
            values.extend(int(candidate.candidate_id[4:]) for candidate in cache.candidates)
    return f"CEX-{max(values, default=0) + 1:04d}"


def _get_scene(store: ChronosStore, scene_id: str | None):
    if scene_id is None:
        return None
    scene = next((item for item in store.scenes if item.id == scene_id), None)
    if scene is None:
        raise ValueError(f"scene is not registered: {scene_id}")
    return scene


def _validate_chapter_scene(store: ChronosStore, scene_id: str | None, chapter: int, text: str) -> None:
    scene = _get_scene(store, scene_id)
    if scene is None:
        return
    if scene.chapter != chapter:
        raise ValueError(f"scene {scene_id} belongs to chapter {scene.chapter}, not {chapter}")
    marker = f"<!-- scene: {scene_id} -->"
    if marker not in text:
        raise ValueError(f"scene marker is missing from source: {scene_id}")


def _proposal_event_payload(proposal: CandidateProposal) -> dict[str, Any]:
    return proposal.model_dump(
        mode="python",
        exclude={"candidate_id", "source_quote", "unresolved_actor_mentions"},
    )


def _proposal_digest(proposal: CandidateProposal) -> str:
    payload = proposal.model_dump(
        mode="json",
        exclude={"candidate_id", "source_quote"},
    )
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return _digest(canonical)


def _has_update_changes(current: Event, proposal: CandidateProposal) -> bool:
    if proposal.unresolved_actor_mentions:
        return True
    proposed_event = Event.model_validate(
        {"id": current.id, **_proposal_event_payload(proposal)}
    )
    return any(
        getattr(current, name) != getattr(proposed_event, name) for name in _UPDATE_FIELDS
    )


def _existing_identity(
    records: list[ExtractReviewRecord],
    *,
    scene_id: str | None,
    source_file: str,
    source_digest: str | None,
    occurrence: int | None,
) -> list[ExtractReviewRecord]:
    if source_digest is None:
        return []
    matches = [
        item
        for item in records
        if item.scene_id == scene_id
        and item.source_file == source_file
        and item.source_digest == source_digest
    ]
    if occurrence is not None:
        exact = [item for item in matches if item.occurrence == occurrence]
        if exact:
            return exact
    return matches


def _authored_source_matches(
    store: ChronosStore,
    *,
    scene_id: str | None,
    source_file: str,
    span: tuple[int, int] | None,
    source_digest: str | None,
) -> bool:
    if scene_id is None or span is None or source_digest is None:
        return False
    scene = _get_scene(store, scene_id)
    if scene is None or scene.chapter is None:
        return False
    expected_source_file = f"_novel_text/novel_text{scene.chapter:02d}.md"
    if source_file != expected_source_file:
        return False
    return any(
        event.origin.value == "authored"
        and event.source is not None
        and event.source.scene == scene_id
        and event.source.span == span
        and event.source.digest in (None, source_digest)
        for event in store.events
    )


def stage_candidates(novel_root: str | Path, proposal_path: str | Path) -> tuple[int, str]:
    store = load_store(novel_root)
    gate = store.config.extract_gate
    if gate is None:
        raise ValueError("extract_gate is not configured for this work")
    proposal = CandidateProposalBatch.model_validate(load_yaml(proposal_path))
    root = novel_root_for(store)
    source_file, source_path, text = _source_file(root, proposal.source_file)
    chapter_match = _CHAPTER_STEM.fullmatch(source_path.stem)
    assert chapter_match is not None
    chapter = int(chapter_match.group("chapter"))
    _validate_chapter_scene(store, proposal.scene_id, chapter, text)

    reviews = _load_reviews(store)
    records = list(reviews.records)
    cache_file = _cache_path(store, proposal.scene_id, source_file)
    old_cache = _read_cache(cache_file)
    old_candidates = {candidate.candidate_id: candidate for candidate in old_cache.candidates}
    for record in records:
        if record.source_digest is not None:
            continue
        legacy_candidate = old_candidates.get(record.candidate_id)
        if (
            legacy_candidate is None
            or legacy_candidate.scene_id != record.scene_id
            or legacy_candidate.source_file != record.source_file
        ):
            continue
        record.source_digest = _digest(normalize_source(legacy_candidate.source_quote))
    staged: list[CandidateRecord] = []
    skipped_authored = 0
    claimed_ids: set[str] = set()
    proposal_keys: set[tuple[str | None, str, str | None, int | None]] = set()

    for item in proposal.candidates:
        if item.type is None or item.type not in gate.include:
            raise ValueError(f"candidate type must be one of extract_gate.include: {item.title}")
        if any(actor not in store.characters_by_id for actor in item.actors):
            unknown = sorted(set(item.actors) - set(store.characters_by_id))
            raise ValueError(
                "unregistered actor IDs cannot be placed in actors; "
                f"use unresolved_actor_mentions for names: {', '.join(unknown)}"
            )
        if any(location not in store.locations_by_id for location in [item.location] if location):
            raise ValueError(f"unregistered location: {item.location}")
        if item.unresolved_actor_mentions:
            # Keep the names in the candidate document, but approval will remain unavailable.
            pass

        quote = normalize_source(item.source_quote)
        positions = _scene_positions(text, quote, proposal.scene_id)
        if not positions:
            raise ValueError(f"source_quote was not found in {source_file}: {item.title}")
        source_digest = _digest(quote)
        occurrence = 1 if len(positions) == 1 else None
        source_span = (positions[0], positions[0] + len(quote)) if len(positions) == 1 else None
        if _authored_source_matches(
            store,
            scene_id=proposal.scene_id,
            source_file=source_file,
            span=source_span,
            source_digest=source_digest,
        ):
            skipped_authored += 1
            continue
        identity_key = (proposal.scene_id, source_file, source_digest, occurrence)
        if identity_key in proposal_keys and item.candidate_id is None:
            raise ValueError("multiple proposals share one source identity; link them with reserved candidate_id values")
        proposal_keys.add(identity_key)

        matched = _existing_identity(
            records,
            scene_id=proposal.scene_id,
            source_file=source_file,
            source_digest=source_digest,
            occurrence=occurrence,
        )
        if item.candidate_id is not None:
            record = _record_for(records, item.candidate_id)
            if record is None:
                raise ValueError(f"candidate_id is not reserved in extract_reviews.yaml: {item.candidate_id}")
            if record.scene_id != proposal.scene_id or record.source_file != source_file:
                raise ValueError("candidate_id does not belong to this scene and source file")
        elif len(matched) > 1:
            raise ValueError("source identity matches multiple candidates; provide candidate_id for explicit linking")
        else:
            record = matched[0] if matched else None

        if record is not None and record.review is ReviewStatus.REJECTED and record.source_digest == source_digest:
            continue

        candidate_id = record.candidate_id if record is not None else _next_candidate_id(
            store, ExtractReviewDocument(records=records)
        )
        if candidate_id in claimed_ids:
            raise ValueError(f"duplicate candidate_id in proposal batch: {candidate_id}")
        claimed_ids.add(candidate_id)

        linked_occurrence = occurrence
        if len(positions) > 1 and record is not None and record.occurrence is not None:
            if record.occurrence <= len(positions):
                linked_occurrence = record.occurrence
        start = positions[linked_occurrence - 1] if linked_occurrence is not None else None
        source = EventSource(
            scene=proposal.scene_id,
            span=(start, start + len(quote)) if start is not None else None,
            digest=source_digest,
        )
        source_file_digest = _digest(text)
        kind = "update" if record is not None and record.event_id is not None else "new"
        if item.candidate_id is None:
            proposal_item = item.model_copy(update={"candidate_id": candidate_id})
        else:
            proposal_item = item
        candidate = CandidateRecord.model_validate(
            {
                "candidate_id": candidate_id,
                "scene_id": proposal.scene_id,
                "source_file": source_file,
                "source_file_digest": source_file_digest,
                "source_quote": quote,
                "source_match_count": 1 if start is not None else len(positions),
                "source": source,
                "proposal": proposal_item,
                "review": "pending",
                "event_id": record.event_id if record is not None else None,
                "kind": kind,
            }
        )
        staged.append(candidate)

        if record is None:
            record = ExtractReviewRecord(
                candidate_id=candidate_id,
                scene_id=proposal.scene_id,
                source_file=source_file,
                source_digest=source_digest,
                occurrence=occurrence,
                span=source.span,
                source_file_digest=source_file_digest,
                review=ReviewStatus.PENDING,
            )
            records.append(record)
        else:
            previous_digest = record.source_digest
            record.source_digest = source_digest
            record.occurrence = linked_occurrence
            record.span = source.span
            record.source_file_digest = source_file_digest
            if record.review is ReviewStatus.REJECTED and previous_digest != source_digest:
                record.review = ReviewStatus.PENDING
        if record.review is ReviewStatus.APPROVED and record.event_id is not None:
            proposal_digest = _proposal_digest(proposal_item)
            if (
                record.update_digest == proposal_digest
                and record.update_review in (ReviewStatus.APPROVED, ReviewStatus.REJECTED)
            ):
                staged.pop()
                continue
            current_event = store.all_by_id.get(record.event_id)
            if current_event is not None and not _has_update_changes(
                current_event, proposal_item
            ):
                record.update_digest = proposal_digest
                record.update_review = ReviewStatus.APPROVED
                staged.pop()
                continue
            record.update_digest = proposal_digest
            record.update_review = ReviewStatus.PENDING

    reviews.records = records
    _write_reviews(store, reviews)
    staged_ids = {candidate.candidate_id for candidate in staged}
    merged_cache = [*staged, *(item for item in old_cache.candidates if item.candidate_id not in staged_ids)]
    _write_cache(cache_file, CandidateCache(candidates=merged_cache))
    message = f"staged {len(staged)} candidate(s): {cache_file}"
    if skipped_authored:
        message += f"; skipped {skipped_authored} authored source interval(s)"
    if gate.per_chapter is not None and proposal.scene_id is not None:
        scene = _get_scene(store, proposal.scene_id)
        if scene is not None and scene.chapter is not None:
            active_ids = {event.id for event in store.selection.events}
            projected = store.selection.chapter_counts.get(scene.chapter, 0)
            for candidate in staged:
                if candidate.event_id is None or candidate.event_id not in active_ids:
                    candidate_scene = _get_scene(store, candidate.scene_id)
                    if candidate_scene is not None and candidate_scene.chapter == scene.chapter:
                        projected += 1
            if projected < gate.per_chapter.min or projected > gate.per_chapter.max:
                message += (
                    f"\nWARNING CHR022: chapter {scene.chapter} projects {projected} "
                    f"effective event(s) after candidate approval; expected "
                    f"{gate.per_chapter.min}..{gate.per_chapter.max}"
                )
    return 0, message


def _find_candidate(store: ChronosStore, candidate_id: str) -> tuple[Path, CandidateCache, CandidateRecord]:
    cache_root = store.root / ".cache" / "extract"
    if cache_root.is_dir():
        for path in cache_root.glob("*.yaml"):
            cache = _read_cache(path)
            for candidate in cache.candidates:
                if candidate.candidate_id == candidate_id:
                    return path, cache, candidate
    raise ValueError(f"pending candidate not found in extract cache: {candidate_id}")


def _assert_review_pending(store: ChronosStore, candidate: CandidateRecord) -> None:
    reviews = _load_reviews(store)
    record = _record_for(reviews.records, candidate.candidate_id)
    if record is None:
        raise ValueError(f"missing review record: {candidate.candidate_id}")
    if candidate.kind == "update":
        matches_pending_update = (
            record.review is ReviewStatus.APPROVED
            and record.event_id == candidate.event_id
            and record.update_review is ReviewStatus.PENDING
            and record.update_digest == _proposal_digest(candidate.proposal)
        )
        if not matches_pending_update:
            raise ValueError(f"candidate is not the active pending update: {candidate.candidate_id}")
    elif record.review is not ReviewStatus.PENDING:
        raise ValueError(f"candidate is not pending in extract_reviews.yaml: {candidate.candidate_id}")


def list_pending_candidates(novel_root: str | Path) -> tuple[int, str]:
    store = load_store(novel_root)
    if store.config.extract_gate is None:
        raise ValueError("extract_gate is not configured for this work")
    reviews = _load_reviews(store)
    pending = {
        item.candidate_id: item
        for item in reviews.records
        if item.review is ReviewStatus.PENDING
        or (item.review is ReviewStatus.APPROVED and item.update_review is ReviewStatus.PENDING)
    }
    cache_root = store.root / ".cache" / "extract"
    cached: dict[str, CandidateRecord] = {}
    if cache_root.is_dir():
        for path in cache_root.glob("*.yaml"):
            cache = _read_cache(path)
            cached.update({item.candidate_id: item for item in cache.candidates})
    pending = {
        candidate_id: record
        for candidate_id, record in pending.items()
        if candidate_id not in cached or cached[candidate_id].review is ReviewStatus.PENDING
    }

    scenes = {item.id: item for item in store.scenes}

    def sort_key(candidate_id: str) -> tuple[int, int, int, str]:
        record = pending[candidate_id]
        scene = scenes.get(record.scene_id) if record.scene_id is not None else None
        return (
            scene.chapter if scene is not None and scene.chapter is not None else 10**9,
            scene.order if scene is not None and scene.order is not None else 10**9,
            record.span[0] if record.span is not None else 10**9,
            candidate_id,
        )

    if not pending:
        return 0, "pending candidates: 0"
    lines = [f"pending candidates: {len(pending)}"]
    for candidate_id in sorted(pending, key=sort_key):
        record = pending[candidate_id]
        candidate = cached.get(candidate_id)
        if candidate is None:
            lines.append(
                f"  {candidate_id}  {record.scene_id or 'unplaced'}  "
                f"[{('update' if record.review is ReviewStatus.APPROVED else 'new')}; "
                "candidate cache missing; re-extract required]"
            )
            continue
        scene_label = candidate.scene_id or "unplaced (SCENE_ID_REQUIRED)"
        event_type = candidate.proposal.type.value if candidate.proposal.type is not None else "type missing"
        source_label = (
            f"span={candidate.source.span[0]}:{candidate.source.span[1]}"
            if candidate.source.span is not None
            else f"source matches={candidate.source_match_count}; link-source required"
        )
        unresolved = (
            f"; unresolved actors={','.join(candidate.proposal.unresolved_actor_mentions)}"
            if candidate.proposal.unresolved_actor_mentions
            else ""
        )
        lines.append(
            f"  {candidate_id}  [{candidate.kind}]  {scene_label}  {event_type}  {candidate.proposal.title}  "
            f"[{source_label}{unresolved}]"
        )
    return 0, "\n".join(lines)


def _current_source(
    candidate: CandidateRecord,
    root: Path,
) -> tuple[str, tuple[int, int], str, str, int]:
    source_file, path, text = _source_file(root, candidate.source_file)
    quote = normalize_source(candidate.source_quote)
    if candidate.source.span is not None and candidate.source.digest is not None:
        start, end = candidate.source.span
        region_start, region_end = _scene_region(text, candidate.scene_id)
        if (
            region_start <= start < end <= region_end
            and text[start:end] == quote
            and _digest(text[start:end]) == candidate.source.digest
        ):
            occurrence = len(
                [position for position in _scene_positions(text, quote, candidate.scene_id) if position < start]
            ) + 1
            return source_file, (start, end), _digest(quote), _digest(text), occurrence
    positions = _scene_positions(text, quote, candidate.scene_id)
    if len(positions) != 1:
        raise ValueError(
            f"source interval is not unique ({len(positions)} matches); use link-source before approve/reject"
        )
    start = positions[0]
    end = start + len(quote)
    return source_file, (start, end), _digest(quote), _digest(text), 1


def _refresh_candidate_source(
    store: ChronosStore,
    cache_path: Path,
    cache: CandidateCache,
    candidate: CandidateRecord,
) -> CandidateRecord:
    root = novel_root_for(store)
    source_file, span, interval_digest, file_digest, occurrence = _current_source(candidate, root)
    candidate.source_file = source_file
    candidate.source_file_digest = file_digest
    candidate.source_match_count = 1
    candidate.source = EventSource(
        scene=candidate.scene_id,
        span=span,
        digest=interval_digest,
    )
    _write_cache(cache_path, cache)
    reviews = _load_reviews(store)
    record = _record_for(reviews.records, candidate.candidate_id)
    if record is None:
        raise ValueError(f"missing review record: {candidate.candidate_id}")
    record.source_digest = interval_digest
    record.occurrence = occurrence
    record.span = span
    record.source_file_digest = file_digest
    _write_reviews(store, reviews)
    return candidate


def link_source(
    novel_root: str | Path,
    candidate_id: str,
    *,
    start: int,
    end: int,
) -> tuple[int, str]:
    store = load_store(novel_root)
    cache_path, cache, candidate = _find_candidate(store, candidate_id)
    if candidate.review is not ReviewStatus.PENDING:
        raise ValueError(f"candidate is not pending: {candidate_id} ({candidate.review.value})")
    _assert_review_pending(store, candidate)
    root = novel_root_for(store)
    source_file, path, text = _source_file(root, candidate.source_file)
    if start < 0 or end <= start or end > len(text):
        raise ValueError("source span must be a non-empty interval inside the normalized chapter")
    region_start, region_end = _scene_region(text, candidate.scene_id)
    if start < region_start or end > region_end:
        raise ValueError("source span is outside the candidate's scene")
    quote = text[start:end]
    digest = _digest(quote)
    occurrence = len([position for position in _scene_positions(text, quote, candidate.scene_id) if position < start]) + 1
    candidate.source_quote = quote
    candidate.source_file = source_file
    candidate.source_file_digest = _digest(text)
    candidate.source_match_count = 1
    candidate.source = EventSource(scene=candidate.scene_id, span=(start, end), digest=digest)

    reviews = _load_reviews(store)
    record = _record_for(reviews.records, candidate.candidate_id)
    if record is None:
        raise ValueError(f"missing review record: {candidate.candidate_id}")
    candidate.proposal = CandidateProposal.model_validate(
        candidate.proposal.model_dump(mode="python") | {"source_quote": quote}
    )
    record.scene_id = candidate.scene_id
    record.source_file = source_file
    record.source_digest = digest
    record.occurrence = occurrence
    record.span = (start, end)
    record.source_file_digest = _digest(text)
    _write_cache(cache_path, cache)
    _write_reviews(store, reviews)
    return 0, f"linked {candidate.candidate_id} to [{start}, {end}) in {source_file}"


def _next_event_id(store: ChronosStore) -> str:
    values = [int(event.id[4:]) for event in store.events]
    return f"EVT-{max(values, default=0) + 1:04d}"


def _to_event(candidate: CandidateRecord, event_id: str) -> Event:
    payload = _proposal_event_payload(candidate.proposal)
    payload.update(
        {
            "id": event_id,
            "candidate_id": candidate.candidate_id,
            "origin": "extracted",
            "review": "approved",
            "source": candidate.source,
        }
    )
    return Event.model_validate(payload)


def diff_candidate(novel_root: str | Path, candidate_id: str) -> tuple[int, str]:
    store = load_store(novel_root)
    _, _, candidate = _find_candidate(store, candidate_id)
    if candidate.kind != "update" or candidate.event_id is None:
        return 0, f"{candidate_id}: new event; no existing event diff"
    current = store.all_by_id.get(candidate.event_id)
    if current is None:
        raise ValueError(f"candidate update target is missing: {candidate.event_id}")
    locked = set(current.locked_fields)
    lines = [f"{candidate_id} -> {current.id}"]
    changed = False
    for name in _UPDATE_FIELDS:
        old_value = getattr(current, name)
        proposed_value = getattr(candidate.proposal, name)
        if old_value == proposed_value:
            continue
        changed = True
        disposition = "UNAPPLIED (locked)" if name in locked else "proposed"
        lines.append(f"{name}: {old_value!r} -> {proposed_value!r} [{disposition}]")
    if not changed:
        lines.append("no event field changes")
    return 0, "\n".join(lines)


def _apply_update(current: Event, proposed: Event, lock_fields: set[str]) -> Event:
    locked = set(current.locked_fields)
    payload = current.model_dump(mode="python")
    for name in _UPDATE_FIELDS:
        if name not in locked:
            payload[name] = getattr(proposed, name)
    payload.update(
        {
            "candidate_id": proposed.candidate_id,
            "origin": proposed.origin,
            "review": proposed.review,
            "source": proposed.source,
            "locked_fields": sorted(locked | lock_fields),
        }
    )
    return Event.model_validate(payload)


def _validate_approval(store: ChronosStore, candidate: CandidateRecord, event: Event) -> None:
    gate = store.config.extract_gate
    if gate is None:
        raise ValueError("extract_gate is not configured")
    if candidate.scene_id is None or event.source is None or event.source.scene is None:
        raise ValueError("SCENE_ID_REQUIRED: candidate has no registered source scene")
    if candidate.proposal.unresolved_actor_mentions:
        raise ValueError(
            "unresolved actor mentions remain: "
            + ", ".join(candidate.proposal.unresolved_actor_mentions)
        )
    if gate.profile == "relation-state" and not event.effects_on:
        raise ValueError("relation-state candidate requires non-empty effects_on")
    if candidate.proposal.type not in gate.include:
        raise ValueError("candidate type is not allowed by extract_gate.include")
    if gate.order.value == "required" and not (
        event.time and (event.time.after or event.time.before)
    ):
        raise ValueError("extract_gate.order requires a confirmed after/before relation")

    scene = next((item for item in store.scenes if item.id == candidate.scene_id), None)
    if scene is None or scene.chapter is None:
        raise ValueError("candidate scene must be registered with a chapter number")

    if candidate.kind == "update" and candidate.event_id:
        base_events = [item for item in store.events if item.id != candidate.event_id]
    else:
        base_events = list(store.events)
    probe = copy(store)
    probe.events = [*base_events, event]
    probe.selection = select_effective_events(probe)
    _validate_character_state(probe)
    if not any(item.id == event.id for item in probe.selection.events):
        details = next(
            (finding.message for finding in probe.selection.findings if event.id in finding.events),
            "candidate does not satisfy extract_gate.required_fields",
        )
        raise ValueError(details)
    active_ids = {item.id for item in probe.selection.events}
    for ref in _event_reference_ids(event):
        if ref not in active_ids:
            raise ValueError(f"candidate references non-effective event: {ref}")

    graph = build_order_graph(probe.selection.events)
    component = strongly_connected_component(graph, event.id)
    if len(component) > 1 or event.id in graph.successors.get(event.id, []):
        raise ValueError(
            f"candidate would participate in CHR001 cycle: {', '.join(sorted(component))}"
        )

    if gate.profile == "relation-state" and event.effects_on:
        for actor_id in event.effects_on:
            prior = [item.id for item in base_events if actor_id in item.actors and item.id in active_ids]
            if prior:
                pairs = incomparable_pairs(graph, [*prior, event.id])
                if pairs:
                    raise ValueError(
                        f"relation-state event is incomparable for {actor_id}: {pairs}"
                    )


def _event_reference_ids(event: Event) -> list[str]:
    refs: list[str] = []
    if event.time is not None:
        refs.extend(event.time.after)
        refs.extend(event.time.before)
        if event.time.offset is not None:
            refs.append(event.time.offset.from_event)
    refs.extend(event.causes)
    refs.extend(event.effects)
    return refs


def _write_approved_event(store: ChronosStore, candidate: CandidateRecord, event: Event) -> None:
    scene = next(item for item in store.scenes if item.id == candidate.scene_id)
    target = store.root / "events" / f"ch{scene.chapter:02d}.yaml"
    existing = list(store.events)
    if candidate.event_id:
        existing = [item for item in existing if item.id != candidate.event_id]
    target_events = [item for item in existing if store.event_files.get(item.id) == target]
    target_events.append(event)
    write_event_file(target, target_events)
    if candidate.event_id:
        old_path = store.event_files.get(candidate.event_id)
        if old_path is not None and old_path != target:
            write_event_file(old_path, [item for item in existing if store.event_files.get(item.id) == old_path])


def approve_candidate(
    novel_root: str | Path,
    candidate_id: str,
    *,
    confirm_update: bool = False,
    lock_fields: tuple[str, ...] | list[str] = (),
) -> tuple[int, str]:
    store = load_store(novel_root)
    cache_path, cache, candidate = _find_candidate(store, candidate_id)
    if candidate.review is not ReviewStatus.PENDING:
        raise ValueError(f"candidate is not pending: {candidate_id} ({candidate.review.value})")
    _assert_review_pending(store, candidate)
    locks = set(lock_fields)
    unknown_locks = sorted(locks - {"title", "type", "actors", "location", "time", "causes", "effects", "effects_on"})
    if unknown_locks:
        raise ValueError(f"unknown --lock fields: {unknown_locks}")
    if len(lock_fields) != len(locks):
        raise ValueError("--lock fields must not contain duplicates")
    _refresh_candidate_source(store, cache_path, cache, candidate)
    if candidate.scene_id is None:
        raise ValueError("SCENE_ID_REQUIRED: add a scene marker and register the scene before approval")
    if candidate.kind == "update" and not confirm_update:
        raise ValueError("candidate updates require diff review and --confirm-update")
    event_id = candidate.event_id or _next_event_id(store)
    event = _to_event(candidate, event_id)
    if candidate.kind == "update":
        current = store.all_by_id.get(event_id)
        if current is None:
            raise ValueError(f"candidate update target is missing: {event_id}")
        event = _apply_update(current, event, locks)
    else:
        event.locked_fields = sorted(locks)
    _validate_approval(store, candidate, event)
    _write_approved_event(store, candidate, event)

    reviews = _load_reviews(store)
    record = _record_for(reviews.records, candidate_id)
    if record is None:
        raise ValueError(f"missing review record: {candidate_id}")
    record.event_id = event_id
    if candidate.kind == "update":
        record.review = ReviewStatus.APPROVED
        record.update_digest = _proposal_digest(candidate.proposal)
        record.update_review = ReviewStatus.APPROVED
    else:
        record.review = ReviewStatus.APPROVED
        record.update_digest = _proposal_digest(candidate.proposal)
        record.update_review = ReviewStatus.APPROVED
    _write_reviews(store, reviews)
    candidate.event_id = event_id
    candidate.review = ReviewStatus.APPROVED
    _write_cache(cache_path, cache)
    return 0, f"approved {candidate_id} as {event_id}"


def reject_candidate(novel_root: str | Path, candidate_id: str) -> tuple[int, str]:
    store = load_store(novel_root)
    cache_path, cache, candidate = _find_candidate(store, candidate_id)
    if candidate.review is not ReviewStatus.PENDING:
        raise ValueError(f"candidate is not pending: {candidate_id} ({candidate.review.value})")
    _assert_review_pending(store, candidate)
    _refresh_candidate_source(store, cache_path, cache, candidate)
    reviews = _load_reviews(store)
    record = _record_for(reviews.records, candidate_id)
    if record is None:
        raise ValueError(f"missing review record: {candidate_id}")
    if candidate.kind == "update":
        record.update_digest = _proposal_digest(candidate.proposal)
        record.update_review = ReviewStatus.REJECTED
    else:
        record.review = ReviewStatus.REJECTED
    _write_reviews(store, reviews)
    candidate.review = ReviewStatus.REJECTED
    _write_cache(cache_path, cache)
    return 0, f"rejected {candidate_id}"

