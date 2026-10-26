"""File handoff for METRON repair steps. Never publishes or calls a provider."""
from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Literal, cast

from pydantic import Field

from metron.analyze import analyze_marked_text
from metron.classify import load_model_calibration, CalibrationNotReady, classify_metrics
from metron.contract import load_beat_plan
from metron.contract import load_scene_contract
from metron.contract_fix import CONTRACT_FIX_TOKEN, ContractFixSpec
from metron.length import (
    LENGTH_TOKEN, LengthConfigError, LengthSpec, assembled_chars, band_state,
    FINISH_SLACK, canon_review_digest, finish_bounds, measured_chars, resolve_bounds,
)
from metron import length as length_rules
from metron.repetition import count_phrase, repeat_report
from metron.canon_check import (
    CanonCheckError, build_canon_check_prompt, parse_canon_check, parse_precheck,
)
from metron.episodes import EpisodeError, load_episodes, splice, validate_against_plan
from metron.models import Failure, GeneratorInfo, LengthTarget
from metron.repair import marked_text_for_measurement, _text_by_beat
from metron.repair_steps import (
    RepairSession, RepairJob, StepModel, begin_repair, next_job, submit_result,
)
from metron.storage import atomic_write_text

from . import canon_review
from . import commands as commands
from .context_build import collect_input_hashes
from .errors import BridgeError
from .hashes import raw_sha256, text_sha256
from .locking import locked_scene
from .models import ArtifactRefsDocument, RequestDocument, FlagValue, JournalAction, JournalEntry
from .paths import canonical_rel, metron_scene_dir, resolve_work_path, writing_scene_dir
from .storage import load_json_model, load_model, append_journal, now_iso


class SkippedJob(StepModel):
    job_id: str
    job_hash: str
    prompt_hash: str
    input_hash: str
    operation: Literal["deepen", "regenerate", "seam", "tighten", "condense"]
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
    intent: Literal["auto", "explicit_deepen", "length", "contract_fix"] = "auto"
    scope: Literal["scene", "beats"] = "scene"
    beat_ids: list[str] = Field(default_factory=list)
    skipped_jobs: list[SkippedJob] = Field(default_factory=list)
    stop_reason: Literal["floor_met", "author_stop"] | None = None
    # 規定量調整で、CANON 検査の合格を著者確認の代わりにする（ユーザーが開始時に明示したときだけ）。
    check_replaces_author: bool = False


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
    dest = writing_scene_dir(root, scene_id) / run_id
    request = load_model(dest / "request.yaml", RequestDocument)
    if request.scene_id != scene_id or request.run_id != run_id:
        raise BridgeError("JOB_CONFLICT", "request does not match run")
    return root, dest, request


def _hashes(root, request):
    return {item.path: item.raw_sha256 for item in collect_input_hashes(
        root, commands._input_rel_paths(root, request))}


def _canonical_hashes(hashes):
    return {canonical_rel(path): digest for path, digest in hashes.items()}


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
    # 記録した鍵は書き換えず、照合のときだけ置き場によらない形にそろえる（移行の前後で同じ組を同じに扱う）。
    if _canonical_hashes(_hashes(root, request)) != _canonical_hashes(state.input_hashes):
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
    # episode_id は収束ジョブだけに出す（既存のジョブ JSON とのバイト一致を保つ）。
    body = job.model_dump(exclude={"episode_id"} if job.episode_id is None else set())
    return json.dumps({"schema": 1, "run_id": dest.name, "status": "pending",
                       **body}, ensure_ascii=False, indent=2) + "\n"


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
                 beat_ids: list[str] | None = None,
                 length_target: LengthTarget | None = None,
                 check_replaces_author: bool = False,
                 instruction: str | None = None) -> tuple[int, str]:
    root, dest, request = _paths(work_root, scene_id, run_id)
    if intent not in {"auto", "explicit_deepen", "length", "contract_fix"}:
        raise BridgeError("BAD_ID", "intent must be auto, explicit_deepen, length or contract_fix")
    if intent == "contract_fix":
        # D16b: 契約を直す再生成は明示の Beat と指示が要り、採用には著者確認が要る。
        if scope != "beats" or not beat_ids:
            raise BridgeError("MISSING_FIELD", "contract_fix needs --scope beats --beat-ids")
        if not (instruction and instruction.strip()):
            raise BridgeError("MISSING_FIELD", "contract_fix needs --instruction")
    elif instruction is not None:
        raise BridgeError("JOB_CONFLICT", "--instruction requires --intent contract_fix")
    if scope not in {"scene", "beats"}:
        raise BridgeError("BAD_ID", "scope must be scene or beats")
    if intent == "length" and (scope != "scene" or beat_ids):
        raise BridgeError("JOB_CONFLICT",
                          "length adjustment takes its scope from the length target, not --scope/--beat-ids")
    if intent != "length" and (length_target is not None or check_replaces_author):
        raise BridgeError("JOB_CONFLICT", "a length target requires --intent length")
    checked_intent = cast(Literal["auto", "explicit_deepen", "length", "contract_fix"], intent)
    checked_scope = cast(Literal["scene", "beats"], scope)
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
        plan = load_beat_plan(metron_scene_dir(root, scene_id) / "beats.yaml")
        normalized = normalize_beat_ids(plan, raw_ids) if raw_ids else []
        wanted_length = length_target or (plan.length_target if intent == "length" else None)
        began_length = state.session.length.target if state.session.length else None
        began_fix = state.session.contract_fix.instruction if state.session.contract_fix else None
        if (model != state.session.model or authorization != state.authorization
                or intent != state.intent or scope != state.scope
                or normalized != state.beat_ids or wanted_length != began_length
                or check_replaces_author != state.check_replaces_author
                or (instruction if intent == "contract_fix" else None) != began_fix):
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
    plan = load_beat_plan(metron_scene_dir(root, scene_id) / "beats.yaml")
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
    if intent == "contract_fix":
        # 打切りなど開始できない必須異常は、契約修正でも先に止める。欠落 Beat は、
        # 書き直す Beat に含まれるときだけ契約修正の中で扱える。
        fix_ids = normalize_beat_ids(plan, raw_ids)
        blocking = [item for item in required if item != "BeatMissing"]
        if "BeatMissing" in required:
            classified = classify_metrics(analyzed.metrics, plan, calibration, spans=analyzed.spans)
            outside = sorted({item.beat_id for item in classified.findings
                              if item.failure == Failure.BEAT_MISSING and item.beat_id
                              and item.beat_id not in fix_ids})
            if outside:
                blocking.append("BeatMissing: " + ", ".join(outside))
        if blocking:
            raise BridgeError("JOB_CONFLICT",
                              "resolve required repairs before a contract fix: " + ", ".join(blocking))
        return _begin_contract_fix(root, dest, request, model=model, authorization=authorization,
                                   plan=plan, analyzed=analyzed, source=source, marked=marked,
                                   context=context, calibration=calibration,
                                   calibration_path=calibration_path,
                                   beat_ids=normalize_beat_ids(plan, raw_ids),
                                   instruction=instruction or "")
    if intent == "length":
        return _begin_length(root, dest, request, model=model, authorization=authorization,
                             plan=plan, analyzed=analyzed, required=required, source=source,
                             marked=marked, context=context, calibration=calibration,
                             calibration_path=calibration_path, floor_met=floor_met,
                             length_target=length_target,
                             check_replaces_author=check_replaces_author)
    if intent == "auto" and floor_met and not required:
        raise BridgeError(
            "REPAIR_NOT_NEEDED",
            "scene floor is met and no required repairs remain",
            exit_code=1,
        )
    # D21・6-7: 自動修復の不足率は、当面は計測して報告するだけで止めない。
    density_notes = _measure_shortage(
        root, request, intent=intent, target=floor,
        chars=analyzed.metrics.metrics.scene.chars, stop=False)
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
                if (found.chars if (found := by_id.get(beat.id)) else 0) < beat.budget.chars_hint
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
    contract = (metron_scene_dir(root, scene_id) / "contract.yaml").read_text(encoding="utf-8")
    full_context = ("共通執筆文脈（未知状態を補完しない）:\n" +
                    context.model_dump_json(by_alias=True, indent=2) +
                    "\n場面契約:\n" + contract + "\n開始時の前後本文:\n" + marked)
    try:
        session = begin_repair(analyzed.metrics, plan, calibration,
            clean_text=analyzed.clean_text, spans=analyzed.spans,
            model=model, context=full_context, seam_enabled=False,
            force_deepen_ids=force_deepen_ids, force_ending_rush=force_ending,
            restrict_beat_ids=restrict_ids,
            allowed_repeats=_allowed_repeats(root, scene_id))
    except ValueError as error:
        raise BridgeError("MODEL_UNCALIBRATED", str(error)) from error
    state = BridgeRepair(session=session, request_hash=raw_sha256(dest / "request.yaml"),
        input_hashes=_hashes(root, request), calibration_hash=raw_sha256(calibration_path),
        authorization=authorization, source_path=source.relative_to(root).as_posix(),
        source_hash=raw_sha256(source), source_marked=marked, prefix=prefix, suffix=suffix,
        intent=checked_intent, scope=checked_scope, beat_ids=normalized, notes=density_notes)
    _save(dest, state)
    _journal(dest, request, JournalAction.REPAIR_BEGIN)
    return 0, f"repair begun: {dest}; use repair-next"


def _begin_length(root, dest, request, *, model, authorization, plan, analyzed, required,
                  source, marked, context, calibration, calibration_path, floor_met,
                  length_target, check_replaces_author):
    """規定量調整を始める。出来事を変えない伸縮だけを行い、候補は著者確認を経て採用する。"""

    if length_target and plan.length_target and length_target != plan.length_target:
        raise BridgeError("JOB_CONFLICT", "the length target differs from beats.yaml length_target")
    target = length_target or plan.length_target
    if target is None:
        raise BridgeError("MISSING_FIELD", "length adjustment needs --target-chars or beats.yaml length_target")
    try:
        bounds = resolve_bounds(target, plan)
    except LengthConfigError as error:
        raise BridgeError("LENGTH_CONFIG", str(error)) from error
    # D17: 欠落 Beat は length の中で先に埋める。打切りなど、埋められない必須だけを止める。
    blocking = [item for item in required if item != "BeatMissing"]
    if blocking:
        raise BridgeError("JOB_CONFLICT",
                          "resolve required repairs before length adjustment: " + ", ".join(blocking))
    texts = _text_by_beat(analyzed.clean_text, plan, analyzed.spans)
    if (band_state(measured_chars(target, plan, texts), bounds) == "in_band" and floor_met
            and not required):
        raise BridgeError("REPAIR_NOT_NEEDED", "already within the length band and the floor",
                          exit_code=1)
    # D21・6-8: 余地込みの増量目標に対して大きく足りない稿は、Deepen ではなく設計追加へ回す。
    # 欠落 Beat があるときは、まず欠落を埋めるのが先なので止めずに記録だけ残す。
    density_notes = _measure_shortage(
        root, request, intent="length", target=target.target_chars,
        chars=measured_chars(target, plan, texts), stop="BeatMissing" not in required,
        scope=f"beat {target.beat_id}" if target.scope == "beat" else "scene")
    events = canon_review.scene_events(root, request)
    precheck_note = canon_review.require_precheck(dest, source=source, events=events,
                                                  accept_check=check_replaces_author)
    episodes = _load_scene_episodes(root, request.scene_id, plan)
    prefix = marked[:marked.index(f"<!--beat:{plan.beats[0].id}-->")]
    closing = f"<!--/beat:{plan.beats[-1].id}-->"
    suffix = marked[marked.rindex(closing) + len(closing):]
    contract = (metron_scene_dir(root, request.scene_id) / "contract.yaml").read_text(encoding="utf-8")
    full_context = ("共通執筆文脈（未知状態を補完しない）:\n" +
                    context.model_dump_json(by_alias=True, indent=2) +
                    "\n場面契約:\n" + contract + "\n調整前の本文（既出事実の基準）:\n" + marked)
    try:
        session = begin_repair(analyzed.metrics, plan, calibration,
            clean_text=analyzed.clean_text, spans=analyzed.spans, model=model,
            context=full_context, seam_enabled=False,
            length=LengthSpec(target=target, known_facts=canon_review.known_facts_text(events),
                              episodes=episodes),
            allowed_repeats=_allowed_repeats(root, request.scene_id))
    except (LengthConfigError, ValueError) as error:
        raise BridgeError("MODEL_UNCALIBRATED", str(error)) from error
    state = BridgeRepair(session=session, request_hash=raw_sha256(dest / "request.yaml"),
        input_hashes=_hashes(root, request), calibration_hash=raw_sha256(calibration_path),
        authorization=authorization, source_path=source.relative_to(root).as_posix(),
        source_hash=raw_sha256(source), source_marked=marked, prefix=prefix, suffix=suffix,
        intent="length", notes=[precheck_note, *density_notes],
        check_replaces_author=check_replaces_author)
    _save(dest, state)
    _journal(dest, request, JournalAction.REPAIR_BEGIN, note="length")
    return 0, (f"length adjustment begun: {dest}; band {bounds.effective_lower}-{bounds.upper_chars}; "
               f"{precheck_note}; use repair-next")


def _load_scene_episodes(root, scene_id, plan):
    """作者が登録した子エピソード契約（任意）。収束（OP-C）の対象はこれだけ。"""
    path = metron_scene_dir(root, scene_id) / "episodes.yaml"
    if not path.is_file():
        return []
    try:
        document = load_episodes(path)
        validate_against_plan(document, plan, scene_id=scene_id)
    except (EpisodeError, OSError, ValueError) as error:
        raise BridgeError("SCHEMA_UNSUPPORTED", f"invalid episodes.yaml: {error}") from error
    return document.episodes


def _episode_of(state, job):
    if job.episode_id is None or state.session.length is None:
        return None
    return next((item for item in state.session.length.episodes if item.id == job.episode_id), None)


def _candidate_beat_text(state, job, text):
    """収束の候補は子エピソードの範囲の置き換えなので、Beat 全体に戻して比べる。"""
    episode = _episode_of(state, job)
    original = state.session.working_texts[job.beat_id]
    if episode is None:
        return original, text
    try:
        return original, splice(original, episode, text)
    except EpisodeError as error:
        raise BridgeError("RANGE_MISMATCH", str(error)) from error


def _begin_contract_fix(root, dest, request, *, model, authorization, plan, analyzed, source,
                        marked, context, calibration, calibration_path, beat_ids, instruction):
    """契約修正の再生成を始める（D16b）。長さは旧稿ではなく Beat の床で判定する。"""
    prefix = marked[:marked.index(f"<!--beat:{plan.beats[0].id}-->")]
    closing = f"<!--/beat:{plan.beats[-1].id}-->"
    suffix = marked[marked.rindex(closing) + len(closing):]
    contract = (metron_scene_dir(root, request.scene_id) / "contract.yaml").read_text(encoding="utf-8")
    full_context = ("共通執筆文脈（未知状態を補完しない）:\n" +
                    context.model_dump_json(by_alias=True, indent=2) +
                    "\n場面契約:\n" + contract + "\n修正前の本文:\n" + marked)
    try:
        session = begin_repair(analyzed.metrics, plan, calibration,
            clean_text=analyzed.clean_text, spans=analyzed.spans, model=model,
            context=full_context, seam_enabled=False,
            contract_fix=ContractFixSpec(beat_ids=beat_ids, instruction=instruction),
            allowed_repeats=_allowed_repeats(root, request.scene_id))
    except ValueError as error:
        raise BridgeError("MODEL_UNCALIBRATED", str(error)) from error
    state = BridgeRepair(session=session, request_hash=raw_sha256(dest / "request.yaml"),
        input_hashes=_hashes(root, request), calibration_hash=raw_sha256(calibration_path),
        authorization=authorization, source_path=source.relative_to(root).as_posix(),
        source_hash=raw_sha256(source), source_marked=marked, prefix=prefix, suffix=suffix,
        intent="contract_fix", scope="beats", beat_ids=beat_ids)
    _save(dest, state)
    _journal(dest, request, JournalAction.REPAIR_BEGIN, note="contract_fix")
    return 0, f"contract fix begun: {dest}; beats {', '.join(beat_ids)}; use repair-next"


def _measure_shortage(root, request, *, intent: str, target: int, chars: int, stop: bool,
                      scope: str = "scene") -> list[str]:
    """不足率を場面ごとに記録し、D21 の上限を超えたら報告（stop のときは止める）。"""
    ratio = length_rules.shortage_ratio(target, chars)
    limit = length_rules.DESIGN_SHORTAGE_LIMIT
    log = metron_scene_dir(root, request.scene_id) / "shortage_log.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    entry = {"at": now_iso(), "run_id": request.run_id, "intent": intent, "scope": scope,
             "target": target, "chars": chars, "shortage": round(ratio, 4),
             "over_limit": ratio >= limit, "stopped": bool(stop and ratio >= limit)}
    with log.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    if ratio < limit:
        return []
    message = (f"DESIGN_DENSITY: {scope} is short by {target - chars} chars ({ratio:.0%}) of {target}; "
               f"Deepen is for gaps under {limit:.0%}. Check the chapter density "
               "(tools/design_density.py) and propose adding design items or child episodes")
    if stop:
        raise BridgeError("DESIGN_DENSITY", message,
                          refs={"target": target, "chars": chars, "shortage": round(ratio, 4)})
    return [message]


def _allowed_repeats(root, scene_id) -> list[str]:
    """場面契約の意図した反復（D18）。"""
    path = metron_scene_dir(root, scene_id) / "contract.yaml"
    return list(load_scene_contract(path).scene.allowed_repeats) if path.is_file() else []


def _length_known_text(root, state, events):
    character = root / "character.md"
    parts = [state.source_marked, canon_review.known_facts_text(events)]
    if character.is_file():
        parts.append(character.read_text(encoding="utf-8"))
    return "\n".join(parts)


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
            stopped = {SCENE_FLOOR_TOKEN, LENGTH_TOKEN, CONTRACT_FIX_TOKEN} & set(
                result.escalated_beats)
            state.status = "escalated" if stopped else "completed"
            if result.notes:
                kept = [note for note in state.notes
                        if note.startswith(("CANON_PRECHECK", "DESIGN_DENSITY"))]
                state.notes = [*kept, *result.notes]
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
    metron = metron_scene_dir(root, request.scene_id)
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
                  observations_path: Path | None = None,
                  canon_authorization: str | None = None) -> tuple[int, str]:
    root, dest, request = _paths(work_root, scene_id, run_id)
    state = read_state(dest / "repair_state.json")
    _guard(root, dest, request, state, repo_root)
    if (candidate is None) == (error is None):
        raise BridgeError("MISSING_FIELD", "provide either candidate or explicit error")
    if candidate is not None and not candidate.is_file():
        raise BridgeError("UNKNOWN_REF", f"candidate not found: {candidate}")
    text = candidate.read_text(encoding="utf-8") if candidate else ""
    pending = state.session.pending
    # 提出済みのジョブの再送は submit_result の同一結果判定に任せる（応答喪失からの復旧）。
    resent = any(item.job.job_id == job_id for item in state.session.history)
    if state.intent in {"length", "contract_fix"} and candidate is not None and not resent:
        if pending is None or pending.job_id != job_id or not pending.beat_id:
            raise BridgeError("JOB_CONFLICT", "result requires the matching pending job")
        authorization = _length_authorization(dest, state, pending, text, review,
                                              canon_authorization)
        events = canon_review.scene_events(root, request)
        original, full = _candidate_beat_text(state, pending, text)
        # 結果より先に記録する。記録は同一内容なら冪等なので、途中で止まっても再送できる。
        canon_review.record_candidate(
            dest, job=pending, candidate=full, original=original, review=review,
            authorization=authorization,
            known_text=_length_known_text(root, state, events),
            names=canon_review.event_names(events))
    try:
        submit_result(state.session, job_id=job_id, model=model, candidate=text,
                      error=error,
                      review=cast(Literal["confirmed", "unverified", "rejected"], review))
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


AGENT_ACCEPTED = "agent:mechanical-checks"


def _length_authorization(dest, state, job, text, review, canon_authorization):
    """採用の根拠を決める。

    増量（deepen）と欠落 Beat の再生成は機械検査を通れば採用する（D14・D17）。差分は証跡に残し、
    著者には保存前に一度だけまとめて見せる（D15）。引き締め・収束は著者確認が基本で、検査の合格は
    開始時のオプトインがあるときだけ代わりになる。
    """
    if review != "confirmed":
        return canon_authorization
    check = canon_review.find_check(dest, job_id=job.job_id, candidate=text)
    if canon_authorization and canon_authorization.strip():
        return canon_authorization  # 著者の確認は検査の不合格（誤検出）にも優先する。
    if check is not None and not check.passed:
        raise BridgeError(
            "CANON_CHECK_FAILED",
            "the canon check failed: " + "; ".join(check.reasons)
            + " (submit --review rejected, or get the author's confirmation)")
    if state.intent == "length" and job.operation in {"deepen", "regenerate"}:
        return AGENT_ACCEPTED
    if check is not None and check.passed and state.check_replaces_author:
        return f"canon-check:{check.checker_model}"
    raise BridgeError(
        "MISSING_FIELD",
        "length adjustment needs the author's fact confirmation (--canon-authorization)")


@locked_scene
def repair_finish(work_root: Path, *, scene_id: str, run_id: str,
                  reason: str, authorization: str, repo_root: Path) -> tuple[int, str]:
    root, dest, request = _paths(work_root, scene_id, run_id)
    if not authorization.strip():
        raise BridgeError("MISSING_FIELD", "record the user's repair authorization source")
    if reason not in {"floor_met", "author_stop"}:
        raise BridgeError("BAD_ID", "reason must be floor_met or author_stop")
    stop_reason = cast(Literal["floor_met", "author_stop"], reason)
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
            operation=pending.operation, beat_id=pending.beat_id, reason=stop_reason,
            at=now_iso(), recorder="tool", candidate_hash=candidate_hash,
            metrics_source_raw_sha256=metrics_hash))
        state.session.pending = None
    state.stop_reason = stop_reason
    length_met = True
    if state.session.length is not None:
        # 規定量調整は床に加えて許容帯にも入っていなければ完了にしない。
        target = state.session.length.target
        bounds = resolve_bounds(target, plan)
        texts = _text_by_beat(analyzed.clean_text, plan, analyzed.spans)
        chars = measured_chars(target, plan, texts)
        length_met = (band_state(chars, bounds) == "in_band"
                      and assembled_chars(plan, texts) >= bounds.scene_floor)
        if not length_met:
            state.notes = [*state.notes,
                           f"LENGTH_NOT_IN_BAND: stopped at {chars} chars "
                           f"({bounds.effective_lower}-{bounds.upper_chars})"]
    state.status = ("escalated" if (unrepairable or not floor_met or not length_met)
                    else "completed")
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


@locked_scene
def canon_precheck(work_root: Path, *, scene_id: str, run_id: str,
                   result: str | None = None,
                   authorization: str | None = None,
                   check_prompt: bool = False,
                   check_result: Path | None = None,
                   checker_model: str | None = None,
                   by: str = "author") -> tuple[int, str]:
    """規定量調整の開始前照合。引数なしは材料の表示だけ、--result で著者の返答を記録する。"""
    root, dest, request = _paths(work_root, scene_id, run_id)
    commands._assert_base_text_current(root, request)
    source, _, _ = commands._resolve_inspect_edition(root, request, dest, None)
    events = canon_review.scene_events(root, request)
    if not events:
        return 0, ("CANON_PRECHECK_SKIPPED: no CHRONOS events for this scene; "
                   "the pre-adjustment text is canon and no pre-check is needed")
    inputs = {"run_path_sha256": text_sha256(dest.resolve().as_posix()),
              "request_sha256": raw_sha256(dest / "request.yaml"),
              "text_sha256": raw_sha256(source),
              "events_sha256": canon_review.events_sha256(events)}
    issued = dest / "canon_precheck.request.json"
    if check_result is not None:
        # 別の呼び出しによる検査で照合した結果。採用には repair-begin のオプトインが要る。
        if result is not None or authorization is not None:
            raise BridgeError("JOB_CONFLICT", "use either the author's --result or --check-result")
        if not check_result.is_file():
            raise BridgeError("UNKNOWN_REF", f"check result not found: {check_result}")
        try:
            parsed = parse_precheck(check_result.read_text(encoding="utf-8"))
        except CanonCheckError as error:
            raise BridgeError("SCHEMA_UNSUPPORTED", str(error)) from error
        canon_review.require_check_request(issued, inputs, parsed.input_sha256)
        check = canon_review.record_precheck_by_check(
            dest, source=source, events=events, result=parsed, checker_model=checker_model or "")
        return 0, f"canon pre-check recorded by check ({check.result}): {dest / canon_review.FILE_NAME}"
    if check_prompt:
        path = dest / "canon_precheck.prompt.md"
        atomic_write_text(path, canon_review.precheck_prompt(
            source, events, input_sha256=canon_review.check_input_hash(inputs)))
        canon_review.write_check_request(issued, inputs)
        return 0, f"canon pre-check prompt: {path}"
    if result is None:
        if authorization is not None:
            raise BridgeError("MISSING_FIELD", "--authorization requires --result")
        return 0, canon_review.precheck_view(source, events)
    check = canon_review.record_precheck(dest, source=source, events=events, result=result,
                                         authorization=authorization or "", by=by)
    return 0, (f"canon pre-check recorded by {check.source} ({check.result}): "
               f"{dest / canon_review.FILE_NAME}")


@locked_scene
def length_review(work_root: Path, *, scene_id: str, run_id: str, job_id: str,
                  candidate: Path, repo_root: Path) -> tuple[int, str]:
    """保留中の規定量調整ジョブに対する候補の確認材料を出す（何も書かない）。"""
    root, dest, request = _paths(work_root, scene_id, run_id)
    state = read_state(dest / "repair_state.json")
    _guard(root, dest, request, state, repo_root)
    if state.intent not in {"length", "contract_fix"}:
        raise BridgeError("JOB_CONFLICT",
                          "length-review is only for --intent length or contract_fix runs")
    pending = state.session.pending
    if pending is None or pending.job_id != job_id or not pending.beat_id:
        raise BridgeError("JOB_CONFLICT", "length-review requires the matching pending job")
    if not candidate.is_file():
        raise BridgeError("UNKNOWN_REF", f"candidate not found: {candidate}")
    events = canon_review.scene_events(root, request)
    original, full = _candidate_beat_text(state, pending, candidate.read_text(encoding="utf-8"))
    view = canon_review.review_view(
        original, full,
        known_text=_length_known_text(root, state, events),
        names=canon_review.event_names(events))
    return 0, view


@locked_scene
def canon_check(work_root: Path, *, scene_id: str, run_id: str, job_id: str,
                candidate: Path, repo_root: Path, result_path: Path | None = None,
                checker_model: str | None = None) -> tuple[int, str]:
    """CANON 検査。結果なしは検査用の指示を jobs/ に書き、結果ありは判定して記録する。"""
    root, dest, request = _paths(work_root, scene_id, run_id)
    state = read_state(dest / "repair_state.json")
    _guard(root, dest, request, state, repo_root)
    if state.intent != "length" or state.session.length is None:
        raise BridgeError("JOB_CONFLICT", "canon-check is only for --intent length runs")
    pending = state.session.pending
    if pending is None or pending.job_id != job_id or not pending.beat_id:
        raise BridgeError("JOB_CONFLICT", "canon-check requires the matching pending job")
    if not candidate.is_file():
        raise BridgeError("UNKNOWN_REF", f"candidate not found: {candidate}")
    text = candidate.read_text(encoding="utf-8")
    episode = _episode_of(state, pending)
    original, full = _candidate_beat_text(state, pending, text)
    events = canon_review.scene_events(root, request)
    inputs = {"run_path_sha256": text_sha256(dest.resolve().as_posix()),
              "request_sha256": raw_sha256(dest / "request.yaml"),
              "job_sha256": text_sha256(pending.model_dump_json()),
              "source_sha256": state.source_hash,
              "original_sha256": text_sha256(original),
              "candidate_sha256": raw_sha256(candidate),
              "known_facts_sha256": text_sha256(state.session.length.known_facts),
              "events_sha256": canon_review.events_sha256(events),
              "episode_sha256": text_sha256(episode.model_dump_json() if episode else "")}
    issued = dest / "jobs" / f"{pending.job_id}.canon_check.request.json"
    if result_path is None:
        if checker_model is not None:
            raise BridgeError("MISSING_FIELD", "--checker-model requires --result")
        prompt = build_canon_check_prompt(
            operation=pending.operation, known_facts=state.session.length.known_facts,
            original=original, candidate=full, episode=episode,
            input_sha256=canon_review.check_input_hash(inputs))
        path = dest / "jobs" / f"{pending.job_id}.canon_check.prompt.md"
        atomic_write_text(path, prompt)
        canon_review.write_check_request(issued, inputs)
        return 0, f"canon check prompt: {path}"
    if not result_path.is_file():
        raise BridgeError("UNKNOWN_REF", f"check result not found: {result_path}")
    try:
        result = parse_canon_check(result_path.read_text(encoding="utf-8"))
    except CanonCheckError as error:
        raise BridgeError("SCHEMA_UNSUPPORTED", str(error)) from error
    canon_review.require_check_request(issued, inputs, result.input_sha256)
    check = canon_review.record_candidate_check(
        dest, job=pending, candidate=text, result=result,
        checker_model=checker_model or "", episode=episode)
    if check.passed:
        return 0, f"canon check passed ({check.checker_model})"
    return 1, "canon check failed: " + "; ".join(check.reasons)


def _next_chapter_opening(root: Path, scene_id: str, limit: int = 300) -> str:
    match = re.fullmatch(r"ch(\d{2,})-\d{3,}", scene_id)
    if not match:
        return ""
    number = int(match.group(1)) + 1
    for path in sorted((root / "_novel_text").glob(f"novel_text{number:02d}*.md")):
        lines = [line for line in path.read_text(encoding="utf-8").splitlines()
                 if line.strip() and not line.lstrip().startswith("#")]
        return f"{path.name}: " + "".join(lines)[:limit]
    return ""


def _refined_texts(plan, path: Path, state=None) -> dict[str, str]:
    """続けて清書した稿（Beat マーカー付き）を Beat ごとの本文にする。

    報告に載らない本文の変更を黙って落とさないよう、Beat の順序、Beat の間の本文、
    Beat の外（章見出しなど）が作業稿と同じであることを確かめる。
    """
    if not path.is_file():
        raise BridgeError("UNKNOWN_REF", f"refined draft not found: {path}")
    marked = path.read_text(encoding="utf-8")
    analyzed = analyze_marked_text(marked, plan, run=1)
    spans = analyzed.spans.spans
    if not analyzed.metrics.metrics.scene.coverage:
        raise BridgeError("RANGE_MISMATCH", "the refined draft must keep every Beat marker")
    if [item.beat for item in spans] != [beat.id for beat in plan.beats]:
        raise BridgeError("RANGE_MISMATCH", "the refined draft changes the Beat order")
    clean = analyzed.clean_text
    if any(clean[left.end:right.start].strip() for left, right in zip(spans, spans[1:])):
        raise BridgeError("RANGE_MISMATCH", "the refined draft has text between Beat markers")
    if state is not None:
        opening = f"<!--beat:{plan.beats[0].id}-->"
        closing = f"<!--/beat:{plan.beats[-1].id}-->"
        prefix = marked[:marked.index(opening)]
        suffix = marked[marked.rindex(closing) + len(closing):]
        if prefix.strip() != state.prefix.strip() or suffix.strip() != state.suffix.strip():
            raise BridgeError("RANGE_MISMATCH",
                              "the refined draft changes text outside the Beats (e.g. the heading)")
    return _text_by_beat(clean, plan, analyzed.spans)


def _summary_text(root, dest, request, state, refined: dict[str, str] | None = None) -> str:
    """保存前に一度だけ見せる、主要な変化の報告（D15）。清書稿があれば3段で比べる（D20）。"""
    plan = state.session.beat_plan
    original = _text_by_beat(state.session.clean_text, plan, state.session.spans)
    current = state.session.working_texts or original
    final = refined or current
    before, after = assembled_chars(plan, original), assembled_chars(plan, current)
    events = canon_review.scene_events(root, request)
    joined_before = "\n".join(original[beat.id] for beat in plan.beats)
    joined_after = "\n".join(final.get(beat.id, "") for beat in plan.beats)
    digest = canon_review_digest(joined_before, joined_after,
                                 known_text=_length_known_text(root, state, events),
                                 names=canon_review.event_names(events))
    document = canon_review.load(dest)
    adopted = {item.job_id: item.authorization for item in document.candidates}
    lines = [f"# 主要な変化の報告: {request.scene_id}（{state.intent}、{state.status}）", ""]
    if refined is None:
        lines.append(f"- 字数（Beat 本文の合計）: {before} → {after}（床 {plan.generation.chars_floor}）")
    else:
        polished = assembled_chars(plan, refined)
        trim = (after - polished) / after if after else 0.0
        lines.append(f"- 字数（Beat 本文の合計）: 調整前 {before} → 増量後 {after} → 清書後 {polished}"
                     f"（清書で {trim:.1%} 削減、床 {plan.generation.chars_floor}）")
    if state.session.length is not None:
        target = state.session.length.target
        bounds = resolve_bounds(target, plan)
        lines.append(f"- 増量の許容帯: {bounds.effective_lower}〜{bounds.upper_chars}")
        finish = finish_bounds(target, plan)
        if finish is not None:
            lines.append(f"- 仕上がり目標: {target.finish_chars}（帯 {finish[0]}〜{finish[1]}。"
                         f"清書で削る分を見込み、増量は {target.target_chars} を目標にした）")
            if refined is not None:
                # Beat 指定では対象 Beat の字数で仕上がりを見る（場面全体の床は下で別に見る）。
                polished = measured_chars(target, plan, refined)
                if target.scope == "beat":
                    lines.append(f"- 対象 Beat {target.beat_id}: 清書後 {polished}字")
                slack = math.floor(target.finish_chars * (1 - FINISH_SLACK))
                if polished < slack:
                    lines.append(f"- REFINED_BELOW_FINISH: 清書後 {polished} が仕上がり目標 {target.finish_chars} を"
                                 f" {FINISH_SLACK:.0%} より大きく割っている。増量へは戻らず、削りすぎた箇所を戻すか、"
                                 "目標の見直しを相談する")
                elif polished < finish[0]:
                    lines.append(f"- 仕上がり目標との差は誤差の範囲（{polished - target.finish_chars:+d}字）。合わせ直さない")
    if (refined is not None and state.session.length is not None
            and state.session.length.target.scope == "beat"):
        target = state.session.length.target
        hint = next(beat.budget.chars_hint for beat in plan.beats if beat.id == target.beat_id)
        beat_chars_now = measured_chars(target, plan, refined)
        if beat_chars_now < hint:
            lines.append(f"- REFINED_BELOW_FLOOR: 清書後の Beat {target.beat_id} が {beat_chars_now}字で、"
                         f"Beat の床 {hint} を割っている。床はルールで守るため、保存の前に削りすぎた箇所を戻す")
    if refined is not None and assembled_chars(plan, refined) < plan.generation.chars_floor:
        lines.append(f"- REFINED_BELOW_FLOOR: 清書後 {assembled_chars(plan, refined)} が場面の床 "
                     f"{plan.generation.chars_floor} を割っている。床はルールで守るため、保存の前に削りすぎた箇所を戻す")
    lines.extend(["", "## 採用・棄却したジョブ"])
    for item in state.session.history:
        target = item.job.episode_id or item.job.beat_id or "scene"
        result = f"棄却（{item.rejection or item.error}）" if (item.rejection or item.error) else "採用"
        via = adopted.get(item.job.job_id)
        lines.append(f"- {item.job.job_id} {item.job.operation} {target}: {result}"
                     + (f"（{via}）" if via and result == "採用" else ""))
    if not state.session.history:
        lines.append("- なし")
    if refined is not None:
        trimmed = canon_review_digest("\n".join(current.get(b.id, "") for b in plan.beats),
                                      "\n".join(refined.get(b.id, "") for b in plan.beats))
        lines.extend(["", "## 清書で消えた・書き換わった文"])
        lines.extend(f"- {item}" for item in trimmed.removed_sentences or ("なし",))
    report = repeat_report([joined_before], ["\n".join(current.get(b.id, "") for b in plan.beats)])
    lines.extend(["", "## 場面内で3回以上に増えた語句（10字）"])
    if report:
        for phrase, count_before, count_after in report:
            tail = f" → 清書後 {count_phrase([joined_after], phrase)}" if refined is not None else ""
            lines.append(f"- {phrase}: 調整前 {count_before} → 増量後 {count_after}{tail}")
    else:
        lines.append("- なし")
    lines.extend(["", "## 調整前に無かった文"])
    lines.extend(f"- {item}" for item in digest.new_sentences or ("なし",))
    lines.extend(["", "## 消えた・書き換わった文"])
    lines.extend(f"- {item}" for item in digest.removed_sentences or ("なし",))
    lines.extend(["", "## 順序が変わった文"])
    lines.extend(f"- {item}" for item in digest.moved_sentences or ("なし",))
    lines.extend(["", "## 印（補助）",
                  "- 本文・設定に無い語: " + ("、".join(digest.new_terms) or "なし"),
                  "- 消えた名前・語: " + ("、".join(digest.removed_terms) or "なし")])
    check = document.pre_check
    lines.extend(["", "## 開始前のイベント照合"])
    if check is None:
        lines.append("- 記録なし（イベントが無い場面、または照合前）")
    else:
        lines.append(f"- {check.result}（{check.source}）: {check.authorization}")
    lines.extend(f"- {event['id']}: {event['title']}" for event in events)
    scene = load_scene_contract(metron_scene_dir(root, request.scene_id) / "contract.yaml").scene
    lines.extend(["", "## 場面契約と次章"])
    if scene.end_state is not None:
        end = scene.end_state
        lines.append(f"- 終了状態: 場所={end.location or '-'} / 行動={end.action or '-'} / 感情={end.emotion or '-'}")
    lines.extend(f"- 禁止: {item}" for item in scene.forbidden)
    opening = _next_chapter_opening(root, request.scene_id)
    lines.append(f"- 次章の書き出し: {opening or 'なし'}")
    lines.append("- 章末が設計（design_specification.md）と次章の書き出しにつながるかを確かめる")
    if state.notes:
        lines.extend(["", "## 報告"])
        lines.extend(f"- {note}" for note in state.notes)
    lines.extend(["", "主要な変化は以上です。この内容で保存してよいか、気になる箇所があれば指摘してください。", ""])
    return "\n".join(lines)


def _refined_record(plan, state, refined_path: Path, refined: dict[str, str]) -> dict:
    current = state.session.working_texts or _text_by_beat(
        state.session.clean_text, plan, state.session.spans)
    deepened, polished = assembled_chars(plan, current), assembled_chars(plan, refined)
    length = state.session.length
    return {"refined_hash": raw_sha256(refined_path), "refined_chars": polished,
            "deepened_chars": deepened,
            "trim_ratio": round((deepened - polished) / deepened, 4) if deepened else None,
            "finish_chars": length.target.finish_chars if length else None}


@locked_scene
def repair_summary(work_root: Path, *, scene_id: str, run_id: str, repo_root: Path,
                   accept: bool = False, authorization: str | None = None,
                   refined_path: Path | None = None) -> tuple[int, str]:
    """保存前の1回の確認（D15）。表示だけ、または著者の「これでよい」を記録する。

    続けて清書した稿（D20）を ``refined_path`` で渡すと、調整前 → 増量後 → 清書後で報告する。
    """
    root, dest, request = _paths(work_root, scene_id, run_id)
    state = read_state(dest / "repair_state.json")
    _guard(root, dest, request, state, repo_root)
    refined = (_refined_texts(state.session.beat_plan, refined_path, state)
               if refined_path else None)
    text = _summary_text(root, dest, request, state, refined)
    if not accept:
        if authorization is not None:
            raise BridgeError("MISSING_FIELD", "--authorization requires --accept")
        return 0, text
    if state.status == "active" or state.session.pending is not None:
        raise BridgeError("JOB_CONFLICT", "finish the repair before recording the final review")
    extra = (_refined_record(state.session.beat_plan, state, refined_path, refined)
             if refined is not None and refined_path is not None else {})
    canon_review.record_final_review(dest, authorization=authorization or "",
                                     status=state.status, output_hash=state.output_hash,
                                     summary=text, **extra)
    return 0, f"final review recorded: {dest / canon_review.FILE_NAME}"
