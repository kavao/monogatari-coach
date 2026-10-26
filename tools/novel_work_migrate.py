"""作品フォルダの機械の記録を、古い置き場から新しい置き場（`_work/`）へ組ごとに移す。

計画: _workingspace/plans/20261024_work-folder-layout.md §3.1「移す手順」・M6

    uv run python tools/novel_work_migrate.py novels/<作品> --dry-run   # 何をどこへ移すかを表示（書かない）
    uv run python tools/novel_work_migrate.py novels/<作品>             # 移す
    uv run python tools/novel_work_migrate.py novels/<作品> --recover   # 中断した移行を記録から復旧する

手順（組ごと）:
1. 組の排他を各ツールと同じ方法で取り、終わっていない操作が無いことを確かめる。
2. 移行の記録 `_work/.migrating/<kind>/<unit>.json` を `copying` で作り、排他を放す
   （記録がある組はどのツールも MIGRATING で拒否する。Windows ではロック中のファイルを含むフォルダを動かせない）。
3. 一時領域 `_work/.migrating/<kind>/<unit>/` へ写し、ハッシュを照らして `verified`。
4. `switching` にして、古い組を `<unit>.old/` へ名前の変更で退け、写しを新しい置き場へ名前の変更で置く。
   古い組を退ける最初の名前の変更に失敗したら（Windows で誰かがファイルを開いている等）、何も動かさずに戻す。
5. 新しい置き場のハッシュを照らして `switched`。`.old` と移行の記録を消す。

古い置き場のファイルを直接消す手順は持たない（退けるのは名前の変更だけ）。中断したら `--recover` が
記録の状態から、組を古い置き場か新しい置き場のどちらか一か所に完全な形で戻す。
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from work_paths import (  # noqa: E402
    DIR_KIND_ROOTS,
    MIGRATING_DIR,
    STORY_REFLECTION_FILES,
    STORY_REFLECTION_UNIT,
    WorkPathError,
    iter_unit_ids,
    legacy_location,
    migration_marker,
    new_location,
    resolve_unit,
)

KINDS = ("story_reflection", "writing", "metron", "reader")

# 置き場の規則の外にある古い作業フォルダ（ストーリー反映の材料の即興の置き場）。中身はそのまま、
# `_work/story_reflection/staging/<名前>/` へフォルダごと名前を変えて移す。
LOOSE_STAGING = (("_story_work", "legacy_story_work"), ("_reader/_sr_staging", "legacy_sr_staging"))


class MigrationError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class _Interrupt(Exception):
    """テスト用: 指定した段階の直後で止める（電源断や強制終了の代わり）。"""


# テストから段階の直後で止めるためのフック。None なら止めない。
STOP_AFTER: Callable[[str], bool] | None = None


def _checkpoint(step: str) -> None:
    if STOP_AFTER is not None and STOP_AFTER(step):
        raise _Interrupt(step)


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _rel(work: Path, path: Path) -> str:
    return path.relative_to(work).as_posix()


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


@contextmanager
def migration_lock(work: Path) -> Iterator[None]:
    """移行と復旧の全期間を守る、作品ごとの共通の排他（`_work/.migrating/.migrate.lock`）。

    実行中の移行に復旧が割り込んで移行の記録を消すと、古い組が編集できるようになり、そのあと移行が続くと
    写したあとの編集が失われる。移行（組1つ分）と復旧は、どちらもこの排他を全期間持つ。取れなければ止める。
    ロックファイルは解放後も残し、消さない。
    """
    root = work.joinpath(*MIGRATING_DIR.split("/"))
    root.mkdir(parents=True, exist_ok=True)
    handle = (root / ".migrate.lock").open("a+b")
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
            raise MigrationError("MIGRATION_RUNNING", "別の移行か復旧が実行中。終わってからもう一度実行する") from error
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@dataclass(frozen=True)
class Unit:
    kind: str
    unit_id: str

    @property
    def label(self) -> str:
        return f"{self.kind}/{self.unit_id}"


def _staging_dir(work: Path, unit: Unit) -> Path:
    return work.joinpath(*MIGRATING_DIR.split("/")) / unit.kind / unit.unit_id


def _old_dir(work: Path, unit: Unit) -> Path:
    return work.joinpath(*MIGRATING_DIR.split("/")) / unit.kind / f"{unit.unit_id}.old"


# ── 組のファイルの一覧（古い置き場のパス → 新しい置き場のパス） ─────────────────────


def _file_pairs(work: Path, unit: Unit) -> list[tuple[Path, Path]]:
    """古い置き場にある組のファイルと、それぞれの新しい置き場のパス。"""
    if unit.kind == "story_reflection":
        new_dir = new_location(work, unit.kind)
        pairs = []
        for role, (legacy_name, new_name) in STORY_REFLECTION_FILES.items():
            if role == "lock":
                continue  # ロックは操作の間だけある一時のファイル（移行が取ったロックは放すときに消える）
            source = work / legacy_name
            if source.is_file():
                pairs.append((source, new_dir / new_name))
        return pairs
    legacy_dir = legacy_location(work, unit.kind, unit.unit_id)
    new_dir = new_location(work, unit.kind, unit.unit_id)
    return [
        (path, new_dir / path.relative_to(legacy_dir))
        for path in sorted(legacy_dir.rglob("*"))
        if path.is_file()
    ]


# ── 操作の状態（終わっていない操作がある組は移さない） ─────────────────────────


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _writing_scene_busy(scene_dir: Path) -> str | None:
    for run in sorted(scene_dir.glob("run-*")):
        repair = _read_json(run / "repair_state.json")
        if repair.get("status") == "active" or (repair.get("session") or {}).get("pending") is not None:
            return f"{run.name} の修復が終わっていない"
        if _read_json(run / "publish_state.json").get("status") == "active":
            return f"{run.name} の保存（publish）が終わっていない"
    return None


@dataclass
class _Hold:
    release: Callable[[], None]


def _hold_unit(work: Path, unit: Unit) -> _Hold:
    """組の排他を取り、終わっていない操作が無いことを確かめる。取れなければ MigrationError。"""
    if unit.kind == "story_reflection":
        from story_reflection_op import NovelPaths, OpError, acquire_lock, cmd_inspect, unlink_owned_lock

        try:
            paths = NovelPaths(work)
            verdict = cmd_inspect(paths)["verdict"]
        except OpError as error:
            raise MigrationError(error.code, f"{unit.label}: {error.message}") from error
        if verdict not in {"terminal_match", "missing"}:
            raise MigrationError("BUSY", f"{unit.label}: 操作が終わっていない（{verdict}）")
        try:
            held = acquire_lock(paths, "migrate-" + os.urandom(4).hex())
        except OpError as error:
            raise MigrationError("BUSY", f"{unit.label}: 排他を取れない（{error.code}）") from error

        def release_story() -> None:
            # 移行が取ったロックを消せなかったら、古い置き場にロックが残り、移したあとに競合になる。
            # 切り替えに進まずに止める（呼び出し側が移行の記録を取り消す）。
            if not unlink_owned_lock(held):
                raise MigrationError("LOCK_RELEASE", f"{unit.label}: 移行が取ったロックを消せない。何も移さずに止めた")

        return _Hold(release_story)

    if unit.kind in {"writing", "metron"}:
        # METRON の場面は執筆接続の同じ場面のロックで守られている。執筆接続の場面があるときだけ取る
        # （無い場面にロックを作ると、新しい置き場に場面を作ってしまう）。
        from writing_bridge.errors import BridgeError
        from writing_bridge.locking import scene_lock

        if not re.fullmatch(r"ch\d{2,}-\d{3,}", unit.unit_id):
            # 場面 ID でない作業フォルダ（例: run-reflection-proof）は執筆接続が使わない。ロックを取らずに移す。
            return _Hold(lambda: None)
        writing = resolve_unit(work, "writing", unit.unit_id)
        if writing.layout == "absent":
            return _Hold(lambda: None)
        busy = _writing_scene_busy(writing.base)
        if busy:
            raise MigrationError("BUSY", f"{unit.label}: {busy}")
        context = scene_lock(work, unit.unit_id)
        try:
            context.__enter__()
        except BridgeError as error:
            raise MigrationError("BUSY", f"{unit.label}: 排他を取れない（{error.code}）") from error
        busy = _writing_scene_busy(writing.base)
        if busy:
            context.__exit__(None, None, None)
            raise MigrationError("BUSY", f"{unit.label}: {busy}")
        def release_scene() -> None:
            context.__exit__(None, None, None)

        return _Hold(release_scene)

    return _Hold(lambda: None)  # reader: 排他を持たない作業フォルダ


# ── 移す ─────────────────────────────────────────────────────────────────


@dataclass
class PlanItem:
    unit: Unit
    files: int
    action: str  # "migrate" / "skip:<理由>"


def plan(work: Path, kinds: tuple[str, ...] = KINDS) -> list[PlanItem]:
    items: list[PlanItem] = []
    for kind in kinds:
        if kind not in KINDS:
            continue  # 付属原稿（matter）は組ではないので、migrate_book_matter で別に扱う
        unit_ids = [STORY_REFLECTION_UNIT] if kind == "story_reflection" else iter_unit_ids(work, kind)
        for unit_id in unit_ids:
            unit = Unit(kind, unit_id)
            try:
                location = resolve_unit(work, kind, unit_id)
            except WorkPathError as error:
                items.append(PlanItem(unit, 0, f"skip:{error.code}"))
                continue
            if location.layout != "legacy":
                continue
            items.append(PlanItem(unit, len(_file_pairs(work, unit)), "migrate"))
    return items


def migrate_unit(work: Path, unit: Unit) -> None:
    """組を一つ移す。終わったときは、組は新しい置き場だけにある。移行と復旧の共通の排他を全期間持つ。"""
    with migration_lock(work):
        _migrate_unit_locked(work, unit)


def _migrate_unit_locked(work: Path, unit: Unit) -> None:
    location = resolve_unit(work, unit.kind, unit.unit_id)
    if location.layout != "legacy":
        raise MigrationError("NOT_LEGACY", f"{unit.label} は古い置き場に無い（{location.layout}）")
    marker = migration_marker(work, unit.kind, unit.unit_id)
    staging = _staging_dir(work, unit)
    if staging.exists() or _old_dir(work, unit).exists():
        raise MigrationError("LEFTOVER", f"{unit.label}: 前の移行の残りがある。--recover を先に実行する")

    hold = _hold_unit(work, unit)
    try:
        # 排他を持っている間は、移行の記録（ファイルの一覧）を作るだけにする。ロック中のファイルは
        # Windows では自分でも読めないので、ハッシュは排他を放したあとに取る。記録がある組はどのツールも
        # 使わないので、その間に中身は変わらない。
        pairs = _file_pairs(work, unit)
        manifest: list[dict[str, Any]] = [
            {"legacy": _rel(work, source), "new": _rel(work, target), "sha256": None} for source, target in pairs
        ]
        record: dict[str, Any] = {
            "kind": unit.kind,
            "unit_id": unit.unit_id,
            "state": "copying",
            "files": manifest,
        }
        _write_json(marker, record)
    except BaseException:
        hold.release()
        marker.unlink(missing_ok=True)
        raise
    try:
        hold.release()
    except MigrationError:
        # まだ何も写していない。移行の記録を取り消して、古い置き場のまま止める。
        marker.unlink(missing_ok=True)
        raise
    _checkpoint("listed")  # 記録はあるが、ハッシュはまだ取っていない
    for item in manifest:
        item["sha256"] = _sha256(work / item["legacy"])
    _write_json(marker, record)
    _checkpoint("copying")

    for item in manifest:
        source = work / item["legacy"]
        copy = staging / Path(item["new"]).relative_to(Path(_rel(work, _new_base(work, unit))))
        copy.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, copy)
        _checkpoint("copying:file")
    for item in manifest:
        copy = staging / Path(item["new"]).relative_to(Path(_rel(work, _new_base(work, unit))))
        if _sha256(copy) != item["sha256"]:
            raise MigrationError("HASH_MISMATCH", f"{unit.label}: 写しのハッシュが一致しない: {item['legacy']}")
    record["state"] = "verified"
    _write_json(marker, record)
    _checkpoint("verified")

    record["state"] = "switching"
    _write_json(marker, record)
    _checkpoint("switching")
    old = _old_dir(work, unit)
    try:
        _move_legacy_aside(work, unit, manifest, old)
    except OSError as error:
        # 退ける最初の名前の変更で失敗したら、何も動かさずに戻す（古い組はそのまま）。
        if not old.exists() or not any(old.rglob("*")):
            _discard(staging)
            _discard(old)
            marker.unlink(missing_ok=True)
            raise MigrationError(
                "IN_USE", f"{unit.label}: 古い組を動かせない（使用中の可能性）。何も変えずに戻した: {error}"
            ) from error
        raise MigrationError(
            "INTERRUPTED", f"{unit.label}: 古い組を退ける途中で失敗した。--recover で復旧する: {error}"
        ) from error
    _checkpoint("aside")
    _finish_placement(work, unit, staging)
    _checkpoint("placed")
    for item in manifest:
        if _sha256(work / item["new"]) != item["sha256"]:
            raise MigrationError("HASH_MISMATCH", f"{unit.label}: 新しい置き場のハッシュが一致しない: {item['new']}")
    record["state"] = "switched"
    _write_json(marker, record)
    _checkpoint("switched")
    _discard(old)
    _checkpoint("cleaned")
    marker.unlink(missing_ok=True)


def _new_base(work: Path, unit: Unit) -> Path:
    return new_location(work, unit.kind, unit.unit_id)


def _move_legacy_aside(work: Path, unit: Unit, manifest: list[dict[str, Any]], old: Path) -> None:
    old.parent.mkdir(parents=True, exist_ok=True)
    if unit.kind == "story_reflection":
        old.mkdir(exist_ok=True)
        for index, item in enumerate(manifest):
            source = work / item["legacy"]
            os.rename(source, old / source.name)
            if index == 0:
                _checkpoint("aside:first")
        return
    os.rename(legacy_location(work, unit.kind, unit.unit_id), old)


def _discard(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


MATTER_LEGACY = "book_matter"
MATTER_NEW = "_novel_text/matter"
MATTER_MARKER = "_work/.migrating/matter/book_matter.json"
MATTER_NEW_YAML = "_work/.migrating/matter/book.yaml.new"
_RE_MATTER_PATH = re.compile(r"(?<![\w./-])book_matter/")


def _map_matter(value: Any) -> Any:
    """YAML を読んだ値の中で、book_matter/ で始まる文字列だけを新しい置き場へ写す。"""
    if isinstance(value, str) and value.startswith(MATTER_LEGACY + "/"):
        return MATTER_NEW + value[len(MATTER_LEGACY) :]
    if isinstance(value, list):
        return [_map_matter(item) for item in value]
    if isinstance(value, dict):
        return {key: _map_matter(item) for key, item in value.items()}
    return value


def _matter_strings(value: Any, prefix: str) -> list[str]:
    if isinstance(value, str):
        return [value] if value.startswith(prefix) else []
    if isinstance(value, list):
        return [found for item in value for found in _matter_strings(item, prefix)]
    if isinstance(value, dict):
        return [found for item in value.values() for found in _matter_strings(item, prefix)]
    return []


def _rewrite_book_yaml(text: str) -> tuple[str, list[str]]:
    """book.yaml の付属原稿のパスを、行の中のものも含めてすべて書き換える。

    書き換えの前後で YAML を読み比べ、book_matter/ で始まる値だけが新しい置き場に変わり、ほかは同じことを
    確かめる。新しい置き場を指す値の一覧を返す（移したあとに実在を確かめる）。
    """
    import yaml

    updated = "\n".join(_RE_MATTER_PATH.sub(MATTER_NEW + "/", line) for line in text.split("\n"))
    try:
        before = yaml.safe_load(text)
        after = yaml.safe_load(updated)
    except yaml.YAMLError as error:
        raise MigrationError("BOOK_YAML", f"book.yaml を読めない: {error}") from error
    if _map_matter(before) != after or _matter_strings(after, MATTER_LEGACY + "/"):
        raise MigrationError("BOOK_YAML", "book.yaml の付属原稿のパスだけを書き換えられない（手で確かめる）")
    return updated, _matter_strings(after, MATTER_NEW + "/")


def plan_book_matter(work: Path) -> tuple[int, int] | None:
    """付属原稿（`book_matter/`）を移すときの (ファイル数, book.yaml で書き換えるパスの数)。無ければ None。"""
    legacy = work / MATTER_LEGACY
    if not legacy.is_dir():
        return None
    files = sum(1 for path in legacy.rglob("*") if path.is_file())
    book = work / "book.yaml"
    paths = _rewrite_book_yaml(book.read_text(encoding="utf-8"))[1] if book.is_file() else []
    return files, len(paths)


def _sha256_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def migrate_book_matter(work: Path) -> str | None:
    """`book_matter/` を `_novel_text/matter/` へ移し、book.yaml の付属原稿のパスを書き換える。

    フォルダの移動と book.yaml の書き換えを、移行の記録（`_work/.migrating/matter/`）で管理する。
    途中で止まっても `--recover` で、移す前（古い置き場と元の book.yaml）か移したあと（新しい置き場と
    書き換えた book.yaml）のどちらか一方に戻る。
    """
    legacy = work / MATTER_LEGACY
    if not legacy.is_dir():
        return None
    target = work.joinpath(*MATTER_NEW.split("/"))
    if target.exists():
        raise MigrationError("LEFTOVER", f"{MATTER_NEW} が既にある。中身を確かめてから移す")
    marker = work.joinpath(*MATTER_MARKER.split("/"))
    staged_yaml = work.joinpath(*MATTER_NEW_YAML.split("/"))
    if marker.exists():
        raise MigrationError("LEFTOVER", "前の付属原稿の移行の残りがある。--recover を先に実行する")
    book = work / "book.yaml"
    original = book.read_text(encoding="utf-8") if book.is_file() else None
    updated, referenced = _rewrite_book_yaml(original) if original is not None else (None, [])
    record: dict[str, Any] = {
        "kind": "matter",
        "state": "prepared",
        "book_exists": original is not None,
        "book_original_sha256": _sha256_text(original) if original is not None else None,
        "book_updated_sha256": _sha256_text(updated) if updated is not None else None,
    }
    if updated is not None:
        staged_yaml.parent.mkdir(parents=True, exist_ok=True)
        staged_yaml.write_text(updated, encoding="utf-8", newline="")
    _write_json(marker, record)
    _checkpoint("matter:prepared")
    target.parent.mkdir(parents=True, exist_ok=True)
    os.rename(legacy, target)
    record["state"] = "moved"
    _write_json(marker, record)
    _checkpoint("matter:moved")
    try:
        _finish_matter(work, record)
    except OSError as error:
        raise MigrationError(
            "INTERRUPTED", f"book.yaml を書き換えられない（使用中の可能性）。--recover で完了させる: {error}"
        ) from error
    for path in referenced:
        if not (work / path).is_file():
            raise MigrationError("BOOK_YAML", f"移したあとの付属原稿が見つからない: {path}")
    note = f"{MATTER_LEGACY} → {MATTER_NEW}"
    if (work / "book.lock.yaml").is_file():
        note += "（book.yaml のパスが変わったので、book_lock.py で lock を作り直す）"
    return note


def _finish_matter(work: Path, record: dict[str, Any]) -> None:
    """記録に従って book.yaml を書き換えた形にし、記録を片付ける（フォルダは移したあと）。"""
    marker = work.joinpath(*MATTER_MARKER.split("/"))
    staged_yaml = work.joinpath(*MATTER_NEW_YAML.split("/"))
    book = work / "book.yaml"
    if record["book_exists"]:
        current = _sha256_text(book.read_text(encoding="utf-8")) if book.is_file() else None
        if current == record["book_original_sha256"]:
            # 書き換えた全文（記録と一緒に置いた写し）を、一時ファイル経由で置き換える。写しは完了まで残す。
            tmp = book.with_name(f".{book.name}.{os.getpid()}.tmp")
            tmp.write_text(staged_yaml.read_text(encoding="utf-8"), encoding="utf-8", newline="")
            os.replace(tmp, book)
            _checkpoint("matter:written")
        elif current != record["book_updated_sha256"]:
            raise MigrationError("BOOK_YAML", "book.yaml が移行の途中で変わっている。手で確かめる")
        if _sha256_text(book.read_text(encoding="utf-8")) != record["book_updated_sha256"]:
            raise MigrationError("BOOK_YAML", "book.yaml を書き換えた結果が記録と一致しない")
    # 写しを消す前に完了（done）を記録する。done の記録は写しが無くても検証を通り、後片付けだけを再開できる。
    if record["state"] != "done":
        record["state"] = "done"
        _write_json(marker, record)
        _checkpoint("matter:done")
    staged_yaml.unlink(missing_ok=True)
    _checkpoint("matter:staged_removed")
    marker.unlink(missing_ok=True)


def _matter_references(work: Path) -> list[str]:
    """book.yaml が指す、新しい置き場の付属原稿のパス。"""
    import yaml

    book = work / "book.yaml"
    if not book.is_file():
        return []
    try:
        loaded = yaml.safe_load(book.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise MigrationError("BOOK_YAML", f"book.yaml を読めない: {error}") from error
    return _matter_strings(loaded, MATTER_NEW + "/")


def recover_matter(work: Path) -> str:
    """付属原稿の移行の記録から、移す前か移したあとのどちらか一方に戻す。"""
    marker = work.joinpath(*MATTER_MARKER.split("/"))
    staged_yaml = work.joinpath(*MATTER_NEW_YAML.split("/"))
    record = _validated_matter_record(work, marker)
    legacy = work / MATTER_LEGACY
    target = work.joinpath(*MATTER_NEW.split("/"))
    book = work / "book.yaml"
    current = _sha256_text(book.read_text(encoding="utf-8")) if book.is_file() else None
    if record["state"] == "done":
        # 移行は済んでいる。完了状態（新しい置き場だけにある、book.yaml が書き換えたあとの内容、参照が実在）を
        # 確かめてから、残った写しと記録を片付ける。
        if not (target.is_dir() and not legacy.exists()):
            raise MigrationError("UNRECOVERABLE", "完了の記録があるが、付属原稿が新しい置き場だけにない。手で確かめる")
        if record["book_exists"] and current != record["book_updated_sha256"]:
            raise MigrationError("UNRECOVERABLE", "完了の記録があるが、book.yaml が書き換えたあとの内容と違う。手で確かめる")
        missing = [path for path in _matter_references(work) if not (work / path).is_file()]
        if missing:
            raise MigrationError("UNRECOVERABLE", "完了の記録があるが、付属原稿が見つからない: " + "、".join(missing))
        staged_yaml.unlink(missing_ok=True)
        marker.unlink(missing_ok=True)
        return "new"
    if legacy.is_dir() and not target.exists():
        # フォルダはまだ移していない。book.yaml が元のままなら、記録を捨てて移す前に戻す。
        if record["book_exists"] and current != record["book_original_sha256"]:
            raise MigrationError("UNRECOVERABLE", "付属原稿は古い置き場にあるが、book.yaml が元と違う。手で確かめる")
        staged_yaml.unlink(missing_ok=True)
        marker.unlink(missing_ok=True)
        return "legacy"
    if target.is_dir() and not legacy.exists():
        # フォルダは移した。book.yaml を書き換えた形にそろえて完了させる。
        _finish_matter(work, record)
        return "new"
    raise MigrationError("UNRECOVERABLE", "付属原稿が古い置き場と新しい置き場の両方にある（または両方に無い）。手で確かめる")


def _validated_matter_record(work: Path, marker: Path) -> dict[str, Any]:
    record = _read_json(marker)
    sha = re.compile(r"sha256:[0-9a-f]{64}")
    ok = (
        record.get("kind") == "matter"
        and record.get("state") in {"prepared", "moved", "done"}
        and isinstance(record.get("book_exists"), bool)
    )
    if ok and record["book_exists"]:
        staged_path = work.joinpath(*MATTER_NEW_YAML.split("/"))
        ok = all(
            isinstance(record.get(key), str) and sha.fullmatch(record[key])
            for key in ("book_original_sha256", "book_updated_sha256")
        )
        if ok and record["state"] != "done":
            # prepared・moved では、book.yaml を書き換えるために写しが要る。
            ok = staged_path.is_file()
        if ok and staged_path.is_file():
            ok = _sha256_text(staged_path.read_text(encoding="utf-8")) == record["book_updated_sha256"]
    if not ok:
        raise MigrationError("BAD_RECORD", f"付属原稿の移行の記録が正しくない: {_rel(work, marker)}")
    return record


def remove_empty_legacy_roots(work: Path) -> list[str]:
    """移し終えて空になった古い親フォルダ（`_writing/`・`_metron/`・`_reader/_work/`）を消す。

    ファイルが1つでも残っていれば何もしない（空のフォルダだけを rmdir する）。
    """
    removed: list[str] = []
    for legacy, _ in DIR_KIND_ROOTS.values():
        root = work.joinpath(*legacy.split("/"))
        if not root.is_dir() or any(path.is_file() for path in root.rglob("*")):
            continue
        for directory in sorted((path for path in root.rglob("*") if path.is_dir()), reverse=True):
            directory.rmdir()
        root.rmdir()
        removed.append(legacy)
    return removed


def migrate_loose_staging(work: Path) -> list[str]:
    """即興の材料フォルダ（`_story_work/`・`_reader/_sr_staging/`）をフォルダごと移す。"""
    moved: list[str] = []
    for relative, name in LOOSE_STAGING:
        source = work.joinpath(*relative.split("/"))
        if not source.is_dir():
            continue
        target = new_location(work, "story_reflection") / "staging" / name
        if target.exists():
            raise MigrationError("LEFTOVER", f"{relative}: 移し先が既にある: {_rel(work, target)}")
        target.parent.mkdir(parents=True, exist_ok=True)
        os.rename(source, target)
        moved.append(f"{relative} → {_rel(work, target)}")
    return moved


# ── 復旧 ─────────────────────────────────────────────────────────────────


def _validated_record(work: Path, marker: Path) -> tuple[Unit, str, list[dict[str, Any]]]:
    """移行の記録を、何かを変える前に全体で検証する。合わなければ BAD_RECORD（何も変えない）。

    - 種類・ID が記録のファイルの位置（`_work/.migrating/<kind>/<unit_id>.json`）と一致する。
    - 状態が既知で、ファイル一覧の各項目が legacy・new・sha256（`sha256:` と 64 桁）を持つ。
    - 各パスが作品ルート相対で、古い置き場・新しい置き場それぞれの組の範囲内にあり、両者の対応が正しい
      （ストーリー反映は current・journal の決まった名前だけ）。
    """
    label = _rel(work, marker) if marker.is_relative_to(work) else str(marker)

    def bad(reason: str) -> MigrationError:
        return MigrationError("BAD_RECORD", f"移行の記録が正しくない（{reason}）: {label}")

    record = _read_json(marker)
    kind, unit_id, state, files = record.get("kind"), record.get("unit_id"), record.get("state"), record.get("files")
    if kind not in KINDS or not isinstance(unit_id, str):
        raise bad("種類または ID")
    if marker.parent.name != kind or marker.stem != unit_id:
        raise bad("記録の位置と種類・ID が一致しない")
    try:
        expected_marker = migration_marker(work, kind, unit_id)
        legacy_base = legacy_location(work, kind, unit_id)
        new_base = new_location(work, kind, unit_id)
    except WorkPathError as error:
        raise bad(str(error)) from error
    if expected_marker.resolve() != marker.resolve():
        raise bad("記録の位置")
    if state not in {"copying", "verified", "switching", "switched"}:
        raise bad(f"状態 {state!r}")
    if not isinstance(files, list) or not files:
        raise bad("ファイル一覧")
    story_names = {
        legacy_name: new_name for role, (legacy_name, new_name) in STORY_REFLECTION_FILES.items() if role != "lock"
    }
    root = work.resolve()
    seen: set[str] = set()
    manifest: list[dict[str, Any]] = []
    for item in files:
        if not isinstance(item, dict):
            raise bad("ファイル一覧の項目")
        legacy, new, digest = item.get("legacy"), item.get("new"), item.get("sha256")
        if not (isinstance(legacy, str) and isinstance(new, str)):
            raise bad("ファイル一覧の項目の欄")
        if digest is None and state == "copying":
            # 最初の記録はハッシュを取る前に保存する。copying からの復旧は写しを捨てて移行前に戻すだけで、
            # ハッシュを使わないので、未確定（None）を許す。verified 以降は必ず確定している。
            pass
        elif not (
            isinstance(digest, str)
            and digest.startswith("sha256:")
            and len(digest) == 71
            and all(c in "0123456789abcdef" for c in digest[7:])
        ):
            raise bad(f"ハッシュの書式: {legacy}")
        for value in (legacy, new):
            if value.startswith("/") or "\\" in value or (len(value) >= 2 and value[1] == ":") or ".." in value.split("/"):
                raise bad(f"作品ルート相対でないパス: {value}")
            if not (work / value).resolve().is_relative_to(root):
                raise bad(f"作品の外を指すパス: {value}")
        legacy_path, new_path = work / legacy, work / new
        if kind == "story_reflection":
            if legacy_path.parent != work or story_names.get(legacy_path.name) != new_path.name or new_path.parent != new_base:
                raise bad(f"ストーリー反映のファイルの対応: {legacy} → {new}")
        else:
            try:
                inner_legacy = legacy_path.relative_to(legacy_base)
                inner_new = new_path.relative_to(new_base)
            except ValueError as error:
                raise bad(f"組の範囲の外: {legacy} → {new}") from error
            if inner_legacy != inner_new or not inner_legacy.parts:
                raise bad(f"古い置き場と新しい置き場の対応: {legacy} → {new}")
        if legacy in seen:
            raise bad(f"重複: {legacy}")
        seen.add(legacy)
        manifest.append({"legacy": legacy, "new": new, "sha256": digest})
    return Unit(kind, unit_id), state, manifest


def recover_unit(work: Path, marker: Path) -> str:
    """移行の記録から、組を一か所に完全な形で戻す。戻した先（legacy / new）を返す。"""
    unit, state, manifest = _validated_record(work, marker)
    kind = unit.kind
    staging, old = _staging_dir(work, unit), _old_dir(work, unit)

    def complete(side: str) -> bool:
        return all(
            (work / item[side]).is_file() and _sha256(work / item[side]) == item["sha256"] for item in manifest
        )

    if state in {"copying", "verified"} or (state == "switching" and complete("legacy")):
        # 古い組には手を付けていない。写しを捨てて移行前に戻す。
        _discard(staging)
        _discard(old)
        for item in manifest:
            if state == "switching":
                (work / item["new"]).unlink(missing_ok=True)
        marker.unlink(missing_ok=True)
        return "legacy"
    if state == "switching":
        # 古い組を一部でも退けていた。写しは検証済みなので、新しい置き場への配置を済ませて完了させる。
        if not complete("new") and staging.exists():
            _finish_placement(work, unit, staging)
        if not complete("new"):
            return _restore_legacy(work, unit, manifest, staging, old, marker)
    if state in {"switching", "switched"}:
        if not complete("new"):
            raise MigrationError("UNRECOVERABLE", f"{unit.label}: switched なのに新しい置き場が揃わない。手で確かめる")
        if kind == "story_reflection":
            # 退けきれていなかった古いファイルも退けてから片付ける（直接は消さない）。
            old.mkdir(parents=True, exist_ok=True)
            for item in manifest:
                remaining = work / item["legacy"]
                if remaining.is_file():
                    os.rename(remaining, old / remaining.name)
        _discard(old)
        _discard(staging)
        marker.unlink(missing_ok=True)
        return "new"
    raise MigrationError("BAD_RECORD", f"未知の状態: {state}")


def _finish_placement(work: Path, unit: Unit, staging: Path) -> None:
    """一時領域に残った写しを新しい置き場へ置く（途中まで置いていても続きから）。"""
    target = _new_base(work, unit)
    if unit.kind == "story_reflection":
        target.mkdir(parents=True, exist_ok=True)
        for copy in sorted(staging.iterdir()):
            os.replace(copy, target / copy.name)
            _checkpoint("placing:file")
        staging.rmdir()
        return
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        os.rename(staging, target)


def _restore_legacy(
    work: Path, unit: Unit, manifest: list[dict[str, Any]], staging: Path, old: Path, marker: Path
) -> str:
    """新しい置き場が揃わないとき、退けた古い組を元の場所へ戻す。戻せなければ止める。"""
    if unit.kind == "story_reflection":
        for item in manifest:
            source = old / Path(item["legacy"]).name
            target = work / item["legacy"]
            if not target.exists() and source.is_file():
                os.rename(source, target)
    else:
        legacy_dir = legacy_location(work, unit.kind, unit.unit_id)
        if not legacy_dir.exists() and old.is_dir():
            legacy_dir.parent.mkdir(parents=True, exist_ok=True)
            os.rename(old, legacy_dir)
    if not all(
        (work / item["legacy"]).is_file() and _sha256(work / item["legacy"]) == item["sha256"] for item in manifest
    ):
        raise MigrationError("UNRECOVERABLE", f"{unit.label}: 古い組も新しい組も揃わない。手で確かめる")
    # 新しい置き場に置きかけた分を消す（移行の前は新しい置き場に組が無かった）。
    for item in manifest:
        (work / item["new"]).unlink(missing_ok=True)
    if unit.kind != "story_reflection":
        _discard(new_location(work, unit.kind, unit.unit_id))
    _discard(staging)
    _discard(old)
    marker.unlink(missing_ok=True)
    return "legacy"


def recover(work: Path) -> list[str]:
    root = work.joinpath(*MIGRATING_DIR.split("/"))
    results: list[str] = []
    if not root.is_dir():
        return results
    matter_marker = work.joinpath(*MATTER_MARKER.split("/"))
    with migration_lock(work):
        markers = [marker for marker in sorted(root.glob("*/*.json")) if marker != matter_marker]
        # 先にすべての記録を検証し、1つでも正しくなければ何も変えずに止める。
        for marker in markers:
            _validated_record(work, marker)
        if matter_marker.is_file():
            _validated_matter_record(work, matter_marker)
        for marker in markers:
            side = recover_unit(work, marker)
            results.append(f"{marker.parent.name}/{marker.stem} → {side}")
        if matter_marker.is_file():
            results.append(f"matter/book_matter → {recover_matter(work)}")
    return results


# ── 移行の勧め（計画 §3.4・§3.5） ─────────────────────────────────────────────

DECLINE_RECORD = "_work/migration.json"
# 依頼の種類ごとに、その作業でツールが `_meta.md` に書く節（無ければ ensure-section で足す）。
NEEDED_SECTIONS = {"edit": ["phase-status"], "evaluate": ["evaluation-history"], "read": []}


def _active_operation(work: Path) -> str | None:
    """進行中の操作（執筆接続の修復・保存、ストーリー反映）。あれば移行を勧めない。"""
    for unit_id in iter_unit_ids(work, "writing"):
        try:
            base = resolve_unit(work, "writing", unit_id).base
        except WorkPathError as error:
            return f"writing/{unit_id}: {error.code}"
        busy = _writing_scene_busy(base)
        if busy:
            return f"writing/{unit_id}: {busy}"
    from story_reflection_op import NovelPaths, OpError, cmd_inspect

    try:
        verdict = cmd_inspect(NovelPaths(work))["verdict"]
    except (OpError, WorkPathError) as error:
        return f"story_reflection: {getattr(error, 'code', error)}"
    if verdict not in {"terminal_match", "missing", "terminal"}:
        return f"story_reflection: {verdict}"
    return None


def advise(work: Path, request: str) -> dict[str, Any]:
    """依頼の種類（edit / evaluate / read）ごとに、移行を勧めるかと、足す節を決める。何も書かない。

    - 編集: 古い構成（機械の記録の古い置き場、`_meta.md` の古い形・一部だけの形）なら一度だけ勧める。
      断った記録（`_work/migration.json`）があれば勧めない。進行中の操作があるときも勧めない。
    - 評価・読むだけ: 勧めない。
    - どの依頼でも、その作業で書く `_meta.md` の節が無ければ ensure-section で足す（読むだけは書かない）。
    - 中断した移行があれば、どの依頼でも先に --recover を求める（読むだけは知らせるだけ）。
    """
    from novel_meta_check import ENSURE_NAMES, check_text
    from work_paths import legacy_markers

    if request not in NEEDED_SECTIONS:
        raise MigrationError("USAGE", f"未知の依頼の種類: {request}")
    markers = [{"kind": item.kind, "path": item.path} for item in legacy_markers(work)]
    interrupted = sorted(
        _rel(work, path) for path in work.joinpath(*MIGRATING_DIR.split("/")).glob("*/*.json")
    )
    meta = work / "_meta.md"
    meta_form = "none"
    missing_keys: list[str] = []
    if meta.is_file():
        result = check_text(meta.read_text(encoding="utf-8").replace("\r\n", "\n"))
        meta_form = result.form
        missing_keys = [key for key in result.missing] + [
            key for key in ENSURE_NAMES.values() if key not in result.present and key not in result.missing
        ]
    glossary_form = "none"
    world = work / "world.md"
    if world.is_file():
        try:
            from novel_glossary import parse_glossary

            glossary_form = parse_glossary(world.read_text(encoding="utf-8")).form
        except Exception:  # noqa: BLE001 — 用語集の形は参考情報。読めなくても勧めの判断は続ける
            glossary_form = "unknown"
    declined = (work / DECLINE_RECORD).is_file()
    active = _active_operation(work)
    legacy = bool(markers) or meta_form in {"legacy", "partial"}
    propose = request == "edit" and legacy and not declined and active is None and not interrupted
    ensure = [
        name
        for name in NEEDED_SECTIONS[request]
        if meta.is_file() and ENSURE_NAMES[name] in missing_keys
    ]
    if interrupted and request != "read":
        message = "中断した移行がある。作業の前に `novel_work_migrate.py --recover` を実行する"
    elif propose:
        message = "古い構成の作品。作業の前に一度だけ、新しい構成への移行を勧める（--dry-run の結果を見せる）"
    elif request == "edit" and legacy and declined:
        message = "古い構成だが、移行は断られている。勧めずに読み取り互換で続ける"
    elif request == "edit" and legacy and active:
        message = f"古い構成だが、進行中の操作があるので勧めない（{active}）"
    else:
        message = "勧めることはない"
    return {
        "request": request,
        "legacy_markers": markers,
        "meta_form": meta_form,
        "glossary_form": glossary_form,
        "declined": declined,
        "active_operation": active,
        "interrupted_migrations": interrupted,
        "propose_migration": propose,
        "ensure_sections": ensure,
        "message": message,
    }


def decline(work: Path) -> Path:
    """移行を断ったことを記録する（同じ作品では勧めを繰り返さない）。"""
    import datetime as dt

    from work_paths import legacy_markers

    path = work.joinpath(*DECLINE_RECORD.split("/"))
    _write_json(
        path,
        {
            "declined_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
            "legacy_markers": [item.path for item in legacy_markers(work)],
        },
    )
    return path


# ── CLI ──────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="作品フォルダの機械の記録を新しい置き場（_work/）へ組ごとに移す")
    parser.add_argument("work", type=Path)
    parser.add_argument("--dry-run", action="store_true", help="何をどこへ移すかを表示するだけ（何も書かない）")
    parser.add_argument("--recover", action="store_true", help="中断した移行を記録から復旧する")
    parser.add_argument(
        "--kind", choices=(*KINDS, "matter"), action="append", help="移す種類（省略時はすべて。matter は付属原稿）"
    )
    parser.add_argument(
        "--advise",
        choices=sorted(NEEDED_SECTIONS),
        help="依頼の種類（edit / evaluate / read）ごとに、移行を勧めるかと足す節を表示する（書かない）",
    )
    parser.add_argument("--decline", action="store_true", help="移行を断ったことを記録する（以後は勧めない）")
    parser.add_argument("--json", action="store_true", help="--advise の結果を JSON で出す")
    args = parser.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except AttributeError:
        pass
    work = args.work.resolve()
    kinds = tuple(args.kind) if args.kind else (*KINDS, "matter")
    try:
        if args.advise:
            advice = advise(work, args.advise)
            if args.json:
                print(json.dumps(advice, ensure_ascii=False, indent=2))
            else:
                print(advice["message"])
                if advice["legacy_markers"]:
                    print("古い構成の印: " + "、".join(item["path"] for item in advice["legacy_markers"]))
                print(f"_meta.md の形: {advice['meta_form']}")
                for name in advice["ensure_sections"]:
                    print(f"足す節: uv run python tools/novel_meta_check.py ensure-section {args.work} {name}")
            return 0
        if args.decline:
            print(f"記録しました: {_rel(work, decline(work))}")
            return 0
        if args.recover:
            results = recover(work)
            print("\n".join(results) if results else "復旧する移行はありません")
            return 0
        pending = sorted(work.joinpath(*MIGRATING_DIR.split("/")).glob("*/*.json"))
        if pending:
            print("中断した移行があります。先に --recover を実行してください:")
            for marker in pending:
                print(f"  {_rel(work, marker)}")
            return 1
        items = plan(work, kinds)
        loose = [rel for rel, _ in LOOSE_STAGING if work.joinpath(*rel.split("/")).is_dir()]
        if args.dry_run:
            for item in items:
                print(f"{item.action}\t{item.unit.label}\t{item.files} files")
            for rel in loose:
                print(f"migrate\t{rel}\t(フォルダごと _work/story_reflection/staging/ へ)")
            matter = plan_book_matter(work) if "matter" in kinds else None
            if matter:
                print(f"migrate\t{MATTER_LEGACY}\t{matter[0]} files（{MATTER_NEW} へ。book.yaml の {matter[1]} 行を書き換え）")
            if not items and not loose and not matter:
                print("移すものはありません")
            return 0
        failures = 0
        for item in items:
            if item.action != "migrate":
                print(f"{item.action}\t{item.unit.label}")
                failures += 1
                continue
            try:
                migrate_unit(work, item.unit)
                print(f"migrated\t{item.unit.label}\t{item.files} files")
            except MigrationError as error:
                print(f"{error.code}\t{item.unit.label}\t{error}")
                failures += 1
        with migration_lock(work):
            if "matter" in kinds:
                moved = migrate_book_matter(work)
                if moved:
                    print(f"migrated\t{moved}")
            if "story_reflection" in kinds:
                for line in migrate_loose_staging(work):
                    print(f"migrated\t{line}")
            for line in remove_empty_legacy_roots(work):
                print(f"removed empty\t{line}")
        return 1 if failures else 0
    except (MigrationError, WorkPathError) as error:
        print(f"{getattr(error, 'code', 'ERROR')}\t{error}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
