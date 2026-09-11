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
    _repair_scene_impl, SceneRepairResult, validate_expansion,
    run_marked_seam_correction, strip_generation_markers, current_beat_chars,
)
from .markers import parse_markers


def digest(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


class StepModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RepairJob(StepModel):
    job_id: str
    operation: Literal["deepen", "regenerate", "seam"]
    beat_id: str | None
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
    history: list[SubmittedResult] = Field(default_factory=list)
    pending: RepairJob | None = None
    working_texts: dict[str, str] = Field(default_factory=dict)


class _AwaitJob(Exception):
    def __init__(self, job: RepairJob):
        self.job = job


def begin_repair(metrics, beat_plan, calibration, *, clean_text, spans,
                 model: str, context: str = "", seam_enabled: bool = True,
                 deepen_enabled: bool = True, regenerate_enabled: bool = True) -> RepairSession:
    require_calibration(calibration)
    if not model:
        raise ValueError("generation model is required")
    return RepairSession(metrics=metrics, beat_plan=beat_plan, calibration=calibration,
                         clean_text=clean_text, spans=spans, model=model,
                         context=context, seam_enabled=seam_enabled,
                         deepen_enabled=deepen_enabled, regenerate_enabled=regenerate_enabled)


def _replay(state: RepairSession) -> RepairJob | SceneRepairResult:
    index = 0
    attempts: dict[tuple[str, str | None], int] = {}

    def dispatch(operation, beat_id, prompt):
        nonlocal index
        key = (operation, beat_id)
        attempts[key] = attempts.get(key, 0) + 1
        limit = 2 if operation == "deepen" else 1
        if attempts[key] > limit:
            raise ValueError("repair attempt limit exceeded")
        current = json.dumps(state.working_texts, ensure_ascii=False, sort_keys=True)
        actual = (state.context + "\n\n修復時の全Beat本文:\n" + current + "\n\n" + prompt
                  if state.context else prompt)
        job = RepairJob(job_id=f"JOB-{index + 1:04d}", operation=operation,
                        beat_id=beat_id, attempt=attempts[key], model=state.model,
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
        result = _repair_scene_impl(
            state.metrics, state.beat_plan, state.calibration,
            clean_text=state.clean_text, spans=state.spans,
            expander=callback if state.deepen_enabled else None,
            regenerator=callback if state.regenerate_enabled else None,
            seam_corrector=callback if state.seam_enabled else None,
            dispatch=dispatch,
            checkpoint=lambda texts: setattr(state, "working_texts", texts),
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
    rejection = None
    if review != "confirmed":
        rejection = "meaning review missing or rejected (events/viewpoint/ending/state)"
    marker_parse = parse_markers(candidate)
    if marker_parse.errors or re.search(r"<!--/?beat", marker_parse.clean_text):
        rejection = "candidate contains malformed Beat markers"
    if job.operation != "seam" and re.search(r"<!--/?beat", candidate):
        parsed = parse_markers(candidate, expected_beats=[job.beat_id])
        if not parsed.coverage or [span.beat for span in parsed.spans] != [job.beat_id]:
            rejection = "candidate changed Beat markers"
    if job.operation == "regenerate" and not parse_markers(candidate).clean_text.strip():
        rejection = "candidate is empty"
    if not rejection and not error:
        if job.operation == "deepen":
            check = validate_expansion(state.working_texts[job.beat_id],
                strip_generation_markers(candidate),
                retention_threshold=state.calibration.expand_retention_threshold)
            if not check.accepted:
                rejection = check.reason
        elif job.operation == "seam":
            check = run_marked_seam_correction(state.beat_plan, state.working_texts,
                                               lambda prompt: candidate)
            if not check.accepted:
                rejection = check.reason
        else:
            original = state.working_texts[job.beat_id]
            clean = strip_generation_markers(candidate)
            if clean.strip() == original.strip() or current_beat_chars(clean) < current_beat_chars(original):
                rejection = "regeneration is identical or shortened"
    state.history.append(SubmittedResult(job=job, candidate=candidate, error=error,
                                         review=review, rejection=rejection))
    state.pending = None


def history_summary(state: RepairSession) -> list[dict]:
    return [{"job_id": item.job.job_id, "operation": item.job.operation,
             "beat_id": item.job.beat_id, "attempt": item.job.attempt,
             "model": item.job.model, "prompt_hash": item.job.prompt_hash,
             "candidate_hash": digest(item.candidate), "review": item.review,
             "error": item.error, "rejection": item.rejection} for item in state.history]
