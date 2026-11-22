import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import workspace_temp_maintain as maintain  # noqa: E402
from workspace_audit_log import main as audit_main  # noqa: E402
from workspace_temp_inventory import entries  # noqa: E402
from workspace_temp_lock import operation_lock  # noqa: E402
from workspace_temp_quarantine import list_items, quarantine_item  # noqa: E402


def config(root: Path, content: str = '{"auto": true}') -> None:
    tmp = root / '_workingspace' / 'tmp'
    tmp.mkdir(parents=True, exist_ok=True)
    (tmp / 'retention.json').write_text(content, encoding='utf-8')


def old_run(root: Path, name: str, *, hold: str | None = None) -> Path:
    run = root / '_workingspace' / 'tmp' / 'runs' / name
    run.mkdir(parents=True)
    (run / 'data.txt').write_text(name, encoding='utf-8')
    if hold is not None:
        (run / '.run.json').write_text(hold, encoding='utf-8')
    old = (datetime.now(timezone.utc) - timedelta(days=32)).timestamp()
    os.utime(run / 'data.txt', (old, old))
    os.utime(run, (old, old))
    return run


def age_record(root: Path, item_id: str) -> None:
    record = root / '_workingspace' / 'tmp' / '_quarantine' / item_id / 'record.json'
    data = json.loads(record.read_text(encoding='utf-8'))
    data['moved_at'] = (datetime.now(timezone.utc) - timedelta(days=15)).isoformat()
    record.write_text(json.dumps(data), encoding='utf-8')


@pytest.mark.parametrize('content', [None, '', '{', '{"auto": false}', '{"auto": 1}'])
def test_disabled_configuration_does_nothing(tmp_path: Path, content: str | None) -> None:
    run = old_run(tmp_path, 'old')
    if content is not None:
        config(tmp_path, content)
    assert maintain.maintain(tmp_path)['status'] == 'disabled'
    assert run.exists()
    assert not (tmp_path / '_workingspace/tmp/_quarantine').exists()


def test_only_expired_runs_and_cadence(tmp_path: Path) -> None:
    config(tmp_path)
    expired = old_run(tmp_path, 'expired')
    held = old_run(tmp_path, 'held', hold='{"hold": true, "reason": "work"}')
    invalid = old_run(tmp_path, 'invalid', hold='{')
    legacy = tmp_path / '_workingspace' / 'tmp_legacy'
    legacy.write_text('legacy', encoding='utf-8')
    result = maintain.maintain(tmp_path)
    assert result['quarantined'] == 1 and not expired.exists()
    assert held.exists() and invalid.exists() and legacy.exists()
    old_run(tmp_path, 'second')
    assert maintain.maintain(tmp_path)['status'] == 'recent'
    assert (tmp_path / '_workingspace/tmp/runs/second').exists()
    assert len(list_items(tmp_path)) == 1


def test_cadence_allows_run_at_24_hours(tmp_path: Path) -> None:
    config(tmp_path)
    now = datetime.now(timezone.utc)
    assert maintain.maintain(tmp_path, now=now)['status'] == 'completed'
    old_run(tmp_path, 'next')
    assert maintain.maintain(tmp_path, now=now + timedelta(hours=24) - timedelta(microseconds=1))['status'] == 'recent'
    assert maintain.maintain(tmp_path, now=now + timedelta(hours=24))['quarantined'] == 1


@pytest.mark.parametrize('content', [
    '{', '{}', '{"started_at": "2026-11-22T12:00:00"}',
    '{"started_at": null}', '{"started_at": "9999-12-31T23:59:59+00:00"}',
])
def test_broken_checkpoint_is_preserved_once_and_skips_cleanup(tmp_path: Path, content: str) -> None:
    config(tmp_path)
    run = old_run(tmp_path, 'old')
    folder = tmp_path / '_workingspace/tmp/_quarantine'
    folder.mkdir()
    checkpoint = folder / '.maintenance.json'
    checkpoint.write_text(content, encoding='utf-8')
    for message in ('first', 'second'):
        assert audit_main(['--repo-root', str(tmp_path), 'append', '--year-month', '202611', message]) == 0
    backups = list(folder.glob('.maintenance.json.broken-*'))
    assert len(backups) == 1 and backups[0].read_text(encoding='utf-8') == content
    assert datetime.fromisoformat(json.loads(checkpoint.read_text(encoding='utf-8'))['started_at']).tzinfo
    assert run.exists()
    events = [json.loads(line) for line in (folder / '.maintenance.jsonl').read_text(encoding='utf-8').splitlines()]
    assert len(events) == 1 and events[0]['action'] == 'checkpoint_repaired'
    log = (tmp_path / '_workingspace/log/202611.md').read_text(encoding='utf-8')
    assert log.count('失敗1件') == 1
    assert list_items(tmp_path) == []
    recovered_at = datetime.fromisoformat(json.loads(checkpoint.read_text(encoding='utf-8'))['started_at'])
    assert maintain.maintain(tmp_path, now=recovered_at + timedelta(hours=24))['quarantined'] == 1
    assert not run.exists()


def test_unreadable_regular_checkpoint_is_preserved(tmp_path: Path, monkeypatch) -> None:
    config(tmp_path)
    run = old_run(tmp_path, 'old')
    folder = tmp_path / '_workingspace/tmp/_quarantine'
    folder.mkdir()
    checkpoint = folder / '.maintenance.json'
    checkpoint.write_text('unreadable', encoding='utf-8')
    original_open = maintain.os.open
    def deny_read(path, flags, *args):
        if Path(path) == checkpoint and flags == os.O_RDONLY:
            raise PermissionError('test read failure')
        return original_open(path, flags, *args)
    monkeypatch.setattr(maintain.os, 'open', deny_read)
    assert maintain.maintain(tmp_path)['status'] == 'error'
    assert run.exists()
    assert [p.read_text(encoding='utf-8') for p in folder.glob('.maintenance.json.broken-*')] == ['unreadable']


def test_unmovable_broken_checkpoint_reports_only_once(tmp_path: Path, monkeypatch) -> None:
    config(tmp_path)
    folder = tmp_path / '_workingspace/tmp/_quarantine'
    folder.mkdir()
    checkpoint = folder / '.maintenance.json'
    checkpoint.write_text('{', encoding='utf-8')
    def denied(*args):
        raise PermissionError('test rename failure')
    monkeypatch.setattr(maintain.os, 'rename', denied)
    assert maintain.maintain(tmp_path)['status'] == 'error'
    assert maintain.maintain(tmp_path)['status'] == 'recent'
    assert checkpoint.read_text(encoding='utf-8') == '{'
    events = (folder / '.maintenance.jsonl').read_text(encoding='utf-8').splitlines()
    assert len(events) == 1 and json.loads(events[0])['action'] == 'checkpoint_error'


def test_recent_launch_does_not_start_subprocess(tmp_path: Path, monkeypatch) -> None:
    config(tmp_path)
    folder = tmp_path / '_workingspace/tmp/_quarantine'
    folder.mkdir()
    now = datetime.now(timezone.utc)
    (folder / '.maintenance.json').write_text(json.dumps({'started_at': now.isoformat()}), encoding='utf-8')
    def unexpected(*args, **kwargs):
        raise AssertionError('subprocess must not start')
    monkeypatch.setattr(maintain.subprocess, 'run', unexpected)
    assert maintain.launch(tmp_path)['status'] == 'recent'


def test_nonregular_checkpoint_logs_at_most_once_per_day(tmp_path: Path, monkeypatch) -> None:
    config(tmp_path)
    run = old_run(tmp_path, 'old')
    folder = tmp_path / '_workingspace/tmp/_quarantine'
    folder.mkdir()
    checkpoint = folder / '.maintenance.json'
    checkpoint.mkdir()
    assert audit_main(['--repo-root', str(tmp_path), 'append', '--year-month', '202611', 'first']) == 0
    def unexpected(*args, **kwargs):
        raise AssertionError('subprocess must not start again')
    monkeypatch.setattr(maintain.subprocess, 'run', unexpected)
    assert audit_main(['--repo-root', str(tmp_path), 'append', '--year-month', '202611', 'second']) == 0
    log = (tmp_path / '_workingspace/log/202611.md').read_text(encoding='utf-8')
    assert log.count('失敗1件') == 1
    events_path = folder / '.maintenance.jsonl'
    events = [json.loads(line) for line in events_path.read_text(encoding='utf-8').splitlines()]
    assert len(events) == 1 and events[0]['action'] == 'checkpoint_error'
    assert checkpoint.is_dir() and run.exists()
    assert list_items(tmp_path) == []
    last = datetime.fromisoformat(events[0]['at'])
    assert maintain.maintain(tmp_path, now=last + timedelta(hours=24))['status'] == 'error'
    assert len(events_path.read_text(encoding='utf-8').splitlines()) == 2


def test_maintenance_lock_contention_does_not_duplicate_checkpoint_error(tmp_path: Path) -> None:
    config(tmp_path)
    folder = tmp_path / '_workingspace/tmp/_quarantine'
    folder.mkdir()
    (folder / '.maintenance.json').write_text('{', encoding='utf-8')
    with operation_lock(tmp_path, maintenance=True):
        assert audit_main(['--repo-root', str(tmp_path), 'append', '--year-month', '202611', 'first']) == 0
    assert audit_main(['--repo-root', str(tmp_path), 'append', '--year-month', '202611', 'second']) == 0
    log = (tmp_path / '_workingspace/log/202611.md').read_text(encoding='utf-8')
    assert log.count('失敗1件') == 1
    events = (folder / '.maintenance.jsonl').read_text(encoding='utf-8').splitlines()
    assert len(events) == 1 and json.loads(events[0])['action'] == 'checkpoint_repaired'


def test_time_limit_records_failure_without_processing(tmp_path: Path) -> None:
    config(tmp_path)
    run = old_run(tmp_path, 'old')
    result = maintain.maintain(tmp_path, budget=0)
    assert result['status'] == 'time_limit' and result['errors'] and run.exists()
    assert 'time_limit' in (tmp_path / '_workingspace/tmp/_quarantine/.maintenance.jsonl').read_text(encoding='utf-8')


def test_deletion_restricts_to_runs_and_requires_14_days(tmp_path: Path) -> None:
    config(tmp_path)
    old_run(tmp_path, 'old')
    old_run(tmp_path, 'young')
    legacy = tmp_path / '_workingspace' / 'tmp_legacy'
    legacy.write_text('legacy', encoding='utf-8')
    rows = {r['path']: r for r in entries(tmp_path, datetime.now(timezone.utc))}
    ids = {}
    for path, row in rows.items():
        if path in {'_workingspace/tmp/runs/old', '_workingspace/tmp/runs/young', '_workingspace/tmp_legacy'}:
            ids[path] = quarantine_item(tmp_path, path, expected_fingerprint=row['fingerprint'])
    age_record(tmp_path, ids['_workingspace/tmp/runs/old'])
    age_record(tmp_path, ids['_workingspace/tmp_legacy'])
    result = maintain.maintain(tmp_path)
    states = {r['id']: r['state'] for r in list_items(tmp_path)}
    assert result['deleted'] == 1
    assert states[ids['_workingspace/tmp/runs/old']] == 'deleted'
    assert states[ids['_workingspace/tmp/runs/young']] == 'quarantined'
    assert states[ids['_workingspace/tmp_legacy']] == 'quarantined'


def test_dry_run_does_not_trigger_maintenance(tmp_path: Path) -> None:
    config(tmp_path)
    run = old_run(tmp_path, 'old')
    assert audit_main(['--repo-root', str(tmp_path), 'append', '--dry-run', 'test']) == 0
    assert run.exists()
    assert not (tmp_path / '_workingspace/tmp/_quarantine').exists()


@pytest.mark.parametrize('failure', ['timeout', 'error'])
def test_audit_append_succeeds_if_child_fails(tmp_path: Path, monkeypatch, failure: str) -> None:
    config(tmp_path)
    with operation_lock(tmp_path):
        pass
    def fail(*args, **kwargs):
        if failure == 'timeout':
            raise subprocess.TimeoutExpired('worker', 8)
        raise OSError('worker failed')
    monkeypatch.setattr(maintain.subprocess, 'run', fail)
    assert audit_main(['--repo-root', str(tmp_path), 'append', '--year-month', '202611', 'original']) == 0
    log = (tmp_path / '_workingspace/log/202611.md').read_text(encoding='utf-8')
    assert 'original' in log and '失敗1件' in log
    assert 'launch_error' in (tmp_path / '_workingspace/tmp/_quarantine/.maintenance.jsonl').read_text(encoding='utf-8')


def test_busy_operation_lock_preserves_audit(tmp_path: Path) -> None:
    config(tmp_path)
    old_run(tmp_path, 'old')
    with operation_lock(tmp_path):
        assert audit_main(['--repo-root', str(tmp_path), 'append', '--year-month', '202611', 'original']) == 0
    assert 'original' in (tmp_path / '_workingspace/log/202611.md').read_text(encoding='utf-8')
    assert (tmp_path / '_workingspace/tmp/runs/old').exists()
    assert '失敗1件' in (tmp_path / '_workingspace/log/202611.md').read_text(encoding='utf-8')


def test_off_still_triggers_cleanup_without_audit_line(tmp_path: Path) -> None:
    config(tmp_path)
    old_run(tmp_path, 'old')
    novel = tmp_path / 'novels/001_test'
    novel.mkdir(parents=True)
    (novel / 'config.md').write_text('# config.md\n\n## 基本情報\n\n| 項目 | 内容 |\n|------|------|\n| AUDIT_LOG | OFF |\n', encoding='utf-8')
    assert audit_main(['--repo-root', str(tmp_path), 'append', '--novel', str(novel),
                       '--year-month', '202611', 'original']) == 0
    assert not (tmp_path / '_workingspace/tmp/runs/old').exists()
    assert not (tmp_path / '_workingspace/log/202611.md').exists()


def test_linked_runs_are_not_quarantined(tmp_path: Path) -> None:
    config(tmp_path)
    linked = old_run(tmp_path, 'linked')
    outside = tmp_path / 'outside.txt'
    outside.write_text('outside', encoding='utf-8')
    try:
        (linked / 'link.txt').symlink_to(outside)
    except OSError:
        pytest.skip('symbolic links unavailable')
    assert maintain.maintain(tmp_path)['quarantined'] == 0
    assert outside.read_text(encoding='utf-8') == 'outside'
    assert linked.exists()
