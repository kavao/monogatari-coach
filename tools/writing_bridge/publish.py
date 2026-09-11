"""Adopt a received candidate into `_novel_text`. Does not call a provider."""
from __future__ import annotations

from hashlib import sha256
import re
import shutil
import sys
from pathlib import Path
from typing import Literal

from metron.repair import normalize_novel_body, strip_generation_markers
from metron.repair_steps import StepModel
from metron.storage import atomic_write_text

from . import commands as commands
from .errors import BridgeError
from .hashes import EMPTY_RAW_SHA256, format_sha256, normalize_body, raw_sha256, text_sha256
from .locking import locked_scene
from .models import (
    ArtifactRefsDocument,
    FlagValue,
    ItemStatus,
    JournalAction,
    JournalEntry,
    LinksDocument,
    ReportDocument,
    ReportFinding,
    RequestDocument,
    RequestKind,
    Selector,
    SelectorKind,
)
from .paths import resolve_work_path
from .repair import read_state
from .storage import append_journal, load_json_model, load_model, next_index, now_iso, write_model, write_text

_TOOLS = Path(__file__).resolve().parents[1]
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

from novel_char_count import count_chars  # noqa: E402
from novel_punctuation_metrics import evaluate_gate, measure_text  # noqa: E402

_SCENE_ANCHOR = re.compile(
    r"(?m)^[ \t]*<!--\s*scene:\s*(ch\d{2,}-\d{3,})\s*-->[ \t]*(?:\n|$)"
)
_HEADING = re.compile(r"(?m)^(#{1,6})[ \t]+.+$")
_OFFSET = re.compile(r"^(\d+):(\d+)$")
_BEAT_LEFT = re.compile(r"<!--/?beat:|<!--fact:")


class BridgePublish(StepModel):
    version: Literal[1] = 1
    status: Literal["active", "completed"] = "active"
    stage: Literal["backup", "write", "inspect", "done"] = "backup"
    authorization: str
    candidate_path: str
    candidate_hash: str
    published_path: str
    intended_raw_sha256: str
    intended_text_sha256: str
    original_raw_sha256: str
    original_exists: bool
    backup_path: str | None = None
    prefix: str = ""
    suffix: str = ""
    adopted_marked_path: str | None = None
    char_count: int | None = None
    punctuation_status: str | None = None
    punctuation_note: str | None = None


def read_publish_state(path: Path) -> BridgePublish:
    try:
        return BridgePublish.model_validate_json(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as error:
        raise BridgeError("SCHEMA_UNSUPPORTED", f"invalid publish state: {error}") from error


def _save(dest: Path, state: BridgePublish) -> None:
    atomic_write_text(dest / "publish_state.json", state.model_dump_json(indent=2) + "\n")


def _paths(work_root, scene_id, run_id):
    if not re.fullmatch(r"run-\d{4,}", run_id):
        raise BridgeError("BAD_ID", "invalid run_id")
    root = commands.work_root_of(work_root)
    dest = resolve_work_path(root, f"_writing/{scene_id}/{run_id}")
    request = load_model(dest / "request.yaml", RequestDocument)
    if request.scene_id != scene_id or request.run_id != run_id:
        raise BridgeError("JOB_CONFLICT", "request does not match run")
    return root, dest, request


def _journal(dest, request, note=None, hashes=None):
    append_journal(
        dest / "journal.jsonl",
        JournalEntry(
            schema=1,
            at=now_iso(),
            action=JournalAction.PUBLISH,
            run_id=request.run_id,
            request_id=request.request_id,
            hashes=hashes,
            note=note,
        ),
    )


def _lf(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _clean_scene_body(marked: str) -> str:
    """マーカーを除き、Beat境界に残った連続空行を段落1つ分へ畳む。"""

    body = normalize_body(strip_generation_markers(marked))
    if _BEAT_LEFT.search(body):
        raise BridgeError("JOB_CONFLICT", "published body still contains Beat/fact markers")
    return normalize_novel_body(body)


def scene_anchor_span(text: str, scene_id: str) -> tuple[int, int] | None:
    matches = list(_SCENE_ANCHOR.finditer(text))
    for index, match in enumerate(matches):
        if match.group(1) != scene_id:
            continue
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        return start, end
    return None


def _scene_anchor_span(text: str, scene_id: str) -> tuple[int, int] | None:
    return scene_anchor_span(text, scene_id)


def _heading_span(text: str, value: str) -> tuple[int, int]:
    headings = list(_HEADING.finditer(text))
    chosen = next((item for item in headings if value in item.group(0)), None)
    if chosen is None:
        index = text.find(value)
        if index < 0:
            raise BridgeError("UNKNOWN_REF", "selector heading was not found in the text")
        return index, len(text)
    level = len(chosen.group(1))
    start = chosen.start()
    end = len(text)
    for later in headings:
        if later.start() <= start:
            continue
        if len(later.group(1)) <= level:
            end = later.start()
            break
    return start, end


def _comment_span(text: str, value: str) -> tuple[int, int]:
    start = text.find(value)
    if start < 0:
        raise BridgeError("UNKNOWN_REF", "selector comment was not found in the text")
    if text.find(value, start + len(value)) >= 0:
        raise BridgeError("UNKNOWN_REF", "selector comment is not unique", refs={"value": value})
    scene = _SCENE_ANCHOR.search(value)
    if scene:
        span = _scene_anchor_span(text, scene.group(1))
        if span is not None:
            return span
    return start, len(text)


def _offset_span(text: str, value: str) -> tuple[int, int]:
    match = _OFFSET.fullmatch(value)
    if match is None:
        raise BridgeError("BAD_ID", "offset selector must be start:end")
    start, end = int(match.group(1)), int(match.group(2))
    if not 0 <= start <= end <= len(text):
        raise BridgeError(
            "STALE_EVIDENCE",
            "offset selector is outside the current text",
            refs={"start": start, "end": end, "length": len(text)},
        )
    return start, end


def replacement_span(
    text: str,
    *,
    scene_id: str,
    selector: Selector | None,
    request_kind: RequestKind,
) -> tuple[int, int]:
    if request_kind is RequestKind.APPEND:
        return len(text), len(text)
    anchored = scene_anchor_span(text, scene_id)
    if anchored is not None:
        return anchored
    if selector is None:
        if text.strip():
            raise BridgeError(
                "MISSING_FIELD",
                "existing text requires a selector, scene anchor, or append",
            )
        return 0, len(text)
    if selector.kind is SelectorKind.OFFSET:
        return _offset_span(text, selector.value)
    if selector.kind is SelectorKind.HEADING:
        return _heading_span(text, selector.value)
    return _comment_span(text, selector.value)


def compose_published(
    current: str,
    scene_body: str,
    *,
    scene_id: str,
    selector: Selector | None,
    request_kind: RequestKind,
) -> tuple[str, str, str]:
    start, end = replacement_span(
        current, scene_id=scene_id, selector=selector, request_kind=request_kind
    )
    prefix, suffix = current[:start], current[end:]
    body = scene_body
    if request_kind is RequestKind.APPEND and prefix and not prefix.endswith("\n"):
        body = "\n" + body
    composed = prefix + body + suffix
    if composed and not composed.endswith("\n"):
        composed += "\n"
    return composed, prefix, suffix


def _assemble(state: BridgePublish, scene_body: str, request_kind: RequestKind) -> str:
    body = scene_body
    if request_kind is RequestKind.APPEND and state.prefix and not state.prefix.endswith("\n"):
        body = "\n" + scene_body
    composed = state.prefix + body + state.suffix
    if composed and not composed.endswith("\n"):
        composed += "\n"
    return composed


def _next_backup_path(directory: Path, name: str) -> Path:
    stem = Path(name).stem
    suffix = Path(name).suffix
    numbers: list[int] = []
    for path in directory.glob(f"{stem}_v*{suffix}"):
        mid = path.name.removeprefix(f"{stem}_v").removesuffix(suffix)
        if mid.isdigit():
            numbers.append(int(mid))
    return directory / f"{stem}_v{next_index(numbers):03d}{suffix}"


def _candidate(root: Path, dest: Path) -> Path:
    refs_path = dest / "artifact_refs.json"
    if not refs_path.is_file():
        raise BridgeError("UNKNOWN_REF", "no received candidate to publish")
    refs = load_json_model(refs_path, ArtifactRefsDocument)
    if refs.candidate is None:
        raise BridgeError("UNKNOWN_REF", "no received candidate to publish")
    path = resolve_work_path(root, refs.candidate.path)
    if not path.is_file() or raw_sha256(path) != refs.candidate.raw_sha256:
        raise BridgeError("STALE_EVIDENCE", "received candidate changed; receive it again")
    return path


def _assert_canonical_for_write(state: BridgePublish, text_file: Path) -> None:
    exists = text_file.is_file()
    if state.original_exists and not exists:
        raise BridgeError(
            "STALE_EVIDENCE",
            "canonical text was deleted during publish",
            refs={"path": state.published_path},
        )
    if not exists:
        return
    current_raw = raw_sha256(text_file)
    if current_raw == state.intended_raw_sha256:
        return
    if not state.original_exists:
        raise BridgeError(
            "STALE_EVIDENCE",
            "canonical text was created during publish",
            refs={"path": state.published_path},
        )
    if current_raw != state.original_raw_sha256:
        raise BridgeError(
            "STALE_EVIDENCE",
            "canonical text changed during publish",
            refs={
                "path": state.published_path,
                "expected": state.original_raw_sha256,
                "actual": current_raw,
            },
        )


def _refuse_active_repair(dest: Path) -> None:
    path = dest / "repair_state.json"
    if not path.is_file():
        return
    if read_state(path).status == "active":
        raise BridgeError("JOB_CONFLICT", "finish or abandon the active repair before publish")


def _update_request_hashes(dest: Path, request: RequestDocument, text_file: Path) -> RequestDocument:
    request.target.base_exists = True
    request.target.base_raw_sha256 = raw_sha256(text_file)
    request.target.base_text_sha256 = text_sha256(text_file.read_text(encoding="utf-8"))
    write_model(dest / "request.yaml", request)
    links_path = dest / "links.yaml"
    if links_path.is_file():
        links = load_model(links_path, LinksDocument)
        links.text_sha256 = request.target.base_text_sha256
        write_model(links_path, links)
    return request


def _record_counts(state: BridgePublish, published: str) -> None:
    state.char_count = count_chars(published, strip_fm=True)
    gate = evaluate_gate(measure_text(published))
    state.punctuation_status = gate["status"]
    state.punctuation_note = gate["reason"]


def _c1_ready(report: ReportDocument) -> bool:
    return report.text_state in {ItemStatus.SUCCESS, ItemStatus.SKIPPED}


def _c1_refusal_code(report: ReportDocument) -> str:
    for item in report.findings:
        if item.code in {
            "TEXT_STATE_UNVERIFIED",
            "TEXT_STATE_MISMATCH",
            "RANGE_MISMATCH",
            "UNKNOWN_REF",
        }:
            return item.code
    return "TEXT_STATE_UNVERIFIED"


def _refuse_if_c1_not_ready(
    root: Path,
    dest: Path,
    request: RequestDocument,
    repo_root: Path,
    observations_path: Path | None,
    marked: Path,
) -> None:
    if request.flags.chronos is not FlagValue.ON:
        return
    commands.inspect(
        root,
        scene_id=request.scene_id,
        run_id=request.run_id,
        observations_path=observations_path,
        marked_path=marked,
        repo_root=repo_root,
    )
    report = load_json_model(dest / "report.json", ReportDocument)
    if _c1_ready(report):
        return
    raise BridgeError(
        _c1_refusal_code(report),
        "C1 must succeed before publish",
        refs={"text_state": report.text_state.value},
    )


def _follow_inspect(
    root: Path,
    dest: Path,
    request: RequestDocument,
    repo_root: Path,
    observations_path: Path | None,
    marked: Path,
    state: BridgePublish,
) -> tuple[int, str]:
    code, message = commands.inspect(
        root,
        scene_id=request.scene_id,
        run_id=request.run_id,
        observations_path=observations_path,
        marked_path=marked,
        repo_root=repo_root,
    )
    report_path = dest / "report.json"
    report = load_json_model(report_path, ReportDocument)
    published = resolve_work_path(root, request.target.text_path)
    published_sha = text_sha256(published.read_text(encoding="utf-8"))
    report.target_text_sha256 = published_sha
    if _c1_ready(report):
        report.text_save = ItemStatus.SUCCESS
    else:
        report.text_save = ItemStatus.UNRESOLVED
    findings = list(report.findings)
    if text_sha256(marked.read_text(encoding="utf-8")) != published_sha:
        findings.append(
            ReportFinding(
                code=None,
                note="C1/METRON measured the adopted scene edition; target_text_sha256 is the saved file",
            )
        )
    findings.append(
        ReportFinding(code=None, note="story_sync skipped; run novel-story-reflection after publish")
    )
    if state.char_count is not None:
        findings.append(ReportFinding(code=None, note=f"char_count={state.char_count}"))
    if state.punctuation_status:
        findings.append(
            ReportFinding(
                code=None,
                note=f"punctuation_gate={state.punctuation_status}: {state.punctuation_note}",
            )
        )
    report.findings = findings
    write_model(report_path, report, json_format=True)
    write_text(dest / "report.md", commands._render_report_md(report))
    return code, message


def _plan_state(
    root: Path,
    request: RequestDocument,
    text_file: Path,
    candidate: Path,
    scene_body: str,
    authorization: str,
) -> BridgePublish:
    commands._assert_base_text_current(root, request)
    current = _lf(text_file.read_text(encoding="utf-8")) if text_file.is_file() else ""
    composed, prefix, suffix = compose_published(
        current,
        scene_body,
        scene_id=request.scene_id,
        selector=request.target.selector,
        request_kind=request.request_kind,
    )
    return BridgePublish(
        authorization=authorization.strip(),
        candidate_path=candidate.relative_to(root).as_posix(),
        candidate_hash=raw_sha256(candidate),
        published_path=request.target.text_path,
        intended_raw_sha256=format_sha256(sha256(composed.encode("utf-8")).digest()),
        intended_text_sha256=text_sha256(composed),
        original_raw_sha256=raw_sha256(text_file) if text_file.is_file() else EMPTY_RAW_SHA256,
        original_exists=text_file.is_file(),
        prefix=prefix,
        suffix=suffix,
    )


@locked_scene
def publish(
    work_root: Path,
    *,
    scene_id: str,
    run_id: str,
    authorization: str,
    repo_root: Path,
    observations_path: Path | None = None,
    dry_run: bool = False,
) -> tuple[int, str]:
    root, dest, request = _paths(work_root, scene_id, run_id)
    if not authorization.strip():
        raise BridgeError("MISSING_FIELD", "record the user's publish authorization source")
    if not request.permissions.publish:
        raise BridgeError("PERMISSION_DENIED", "this run was prepared without publish permission")
    _refuse_active_repair(dest)
    commands._assert_received_candidates_current(root, dest)
    candidate = _candidate(root, dest)
    scene_body = _clean_scene_body(candidate.read_text(encoding="utf-8"))
    text_file = resolve_work_path(root, request.target.text_path)
    state_path = dest / "publish_state.json"

    if state_path.is_file():
        state = read_publish_state(state_path)
        if authorization != state.authorization:
            raise BridgeError("JOB_CONFLICT", "publish already began with different authorization")
        if state.candidate_hash != raw_sha256(candidate):
            raise BridgeError("STALE_EVIDENCE", "publish candidate changed; start a new run")
        if state.status == "completed":
            if not text_file.is_file() or raw_sha256(text_file) != state.intended_raw_sha256:
                raise BridgeError("STALE_EVIDENCE", "published text changed after save")
            return 0, f"already published: {text_file}"
    else:
        state = _plan_state(root, request, text_file, candidate, scene_body, authorization)
        if dry_run:
            return 0, f"would publish: {text_file}"
        _save(dest, state)
        _journal(dest, request, note="publish begun", hashes={"candidate": state.candidate_hash})

    if dry_run:
        return 0, f"would publish: {text_file}"

    composed = _assemble(state, scene_body, request.request_kind)

    if state.stage in {"backup", "write"} and state.status != "completed":
        _refuse_if_c1_not_ready(root, dest, request, repo_root, observations_path, candidate)
        _assert_canonical_for_write(state, text_file)
        if text_file.is_file() and state.stage == "backup":
            now = _lf(text_file.read_text(encoding="utf-8"))
            if raw_sha256(text_file) == state.original_raw_sha256:
                start = len(state.prefix)
                end = len(now) - len(state.suffix) if state.suffix else len(now)
                if request.request_kind is RequestKind.APPEND:
                    start = end = len(now)
                if now[:start] != state.prefix or now[end:] != state.suffix:
                    raise BridgeError("STALE_EVIDENCE", "text outside the target scene changed")
        if state.original_exists and state.stage == "backup":
            backup_dir = root / "_novel_text_backup"
            backup_dir.mkdir(parents=True, exist_ok=True)
            if state.backup_path:
                backup = resolve_work_path(root, state.backup_path)
            else:
                backup = _next_backup_path(backup_dir, Path(request.target.text_path).name)
                shutil.copyfile(text_file, backup)
                state.backup_path = backup.relative_to(root).as_posix()
            if raw_sha256(backup) != state.original_raw_sha256:
                raise BridgeError("JOB_CONFLICT", "publish backup was modified")
            state.stage = "backup"
            _save(dest, state)
            _journal(dest, request, note="backup written", hashes={"backup": raw_sha256(backup)})
        elif not state.original_exists:
            state.stage = "backup"
            _save(dest, state)

        _assert_canonical_for_write(state, text_file)
        current_raw = raw_sha256(text_file) if text_file.is_file() else None
        if current_raw == state.intended_raw_sha256:
            state.stage = "write"
        else:
            text_file.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_text(text_file, composed)
            if raw_sha256(text_file) != state.intended_raw_sha256:
                raise BridgeError("JOB_CONFLICT", "published bytes do not match the intended edition")
            state.stage = "write"
        metron = root / "_metron" / request.scene_id
        metron.mkdir(parents=True, exist_ok=True)
        adopted = metron / f"adopted.{request.run_id}.md"
        marked_text = candidate.read_text(encoding="utf-8")
        if adopted.exists() and adopted.read_text(encoding="utf-8") != marked_text:
            raise BridgeError("JOB_CONFLICT", "adopted marked snapshot was modified")
        if not adopted.exists():
            atomic_write_text(adopted, marked_text)
        state.adopted_marked_path = adopted.relative_to(root).as_posix()
        atomic_write_text(dest / "published.md", scene_body)
        _record_counts(state, text_file.read_text(encoding="utf-8"))
        request = _update_request_hashes(dest, request, text_file)
        state.stage = "inspect"
        _save(dest, state)
        _journal(dest, request, note="canonical text written", hashes={"published": state.intended_raw_sha256})

    if state.stage == "inspect":
        commands._assert_base_text_current(root, request)
        now = _lf(text_file.read_text(encoding="utf-8"))
        if not now.startswith(state.prefix) or (state.suffix and not now.endswith(state.suffix)):
            raise BridgeError("STALE_EVIDENCE", "text outside the target scene changed after save")
        code, message = _follow_inspect(
            root, dest, request, repo_root, observations_path, candidate, state
        )
        report = load_json_model(dest / "report.json", ReportDocument)
        if not _c1_ready(report):
            return 1, f"canonical text written; C1 incomplete: {text_file}; {message}"
        state.status = "completed"
        state.stage = "done"
        _save(dest, state)
        _journal(dest, request, note="publish completed", hashes={"published": state.intended_text_sha256})
        if state.punctuation_status == "fail":
            return 1, f"published with punctuation findings: {text_file}; {message}"
        return code, f"published: {text_file}; {message}"

    raise BridgeError("JOB_CONFLICT", f"unknown publish stage: {state.stage}")
