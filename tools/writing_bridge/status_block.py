"""章末ステータスのブロックだけを更新する run（`prepare --request-kind status_block`）の保存。

正本は `.rulesync/rules/workflow-specification.md`「章末ステータスの表示（CHAPTER_STATUS）」。
ブロックは Beat ではないので METRON の検査（床・Beat の対応）は通さず、保存と記録だけを行う。
計測していない本文の変更をこの run で計測済みにしないよう、次の二つを満たさなければ保存しない。

1. 保存前の全文（writing_bridge と同じ正規化のハッシュ）が、その章の run がすでに計測したハッシュの
   どれかと一致する（`novel_project_check._measured_text_hashes`）。
2. 保存前と保存後で、ブロックの外の本文が一字も変わらない。

また、初回の保存では版を照合する。正本が prepare の時点（`target.base_raw_sha256`）のままで、
作業用の candidate.md が receive で記録した候補（`artifact_refs.json`）と同じでなければ保存しない。
古い run が新しい更新を上書きすること、receive の後に書き換えた候補を保存することを防ぐ。

保存後は `report.json` に保存後のハッシュを書くので、`novel_project_check --check-inspection-layers` の
計測済みの判定はそのまま通る（判定の側は変えない）。候補（candidate.md）がブロックの中身で、
空白だけの候補はブロックを外す。
"""
from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

from metron.storage import atomic_write_text

from .errors import BridgeError
from .hashes import raw_sha256, text_sha256
from .models import (
    ArtifactRefsDocument,
    ItemStatus,
    JournalAction,
    JournalEntry,
    ReportDocument,
    RequestDocument,
    RequestKind,
)
from .paths import resolve_work_path
from .storage import append_journal, load_json_model, load_model, now_iso, write_model, write_text

_TOOLS = Path(__file__).resolve().parents[1]
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

import chapter_status as cs  # noqa: E402

SCHEMA = 1
STATE_NAME = "status_block_state.json"
_CHAPTER_RE = re.compile(r"^ch(\d{2,})-\d+$")
_FORBIDDEN = re.compile(r"<!--\s*(?:/?beat:|fact:|status:)")


def _lf(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def chapter_of(scene_id: str) -> int:
    match = _CHAPTER_RE.match(scene_id)
    if not match:
        raise BridgeError("BAD_ID", f"status_block needs a scene id like ch03-004: {scene_id}")
    return int(match.group(1))


def _measured_hashes(root: Path, chapter: int, text_rel: str) -> set[str]:
    from novel_project_check import _measured_text_hashes

    measured = _measured_text_hashes(root, chapter)
    return set(measured["hashes"].get(text_rel.replace("\\", "/"), set()))


def _content(candidate: Path) -> str | None:
    raw = _lf(candidate.read_text(encoding="utf-8"))
    if _FORBIDDEN.search(raw):
        raise BridgeError(
            "JOB_CONFLICT",
            "status_block candidate must be the block content only (no beat/fact/status markers)",
        )
    return raw if raw.strip() else None


def _verify_received(root: Path, dest: Path, candidate: Path) -> None:
    """作業用の candidate.md が、receive で記録した候補（artifact_refs.json）と同じであること。"""

    refs_path = dest / "artifact_refs.json"
    if not refs_path.is_file():
        raise BridgeError("UNKNOWN_REF", "receive the block content before publish")
    refs = load_json_model(refs_path, ArtifactRefsDocument)
    if refs.candidate is None:
        raise BridgeError("UNKNOWN_REF", "receive the block content before publish")
    recorded = refs.candidate.raw_sha256
    stored = resolve_work_path(root, refs.candidate.path)
    if raw_sha256(candidate) != recorded or not stored.is_file() or raw_sha256(stored) != recorded:
        raise BridgeError(
            "STALE_EVIDENCE",
            "candidate.md differs from the received candidate; receive it again",
        )


def compose(current: str, content: str | None) -> str:
    """ブロックを置き換えた全文。ブロックの外が変わらないことを確かめる。"""

    try:
        composed = cs.replace_block(current, content)
    except ValueError as error:
        raise BridgeError("JOB_CONFLICT", f"cannot place the status block: {error}") from error
    before = cs.split_body_and_tail(current)[0].rstrip("\n")
    after = cs.split_body_and_tail(composed)[0].rstrip("\n")
    if before != after:
        raise BridgeError("STALE_EVIDENCE", "status_block would change text outside the block")
    return composed


def _next_backup(root: Path, name: str) -> Path:
    directory = root / "_novel_text_backup"
    directory.mkdir(parents=True, exist_ok=True)
    stem, suffix = Path(name).stem, Path(name).suffix
    numbers = [
        int(mid)
        for path in directory.glob(f"{stem}_v*{suffix}")
        if (mid := path.name.removeprefix(f"{stem}_v").removesuffix(suffix)).isdigit()
    ]
    return directory / f"{stem}_v{(max(numbers) + 1 if numbers else 1):03d}{suffix}"


def _read_state(dest: Path) -> dict[str, object] | None:
    path = dest / STATE_NAME
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _save_state(dest: Path, state: dict[str, object]) -> None:
    atomic_write_text(dest / STATE_NAME, json.dumps(state, ensure_ascii=False, indent=2) + "\n")


def _write_report(dest: Path, request: RequestDocument, composed: str) -> None:
    report = ReportDocument.model_validate(
        {
            "schema": SCHEMA,
            "request_id": request.request_id,
            "run_id": request.run_id,
            "target_text_sha256": text_sha256(composed),
            "text_save": ItemStatus.SUCCESS,
            "metron": ItemStatus.SKIPPED,
            "chronos_registered": ItemStatus.SKIPPED,
            "text_state": ItemStatus.SUCCESS,
            "next_action": None,
        }
    )
    write_model(dest / "report.json", report, json_format=True)
    write_text(
        dest / "report.md",
        "# status_block\n\n"
        f"- run: {request.run_id}\n"
        f"- target: {request.target.text_path}\n"
        "- METRON: skipped（章末ステータスのブロックだけを更新。ブロックの外は保存前と同じ）\n",
    )


def publish_status_block(
    root: Path,
    dest: Path,
    request: RequestDocument,
    *,
    authorization: str,
    dry_run: bool = False,
) -> tuple[int, str]:
    if request.request_kind is not RequestKind.STATUS_BLOCK:
        raise BridgeError("JOB_CONFLICT", "not a status_block run")
    candidate = dest / "candidate.md"
    if not candidate.is_file():
        raise BridgeError("UNKNOWN_REF", "receive the block content before publish")
    content = _content(candidate)
    text_file = resolve_work_path(root, request.target.text_path)
    if not text_file.is_file():
        raise BridgeError("UNKNOWN_REF", f"text file not found: {request.target.text_path}")
    current = _lf(text_file.read_text(encoding="utf-8"))
    state = _read_state(dest)

    if state is not None:
        if state.get("authorization") != authorization.strip():
            raise BridgeError("JOB_CONFLICT", "publish already began with different authorization")
        if state.get("candidate_hash") != raw_sha256(candidate):
            raise BridgeError("STALE_EVIDENCE", "status_block candidate changed; start a new run")
        if raw_sha256(text_file) == state["intended_raw_sha256"]:
            composed = current
            if state.get("status") == "completed":
                return 0, f"already published: {text_file}"
        elif raw_sha256(text_file) == state["original_raw_sha256"]:
            composed = compose(current, content)
        else:
            raise BridgeError("STALE_EVIDENCE", "text changed after status_block publish began")
    else:
        # 版の照合：prepare の時点の正本と、receive で記録した候補のままであること。
        if raw_sha256(text_file) != request.target.base_raw_sha256:
            raise BridgeError(
                "STALE_EVIDENCE",
                "the text changed after this status_block run was prepared; start a new run",
                refs={"path": request.target.text_path},
            )
        _verify_received(root, dest, candidate)
        chapter = chapter_of(request.scene_id)
        if text_sha256(current) not in _measured_hashes(root, chapter, request.target.text_path):
            raise BridgeError(
                "STALE_EVIDENCE",
                "the current text is not measured; measure the chapter before updating the status block",
                refs={"path": request.target.text_path},
            )
        composed = compose(current, content)
        if dry_run:
            action = "remove" if content is None else "write"
            return 0, f"would {action} status block: {text_file}; text hash {text_sha256(composed)}"
        state = {
            "version": 1,
            "status": "active",
            "authorization": authorization.strip(),
            "candidate_hash": raw_sha256(candidate),
            "original_raw_sha256": raw_sha256(text_file),
            "intended_text_sha256": text_sha256(composed),
            "backup_path": None,
        }
        # 書く前の全文のハッシュを計算するため、一時的に組み立てた全文の生のハッシュを持つ。
        from hashlib import sha256

        state["intended_raw_sha256"] = "sha256:" + sha256(composed.encode("utf-8")).hexdigest()
        _save_state(dest, state)

    if dry_run:
        return 0, f"would resume status block: {text_file}"

    if raw_sha256(text_file) != state["intended_raw_sha256"]:
        if not state.get("backup_path"):
            backup = _next_backup(root, text_file.name)
            shutil.copyfile(text_file, backup)
            state["backup_path"] = backup.relative_to(root).as_posix()
            _save_state(dest, state)
        atomic_write_text(text_file, composed)
        if raw_sha256(text_file) != state["intended_raw_sha256"]:
            raise BridgeError("JOB_CONFLICT", "status block bytes do not match the intended edition")
    _write_report(dest, request, composed)
    state["status"] = "completed"
    _save_state(dest, state)
    append_journal(
        dest / "journal.jsonl",
        JournalEntry(
            schema=SCHEMA,
            at=now_iso(),
            action=JournalAction.PUBLISH,
            run_id=request.run_id,
            request_id=request.request_id,
            hashes={"published": str(state["intended_text_sha256"])},
            note="status block published (METRON skipped)",
        ),
    )
    return 0, f"published status block: {text_file}"


def load_request(dest: Path) -> RequestDocument:
    return load_model(dest / "request.yaml", RequestDocument)
