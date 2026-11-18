#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Beat の intent が、結果を認識の動詞（知る・気づく・認める・分かる・口にする・理解する・悟る）で
まとめていないかを調べる（助言）。

`novel-text-file-output` の規則「intent は動作だけにする」を、Beat を書いた時点で確かめるための検査。
intent の「〜と知る」は本文の「〜と知った」に写りやすい（計画 _workingspace/plans/20261114_model-adaptive-writing-support.md §13 H3・§14.7）。

LLM / provider を呼ばず、作品ファイルを書き換えない。METRON 場面の置き場は tools/work_paths.py で解決する。
終了コード: 0 = 検査できた（助言の件数によらない） / 2 = 作品フォルダが無い・beats.yaml を読めない
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

import yaml  # noqa: E402

import work_paths  # noqa: E402

# 語幹ごとに、活用の続きを限る（「知らせる」「分かれる」「認め印」などを拾わない）。
COGNITIVE_VERB = re.compile(
    r"(知る|知った|知って|知り|"
    r"気づ[くいかけ]|気付[くいかけ]|"
    r"認め[るたて]|"
    r"分か[るっり]|わか[るっり]|"
    r"口にす|口にし|"
    r"理解す|理解し|"
    r"悟[るっり])"
)
ADVICE = "何を見て・数えて・触って知るのかを書く。口にするなら、台詞の中身を書く。"


@dataclass
class Finding:
    scene_id: str
    beat_id: str
    word: str
    intent: str
    beats_path: str


@dataclass
class Report:
    novel: str
    scenes: list[str]
    beat_count: int
    findings: list[Finding]
    ignored: list[str]
    errors: list[str]


def find_cognitive_verbs(intent: str) -> list[str]:
    return sorted({m.group(1) for m in COGNITIVE_VERB.finditer(intent)})


def check_beats_file(path: Path, scene_id: str, work: Path, ignore: set[str]) -> tuple[int, list[Finding], list[str]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    beats = data.get("beats") or []
    findings: list[Finding] = []
    ignored: list[str] = []
    for beat in beats:
        if not isinstance(beat, dict):
            continue
        beat_id = str(beat.get("id", ""))
        intent = str(beat.get("intent", ""))
        words = find_cognitive_verbs(intent)
        if not words:
            continue
        if beat_id in ignore or f"{scene_id}/{beat_id}" in ignore:
            ignored.append(f"{scene_id}/{beat_id}")
            continue
        rel = path.relative_to(work).as_posix()
        findings.extend(Finding(scene_id, beat_id, w, intent, rel) for w in words)
    return len(beats), findings, ignored


def check_novel(work: Path, scenes: list[str] | None = None, ignore: set[str] | None = None) -> Report:
    report = Report(str(work), [], 0, [], [], [])
    if not work.is_dir():
        report.errors.append(f"作品フォルダがない: {work}")
        return report
    ignore = ignore or set()
    scene_ids = scenes or work_paths.iter_unit_ids(work, "metron")
    for scene_id in scene_ids:
        try:
            location = work_paths.resolve_unit(work, "metron", scene_id)
        except work_paths.WorkPathError as error:
            report.errors.append(f"{scene_id}: {error}")
            continue
        path = location.path("beats.yaml")
        if not path.is_file():
            continue
        try:
            count, findings, ignored = check_beats_file(path, scene_id, work, ignore)
        except (OSError, yaml.YAMLError) as error:
            report.errors.append(f"{scene_id}: beats.yaml を読めない: {error}")
            continue
        report.scenes.append(scene_id)
        report.beat_count += count
        report.findings.extend(findings)
        report.ignored.extend(ignored)
    return report


def render_text(report: Report) -> str:
    lines = [f"作品: {report.novel}"]
    for error in report.errors:
        lines.append(f"[ERROR] {error}")
    lines.append(f"対象: 場面 {len(report.scenes)} / Beat {report.beat_count}")
    beats_hit = {(f.scene_id, f.beat_id) for f in report.findings}
    lines.append(f"intent の認識の動詞（助言）: {len(beats_hit)} Beat")
    for finding in report.findings:
        lines.append(f"  - {finding.scene_id}/{finding.beat_id}「{finding.word}」｜{finding.intent}")
    if report.findings:
        lines.append(f"直し方: {ADVICE}")
    if report.ignored:
        lines.append("指定で外した Beat: " + "、".join(report.ignored))
    lines.append("助言であり、prepare や保存を止めない。意図して使う Beat は --ignore で外す。")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    from console_io import configure_stdio_utf8

    configure_stdio_utf8()
    parser = argparse.ArgumentParser(description="Beat の intent の認識の動詞を調べる（助言・書き換えない）")
    parser.add_argument("novel", type=Path, help="作品フォルダ")
    parser.add_argument("--scene", nargs="+", help="対象の場面 ID（既定: METRON の全場面）")
    parser.add_argument(
        "--ignore",
        nargs="+",
        default=[],
        help="外す Beat（beat_id または scene_id/beat_id）。意図して認識の動詞を使う Beat に使う",
    )
    parser.add_argument("--json", action="store_true", help="JSON で出す")
    args = parser.parse_args(argv)

    report = check_novel(args.novel, args.scene, set(args.ignore))
    if args.json:
        payload = asdict(report)
        payload["advice"] = ADVICE
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(render_text(report))
    if not Path(args.novel).is_dir() or (report.errors and not report.scenes):
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
