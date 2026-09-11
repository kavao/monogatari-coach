"""Fill writing-run samples from the ok work tree. Not a runtime tool."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WORK = ROOT / "ok_ch01_001" / "work"
RUN = WORK / "_writing" / "ch01-001" / "run-0001"


def raw_sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = unicodedata.normalize("NFC", text)
    text = re.sub(r"<!--/?beat:[A-Za-z][A-Za-z0-9_-]*-->", "", text)
    text = re.sub(r"<!--fact:[A-Za-z][A-Za-z0-9_-]*-->", "", text)
    return text


def text_sha(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def dump(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == ".jsonl":
        lines = [json.dumps(item, ensure_ascii=False, separators=(",", ":")) for item in payload]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
        return
    if path.suffix == ".md":
        path.write_text(str(payload), encoding="utf-8", newline="\n")
        return
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    path.write_text(text, encoding="utf-8", newline="\n")


def dump_yaml(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def main() -> None:
    novel = WORK / "_novel_text" / "novel_text01.md"
    norm = normalize_text(novel.read_text(encoding="utf-8"))
    base_text = text_sha(norm)
    base_raw = raw_sha(novel)

    quotes = {
        "coat": "旅行用の上着",
        "ticket": "改札の前で切符を買う",
        "station": "駅の券売機の前に立った",
    }
    spans = {key: (norm.find(value), norm.find(value) + len(value)) for key, value in quotes.items()}
    if any(start < 0 for start, _end in spans.values()):
        raise SystemExit(f"quote not found: {spans}")

    def evidence(quote_key: str) -> tuple[int, int, str, str]:
        start, end = spans[quote_key]
        quote = quotes[quote_key]
        if norm[start:end] != quote:
            raise SystemExit("range mismatch")
        return start, end, quote, text_sha(quote)

    metron = WORK / "_metron" / "ch01-001"
    refs = {
        "contract": metron / "contract.yaml",
        "beats": metron / "beats.yaml",
        "marked": metron / "marked.md",
        "metrics": metron / "metrics.001.yaml",
        "spans": metron / "spans.001.yaml",
    }

    request_yaml = f"""schema: 1
request_id: WRQ-0001
run_id: run-0001
work_rel: 000_neutral_trip
scene_id: ch01-001
request_kind: new
target:
  text_path: _novel_text/novel_text01.md
  selector:
    kind: heading
    value: 第一章　駅までの道
  base_raw_sha256: {base_raw}
  base_text_sha256: {base_text}
model:
  id: local-writer
  calibrated: true
permissions:
  draft: true
  repair: false
  publish: false
  event_patch: false
flags:
  metron: ON
  chronos: ON
"""
    dump_yaml(RUN / "request.yaml", request_yaml)

    links_yaml = f"""schema: 1
scene_id: ch01-001
text_path: _novel_text/novel_text01.md
selector:
  kind: heading
  value: 第一章　駅までの道
text_sha256: {base_text}
status: adopted
created_by: agent
adopted_by: agent
items:
  - beat_id: pack_bag
    event_id: EVT-0001
    state_at: after
    actors: [CHR-a]
  - beat_id: say_goodbye
    event_id: EVT-0002
    state_at: after
    actors: [CHR-a]
  - beat_id: reach_station
    event_id: EVT-0001
    state_at: after
    actors: [CHR-a]
"""
    dump_yaml(RUN / "links.yaml", links_yaml)

    expected = [
        {
            "event_id": "EVT-0001",
            "actor_id": "CHR-a",
            "dimension": "outfit",
            "state_at": "after",
            "expected_value": "travel",
        },
        {
            "event_id": "EVT-0001",
            "actor_id": "CHR-a",
            "dimension": "whereabouts",
            "state_at": "after",
            "expected_value": "LOC-station",
        },
        {
            "event_id": "EVT-0002",
            "actor_id": "CHR-a",
            "dimension": "whereabouts",
            "state_at": "after",
            "expected_value": "LOC-station",
        },
    ]
    context = {
        "schema": 1,
        "request_id": "WRQ-0001",
        "run_id": "run-0001",
        "input_hashes": [
            {"path": "_novel_text/novel_text01.md", "raw_sha256": base_raw},
            {"path": "_metron/ch01-001/contract.yaml", "raw_sha256": raw_sha(refs["contract"])},
            {"path": "_metron/ch01-001/beats.yaml", "raw_sha256": raw_sha(refs["beats"])},
            {"path": "chronos/chronos.config.yaml", "raw_sha256": raw_sha(WORK / "chronos" / "chronos.config.yaml")},
            {"path": "chronos/events/ch01.yaml", "raw_sha256": raw_sha(WORK / "chronos" / "events" / "ch01.yaml")},
        ],
        "expected_checks": expected,
        "forbidden": ["旅の目的を途中で変える", "切符を買わずに改札を越える"],
        "instruction_chars": 92,
        "prose_start_end": {
            "start_location": "家の玄関",
            "end_location": "駅の券売機",
            "note": "散文。LOC-home / LOC-station へ変換しない",
        },
        "unresolved": [],
    }
    dump(RUN / "context.json", context)
    dump(
        RUN / "context.md",
        "# context\n\n"
        "兄は旅行用の上着（outfit=travel）で家を出て、駅の券売機前に立つ。\n"
        "散文の「家の玄関」は LOC-home と同一視しない。\n",
    )

    artifact_refs = {
        "schema": 1,
        "request_id": "WRQ-0001",
        "model": {"id": "local-writer", "calibrated": True},
        "metron": {
            key: {"path": f"_metron/ch01-001/{path.name}", "raw_sha256": raw_sha(path)}
            for key, path in refs.items()
        },
    }
    dump(RUN / "artifact_refs.json", artifact_refs)

    items = []
    mapping = [
        ("EVT-0001", "outfit", "travel", "coat"),
        ("EVT-0001", "whereabouts", "LOC-station", "station"),
        ("EVT-0002", "whereabouts", "LOC-station", "station"),
    ]
    for event_id, dimension, value, quote_key in mapping:
        start, end, quote, range_hash = evidence(quote_key)
        items.append(
            {
                "event_id": event_id,
                "actor_id": "CHR-a",
                "dimension": dimension,
                "value": value,
                "state_at": "after",
                "quote": quote,
                "start": start,
                "end": end,
                "range_sha256": range_hash,
                "recorder": "agent",
                "confirmation": "match",
            }
        )
    observations = {
        "schema": 1,
        "request_id": "WRQ-0001",
        "text_sha256": base_text,
        "expected_total": 3,
        "items": items,
    }
    dump(RUN / "observations.json", observations)

    report = {
        "schema": 1,
        "request_id": "WRQ-0001",
        "run_id": "run-0001",
        "target_text_sha256": base_text,
        "text_save": "success",
        "metron": "findings",
        "chronos_registered": "success",
        "text_state": "success",
        "findings": [
            {
                "code": None,
                "note": "METRON V0 は観測のみ。fixture の床は短い。BeatThin は classify しない（R1・未校正扱いはしないが repair 権限なし）",
            }
        ],
        "repair_history": [],
        "open_issues": [],
    }
    dump(RUN / "report.json", report)
    dump(
        RUN / "report.md",
        "# report run-0001\n\n"
        "- 本文保存: success（既存スキル想定。この fixture では work/_novel_text が対象版）\n"
        "- METRON計測・判定: findings（計測済み。repair は権限外）\n"
        "- CHRONOS登録データ検査: success（2 events, 0 findings）\n"
        "- 本文状態照合: success（expected 3 / match 3）\n",
    )

    journal = [
        {"schema": 1, "at": "2026-09-09T02:40:00+09:00", "action": "prepare", "run_id": "run-0001", "request_id": "WRQ-0001"},
        {"schema": 1, "at": "2026-09-09T02:41:00+09:00", "action": "receive", "run_id": "run-0001", "request_id": "WRQ-0001", "hashes": {"text_sha256": base_text}},
        {"schema": 1, "at": "2026-09-09T02:42:00+09:00", "action": "inspect", "run_id": "run-0001", "request_id": "WRQ-0001"},
        {"schema": 1, "at": "2026-09-09T02:43:00+09:00", "action": "select", "run_id": "run-0001", "note": "R1 は既存スキルが保存。publish 権限なし"},
    ]
    dump(RUN / "journal.jsonl", journal)

    start, end, quote, range_hash = evidence("coat")
    missing_obs = {
        "schema": 1,
        "request_id": "WRQ-0001",
        "text_sha256": base_text,
        "expected_total": 3,
        "items": [
            {
                "event_id": "EVT-0001",
                "actor_id": "CHR-a",
                "dimension": "outfit",
                "value": "travel",
                "state_at": "after",
                "quote": quote,
                "start": start,
                "end": end,
                "range_sha256": range_hash,
                "recorder": "agent",
                "confirmation": "match",
            }
        ],
    }
    dump(ROOT / "missing_required" / "observations.json", missing_obs)
    dump(
        ROOT / "missing_required" / "expected_error.json",
        {
            "schema": 1,
            "errors": [
                {
                    "schema": 1,
                    "code": "TEXT_STATE_UNVERIFIED",
                    "severity": "error",
                    "message": "required check not recorded",
                    "refs": {
                        "event_id": "EVT-0001",
                        "actor_id": "CHR-a",
                        "dimension": "whereabouts",
                        "state_at": "after",
                    },
                },
                {
                    "schema": 1,
                    "code": "TEXT_STATE_UNVERIFIED",
                    "severity": "error",
                    "message": "required check not recorded",
                    "refs": {
                        "event_id": "EVT-0002",
                        "actor_id": "CHR-a",
                        "dimension": "whereabouts",
                        "state_at": "after",
                    },
                },
            ],
        },
    )
    dump(
        ROOT / "missing_required" / "README.md",
        "ok 系の expected_checks 3件に対し、outfit 1件しかない。欠落は TEXT_STATE_UNVERIFIED。\n",
    )

    dump_yaml(
        ROOT / "invalid_schema" / "request.yaml",
        """schema: 1
request_id: WRQ-0001
run_id: run-0001
work_rel: 000_neutral_trip
scene_id: ch01-001
request_kind: Yes
extra_flag: true
target:
  text_path: _novel_text/novel_text01.md
  selector:
    kind: heading
    value: 第一章　駅までの道
  base_raw_sha256: not-a-hash
  base_text_sha256: sha256:afdfb80c8271130b1698d54e43d73f07e429d9fe3c175995c99ca1547cc57baf
model:
  id: local-writer
  calibrated: true
permissions:
  draft: true
  repair: false
  publish: false
  event_patch: false
flags:
  metron: ON
  chronos: ON
""",
    )
    dump(
        ROOT / "invalid_schema" / "expected_error.json",
        {
            "schema": 1,
            "errors": [
                {
                    "schema": 1,
                    "code": "UNKNOWN_KEY",
                    "severity": "error",
                    "message": "unknown key extra_flag",
                    "refs": {"path": "request.yaml", "key": "extra_flag"},
                },
                {
                    "schema": 1,
                    "code": "BAD_ID",
                    "severity": "error",
                    "message": "request_kind must be one of new|append|local_expand|refine",
                    "refs": {"path": "request.yaml", "key": "request_kind", "value": "Yes"},
                },
                {
                    "schema": 1,
                    "code": "BAD_HASH",
                    "severity": "error",
                    "message": "base_raw_sha256 must be sha256: plus 64 lowercase hex digits",
                    "refs": {"path": "request.yaml", "key": "target.base_raw_sha256"},
                },
            ],
        },
    )
    dump(
        ROOT / "invalid_schema" / "README.md",
        "未知キー、不正な request_kind、不正ハッシュの同時例。\n",
    )

    dump_yaml(
        ROOT / "stale_hash" / "request.yaml",
        f"""schema: 1
request_id: WRQ-0001
run_id: run-0001
work_rel: 000_neutral_trip
scene_id: ch01-001
request_kind: new
target:
  text_path: _novel_text/novel_text01.md
  selector:
    kind: heading
    value: 第一章　駅までの道
  base_raw_sha256: {base_raw}
  base_text_sha256: sha256:0000000000000000000000000000000000000000000000000000000000000000
model:
  id: local-writer
  calibrated: true
permissions:
  draft: true
  repair: false
  publish: false
  event_patch: false
flags:
  metron: ON
  chronos: ON
""",
    )
    dump(
        ROOT / "stale_hash" / "expected_error.json",
        {
            "schema": 1,
            "code": "STALE_EVIDENCE",
            "severity": "error",
            "message": "base_text_sha256 does not match current normalized text",
            "refs": {
                "path": "_novel_text/novel_text01.md",
                "expected": "sha256:0000000000000000000000000000000000000000000000000000000000000000",
                "actual": base_text,
            },
        },
    )
    dump(
        ROOT / "stale_hash" / "README.md",
        "ok 系と同じ本文に対し、古い base_text_sha256 を置いた例。inspect / publish 前に止める。\n",
    )

    dump_yaml(
        ROOT / "examples" / "job_deepen.yaml",
        f"""schema: 1
job_id: JOB-0001
run_id: run-0001
operation: deepen
beat_id: pack_bag
attempt: 1
input_hash: {base_text}
context_hash: sha256:pending-context
prompt_hash: sha256:pending-prompt
model: local-writer
status: pending
""",
    )
    dump(
        ROOT / "examples" / "README.md",
        "R2 の job 形。context_hash / prompt_hash は実装時に実送信文字列から計算する。\n"
        "regenerate の同一 Beat 上限は 1。deepen は 2。R1 では実行しない。\n",
    )
    print("ok", base_text)


if __name__ == "__main__":
    main()
