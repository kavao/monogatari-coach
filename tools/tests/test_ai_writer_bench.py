from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from ai_writer import novelai as nai  # noqa: E402
from ai_writer.bench import (  # noqa: E402
    BUILDERS,
    Cell,
    auto_metrics,
    build_report,
    cells,
    clean_output,
    compare_scores,
    load_scenes,
    main,
    make_blind,
    write_sheets,
)


def test_scenes_cover_seven_genres_with_one_gap() -> None:
    scenes = load_scenes()
    assert [s.genre for s in scenes] == ["日常会話", "不穏な探索", "戦闘", "恋愛", "心理", "コメディ", "SF"]
    for s in scenes:
        assert "◆" not in s.text
        assert s.contract.must_include and s.contract.must_not


def test_full_benchmark_is_126_cells() -> None:
    assert len(cells(load_scenes(), None, None, 3, None)) == 126


def test_builders_target_expected_endpoints() -> None:
    scene = load_scenes()[0]
    assert BUILDERS["continue"](scene, "glm-4-6")[0].endswith(nai.COMPLETIONS_PATH)
    url, body = BUILDERS["directed_continue"](scene, "xialong-v1")
    assert url.endswith(nai.CHAT_PATH)
    assert scene.contract.end_condition in body["messages"][1]["content"]
    assert "【ここに挿入】" in BUILDERS["expand"](scene, "glm-4-6")[1]["messages"][1]["content"]


def test_clean_output_cuts_trailer_and_partial_tail() -> None:
    assert clean_output("continue", "風が吹いた。雨が\n") == "風が吹いた。"
    assert clean_output("directed_continue", "本文。\n***\n[解説]") == "本文。"
    assert clean_output("expand", "\n挿入文。\n***\n自己採点") == "挿入文。"


def test_auto_metrics_counts_with_project_standard() -> None:
    scene = load_scenes()[0]
    m = auto_metrics(scene, "directed_continue", "味噌汁が冷めていく。", "味噌汁が冷めていく。", 8)
    assert m["chars"] == 10
    assert m["chars_per_token"] == 1.25
    assert m["must_include_in_output"] == ["味噌汁"]


def _fake_record(cell: Cell, chars: int = 300) -> dict[str, object]:
    text = "あ" * chars
    return {"id": cell.id, "scene": cell.scene.id, "genre": cell.scene.genre, "op": cell.op, "model": cell.model,
            "sample": cell.sample, "ok": True, "output": text,
            "metrics": auto_metrics(cell.scene, cell.op, text, text, 230),
            "request": {}, "result": {"error": None}}


def test_sheets_keep_existing_scores_and_report_aggregates(tmp_path: Path) -> None:
    scenes = load_scenes()
    todo = cells(scenes, ["directed_continue"], None, 2, ["daily"])
    (tmp_path / "cells").mkdir()
    for cell in todo:
        (tmp_path / "cells" / f"{cell.id}.json").write_text(json.dumps(_fake_record(cell), ensure_ascii=False), encoding="utf-8")
    write_sheets(tmp_path, scenes)
    path = tmp_path / "scores.csv"
    with path.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 4
    for row in rows:
        row.update({"naturalness": "4", "appeal": "3", "compliance": "5", "character": "5", "lore": "5",
                    "new_fact": "0", "continuity": "4", "end_condition": "met", "judge": "test"})
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    write_sheets(tmp_path, scenes)  # 作り直しても採点は残る
    with path.open(encoding="utf-8", newline="") as f:
        assert all(r["naturalness"] == "4" for r in csv.DictReader(f))
    report = build_report(tmp_path)
    assert "| directed_continue | glm-4-6 | 2 | 4.00±0.00" in report
    assert "| 0/2 | 2 / 0 / 0 |" in report
    assert "chars_per_token" in report
    assert "scores.csv（一次点）" in report
    assert "| daily | directed_continue | +0.00 | +0.00 | 2/2 |" in report


def _write_cells(tmp_path: Path, todo: list[Cell]) -> None:
    (tmp_path / "cells").mkdir(exist_ok=True)
    for cell in todo:
        (tmp_path / "cells" / f"{cell.id}.json").write_text(json.dumps(_fake_record(cell), ensure_ascii=False), encoding="utf-8")


def _fill(path: Path, key: str, values: dict[str, dict[str, str]]) -> None:
    with path.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        row.update(values.get(row[key], {}))
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def test_failed_cell_is_marked_excluded(tmp_path: Path) -> None:
    scenes = load_scenes()
    todo = cells(scenes, ["expand"], ["glm-4-6"], 1, ["daily"])
    _write_cells(tmp_path, todo)
    rec_path = tmp_path / "cells" / f"{todo[0].id}.json"
    rec = json.loads(rec_path.read_text(encoding="utf-8"))
    rec.update({"ok": False, "output": "", "result": {"status": 500, "error": "x"}})
    rec_path.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    write_sheets(tmp_path, scenes)
    with (tmp_path / "scores.csv").open(encoding="utf-8", newline="") as f:
        assert next(csv.DictReader(f))["excluded"] == "通信失敗 500"


def test_blind_hides_model_and_compare_flags_disagreements(tmp_path: Path) -> None:
    scenes = load_scenes()
    todo = cells(scenes, None, None, 2, None)
    _write_cells(tmp_path, todo)
    write_sheets(tmp_path, scenes)
    assert make_blind(tmp_path, scenes, sample=1) == 42
    blind_md = (tmp_path / "blind" / "review_blind.md").read_text(encoding="utf-8")
    assert "glm-4-6" not in blind_md and "xialong-v1" not in blind_md
    key = json.loads((tmp_path / "blind" / "blind_key.json").read_text(encoding="utf-8"))
    base = {"naturalness": "4", "appeal": "4", "compliance": "4", "character": "4", "lore": "4", "new_fact": "0"}
    _fill(tmp_path / "scores.csv", "id", {cid: base for cid in key.values()})
    first_code, first_id = next(iter(key.items()))
    independent = {code: base for code in key}
    independent[first_code] = {**base, "appeal": "2"}
    _fill(tmp_path / "blind" / "scores_independent.csv", "code", independent)
    result = compare_scores(tmp_path)
    assert result["compared"] == 42
    assert [f["code"] for f in result["flagged"]] == [first_code]
    assert result["recheck_conditions"] == ["__".join(first_id.split("__")[:3])]


def test_run_without_execute_is_dry_run(capsys, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def fail(*_a, **_k):  # type: ignore[no-untyped-def]
        raise AssertionError("dry-run で通信した")

    monkeypatch.setattr(nai, "call_stream", fail)
    monkeypatch.setattr(nai, "load_token", fail)
    assert main(["run"]) == 0
    assert "生成 126 回" in capsys.readouterr().out
