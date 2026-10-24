"""Tests for novel_structure_draw.py（構造方針 rolled の抽選）."""

from __future__ import annotations

import json
import random
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import novel_pick_registry  # noqa: E402
import novel_structure_draw as draw  # noqa: E402
import work_paths  # noqa: E402
from json_weighted_pick import pick_from_list  # noqa: E402

TABLE_REL = "_how_to.example/episode/general/episode_structure_dosing.json"


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    """標準の表とレジストリだけを写した一時リポジトリ。作品フォルダは novels/999_test。"""
    for rel in (TABLE_REL, "_how_to.example/pick_registry/_index.yaml", "_how_to.example/pick_registry/episode.yaml"):
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / rel, target)
    novel = tmp_path / "novels" / "999_test"
    novel.mkdir(parents=True)
    monkeypatch.setattr(novel_pick_registry, "_REPO_ROOT", tmp_path)
    return tmp_path, novel


def _utf8_env() -> dict:
    import os

    return {**os.environ, "PYTHONIOENCODING": "utf-8"}


def _chapter(chapter_id, strength=1, **extra):
    return {"id": chapter_id, "strength": strength, "scope": extra.pop("scope", "target"), **extra}


def _write_diagnosis(path: Path, chapters, **extra) -> Path:
    data = {"seed": 12345, "chapters": chapters, **extra}
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def _draw_lines(novel: Path) -> list[dict]:
    path = novel / "_work" / "structure" / "draws.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_derive_seed_matches_documented_command():
    # スキル手順7のコマンドで "12345:ch05:major:0" から出した値
    assert draw.derive_seed(12345, "ch05", "major", 0) == 3866997478


def test_same_input_reproduces_and_matches_manual_eval(repo, tmp_path):
    _, novel = repo
    chapters = [_chapter(f"ch{i:02d}", strength=i % 3) for i in range(1, 9)]
    diagnosis = _write_diagnosis(tmp_path / "d.json", chapters, total_chars=50000)
    first = draw.run(diagnosis, novel, dry_run=True)
    second = draw.run(diagnosis, novel, dry_run=True)
    assert first["chapters"] == second["chapters"]

    draw.run(diagnosis, novel)
    rolled = [line for line in _draw_lines(novel) if line["seed"] is not None]
    assert rolled
    for line in rolled:
        picked, index, mode, _ = pick_from_list(line["candidates"], rng=random.Random(line["seed"]))
        assert (picked, index, mode) == (line["result"]["picked"], line["result"]["index"], line["result"]["mode"])
    # 手で振るときの CLI（--eval --seed）とも一致する
    sample = rolled[0]
    proc = subprocess.run(
        [sys.executable, str(TOOLS / "json_weighted_pick.py"), "--eval", json.dumps(sample["candidates"], ensure_ascii=False),
         "--seed", str(sample["seed"]), "--json"],
        capture_output=True, text=True, encoding="utf-8", check=True, env=_utf8_env(),
    )
    assert json.loads(proc.stdout)["picked"] == sample["result"]["picked"]


def test_upper_bound_blocks_all_targets(repo, tmp_path):
    _, novel = repo
    chapters = [_chapter("ch01", major="関係を壊す", major_status="keep", scope="outside")]
    chapters += [_chapter(f"ch{i:02d}") for i in range(2, 7)]
    diagnosis = _write_diagnosis(tmp_path / "d.json", chapters, range={"L": 0, "U": 1})
    summary = draw.run(diagnosis, novel, dry_run=True)
    assert summary["count"] == 1
    assert all(not result["major"] for result in summary["chapters"])
    assert any(result["fixed"] == "上限到達" for result in summary["chapters"])


def test_lower_bound_forces_placement(repo, tmp_path):
    _, novel = repo
    chapters = [_chapter("ch01", scope="outside"), _chapter("ch02"), _chapter("ch03", scope="outside"), _chapter("ch04")]
    diagnosis = _write_diagnosis(tmp_path / "d.json", chapters, range={"L": 2, "U": 3})
    summary = draw.run(diagnosis, novel, dry_run=True)
    assert [r["fixed"] for r in summary["chapters"]] == ["下限のため配置", "下限のため配置"]
    assert summary["count"] == 2 and summary["shortage"] == 0


def test_review_major_is_not_counted(repo, tmp_path):
    # レビュー記録の例: U=1、第3章の転を見直し、第5章へ置けること
    _, novel = repo
    chapters = [_chapter(f"ch{i:02d}", scope="outside") for i in range(1, 7)]
    chapters[2] = _chapter("ch03", major="目的を壊す", major_status="review")
    chapters[4] = _chapter("ch05")
    diagnosis = _write_diagnosis(tmp_path / "d.json", chapters, range={"L": 1, "U": 1})
    summary = draw.run(diagnosis, novel, dry_run=True)
    by_id = {r["id"]: r for r in summary["chapters"]}
    assert summary["count"] == 1
    assert by_id["ch03"]["major"] or by_id["ch05"]["major"]
    first = draw.run(diagnosis, novel)
    budget = next(line["budget"] for line in _draw_lines(novel) if line.get("budget"))
    assert budget["C"] == 0 and budget["chapters"]["review"] == ["ch03"]
    assert first["written"] == len(_draw_lines(novel))


def test_gate_after_major_and_premise_excluded(repo, tmp_path):
    _, novel = repo
    chapters = [_chapter("ch01", scope="outside"), _chapter("ch02", foreshadow_before=False), _chapter("ch03")]
    # L=2・抽選対象2章 → 第2章は下限のため配置、第3章は直前に転があるので振らない（下限に1足りない）
    diagnosis = _write_diagnosis(tmp_path / "d.json", chapters, range={"L": 2, "U": 3})
    draw.run(diagnosis, novel)
    lines = _draw_lines(novel)
    by_scope = {}
    for line in lines:
        by_scope.setdefault(line["scope"], []).append(line)
    ch02_major = next(line for line in by_scope["ch02"] if line["item"] == "major")
    assert ch02_major["fixed"] == "下限のため配置"
    type_line = next(line for line in by_scope["ch02"] if line["item"] == "major_type")
    assert all(c["型"] != draw.PREMISE_TYPE for c in type_line["candidates"])
    ch03_major = next(line for line in by_scope["ch03"] if line["item"] == "major")
    assert ch03_major["fixed"].startswith("振らない: 直前の章に大きな転")
    summary = draw.run(diagnosis, novel, dry_run=True)
    assert summary["shortage"] == 1 and summary["shortage_reasons"] == ["ch03: 直前の章に大きな転"]


def test_work_items_keep_is_not_drawn(repo, tmp_path):
    _, novel = repo
    diagnosis = _write_diagnosis(
        tmp_path / "d.json",
        [_chapter("ch01", scope="outside")],
        range={"L": 0, "U": 0},
        work_items={"payoff_mode": "keep", "ending_tone": "review", "payoff_answer": "undecided"},
    )
    summary = draw.run(diagnosis, novel, dry_run=True)
    assert summary["work_items"]["payoff_mode"] == {"status": "keep"}
    assert summary["work_items"]["contract_break"] == {"status": "keep"}
    assert "picked" in summary["work_items"]["ending_tone"]
    assert "picked" in summary["work_items"]["payoff_answer"]


def test_work_override_and_working_table(repo, tmp_path):
    root, novel = repo
    work_table = novel / "structure_dosing.json"
    work_table.write_text(
        json.dumps({"後味": [{"tone": "uneasy", "確率": 1.0}]}, ensure_ascii=False), encoding="utf-8"
    )
    (novel / "pick_registry").mkdir()
    (novel / "pick_registry" / "work.yaml").write_text(
        "pick_lists:\n"
        "  structure_ending_tone:\n"
        "    domain: episode\n"
        "    visibility: public\n"
        "    description: 作品用の後味\n"
        "    source: novels/999_test/structure_dosing.json\n"
        "    path: 後味\n"
        "    tool: json_weighted_pick\n",
        encoding="utf-8",
    )
    # 作品ごとの上書きは --novel 付きの show に出る（レジストリ側の確認）
    entry = novel_pick_registry.merge_registry(novel_dir=novel)["structure_ending_tone"]
    assert entry.source == "novels/999_test/structure_dosing.json"
    assert draw.resolve_table("ending_tone", novel).path == work_table.resolve()

    # 作業用の表は、標準を指している項目にだけ効く
    working = root / draw.WORKING_TABLE
    working.parent.mkdir(parents=True)
    shutil.copyfile(root / TABLE_REL, working)
    assert draw.resolve_table("payoff_mode", novel).path == working.resolve()
    assert draw.resolve_table("ending_tone", novel).path == work_table.resolve()
    assert draw.correction_table() == working


def test_records_append_and_dry_run_does_not_write(repo, tmp_path):
    _, novel = repo
    diagnosis = _write_diagnosis(tmp_path / "d.json", [_chapter("ch01"), _chapter("ch02")], range={"L": 0, "U": 2})
    draw.run(diagnosis, novel, dry_run=True)
    assert not (novel / "_work" / "structure" / "draws.jsonl").exists()
    first = draw.run(diagnosis, novel)
    second = draw.run(diagnosis, novel, attempt=1)
    ids = [line["draw_id"] for line in _draw_lines(novel)]
    assert ids == list(range(1, len(ids) + 1))
    assert second["draw_ids"][0] == first["draw_ids"][-1] + 1


def test_reader_trace_marks_flat_chapters(tmp_path):
    trace = tmp_path / "trace.json"
    trace.write_text(
        json.dumps(
            [
                {"scene_id": "ch01-001", "trend": None},
                {"scene_id": "ch01-002", "trend": "flat"},
                {"scene_id": "ch02-001", "trend": "flat"},
                {"scene_id": "ch03-001", "trend": "rising"},
            ]
        ),
        encoding="utf-8",
    )
    assert draw.reader_flat_chapters(trace) == {"ch01", "ch02"}


def test_invalid_input_is_reported(repo, tmp_path):
    _, novel = repo
    bad = _write_diagnosis(tmp_path / "d.json", [_chapter("ch01", major="関係を壊す")], range={"L": 0, "U": 1})
    with pytest.raises(draw.DrawError):
        draw.run(bad, novel, dry_run=True)


def test_work_paths_structure_is_new_only(tmp_path):
    assert work_paths.new_only_location(tmp_path, "structure") == tmp_path / "_work" / "structure"
    (tmp_path / "_work" / "structure").mkdir(parents=True)
    (tmp_path / "_work" / "structure" / "draws.jsonl").write_text("{}\n", encoding="utf-8")
    assert work_paths.legacy_markers(tmp_path) == []
    with pytest.raises(work_paths.WorkPathError):
        work_paths.new_only_location(tmp_path, "metron")
    proc = subprocess.run(
        [sys.executable, str(TOOLS / "work_paths.py"), "resolve", str(tmp_path), "structure", "--json"],
        capture_output=True, text=True, encoding="utf-8", check=True, env=_utf8_env(),
    )
    assert json.loads(proc.stdout)["layout"] == "new"


# --- 第2段階レビュー（20261025_structure-theory-dosing-phase2-review.md）の再現条件 ---


def test_remaining_excludes_chapter_right_after_kept_major(repo, tmp_path):
    # 指摘1: ch05 に維持する転 → ch06 は置けない。R=1 と数え、ch02 を下限のため配置する
    _, novel = repo
    chapters = [_chapter(f"ch{i:02d}", strength=i % 4, scope="outside") for i in range(1, 7)]
    chapters[1] = _chapter("ch02", strength=2)
    chapters[4] = _chapter("ch05", strength=1, major="関係を壊す", major_status="keep", scope="outside")
    chapters[5] = _chapter("ch06", strength=2)
    diagnosis = _write_diagnosis(tmp_path / "d.json", chapters, range={"L": 2, "U": 3})
    diagnosis.write_text(diagnosis.read_text(encoding="utf-8").replace('"seed": 12345', '"seed": 0'), encoding="utf-8")
    summary = draw.run(diagnosis, novel, dry_run=True)
    by_id = {r["id"]: r for r in summary["chapters"]}
    assert by_id["ch02"]["fixed"] == "下限のため配置"
    assert by_id["ch06"]["fixed"] == "振らない: 直前の章に大きな転"
    assert summary["count"] == 2 and summary["shortage"] == 0


def test_kept_major_in_target_is_not_redrawn(repo, tmp_path):
    # 指摘2: keep と target の併用で、維持する転を振り直したり二重に数えたりしない
    _, novel = repo
    chapters = [
        _chapter("ch01", strength=0, scope="outside"),
        _chapter("ch02", strength=1, major="関係を壊す", major_status="keep"),
        _chapter("ch03", strength=2, scope="outside"),
        _chapter("ch04", strength=3, scope="outside"),
    ]
    diagnosis = _write_diagnosis(tmp_path / "d.json", chapters, range={"L": 2, "U": 2})
    diagnosis.write_text(diagnosis.read_text(encoding="utf-8").replace('"seed": 12345', '"seed": 1'), encoding="utf-8")
    summary = draw.run(diagnosis, novel, dry_run=True)
    ch02 = summary["chapters"][0]
    assert ch02["kept"] is True and ch02["major"] is False
    assert ch02["fixed"].startswith("振らない: 維持する大きな転")
    assert summary["count"] == 1 and summary["shortage"] == 1
    draw.run(diagnosis, novel)
    items = [line["item"] for line in _draw_lines(novel) if line["scope"] == "ch02"]
    assert items == ["major"]


def test_reader_flat_single_chapter_applies_multiplier(repo, tmp_path):
    # 指摘3: 読み進みで1章だけ flat でも、その章の平坦の倍率が効く（0.3 → 0.45）
    _, novel = repo
    chapters = [
        _chapter("ch01", strength=0, scope="outside"),
        _chapter("ch02", strength=1),
        _chapter("ch03", strength=2, scope="outside"),
        _chapter("ch04", strength=3, scope="outside"),
    ]
    diagnosis = _write_diagnosis(tmp_path / "d.json", chapters, range={"L": 0, "U": 2})
    diagnosis.write_text(diagnosis.read_text(encoding="utf-8").replace('"seed": 12345', '"seed": 1'), encoding="utf-8")
    trace = tmp_path / "trace.json"
    trace.write_text(json.dumps([{"scene_id": "ch02-001", "trend": "flat"}]), encoding="utf-8")
    without = draw.run(diagnosis, novel, dry_run=True)
    with_trace = draw.run(diagnosis, novel, dry_run=True, reader_trace=trace)
    assert without["chapters"][0]["probability"] == pytest.approx(0.3)
    assert with_trace["chapters"][0]["probability"] == pytest.approx(0.45)
