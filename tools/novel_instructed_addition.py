"""指示加筆のあとの同期の段を記録する（計画 20261121_metron-length-relaxation §10.4）。

作者が「〇〇を足して」と指示したときは、その指示を承認とみなして本文を書き、そのあとで設計へ同期する。
同期は段に分け、全段が終わるまで「指示加筆の完了」と報告しない。途中で止まったら、本文は戻さず、
最初の未完了の段から再開する。このツールは記録だけを持ち、本文・設計書・episodes.yaml は書き換えない。

段（作品の設定と、足したのが出来事かディテールかで決まる）:

- text_saved: 本文の保存（METRON ON は保存用 run の publish）
- story_reflection: novel-story-reflection で設計書と _meta.md
- episodes: 出来事を足したときだけ。episodes.yaml に子エピソード（span あり・span_pending なし）を登録
- beats: METRON ON かつ出来事を足したときだけ。Beat の intent と chars_hint（直す必要が無ければ --skip）
- chronos: CHRONOS ON かつ出来事を足したときだけ。イベントを既存の承認の手順で

    uv run python tools/novel_instructed_addition.py start novels/NNN --chapter 3 --kind event --instruction "駅の場面に母との会話を足す"
    uv run python tools/novel_instructed_addition.py mark novels/NNN ch03-20261122T101500 --step text_saved
    uv run python tools/novel_instructed_addition.py mark novels/NNN ch03-20261122T101500 --step episodes --scene-id ch03-001 --episode-id ep-mother-talk
    uv run python tools/novel_instructed_addition.py mark novels/NNN ch03-20261122T101500 --step beats --skip --reason "intent に収まる"
    uv run python tools/novel_instructed_addition.py status novels/NNN ch03-20261122T101500
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Any

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from inspection_flags import InspectionFlag, load_inspection_flags  # noqa: E402
from work_paths import new_only_location  # noqa: E402

SCHEMA = 1
STEP_ORDER = ("text_saved", "story_reflection", "episodes", "beats", "chronos")
STEP_LABELS = {
    "text_saved": "本文の保存",
    "story_reflection": "設計書と _meta.md の同期（novel-story-reflection）",
    "episodes": "episodes.yaml への子エピソードの登録",
    "beats": "beats.yaml の intent と chars_hint",
    "chronos": "CHRONOS のイベント",
}
_RECORD_ID_RE = re.compile(r"^ch\d{2,}-\d{8}T\d{6}(?:-\d+)?$")


class AdditionError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def required_steps(*, kind: str, metron_on: bool, chronos_on: bool) -> list[str]:
    steps = ["text_saved", "story_reflection"]
    if kind == "event":
        steps.append("episodes")
        if metron_on:
            steps.append("beats")
        if chronos_on:
            steps.append("chronos")
    return steps


def _folder(work: Path) -> Path:
    return new_only_location(work, "additions")


def _record_path(work: Path, record_id: str) -> Path:
    if not _RECORD_ID_RE.fullmatch(record_id):
        raise AdditionError("BAD_ID", f"記録の ID の形ではない: {record_id}")
    return _folder(work) / f"{record_id}.json"


def _write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temp, path)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise


def load(work: Path, record_id: str) -> dict[str, Any]:
    path = _record_path(work, record_id)
    if not path.is_file():
        raise AdditionError("UNKNOWN_REF", f"指示加筆の記録が無い: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != SCHEMA:
        raise AdditionError("SCHEMA_UNSUPPORTED", f"記録の版が違う: {path}")
    return data


def pending_steps(data: dict[str, Any]) -> list[str]:
    return [step for step in data["steps"] if step not in data["done"]]


def start(work: Path, *, chapter: int, kind: str, instruction: str, now: datetime | None = None) -> str:
    if kind not in {"event", "detail"}:
        raise AdditionError("BAD_ID", "kind は event（出来事を足す）か detail（ディテールを足す）")
    if not instruction.strip():
        raise AdditionError("MISSING_FIELD", "作者の指示を記録する（--instruction）")
    flags = load_inspection_flags(work / "config.md")
    steps = required_steps(kind=kind, metron_on=flags.metron is InspectionFlag.ON,
                           chronos_on=flags.chronos is InspectionFlag.ON)
    stamp = (now or datetime.now()).strftime("%Y%m%dT%H%M%S")
    record_id = f"ch{chapter:02d}-{stamp}"
    path = _record_path(work, record_id)
    suffix = 1
    while path.exists():
        suffix += 1
        record_id = f"ch{chapter:02d}-{stamp}-{suffix}"
        path = _record_path(work, record_id)
    _write(path, {"schema": SCHEMA, "id": record_id, "chapter": chapter, "kind": kind,
                  "instruction": instruction.strip(), "steps": steps, "done": {},
                  "started_at": (now or datetime.now()).isoformat(timespec="seconds")})
    return record_id


def _check_episode(work: Path, scene_id: str, episode_id: str) -> None:
    from metron.episodes import load_episodes
    from work_paths import resolve_unit

    path = resolve_unit(work, "metron", scene_id).base / "episodes.yaml"
    if not path.is_file():
        raise AdditionError("UNKNOWN_REF", f"episodes.yaml が無い: {path}")
    document = load_episodes(path)
    episode = next((item for item in document.episodes if item.id == episode_id), None)
    if episode is None:
        raise AdditionError("UNKNOWN_REF", f"{scene_id} の episodes.yaml に {episode_id} が無い")
    if episode.span_pending or episode.span is None:
        raise AdditionError("JOB_CONFLICT",
                            f"{episode_id} は本文があるので span（開始・終了の引用）を入れ、span_pending を外す")


def mark(work: Path, record_id: str, *, step: str, skip: bool = False, reason: str = "",
         scene_id: str | None = None, episode_id: str | None = None, now: datetime | None = None) -> list[str]:
    data = load(work, record_id)
    if step not in data["steps"]:
        raise AdditionError("BAD_ID", f"この指示加筆に {step} の段は無い（段: {', '.join(data['steps'])}）")
    pending = pending_steps(data)
    if step in data["done"]:
        return pending
    if pending and pending[0] != step:
        raise AdditionError("JOB_CONFLICT", f"先に {pending[0]}（{STEP_LABELS[pending[0]]}）を済ませる")
    if skip:
        if step in {"text_saved", "story_reflection", "episodes"}:
            raise AdditionError("JOB_CONFLICT", f"{step} は飛ばせない")
        if not reason.strip():
            raise AdditionError("MISSING_FIELD", "飛ばす理由を書く（--reason）")
    if step == "episodes" and not skip:
        if not scene_id or not episode_id:
            raise AdditionError("MISSING_FIELD", "episodes の段は --scene-id と --episode-id を付ける")
        _check_episode(work, scene_id, episode_id)
    entry: dict[str, Any] = {"at": (now or datetime.now()).isoformat(timespec="seconds")}
    if skip:
        entry["skipped"] = reason.strip()
    if episode_id:
        entry["episode"] = f"{scene_id}/{episode_id}"
    data["done"][step] = entry
    _write(_record_path(work, record_id), data)
    return pending_steps(data)


def render_status(data: dict[str, Any]) -> str:
    lines = [f"指示加筆 {data['id']}（第{data['chapter']}章、{'出来事' if data['kind'] == 'event' else 'ディテール'}）",
             f"- 指示: {data['instruction']}"]
    for step in data["steps"]:
        done = data["done"].get(step)
        mark_text = "済" if done and "skipped" not in done else ("飛ばした" if done else "未")
        extra = f"（{done['skipped']}）" if done and "skipped" in done else ""
        lines.append(f"- [{mark_text}] {STEP_LABELS[step]}{extra}")
    pending = pending_steps(data)
    lines.append("指示加筆: " + ("完了" if not pending else f"未完了（次は {STEP_LABELS[pending[0]]}）"))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="指示加筆の同期の段を記録する（本文・設計は書き換えない）")
    sub = parser.add_subparsers(dest="command", required=True)
    p_start = sub.add_parser("start")
    p_start.add_argument("work", type=Path)
    p_start.add_argument("--chapter", type=int, required=True)
    p_start.add_argument("--kind", choices=["event", "detail"], required=True)
    p_start.add_argument("--instruction", required=True)
    p_mark = sub.add_parser("mark")
    p_mark.add_argument("work", type=Path)
    p_mark.add_argument("record_id")
    p_mark.add_argument("--step", choices=list(STEP_ORDER), required=True)
    p_mark.add_argument("--skip", action="store_true")
    p_mark.add_argument("--reason", default="")
    p_mark.add_argument("--scene-id")
    p_mark.add_argument("--episode-id")
    p_status = sub.add_parser("status")
    p_status.add_argument("work", type=Path)
    p_status.add_argument("record_id")
    args = parser.parse_args(argv)
    try:
        if args.command == "start":
            record_id = start(args.work, chapter=args.chapter, kind=args.kind, instruction=args.instruction)
            print(render_status(load(args.work, record_id)))
            return 0
        if args.command == "mark":
            pending = mark(args.work, args.record_id, step=args.step, skip=args.skip, reason=args.reason,
                           scene_id=args.scene_id, episode_id=args.episode_id)
            print(render_status(load(args.work, args.record_id)))
            return 0 if not pending else 3
        data = load(args.work, args.record_id)
        print(render_status(data))
        return 0 if not pending_steps(data) else 3
    except AdditionError as error:
        print(f"[{error.code}] {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
