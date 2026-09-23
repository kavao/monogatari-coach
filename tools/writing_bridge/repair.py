"""File handoff for METRON repair steps. Never publishes or calls a provider."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Literal

from pydantic import Field

from metron.analyze import analyze_marked_text
from metron.classify import load_model_calibration, CalibrationNotReady, classify_metrics
from metron.contract import load_beat_plan
from metron.models import Failure, GeneratorInfo
from metron.repair import marked_text_for_measurement, _text_by_beat
from metron.repair_steps import (
    RepairSession, RepairJob, StepModel, begin_repair, next_job, submit_result,
)
from metron.storage import atomic_write_text

from . import commands as commands
from .context_build import collect_input_hashes
from .errors import BridgeError
from .hashes import raw_sha256, text_sha256
from .locking import locked_scene
from .models import ArtifactRefsDocument, RequestDocument, FlagValue, JournalAction, JournalEntry
from .paths import resolve_work_path
from .storage import load_json_model, load_model, append_journal, now_iso


class SkippedJob(StepModel):
    job_id: str
    job_hash: str
    prompt_hash: str
    input_hash: str
    operation: Literal["deepen", "regenerate", "seam"]
    beat_id: str | None = None
    reason: Literal["floor_met", "author_stop"]
    at: str
    recorder: Literal["tool"] = "tool"
    candidate_hash: str
    metrics_source_raw_sha256: str


class BridgeRepair(StepModel):
    version: Literal[1] = 1
    session: RepairSession
    request_hash: str
    input_hashes: dict[str, str]
    calibration_hash: str
    authorization: str
    source_path: str
    source_hash: str
    source_marked: str
    prefix: str = ""
    suffix: str = ""
    status: Literal["active", "completed", "escalated"] = "active"
    notes: list[str] = Field(default_factory=list)
    output_path: str | None = None
    output_hash: str | None = None
    output_hashes: list[str] = Field(default_factory=list)
    intent: Literal["auto", "explicit_deepen"] = "auto"
    scope: Literal["scene", "beats"] = "scene"
    beat_ids: list[str] = Field(default_factory=list)
    skipped_jobs: list[SkippedJob] = Field(default_factory=list)
    stop_reason: Literal["floor_met", "author_stop"] | None = None


def read_state(path: Path) -> BridgeRepair:
    try:
        return BridgeRepair.model_validate_json(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as error:
        raise BridgeError("SCHEMA_UNSUPPORTED", f"invalid repair state: {error}") from error


def normalize_beat_ids(plan, raw_ids: list[str]) -> list[str]:
    wanted = [item.strip() for item in raw_ids if item and item.strip()]
    known = {beat.id for beat in plan.beats}
    unknown = [item for item in wanted if item not in known]
    if unknown:
        raise BridgeError("BAD_ID", "unknown beat_id: " + ", ".join(unknown))
    seen: set[str] = set()
    ordered: list[str] = []
    for beat in plan.beats:
        if beat.id in wanted and beat.id not in seen:
            ordered.append(beat.id)
            seen.add(beat.id)
    return ordered


def required_repair_reasons(metrics, plan, calibration, clean_text, spans) -> list[str]:
    reasons: list[str] = []
    if not metrics.metrics.scene.coverage:
        reasons.append("coverage")
    span_beats = [item.beat for item in spans.spans]
    plan_beats = [beat.id for beat in plan.beats]
    if span_beats != plan_beats:
        reasons.append("span_order")
    if any(clean_text[left.end:right.start].strip()
           for left, right in zip(spans.spans, spans.spans[1:])):
        reasons.append("unmapped")
    classified = classify_metrics(metrics, plan, calibration, spans=spans)
    if any(item.failure == Failure.GENERATION_TRUNCATED for item in classified.findings):
        reasons.append("GenerationTruncated")
    if any(item.failure == Failure.BEAT_MISSING for item in classified.findings):
        reasons.append("BeatMissing")
    return reasons


def _map_invalid(reasons: list[str]) -> bool:
    return any(item in reasons for item in ("coverage", "span_order", "unmapped"))


def _save(dest, state):
    atomic_write_text(dest / "repair_state.json", state.model_dump_json(indent=2) + "\n")


def _paths(work_root, scene_id, run_id):
    if not re.fullmatch(r"run-\d{4,}", run_id):
        raise BridgeError("BAD_ID", "invalid run_id")
    root = commands.work_root_of(work_root)
    dest = resolve_work_path(root, f"_writing/{scene_id}/{run_id}")
    request = load_model(dest / "request.yaml", RequestDocument)
    if request.scene_id != scene_id or request.run_id != run_id:
        raise BridgeError("JOB_CONFLICT", "request does not match run")
    return root, dest, request


def _hashes(root, request):
    return {item.path: item.raw_sha256 for item in collect_input_hashes(
        root, commands._input_rel_paths(root, request))}


def _received_candidate_hashes(dest):
    refs_path = dest / "artifact_refs.json"
    if not refs_path.is_file():
        return set()
    refs = load_json_model(refs_path, ArtifactRefsDocument)
    hashes = {item.raw_sha256 for item in refs.candidates}
    if refs.candidate is not None:
        hashes.add(refs.candidate.raw_sha256)
    return hashes


def _active_candidate_hash(state, dest):
    received = _received_candidate_hashes(dest)
    if state.output_hash and state.output_hash in received:
        return state.output_hash
    prior = [item for item in state.output_hashes if item in received]
    return prior[-1] if prior else state.source_hash


def _guard(root, dest, request, state, repo_root):
    commands._assert_base_text_current(root, request)
    commands._assert_received_candidates_current(root, dest)
    if raw_sha256(dest / "request.yaml") != state.request_hash:
        raise BridgeError("STALE_EVIDENCE", "repair request changed; start a new run")
    if _hashes(root, request) != state.input_hashes:
        raise BridgeError("STALE_EVIDENCE", "repair context inputs changed; start a new run")
    calibration = repo_root / "config" / "metron_models.yaml"
    if not calibration.is_file() or raw_sha256(calibration) != state.calibration_hash:
        raise BridgeError("STALE_EVIDENCE", "repair model calibration changed")
    source = resolve_work_path(root, state.source_path)
    if not source.is_file() or raw_sha256(source) != state.source_hash:
        raise BridgeError("STALE_EVIDENCE", "original repair candidate changed")
    path, _, _ = commands._resolve_inspect_edition(root, request, dest, None)
    if raw_sha256(path) != _active_candidate_hash(state, dest):
        raise BridgeError("STALE_EVIDENCE", "a different candidate was received during repair")
    if state.session.pending:
        _require_issued_job_files(dest, state.session.pending)


def _job_json(dest, job):
    return json.dumps({"schema": 1, "run_id": dest.name, "status": "pending",
                       **job.model_dump()}, ensure_ascii=False, indent=2) + "\n"


def _check_job_files(dest, job):
    for suffix, content in ((".json", _job_json(dest, job)), (".prompt.md", job.prompt)):
        path = dest / "jobs" / (job.job_id + suffix)
        if path.exists() and path.read_text(encoding="utf-8") != content:
            raise BridgeError("JOB_CONFLICT", "issued job or prompt was modified")


def _require_issued_job_files(dest, job):
    for suffix, content in ((".json", _job_json(dest, job)), (".prompt.md", job.prompt)):
        path = dest / "jobs" / (job.job_id + suffix)
        if not path.is_file():
            raise BridgeError("STALE_EVIDENCE", "issued job or prompt is missing")
        if path.read_text(encoding="utf-8") != content:
            raise BridgeError("JOB_CONFLICT", "issued job or prompt was modified")


def _journal(dest, request, action, job_id=None, hashes=None, note=None):
    append_journal(dest / "journal.jsonl", JournalEntry(
        schema=1, at=now_iso(), action=action, run_id=request.run_id,
        request_id=request.request_id, job_id=job_id, hashes=hashes, note=note))


@locked_scene
def repair_begin(work_root: Path, *, scene_id: str, run_id: str,
                 model: str, authorization: str, repo_root: Path,
                 intent: str = "auto", scope: str = "scene",
                 beat_ids: list[str] | None = None) -> tuple[int, str]:
    root, dest, request = _paths(work_root, scene_id, run_id)
    if intent not in {"auto", "explicit_deepen"}:
        raise BridgeError("BAD_ID", "intent must be auto or explicit_deepen")
    if scope not in {"scene", "beats"}:
        raise BridgeError("BAD_ID", "scope must be scene or beats")
    raw_ids = list(beat_ids or [])
    if intent == "auto" and raw_ids:
        raise BridgeError("JOB_CONFLICT", "beat-ids requires --intent explicit_deepen")
    if scope == "scene" and raw_ids:
        raise BridgeError("JOB_CONFLICT", "beat-ids requires --scope beats")
    if scope == "beats" and not raw_ids:
        raise BridgeError("MISSING_FIELD", "scope beats requires --beat-ids")
    if (dest / "repair_state.json").exists():
        state = read_state(dest / "repair_state.json")
        _guard(root, dest, request, state, repo_root)
        plan = load_beat_plan(root / "_metron" / scene_id / "beats.yaml")
        normalized = normalize_beat_ids(plan, raw_ids) if raw_ids else []
        if (model != state.session.model or authorization != state.authorization
                or intent != state.intent or scope != state.scope
                or normalized != state.beat_ids):
            raise BridgeError("JOB_CONFLICT", "repair already began with different provenance")
        return 0, f"repair already begun: {dest}"
    if request.flags.metron is not FlagValue.ON:
        raise BridgeError("CONFIG_ERROR", "repair requires METRON ON")
    if not authorization.strip():
        raise BridgeError("MISSING_FIELD", "record the user's repair authorization source")
    if model != request.model.id:
        raise BridgeError("MODEL_MISMATCH", "generation model differs from the run model")
    calibration_path = repo_root / "config" / "metron_models.yaml"
    try:
        calibration = load_model_calibration(calibration_path, model)
        if not request.model.calibrated:
            raise CalibrationNotReady("run model is not calibrated")
        if calibration.expand_retention_threshold is None:
            raise CalibrationNotReady("repair requires expand_retention_threshold")
    except (CalibrationNotReady, OSError, ValueError) as error:
        raise BridgeError("MODEL_UNCALIBRATED", str(error)) from error
    commands._assert_base_text_current(root, request)
    commands._assert_received_candidates_current(root, dest)
    context, _ = commands._refresh_context_if_stale(root, dest, request)
    source, _, _ = commands._resolve_inspect_edition(root, request, dest, None)
    marked = source.read_text(encoding="utf-8")
    plan = load_beat_plan(root / "_metron" / scene_id / "beats.yaml")
    analyzed = analyze_marked_text(marked, plan, run=1,
        generator=GeneratorInfo(model=model, granularity="auto"))
    inherited = commands._edition_finish_reason(root, dest, source, analyzed.metrics)
    if inherited:
        analyzed.metrics.metrics.finish_reason = inherited
    spans = analyzed.spans.spans
    required = required_repair_reasons(
        analyzed.metrics, plan, calibration, analyzed.clean_text, analyzed.spans)
    if _map_invalid(required):
        raise BridgeError("RANGE_MISMATCH", "map valid ordered Beat boundaries before repair")
    floor = plan.generation.chars_floor
    floor_met = analyzed.metrics.metrics.scene.chars >= floor
    if intent == "auto" and floor_met and not required:
        raise BridgeError(
            "REPAIR_NOT_NEEDED",
            "scene floor is met and no required repairs remain",
            exit_code=1,
        )
    normalized = normalize_beat_ids(plan, raw_ids) if raw_ids else []
    force_deepen_ids: list[str] = []
    force_ending = False
    if intent == "explicit_deepen":
        classified = classify_metrics(
            analyzed.metrics, plan, calibration, spans=analyzed.spans)
        by_id = {item.id: item for item in analyzed.metrics.metrics.beats}
        if scope == "scene":
            force_deepen_ids = [
                beat.id for beat in plan.beats
                if (by_id.get(beat.id).chars if by_id.get(beat.id) else 0) < beat.budget.chars_hint
            ]
            force_ending = any(item.failure == Failure.ENDING_RUSH for item in classified.findings)
        else:
            force_deepen_ids = list(normalized)
            force_ending = bool(normalized) and normalized[-1] == plan.beats[-1].id
    restrict_ids = list(normalized) if scope == "beats" else []
    # Preserve outer chapter headings/prose; repairs only replace mapped Beats.
    prefix = marked[:marked.index(f"<!--beat:{plan.beats[0].id}-->")]
    closing = f"<!--/beat:{plan.beats[-1].id}-->"
    suffix = marked[marked.rindex(closing) + len(closing):]
    contract = (root / "_metron" / scene_id / "contract.yaml").read_text(encoding="utf-8")
    full_context = ("共通執筆文脈（未知状態を補完しない）:\n" +
                    context.model_dump_json(by_alias=True, indent=2) +
                    "\n場面契約:\n" + contract + "\n開始時の前後本文:\n" + marked)
    try:
        session = begin_repair(analyzed.metrics, plan, calibration,
            clean_text=analyzed.clean_text, spans=analyzed.spans,
            model=model, context=full_context, seam_enabled=False,
            force_deepen_ids=force_deepen_ids, force_ending_rush=force_ending,
            restrict_beat_ids=restrict_ids)
    except ValueError as error:
        raise BridgeError("MODEL_UNCALIBRATED", str(error)) from error
    state = BridgeRepair(session=session, request_hash=raw_sha256(dest / "request.yaml"),
        input_hashes=_hashes(root, request), calibration_hash=raw_sha256(calibration_path),
        authorization=authorization, source_path=source.relative_to(root).as_posix(),
        source_hash=raw_sha256(source), source_marked=marked, prefix=prefix, suffix=suffix,
        intent=intent, scope=scope, beat_ids=normalized)
    _save(dest, state)
    _journal(dest, request, JournalAction.REPAIR_BEGIN)
    return 0, f"repair begun: {dest}; use repair-next"


def _advance(dest, state):
    try:
        result = next_job(state.session)
    except ValueError as error:
        raise BridgeError("JOB_CONFLICT", str(error)) from error
    if not isinstance(result, RepairJob):
        from metron.repair import SCENE_FLOOR_TOKEN
        marked = state.source_marked
        if state.session.working_texts:
            marked = (state.prefix + marked_text_for_measurement(
                state.session.beat_plan, state.session.working_texts).rstrip("\n")
                + state.suffix)
        analyzed = analyze_marked_text(
            marked, state.session.beat_plan, run=1,
            generator=GeneratorInfo(model=state.session.model, granularity="auto"))
        if state.session.metrics.metrics.finish_reason in {"length", "max_tokens"}:
            analyzed.metrics.metrics.finish_reason = state.session.metrics.metrics.finish_reason
        required = required_repair_reasons(
            analyzed.metrics, state.session.beat_plan, state.session.calibration,
            analyzed.clean_text, analyzed.spans)
        if required:
            # No issuable job remains (e.g. GenerationTruncated). Close as escalated
            # so the author starts a new prepare instead of looping on active.
            state.status = "escalated"
            extra = "REQUIRED_UNREPAIRABLE: " + ", ".join(required)
            state.notes = [*(result.notes or []), extra]
        else:
            state.status = (
                "escalated" if SCENE_FLOOR_TOKEN in result.escalated_beats else "completed"
            )
            if result.notes:
                state.notes = list(result.notes)
    _save(dest, state)  # Reservation is durable BEFORE returning the prompt.
    if isinstance(result, RepairJob):
        jobs = dest / "jobs"
        jobs.mkdir(exist_ok=True)
        _check_job_files(dest, result)
        atomic_write_text(jobs / f"{result.job_id}.json", _job_json(dest, result))
        atomic_write_text(jobs / f"{result.job_id}.prompt.md", result.prompt)
    return result


def _marked_for_export(state):
    texts = state.session.working_texts
    original = _text_by_beat(state.session.clean_text, state.session.beat_plan, state.session.spans)
    if (not texts or texts == original
            or any(beat.id not in texts for beat in state.session.beat_plan.beats)):
        return state.source_marked
    return (state.prefix + marked_text_for_measurement(
        state.session.beat_plan, texts).rstrip("\n") + state.suffix)


def _export(root, dest, request, state, repo_root, observations_path=None):
    marked = _marked_for_export(state)
    # Durable output reference permits recovery if receive/inspect is interrupted.
    metron = root / "_metron" / request.scene_id
    name = f"repair.{request.run_id}.{len(state.session.history):03d}.md"
    output = metron / name
    if output.exists() and output.read_text(encoding="utf-8") != marked:
        raise BridgeError("JOB_CONFLICT", "repair output was modified")
    atomic_write_text(output, marked)
    state.output_path = output.relative_to(root).as_posix()
    state.output_hash = raw_sha256(output)
    if state.output_hash not in state.output_hashes:
        state.output_hashes.append(state.output_hash)
    _save(dest, state)
    commands.receive(root, scene_id=request.scene_id, run_id=request.run_id,
                     candidate=output, request_id=request.request_id)
    observed = dest / "observations.json"
    if observed.is_file():
        old = json.loads(observed.read_text(encoding="utf-8"))
        if old["text_sha256"] != text_sha256(marked):
            archive = dest / "observations_history" / (old["text_sha256"].split(":")[1] + ".json")
            archive.parent.mkdir(exist_ok=True)
            if not archive.exists():
                atomic_write_text(archive, observed.read_text(encoding="utf-8"))
            old.update(text_sha256=text_sha256(marked), items=[])
            atomic_write_text(observed, json.dumps(old, ensure_ascii=False, indent=2) + "\n")
    defer_c1 = state.status == "active"
    try:
        return commands.inspect(
            root,
            scene_id=request.scene_id,
            run_id=request.run_id,
            observations_path=observations_path,
            marked_path=None,
            repo_root=repo_root,
            defer_c1=defer_c1,
        )
    except BridgeError:
        # Even invalid submitted evidence must not leave the previous success report visible.
        if observations_path is not None:
            commands.inspect(
                root,
                scene_id=request.scene_id,
                run_id=request.run_id,
                observations_path=None,
                marked_path=None,
                repo_root=repo_root,
                defer_c1=defer_c1,
            )
        raise


@locked_scene
def repair_next(work_root: Path, *, scene_id: str, run_id: str,
                repo_root: Path) -> tuple[int, str]:
    root, dest, request = _paths(work_root, scene_id, run_id)
    state = read_state(dest / "repair_state.json")
    _guard(root, dest, request, state, repo_root)
    if state.status in {"completed", "escalated"} and state.session.pending is None:
        return 0, f"repair already {state.status}: {dest}"
    result = _advance(dest, state)
    _journal(dest, request, JournalAction.REPAIR_NEXT,
             result.job_id if isinstance(result, RepairJob) else None)
    if isinstance(result, RepairJob):
        if state.session.history:
            _export(root, dest, request, state, repo_root)
        return 0, f"pending: {dest / 'jobs' / (result.job_id + '.json')}"
    code, message = _export(root, dest, request, state, repo_root)
    if state.status == "active":
        return code, f"repair active (required findings remain); {message}"
    label = "escalated" if state.status == "escalated" else "completed"
    return code, f"repair {label} (unresolved findings may remain); {message}"


@locked_scene
def repair_submit(work_root: Path, *, scene_id: str, run_id: str,
                  job_id: str, model: str, candidate: Path | None,
                  error: str | None, review: str, repo_root: Path,
                  observations_path: Path | None = None) -> tuple[int, str]:
    root, dest, request = _paths(work_root, scene_id, run_id)
    state = read_state(dest / "repair_state.json")
    _guard(root, dest, request, state, repo_root)
    if (candidate is None) == (error is None):
        raise BridgeError("MISSING_FIELD", "provide either candidate or explicit error")
    if candidate is not None and not candidate.is_file():
        raise BridgeError("UNKNOWN_REF", f"candidate not found: {candidate}")
    text = candidate.read_text(encoding="utf-8") if candidate else ""
    try:
        submit_result(state.session, job_id=job_id, model=model, candidate=text,
                      error=error, review=review)
    except ValueError as failure:
        raise BridgeError("JOB_CONFLICT", str(failure)) from failure
    _save(dest, state)  # Confirm once before any derived output or measurements.
    _advance(dest, state)
    code, message = _export(root, dest, request, state, repo_root, observations_path)
    _journal(dest, request, JournalAction.REPAIR_SUBMIT, job_id)
    return code, f"result recorded; repair {state.status}; {message}"


def _reanalyze_current(root, dest, request, state, repo_root):
    source, _, _ = commands._resolve_inspect_edition(root, request, dest, None)
    marked = source.read_text(encoding="utf-8")
    candidate_hash = raw_sha256(source)
    if candidate_hash != _active_candidate_hash(state, dest):
        raise BridgeError("STALE_EVIDENCE", "current candidate hash does not match repair state")
    plan = state.session.beat_plan
    analyzed = analyze_marked_text(
        marked, plan, run=1,
        generator=GeneratorInfo(model=state.session.model, granularity="auto"))
    inherited = commands._edition_finish_reason(root, dest, source, analyzed.metrics)
    if inherited:
        analyzed.metrics.metrics.finish_reason = inherited
    return analyzed, candidate_hash, plan


@locked_scene
def repair_finish(work_root: Path, *, scene_id: str, run_id: str,
                  reason: str, authorization: str, repo_root: Path) -> tuple[int, str]:
    root, dest, request = _paths(work_root, scene_id, run_id)
    if not authorization.strip():
        raise BridgeError("MISSING_FIELD", "record the user's repair authorization source")
    if reason not in {"floor_met", "author_stop"}:
        raise BridgeError("BAD_ID", "reason must be floor_met or author_stop")
    state = read_state(dest / "repair_state.json")
    _guard(root, dest, request, state, repo_root)
    analyzed, candidate_hash, plan = _reanalyze_current(root, dest, request, state, repo_root)
    metrics_hash = candidate_hash
    required = required_repair_reasons(
        analyzed.metrics, plan, state.session.calibration,
        analyzed.clean_text, analyzed.spans)
    if state.session.metrics.metrics.finish_reason in {"length", "max_tokens"}:
        if "GenerationTruncated" not in required:
            required.append("GenerationTruncated")
    floor_met = analyzed.metrics.metrics.scene.chars >= plan.generation.chars_floor
    pending = state.session.pending
    unrepairable = [item for item in required if item == "GenerationTruncated"]
    issuable = [item for item in required if item != "GenerationTruncated"]
    can_attach_author_stop = (
        reason == "author_stop" and not issuable and pending is None)
    attaching_stop = False
    if state.status in {"completed", "escalated"}:
        last = state.skipped_jobs[-1] if state.skipped_jobs else None
        if last is None:
            if state.stop_reason == reason:
                return 0, f"repair already completed: {dest}"
            if (state.status == "escalated" and state.stop_reason is None
                    and can_attach_author_stop):
                attaching_stop = True
            else:
                raise BridgeError(
                    "JOB_CONFLICT", "repair already finished with different provenance")
        else:
            if last.reason != reason:
                raise BridgeError(
                    "JOB_CONFLICT", "repair already finished with different provenance")
            job_path = dest / "jobs" / f"{last.job_id}.json"
            if not job_path.is_file():
                raise BridgeError("STALE_EVIDENCE", "issued job is missing")
            if raw_sha256(job_path) != last.job_hash:
                raise BridgeError("JOB_CONFLICT", "skipped job hash does not match issued file")
            if last.candidate_hash != candidate_hash:
                raise BridgeError(
                    "JOB_CONFLICT", "skipped candidate hash does not match current text")
            return 0, f"repair already completed: {dest}"
    if not attaching_stop:
        if state.status != "active":
            raise BridgeError("JOB_CONFLICT", "repair is not active")
        if issuable:
            raise BridgeError("JOB_CONFLICT", "required repairs remain; cannot finish")
        if required and reason == "floor_met":
            raise BridgeError("JOB_CONFLICT", "unrepairable required findings remain")
        if reason == "floor_met" and not floor_met:
            raise BridgeError("JOB_CONFLICT", "scene floor is not met")
    if unrepairable and not any("REQUIRED_UNREPAIRABLE" in note for note in state.notes):
        state.notes = [*state.notes, "REQUIRED_UNREPAIRABLE: " + ", ".join(unrepairable)]
    if pending is not None:
        job_path = dest / "jobs" / f"{pending.job_id}.json"
        if not job_path.is_file():
            raise BridgeError("STALE_EVIDENCE", "issued job is missing")
        job_hash = raw_sha256(job_path)
        state.skipped_jobs.append(SkippedJob(
            job_id=pending.job_id, job_hash=job_hash,
            prompt_hash=pending.prompt_hash, input_hash=pending.input_hash,
            operation=pending.operation, beat_id=pending.beat_id, reason=reason,
            at=now_iso(), recorder="tool", candidate_hash=candidate_hash,
            metrics_source_raw_sha256=metrics_hash))
        state.session.pending = None
    state.stop_reason = reason
    state.status = "escalated" if (unrepairable or not floor_met) else "completed"
    _save(dest, state)
    code, message = _export(root, dest, request, state, repo_root)
    source, _, _ = commands._resolve_inspect_edition(root, request, dest, None)
    exported_hash = raw_sha256(source)
    candidate_hash = exported_hash
    if state.skipped_jobs:
        last = state.skipped_jobs[-1]
        state.skipped_jobs[-1] = last.model_copy(update={
            "candidate_hash": exported_hash,
            "metrics_source_raw_sha256": exported_hash,
        })
        _save(dest, state)
    hashes = {"candidate": candidate_hash}
    if state.skipped_jobs:
        hashes["job"] = state.skipped_jobs[-1].job_hash
    _journal(dest, request, JournalAction.REPAIR_FINISH,
             pending.job_id if pending is not None else (
                 state.skipped_jobs[-1].job_id if state.skipped_jobs else None),
             hashes=hashes, note=reason)
    return code, f"repair {state.status} ({reason}); {message}"
