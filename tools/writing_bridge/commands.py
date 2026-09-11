"""prepare / receive / inspect / status。本文正本は書き換えない。"""

from __future__ import annotations

from pathlib import Path
import re
import shutil

from inspection_flags import InspectionConfigError, InspectionFlag, load_inspection_flags
from chronos.check import check_store
from chronos.models import Severity as ChronosSeverity
from chronos.store import ChronosLoadError, ChronosStore, load_store
from metron.analyze import analyze_marked_text
from metron.classify import CalibrationNotReady, classify_metrics, load_model_calibration
from metron.contract import load_beat_plan
from metron.models import GeneratorInfo, MetricsDocument
from metron.regression import build_regression_observation
from metron.storage import atomic_write_model, atomic_write_text, load_model as load_metron_model

from .context_build import (
    build_candidate_links,
    build_context,
    collect_input_hashes,
    peek_model_calibrated,
    render_context_md,
)
from .errors import BridgeError, ErrorDocument, ErrorItem
from .hashes import (
    EMPTY_RAW_SHA256,
    EMPTY_TEXT_SHA256,
    raw_sha256,
    read_normalized,
    text_sha256,
)
from .links import raise_if_errors, validate_links
from .locking import locked_scene
from .models import (
    SCHEMA,
    ArtifactRef,
    ArtifactRefsDocument,
    GenerationProvenance,
    Confirmation,
    ContextDocument,
    FlagPair,
    FlagValue,
    ItemStatus,
    JournalAction,
    JournalEntry,
    LinksDocument,
    ModelRef,
    ObservationsDocument,
    Permissions,
    ReportDocument,
    ReportFinding,
    RequestDocument,
    RequestKind,
    Selector,
    SelectorKind,
    Severity,
)
from .observe import inspect_observations
from .paths import resolve_work_path, work_rel_path
from .storage import (
    append_journal,
    load_json_model,
    load_model,
    next_index,
    now_iso,
    read_journal,
    write_model,
    write_text,
)


def work_root_of(path: Path) -> Path:
    root = path.resolve()
    if (root / "config.md").is_file() or (root / "_novel_text").is_dir():
        return root
    raise BridgeError("UNKNOWN_REF", f"work root not found: {path}", refs={"path": str(path)})


def run_dir(work_root: Path, scene_id: str, run_id: str) -> Path:
    return work_root / "_writing" / scene_id / run_id


def allocate_run_id(work_root: Path, scene_id: str) -> str:
    parent = work_root / "_writing" / scene_id
    numbers: list[int] = []
    if parent.is_dir():
        for child in parent.iterdir():
            if child.is_dir() and child.name.startswith("run-"):
                suffix = child.name.removeprefix("run-")
                if suffix.isdigit():
                    numbers.append(int(suffix))
    return f"run-{next_index(numbers):04d}"


def allocate_request_id(work_root: Path) -> str:
    numbers: list[int] = []
    writing = work_root / "_writing"
    if writing.is_dir():
        for request in writing.glob("**/request.yaml"):
            try:
                loaded = load_model(request, RequestDocument)
            except BridgeError:
                continue
            suffix = loaded.request_id.removeprefix("WRQ-")
            if suffix.isdigit():
                numbers.append(int(suffix))
    return f"WRQ-{next_index(numbers):04d}"


def prepare(
    work_root: Path,
    *,
    scene_id: str,
    text_path: str,
    request_kind: RequestKind,
    model_id: str,
    selector: Selector | None,
    links_path: Path | None,
    repo_root: Path,
    dry_run: bool = False,
    allow_publish: bool = False,
) -> tuple[int, str]:
    root = work_root_of(work_root)
    try:
        flags = load_inspection_flags(root / "config.md")
    except InspectionConfigError as error:
        raise BridgeError("CONFIG_ERROR", str(error), refs={"path": "config.md"}) from error
    if flags.metron is InspectionFlag.OFF and flags.chronos is InspectionFlag.OFF:
        return 0, "skipped: METRON and CHRONOS are OFF; no run created"
    rel_text = work_rel_path(text_path, field="target.text_path")
    text_file = resolve_work_path(root, rel_text, field="target.text_path")
    text_exists = text_file.is_file()
    if not text_exists and request_kind is not RequestKind.NEW:
        raise BridgeError(
            "UNKNOWN_REF",
            f"text file not found: {rel_text}",
            refs={"path": rel_text},
        )
    if text_exists:
        existing_text = text_file.read_text(encoding="utf-8")
        if selector is None and request_kind is not RequestKind.NEW:
            raise BridgeError("MISSING_FIELD", "selector is required for existing text")
        if selector is not None:
            _validate_selector(read_normalized(text_file), selector)
        elif (
            allow_publish
            and request_kind is RequestKind.NEW
            and existing_text.strip()
        ):
            from .publish import scene_anchor_span
            if scene_anchor_span(existing_text, scene_id) is None:
                raise BridgeError(
                    "MISSING_FIELD",
                    "existing text requires a selector, scene anchor, or append",
                    refs={"path": rel_text, "request_kind": request_kind.value},
                )
    run_id = allocate_run_id(root, scene_id)
    request_id = allocate_request_id(root)
    dest = run_dir(root, scene_id, run_id)
    if dry_run:
        return 0, f"would prepare: {dest}"

    request = RequestDocument(
        schema=SCHEMA,
        request_id=request_id,
        run_id=run_id,
        work_rel=root.name,
        scene_id=scene_id,
        request_kind=request_kind,
        target={
            "text_path": rel_text,
            "selector": selector.model_dump(mode="json") if selector else None,
            "base_raw_sha256": raw_sha256(text_file) if text_exists else EMPTY_RAW_SHA256,
            "base_text_sha256": (
                text_sha256(text_file.read_text(encoding="utf-8"))
                if text_exists
                else EMPTY_TEXT_SHA256
            ),
            "base_exists": text_exists,
        },
        model=ModelRef(
            id=model_id,
            calibrated=peek_model_calibrated(repo_root / "config" / "metron_models.yaml", model_id),
        ),
        permissions=Permissions(
            draft=True,
            repair=False,
            publish=allow_publish,
            event_patch=False,
        ),
        flags=FlagPair(
            metron=FlagValue(flags.metron.value),
            chronos=FlagValue(flags.chronos.value),
        ),
    )
    dest.mkdir(parents=True, exist_ok=True)
    write_model(dest / "request.yaml", request)

    store = None
    if flags.chronos is InspectionFlag.ON:
        try:
            store = load_store(root)
        except ChronosLoadError as error:
            raise BridgeError("UNKNOWN_REF", str(error)) from error
    links = None
    if flags.chronos is InspectionFlag.ON:
        if selector is None:
            selector = Selector(kind=SelectorKind.HEADING, value=scene_id)
        if links_path is not None:
            links = load_model(links_path, LinksDocument)
            raise_if_errors(
                validate_links(
                    links,
                    store,
                    scene_id=scene_id,
                    metron_on=flags.metron is InspectionFlag.ON,
                )
            )
        else:
            links = build_candidate_links(
                request,
                store,
                selector,
                request.target.base_text_sha256,
            )
            raise_if_errors(
                validate_links(
                    links,
                    store,
                    scene_id=scene_id,
                    metron_on=flags.metron is InspectionFlag.ON,
                )
            )
        write_model(dest / "links.yaml", links)

    metron_dir = root / "_metron" / scene_id if flags.metron is InspectionFlag.ON else None
    extra = _input_rel_paths(root, request)
    context = build_context(
        root,
        request,
        store=store,
        links=links,
        metron_root=metron_dir,
        extra_hashes=extra,
    )
    write_model(dest / "context.json", context, json_format=True)
    write_text(dest / "context.md", render_context_md(context))
    append_journal(
        dest / "journal.jsonl",
        JournalEntry(
            schema=SCHEMA,
            at=now_iso(),
            action=JournalAction.PREPARE,
            run_id=run_id,
            request_id=request_id,
        ),
    )
    return 0, f"prepared: {dest}"


@locked_scene
def receive(
    work_root: Path,
    *,
    scene_id: str,
    run_id: str,
    candidate: Path,
    request_id: str | None,
    finish_reason: str | None = None,
) -> tuple[int, str]:
    root = work_root_of(work_root)
    dest = run_dir(root, scene_id, run_id)
    request = load_model(dest / "request.yaml", RequestDocument)
    if request_id and request.request_id != request_id:
        raise BridgeError(
            "UNKNOWN_REF",
            "request_id does not match the run",
            refs={"expected": request.request_id, "actual": request_id},
        )
    if not candidate.is_file():
        raise BridgeError("UNKNOWN_REF", f"candidate not found: {candidate}")
    _refuse_receive_after_publish(dest)
    incoming = raw_sha256(candidate)
    refs_path = dest / "artifact_refs.json"
    refs = (
        load_json_model(refs_path, ArtifactRefsDocument)
        if refs_path.is_file()
        else ArtifactRefsDocument(
            schema=SCHEMA,
            request_id=request.request_id,
            model=request.model,
        )
    )
    history = list(refs.candidates)
    if refs.candidate is not None and all(
        item.raw_sha256 != refs.candidate.raw_sha256 for item in history
    ):
        history.append(refs.candidate)
    reused = next(
        (item for item in history if _edition_intact(root, item, incoming)),
        None,
    )
    if reused is not None:
        refs.candidate = reused
        refs.candidates = history
        _remember_metron_sources(root, request, refs, marked=reused)
        _apply_generation(refs, incoming, finish_reason, request.model.id)
        write_model(refs_path, refs, json_format=True)
        latest = dest / "candidate.md"
        source = resolve_work_path(root, reused.path)
        shutil.copyfile(source, latest)
        append_journal(
            dest / "journal.jsonl",
            JournalEntry(
                schema=SCHEMA,
                at=now_iso(),
                action=JournalAction.RECEIVE,
                run_id=request.run_id,
                request_id=request.request_id,
                hashes={"candidate": incoming},
                note="duplicate receive; existing edition reused",
            ),
        )
        return 0, f"received (unchanged): {source}"
    if request.flags.metron is FlagValue.ON:
        metron = root / "_metron" / request.scene_id
        metron.mkdir(parents=True, exist_ok=True)
        stored = _next_versioned_path(metron, "marked", ".md")
    else:
        cand_dir = dest / "candidates"
        cand_dir.mkdir(parents=True, exist_ok=True)
        stored = _next_versioned_path(cand_dir, "candidate", ".md")
    shutil.copyfile(candidate, stored)
    latest = dest / "candidate.md"
    shutil.copyfile(stored, latest)
    ref = ArtifactRef(path=_rel(root, stored), raw_sha256=incoming)
    history.append(ref)
    refs.candidate = ref
    refs.candidates = history
    _remember_metron_sources(root, request, refs, marked=ref)
    _apply_generation(refs, incoming, finish_reason, request.model.id)
    write_model(refs_path, refs, json_format=True)
    append_journal(
        dest / "journal.jsonl",
        JournalEntry(
            schema=SCHEMA,
            at=now_iso(),
            action=JournalAction.RECEIVE,
            run_id=request.run_id,
            request_id=request.request_id,
            hashes={"candidate": incoming},
        ),
    )
    return 0, f"received: {stored}"


@locked_scene
def inspect(
    work_root: Path,
    *,
    scene_id: str,
    run_id: str,
    observations_path: Path | None,
    marked_path: Path | None,
    repo_root: Path,
) -> tuple[int, str]:
    root = work_root_of(work_root)
    dest = run_dir(root, scene_id, run_id)
    request = load_model(dest / "request.yaml", RequestDocument)
    _assert_base_text_current(root, request)
    _assert_received_candidates_current(root, dest)
    inspect_path, normalized, inspect_sha = _resolve_inspect_edition(
        root, request, dest, marked_path
    )
    context, refreshed = _refresh_context_if_stale(root, dest, request)
    errors: list[ErrorItem] = []
    metron_status = ItemStatus.SKIPPED
    chronos_status = ItemStatus.SKIPPED
    text_state = ItemStatus.SKIPPED

    metron_notes: list[ReportFinding] = []
    if request.flags.metron is FlagValue.ON:
        metron_status, metro_errors, metron_notes = _inspect_metron(
            root, request, dest, inspect_path, repo_root
        )
        errors.extend(metro_errors)

    if request.flags.chronos is FlagValue.ON:
        try:
            store = load_store(root)
        except ChronosLoadError as error:
            raise BridgeError("UNKNOWN_REF", str(error)) from error
        _validated_run_links(dest, request, store)
        findings = check_store(store)
        if any(item.severity is ChronosSeverity.ERROR for item in findings):
            chronos_status = ItemStatus.FAILED
            errors.append(
                ErrorItem(
                    schema=SCHEMA,
                    code="UNKNOWN_REF",
                    severity=Severity.ERROR,
                    message="CHRONOS registered check has errors",
                    refs={"count": len(findings)},
                )
            )
        elif findings:
            chronos_status = ItemStatus.FINDINGS
        else:
            chronos_status = ItemStatus.SUCCESS
        observations = None
        source = observations_path or dest / "observations.json"
        if source.is_file():
            observations = load_json_model(source, ObservationsDocument)
        observed, c1_errors = inspect_observations(
            observations,
            request_id=request.request_id,
            normalized=normalized,
            text_sha=inspect_sha,
            context=context,
            store=store,
        )
        errors.extend(c1_errors)
        write_model(dest / "observations.json", observed, json_format=True)
        text_state = _text_state_status(observed, context, c1_errors)

    text_save = ItemStatus.SKIPPED
    publish_state = dest / "publish_state.json"
    if publish_state.is_file():
        from .publish import read_publish_state
        published = read_publish_state(publish_state)
        refs_path = dest / "artifact_refs.json"
        current_hash = None
        if refs_path.is_file():
            refs = load_json_model(refs_path, ArtifactRefsDocument)
            if refs.candidate is not None:
                current_hash = refs.candidate.raw_sha256
        published_edition = (
            published.status == "completed" or published.stage in {"inspect", "done"}
        ) and current_hash == published.candidate_hash
        inspected_raw = raw_sha256(inspect_path)
        if published_edition and inspected_raw == published.candidate_hash:
            text_save = ItemStatus.SUCCESS
            inspect_sha = published.intended_text_sha256
        elif published.status == "completed":
            text_save = ItemStatus.UNRESOLVED
            findings_extra = ReportFinding(
                code="STALE_EVIDENCE",
                note="inspect candidate is not the published edition; start a new run",
            )
            metron_notes = [*metron_notes, findings_extra]
    report = ReportDocument(
        schema=SCHEMA,
        request_id=request.request_id,
        run_id=request.run_id,
        target_text_sha256=inspect_sha,
        text_save=text_save,
        metron=metron_status,
        chronos_registered=chronos_status,
        text_state=text_state,
        findings=[
            *metron_notes,
            *[ReportFinding(code=item.code, note=item.message) for item in errors],
        ],
        open_issues=[item.model_dump(mode="json", by_alias=True) for item in errors],
    )
    repair_path = dest / "repair_state.json"
    if repair_path.is_file():
        from .repair import read_state
        from metron.repair_steps import history_summary
        repair = read_state(repair_path)
        report.repair_history = history_summary(repair.session)
    write_model(dest / "report.json", report, json_format=True)
    write_text(dest / "report.md", _render_report_md(report))
    if errors:
        write_model(dest / "errors.json", ErrorDocument.from_items(errors), json_format=True)
    append_journal(
        dest / "journal.jsonl",
        JournalEntry(
            schema=SCHEMA,
            at=now_iso(),
            action=JournalAction.INSPECT,
            run_id=request.run_id,
            request_id=request.request_id,
            note="context rebuilt: input_hashes changed" if refreshed else None,
        ),
    )
    if any(item.severity is Severity.ERROR for item in errors):
        return 1, f"inspect findings: {dest / 'report.json'}"
    return 0, f"inspected: {dest / 'report.json'}"


def status(work_root: Path, *, scene_id: str, run_id: str) -> tuple[int, str]:
    root = work_root_of(work_root)
    dest = run_dir(root, scene_id, run_id)
    if not dest.is_dir():
        raise BridgeError("UNKNOWN_REF", f"run not found: {dest}")
    lines = [f"run: {dest}"]
    report_path = dest / "report.json"
    if report_path.is_file():
        report = load_json_model(report_path, ReportDocument)
        lines.append(f"text_save: {report.text_save.value}")
        lines.append(f"metron: {report.metron.value}")
        lines.append(f"chronos_registered: {report.chronos_registered.value}")
        lines.append(f"text_state: {report.text_state.value}")
    journal = read_journal(dest / "journal.jsonl")
    if (dest / "repair_state.json").is_file():
        from .repair import read_state
        repair = read_state(dest / "repair_state.json")
        lines.append(f"repair: {repair.status}")
        lines.append(f"repair_attempts: {len(repair.session.history)}")
        if repair.session.pending:
            lines.append(f"pending_job: {repair.session.pending.job_id}")
    if (dest / "publish_state.json").is_file():
        from .publish import read_publish_state
        published = read_publish_state(dest / "publish_state.json")
        lines.append(f"publish: {published.status}")
        lines.append(f"publish_stage: {published.stage}")
    if journal:
        last = journal[-1]
        lines.append(f"last_action: {last.action.value} at {last.at}")
    return 0, "\n".join(lines)


def _inspect_metron(
    root: Path,
    request: RequestDocument,
    dest: Path,
    marked: Path,
    repo_root: Path,
) -> tuple[ItemStatus, list[ErrorItem], list[ReportFinding]]:
    metron = root / "_metron" / request.scene_id
    if not marked.is_file():
        raise BridgeError(
            "UNKNOWN_REF",
            "METRON is ON but no marked draft was received",
            refs={"path": str(marked)},
        )
    beats = load_beat_plan(metron / "beats.yaml")
    next_run = _next_metron_run(metron)
    result = analyze_marked_text(
        marked.read_text(encoding="utf-8"),
        beats,
        run=next_run,
        generator=GeneratorInfo(model=request.model.id, granularity="auto"),
    )
    inherited = _edition_finish_reason(root, dest, marked, result.metrics)
    if inherited:
        result.metrics.metrics.finish_reason = inherited
    result.metrics.metrics.source_raw_sha256 = raw_sha256(marked)
    result.metrics.metrics.source_text_sha256 = text_sha256(
        marked.read_text(encoding="utf-8")
    )
    atomic_write_text(metron / f"draft.{next_run:03d}.md", result.clean_text)
    atomic_write_model(metron / f"spans.{next_run:03d}.yaml", result.spans)
    atomic_write_model(metron / f"metrics.{next_run:03d}.yaml", result.metrics)
    atomic_write_model(
        metron / f"regression.{next_run:03d}.yaml",
        build_regression_observation(result.metrics, beats),
    )
    refs_path = dest / "artifact_refs.json"
    refs = (
        load_json_model(refs_path, ArtifactRefsDocument)
        if refs_path.is_file()
        else ArtifactRefsDocument(schema=SCHEMA, request_id=request.request_id, model=request.model)
    )
    refs.metron = refs.metron or {}
    for key, name in (
        ("metrics", f"metrics.{next_run:03d}.yaml"),
        ("spans", f"spans.{next_run:03d}.yaml"),
    ):
        path = metron / name
        refs.metron[key] = ArtifactRef(path=_rel(root, path), raw_sha256=raw_sha256(path))
    write_model(refs_path, refs, json_format=True)
    if not request.model.calibrated:
        return ItemStatus.FINDINGS, [], []
    try:
        calibration = load_model_calibration(
            repo_root / "config" / "metron_models.yaml",
            request.model.id,
        )
    except CalibrationNotReady:
        return (
            ItemStatus.FINDINGS,
            [],
            [ReportFinding(code="MODEL_UNCALIBRATED", note="V1 classify skipped; V0 metrics kept")],
        )
    classified = classify_metrics(result.metrics, beats, calibration, spans=result.spans)
    notes = [
        ReportFinding(code=finding.failure.value, note=finding.reason)
        for finding in classified.findings
    ]
    return ItemStatus.FINDINGS if classified.findings else ItemStatus.SUCCESS, [], notes


def _refuse_receive_after_publish(dest: Path) -> None:
    path = dest / "publish_state.json"
    if not path.is_file():
        return
    from .publish import read_publish_state
    state = read_publish_state(path)
    if state.status == "completed":
        raise BridgeError(
            "JOB_CONFLICT",
            "this run already published; start a new run",
        )
    raise BridgeError(
        "JOB_CONFLICT",
        "publish is in progress; finish it before receiving another candidate",
    )


def _assert_base_text_current(root: Path, request: RequestDocument) -> None:
    text_file = resolve_work_path(root, request.target.text_path)
    exists = text_file.is_file()
    if exists != request.target.base_exists:
        raise BridgeError(
            "STALE_EVIDENCE",
            "text file existence changed since prepare",
            refs={
                "path": request.target.text_path,
                "expected_exists": request.target.base_exists,
                "actual_exists": exists,
            },
            exit_code=1,
        )
    if not exists:
        return
    current_raw = raw_sha256(text_file)
    current_text = text_sha256(text_file.read_text(encoding="utf-8"))
    if (
        current_raw != request.target.base_raw_sha256
        or current_text != request.target.base_text_sha256
    ):
        raise BridgeError(
            "STALE_EVIDENCE",
            "base hash does not match current text",
            refs={
                "path": request.target.text_path,
                "expected": request.target.base_text_sha256,
                "actual": current_text,
            },
            exit_code=1,
        )


def _assert_received_candidates_current(root: Path, dest: Path) -> None:
    refs_path = dest / "artifact_refs.json"
    if not refs_path.is_file():
        return
    refs = load_json_model(refs_path, ArtifactRefsDocument)
    item = refs.candidate
    if item is None:
        return
    path = resolve_work_path(root, item.path)
    if not path.is_file():
        raise BridgeError(
            "STALE_EVIDENCE",
            "received candidate is missing; receive it again",
            refs={"path": item.path, "expected": item.raw_sha256},
            exit_code=1,
        )
    actual = raw_sha256(path)
    if actual != item.raw_sha256:
        raise BridgeError(
            "STALE_EVIDENCE",
            "received candidate changed; receive it again",
            refs={
                "path": item.path,
                "expected": item.raw_sha256,
                "actual": actual,
            },
            exit_code=1,
        )


def _resolve_inspect_edition(
    root: Path,
    request: RequestDocument,
    dest: Path,
    marked_path: Path | None,
) -> tuple[Path, str, str]:
    if marked_path is not None:
        if not marked_path.is_file():
            raise BridgeError(
                "UNKNOWN_REF",
                f"inspect target not found: {marked_path}",
                refs={"path": str(marked_path)},
            )
        _assert_marked_matches_received(dest, marked_path)
        path = marked_path
    else:
        path = _latest_candidate_path(root, dest)
        if path is None:
            novel = resolve_work_path(root, request.target.text_path)
            if novel.is_file():
                path = novel
            else:
                raise BridgeError(
                    "UNKNOWN_REF",
                    "no received candidate and text file is missing",
                    refs={"path": request.target.text_path},
                )
    body = path.read_text(encoding="utf-8")
    return path, read_normalized(path), text_sha256(body)


def _latest_candidate_path(root: Path, dest: Path) -> Path | None:
    refs_path = dest / "artifact_refs.json"
    if refs_path.is_file():
        refs = load_json_model(refs_path, ArtifactRefsDocument)
        if refs.candidate is not None:
            path = resolve_work_path(root, refs.candidate.path)
            if path.is_file():
                return path
    legacy = dest / "candidate.md"
    if legacy.is_file():
        return legacy
    return None


def _assert_marked_matches_received(dest: Path, marked: Path) -> None:
    refs_path = dest / "artifact_refs.json"
    if not refs_path.is_file():
        return
    refs = load_json_model(refs_path, ArtifactRefsDocument)
    if refs.candidate is None:
        return
    actual = raw_sha256(marked)
    if actual == refs.candidate.raw_sha256:
        return
    raise BridgeError(
        "STALE_EVIDENCE",
        "inspect --marked does not match the received candidate",
        refs={
            "path": str(marked),
            "expected": refs.candidate.raw_sha256,
            "actual": actual,
        },
        exit_code=1,
    )


def _input_rel_paths(root: Path, request: RequestDocument) -> list[str]:
    extra: list[str] = []
    text_file = resolve_work_path(root, request.target.text_path)
    if text_file.is_file():
        extra.append(request.target.text_path)
    if request.flags.metron is FlagValue.ON:
        extra.extend(
            [
                f"_metron/{request.scene_id}/contract.yaml",
                f"_metron/{request.scene_id}/beats.yaml",
            ]
        )
    if request.flags.chronos is FlagValue.ON:
        extra.append("chronos/chronos.config.yaml")
        extra.extend(
            [
                "chronos/entities/characters.yaml",
                "chronos/entities/locations.yaml",
                "chronos/scenes.yaml",
            ]
        )
        entities = root / "chronos" / "entities"
        if entities.is_dir():
            extra.extend(
                path.relative_to(root).as_posix()
                for path in sorted(entities.glob("**/*.yaml"))
            )
        events = root / "chronos" / "events"
        if events.is_dir():
            extra.extend(
                path.relative_to(root).as_posix()
                for path in sorted(events.glob("**/*.yaml"))
            )
        extra.append(
            f"_writing/{request.scene_id}/{request.run_id}/links.yaml"
        )
    return _unique_paths(extra)


def _unique_paths(paths: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for path in paths:
        if path in seen:
            continue
        seen.add(path)
        ordered.append(path)
    return ordered


def _refresh_context_if_stale(
    root: Path,
    dest: Path,
    request: RequestDocument,
) -> tuple[ContextDocument, bool]:
    context = load_json_model(dest / "context.json", ContextDocument)
    extra = _input_rel_paths(root, request)
    current = collect_input_hashes(root, extra)
    recorded = {(item.path, item.raw_sha256) for item in context.input_hashes}
    actual = {(item.path, item.raw_sha256) for item in current}
    if recorded == actual:
        return context, False
    store = None
    links = None
    if request.flags.chronos is FlagValue.ON:
        try:
            store = load_store(root)
        except ChronosLoadError as error:
            raise BridgeError("UNKNOWN_REF", str(error)) from error
        links = _validated_run_links(dest, request, store)
    metron_dir = (
        root / "_metron" / request.scene_id
        if request.flags.metron is FlagValue.ON
        else None
    )
    context = build_context(
        root,
        request,
        store=store,
        links=links,
        metron_root=metron_dir,
        extra_hashes=extra,
    )
    write_model(dest / "context.json", context, json_format=True)
    write_text(dest / "context.md", render_context_md(context))
    return context, True


def _text_state_status(
    observed: ObservationsDocument,
    context: ContextDocument,
    c1_errors: list[ErrorItem],
) -> ItemStatus:
    if any(item.code in {"RANGE_MISMATCH", "UNKNOWN_REF"} for item in c1_errors):
        return ItemStatus.FAILED
    if any(item.code == "TEXT_STATE_MISMATCH" for item in c1_errors):
        return ItemStatus.FAILED
    if any(item.code == "TEXT_STATE_UNVERIFIED" for item in c1_errors):
        return ItemStatus.UNRESOLVED
    if observed.expected_total == 0:
        return ItemStatus.SKIPPED
    expected_keys = {
        (item.event_id, item.actor_id, item.dimension, item.state_at.value)
        for item in context.expected_checks
    }
    matches = [
        item
        for item in observed.items
        if item.confirmation is Confirmation.MATCH
        and (
            item.event_id,
            item.actor_id,
            item.dimension,
            item.state_at.value,
        )
        in expected_keys
    ]
    return (
        ItemStatus.SUCCESS
        if len(matches) == observed.expected_total
        else ItemStatus.UNRESOLVED
    )


def _apply_generation(
    refs: ArtifactRefsDocument,
    candidate_hash: str,
    finish_reason: str | None,
    model_id: str,
) -> None:
    if finish_reason:
        refs.generation = GenerationProvenance(
            candidate_raw_sha256=candidate_hash,
            finish_reason=finish_reason,
            model_id=model_id,
        )
        return
    if refs.generation is not None and refs.generation.candidate_raw_sha256 != candidate_hash:
        refs.generation = None


def _edition_finish_reason(
    root: Path,
    dest: Path,
    source: Path,
    measured: MetricsDocument | None = None,
) -> str | None:
    del measured
    refs_path = dest / "artifact_refs.json"
    if not refs_path.is_file():
        return None
    refs = load_json_model(refs_path, ArtifactRefsDocument)
    source_hash = raw_sha256(source)
    source_text = text_sha256(source.read_text(encoding="utf-8"))
    if refs.candidate is None or refs.candidate.raw_sha256 != source_hash:
        return None
    if (
        refs.generation is not None
        and refs.generation.candidate_raw_sha256 == source_hash
        and refs.generation.finish_reason
    ):
        return refs.generation.finish_reason
    metrics_ref = (refs.metron or {}).get("metrics")
    if metrics_ref is None:
        return None
    path = resolve_work_path(root, metrics_ref.path)
    if not path.is_file() or raw_sha256(path) != metrics_ref.raw_sha256:
        return None
    stored = load_metron_model(path, MetricsDocument)
    if stored.metrics.source_raw_sha256 != source_hash:
        return None
    if (
        stored.metrics.source_text_sha256
        and stored.metrics.source_text_sha256 != source_text
    ):
        return None
    return stored.metrics.finish_reason


def _remember_metron_sources(
    root: Path,
    request: RequestDocument,
    refs: ArtifactRefsDocument,
    *,
    marked: ArtifactRef,
) -> None:
    if request.flags.metron is not FlagValue.ON:
        return
    metron = root / "_metron" / request.scene_id
    refs.metron = refs.metron or {}
    previous = refs.metron.get("marked")
    refs.metron["marked"] = marked
    if previous is None or previous.raw_sha256 != marked.raw_sha256:
        refs.metron.pop("metrics", None)
        refs.metron.pop("spans", None)
    for key, name in (("contract", "contract.yaml"), ("beats", "beats.yaml")):
        path = metron / name
        if path.is_file():
            refs.metron[key] = ArtifactRef(
                path=_rel(root, path),
                raw_sha256=raw_sha256(path),
            )


def _next_versioned_path(directory: Path, prefix: str, suffix: str) -> Path:
    numbers: list[int] = []
    for path in directory.glob(f"{prefix}.*{suffix}"):
        mid = path.name.removeprefix(f"{prefix}.").removesuffix(suffix)
        if mid.isdigit():
            numbers.append(int(mid))
    return directory / f"{prefix}.{next_index(numbers):03d}{suffix}"


def _validated_run_links(
    dest: Path,
    request: RequestDocument,
    store: ChronosStore,
) -> LinksDocument | None:
    if request.flags.chronos is not FlagValue.ON:
        return None
    links_path = dest / "links.yaml"
    if not links_path.is_file():
        return None
    links = load_model(links_path, LinksDocument)
    raise_if_errors(
        validate_links(
            links,
            store,
            scene_id=request.scene_id,
            metron_on=request.flags.metron is FlagValue.ON,
        )
    )
    return links


def _edition_intact(root: Path, item: ArtifactRef, incoming: str) -> bool:
    if item.raw_sha256 != incoming:
        return False
    path = resolve_work_path(root, item.path)
    return path.is_file() and raw_sha256(path) == incoming


def _next_metron_run(metron: Path) -> int:
    numbers: list[int] = []
    for path in metron.glob("metrics.*.yaml"):
        part = path.name.removeprefix("metrics.").removesuffix(".yaml")
        if part.isdigit():
            numbers.append(int(part))
    return next_index(numbers)


def _validate_selector(normalized: str, selector: Selector) -> None:
    if selector.kind is SelectorKind.OFFSET:
        if not re.fullmatch(r"\d+:\d+", selector.value):
            raise BridgeError("BAD_ID", "offset selector must be start:end")
        start, end = (int(part) for part in selector.value.split(":"))
        if not 0 <= start <= end <= len(normalized):
            raise BridgeError(
                "STALE_EVIDENCE",
                "offset selector is outside the current text",
                refs={"start": start, "end": end, "length": len(normalized)},
            )
        return
    if selector.kind is SelectorKind.HEADING and selector.value not in normalized:
        raise BridgeError(
            "UNKNOWN_REF",
            "selector heading was not found in the text",
            refs={"value": selector.value},
        )
    if selector.kind is SelectorKind.HTML_COMMENT and selector.value not in normalized:
        raise BridgeError(
            "UNKNOWN_REF",
            "selector comment was not found in the text",
            refs={"value": selector.value},
        )


def _rel(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _render_report_md(report: ReportDocument) -> str:
    return (
        f"# report {report.run_id}\n\n"
        f"- 本文保存: {report.text_save.value}\n"
        f"- METRON計測・判定: {report.metron.value}\n"
        f"- CHRONOS登録データ検査: {report.chronos_registered.value}\n"
        f"- 本文状態照合: {report.text_state.value}\n"
    )
