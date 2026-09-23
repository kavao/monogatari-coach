"""Scene-local process lock. OS releases the lock even after process failure."""
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from pathlib import Path
import os
import re

from .errors import BridgeError
from .paths import resolve_work_path

_held = ContextVar("writing_locks", default=frozenset())


@contextmanager
def scene_lock(work: Path, scene_id: str):
    if not re.fullmatch(r"ch\d{2,}-\d{3,}", scene_id):
        raise BridgeError("BAD_ID", "invalid scene_id")
    path = resolve_work_path(work.resolve(), f"_writing/{scene_id}/.operation.lock")
    if path in _held.get():
        yield
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise BridgeError("JOB_CONFLICT", "another operation holds the scene lock") from error
        token = _held.set(_held.get() | {path})
        try:
            yield
        finally:
            _held.reset(token)
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def locked_scene(function):
    @wraps(function)
    def wrapped(work_root, *, scene_id, **kwargs):
        with scene_lock(Path(work_root), scene_id):
            return function(work_root, scene_id=scene_id, **kwargs)
    return wrapped
