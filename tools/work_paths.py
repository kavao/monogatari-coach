"""作品フォルダの機械の記録の置き場を、組（unit）単位で解決する共通モジュール。

計画: _workingspace/plans/20261024_work-folder-layout.md §3.1

- 組: ストーリー反映（current・journal・lock の3ファイル）、執筆接続の1場面、METRON の1場面、
  評価の中間の1日分。組ごとに、古い置き場（legacy）か新しい置き場（new, `_work/` の下）の一か所に置く。
- 解決: 古い置き場だけにあれば legacy、新しい置き場だけにあれば new、どちらにも無ければ absent
  （新しく始める組は ABSENT_LAYOUT の置き場。既定は new）、両方にあれば競合（CONFLICT）で止める。
- 移行中: `_work/.migrating/<kind>/<unit_id>.json` がある組は MIGRATING で拒否する。
  `_work/.migrating/` の下は組の置き場として数えない。
- 保存された参照パスは書き換えず、参照先の組をこの規則で解決して読む（接頭辞の一律変換はしない）。

ロックファイルの有無では判断しない。排他の取得と操作の状態は、各ツールの既存の手順で確かめる。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import re
from typing import Literal

Kind = Literal["story_reflection", "writing", "metron", "reader"]
Layout = Literal["legacy", "new", "absent"]

WORK_DIR = "_work"
MIGRATING_DIR = "_work/.migrating"
STORY_REFLECTION_UNIT = "op"

# 場面などのフォルダを組とする種類: 古い親フォルダ → 新しい親フォルダ
DIR_KIND_ROOTS: dict[str, tuple[str, str]] = {
    "writing": ("_writing", "_work/writing"),
    "metron": ("_metron", "_work/metron"),
    "reader": ("_reader/_work", "_work/reader"),
}

# 新しい置き場だけを持つ種類: 種類 → `_work/` の下の親フォルダ。古い置き場が無いので組の解決・移行・
# 古い構成の印の対象にしない（DIR_KIND_ROOTS には入れない）。作品に一つのフォルダとして使う。
# structure: 構造方針 rolled の抽選の記録（計画 _workingspace/plans/20261025_structure-theory-dosing.md）。
NEW_ONLY_DIRS: dict[str, str] = {
    "structure": "_work/structure",
}

# まだ無い組（absent）を始める置き場。既定は新しい置き場。書き手のツールがまだ新しい置き場へ
# 切り替わっていない種類だけを古い置き場にしておき、同じ組が二か所に分かれないようにする。
# 2026-10-24 の M5 で metron も新しい置き場へ切り替え、今は古い置き場で始める種類は無い（計画 §4）。
ABSENT_LAYOUT: dict[str, Literal["legacy", "new"]] = {}

# ストーリー反映の組（3ファイル）: 役割 → (古い置き場のファイル名, 新しい置き場のファイル名)
STORY_REFLECTION_NEW_DIR = "_work/story_reflection"
STORY_REFLECTION_FILES: dict[str, tuple[str, str]] = {
    "current": ("_story_reflection_op.json", "op.json"),
    "journal": ("_story_reflection_op.jsonl", "op.jsonl"),
    "lock": ("_story_reflection_op.lock", "op.lock"),
}

# 保存された参照パスの接頭辞 → 種類。長いものから照合する。
_REFERENCE_PREFIXES: tuple[tuple[str, str], ...] = tuple(
    sorted(
        [(new, kind) for kind, (_, new) in DIR_KIND_ROOTS.items()]
        + [(legacy, kind) for kind, (legacy, _) in DIR_KIND_ROOTS.items()],
        key=lambda item: len(item[0]),
        reverse=True,
    )
)

# 古い構成の印（§3.4）。ストーリー反映の3ファイルと、DIR_KIND_ROOTS の古い親フォルダは別に数える。
_LEGACY_ONLY_MARKERS: tuple[tuple[str, str], ...] = (
    ("_story_work", "story_work"),
    ("_reader/_sr_staging", "sr_staging"),
    ("book_matter", "book_matter"),
)

_UNIT_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.\-]*")


class WorkPathError(Exception):
    """置き場の解決の失敗。code: BAD_KIND / BAD_ID / OUT_OF_ROOT / CONFLICT / MIGRATING。"""

    def __init__(self, code: str, message: str, *, refs: dict[str, str] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.refs = refs or {}


@dataclass(frozen=True)
class UnitLocation:
    """解決した組の置き場。layout が absent のときの base は、新しく始める場合の置き場（ABSENT_LAYOUT。既定は new）。"""

    work: Path
    kind: str
    unit_id: str
    layout: Layout
    base: Path

    def path(self, *parts: str) -> Path:
        """組の中のパス。絶対パス・親参照（..）は拒否し、組の範囲内に収まることを確かめる。

        ストーリー反映では file() を使う。
        """
        if self.kind == "story_reflection":
            raise WorkPathError("BAD_KIND", "story_reflection は file(role) で解決する")
        target = self.base.joinpath(*_safe_parts(parts))
        try:
            target.resolve().relative_to(self.base.resolve())
        except ValueError as error:
            raise WorkPathError(
                "OUT_OF_ROOT", "組の外を指すパス", refs={"value": "/".join(parts)}
            ) from error
        return target

    def file(self, role: str) -> Path:
        """ストーリー反映の役割（current / journal / lock）のファイル。"""
        if self.kind != "story_reflection":
            raise WorkPathError("BAD_KIND", "file(role) は story_reflection だけで使う")
        if role not in STORY_REFLECTION_FILES:
            raise WorkPathError("BAD_ID", f"未知の役割: {role}", refs={"role": role})
        legacy_name, new_name = STORY_REFLECTION_FILES[role]
        return self.base / (legacy_name if self.layout == "legacy" else new_name)

    def relative(self, *parts: str) -> str:
        """記録に書く作品ルート相対のパス（実際の置き場。absent なら新しく始める置き場）。"""
        target = self.path(*parts) if self.kind != "story_reflection" else self.base
        return target.relative_to(self.work).as_posix()


@dataclass(frozen=True)
class LegacyMarker:
    """古い構成の印。path は作品ルート相対。"""

    kind: str
    path: str


def _check_kind(kind: str) -> None:
    if kind != "story_reflection" and kind not in DIR_KIND_ROOTS:
        raise WorkPathError("BAD_KIND", f"未知の種類: {kind}", refs={"kind": kind})


def _check_unit_id(unit_id: str, kind: str | None = None) -> None:
    if not _UNIT_ID_RE.fullmatch(unit_id) or unit_id in {".", ".."}:
        raise WorkPathError("BAD_ID", f"組の ID に使えない文字がある: {unit_id!r}", refs={"unit_id": unit_id})
    # ストーリー反映の組は作品に1つだけで、置き場は ID によらない。別の ID で移行中の判定を回避させない。
    if kind == "story_reflection" and unit_id != STORY_REFLECTION_UNIT:
        raise WorkPathError(
            "BAD_ID",
            f"story_reflection の組の ID は {STORY_REFLECTION_UNIT!r} だけ: {unit_id!r}",
            refs={"unit_id": unit_id},
        )


def _safe_parts(parts: tuple[str, ...]) -> list[str]:
    """組の中の相対パスの部品。絶対パス・ドライブ指定・親参照を拒否する。"""
    joined = "/".join(parts).replace("\\", "/")
    if joined.startswith("/") or (len(joined) >= 2 and joined[1] == ":"):
        raise WorkPathError("OUT_OF_ROOT", "組の中のパスは相対で書く", refs={"value": joined})
    pieces = [piece for piece in joined.split("/") if piece not in {"", "."}]
    if ".." in pieces:
        raise WorkPathError("OUT_OF_ROOT", "組の中のパスに '..' を含めない", refs={"value": joined})
    return pieces


def _join(work: Path, relative: str) -> Path:
    return work.joinpath(*relative.split("/"))


def _has_any_file(directory: Path) -> bool:
    if not directory.is_dir():
        return False
    for child in directory.rglob("*"):
        if child.is_file():
            return True
    return False


def legacy_location(work: Path, kind: str, unit_id: str = STORY_REFLECTION_UNIT) -> Path:
    """古い置き場の組の base（ストーリー反映は作品ルート）。存在は問わない。"""
    _check_kind(kind)
    _check_unit_id(unit_id, kind)
    if kind == "story_reflection":
        return work
    return _join(work, DIR_KIND_ROOTS[kind][0]) / unit_id


def new_location(work: Path, kind: str, unit_id: str = STORY_REFLECTION_UNIT) -> Path:
    """新しい置き場の組の base。存在は問わない。"""
    _check_kind(kind)
    _check_unit_id(unit_id, kind)
    if kind == "story_reflection":
        return _join(work, STORY_REFLECTION_NEW_DIR)
    return _join(work, DIR_KIND_ROOTS[kind][1]) / unit_id


def _present(work: Path, kind: str, unit_id: str, layout: Literal["legacy", "new"]) -> bool:
    if kind == "story_reflection":
        index = 0 if layout == "legacy" else 1
        base = legacy_location(work, kind) if layout == "legacy" else new_location(work, kind)
        return any((base / names[index]).is_file() for names in STORY_REFLECTION_FILES.values())
    base = legacy_location(work, kind, unit_id) if layout == "legacy" else new_location(work, kind, unit_id)
    return _has_any_file(base)


def unit_present(work: Path, kind: str, unit_id: str, layout: Literal["legacy", "new"]) -> bool:
    """組のファイルがその置き場に1つでもあるか（移行中の印は見ない）。

    排他を取ったあとの確かめ直しで、「選ばなかったほうの置き場が空のままか」を見るのに使う。
    """
    _check_kind(kind)
    _check_unit_id(unit_id, kind)
    if layout not in ("legacy", "new"):
        raise WorkPathError("BAD_KIND", f"未知の置き場: {layout}")
    return _present(work, kind, unit_id, layout)


def new_only_location(work: Path, kind: str) -> Path:
    """新しい置き場だけを持つ種類（NEW_ONLY_DIRS）のフォルダ。何も作らない。"""
    if kind not in NEW_ONLY_DIRS:
        raise WorkPathError("BAD_KIND", f"新しい置き場だけの種類ではない: {kind}", refs={"kind": kind})
    return _join(work, NEW_ONLY_DIRS[kind])


def migration_marker(work: Path, kind: str, unit_id: str = STORY_REFLECTION_UNIT) -> Path:
    """移行の記録のパス（`_work/.migrating/<kind>/<unit_id>.json`）。"""
    _check_kind(kind)
    _check_unit_id(unit_id, kind)
    return _join(work, MIGRATING_DIR) / kind / f"{unit_id}.json"


def ensure_not_migrating(work: Path, kind: str, unit_id: str = STORY_REFLECTION_UNIT) -> None:
    """移行の記録がある組を拒否する。各ツールは排他を取ったあとにもう一度呼ぶ。"""
    marker = migration_marker(work, kind, unit_id)
    if marker.exists():
        raise WorkPathError(
            "MIGRATING",
            f"{kind}/{unit_id} は移行中。`migrate --recover` で復旧してから使う",
            refs={"marker": marker.relative_to(work).as_posix()},
        )


def resolve_unit(work: Path, kind: str, unit_id: str = STORY_REFLECTION_UNIT) -> UnitLocation:
    """組の置き場を解決する。両方にあれば CONFLICT、移行中なら MIGRATING。"""
    ensure_not_migrating(work, kind, unit_id)
    in_legacy = _present(work, kind, unit_id, "legacy")
    in_new = _present(work, kind, unit_id, "new")
    if in_legacy and in_new:
        raise WorkPathError(
            "CONFLICT",
            f"{kind}/{unit_id} が古い置き場と新しい置き場の両方にある",
            refs={
                "legacy": legacy_location(work, kind, unit_id).relative_to(work).as_posix() or ".",
                "new": new_location(work, kind, unit_id).relative_to(work).as_posix(),
            },
        )
    if in_legacy:
        return UnitLocation(work, kind, unit_id, "legacy", legacy_location(work, kind, unit_id))
    if in_new:
        return UnitLocation(work, kind, unit_id, "new", new_location(work, kind, unit_id))
    start = legacy_location if ABSENT_LAYOUT.get(kind, "new") == "legacy" else new_location
    return UnitLocation(work, kind, unit_id, "absent", start(work, kind, unit_id))


def kind_roots(work: Path, kind: str) -> list[Path]:
    """その種類の親フォルダのうち、存在するもの（古い→新しいの順）。番号の採番は両方を数える。"""
    _check_kind(kind)
    if kind == "story_reflection":
        raise WorkPathError("BAD_KIND", "story_reflection は親フォルダを持たない")
    legacy, new = DIR_KIND_ROOTS[kind]
    return [path for path in (_join(work, legacy), _join(work, new)) if path.is_dir()]


def iter_unit_ids(work: Path, kind: str) -> list[str]:
    """古い置き場と新しい置き場の組の ID（重複なし・昇順）。"""
    ids: set[str] = set()
    for root in kind_roots(work, kind):
        for child in root.iterdir():
            if child.is_dir() and _UNIT_ID_RE.fullmatch(child.name):
                ids.add(child.name)
    return sorted(ids)


def _normalize_reference(reference: str) -> str:
    normalized = reference.replace("\\", "/").strip()
    if not normalized:
        raise WorkPathError("OUT_OF_ROOT", "参照パスが空")
    if normalized.startswith("/") or (len(normalized) >= 2 and normalized[1] == ":"):
        raise WorkPathError("OUT_OF_ROOT", "参照パスは作品ルート相対で書く", refs={"value": normalized})
    parts = PurePosixPath(normalized).parts
    if ".." in parts:
        raise WorkPathError("OUT_OF_ROOT", "参照パスに '..' を含めない", refs={"value": normalized})
    return "/".join(part for part in parts if part != ".")


def resolve_reference(work: Path, reference: str) -> Path:
    """保存された参照パスを、参照先の組の実際の置き場で解決する。

    `_writing/<scene>/…` と `_work/writing/<scene>/…`（metron・reader も同じ）は、組の解決結果で
    古い置き場か新しい置き場へ向ける。組がどちらにも無ければ、記録どおりのパスを返す
    （存在しないので、呼び出し側が参照切れとして扱う）。組の外のパスはそのまま返す。
    """
    normalized = _normalize_reference(reference)
    for prefix, kind in _REFERENCE_PREFIXES:
        if not normalized.startswith(prefix + "/"):
            continue
        rest = normalized[len(prefix) + 1 :]
        unit_id, _, inner = rest.partition("/")
        if not unit_id:
            break
        location = resolve_unit(work, kind, unit_id)
        if location.layout == "absent":
            return _join(work, normalized)
        return location.path(*inner.split("/")) if inner else location.base
    return _join(work, normalized)


def canonical_reference(reference: str) -> str:
    """照合用の、置き場によらない参照の形。

    `_writing/<scene>/x` と `_work/writing/<scene>/x` を同じ `@writing/<scene>/x` にする（metron・reader も同じ）。
    記録したパスの文字列を照合の鍵に使う箇所で、移行の前後で同じ組を同じものとして比べるために使う。
    記録そのものは書き換えない。組の外のパスは正規化した形をそのまま返す。
    """
    normalized = _normalize_reference(reference)
    for prefix, kind in _REFERENCE_PREFIXES:
        if normalized.startswith(prefix + "/"):
            return f"@{kind}/{normalized[len(prefix) + 1 :]}"
    return normalized


def record_reference(work: Path, kind: str, unit_id: str, *parts: str) -> str:
    """新しく作る記録に書く参照パス。参照先の組の実際の置き場（無ければ新しく始める置き場）を指す。"""
    return resolve_unit(work, kind, unit_id).relative(*parts)


def legacy_markers(work: Path) -> list[LegacyMarker]:
    """古い構成の印の一覧（§3.4）。`_meta.md` の形は別のツールで判定する。"""
    markers: list[LegacyMarker] = []
    for names in STORY_REFLECTION_FILES.values():
        if (work / names[0]).is_file():
            markers.append(LegacyMarker("story_reflection", names[0]))
    for kind, (legacy, _) in DIR_KIND_ROOTS.items():
        if _has_any_file(_join(work, legacy)):
            markers.append(LegacyMarker(kind, legacy))
    for relative, kind in _LEGACY_ONLY_MARKERS:
        if _join(work, relative).exists():
            markers.append(LegacyMarker(kind, relative))
    return markers


def main(argv: list[str] | None = None) -> int:
    """場面などの組の置き場を表示する（読み取りだけ。何も作らない）。

    例: uv run python tools/work_paths.py resolve novels/<作品> metron ch01-001
        → novels/<作品>/_work/metron/ch01-001（以前からある場面なら novels/<作品>/_metron/ch01-001）
    """
    import argparse
    import json
    import sys

    parser = argparse.ArgumentParser(description="作品フォルダの機械の記録の置き場を、組単位で表示する")
    sub = parser.add_subparsers(dest="command", required=True)
    resolve = sub.add_parser("resolve", help="組の置き場を表示する（無ければ新しく始める置き場）")
    resolve.add_argument("work", type=Path)
    resolve.add_argument("kind", choices=["story_reflection", "writing", "metron", "reader", *NEW_ONLY_DIRS])
    resolve.add_argument("unit_id", nargs="?", default=STORY_REFLECTION_UNIT)
    resolve.add_argument("--json", action="store_true")
    markers = sub.add_parser("legacy-markers", help="古い構成の印を一覧する")
    markers.add_argument("work", type=Path)
    markers.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except AttributeError:
        pass
    try:
        if args.command == "resolve" and args.kind in NEW_ONLY_DIRS:
            path = new_only_location(args.work, args.kind)
            if args.json:
                print(json.dumps({"layout": "new", "path": path.as_posix()}, ensure_ascii=False))
            else:
                print(path.as_posix())
            return 0
        if args.command == "resolve":
            location = resolve_unit(args.work, args.kind, args.unit_id)
            if args.json:
                print(json.dumps({"layout": location.layout, "path": location.base.as_posix()}, ensure_ascii=False))
            else:
                print(location.base.as_posix())
            return 0
        found = legacy_markers(args.work)
        if args.json:
            print(json.dumps([{"kind": item.kind, "path": item.path} for item in found], ensure_ascii=False))
        else:
            for item in found:
                print(f"{item.kind}\t{item.path}")
        return 0
    except WorkPathError as error:
        print(json.dumps({"code": error.code, "message": str(error), "refs": error.refs}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
