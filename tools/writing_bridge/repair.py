"""File handoff for METRON repair steps. Never publishes or calls a provider."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Literal

from pydantic import Field

from metron.analyze import analyze_marked_text
from metron.classify import load_model_calibration, CalibrationNotReady
from metron.contract import load_beat_plan
from metron.models import GeneratorInfo
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
    status: Literal["active", "completed"] = "active"
    output_path: str | None = None
    output_hash: str | None = None
    output_hashes: list[str] = Field(default_factory=list)


def read_state(path: Path) -> BridgeRepair:
    try:
        return BridgeRepair.model_validate_json(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as error:
        raise BridgeError("SCHEMA_UNSUPPORTED", f"invalid repair state: {error}") from error


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
        _check_job_files(dest, state.session.pending)


def _job_json(dest, job):
    return json.dumps({"schema": 1, "run_id": dest.name, "status": "pending",
                       **job.model_dump()}, ensure_ascii=False, indent=2) + "\n"


def _check_job_files(dest, job):
    for suffix, content in ((".json", _job_json(dest, job)), (".prompt.md", job.prompt)):
        path = dest / "jobs" / (job.job_id + suffix)
        if path.exists() and path.read_text(encoding="utf-8") != content:
            raise BridgeError("JOB_CONFLICT", "issued job or prompt was modified")


def _journal(dest, request, action, job_id=None):
    append_journal(dest / "journal.jsonl", JournalEntry(
        schema=1, at=now_iso(), action=action, run_id=request.run_id,
        request_id=request.request_id, job_id=job_id))


@locked_scene
def repair_begin(work_root: Path, *, scene_id: str, run_id: str,
                 model: str, authorization: str, repo_root: Path) -> tuple[int, str]:
    root, dest, request = _paths(work_root, scene_id, run_id)
    if (dest / "repair_state.json").exists():
        state = read_state(dest / "repair_state.json")
        _guard(root, dest, request, state, repo_root)
        if model != state.session.model or authorization != state.authorization:
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
    if (not analyzed.metrics.metrics.scene.coverage or
            [item.beat for item in spans] != [beat.id for beat in plan.beats]):
        raise BridgeError("RANGE_MISMATCH", "map valid ordered Beat boundaries before repair")
    if any(analyzed.clean_text[left.end:right.start].strip()
           for left, right in zip(spans, spans[1:])):
        raise BridgeError("RANGE_MISMATCH", "unmapped prose between Beats")
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
            model=model, context=full_context)
    except ValueError as error:
        raise BridgeError("MODEL_UNCALIBRATED", str(error)) from error
    state = BridgeRepair(session=session, request_hash=raw_sha256(dest / "request.yaml"),
        input_hashes=_hashes(root, request), calibration_hash=raw_sha256(calibration_path),
        authorization=authorization, source_path=source.relative_to(root).as_posix(),
        source_hash=raw_sha256(source), source_marked=marked, prefix=prefix, suffix=suffix)
    _save(dest, state)
    _journal(dest, request, JournalAction.REPAIR_BEGIN)
    return 0, f"repair begun: {dest}; use repair-next"


def _advance(dest, state):
    try:
        result = next_job(state.session)
    except ValueError as error:
        raise BridgeError("JOB_CONFLICT", str(error)) from error
    if not isinstance(result, RepairJob):
        state.status = "completed"
    _save(dest, state)  # Reservation is durable BEFORE returning the prompt.
    if isinstance(result, RepairJob):
        jobs = dest / "jobs"
        jobs.mkdir(exist_ok=True)
        _check_job_files(dest, result)
        atomic_write_text(jobs / f"{result.job_id}.json", _job_json(dest, result))
        atomic_write_text(jobs / f"{result.job_id}.prompt.md", result.prompt)
    return result


def _export(root, dest, request, state, repo_root, observations_path=None):
    original = _text_by_beat(state.session.clean_text, state.session.beat_plan, state.session.spans)
    if state.session.working_texts == original:
        marked = state.source_marked
    else:
        marked = (state.prefix + marked_text_for_measurement(
            state.session.beat_plan, state.session.working_texts).rstrip("\n") + state.suffix)
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
    try:
        return commands.inspect(root, scene_id=request.scene_id, run_id=request.run_id,
                                observations_path=observations_path, marked_path=None,
                                repo_root=repo_root)
    except BridgeError:
        # Even invalid submitted evidence must not leave the previous success report visible.
        if observations_path is not None:
            commands.inspect(root, scene_id=request.scene_id, run_id=request.run_id,
                             observations_path=None, marked_path=None, repo_root=repo_root)
        raise


@locked_scene
def repair_next(work_root: Path, *, scene_id: str, run_id: str,
                repo_root: Path) -> tuple[int, str]:
    root, dest, request = _paths(work_root, scene_id, run_id)
    state = read_state(dest / "repair_state.json")
    _guard(root, dest, request, state, repo_root)
    result = _advance(dest, state)
    _journal(dest, request, JournalAction.REPAIR_NEXT,
             result.job_id if isinstance(result, RepairJob) else None)
    if isinstance(result, RepairJob):
        if state.session.history:
            _export(root, dest, request, state, repo_root)
        return 0, f"pending: {dest / 'jobs' / (result.job_id + '.json')}"
    code, message = _export(root, dest, request, state, repo_root)
    return code, f"repair completed (unresolved findings may remain); {message}"


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
