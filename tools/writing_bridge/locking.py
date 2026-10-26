"""Scene-local process lock. OS releases the lock even after process failure."""
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from pathlib import Path
import os
import re

from work_paths import WorkPathError, ensure_not_migrating, legacy_location, unit_present

from .errors import BridgeError
from .paths import writing_scene_dir

_held = ContextVar("writing_locks", default=frozenset())


@contextmanager
def scene_lock(work: Path, scene_id: str):
    if not re.fullmatch(r"ch\d{2,}-\d{3,}", scene_id):
        raise BridgeError("BAD_ID", "invalid scene_id")
    # ロックは場面の組の一部。組と同じ置き場（古い _writing/ か新しい _work/writing/）で取る。
    scene_dir = writing_scene_dir(work, scene_id)
    path = scene_dir / ".operation.lock"
    if path in _held.get():
        yield
        return
    # ロックファイルは解放後も残し、どの経路でも消さない（解放してから消すと、その間に別のプロセスが
    # 取ったロックを消してしまう）。古い置き場を選んだときはフォルダを作らない。開く時点で場面の
    # フォルダが無ければ、解決したあとに移行が終わったとして、何も作らずに止める
    # （古い置き場に組を作り直さない）。新しい置き場で始める場面だけフォルダを作る。
    chose_legacy = scene_dir == legacy_location(work.resolve(), "writing", scene_id)
    if not chose_legacy:
        path.parent.mkdir(parents=True, exist_ok=True)
    try:
        handle = path.open("a+b")
    except FileNotFoundError as error:
        raise BridgeError(
            "STALE_LOCATION",
            "scene location changed; run the command again",
            refs={"expected": scene_dir.as_posix()},
        ) from error
    with handle:
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
        try:
            _revalidate(work, scene_id, scene_dir)
        except BridgeError:
            _unlock(handle)
            raise
        token = _held.set(_held.get() | {path})
        try:
            yield
        finally:
            _held.reset(token)
            _unlock(handle)


def _revalidate(work: Path, scene_id: str, expected: Path) -> None:
    """排他を取ったあとに、場面の置き場がまだ有効かを確かめ直す。

    - 移行中の印がある（印を作る前に解決を済ませていた操作との競合）。
    - 選ばなかったほうの置き場に組がある（解決したあとに移行が終わって組が移っていた）。
    どちらも STALE_LOCATION で止める。自分のロックファイルは選んだ置き場の側にあるので、
    「選ばなかったほうが空か」だけを見れば、自分のロックを組として数えずに判定できる。
    """
    root = work.resolve()
    try:
        ensure_not_migrating(root, "writing", scene_id)
    except WorkPathError as error:
        raise BridgeError(
            "STALE_LOCATION", f"scene is migrating; run the command again later ({error})", refs=error.refs
        ) from error
    chose_legacy = expected == legacy_location(root, "writing", scene_id)
    other = "new" if chose_legacy else "legacy"
    if unit_present(root, "writing", scene_id, other):
        raise BridgeError(
            "STALE_LOCATION",
            "scene location changed; run the command again",
            refs={"expected": expected.as_posix(), "other_layout": other},
        )


def _unlock(handle) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def locked_scene(function):
    @wraps(function)
    def wrapped(work_root, *, scene_id, **kwargs):
        with scene_lock(Path(work_root), scene_id):
            return function(work_root, scene_id=scene_id, **kwargs)
    return wrapped
