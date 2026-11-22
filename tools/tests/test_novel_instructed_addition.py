from __future__ import annotations

from datetime import datetime
import json

import pytest

from test_writing_bridge import _copy_ok
import novel_instructed_addition as addition
from novel_instructed_addition import AdditionError, load, mark, pending_steps, required_steps, start

NOW = datetime(2026, 11, 22, 10, 15, 0)


def _episodes(work, *, pending: bool):
    path = work / "_metron/ch01-001/episodes.yaml"
    body = ("scene_id: ch01-001\nepisodes:\n  - id: ep_mother\n    beat_id: say_goodbye\n"
            + ("    span_pending: true\n" if pending else
               "    span:\n      start: 「鍵は入れた？」\n      end: 切符を買う」\n"))
    path.write_text(body, encoding="utf-8")


def test_steps_follow_the_work_flags_and_the_kind():
    assert required_steps(kind="detail", metron_on=True, chronos_on=True) == ["text_saved", "story_reflection"]
    assert required_steps(kind="event", metron_on=False, chronos_on=False) == [
        "text_saved", "story_reflection", "episodes"]
    assert required_steps(kind="event", metron_on=True, chronos_on=True) == [
        "text_saved", "story_reflection", "episodes", "beats", "chronos"]


def test_record_goes_in_order_and_completes_only_after_every_step(tmp_path):
    work = _copy_ok(tmp_path)  # METRON ON / CHRONOS ON
    record_id = start(work, chapter=1, kind="event", instruction="駅の場面に母との会話を足す", now=NOW)
    assert record_id == "ch01-20261122T101500"
    assert (work / "_work/additions" / f"{record_id}.json").is_file()
    with pytest.raises(AdditionError) as error:
        mark(work, record_id, step="story_reflection")
    assert error.value.code == "JOB_CONFLICT"  # 先に本文の保存
    mark(work, record_id, step="text_saved")
    mark(work, record_id, step="story_reflection")
    _episodes(work, pending=True)
    with pytest.raises(AdditionError) as error:
        mark(work, record_id, step="episodes", scene_id="ch01-001", episode_id="ep_mother")
    assert error.value.code == "JOB_CONFLICT" and "span_pending" in str(error.value)
    _episodes(work, pending=False)
    mark(work, record_id, step="episodes", scene_id="ch01-001", episode_id="ep_mother")
    with pytest.raises(AdditionError):
        mark(work, record_id, step="beats", skip=True)  # 理由なしでは飛ばせない
    mark(work, record_id, step="beats", skip=True, reason="intent に収まる")
    assert pending_steps(load(work, record_id)) == ["chronos"]
    assert mark(work, record_id, step="chronos") == []
    data = json.loads((work / "_work/additions" / f"{record_id}.json").read_text(encoding="utf-8"))
    assert data["done"]["beats"]["skipped"] == "intent に収まる"
    assert data["done"]["episodes"]["episode"] == "ch01-001/ep_mother"


def test_required_steps_cannot_be_skipped_and_cli_reports_incomplete(tmp_path, capsys):
    work = _copy_ok(tmp_path)
    record_id = start(work, chapter=1, kind="detail", instruction="会話に間を足す", now=NOW)
    with pytest.raises(AdditionError):
        mark(work, record_id, step="text_saved", skip=True, reason="x")
    assert addition.main(["status", str(work), record_id]) == 3
    assert "未完了" in capsys.readouterr().out
    assert addition.main(["mark", str(work), record_id, "--step", "text_saved"]) == 3
    assert addition.main(["mark", str(work), record_id, "--step", "story_reflection"]) == 0
    assert addition.main(["status", str(work), record_id]) == 0
    assert addition.main(["status", str(work), "../escape"]) == 2
