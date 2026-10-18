"""Resumable repair via deterministic replay of confirmed local results.

Replay never calls a provider. Only the first unconfirmed callback becomes a job;
the bounded repair algorithm and candidate checks remain in repair.py.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .calibrate import ModelCalibration
from .classify import require_calibration
from .models import BeatPlan, MetricsDocument, SpansDocument
from .repair import (
    _repair_scene_impl, _retention_threshold, SceneRepairResult, validate_expansion,
    run_marked_seam_correction, strip_generation_markers, current_beat_chars,
)
from .markers import parse_markers
from .contract_fix import ContractFixSpec, contract_fix_impl, validate_contract_fix
from .episodes import EpisodeError, locate_span, splice, validate_condense
from .length import (
    LengthSpec, assembled_chars, length_adjust_impl, measured_chars, resolve_bounds,
    tighten_min_chars, validate_tightening,
)


def digest(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


class StepModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RepairJob(StepModel):
    job_id: str
    operation: Literal["deepen", "regenerate", "seam", "tighten", "condense"]
    beat_id: str | None
    episode_id: str | None = None
    attempt: int
    model: str
    prompt: str
    prompt_hash: str
    input_hash: str
    context_hash: str


class SubmittedResult(StepModel):
    job: RepairJob
    candidate: str
    error: str | None = None
    review: Literal["confirmed", "unverified", "rejected"] = "unverified"
    rejection: str | None = None


class RepairSession(StepModel):
    version: Literal[1] = 1
    metrics: MetricsDocument
    beat_plan: BeatPlan
    calibration: ModelCalibration
    clean_text: str
    spans: SpansDocument
    model: str
    context: str = ""
    seam_enabled: bool = True
    deepen_enabled: bool = True
    regenerate_enabled: bool = True
    force_deepen_ids: list[str] = Field(default_factory=list)
    force_ending_rush: bool = False
    restrict_beat_ids: list[str] = Field(default_factory=list)
    length: LengthSpec | None = None
    contract_fix: ContractFixSpec | None = None
    allowed_repeats: list[str] = Field(default_factory=list)
    history: list[SubmittedResult] = Field(default_factory=list)
    pending: RepairJob | None = None
    working_texts: dict[str, str] = Field(default_factory=dict)


class _AwaitJob(Exception):
    def __init__(self, job: RepairJob):
        self.job = job


def begin_repair(metrics, beat_plan, calibration, *, clean_text, spans,
                 model: str, context: str = "", seam_enabled: bool = True,
                 deepen_enabled: bool = True, regenerate_enabled: bool = True,
                 force_deepen_ids: list[str] | None = None,
                 force_ending_rush: bool = False,
                 restrict_beat_ids: list[str] | None = None,
                 length: LengthSpec | None = None,
                 contract_fix: ContractFixSpec | None = None,
                 allowed_repeats: list[str] | None = None) -> RepairSession:
    require_calibration(calibration)
    if not model:
        raise ValueError("generation model is required")
    if length is not None:
        resolve_bounds(length.target, beat_plan)
    if length is not None and contract_fix is not None:
        raise ValueError("length adjustment and contract fix are separate sessions")
    if contract_fix is not None:
        known = {beat.id for beat in beat_plan.beats}
        unknown = [item for item in contract_fix.beat_ids if item not in known]
        if unknown:
            raise ValueError("unknown beat_id for contract fix: " + ", ".join(unknown))
    return RepairSession(metrics=metrics, beat_plan=beat_plan, calibration=calibration,
                         length=length, contract_fix=contract_fix,
                         allowed_repeats=list(allowed_repeats or []),
                         clean_text=clean_text, spans=spans, model=model,
                         context=context, seam_enabled=seam_enabled,
                         deepen_enabled=deepen_enabled, regenerate_enabled=regenerate_enabled,
                         force_deepen_ids=list(force_deepen_ids or []),
                         force_ending_rush=force_ending_rush,
                         restrict_beat_ids=list(restrict_beat_ids or []))


def _replay(state: RepairSession) -> RepairJob | SceneRepairResult:
    index = 0
    attempts: dict[tuple[str, str | None], int] = {}

    def dispatch(operation, beat_id, prompt, episode_id=None):
        nonlocal index
        key = (operation, episode_id or beat_id)
        attempts[key] = attempts.get(key, 0) + 1
        # 契約修正の再生成は、棄却されても同じ Beat に2回目の候補を出せる（D16b）。
        limit = 2 if (operation in {"deepen", "tighten"}
                      or (operation == "regenerate" and state.contract_fix is not None)) else 1
        if attempts[key] > limit:
            raise ValueError("repair attempt limit exceeded")
        current = json.dumps(state.working_texts, ensure_ascii=False, sort_keys=True)
        actual = (state.context + "\n\n修復時の全Beat本文:\n" + current + "\n\n" + prompt
                  if state.context else prompt)
        job = RepairJob(job_id=f"JOB-{index + 1:04d}", operation=operation,
                        beat_id=beat_id, episode_id=episode_id,
                        attempt=attempts[key], model=state.model,
                        prompt=actual, prompt_hash=digest(actual),
                        input_hash=digest(state.working_texts[beat_id] if beat_id else current),
                        context_hash=digest(state.context))
        if index == len(state.history):
            raise _AwaitJob(job)
        entry = state.history[index]
        if entry.job != job:
            raise ValueError("repair history does not match replayed job")
        index += 1
        return "" if entry.error or entry.rejection else entry.candidate

    # These callbacks are capability flags only; dispatch handles every call.
    callback = lambda prompt: ""
    try:
        if state.contract_fix is not None:
            result = contract_fix_impl(
                state.metrics, state.beat_plan, state.calibration,
                clean_text=state.clean_text, spans=state.spans, spec=state.contract_fix,
                dispatch=dispatch,
                checkpoint=lambda texts: setattr(state, "working_texts", texts),
            )
        elif state.length is not None:
            result = length_adjust_impl(
                state.metrics, state.beat_plan, state.calibration,
                clean_text=state.clean_text, spans=state.spans, length=state.length,
                dispatch=dispatch, allowed_repeats=tuple(state.allowed_repeats),
                checkpoint=lambda texts: setattr(state, "working_texts", texts),
            )
        else:
            result = _repair_scene_impl(
                state.metrics, state.beat_plan, state.calibration,
                clean_text=state.clean_text, spans=state.spans,
                expander=callback if state.deepen_enabled else None,
                regenerator=callback if state.regenerate_enabled else None,
                seam_corrector=callback if state.seam_enabled else None,
                dispatch=dispatch,
                checkpoint=lambda texts: setattr(state, "working_texts", texts),
                force_deepen_ids=state.force_deepen_ids,
                force_ending_rush=state.force_ending_rush,
                restrict_beat_ids=state.restrict_beat_ids,
                allowed_repeats=tuple(state.allowed_repeats),
            )
    except _AwaitJob as waiting:
        return waiting.job
    if index != len(state.history):
        raise ValueError("unused repair history")
    return result


def next_job(state: RepairSession) -> RepairJob | SceneRepairResult:
    """Reserve the next job; caller must persist state before handing it off."""
    result = _replay(state)
    if isinstance(result, RepairJob):
        if state.pending is not None and state.pending != result:
            raise ValueError("pending repair job changed")
        state.pending = result
    elif state.pending is not None:
        raise ValueError("unexpected pending job at completion")
    return result


def submit_result(state: RepairSession, *, job_id: str, model: str,
                  candidate: str = "", error: str | None = None,
                  review: Literal["confirmed", "unverified", "rejected"] = "unverified") -> None:
    """Confirm one reserved attempt, including empty output or explicit failure."""
    if model != state.model:
        raise ValueError("generation model does not match calibration provenance")
    if error is not None and candidate:
        raise ValueError("provide either candidate or explicit error")
    old = next((item for item in state.history if item.job.job_id == job_id), None)
    if old is not None:
        if (old.candidate, old.error, old.review) != (candidate, error, review):
            raise ValueError("different result already submitted for this job")
        return
    if state.pending is None or state.pending.job_id != job_id:
        raise ValueError("result requires the matching pending job")
    job = state.pending
    beat_id = job.beat_id or ""
    if job.operation != "seam" and not beat_id:
        raise ValueError("pending job has no beat_id")
    rejection = None
    if review != "confirmed":
        rejection = "meaning review missing or rejected (events/viewpoint/ending/state)"
    marker_parse = parse_markers(candidate)
    if marker_parse.errors or re.search(r"<!--/?beat", marker_parse.clean_text):
        rejection = "candidate contains malformed Beat markers"
    if job.operation != "seam" and re.search(r"<!--/?beat", candidate):
        parsed = parse_markers(candidate, expected_beats=[beat_id])
        if not parsed.coverage or [span.beat for span in parsed.spans] != [beat_id]:
            rejection = "candidate changed Beat markers"
    if job.operation == "regenerate" and not parse_markers(candidate).clean_text.strip():
        rejection = "candidate is empty"
    if not rejection and not error:
        if job.operation == "deepen":
            others = tuple(text for key, text in state.working_texts.items() if key != beat_id)
            check = validate_expansion(state.working_texts[beat_id],
                strip_generation_markers(candidate),
                retention_threshold=_retention_threshold(state.calibration),
                others=others, allowed_repeats=tuple(state.allowed_repeats))
            if not check.accepted:
                rejection = check.reason
        elif job.operation == "tighten":
            if state.length is None:
                rejection = "tighten requires a length adjustment session"
            else:
                bounds = resolve_bounds(state.length.target, state.beat_plan)
                minimum = tighten_min_chars(beat_id, state.beat_plan, state.working_texts,
                                            state.length.target, bounds)
                check = validate_tightening(state.working_texts[beat_id],
                    strip_generation_markers(candidate), min_chars=minimum)
                if not check.accepted:
                    rejection = check.reason
        elif job.operation == "condense":
            rejection = _condense_rejection(state, job, strip_generation_markers(candidate))
        elif job.operation == "seam":
            check = run_marked_seam_correction(state.beat_plan, state.working_texts,
                                               lambda prompt: candidate)
            if not check.accepted:
                rejection = check.reason
        elif state.contract_fix is not None:
            # 契約修正は旧稿の字数ではなく Beat の床で長さを保証する（D16b）。
            beat = next(item for item in state.beat_plan.beats if item.id == beat_id)
            rejection = validate_contract_fix(
                state.working_texts[beat_id], strip_generation_markers(candidate),
                floor=beat.budget.chars_hint)
        else:
            original = state.working_texts[beat_id]
            clean = strip_generation_markers(candidate)
            if clean.strip() == original.strip() or current_beat_chars(clean) < current_beat_chars(original):
                rejection = "regeneration is identical or shortened"
    state.history.append(SubmittedResult(job=job, candidate=candidate, error=error,
                                         review=review, rejection=rejection))
    state.pending = None


def _condense_rejection(state: RepairSession, job: RepairJob, candidate: str) -> str | None:
    """収束候補の形と、畳んだあとも実効の下限と場面の床を割らないことを確かめる。"""

    if state.length is None:
        return "condense requires a length adjustment session"
    episode = next((item for item in state.length.episodes if item.id == job.episode_id), None)
    if episode is None or job.beat_id != episode.beat_id:
        return "condense job does not match a registered child episode"
    text = state.working_texts[episode.beat_id]
    try:
        start, end = locate_span(text, episode)
    except EpisodeError as error:
        return str(error)
    check = validate_condense(text[start:end], candidate)
    if not check.accepted:
        return check.reason
    texts = dict(state.working_texts)
    texts[episode.beat_id] = splice(text, episode, candidate)
    bounds = resolve_bounds(state.length.target, state.beat_plan)
    if measured_chars(state.length.target, state.beat_plan, texts) < bounds.effective_lower:
        return "condensing falls below the effective lower bound"
    if assembled_chars(state.beat_plan, texts) < bounds.scene_floor:
        return "condensing falls below the scene floor"
    return None


def history_summary(state: RepairSession) -> list[dict]:
    return [{"job_id": item.job.job_id, "operation": item.job.operation,
             "beat_id": item.job.beat_id, "episode_id": item.job.episode_id,
             "attempt": item.job.attempt,
             "model": item.job.model, "prompt_hash": item.job.prompt_hash,
             "candidate_hash": digest(item.candidate), "review": item.review,
             "error": item.error, "rejection": item.rejection} for item in state.history]
