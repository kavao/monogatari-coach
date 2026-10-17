"""規定量調整の事実確認の記録。開始前のイベント照合と、候補ごとの著者確認を残す。

意味の照合は機械で確定しない。このモジュールは著者に見せる材料を作り、著者の
返答を本文・イベントのハッシュに結び付けて保存するだけで、provider は呼ばない。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import Field

from chronos.store import ChronosLoadError, load_store
from metron.length import canon_review_digest
from metron.repair_steps import StepModel
from metron.storage import atomic_write_text

from .errors import BridgeError
from .hashes import raw_sha256
from .links import union_scene_events
from .models import FlagValue, RequestDocument
from .storage import now_iso

FILE_NAME = "canon_review.json"


class PreCheck(StepModel):
    text_sha256: str
    event_ids: list[str]
    events_sha256: str
    result: Literal["no_conflict", "conflict"]
    authorization: str
    at: str


class CandidateReview(StepModel):
    job_id: str
    operation: str
    beat_id: str | None = None
    candidate_hash: str
    review: Literal["confirmed", "unverified", "rejected"]
    authorization: str | None = None
    new_sentences: int
    removed_sentences: int
    new_terms: list[str] = Field(default_factory=list)
    removed_terms: list[str] = Field(default_factory=list)
    at: str


class CanonReview(StepModel):
    version: Literal[1] = 1
    pre_check: PreCheck | None = None
    candidates: list[CandidateReview] = Field(default_factory=list)


def _digest(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def load(dest: Path) -> CanonReview:
    path = dest / FILE_NAME
    if not path.is_file():
        return CanonReview()
    try:
        return CanonReview.model_validate_json(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as error:
        raise BridgeError("SCHEMA_UNSUPPORTED", f"invalid canon review: {error}") from error


def save(dest: Path, document: CanonReview) -> None:
    atomic_write_text(dest / FILE_NAME, document.model_dump_json(indent=2) + "\n")


def scene_events(root: Path, request: RequestDocument) -> list[dict]:
    """当該場面の CHRONOS イベント（ON のときだけ）。ID 順で返す。"""

    if request.flags.chronos is not FlagValue.ON:
        return []
    try:
        store = load_store(root)
    except ChronosLoadError as error:
        raise BridgeError("UNKNOWN_REF", str(error)) from error
    ids = sorted(union_scene_events(store, request.scene_id))
    events = []
    for item in ids:
        if item not in store.by_id:
            continue
        event = store.by_id[item].model_dump(mode="json", exclude_none=True)
        event["actor_names"] = [
            store.characters_by_id[actor].name if actor in store.characters_by_id else actor
            for actor in event.get("actors", [])
        ]
        events.append(event)
    return events


def events_sha256(events: list[dict]) -> str:
    return _digest(json.dumps(events, ensure_ascii=False, sort_keys=True))


def known_facts_text(events: list[dict]) -> str:
    """Deepen 指示に渡す既出事実リスト。基準は調整前の本文で、イベントは照合して足す。"""

    lines = ["調整前の本文に書かれていることはすべて既出。"]
    for event in events:
        detail = [event["title"]]
        if event.get("actor_names"):
            detail.append("人物: " + "、".join(event["actor_names"]))
        if event.get("effects"):
            detail.append("結果: " + "、".join(event["effects"]))
        lines.append(f"- {event['id']}: " + " / ".join(detail))
    return "\n".join(lines)


def event_names(events: list[dict]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(
        name for event in events for name in event.get("actor_names", [])))


def precheck_view(source: Path, events: list[dict]) -> str:
    """著者が本文とイベントの矛盾を照合するための材料（読取専用）。"""

    lines = ["# 規定量調整の開始前照合", "", "## 当該場面のイベント", ""]
    lines.extend(
        f"- {event['id']}: {event['title']}"
        + (f"（人物: {'、'.join(event['actor_names'])}）" if event.get("actor_names") else "")
        for event in events
    )
    lines.extend(["", "## 調整前の本文", "", source.read_text(encoding="utf-8").rstrip(), ""])
    lines.append("本文とイベントに矛盾が無ければ --result no_conflict、あれば conflict を記録する。")
    return "\n".join(lines) + "\n"


def record_precheck(dest: Path, *, source: Path, events: list[dict], result: str,
                    authorization: str) -> PreCheck:
    if result not in {"no_conflict", "conflict"}:
        raise BridgeError("BAD_ID", "result must be no_conflict or conflict")
    if not authorization.strip():
        raise BridgeError("MISSING_FIELD", "record the author's confirmation source")
    document = load(dest)
    check = PreCheck(text_sha256=raw_sha256(source), event_ids=[item["id"] for item in events],
                     events_sha256=events_sha256(events),
                     result=result,  # type: ignore[arg-type]
                     authorization=authorization, at=now_iso())
    document.pre_check = check
    save(dest, document)
    return check


def require_precheck(dest: Path, *, source: Path, events: list[dict]) -> str:
    """イベントがある場面は、今の本文とイベントに結び付いた「矛盾なし」を要する。"""

    if not events:
        return "CANON_PRECHECK_SKIPPED: no CHRONOS events for this scene; the pre-adjustment text is canon"
    check = load(dest).pre_check
    if check is None:
        raise BridgeError(
            "CANON_PRECHECK_REQUIRED",
            "the author must compare the scene events with the text first (canon-precheck)",
        )
    if (check.text_sha256 != raw_sha256(source) or check.events_sha256 != events_sha256(events)):
        raise BridgeError("STALE_EVIDENCE", "canon pre-check no longer matches the text or events")
    if check.result != "no_conflict":
        raise BridgeError(
            "CANON_CONFLICT",
            "the author found a conflict between the text and the events; resolve it before adjusting",
        )
    return f"CANON_PRECHECK_OK: {len(events)} event(s) confirmed by the author"


def review_view(original: str, candidate: str, *, known_text: str,
                names: tuple[str, ...]) -> str:
    """候補を採用する前に著者へ見せる差分の要点（読取専用）。印は補助。"""

    digest = canon_review_digest(original, candidate, known_text=known_text, names=names)
    lines = ["# 規定量調整の候補確認", "",
             "出来事・人物・所持品・情報の授受・関係・心境の変化・過去・因果の追加・変更・欠落が無いかを確かめる。",
             "", "## 元文に無い文"]
    lines.extend(f"- {item}" for item in digest.new_sentences or ("なし",))
    lines.extend(["", "## 消えた・書き換わった元文"])
    lines.extend(f"- {item}" for item in digest.removed_sentences or ("なし",))
    lines.extend(["", "## 印（補助）",
                  "- 本文・設定に無い語: " + ("、".join(digest.new_terms) or "なし"),
                  "- 消えた名前・語: " + ("、".join(digest.removed_terms) or "なし"), ""])
    return "\n".join(lines)


def record_candidate(dest: Path, *, job, candidate: str, original: str, review: str,
                     authorization: str | None, known_text: str,
                     names: tuple[str, ...]) -> CandidateReview:
    if review == "confirmed" and not (authorization and authorization.strip()):
        raise BridgeError(
            "MISSING_FIELD",
            "length adjustment needs the author's fact confirmation (--canon-authorization)",
        )
    digest = canon_review_digest(original, candidate, known_text=known_text, names=names)
    document = load(dest)
    entry = CandidateReview(
        job_id=job.job_id, operation=job.operation, beat_id=job.beat_id,
        candidate_hash=_digest(candidate),
        review=review,  # type: ignore[arg-type]
        authorization=authorization, new_sentences=len(digest.new_sentences),
        removed_sentences=len(digest.removed_sentences), new_terms=list(digest.new_terms),
        removed_terms=list(digest.removed_terms), at=now_iso())
    previous = next((item for item in document.candidates if item.job_id == job.job_id), None)
    if previous is not None:
        if (previous.candidate_hash, previous.review) != (entry.candidate_hash, entry.review):
            raise BridgeError("JOB_CONFLICT", "a different review was already recorded for this job")
        return previous
    document.candidates.append(entry)
    save(dest, document)
    return entry
