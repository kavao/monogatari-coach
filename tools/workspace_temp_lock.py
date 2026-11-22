"""一時物の整理操作をプロセス間で排他する。"""

from contextlib import contextmanager
import os
from pathlib import Path
import stat

from workspace_temp_inventory import is_link


@contextmanager
def operation_lock(root: Path, *, maintenance: bool = False):
    workspace = root / "_workingspace"
    temporary = workspace / "tmp"
    info = workspace.lstat()
    if is_link(info) or not stat.S_ISDIR(info.st_mode):
        raise ValueError(f"通常のフォルダではありません: {workspace}")
    temporary.mkdir(exist_ok=True)
    info = temporary.lstat()
    if is_link(info) or not stat.S_ISDIR(info.st_mode):
        raise ValueError(f"通常のフォルダではありません: {temporary}")
    quarantine = temporary / "_quarantine"
    quarantine.mkdir(exist_ok=True)
    info = quarantine.lstat()
    if is_link(info) or not stat.S_ISDIR(info.st_mode):
        raise ValueError("退避先が通常のフォルダではありません")
    lock_path = quarantine / (".maintenance.lock" if maintenance else ".operations.lock")
    try:
        descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        info = lock_path.lstat()
        if is_link(info) or not stat.S_ISREG(info.st_mode):
            raise ValueError("ロックが通常のファイルではありません") from None
        descriptor = os.open(lock_path, os.O_RDWR)
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
            os.close(descriptor)
            raise ValueError("ロックの確認中にファイルが変更されました") from None
    try:
        if os.name == "nt":
            import msvcrt

            os.lseek(descriptor, 0, os.SEEK_SET)
            try:
                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise RuntimeError("別の整理操作が実行中です") from exc
        else:
            import fcntl

            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RuntimeError("別の整理操作が実行中です") from exc
        try:
            yield
        finally:
            if os.name == "nt":
                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)
