"""一覧した一時物の退避、復元、期限後の削除。"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import sys
import tempfile
import uuid

from workspace_temp_inventory import JAPAN_TIME, ROOT, entries, fingerprint_path, inspect_path, is_link
from workspace_temp_lock import operation_lock


def save_record(path: Path, record: dict[str, object]) -> None:
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as file:
        json.dump(record, file, ensure_ascii=False, indent=2)
        file.write("\n")
        file.flush()
        os.fsync(file.fileno())
    os.replace(temporary, path)


def get_item(root: Path, item_id: str) -> tuple[Path, dict[str, object]]:
    try:
        if uuid.UUID(item_id).hex != item_id:
            raise ValueError
    except ValueError:
        raise ValueError("退避IDが不正です") from None
    quarantine = root / "_workingspace" / "tmp" / "_quarantine"
    item = quarantine / item_id
    info = item.lstat()
    if is_link(info) or not stat.S_ISDIR(info.st_mode) or item.resolve().parent != quarantine.resolve():
        raise ValueError("退避項目が通常のフォルダではありません")
    record_path = item / "record.json"
    info = record_path.lstat()
    if is_link(info) or not stat.S_ISREG(info.st_mode):
        raise ValueError("退避記録が通常のファイルではありません")
    record = json.loads(record_path.read_text(encoding="utf-8"))
    if not isinstance(record, dict) or record.get("id") != item_id:
        raise ValueError("退避記録が不正です")
    return item, record


def validated_source(root: Path, record: dict[str, object]) -> Path:
    relative = record.get("source")
    if not isinstance(relative, str) or "\\\\" in relative or ":" in relative:
        raise ValueError("退避記録の元パスが不正です")
    parts = PurePosixPath(relative).parts
    if not parts or parts[0] != "_workingspace" or any(p in {".", ".."} for p in parts):
        raise ValueError("退避記録の元パスが不正です")
    allowed = (
        len(parts) == 2 and (parts[1].startswith(("tmp_", "_tmp_"))
                             or parts[1] in {"_intended_meta.md", "__pycache__"})
        or len(parts) == 3 and parts[1] == "tmp" and parts[2] not in {"runs", "_quarantine"}
        or len(parts) == 4 and parts[1:3] == ("tmp", "runs")
    )
    if not allowed or parts[-1] in {".gitkeep", "_novel_text_re", "_manga_ir_backup", "novelai_manga_tests"} or parts[-1].startswith(".env"):
        raise ValueError("退避記録が許可された対象を指していません")
    source = root.joinpath(*parts)
    current = root
    for part in parts[:-1]:
        current = current / part
        info = current.lstat()
        if is_link(info) or not stat.S_ISDIR(info.st_mode):
            raise ValueError("復元先の親が通常のフォルダではありません")
    if not source.parent.resolve().is_relative_to((root / "_workingspace").resolve()):
        raise ValueError("復元先が作業領域の外です")
    return source


def quarantine_item(
    root: Path, relative: str, expected_modified: str | None = None, expected_fingerprint: str = ""
) -> str:
    """一覧の確認値と一致する対象を、同一ドライブ内で退避する。"""
    with operation_lock(root):
        matches = [row for row in entries(root, datetime.now(timezone.utc)) if row["path"] == relative]
        if len(matches) != 1:
            raise ValueError("一覧にある対象を指定してください")
        row = matches[0]
        if (row.get("status") not in {"期限切れ", "要確認"}
                or (expected_modified is not None and row.get("modified") != expected_modified)
                or not expected_fingerprint or row.get("fingerprint") != expected_fingerprint):
            raise ValueError("対象が期限切れ・旧配置でないか、一覧後に変更されています")
        if row.get("status") == "要確認" and row.get("category") != "旧配置":
            raise ValueError("確認できない runs 内の対象は退避できません")
        source = root / relative
        if not source.resolve().is_relative_to((root / "_workingspace").resolve()):
            raise ValueError("対象が作業領域の外です")
        before = inspect_path(source)
        if (expected_modified is not None
                and datetime.fromtimestamp(before[2], JAPAN_TIME).isoformat() != expected_modified):
            raise ValueError("対象が一覧後に変更されています")
        quarantine = root / "_workingspace" / "tmp" / "_quarantine"
        if source.lstat().st_dev != quarantine.lstat().st_dev:
            raise ValueError("退避先が対象と異なるドライブです")
        item_id = uuid.uuid4().hex
        item = quarantine / item_id
        item.mkdir()
        record: dict[str, object] = {
            "id": item_id, "source": relative, "state": "moving",
            "category": row["category"], "kind": "directory" if source.is_dir() else "file", "moved_at": None,
            "move_fingerprint": fingerprint_path(source, ignore_root_ctime=True),
        }
        save_record(item / "record.json", record)
        if inspect_path(source) != before or fingerprint_path(source) != expected_fingerprint:
            record["state"] = "move_failed"
            save_record(item / "record.json", record)
            raise ValueError("退避前に対象が変更されました")
        try:
            os.rename(source, item / "payload")
        except OSError as exc:
            record["error"] = f"退避に失敗: {type(exc).__name__}"
            save_record(item / "record.json", record)
            raise
        record["state"] = "quarantined"
        record["payload_fingerprint"] = fingerprint_path(item / "payload")
        record["moved_at"] = datetime.now(timezone.utc).isoformat()
        save_record(item / "record.json", record)
        return item_id


def recover_move(root: Path, item_id: str) -> None:
    """移動直後に停止した記録を、退避日時を現在時刻として確定する。"""
    with operation_lock(root):
        item, record = get_item(root, item_id)
        if record.get("state") != "moving":
            raise ValueError("復旧対象の退避記録ではありません")
        source = validated_source(root, record)
        if os.path.lexists(source) or not (item / "payload").exists():
            raise ValueError("移動元と退避先を一意に確認できません")
        inspect_path(item / "payload")
        if fingerprint_path(item / "payload", ignore_root_ctime=True) != record.get("move_fingerprint"):
            raise ValueError("退避内容が移動前の記録と一致しません")
        record.update(state="quarantined", moved_at=datetime.now(timezone.utc).isoformat(),
                      payload_fingerprint=fingerprint_path(item / "payload"))
        save_record(item / "record.json", record)


def mark_restored_hold(directory: Path) -> None:
    metadata = directory / ".run.json"
    data: dict[str, object] = {}
    try:
        info = metadata.lstat()
    except FileNotFoundError:
        pass
    else:
        if is_link(info) or not stat.S_ISREG(info.st_mode):
            raise ValueError("復元する保留情報が通常のファイルではありません")
        try:
            existing = json.loads(metadata.read_text(encoding="utf-8"))
        except (ValueError, UnicodeError):
            return  # 不正な保留情報は一覧側で保留扱いになる。
        if not isinstance(existing, dict) or not isinstance(existing.get("hold"), bool):
            return
        data = existing
    data.update(hold=True, reason="退避から復元", hold_since=datetime.now(timezone.utc).isoformat())
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=directory,
                                         prefix=".hold-", delete=False) as file:
            temporary = Path(file.name)
            json.dump(data, file, ensure_ascii=False, indent=2)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, metadata)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def restore_item(root: Path, item_id: str) -> Path:
    """フォルダは元の場所へ、単独ファイルは保留付きフォルダへ戻す。"""
    with operation_lock(root):
        item, record = get_item(root, item_id)
        if record.get("state") not in {"quarantined", "restoring"}:
            raise ValueError("復元できる退避状態ではありません")
        source = validated_source(root, record)
        payload = item / "payload"
        kind = record.get("kind")
        if kind == "directory":
            target = source
        elif kind == "file":
            runs = root / "_workingspace" / "tmp" / "runs"
            runs.mkdir(exist_ok=True)
            info = runs.lstat()
            if is_link(info) or not stat.S_ISDIR(info.st_mode):
                raise ValueError("runs が通常のフォルダではありません")
            target = runs / f"restored_{item_id}" / source.name
        else:
            raise ValueError("退避対象の種類が不正です")
        if record.get("state") == "restoring" and not payload.exists() and target.exists():
            info = target.lstat()
            if (is_link(info) or not info.st_ino or info.st_ino != record.get("restore_inode")
                    or info.st_dev != record.get("restore_device")):
                raise ValueError("復元先の同一性を確認できません")
            record.update(state="restored", restored_at=datetime.now(timezone.utc).isoformat())
            save_record(item / "record.json", record)
            return target
        if target.exists() or target.is_symlink():
            raise ValueError("復元先が既に存在します")
        inspect_path(payload)
        initial_state = record.get("state")
        info = payload.lstat()
        if initial_state == "restoring" and (info.st_ino != record.get("restore_inode")
                                             or info.st_dev != record.get("restore_device")):
            raise ValueError("復元対象が変更されています")
        if kind == "file" and initial_state == "quarantined" and target.parent.exists():
            raise ValueError("復元先フォルダが既に存在します")
        record.update(state="restoring", restore_target=target.relative_to(root).as_posix(),
                      restore_inode=info.st_ino, restore_device=info.st_dev)
        save_record(item / "record.json", record)
        if kind == "directory":
            mark_restored_hold(payload)
        else:
            wrapper = target.parent
            try:
                wrapper.mkdir()
            except FileExistsError:
                if initial_state != "restoring":
                    raise ValueError("復元先フォルダが既に存在します") from None
                info = wrapper.lstat()
                if is_link(info) or not stat.S_ISDIR(info.st_mode):
                    raise ValueError("復元先フォルダが不正です") from None
            mark_restored_hold(wrapper)
        try:
            os.rename(payload, target)
        except OSError as exc:
            record["error"] = f"復元に失敗: {type(exc).__name__}"
            save_record(item / "record.json", record)
            raise
        record.update(state="restored", restored_at=datetime.now(timezone.utc).isoformat())
        save_record(item / "record.json", record)
        return target


def delete_item(root: Path, item_id: str, now: datetime, *, retry_fingerprint: str | None = None) -> None:
    """退避後14日を経過した対象を再検査して削除する。"""
    with operation_lock(root):
        item, record = get_item(root, item_id)
        state = record.get("state")
        if state == "delete_failed":
            if retry_fingerprint is None:
                raise ValueError("削除失敗の再試行には残存内容の確認が必要です")
        elif state not in {"quarantined", "deleting"} or retry_fingerprint is not None:
            raise ValueError("削除できる退避状態ではありません")
        moved_at = datetime.fromisoformat(str(record.get("moved_at", "")))
        if moved_at.tzinfo is None or now < moved_at + timedelta(days=14):
            raise ValueError("退避から14日経過していません")
        payload = item / "payload"
        if not payload.resolve().is_relative_to(item.resolve()):
            raise ValueError("削除対象が退避先の外です")
        if not os.path.lexists(payload) and state == "delete_failed":
            if retry_fingerprint != "missing":
                raise ValueError("残存内容なしの確認が必要です")
            record.update(state="deleted", deleted_at=now.isoformat(), previous_error=record.pop("error", None))
            save_record(item / "record.json", record)
            return
        if not payload.exists() and state == "deleting":
            record.update(state="deleted", deleted_at=now.isoformat())
            save_record(item / "record.json", record)
            return
        if record.get("state") == "deleting":
            raise ValueError("削除が途中で中断しています。残った内容を確認してください")
        inspect_path(payload)
        current_fingerprint = fingerprint_path(payload)
        if state == "delete_failed":
            if current_fingerprint != retry_fingerprint:
                raise ValueError("確認後に残存内容が変更されています")
            record["payload_fingerprint"] = current_fingerprint
            record["previous_error"] = record.pop("error", None)
            record["retry_count"] = int(record.get("retry_count", 0)) + 1
        elif current_fingerprint != record.get("payload_fingerprint"):
            raise ValueError("退避後に内容が変更されています")
        record["state"] = "deleting"
        save_record(item / "record.json", record)
        try:
            inspect_path(payload)
            if fingerprint_path(payload) != record.get("payload_fingerprint"):
                raise ValueError("削除直前に内容が変更されました")
            if payload.is_dir():
                shutil.rmtree(payload)
            else:
                payload.unlink()
        except Exception as exc:
            record["state"] = "delete_failed"
            record["error"] = f"削除に失敗: {type(exc).__name__}"
            save_record(item / "record.json", record)
            raise
        record.update(state="deleted", deleted_at=now.isoformat())
        save_record(item / "record.json", record)


def list_items(root: Path) -> list[dict[str, object]]:
    """退避先の記録を読み取り専用で一覧する。"""
    quarantine = root / "_workingspace" / "tmp" / "_quarantine"
    for directory in (root / "_workingspace", root / "_workingspace" / "tmp", quarantine):
        try:
            info = directory.lstat()
        except FileNotFoundError:
            return []
        if is_link(info) or not stat.S_ISDIR(info.st_mode):
            raise ValueError("退避先または親が通常のフォルダではありません")
    rows: list[dict[str, object]] = []
    with os.scandir(quarantine) as found:
        names = sorted(entry.name for entry in found
                       if entry.name not in {
                           ".operations.lock", ".maintenance.lock", ".maintenance.json",
                           ".maintenance.jsonl", ".maintenance.failure.json",
                       } and not entry.name.startswith(".maintenance.json.broken-"))
    for name in names:
        try:
            item, record = get_item(root, name)
            if record.get("state") == "delete_failed":
                payload = item / "payload"
                if not os.path.lexists(payload):
                    record["remaining_fingerprint"] = "missing"
                    record["remaining_files"] = 0
                    record["remaining_bytes"] = 0
                else:
                    try:
                        count, size, _ = inspect_path(payload)
                        record["remaining_fingerprint"] = fingerprint_path(payload)
                        record["remaining_files"] = count
                        record["remaining_bytes"] = size
                    except (OSError, ValueError) as exc:
                        record["remaining_error"] = str(exc)
            moved_at = record.get("moved_at")
            if isinstance(moved_at, str):
                moved = datetime.fromisoformat(moved_at)
                if moved.tzinfo is None:
                    raise ValueError("退避日時にタイムゾーンがありません")
                record["delete_after"] = (moved + timedelta(days=14)).astimezone(JAPAN_TIME).isoformat()
            rows.append(record)
        except (OSError, ValueError, UnicodeError) as exc:
            rows.append({"id": name, "state": "要確認", "reason": str(exc)})
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="一時物の退避と期限後の削除")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="退避記録を読み取り専用で一覧")
    move = commands.add_parser("quarantine", help="一覧した一項目を退避")
    move.add_argument("path", help="一覧に表示された相対パス")
    move.add_argument("--modified", help="一覧に表示された更新日時（任意）")
    move.add_argument("--fingerprint", required=True, help="一覧に表示された変更検出値")
    recover = commands.add_parser("recover-move", help="中断した退避記録を確認")
    recover.add_argument("id")
    restore = commands.add_parser("restore", help="退避した一項目を保留付きで復元")
    restore.add_argument("id")
    delete = commands.add_parser("delete", help="退避から14日後に一項目を完全削除")
    delete.add_argument("id")
    retry = commands.add_parser("retry-delete", help="確認した削除失敗の残存物を再削除")
    retry.add_argument("id")
    retry.add_argument("--fingerprint", required=True, help="list で確認した remaining_fingerprint")
    args = parser.parse_args()
    try:
        if args.command == "list":
            print(json.dumps(list_items(ROOT), ensure_ascii=False, indent=2))
        elif args.command == "quarantine":
            print(quarantine_item(ROOT, args.path, args.modified, args.fingerprint))
        elif args.command == "recover-move":
            recover_move(ROOT, args.id)
            print("退避記録を復旧しました")
        elif args.command == "restore":
            print(restore_item(ROOT, args.id))
        else:
            retry_fingerprint = args.fingerprint if args.command == "retry-delete" else None
            delete_item(ROOT, args.id, datetime.now(timezone.utc), retry_fingerprint=retry_fingerprint)
            print("退避項目を削除しました")
    except (OSError, ValueError, RuntimeError, UnicodeError) as exc:
        print(f"整理操作を実行できません: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
