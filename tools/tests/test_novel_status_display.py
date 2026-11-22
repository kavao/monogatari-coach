#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""novel_status_display.py（init / check / write / move）。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import chapter_status as cs  # noqa: E402
import novel_status_display as nsd  # noqa: E402

BODY = "　朝の道を歩いた。\n"


def _work(tmp_path: Path, *, metron: str = "OFF", mode: str = "TEXT") -> Path:
    work = tmp_path / "050_test"
    (work / "_novel_text").mkdir(parents=True)
    rows = [f"| METRON | {metron} |", f"| CHAPTER_STATUS | {mode} |"]
    if mode == "TEXT":
        rows.append("| CHAPTER_STATUS_STYLE | notice_log |")
    (work / "config.md").write_text(
        "## 基本情報\n\n| 項目 | 内容 |\n|---|---|\n| 作品名 | 試し |\n" + "\n".join(rows) + "\n",
        encoding="utf-8",
    )
    return work


def _write(work: Path, name: str, text: str) -> Path:
    path = work / "_novel_text" / name
    path.write_text(text, encoding="utf-8")
    return path


@pytest.mark.parametrize("style", cs.STYLES)
def test_init_every_style(tmp_path: Path, style: str) -> None:
    work = _work(tmp_path)
    nsd.cmd_init(work, style, None)
    text = (work / cs.STATUS_DISPLAY_NAME).read_text(encoding="utf-8")
    assert f"型: {style}" in text and "# ステータス表示 — 試し" in text
    for section in ("## 書式", "## 項目の定義", "## 本文内の通知", "## 台帳"):
        assert section in text
    assert not cs.parse_notice_definition(text).enabled
    with pytest.raises(nsd.StatusDisplayError):
        nsd.cmd_init(work, style, None)


def test_init_with_notice_example_is_usable(tmp_path: Path) -> None:
    work = _work(tmp_path)
    nsd.cmd_init(work, "notice_log", "heaven_voice")
    notice = cs.parse_notice_definition((work / cs.STATUS_DISPLAY_NAME).read_text(encoding="utf-8"))
    assert notice.usable and notice.brackets == (("《", "》"),)


def test_check_missing_block_only_for_completed_chapter(tmp_path: Path) -> None:
    work = _work(tmp_path)
    _write(work, "novel_text01_1.md", BODY)
    assert nsd.check_work(work)["ok"]
    result = nsd.check_work(work, completed_chapter=1)
    assert not result["ok"] and "章末ブロックがありません" in result["errors"][0]


def test_write_then_check_ok(tmp_path: Path) -> None:
    work = _work(tmp_path)
    _write(work, "novel_text01_1.md", BODY)
    last = _write(work, "novel_text01_2.md", BODY)
    result = nsd.cmd_write(work, 1, "《記録》技能を得た\n")
    assert result["file"] == "novel_text01_2.md"
    assert (work / "_novel_text_backup" / "novel_text01_2_v001.md").is_file()
    assert cs.scan(last.read_text(encoding="utf-8")).blocks
    assert nsd.check_work(work, completed_chapter=1)["ok"]


def test_write_refused_when_metron_on(tmp_path: Path) -> None:
    work = _work(tmp_path, metron="ON")
    _write(work, "novel_text01.md", BODY)
    with pytest.raises(nsd.StatusDisplayError):
        nsd.cmd_write(work, 1, "x\n")


def test_block_not_in_last_file_warns(tmp_path: Path) -> None:
    work = _work(tmp_path)
    _write(work, "novel_text01_1.md", BODY + "\n" + cs.render_block("x"))
    _write(work, "novel_text01_2.md", BODY)
    result = nsd.check_work(work)
    assert result["ok"] and "最後のファイル" in result["warnings"][0]


def test_move_resumes_after_interruption(tmp_path: Path) -> None:
    work = _work(tmp_path)
    source = _write(work, "novel_text01_1.md", BODY + "\n" + cs.render_block("x"))
    target = _write(work, "novel_text01_2.md", BODY)
    # 移動先に書いた直後で止まった状態を作る（記録は written の手前の recorded のまま）。
    original = nsd._set_block
    calls: list[Path] = []

    def stop_after_first(work_: Path, path: Path, content: str | None) -> Path:
        calls.append(path)
        if len(calls) == 2:
            raise OSError("中断")
        return original(work_, path, content)

    nsd._set_block = stop_after_first  # type: ignore[assignment]
    try:
        with pytest.raises(OSError):
            nsd.cmd_move(work, 1)
    finally:
        nsd._set_block = original  # type: ignore[assignment]
    assert cs.scan(source.read_text(encoding="utf-8")).blocks
    assert cs.scan(target.read_text(encoding="utf-8")).blocks
    interim = nsd.check_work(work)
    assert interim["ok"] and "移動中" in interim["infos"][0]

    code, _ = nsd.cmd_move(work, 1)
    assert code == nsd.EXIT_OK
    assert not cs.scan(source.read_text(encoding="utf-8")).blocks
    assert cs.scan(target.read_text(encoding="utf-8")).blocks
    record = json.loads(nsd.move_record_path(work, 1).read_text(encoding="utf-8"))
    assert record["stage"] == "done"
    assert nsd.check_work(work, completed_chapter=1)["errors"] == []


def test_move_with_metron_on_waits_for_status_block_runs(tmp_path: Path) -> None:
    work = _work(tmp_path, metron="ON")
    source = _write(work, "novel_text01_1.md", BODY + "\n" + cs.render_block("x"))
    target = _write(work, "novel_text01_2.md", BODY)
    code, messages = nsd.cmd_move(work, 1)
    assert code == nsd.EXIT_WAITING and "status_block" in messages[-1]
    target.write_text(cs.replace_block(BODY, "x"), encoding="utf-8")  # status_block の run が書いた想定
    code, messages = nsd.cmd_move(work, 1)
    assert code == nsd.EXIT_WAITING and "外して" in messages[-1]
    source.write_text(BODY, encoding="utf-8")
    code, _ = nsd.cmd_move(work, 1)
    assert code == nsd.EXIT_OK


def test_duplicate_without_record_is_error(tmp_path: Path) -> None:
    work = _work(tmp_path)
    _write(work, "novel_text01_1.md", BODY + "\n" + cs.render_block("x"))
    _write(work, "novel_text01_2.md", BODY + "\n" + cs.render_block("y"))
    assert not nsd.check_work(work)["ok"]


def test_move_resume_does_not_remove_the_only_block(tmp_path: Path) -> None:
    work = _work(tmp_path)
    source = _write(work, "novel_text01_1.md", BODY + "\n" + cs.render_block("x"))
    target = _write(work, "novel_text01_2.md", BODY)
    original = nsd._set_block
    calls: list[Path] = []

    def stop_after_first(work_: Path, path: Path, content: str | None) -> Path:
        calls.append(path)
        if len(calls) == 2:
            raise OSError("中断")
        return original(work_, path, content)

    nsd._set_block = stop_after_first  # type: ignore[assignment]
    try:
        with pytest.raises(OSError):
            nsd.cmd_move(work, 1)
    finally:
        nsd._set_block = original  # type: ignore[assignment]
    target.write_text(BODY, encoding="utf-8")  # 中断のあいだに移動先のブロックが外れた
    with pytest.raises(nsd.StatusDisplayError):
        nsd.cmd_move(work, 1)
    assert cs.scan(source.read_text(encoding="utf-8")).blocks
    assert json.loads(nsd.move_record_path(work, 1).read_text(encoding="utf-8"))["stage"] != "done"


LEDGER = (
    "## 項目の定義\n\n| 項目 | 尺度 | 初期値 | 見せる転機 |\n|---|---|---|---|\n"
    "| HP | 数値 | 30 | 戦闘のあと |\n| 魔力 | 数値 | 10 | 修行のあと |\n\n"
    "## 台帳\n\n| 章 | 項目 | 値 | 根拠 |\n|---|---|---|---|\n"
    "| 1 | HP | 50 | 戦闘 |\n| 1 | 魔力 | 10 | 未確認でない |\n| 1 | 段階 | 未確認 | |\n"
)


@pytest.mark.parametrize(
    ("block", "mismatch"),
    [
        ("《記録》\n・HP 100　魔力 10\n", True),
        ("《記録》\n・HP 50　魔力 10\n", False),
        ("ミナト\n・HP 30 → 50\n", False),
        ("ミナト\n・HP 50 → 30\n", True),
        ("《記録》\n・HP 500\n", True),
        ("《記録》\n・技能を得た\n", False),  # 項目名が出ていなければ機械では判定しない
    ],
)
def test_check_compares_block_with_ledger(tmp_path: Path, block: str, mismatch: bool) -> None:
    work = _work(tmp_path)
    (work / cs.STATUS_DISPLAY_NAME).write_text(LEDGER, encoding="utf-8")
    _write(work, "novel_text01.md", BODY + "\n" + cs.render_block(block))
    warnings = nsd.check_work(work, completed_chapter=1)["warnings"]
    assert any("台帳の値" in w for w in warnings) is mismatch, warnings
    assert any("「段階」" in w and "項目の定義" in w for w in warnings)


def _interrupt_after_target_written(work: Path) -> None:
    original = nsd._set_block
    calls: list[Path] = []

    def stop_after_first(work_: Path, path: Path, content: str | None) -> Path:
        calls.append(path)
        if len(calls) == 2:
            raise OSError("中断")
        return original(work_, path, content)

    nsd._set_block = stop_after_first  # type: ignore[assignment]
    try:
        with pytest.raises(OSError):
            nsd.cmd_move(work, 1)
    finally:
        nsd._set_block = original  # type: ignore[assignment]


def _interrupt_after_record(work: Path) -> None:
    original = nsd._set_block

    def stop(work_: Path, path: Path, content: str | None) -> Path:
        raise OSError("中断")

    nsd._set_block = stop  # type: ignore[assignment]
    try:
        with pytest.raises(OSError):
            nsd.cmd_move(work, 1)
    finally:
        nsd._set_block = original  # type: ignore[assignment]


def test_move_resume_does_not_overwrite_a_different_block_in_target(tmp_path: Path) -> None:
    work = _work(tmp_path)
    _write(work, "novel_text01_1.md", BODY + "\n" + cs.render_block("x"))
    target = _write(work, "novel_text01_2.md", BODY)
    _interrupt_after_record(work)  # 記録は recorded のまま、移動先はまだ書いていない
    target.write_text(cs.replace_block(BODY, "別の中身"), encoding="utf-8")
    with pytest.raises(nsd.StatusDisplayError):
        nsd.cmd_move(work, 1)
    assert cs.scan(target.read_text(encoding="utf-8")).blocks[0].content.strip() == "別の中身"


def test_move_resume_stops_when_source_block_changed(tmp_path: Path) -> None:
    work = _work(tmp_path)
    source = _write(work, "novel_text01_1.md", BODY + "\n" + cs.render_block("x"))
    _write(work, "novel_text01_2.md", BODY)
    _interrupt_after_target_written(work)
    source.write_text(cs.replace_block(source.read_text(encoding="utf-8"), "書き換えた中身"), encoding="utf-8")
    with pytest.raises(nsd.StatusDisplayError):
        nsd.cmd_move(work, 1)
    assert "書き換えた中身" in source.read_text(encoding="utf-8")
    assert json.loads(nsd.move_record_path(work, 1).read_text(encoding="utf-8"))["stage"] != "done"


def test_move_resume_does_not_finish_when_source_block_was_restored(tmp_path: Path) -> None:
    work = _work(tmp_path)
    source = _write(work, "novel_text01_1.md", BODY + "\n" + cs.render_block("x"))
    target = _write(work, "novel_text01_2.md", BODY)
    original_save = nsd._save_move_record

    def stop_at_removed(work_: Path, record: dict[str, object]) -> None:
        original_save(work_, record)
        if record["stage"] == "removed":
            raise OSError("中断")

    nsd._save_move_record = stop_at_removed  # type: ignore[assignment]
    try:
        with pytest.raises(OSError):
            nsd.cmd_move(work, 1)
    finally:
        nsd._save_move_record = original_save  # type: ignore[assignment]
    assert not cs.scan(source.read_text(encoding="utf-8")).blocks
    backup = work / "_novel_text_backup" / "novel_text01_1_v001.md"
    source.write_text(backup.read_text(encoding="utf-8"), encoding="utf-8")  # 旧版から戻した
    with pytest.raises(nsd.StatusDisplayError):
        nsd.cmd_move(work, 1)
    assert cs.scan(source.read_text(encoding="utf-8")).blocks
    assert cs.scan(target.read_text(encoding="utf-8")).blocks
    assert json.loads(nsd.move_record_path(work, 1).read_text(encoding="utf-8"))["stage"] == "removed"
