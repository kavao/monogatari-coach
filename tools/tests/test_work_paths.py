from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from work_paths import (  # noqa: E402
    WorkPathError,
    ensure_not_migrating,
    iter_unit_ids,
    kind_roots,
    legacy_markers,
    migration_marker,
    record_reference,
    resolve_reference,
    resolve_unit,
)


def touch(path: Path, text: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# --- 組の置き場の解決 ---


def test_unmigrated_writing_scene_resolves_to_legacy(tmp_path: Path) -> None:
    touch(tmp_path / "_writing" / "ch01-001" / "run-0001" / "report.json")
    location = resolve_unit(tmp_path, "writing", "ch01-001")
    assert location.layout == "legacy"
    assert location.path("run-0001", "report.json") == tmp_path / "_writing" / "ch01-001" / "run-0001" / "report.json"


def test_migrated_writing_scene_resolves_to_new(tmp_path: Path) -> None:
    touch(tmp_path / "_work" / "writing" / "ch01-001" / "run-0001" / "report.json")
    location = resolve_unit(tmp_path, "writing", "ch01-001")
    assert location.layout == "new"
    assert location.base == tmp_path / "_work" / "writing" / "ch01-001"


def test_absent_unit_starts_in_new_location(tmp_path: Path) -> None:
    location = resolve_unit(tmp_path, "writing", "ch03-001")
    assert location.layout == "absent"
    assert location.base == tmp_path / "_work" / "writing" / "ch03-001"


def test_absent_metron_starts_in_new_location_after_m5(tmp_path: Path) -> None:
    # M5 で METRON も新しい置き場で始めるように切り替えた。以前からある場面は古い置き場のまま。
    location = resolve_unit(tmp_path, "metron", "ch03-001")
    assert location.layout == "absent"
    assert location.base == tmp_path / "_work" / "metron" / "ch03-001"
    assert record_reference(tmp_path, "metron", "ch03-001", "contract.yaml") == "_work/metron/ch03-001/contract.yaml"
    touch(tmp_path / "_metron" / "ch01-001" / "contract.yaml")
    assert record_reference(tmp_path, "metron", "ch01-001", "contract.yaml") == "_metron/ch01-001/contract.yaml"


def test_cli_resolve_prints_location(tmp_path: Path, capsys) -> None:
    from work_paths import main

    touch(tmp_path / "_metron" / "ch01-001" / "contract.yaml")
    assert main(["resolve", str(tmp_path), "metron", "ch01-001"]) == 0
    assert capsys.readouterr().out.strip() == (tmp_path / "_metron" / "ch01-001").as_posix()
    assert main(["resolve", str(tmp_path), "metron", "ch02-001"]) == 0
    assert capsys.readouterr().out.strip() == (tmp_path / "_work" / "metron" / "ch02-001").as_posix()
    assert not (tmp_path / "_work").exists()  # 表示するだけで何も作らない
    touch(tmp_path / "_work" / "metron" / "ch01-001" / "x.txt")
    assert main(["resolve", str(tmp_path), "metron", "ch01-001"]) == 2
    assert '"CONFLICT"' in capsys.readouterr().out


def test_empty_legacy_directory_counts_as_absent(tmp_path: Path) -> None:
    (tmp_path / "_writing" / "ch01-001").mkdir(parents=True)
    assert resolve_unit(tmp_path, "writing", "ch01-001").layout == "absent"


def test_mixed_units_resolve_independently(tmp_path: Path) -> None:
    touch(tmp_path / "_writing" / "ch01-001" / "run-0001" / "report.json")
    touch(tmp_path / "_work" / "writing" / "ch02-001" / "run-0001" / "report.json")
    assert resolve_unit(tmp_path, "writing", "ch01-001").layout == "legacy"
    assert resolve_unit(tmp_path, "writing", "ch02-001").layout == "new"


def test_same_unit_in_both_locations_is_conflict(tmp_path: Path) -> None:
    touch(tmp_path / "_metron" / "ch01-001" / "contract.yaml")
    touch(tmp_path / "_work" / "metron" / "ch01-001" / "draft.001.md")
    with pytest.raises(WorkPathError) as error:
        resolve_unit(tmp_path, "metron", "ch01-001")
    assert error.value.code == "CONFLICT"
    assert error.value.refs["legacy"] == "_metron/ch01-001"
    assert error.value.refs["new"] == "_work/metron/ch01-001"


def test_released_scene_lock_file_keeps_scene_in_legacy(tmp_path: Path) -> None:
    # 執筆接続の場面ロックは解放後もファイルが残る。ファイルの有無で書き込みを止めず、組の一部として古い置き場に解決する。
    touch(tmp_path / "_writing" / "ch01-001" / ".operation.lock", "0")
    location = resolve_unit(tmp_path, "writing", "ch01-001")
    assert location.layout == "legacy"
    assert location.path(".operation.lock").is_file()


def test_story_reflection_legacy_files(tmp_path: Path) -> None:
    touch(tmp_path / "_story_reflection_op.jsonl", "{}\n")
    location = resolve_unit(tmp_path, "story_reflection")
    assert location.layout == "legacy"
    assert location.file("current") == tmp_path / "_story_reflection_op.json"
    assert location.file("journal") == tmp_path / "_story_reflection_op.jsonl"
    assert location.file("lock") == tmp_path / "_story_reflection_op.lock"


def test_story_reflection_leftover_lock_keeps_set_together(tmp_path: Path) -> None:
    # 異常終了で古いロックだけが残っていても、組は古い置き場で解決し、3つが別々の置き場に分かれない。
    touch(tmp_path / "_story_reflection_op.lock", "{}")
    location = resolve_unit(tmp_path, "story_reflection")
    assert location.layout == "legacy"
    assert {location.file(role).parent for role in ("current", "journal", "lock")} == {tmp_path}


def test_story_reflection_new_and_absent(tmp_path: Path) -> None:
    assert resolve_unit(tmp_path, "story_reflection").file("journal") == (
        tmp_path / "_work" / "story_reflection" / "op.jsonl"
    )
    touch(tmp_path / "_work" / "story_reflection" / "op.json", "{}")
    assert resolve_unit(tmp_path, "story_reflection").layout == "new"


def test_story_reflection_conflict(tmp_path: Path) -> None:
    touch(tmp_path / "_story_reflection_op.json", "{}")
    touch(tmp_path / "_work" / "story_reflection" / "op.jsonl", "{}\n")
    with pytest.raises(WorkPathError) as error:
        resolve_unit(tmp_path, "story_reflection")
    assert error.value.code == "CONFLICT"


# --- 移行中の組 ---


def test_migrating_unit_is_refused(tmp_path: Path) -> None:
    touch(tmp_path / "_writing" / "ch01-001" / "run-0001" / "report.json")
    touch(migration_marker(tmp_path, "writing", "ch01-001"), '{"state": "copying"}')
    with pytest.raises(WorkPathError) as error:
        resolve_unit(tmp_path, "writing", "ch01-001")
    assert error.value.code == "MIGRATING"
    with pytest.raises(WorkPathError):
        ensure_not_migrating(tmp_path, "writing", "ch01-001")
    # ほかの組は影響を受けない
    assert resolve_unit(tmp_path, "writing", "ch02-001").layout == "absent"


def test_migration_staging_is_not_counted_as_location(tmp_path: Path) -> None:
    # 一時領域の写しは組の置き場として数えない（両方にあれば競合、の判定に入らない）。
    touch(tmp_path / "_writing" / "ch01-001" / "run-0001" / "report.json")
    touch(tmp_path / "_work" / ".migrating" / "writing" / "ch01-001" / "run-0001" / "report.json")
    assert resolve_unit(tmp_path, "writing", "ch01-001").layout == "legacy"
    assert iter_unit_ids(tmp_path, "writing") == ["ch01-001"]


# --- 保存された参照パス ---


def test_reference_to_unmigrated_unit_stays_legacy(tmp_path: Path) -> None:
    target = touch(tmp_path / "_writing" / "ch01-001" / "run-0001" / "links.yaml")
    assert resolve_reference(tmp_path, "_writing/ch01-001/run-0001/links.yaml") == target


def test_legacy_reference_to_migrated_unit_follows_unit(tmp_path: Path) -> None:
    target = touch(tmp_path / "_work" / "metron" / "ch01-001" / "contract.yaml")
    assert resolve_reference(tmp_path, "_metron/ch01-001/contract.yaml") == target


def test_new_reference_to_unmigrated_unit_follows_unit(tmp_path: Path) -> None:
    target = touch(tmp_path / "_metron" / "ch01-001" / "beats.yaml")
    assert resolve_reference(tmp_path, "_work/metron/ch01-001/beats.yaml") == target


def test_reference_resolution_in_mixed_work(tmp_path: Path) -> None:
    # 場面 A は古い置き場、場面 B は新しい置き場。執筆接続と METRON も別々に解決する。
    links_a = touch(tmp_path / "_writing" / "ch01-001" / "run-0002" / "links.yaml")
    contract_a = touch(tmp_path / "_work" / "metron" / "ch01-001" / "contract.yaml")
    links_b = touch(tmp_path / "_work" / "writing" / "ch02-001" / "run-0001" / "links.yaml")
    assert resolve_reference(tmp_path, "_writing/ch01-001/run-0002/links.yaml") == links_a
    assert resolve_reference(tmp_path, "_metron/ch01-001/contract.yaml") == contract_a
    assert resolve_reference(tmp_path, "_writing/ch02-001/run-0001/links.yaml") == links_b


def test_reference_to_conflicting_unit_stops(tmp_path: Path) -> None:
    touch(tmp_path / "_writing" / "ch01-001" / "a.txt")
    touch(tmp_path / "_work" / "writing" / "ch01-001" / "b.txt")
    with pytest.raises(WorkPathError) as error:
        resolve_reference(tmp_path, "_writing/ch01-001/a.txt")
    assert error.value.code == "CONFLICT"


def test_reference_outside_units_and_missing_units(tmp_path: Path) -> None:
    assert resolve_reference(tmp_path, "_novel_text/novel_text01.md") == tmp_path / "_novel_text" / "novel_text01.md"
    # 組がどちらにも無ければ記録どおりのパス（存在しないので呼び出し側が参照切れとして扱う）
    assert resolve_reference(tmp_path, "_writing/ch09-001/run-0001/x.md") == (
        tmp_path / "_writing" / "ch09-001" / "run-0001" / "x.md"
    )
    assert resolve_reference(tmp_path, "_writing\\ch09-001\\x.md") == tmp_path / "_writing" / "ch09-001" / "x.md"


@pytest.mark.parametrize("bad", ["", "/abs/path", "C:/abs", "_writing/../config.md", "../outside"])
def test_reference_out_of_root(tmp_path: Path, bad: str) -> None:
    with pytest.raises(WorkPathError) as error:
        resolve_reference(tmp_path, bad)
    assert error.value.code == "OUT_OF_ROOT"


def test_record_reference_uses_actual_location(tmp_path: Path) -> None:
    # 古い置き場の場面へ足す run は古いパスで記録する。METRON だけ移した場面では別々に記録する。
    touch(tmp_path / "_writing" / "ch01-001" / "run-0001" / "report.json")
    touch(tmp_path / "_work" / "metron" / "ch01-001" / "contract.yaml")
    assert record_reference(tmp_path, "writing", "ch01-001", "run-0002", "links.yaml") == (
        "_writing/ch01-001/run-0002/links.yaml"
    )
    assert record_reference(tmp_path, "metron", "ch01-001", "contract.yaml") == "_work/metron/ch01-001/contract.yaml"
    assert record_reference(tmp_path, "writing", "ch05-001", "run-0001", "links.yaml") == (
        "_work/writing/ch05-001/run-0001/links.yaml"
    )


# --- 番号の採番（混在中は両方を数える） ---


def _next_request_number(work: Path) -> int:
    numbers = [0]
    for root in kind_roots(work, "writing"):
        for request in root.glob("**/request.yaml"):
            numbers.append(int(request.read_text(encoding="utf-8").strip().removeprefix("WRQ-")))
    return max(numbers) + 1


def test_numbering_counts_both_locations(tmp_path: Path) -> None:
    touch(tmp_path / "_writing" / "ch01-001" / "run-0001" / "request.yaml", "WRQ-0007")
    touch(tmp_path / "_work" / "writing" / "ch02-001" / "run-0001" / "request.yaml", "WRQ-0003")
    assert [path.relative_to(tmp_path).as_posix() for path in kind_roots(tmp_path, "writing")] == [
        "_writing",
        "_work/writing",
    ]
    assert _next_request_number(tmp_path) == 8
    assert iter_unit_ids(tmp_path, "writing") == ["ch01-001", "ch02-001"]


# --- 入力の検査と古い構成の印 ---


@pytest.mark.parametrize("bad", ["", ".", "..", "a/b", "a\\b", "-x", "シーン"])
def test_bad_unit_id(tmp_path: Path, bad: str) -> None:
    with pytest.raises(WorkPathError) as error:
        resolve_unit(tmp_path, "writing", bad)
    assert error.value.code == "BAD_ID"


def test_bad_kind(tmp_path: Path) -> None:
    with pytest.raises(WorkPathError) as error:
        resolve_unit(tmp_path, "chronos", "x")  # type: ignore[arg-type]
    assert error.value.code == "BAD_KIND"


def test_legacy_markers(tmp_path: Path) -> None:
    assert legacy_markers(tmp_path) == []
    touch(tmp_path / "_story_reflection_op.json", "{}")
    touch(tmp_path / "_writing" / "ch01-001" / ".operation.lock", "0")
    touch(tmp_path / "_story_work" / "evidence.json", "{}")
    touch(tmp_path / "book_matter" / "frontmatter" / "characters.md")
    (tmp_path / "_metron").mkdir()  # 空のフォルダは印にしない
    found = {(marker.kind, marker.path) for marker in legacy_markers(tmp_path)}
    assert found == {
        ("story_reflection", "_story_reflection_op.json"),
        ("writing", "_writing"),
        ("story_work", "_story_work"),
        ("book_matter", "book_matter"),
    }
    # 新しい置き場だけの作品には印が出ない
    other = tmp_path / "other"
    touch(other / "_work" / "writing" / "ch01-001" / "run-0001" / "report.json")
    assert legacy_markers(other) == []


# --- レビュー指摘（2026-10-24）: 別 ID による移行中判定の回避と、組の外を指すパス ---


@pytest.mark.parametrize("other_id", ["other", "op2", "ch01-001"])
def test_story_reflection_rejects_other_ids(tmp_path: Path, other_id: str) -> None:
    touch(tmp_path / "_story_reflection_op.json", "{}")
    touch(migration_marker(tmp_path, "story_reflection"), '{"state": "copying"}')
    # 正しい ID では移行中として拒否される
    with pytest.raises(WorkPathError) as migrating:
        resolve_unit(tmp_path, "story_reflection")
    assert migrating.value.code == "MIGRATING"
    # 別の ID では、移行中の判定を回避して同じファイルを返すことはなく、ID の誤りで止まる
    for call in (
        lambda: resolve_unit(tmp_path, "story_reflection", other_id),
        lambda: ensure_not_migrating(tmp_path, "story_reflection", other_id),
        lambda: migration_marker(tmp_path, "story_reflection", other_id),
    ):
        with pytest.raises(WorkPathError) as error:
            call()
        assert error.value.code == "BAD_ID"


@pytest.mark.parametrize(
    "parts",
    [
        ("../../../../outside.txt",),
        ("..", "x.txt"),
        ("run-0001", "..", "..", "x.txt"),
        ("/abs/x.txt",),
        ("C:/x.txt",),
        (r"..\..\x.txt",),
    ],
)
def test_unit_path_rejects_escape(tmp_path: Path, parts: tuple[str, ...]) -> None:
    touch(tmp_path / "_writing" / "ch01-001" / "run-0001" / "report.json")
    location = resolve_unit(tmp_path, "writing", "ch01-001")
    with pytest.raises(WorkPathError) as error:
        location.path(*parts)
    assert error.value.code == "OUT_OF_ROOT"
    with pytest.raises(WorkPathError) as recorded:
        record_reference(tmp_path, "writing", "ch01-001", *parts)
    assert recorded.value.code == "OUT_OF_ROOT"


def test_unit_path_stays_inside_unit(tmp_path: Path) -> None:
    location = resolve_unit(tmp_path, "writing", "ch01-001")
    inside = location.path("sub/dir", "./file.yaml")
    assert inside == tmp_path / "_work" / "writing" / "ch01-001" / "sub" / "dir" / "file.yaml"
    inside.resolve().relative_to(location.base.resolve())
    assert record_reference(tmp_path, "writing", "ch01-001", r"sub\dir", "file.yaml") == (
        "_work/writing/ch01-001/sub/dir/file.yaml"
    )
