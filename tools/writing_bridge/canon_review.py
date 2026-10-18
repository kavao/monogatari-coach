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
from metron.canon_check import (
    CanonCheckResult, PrecheckResult, build_precheck_prompt, evaluate_canon_check,
)
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
    # author: 著者が照合した。check: 別の呼び出しの検査で照合した（開始時のオプトインが要る）。
    source: Literal["author", "check"] = "author"
    checker_model: str | None = None
    conflicts: list[str] = Field(default_factory=list)
    input_sha256: str | None = None


class CandidateCheck(StepModel):
    job_id: str
    candidate_hash: str
    input_sha256: str | None = None
    checker_model: str
    passed: bool
    reasons: list[str] = Field(default_factory=list)
    facts_before: list[str] = Field(default_factory=list)
    facts_after: list[str] = Field(default_factory=list)
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
    checks: list[CandidateCheck] = Field(default_factory=list)


def _digest(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


class CheckRequest(StepModel):
    input_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    inputs: dict[str, str]


def check_input_hash(inputs: dict[str, str]) -> str:
    return _digest(json.dumps(inputs, ensure_ascii=False, sort_keys=True))


def write_check_request(path: Path, inputs: dict[str, str]) -> str:
    request = CheckRequest(input_sha256=check_input_hash(inputs), inputs=inputs)
    atomic_write_text(path, request.model_dump_json(indent=2) + "\n")
    return request.input_sha256


def require_check_request(path: Path, inputs: dict[str, str], reported_hash: str) -> None:
    if not path.is_file():
        raise BridgeError("UNKNOWN_REF", "issue the check prompt before submitting its result")
    try:
        request = CheckRequest.model_validate_json(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as error:
        raise BridgeError("SCHEMA_UNSUPPORTED", f"invalid check request: {error}") from error
    current = check_input_hash(inputs)
    if request.inputs != inputs or request.input_sha256 != current or reported_hash != current:
        raise BridgeError("STALE_EVIDENCE", "the check result no longer matches its issued inputs")


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
    lines = ["# 規定量調整の開始前照合", "", "## 当該場面のイベント", "",
             events_text(events), "", "## 調整前の本文", "",
             source.read_text(encoding="utf-8").rstrip(), ""]
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


def events_text(events: list[dict]) -> str:
    """照合対象のイベントを、結果・時刻・人物状態を省略せず渡す。"""
    return json.dumps(events, ensure_ascii=False, sort_keys=True, indent=2)


def precheck_prompt(source: Path, events: list[dict], *, input_sha256: str) -> str:
    return build_precheck_prompt(events_text=events_text(events),
                                 text=source.read_text(encoding="utf-8"),
                                 input_sha256=input_sha256)


def record_precheck_by_check(dest: Path, *, source: Path, events: list[dict],
                             result: PrecheckResult, checker_model: str) -> PreCheck:
    """検査で照合した結果を記録する。採用するかは repair-begin のオプトインで決まる。"""

    if not checker_model.strip():
        raise BridgeError("MISSING_FIELD", "record the checker model")
    known = {item["id"] for item in events}
    unknown = sorted({item.event_id for item in result.conflicts} - known)
    if unknown:
        raise BridgeError("BAD_ID", "conflict refers to events outside this scene: " + ", ".join(unknown))
    document = load(dest)
    check = PreCheck(
        text_sha256=raw_sha256(source), event_ids=[item["id"] for item in events],
        events_sha256=events_sha256(events),
        result="conflict" if result.conflicts else "no_conflict",
        authorization=f"canon-check:{checker_model}", at=now_iso(), source="check",
        checker_model=checker_model, input_sha256=result.input_sha256,
        conflicts=[f"{item.event_id}: {item.description}" for item in result.conflicts])
    document.pre_check = check
    save(dest, document)
    return check


def require_precheck(dest: Path, *, source: Path, events: list[dict],
                     accept_check: bool = False) -> str:
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
            "a conflict between the text and the events was found; resolve it before adjusting",
            refs={"conflicts": check.conflicts},
        )
    if check.source == "check" and check.input_sha256 is None:
        raise BridgeError("STALE_EVIDENCE", "the model pre-check has no issued input hash; check again")
    if check.source == "check" and not accept_check:
        raise BridgeError(
            "CANON_PRECHECK_REQUIRED",
            "the pre-check was done by a model check; the author must confirm it, "
            "or begin with --check-replaces-author",
        )
    by = "the author" if check.source == "author" else f"a check by {check.checker_model}"
    return f"CANON_PRECHECK_OK: {len(events)} event(s) confirmed by {by}"


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


def find_check(dest: Path, *, job_id: str, candidate: str) -> CandidateCheck | None:
    wanted = _digest(candidate)
    return next((item for item in load(dest).checks
                 if item.job_id == job_id and item.candidate_hash == wanted
                 and item.input_sha256 is not None), None)


def record_candidate_check(dest: Path, *, job, candidate: str, result: CanonCheckResult,
                           checker_model: str, episode=None) -> CandidateCheck:
    if not checker_model.strip():
        raise BridgeError("MISSING_FIELD", "record the checker model")
    passed, reasons = evaluate_canon_check(result, operation=job.operation, episode=episode)
    document = load(dest)
    entry = CandidateCheck(job_id=job.job_id, candidate_hash=_digest(candidate),
                           input_sha256=result.input_sha256,
                           checker_model=checker_model, passed=passed, reasons=reasons,
                           facts_before=result.facts_before, facts_after=result.facts_after,
                           at=now_iso())
    previous = next((item for item in document.checks
                     if item.job_id == entry.job_id and item.candidate_hash == entry.candidate_hash),
                    None)
    if previous is not None:
        if (previous.passed, previous.reasons) != (entry.passed, entry.reasons):
            raise BridgeError("JOB_CONFLICT", "a different check was already recorded for this candidate")
        return previous
    document.checks.append(entry)
    save(dest, document)
    return entry


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
