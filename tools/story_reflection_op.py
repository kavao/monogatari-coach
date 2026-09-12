#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Story-reflection operation journal, exclusive lock, and atomic writes.

機械正本。エージェントは journal / lock / 設計書 / _meta.md を手で書き換えない。
状態遷移の規約はスキル novel-story-reflection と対になる。
"""

from __future__ import annotations

import argparse
import errno
import hashlib
import json
import os
import re
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from console_io import configure_stdio_utf8

CURRENT_NAME = "_story_reflection_op.json"
JOURNAL_NAME = "_story_reflection_op.jsonl"
LOCK_NAME = "_story_reflection_op.lock"
DESIGN_NAME = "design_specification.md"
META_NAME = "_meta.md"

ACTIVE_STATUSES = frozenset({"prepared", "replaced", "verified"})
TERMINAL_STATUSES = frozenset({"done", "failed"})
TRANSITION_STATUSES = ACTIVE_STATUSES | TERMINAL_STATUSES
RECORD_TRANSITION = "transition"
RECORD_LOCK_EVENT = "lock_event"
RECORD_ARCHIVE = "archive"

BODY_FILENAME_RE = re.compile(r"^novel_text(\d+)(?:_(\d+))?\.md$")
CHAPTER_ANCHOR_RE = re.compile(
    r"^#{2,4}\s*第\s*(\d+)\s*章(?!\s*第?\s*\d+\s*項)(?!\d)"
)
SECTION_ANCHOR_RE = re.compile(
    r"^#{2,6}\s*第\s*(\d+)\s*章\s*第?\s*(\d+)\s*項"
)

HASH_FIELDS = (
    "intended_design_sha256",
    "intended_chapter_sha256",
    "intended_meta_sha256",
)

EXIT_OK = 0
EXIT_USAGE = 1
EXIT_INCOMPLETE = 2


class OpError(Exception):
    def __init__(self, code: str, message: str, *, payload: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.payload = payload or {}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def new_operation_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"sr-{stamp}-{uuid.uuid4().hex[:8]}"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp")
    try:
        with tmp.open("wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def atomic_write_text(path: Path, text: str) -> None:
    atomic_write_bytes(path, text.encode("utf-8"))


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    line = json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(line)
        handle.flush()
        os.fsync(handle.fileno())


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def resolve_novel_dir(value: str, *, root: Path | None = None) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path.resolve()
    base = root or repo_root()
    return (base / path).resolve()


def parse_body_filename(name: str) -> tuple[int, int | None] | None:
    match = BODY_FILENAME_RE.match(Path(name).name)
    if not match:
        return None
    chapter = int(match.group(1))
    section = int(match.group(2)) if match.group(2) else None
    return chapter, section


def scan_anchors(design_text: str) -> dict[str, Any]:
    chapters: dict[int, list[int]] = {}
    sections: dict[tuple[int, int], list[int]] = {}
    for index, line in enumerate(design_text.splitlines(), start=1):
        section = SECTION_ANCHOR_RE.match(line)
        if section:
            key = (int(section.group(1)), int(section.group(2)))
            sections.setdefault(key, []).append(index)
            continue
        chapter = CHAPTER_ANCHOR_RE.match(line)
        if chapter:
            key_n = int(chapter.group(1))
            chapters.setdefault(key_n, []).append(index)
    return {"chapters": chapters, "sections": sections}


def resolve_target(design_text: str, filename: str) -> dict[str, Any]:
    parsed = parse_body_filename(filename)
    if parsed is None:
        return {
            "ok": False,
            "code": "UNRESOLVED",
            "message": "本文ファイル名から章番号が取れない",
            "filename": Path(filename).name,
        }
    chapter, section = parsed
    anchors = scan_anchors(design_text)
    chapter_hits = anchors["chapters"].get(chapter, [])
    if len(chapter_hits) > 1:
        return {
            "ok": False,
            "code": "UNRESOLVED",
            "message": f"章アンカー第{chapter}章が重複している",
            "chapter": chapter,
            "section": section,
        }
    if section is None:
        section_keys = [key for key in anchors["sections"] if key[0] == chapter]
        dup_section = next(
            (key for key in section_keys if len(anchors["sections"][key]) > 1),
            None,
        )
        if dup_section:
            return {
                "ok": False,
                "code": "UNRESOLVED",
                "message": f"項アンカー第{dup_section[0]}章{dup_section[1]}項が重複している",
                "chapter": chapter,
            }
        if chapter_hits:
            return {
                "ok": True,
                "kind": "chapter",
                "chapter": chapter,
                "section": None,
                "write_scope": "chapter_anchor",
                "label": f"第{chapter}章",
            }
        if section_keys:
            return {
                "ok": True,
                "kind": "chapter",
                "chapter": chapter,
                "section": None,
                "write_scope": "all_sections_aggregate",
                "label": f"第{chapter}章",
            }
        return {
            "ok": False,
            "code": "UNRESOLVED",
            "message": f"第{chapter}章のアンカーが無い",
            "chapter": chapter,
        }

    section_key = (chapter, section)
    section_hits = anchors["sections"].get(section_key, [])
    if len(section_hits) > 1:
        return {
            "ok": False,
            "code": "UNRESOLVED",
            "message": f"項アンカー第{chapter}章{section}項が重複している",
            "chapter": chapter,
            "section": section,
        }
    if section_hits:
        return {
            "ok": True,
            "kind": "section",
            "chapter": chapter,
            "section": section,
            "write_scope": "section_anchor",
            "label": f"第{chapter}章{section}項",
        }
    if chapter_hits:
        return {
            "ok": True,
            "kind": "chapter",
            "chapter": chapter,
            "section": section,
            "write_scope": "chapter_as_single",
            "label": f"第{chapter}章",
        }
    return {
        "ok": False,
        "code": "UNRESOLVED",
        "message": f"第{chapter}章{section}項のアンカーが無い",
        "chapter": chapter,
        "section": section,
    }


def intended_hash_view(row: dict[str, Any]) -> dict[str, Any]:
    return {key: row.get(key) for key in HASH_FIELDS}


def transition_identity(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "operation_id": row.get("operation_id"),
        "status": row.get("status"),
        "transition_seq": row.get("transition_seq"),
        "last_journal_seq": row.get("last_journal_seq"),
        **intended_hash_view(row),
    }


def identities_match(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return transition_identity(left) == transition_identity(right)


@dataclass
class JournalState:
    rows: list[dict[str, Any]] = field(default_factory=list)
    last_journal_seq: int = 0
    last_transition: dict[str, Any] | None = None
    orphan: bool = False
    orphan_reason: str = ""


def parse_journal(path: Path) -> JournalState:
    state = JournalState()
    if not path.is_file():
        return state
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        return state
    expected_journal = 1
    transition_seqs: dict[str, int] = {}
    for line_no, raw in enumerate(text.splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            row = json.loads(raw)
        except json.JSONDecodeError as exc:
            state.orphan = True
            state.orphan_reason = f"jsonl {line_no}行目が JSON として読めない: {exc}"
            return state
        if not isinstance(row, dict):
            state.orphan = True
            state.orphan_reason = f"jsonl {line_no}行目がオブジェクトではない"
            return state
        kind = row.get("record_kind")
        journal_seq = row.get("journal_seq")
        if not isinstance(journal_seq, int) or journal_seq != expected_journal:
            state.orphan = True
            state.orphan_reason = (
                f"journal_seq が欠番または不連続（期待 {expected_journal}、実値 {journal_seq}）"
            )
            return state
        expected_journal += 1
        state.last_journal_seq = journal_seq
        state.rows.append(row)
        if kind == RECORD_TRANSITION:
            op_id = row.get("operation_id")
            seq = row.get("transition_seq")
            status = row.get("status")
            if not isinstance(op_id, str) or not op_id:
                state.orphan = True
                state.orphan_reason = f"jsonl {line_no}行目の operation_id が無い"
                return state
            if status not in TRANSITION_STATUSES:
                state.orphan = True
                state.orphan_reason = f"jsonl {line_no}行目の status が不正: {status}"
                return state
            expected_seq = transition_seqs.get(op_id, 0) + 1
            if not isinstance(seq, int) or seq != expected_seq:
                state.orphan = True
                state.orphan_reason = (
                    f"operation {op_id} の transition_seq が欠番または重複"
                    f"（期待 {expected_seq}、実値 {seq}）"
                )
                return state
            stored_last = row.get("last_journal_seq")
            if stored_last != journal_seq:
                state.orphan = True
                state.orphan_reason = (
                    f"jsonl {line_no}行目の last_journal_seq が journal_seq と一致しない"
                    f"（last_journal_seq={stored_last}, journal_seq={journal_seq}）"
                )
                return state
            transition_seqs[op_id] = seq
            state.last_transition = row
        elif kind == RECORD_LOCK_EVENT:
            if not isinstance(row.get("operation_id"), str) or not row.get("operation_id"):
                state.orphan = True
                state.orphan_reason = f"jsonl {line_no}行目の lock_event に operation_id が無い"
                return state
            if not isinstance(row.get("event"), str) or not row.get("event"):
                state.orphan = True
                state.orphan_reason = f"jsonl {line_no}行目の lock_event に event が無い"
                return state
        elif kind == RECORD_ARCHIVE:
            if not isinstance(row.get("operation_id"), str) or not row.get("operation_id"):
                state.orphan = True
                state.orphan_reason = f"jsonl {line_no}行目の archive に operation_id が無い"
                return state
        else:
            state.orphan = True
            state.orphan_reason = f"jsonl {line_no}行目の record_kind が不明: {kind}"
            return state
    return state


def load_current(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        data = load_json(path)
    except (OSError, json.JSONDecodeError):
        raise OpError("ORPHAN", "未完了（operation 証跡不整合）: current が JSON として読めない")
    if not isinstance(data, dict):
        raise OpError("ORPHAN", "未完了（operation 証跡不整合）: current がオブジェクトではない")
    return data


def parse_lock_text(raw: str) -> dict[str, Any]:
    raw = raw.strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {"raw": raw}
    return data if isinstance(data, dict) else {"raw": raw}


def read_lock_from_fd(fd: int) -> dict[str, Any]:
    os.lseek(fd, 0, os.SEEK_SET)
    chunks: list[bytes] = []
    while True:
        piece = os.read(fd, 4096)
        if not piece:
            break
        chunks.append(piece)
    os.lseek(fd, 0, os.SEEK_SET)
    return parse_lock_text(b"".join(chunks).decode("utf-8"))


def read_lock(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        raw = path.read_text(encoding="utf-8")
    except PermissionError:
        return {"unreadable": True}
    return parse_lock_text(raw)


def classify_state(
    *,
    current: dict[str, Any] | None,
    journal: JournalState,
    lock: dict[str, Any] | None,
    design_hash: str | None = None,
    own_lock_id: str | None = None,
) -> dict[str, Any]:
    if journal.orphan:
        return {"verdict": "orphan", "reason": journal.orphan_reason, "code": "ORPHAN"}
    last = journal.last_transition
    leftover_lock = lock is not None and (
        own_lock_id is None or (isinstance(lock, dict) and lock.get("operation_id") != own_lock_id)
    )
    if current is None:
        if leftover_lock:
            return {
                "verdict": "orphan",
                "reason": "lock が残っているのに current が無い",
                "code": "ORPHAN",
            }
        if last is None:
            return {"verdict": "missing", "reason": "operation なし", "code": "OK"}
        if last.get("status") in ACTIVE_STATUSES:
            return {
                "verdict": "orphan",
                "reason": "current が無く、最後の状態遷移が active",
                "code": "ORPHAN",
            }
        if (
            last.get("status") in {"replaced", "verified"}
            and design_hash
            and last.get("intended_design_sha256") == design_hash
        ):
            return {
                "verdict": "orphan",
                "reason": "current が無く、設計書だけ意図ハッシュと一致する",
                "code": "ORPHAN",
            }
        if last.get("status") in TERMINAL_STATUSES:
            return {"verdict": "terminal", "reason": "terminal のみ", "code": "OK"}
        return {"verdict": "orphan", "reason": "current 欠落と状態遷移の組合せが不正", "code": "ORPHAN"}

    if last is None:
        return {"verdict": "orphan", "reason": "current があるのに状態遷移行が無い", "code": "ORPHAN"}
    current_view = dict(current)
    current_view["last_journal_seq"] = current.get("last_journal_seq")
    if last.get("journal_seq") and current.get("last_journal_seq") is not None:
        if last["journal_seq"] > current["last_journal_seq"]:
            return {
                "verdict": "orphan",
                "reason": "最後の状態遷移行が current より新しい",
                "code": "ORPHAN",
            }
    if not identities_match(current_view, last):
        return {
            "verdict": "orphan",
            "reason": "current と最後の状態遷移行が完全一致しない",
            "code": "ORPHAN",
        }
    status = current.get("status")
    if status in ACTIVE_STATUSES:
        return {"verdict": "active", "reason": f"status={status}", "code": "JOB_CONFLICT"}
    if status in TERMINAL_STATUSES:
        return {"verdict": "terminal_match", "reason": f"status={status}", "code": "OK"}
    return {"verdict": "orphan", "reason": f"未知の status: {status}", "code": "ORPHAN"}


@dataclass
class NovelPaths:
    novel_dir: Path

    @property
    def current(self) -> Path:
        return self.novel_dir / CURRENT_NAME

    @property
    def journal(self) -> Path:
        return self.novel_dir / JOURNAL_NAME

    @property
    def lock(self) -> Path:
        return self.novel_dir / LOCK_NAME

    @property
    def design(self) -> Path:
        return self.novel_dir / DESIGN_NAME

    @property
    def meta(self) -> Path:
        return self.novel_dir / META_NAME


class LockHeld:
    def __init__(
        self,
        paths: NovelPaths,
        operation_id: str,
        fd: int,
        *,
        created: bool = False,
        payload: dict[str, Any] | None = None,
    ):
        self.paths = paths
        self.operation_id = operation_id
        self.fd = fd
        self.created = created
        self.payload = payload or {"operation_id": operation_id}
        self.delete_file = False
        self.released = False

    def close_fd(self) -> None:
        if self.fd >= 0:
            os.close(self.fd)
            self.fd = -1

    def release_file(self) -> None:
        if self.fd >= 0:
            unlink_owned_lock(self)


def _hold_sleep_for_tests(env_name: str = "STORY_REFLECTION_HOLD_SLEEP") -> None:
    raw = os.environ.get(env_name)
    if not raw:
        return
    try:
        delay = float(raw)
    except ValueError:
        return
    if delay > 0:
        time.sleep(delay)


def same_lock_file(fd: int, path: Path) -> bool:
    try:
        left = os.fstat(fd)
        right = os.stat(path)
    except OSError:
        return False
    return (left.st_dev, left.st_ino) == (right.st_dev, right.st_ino)


def _windows_delete_on_close(fd: int) -> None:
    import ctypes
    import msvcrt
    from ctypes import wintypes

    class FileDispositionInfo(ctypes.Structure):
        _fields_ = [("DeleteFile", wintypes.BOOLEAN)]

    handle = msvcrt.get_osfhandle(fd)
    info = FileDispositionInfo(True)
    ok = ctypes.windll.kernel32.SetFileInformationByHandle(
        wintypes.HANDLE(handle),
        4,
        ctypes.byref(info),
        ctypes.sizeof(info),
    )
    if not ok:
        raise OSError(ctypes.GetLastError(), "SetFileInformationByHandle failed")


def still_owns_lock(held: LockHeld) -> bool:
    if held.fd < 0:
        return False
    try:
        meta = read_lock_from_fd(held.fd)
    except OSError:
        return False
    if meta.get("operation_id") != held.operation_id:
        return False
    token = (held.payload or {}).get("lock_token")
    if token and meta.get("lock_token") != token:
        return False
    return same_lock_file(held.fd, held.paths.lock)


def _remove_owned_lock_name(held: LockHeld) -> None:
    if os.environ.get("STORY_REFLECTION_FAIL_WINDOWS_DELETE"):
        raise OSError("forced delete-on-close failure")
    if os.name == "nt":
        _windows_delete_on_close(held.fd)
        return
    os.unlink(str(held.paths.lock))


def unlink_owned_lock(held: LockHeld, *, close_fd: bool = True) -> bool:
    """Delete the lock only while this fd still owns the same official name."""
    if held.fd < 0:
        return held.released
    try:
        if not still_owns_lock(held):
            return False
        _hold_sleep_for_tests("STORY_REFLECTION_UNLINK_SLEEP_BEFORE_DELETE")
        if not still_owns_lock(held):
            return False
        try:
            _remove_owned_lock_name(held)
        except OSError:
            return False
        held.released = True
        return True
    finally:
        if close_fd:
            held.close_fd()


def try_exclusive_lock(fd: int) -> None:
    os.lseek(fd, 0, os.SEEK_SET)
    if os.name == "nt":
        import msvcrt

        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise OpError("LOCK_HELD", "未完了（同期ロック取得不能）") from exc
        return
    import fcntl

    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (BlockingIOError, OSError) as exc:
        raise OpError("LOCK_HELD", "未完了（同期ロック取得不能）") from exc


def unlock_exclusive(fd: int) -> None:
    os.lseek(fd, 0, os.SEEK_SET)
    if os.name == "nt":
        import msvcrt

        try:
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        return
    import fcntl

    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    except OSError:
        pass


def open_lock_fd(path: Path, *, create_excl: bool) -> int:
    if os.name != "nt":
        flags = os.O_RDWR
        if create_excl:
            flags |= os.O_CREAT | os.O_EXCL
        return os.open(str(path), flags)

    import ctypes
    import msvcrt
    from ctypes import wintypes

    generic_read = 0x80000000
    generic_write = 0x40000000
    delete_access = 0x00010000
    file_share = 0x00000001 | 0x00000002 | 0x00000004
    create_new = 1
    open_existing = 3
    file_attribute_normal = 0x80
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateFileW.restype = wintypes.HANDLE
    handle = kernel32.CreateFileW(
        str(path.resolve()),
        generic_read | generic_write | delete_access,
        file_share,
        None,
        create_new if create_excl else open_existing,
        file_attribute_normal,
        None,
    )
    if handle == wintypes.HANDLE(-1).value:
        error = ctypes.GetLastError()
        if create_excl and error in {80, 183}:
            raise FileExistsError(error, "lock exists", str(path))
        if not create_excl and error in {2, 3}:
            raise FileNotFoundError(error, "lock missing", str(path))
        raise OSError(error, "CreateFileW failed", str(path))
    return msvcrt.open_osfhandle(int(handle), os.O_RDWR)


def publish_official_lock(staging: Path, official: Path) -> None:
    """Publish a locked staging file. Never replace an existing official name."""
    if official.exists():
        raise OpError("LOCK_HELD", "未完了（同期ロック取得不能）")
    if os.name == "nt":
        try:
            os.rename(str(staging), str(official))
        except OSError as exc:
            raise OpError("LOCK_HELD", "未完了（同期ロック取得不能）") from exc
        return
    try:
        os.link(str(staging), str(official))
    except OSError as exc:
        if official.exists() or getattr(exc, "errno", None) in {errno.EEXIST, errno.EPERM}:
            raise OpError("LOCK_HELD", "未完了（同期ロック取得不能）") from exc
        raise OpError("LOCK_HELD", "未完了（同期ロック取得不能）") from exc
    try:
        staging.unlink()
    except OSError:
        pass


def acquire_lock(paths: NovelPaths, operation_id: str) -> LockHeld:
    token = uuid.uuid4().hex
    payload = {
        "operation_id": operation_id,
        "pid": os.getpid(),
        "created_at": utc_now(),
        "lock_token": token,
    }
    staging = paths.lock.with_name(f".{LOCK_NAME}.{os.getpid()}.{token[:8]}.creating")
    try:
        fd = open_lock_fd(staging, create_excl=True)
    except FileExistsError as exc:
        raise OpError("LOCK_HELD", "未完了（同期ロック取得不能）") from exc
    raw = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
    published = False
    try:
        os.write(fd, raw)
        os.fsync(fd)
        try_exclusive_lock(fd)
        _hold_sleep_for_tests("STORY_REFLECTION_ACQUIRE_SLEEP_BEFORE_PUBLISH")
        publish_official_lock(staging, paths.lock)
        published = True
    except Exception:
        os.close(fd)
        if not published:
            try:
                staging.unlink()
            except OSError:
                pass
        raise OpError("LOCK_HELD", "未完了（同期ロック取得不能）") from None
    _hold_sleep_for_tests()
    return LockHeld(paths, operation_id, fd, created=True, payload=payload)


def hold_existing_lock(paths: NovelPaths) -> LockHeld:
    if not paths.lock.is_file():
        raise OpError("LOCK_HELD", "未完了（同期ロック取得不能）: lock が無い")
    try:
        fd = open_lock_fd(paths.lock, create_excl=False)
    except OSError as exc:
        raise OpError("LOCK_HELD", "未完了（同期ロック取得不能）") from exc
    try:
        try_exclusive_lock(fd)
    except OpError:
        os.close(fd)
        raise
    meta = read_lock_from_fd(fd)
    op_id = meta.get("operation_id") if isinstance(meta, dict) else ""
    if not op_id:
        os.close(fd)
        raise OpError("LOCK_HELD", "未完了（同期ロック取得不能）: lock 内容が不完全")
    _hold_sleep_for_tests()
    return LockHeld(paths, str(op_id), fd, created=False, payload=meta)


def hold_or_create_lock(paths: NovelPaths, operation_id: str) -> LockHeld:
    if paths.lock.is_file():
        return hold_existing_lock(paths)
    return acquire_lock(paths, operation_id)


def finish_lock(held: LockHeld) -> None:
    if held.delete_file:
        had_fd = held.fd >= 0
        unlink_owned_lock(held)
        if had_fd and not held.released:
            raise OpError("LOCK_HELD", "未完了（同期ロック取得不能）")
        return
    held.close_fd()


def finish_lock_in_finally(held: LockHeld) -> None:
    pending = sys.exception()
    try:
        finish_lock(held)
    except OpError:
        if pending is not None:
            return
        raise


def rewrite_lock_payload(held: LockHeld, operation_id: str) -> None:
    if held.operation_id == operation_id:
        return
    payload = {
        "operation_id": operation_id,
        "pid": os.getpid(),
        "created_at": utc_now(),
        "lock_token": (held.payload or {}).get("lock_token") or uuid.uuid4().hex,
    }
    raw = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
    os.ftruncate(held.fd, 0)
    os.lseek(held.fd, 0, os.SEEK_SET)
    os.write(held.fd, raw)
    os.fsync(held.fd)
    try_exclusive_lock(held.fd)
    held.operation_id = operation_id
    held.payload = payload


def file_hashes(paths: NovelPaths, text_relpaths: list[str]) -> dict[str, Any]:
    missing = [rel for rel in text_relpaths if not (paths.novel_dir / rel).is_file()]
    if not paths.design.is_file():
        raise OpError("MISSING", "未完了（設計書が無い）")
    if not paths.meta.is_file():
        raise OpError("MISSING", "未完了（_meta.md が無い）")
    if missing:
        raise OpError("MISSING", f"未完了（対象本文が無い）: {', '.join(missing)}")
    return {
        "design": sha256_file(paths.design),
        "meta": sha256_file(paths.meta),
        "texts": {rel: sha256_file(paths.novel_dir / rel) for rel in text_relpaths},
    }


def require_text_hashes(op: dict[str, Any]) -> dict[str, str]:
    texts = op.get("input_text_sha256")
    if not isinstance(texts, dict) or not texts:
        raise OpError("USAGE", "input_text_sha256 が無い")
    out: dict[str, str] = {}
    for key, value in texts.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise OpError("USAGE", "input_text_sha256 の型が不正")
        out[key] = value
    return out


def check_hashes(
    current: dict[str, Any],
    actual: dict[str, Any],
    *,
    design: str,
    meta: str,
    texts: str,
) -> None:
    if design == "input" and actual["design"] != current["input_design_sha256"]:
        raise OpError("STALE_EVIDENCE", "未完了（入力ハッシュ不一致）: 設計書")
    if design == "intended" and actual["design"] != current["intended_design_sha256"]:
        raise OpError("STALE_EVIDENCE", "未完了（入力ハッシュ不一致）: 設計書")
    if meta == "input" and actual["meta"] != current["input_meta_sha256"]:
        raise OpError("STALE_EVIDENCE", "未完了（入力ハッシュ不一致）: _meta.md")
    if meta == "intended" and actual["meta"] != current["intended_meta_sha256"]:
        raise OpError("STALE_EVIDENCE", "未完了（入力ハッシュ不一致）: _meta.md")
    if texts == "input" and actual["texts"] != current["input_text_sha256"]:
        raise OpError("STALE_EVIDENCE", "未完了（入力ハッシュ不一致）: 対象本文")


def next_record_base(current: dict[str, Any], journal: JournalState, status: str) -> dict[str, Any]:
    journal_seq = journal.last_journal_seq + 1
    transition_seq = int(current["transition_seq"]) + 1
    row = {
        "record_kind": RECORD_TRANSITION,
        "journal_seq": journal_seq,
        "operation_id": current["operation_id"],
        "transition_seq": transition_seq,
        "last_journal_seq": journal_seq,
        "status": status,
        "target": current.get("target"),
        "input_design_sha256": current["input_design_sha256"],
        "input_meta_sha256": current["input_meta_sha256"],
        "input_text_sha256": current["input_text_sha256"],
        "intended_design_sha256": current["intended_design_sha256"],
        "intended_chapter_sha256": current["intended_chapter_sha256"],
        "intended_meta_sha256": current["intended_meta_sha256"],
        "created_at": utc_now(),
    }
    return row


def write_transition(paths: NovelPaths, row: dict[str, Any]) -> dict[str, Any]:
    append_jsonl(paths.journal, row)
    current = {key: value for key, value in row.items() if key != "record_kind"}
    current["created_at"] = row["created_at"]
    atomic_write_text(paths.current, json.dumps(current, ensure_ascii=False, indent=2) + "\n")
    return current


def inspect_payload(paths: NovelPaths, lock: dict[str, Any] | None = None) -> dict[str, Any]:
    journal = parse_journal(paths.journal)
    try:
        current = load_current(paths.current)
    except OpError as exc:
        current = None
        journal.orphan = True
        journal.orphan_reason = exc.message
    if lock is None:
        lock = read_lock(paths.lock)
    design_hash = sha256_file(paths.design) if paths.design.is_file() else None
    classified = classify_state(
        current=current,
        journal=journal,
        lock=lock,
        design_hash=design_hash,
    )
    return {
        "novel": str(paths.novel_dir),
        "lock": lock,
        "current": current,
        "last_transition": journal.last_transition,
        "last_journal_seq": journal.last_journal_seq,
        "verdict": classified["verdict"],
        "reason": classified["reason"],
        "code": classified["code"],
    }


def cmd_hash(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise OpError("MISSING", f"ファイルが無い: {path}")
    return {"path": str(path), "sha256": sha256_file(path)}


def cmd_resolve(paths: NovelPaths, filename: str) -> dict[str, Any]:
    if not paths.design.is_file():
        raise OpError("MISSING", "未完了（設計書が無い）")
    result = resolve_target(paths.design.read_text(encoding="utf-8"), filename)
    if not result.get("ok"):
        raise OpError("UNRESOLVED", f"未完了（解決不能）: {result.get('message')}", payload=result)
    return result


def cmd_inspect(paths: NovelPaths) -> dict[str, Any]:
    return inspect_payload(paths)


def cmd_lock_release(paths: NovelPaths) -> dict[str, Any]:
    held = hold_existing_lock(paths)
    try:
        payload = inspect_payload(paths, lock=held.payload)
        lock = payload["lock"]
        current = payload["current"]
        last = payload["last_transition"]
        if lock is None:
            raise OpError("LOCK_RELEASE_DENIED", "未完了（ロック解除不可）: lock が無い")
        if payload["verdict"] != "terminal_match":
            raise OpError(
                "LOCK_RELEASE_DENIED",
                f"未完了（ロック解除不可）: {payload['reason']}",
                payload=payload,
            )
        lock_id = lock.get("operation_id") if isinstance(lock, dict) else None
        if not lock_id or lock_id != current.get("operation_id"):
            raise OpError("LOCK_RELEASE_DENIED", "未完了（ロック解除不可）: lock の operation id が一致しない")
        if current.get("status") not in TERMINAL_STATUSES or last.get("status") not in TERMINAL_STATUSES:
            raise OpError("LOCK_RELEASE_DENIED", "未完了（ロック解除不可）: terminal ではない")

        # The audit event must never claim a release before the official name
        # has actually been removed.  Keep the descriptor open while the
        # event is appended so the delete operation is still tied to the
        # ownership check made above.  On a failed delete, unlink_owned_lock
        # leaves the official name untouched and this command records no
        # success event.
        if not unlink_owned_lock(held, close_fd=False):
            raise OpError("LOCK_HELD", "未完了（同期ロック取得不能）")

        journal = parse_journal(paths.journal)
        event = {
            "record_kind": RECORD_LOCK_EVENT,
            "event": "lock_released",
            "journal_seq": journal.last_journal_seq + 1,
            "operation_id": current["operation_id"],
            "created_at": utc_now(),
        }
        append_jsonl(paths.journal, event)
        payload["lock"] = None
        payload["lock_event"] = event
        payload["verdict"] = "terminal_match"
        payload["message"] = "lock を解除した"
        return payload
    finally:
        finish_lock_in_finally(held)


def prepare_begin_row(
    *,
    operation_id: str,
    journal_seq: int,
    target: str,
    hashes: dict[str, Any],
) -> dict[str, Any]:
    return {
        "record_kind": RECORD_TRANSITION,
        "journal_seq": journal_seq,
        "operation_id": operation_id,
        "transition_seq": 1,
        "last_journal_seq": journal_seq,
        "status": "prepared",
        "target": target,
        "input_design_sha256": hashes["input_design_sha256"],
        "input_meta_sha256": hashes["input_meta_sha256"],
        "input_text_sha256": hashes["input_text_sha256"],
        "intended_design_sha256": hashes["intended_design_sha256"],
        "intended_chapter_sha256": hashes["intended_chapter_sha256"],
        "intended_meta_sha256": hashes["intended_meta_sha256"],
        "created_at": utc_now(),
    }


def cmd_begin(paths: NovelPaths, evidence: dict[str, Any], *, archive: bool = False) -> dict[str, Any]:
    operation_id = evidence.get("operation_id") or new_operation_id()
    required = [
        "target",
        "input_design_sha256",
        "input_meta_sha256",
        "input_text_sha256",
        "intended_design_sha256",
        "intended_chapter_sha256",
        "intended_meta_sha256",
    ]
    missing = [key for key in required if not evidence.get(key)]
    if missing:
        raise OpError("USAGE", f"evidence の必須欄が無い: {', '.join(missing)}")
    lock = acquire_lock(paths, operation_id)
    try:
        journal = parse_journal(paths.journal)
        current = load_current(paths.current)
        classified = classify_state(
            current=current,
            journal=journal,
            lock=lock.payload,
            design_hash=sha256_file(paths.design) if paths.design.is_file() else None,
            own_lock_id=operation_id,
        )
        if classified["verdict"] == "orphan":
            raise OpError("ORPHAN", f"未完了（operation 証跡不整合）: {classified['reason']}")
        if classified["verdict"] == "active":
            raise OpError("JOB_CONFLICT", "未完了（同期中の operation あり）")
        if classified["verdict"] == "terminal_match":
            if current is None or journal.last_transition is None:
                raise OpError("ORPHAN", "未完了（operation 証跡不整合）: terminal 照合不能")
            if not identities_match(current, journal.last_transition):
                raise OpError("ORPHAN", "未完了（operation 証跡不整合）: 既存 terminal が一致しない")
        next_seq = journal.last_journal_seq
        if archive and journal.last_transition is not None:
            next_seq += 1
            archive_row = {
                "record_kind": RECORD_ARCHIVE,
                "journal_seq": next_seq,
                "operation_id": journal.last_transition.get("operation_id"),
                "status": journal.last_transition.get("status"),
                "created_at": utc_now(),
            }
            append_jsonl(paths.journal, archive_row)
            journal = parse_journal(paths.journal)
        next_seq = journal.last_journal_seq + 1
        row = prepare_begin_row(
            operation_id=operation_id,
            journal_seq=next_seq,
            target=str(evidence["target"]),
            hashes=evidence,
        )
        current = write_transition(paths, row)
        return {"ok": True, "current": current, "lock": str(paths.lock)}
    except Exception:
        if not lock.released:
            try:
                lock.release_file()
            except OpError:
                pass
        raise
    finally:
        if lock.fd >= 0:
            lock.close_fd()


def load_active_locked(
    paths: NovelPaths, held: LockHeld
) -> tuple[dict[str, Any], JournalState, dict[str, Any]]:
    lock = held.payload if held.payload else read_lock_from_fd(held.fd)
    if not lock:
        raise OpError("LOCK_HELD", "未完了（同期ロック取得不能）: lock が無い")
    journal = parse_journal(paths.journal)
    current = load_current(paths.current)
    classified = classify_state(
        current=current,
        journal=journal,
        lock=lock,
        design_hash=sha256_file(paths.design) if paths.design.is_file() else None,
    )
    if classified["verdict"] == "orphan":
        raise OpError("ORPHAN", f"未完了（operation 証跡不整合）: {classified['reason']}")
    if current is None:
        raise OpError("ORPHAN", "未完了（operation 証跡不整合）: current が無い")
    if lock.get("operation_id") != current.get("operation_id"):
        raise OpError("ORPHAN", "未完了（operation 証跡不整合）: lock の operation id が current と違う")
    return current, journal, classified


def fail_operation(paths: NovelPaths, current: dict[str, Any], journal: JournalState, reason: str) -> dict[str, Any]:
    row = next_record_base(current, journal, "failed")
    row["fail_reason"] = reason
    written = write_transition(paths, row)
    return {"ok": False, "code": "FAILED", "current": written, "message": reason}


def cmd_apply_design(paths: NovelPaths, source: Path) -> dict[str, Any]:
    held = hold_existing_lock(paths)
    try:
        current, journal, _classified = load_active_locked(paths, held)
        texts = require_text_hashes(current)
        actual = file_hashes(paths, list(texts))
        result = _apply_design_locked(paths, source, current, journal, actual)
        if isinstance(result.get("current"), dict) and result["current"].get("status") in TERMINAL_STATUSES:
            held.delete_file = True
        return result
    finally:
        finish_lock_in_finally(held)


def _apply_design_locked(
    paths: NovelPaths,
    source: Path,
    current: dict[str, Any],
    journal: JournalState,
    actual: dict[str, Any],
) -> dict[str, Any]:
    texts = require_text_hashes(current)
    try:
        if current["status"] == "verified":
            check_hashes(current, actual, design="intended", meta="input", texts="input")
            return {"ok": True, "current": current, "message": "すでに verified"}
        if current["status"] == "replaced":
            check_hashes(current, actual, design="intended", meta="input", texts="input")
            row = next_record_base(current, journal, "verified")
            written = write_transition(paths, row)
            return {"ok": True, "current": written}
        if current["status"] != "prepared":
            raise OpError("INVALID_STATUS", f"未完了: apply-design できない status={current['status']}")
        check_hashes(current, actual, design="input", meta="input", texts="input")
        intended_data = source.read_bytes()
        if sha256_bytes(intended_data) != current["intended_design_sha256"]:
            raise OpError("STALE_EVIDENCE", "未完了（入力ハッシュ不一致）: 置換しようとした設計書")
        if current["intended_design_sha256"] == current["input_design_sha256"]:
            row = next_record_base(current, journal, "verified")
            written = write_transition(paths, row)
            return {"ok": True, "current": written, "message": "設計書は変更なし"}
        atomic_write_bytes(paths.design, intended_data)
        journal = parse_journal(paths.journal)
        current = load_current(paths.current) or current
        row = next_record_base(current, journal, "replaced")
        written = write_transition(paths, row)
        actual = file_hashes(paths, list(texts))
        try:
            check_hashes(written, actual, design="intended", meta="input", texts="input")
        except OpError as exc:
            journal = parse_journal(paths.journal)
            return fail_operation(paths, written, journal, exc.message)
        journal = parse_journal(paths.journal)
        verified = next_record_base(written, journal, "verified")
        written = write_transition(paths, verified)
        return {"ok": True, "current": written}
    except OpError as exc:
        if exc.code == "STALE_EVIDENCE":
            journal = parse_journal(paths.journal)
            current = load_current(paths.current) or current
            return fail_operation(paths, current, journal, exc.message)
        raise


def cmd_apply_meta(paths: NovelPaths, source: Path) -> dict[str, Any]:
    held = hold_existing_lock(paths)
    try:
        current, journal, _classified = load_active_locked(paths, held)
        texts = require_text_hashes(current)
        actual = file_hashes(paths, list(texts))
        result = _apply_meta_locked(paths, source, current, journal, actual)
        if isinstance(result.get("current"), dict) and result["current"].get("status") in TERMINAL_STATUSES:
            held.delete_file = True
        return result
    finally:
        finish_lock_in_finally(held)


def _apply_meta_locked(
    paths: NovelPaths,
    source: Path,
    current: dict[str, Any],
    journal: JournalState,
    actual: dict[str, Any],
) -> dict[str, Any]:
    texts = require_text_hashes(current)
    try:
        if current["status"] == "done":
            check_hashes(current, actual, design="intended", meta="intended", texts="input")
            return {"ok": True, "current": current, "message": "すでに done"}
        if current["status"] == "prepared":
            if actual["design"] != current["intended_design_sha256"]:
                raise OpError("INVALID_STATUS", "未完了: 設計書が未検証のまま _meta.md を書けない")
            check_hashes(current, actual, design="intended", meta="input", texts="input")
            row = next_record_base(current, journal, "verified")
            current = write_transition(paths, row)
            journal = parse_journal(paths.journal)
            actual = file_hashes(paths, list(texts))
        if current["status"] != "verified":
            raise OpError("INVALID_STATUS", f"未完了: apply-meta できない status={current['status']}")
        if (
            actual["meta"] == current["intended_meta_sha256"]
            and actual["design"] == current["intended_design_sha256"]
            and actual["texts"] == current["input_text_sha256"]
        ):
            row = next_record_base(current, journal, "done")
            written = write_transition(paths, row)
            return {"ok": True, "current": written, "message": "冪等完了"}
        check_hashes(current, actual, design="intended", meta="input", texts="input")
        intended_data = source.read_bytes()
        if sha256_bytes(intended_data) != current["intended_meta_sha256"]:
            raise OpError("STALE_EVIDENCE", "未完了（入力ハッシュ不一致）: 置換しようとした _meta.md")
        atomic_write_bytes(paths.meta, intended_data)
        actual = file_hashes(paths, list(texts))
        journal = parse_journal(paths.journal)
        current = load_current(paths.current) or current
        check_hashes(current, actual, design="intended", meta="intended", texts="input")
        row = next_record_base(current, journal, "done")
        written = write_transition(paths, row)
        return {"ok": True, "current": written}
    except OpError as exc:
        if exc.code == "STALE_EVIDENCE":
            journal = parse_journal(paths.journal)
            current = load_current(paths.current) or current
            return fail_operation(paths, current, journal, exc.message)
        raise


def cmd_fail(paths: NovelPaths, reason: str) -> dict[str, Any]:
    held = hold_existing_lock(paths)
    try:
        current, journal, _classified = load_active_locked(paths, held)
        result = fail_operation(paths, current, journal, reason)
        held.delete_file = True
        return result
    finally:
        finish_lock_in_finally(held)


def cmd_resume(paths: NovelPaths) -> dict[str, Any]:
    held = hold_or_create_lock(paths, "resume")
    try:
        journal = parse_journal(paths.journal)
        if journal.orphan or journal.last_transition is None:
            if held.created:
                held.delete_file = True
            raise OpError("ORPHAN", "未完了（operation 証跡不整合）: 復旧できる状態遷移が無い")
        last = journal.last_transition
        texts = last.get("input_text_sha256")
        if not isinstance(texts, dict) or not texts:
            if held.created:
                held.delete_file = True
            raise OpError("ORPHAN", "未完了（operation 証跡不整合）: resume の本文ハッシュが無い")
        actual = file_hashes(paths, list(texts))
        status = last.get("status")
        if status in TERMINAL_STATUSES:
            if held.created:
                held.delete_file = True
            raise OpError("ORPHAN", "未完了: resume は active の状態遷移だけ")
        if status == "prepared":
            check_hashes(last, actual, design="input", meta="input", texts="input")
        elif status in {"replaced", "verified"}:
            check_hashes(last, actual, design="intended", meta="input", texts="input")
        else:
            if held.created:
                held.delete_file = True
            raise OpError("ORPHAN", f"未完了（operation 証跡不整合）: resume できない status={status}")
        if last.get("operation_id"):
            rewrite_lock_payload(held, str(last["operation_id"]))
        atomic_write_text(
            paths.current,
            json.dumps({k: v for k, v in last.items() if k != "record_kind"}, ensure_ascii=False, indent=2)
            + "\n",
        )
        return {
            "ok": True,
            "current": load_current(paths.current),
            "message": "最後の状態遷移行を current へ写した。自動完了はしていない",
        }
    except Exception:
        if held.created:
            held.delete_file = True
        raise
    finally:
        finish_lock_in_finally(held)


def cmd_close_orphan(paths: NovelPaths, reason: str) -> dict[str, Any]:
    held = hold_or_create_lock(paths, "close-orphan")
    try:
        journal = parse_journal(paths.journal)
        last = journal.last_transition
        if last is None:
            if held.created:
                held.delete_file = True
            raise OpError("ORPHAN", "未完了（operation 証跡不整合）: 閉じる状態遷移が無い")
        if last.get("status") not in ACTIVE_STATUSES:
            if held.created:
                held.delete_file = True
            raise OpError("ORPHAN", "未完了: close-orphan は active の孤児だけ")
        try:
            current_file = load_current(paths.current)
        except OpError as exc:
            if exc.code != "ORPHAN":
                raise
            current_file = None
            journal.orphan = True
            journal.orphan_reason = exc.message
        classified = classify_state(
            current=current_file,
            journal=journal,
            lock=held.payload,
            design_hash=sha256_file(paths.design) if paths.design.is_file() else None,
            own_lock_id=held.operation_id if held.created else None,
        )
        if classified["verdict"] != "orphan":
            if held.created:
                held.delete_file = True
            raise OpError("ORPHAN", "未完了: 孤児ではないので close-orphan できない")
        current = {
            key: last[key]
            for key in (
                "operation_id",
                "transition_seq",
                "target",
                "input_design_sha256",
                "input_meta_sha256",
                "input_text_sha256",
                "intended_design_sha256",
                "intended_chapter_sha256",
                "intended_meta_sha256",
            )
            if key in last
        }
        current["status"] = last.get("status")
        current["last_journal_seq"] = last.get("journal_seq")
        result = fail_operation(paths, current, journal, reason)
        result["message"] = "孤児を failed にした"
        held.delete_file = True
        return result
    except Exception:
        if held.created and not held.delete_file:
            held.delete_file = True
        raise
    finally:
        finish_lock_in_finally(held)


def emit(data: dict[str, Any], *, ok: bool = True, code: str = "OK", message: str | None = None) -> dict[str, Any]:
    payload = {"ok": ok, "code": code, **data}
    if message:
        payload["message"] = message
    return payload


def print_json(data: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def load_evidence(args: argparse.Namespace) -> dict[str, Any]:
    if args.evidence:
        data = load_json(Path(args.evidence))
        if not isinstance(data, dict):
            raise OpError("USAGE", "evidence がオブジェクトではない")
        return data
    texts: dict[str, str] = {}
    for item in args.text_hash or []:
        if "=" not in item:
            raise OpError("USAGE", "--text-hash は path=sha256 形式")
        rel, digest = item.split("=", 1)
        texts[rel] = digest
    return {
        "operation_id": args.operation_id,
        "target": args.target,
        "input_design_sha256": args.input_design,
        "input_meta_sha256": args.input_meta,
        "input_text_sha256": texts,
        "intended_design_sha256": args.intended_design,
        "intended_chapter_sha256": args.intended_chapter,
        "intended_meta_sha256": args.intended_meta,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ストーリー反映の operation journal / lock / 原子書込み")
    parser.add_argument("--repo-root", default=None, help="リポジトリ根（試験用）")
    sub = parser.add_subparsers(dest="command", required=True)

    p_hash = sub.add_parser("hash", help="ファイルの sha256")
    p_hash.add_argument("path")

    p_resolve = sub.add_parser("resolve", help="本文ファイル名から設計書アンカーを解決")
    p_resolve.add_argument("novel")
    p_resolve.add_argument("--text", required=True, help="novel_textNN.md または novel_textNN_Y.md")

    p_inspect = sub.add_parser("inspect", help="current / journal / lock を読む（消さない）")
    p_inspect.add_argument("novel")
    p_lock_inspect = sub.add_parser("lock-inspect", help="inspect と同じ")
    p_lock_inspect.add_argument("novel")
    p_lock_release = sub.add_parser("lock-release", help="terminal 一致のときだけ lock を消す")
    p_lock_release.add_argument("novel")

    p_begin = sub.add_parser("begin", help="新規 operation の prepared だけを追加")
    p_begin.add_argument("novel")
    p_begin.add_argument("--evidence", help="hashes と target の JSON")
    p_begin.add_argument("--operation-id")
    p_begin.add_argument("--target")
    p_begin.add_argument("--input-design")
    p_begin.add_argument("--input-meta")
    p_begin.add_argument("--intended-design")
    p_begin.add_argument("--intended-chapter")
    p_begin.add_argument("--intended-meta")
    p_begin.add_argument("--text-hash", action="append", help="相対パス=sha256")
    p_begin.add_argument("--archive", action="store_true", help="既存 terminal の archive 行を先に足す")

    p_design = sub.add_parser("apply-design", help="設計書を原子置換して verified まで進める")
    p_design.add_argument("novel")
    p_design.add_argument("--file", required=True)

    p_meta = sub.add_parser("apply-meta", help="_meta.md を原子置換して done にする")
    p_meta.add_argument("novel")
    p_meta.add_argument("--file", required=True)

    p_fail = sub.add_parser("fail", help="現行 operation を failed にする")
    p_fail.add_argument("novel")
    p_fail.add_argument("--reason", required=True)

    p_resume = sub.add_parser("resume", help="明示復旧: 最後の状態遷移行を current へ写す")
    p_resume.add_argument("novel")

    p_close = sub.add_parser("close-orphan", help="明示復旧: 孤児を failed にする")
    p_close.add_argument("novel")
    p_close.add_argument("--reason", default="user-close-orphan")
    return parser


def run_command(args: argparse.Namespace) -> dict[str, Any]:
    root = Path(args.repo_root).resolve() if args.repo_root else None
    if args.command == "hash":
        return emit(cmd_hash(Path(args.path)))

    paths = NovelPaths(resolve_novel_dir(args.novel, root=root))
    if args.command in {"inspect", "lock-inspect"}:
        payload = cmd_inspect(paths)
        ok = payload["verdict"] != "orphan"
        return emit(payload, ok=ok, code=payload["code"], message=payload["reason"])
    if args.command == "lock-release":
        payload = cmd_lock_release(paths)
        return emit(payload, message=payload.get("message"))
    if args.command == "resolve":
        return emit(cmd_resolve(paths, args.text))
    if args.command == "begin":
        return emit(cmd_begin(paths, load_evidence(args), archive=args.archive))
    if args.command == "apply-design":
        result = cmd_apply_design(paths, Path(args.file))
        return emit(result, ok=bool(result.get("ok")), code=result.get("code", "OK"), message=result.get("message"))
    if args.command == "apply-meta":
        result = cmd_apply_meta(paths, Path(args.file))
        return emit(result, ok=bool(result.get("ok")), code=result.get("code", "OK"), message=result.get("message"))
    if args.command == "fail":
        result = cmd_fail(paths, args.reason)
        return emit(result, ok=False, code="FAILED", message=result.get("message"))
    if args.command == "resume":
        return emit(cmd_resume(paths))
    if args.command == "close-orphan":
        result = cmd_close_orphan(paths, args.reason)
        return emit(result, ok=True, code="FAILED", message=result.get("message"))
    raise OpError("USAGE", f"未知のコマンド: {args.command}")


def main(argv: list[str] | None = None) -> int:
    configure_stdio_utf8()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        payload = run_command(args)
    except OpError as exc:
        print_json({"ok": False, "code": exc.code, "message": exc.message, "detail": exc.payload})
        return EXIT_USAGE if exc.code == "USAGE" else EXIT_INCOMPLETE
    print_json(payload)
    if payload.get("ok"):
        return EXIT_OK
    return EXIT_INCOMPLETE


if __name__ == "__main__":
    raise SystemExit(main())
