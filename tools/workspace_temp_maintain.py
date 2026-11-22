"""Opt-in, bounded maintenance of expired temporary runs."""

from __future__ import annotations

import argparse
import json
import os
import stat
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from workspace_temp_inventory import entries, inspect_path, is_link, read_hold
from workspace_temp_lock import operation_lock
from workspace_temp_quarantine import delete_item, list_items, quarantine_item

INTERVAL = timedelta(hours=24)


def enabled(root: Path) -> bool:
    path = root / '_workingspace' / 'tmp' / 'retention.json'
    try:
        for parent in (path.parent.parent, path.parent):
            info = parent.lstat()
            if is_link(info) or not stat.S_ISDIR(info.st_mode):
                return False
        info = path.lstat()
        if is_link(info) or not stat.S_ISREG(info.st_mode):
            return False
        data = json.loads(path.read_text(encoding='utf-8'))
        return isinstance(data, dict) and data.get('auto') is True
    except (OSError, UnicodeError, ValueError):
        return False


def record_event(root: Path, event: dict[str, object]) -> None:
    """Append only to a verified local regular file, without following links."""
    folder = root / '_workingspace' / 'tmp' / '_quarantine'
    for parent in (root / '_workingspace', folder.parent, folder):
        info = parent.lstat()
        if is_link(info) or not stat.S_ISDIR(info.st_mode):
            raise ValueError('整理記録の親が通常のフォルダではありません')
    path = folder / '.maintenance.jsonl'
    try:
        info = path.lstat()
    except FileNotFoundError:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    else:
        if is_link(info) or not stat.S_ISREG(info.st_mode):
            raise ValueError('整理記録が通常のファイルではありません')
        fd = os.open(path, os.O_WRONLY | os.O_APPEND)
        opened = os.fstat(fd)
        if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
            os.close(fd)
            raise ValueError('整理記録が変更されました')
    with os.fdopen(fd, 'a', encoding='utf-8') as stream:
        stream.write(json.dumps(event, ensure_ascii=False) + '\n')


class UnsafeCheckpoint(ValueError):
    """The checkpoint is not a regular file and must not be moved."""


class InvalidCheckpoint(ValueError):
    """The regular checkpoint cannot provide a usable timestamp."""


def read_checkpoint(path: Path) -> datetime | None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise InvalidCheckpoint(str(exc)) from exc
    if is_link(info) or not stat.S_ISREG(info.st_mode):
        raise UnsafeCheckpoint('前回の整理記録が通常のファイルではありません')
    try:
        fd = os.open(path, os.O_RDONLY)
        with os.fdopen(fd, 'r', encoding='utf-8') as stream:
            opened = os.fstat(stream.fileno())
            if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
                raise UnsafeCheckpoint('整理記録の確認中にファイルが変更されました')
            data = json.load(stream)
        last = datetime.fromisoformat(data['started_at'])
        if last.tzinfo is None or last.utcoffset() is None:
            raise ValueError('日時にタイムゾーンがありません')
        # Reject values whose interval cannot be calculated.
        last + INTERVAL
        return last
    except UnsafeCheckpoint:
        raise
    except (OSError, UnicodeError, ValueError, KeyError, TypeError, OverflowError) as exc:
        raise InvalidCheckpoint(str(exc)) from exc


def write_checkpoint(path: Path, now: datetime) -> None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    else:
        if is_link(info) or not stat.S_ISREG(info.st_mode):
            raise UnsafeCheckpoint('整理記録が通常のファイルではありません')
        fd = os.open(path, os.O_WRONLY)
        opened = os.fstat(fd)
        if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
            os.close(fd)
            raise UnsafeCheckpoint('整理記録の確認中にファイルが変更されました')
        os.ftruncate(fd, 0)
    with os.fdopen(fd, 'w', encoding='utf-8') as stream:
        json.dump({'started_at': now.isoformat()}, stream)


def failure_recent(folder: Path, now: datetime) -> bool:
    try:
        last = read_checkpoint(folder / '.maintenance.failure.json')
    except (InvalidCheckpoint, UnsafeCheckpoint):
        # If the throttle itself is unsafe or unreadable, avoid repeated reports.
        return True
    return last is not None and now < last + INTERVAL


def checkpoint_failure(root: Path, folder: Path, now: datetime, error: str) -> dict[str, object]:
    if failure_recent(folder, now):
        return {'status': 'recent', 'quarantined': 0, 'deleted': 0, 'errors': []}
    try:
        write_checkpoint(folder / '.maintenance.failure.json', now)
    except (OSError, UnsafeCheckpoint):
        # Without a durable throttle, suppress repeated reports and leave the
        # unsafe checkpoint untouched for manual inspection.
        return {'status': 'recent', 'quarantined': 0, 'deleted': 0, 'errors': []}
    record_event(root, {'at': now.isoformat(), 'action': 'checkpoint_error',
                        'ok': False, 'error': error})
    return {'status': 'error', 'quarantined': 0, 'deleted': 0, 'errors': [error]}


def repair_checkpoint(root: Path, checkpoint: Path, now: datetime, error: str) -> dict[str, object]:
    try:
        info = checkpoint.lstat()
        if is_link(info) or not stat.S_ISREG(info.st_mode):
            raise UnsafeCheckpoint('前回の整理記録が通常のファイルではありません')
        suffix = now.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        backup = checkpoint.with_name(checkpoint.name + '.broken-' + suffix)
        # Do not overwrite an existing backup even when the clock repeats.
        index = 1
        while os.path.lexists(backup):
            backup = checkpoint.with_name(checkpoint.name + '.broken-' + suffix + f'-{index}')
            index += 1
        current = checkpoint.lstat()
        if (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino) or is_link(current):
            raise UnsafeCheckpoint('整理記録の確認中にファイルが変更されました')
        os.rename(checkpoint, backup)
        write_checkpoint(checkpoint, now)
        record_event(root, {'at': now.isoformat(), 'action': 'checkpoint_repaired',
                            'ok': False, 'error': error, 'backup': backup.name})
        return {'status': 'error', 'quarantined': 0, 'deleted': 0, 'errors': [error]}
    except (OSError, UnsafeCheckpoint) as exc:
        return checkpoint_failure(root, checkpoint.parent, now, f'整理記録を復旧できません: {exc}')


def maintain(root: Path, *, now: datetime | None = None, budget: float = 3.0) -> dict[str, object]:
    now = now or datetime.now(timezone.utc)
    result: dict[str, object] = {'status': 'disabled', 'quarantined': 0, 'deleted': 0, 'errors': []}
    if not enabled(root):
        return result
    deadline = time.monotonic() + budget
    with operation_lock(root, maintenance=True):
        folder = root / '_workingspace' / 'tmp' / '_quarantine'
        checkpoint = folder / '.maintenance.json'
        try:
            last = read_checkpoint(checkpoint)
        except UnsafeCheckpoint as exc:
            return checkpoint_failure(root, folder, now, str(exc))
        except InvalidCheckpoint as exc:
            return repair_checkpoint(root, checkpoint, now, str(exc))
        if last is not None and now < last + INTERVAL:
            result['status'] = 'recent'
            return result
        # Claim the interval while holding the lock, including interrupted runs.
        write_checkpoint(checkpoint, now)
        result['status'] = 'completed'
        errors = result['errors']
        assert isinstance(errors, list)

        def perform(action: str, path: str, fn) -> None:
            try:
                item_id = fn()
                event = {'at': now.isoformat(), 'action': action, 'path': path, 'id': item_id, 'ok': True}
                result[action] = int(result[action]) + 1
            except Exception as exc:
                event = {'at': now.isoformat(), 'action': action, 'path': path, 'ok': False,
                         'error': f'{type(exc).__name__}: {exc}'}
                errors.append(event['error'])
            record_event(root, event)

        # Only records whose source was an immediate child of runs/ may be deleted.
        for row in list_items(root):
            source = row.get('source')
            if not isinstance(source, str):
                continue
            parts = source.split('/')
            if (row.get('category') != 'runs' or row.get('state') != 'quarantined'
                    or len(parts) != 4 or parts[:3] != ['_workingspace', 'tmp', 'runs']
                    or parts[3] in {'', '.', '..'}):
                continue
            try:
                moved = datetime.fromisoformat(str(row.get('moved_at', '')))
                if moved.tzinfo is None or now < moved + timedelta(days=14):
                    continue
                item_id = str(row['id'])
                payload = folder / item_id / 'payload'
                inspect_path(payload)
                if read_hold(payload, now):
                    continue
            except (KeyError, ValueError, OSError):
                continue
            if time.monotonic() >= deadline:
                result['status'] = 'time_limit'
                break
            perform('deleted', source, lambda item_id=item_id: delete_item(root, item_id, now) or item_id)
        if result['status'] != 'time_limit':
            for row in entries(root, now):
                if row.get('category') != 'runs' or row.get('status') != '期限切れ':
                    continue
                if time.monotonic() >= deadline:
                    result['status'] = 'time_limit'
                    break
                path = str(row['path'])
                fingerprint = str(row['fingerprint'])
                perform('quarantined', path, lambda path=path, fingerprint=fingerprint:
                        quarantine_item(root, path, expected_fingerprint=fingerprint))
        if result['status'] == 'time_limit':
            errors.append('時間の上限に達しました')
            record_event(root, {'at': now.isoformat(), 'action': 'time_limit', 'ok': False})
    return result


def launch(root: Path) -> dict[str, object]:
    if not enabled(root):
        return {'status': 'disabled', 'quarantined': 0, 'deleted': 0, 'errors': []}
    # This is an advisory fast path. The worker repeats the check under its lock.
    folder = root / '_workingspace' / 'tmp' / '_quarantine'
    try:
        info = folder.lstat()
        if not is_link(info) and stat.S_ISDIR(info.st_mode):
            now = datetime.now(timezone.utc)
            try:
                last = read_checkpoint(folder / '.maintenance.json')
            except UnsafeCheckpoint:
                if failure_recent(folder, now):
                    return {'status': 'recent', 'quarantined': 0, 'deleted': 0, 'errors': []}
            except InvalidCheckpoint:
                pass
            else:
                if last is not None and now < last + INTERVAL:
                    return {'status': 'recent', 'quarantined': 0, 'deleted': 0, 'errors': []}
    except OSError:
        pass
    try:
        process = subprocess.run(
            [sys.executable, '-B', str(Path(__file__).resolve()), '--root', str(root)],
            capture_output=True, text=True, encoding='utf-8', timeout=8, check=False,
            env={**os.environ, 'PYTHONUTF8': '1'},
        )
        result = json.loads(process.stdout)
        if not isinstance(result, dict):
            raise ValueError('整理結果がオブジェクトではありません')
        if process.returncode and not result.get('errors'):
            raise RuntimeError(f'整理が終了コード {process.returncode} で終了しました')
        return result
    except Exception as exc:
        error = f'{type(exc).__name__}: {exc}'
        try:
            record_event(root, {'at': datetime.now(timezone.utc).isoformat(),
                                'action': 'launch_error', 'ok': False, 'error': error})
        except Exception:
            pass
        return {'status': 'error', 'quarantined': 0, 'deleted': 0, 'errors': [error]}


def main() -> int:
    parser = argparse.ArgumentParser(description='一時作業の自動整理')
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parent.parent)
    args = parser.parse_args()
    try:
        result = maintain(args.root.resolve())
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as exc:
        # Another maintenance worker owns the interval and will report its result.
        # Treating this as a new failure could duplicate checkpoint warnings.
        if isinstance(exc, RuntimeError) and str(exc) == '別の整理操作が実行中です':
            print(json.dumps({'status': 'recent', 'quarantined': 0, 'deleted': 0, 'errors': []}))
            return 0
        try:
            record_event(args.root.resolve(), {'at': datetime.now(timezone.utc).isoformat(),
                                             'action': 'error', 'ok': False,
                                             'error': f'{type(exc).__name__}: {exc}'})
        except Exception:
            pass
        print(json.dumps({'status': 'error', 'quarantined': 0, 'deleted': 0,
                          'errors': [f'{type(exc).__name__}: {exc}']}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    sys.exit(main())
