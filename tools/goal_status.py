#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""goal の状況: 場面単位で「できている／作っている／保留／未着手」を判定し、章に畳む。

Usage:
    python tools/goal_status.py novels/066_作品名
    python tools/goal_status.py novels/066_作品名 --chapter 3 --chars 4000
    python tools/goal_status.py novels/066_作品名 --json
    python tools/goal_status.py novels/066_作品名 --write-meta

場面の状態は writing_bridge の run（`_writing/<scene>/run-NNNN/`）と、いまの本文のハッシュで決める。
確認できないものは「判定不能」とし、「できている」に入れない。
既定は表示のみ。`--write-meta` を付けたときだけ、`_meta.md` の自動生成ブロックを書き換える。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from work_paths import WorkPathError, kind_roots, resolve_unit  # noqa: E402

DONE = "done"
IN_PROGRESS = "in_progress"
HELD = "held"
NOT_STARTED = "not_started"
UNDETERMINED = "undetermined"
EXCLUDED = "excluded"

STATE_LABEL = {
    DONE: "できている",
    IN_PROGRESS: "作っている",
    HELD: "保留",
    NOT_STARTED: "未着手",
    UNDETERMINED: "判定不能",
    EXCLUDED: "対象外",
}

MET = "met"
UNMET = "unmet"

BLOCK_BEGIN = "<!-- goal-status:begin -->"
BLOCK_END = "<!-- goal-status:end -->"

_RE_SCENE = re.compile(r"^ch(\d{2,})-\d{3,}$")
_RE_RUN = re.compile(r"^run-(\d+)$")
_RE_NOVEL_TEXT = re.compile(r"^novel_text(\d+)(?:_(\d+))?\.md$")
_RE_NEXT_TASK = re.compile(r"\*\*次回のタスク\*\*\s*[:：]\s*(.*)")
_RE_CHAPTER_REF = re.compile(r"第\s*(\d+)\s*章")
_RE_META_SECTION2 = re.compile(r"^## 2\. 執筆用コンテキスト", re.MULTILINE)
_RE_BLOCK = re.compile(re.escape(BLOCK_BEGIN) + r".*?" + re.escape(BLOCK_END), re.DOTALL)


@dataclass
class SceneStatus:
    scene_id: str
    chapter: int
    state: str
    detail: str = ""
    run_id: str | None = None


@dataclass
class ChapterStatus:
    chapter: int
    state: str
    scenes: list[SceneStatus] = field(default_factory=list)
    detail: str = ""

    @property
    def done_count(self) -> int:
        return sum(1 for s in self.scenes if s.state == DONE)


@dataclass
class Check:
    name: str
    status: str  # met / unmet / undetermined
    detail: str = ""


@dataclass
class GoalStatus:
    chapters: list[ChapterStatus]
    excluded: list[int]
    reconcile: list[str]
    checks: list[Check] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(c.status == UNMET for c in self.checks)


# ── 場面の判定 ───────────────────────────────────────────────────────


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _read_yaml(path: Path) -> dict:
    import yaml

    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, ValueError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


def _journal_actions(path: Path) -> list[str]:
    actions: list[str] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return actions
    for line in lines:
        if not line.strip():
            continue
        try:
            action = json.loads(line).get("action")
        except ValueError:
            continue
        if isinstance(action, str):
            actions.append(action)
    return actions


def _current_hash(text_path: Path) -> str | None:
    from writing_bridge.hashes import text_sha256

    try:
        return text_sha256(text_path.read_text(encoding="utf-8"))
    except OSError:
        return None


def _runs(scene_dir: Path) -> list[Path]:
    runs = [p for p in scene_dir.iterdir() if p.is_dir() and _RE_RUN.match(p.name)]
    return sorted(runs, key=lambda p: int(_RE_RUN.match(p.name).group(1)))  # type: ignore[union-attr]


def _publish_record(run: Path) -> tuple[str, str] | None:
    """この run の publish が済んでいれば (本文の相対パス, 保存後の本文ハッシュ) を返す。"""
    if "publish" not in _journal_actions(run / "journal.jsonl"):
        return None
    report = _read_json(run / "report.json")
    if report.get("text_save") != "success":
        return None
    digest = report.get("target_text_sha256")
    target = _read_yaml(run / "request.yaml").get("target") or {}
    text_rel = target.get("text_path") if isinstance(target, dict) else None
    if not (isinstance(digest, str) and isinstance(text_rel, str)):
        return None
    return text_rel.replace("\\", "/"), digest


def published_digests(work: Path, scene_ids: list[str]) -> dict[str, set[str]]:
    """場面群の publish 済み run が保存した本文ハッシュを、本文ファイルごとに集める。

    target_text_sha256 は保存後のファイル全体のハッシュなので、同じ章ファイルへ後の場面を
    保存すると先の場面のハッシュは古くなる。章ファイル単位でどれかと一致すれば現行とみなす。
    """
    digests: dict[str, set[str]] = {}
    for scene_id in scene_ids:
        try:
            scene_dir = _writing_scene_dir(work, scene_id)
        except WorkPathError:
            continue
        if not scene_dir.is_dir():
            continue
        for run in _runs(scene_dir):
            record = _publish_record(run)
            if record:
                digests.setdefault(record[0], set()).add(record[1])
    return digests


def _writing_scene_dir(work: Path, scene_id: str) -> Path:
    """執筆接続の場面フォルダ（古い _writing/ か新しい _work/writing/。tools/work_paths.py の組の規則）。"""
    return resolve_unit(work, "writing", scene_id).base


def judge_scene(
    work: Path,
    scene_id: str,
    chapter: int,
    digests: dict[str, set[str]] | None = None,
) -> SceneStatus:
    """場面の状態。digests は同じ章の全場面の保存ハッシュ（省略時はこの場面だけ）。"""
    try:
        scene_dir = _writing_scene_dir(work, scene_id)
    except WorkPathError as error:
        return SceneStatus(scene_id, chapter, HELD, f"場面の置き場を決められない（{error.code}）")
    runs = _runs(scene_dir) if scene_dir.is_dir() else []
    if not runs:
        return SceneStatus(scene_id, chapter, NOT_STARTED, "run なし")

    if digests is None:
        digests = published_digests(work, [scene_id])
    latest = runs[-1]
    published = []
    for r in runs:
        record = _publish_record(r)
        if record and _current_hash(work / record[0]) in digests.get(record[0], set()):
            published.append(r)
    if published:
        if latest is not published[-1] and "publish" not in _journal_actions(
            latest / "journal.jsonl"
        ):
            return SceneStatus(
                scene_id, chapter, IN_PROGRESS,
                f"保存済みだが後続の {latest.name} が未保存", latest.name,
            )
        return SceneStatus(scene_id, chapter, DONE, "保存済み・本文と一致", published[-1].name)

    repair = _read_json(latest / "repair_state.json")
    if repair.get("status") == "escalated":
        return SceneStatus(scene_id, chapter, HELD, "修復が escalated（報告待ち）", latest.name)

    actions = _journal_actions(latest / "journal.jsonl")
    if "publish" in actions:
        return SceneStatus(
            scene_id, chapter, IN_PROGRESS, "保存後に本文が変わった（計測が古い）", latest.name
        )
    last = actions[-1] if actions else "準備のみ"
    note = "修復が active" if repair.get("status") == "active" else f"最後の工程: {last}"
    return SceneStatus(scene_id, chapter, IN_PROGRESS, note, latest.name)


# ── 章への畳み込み ───────────────────────────────────────────────────


def _chapter_text_files(work: Path) -> dict[int, list[Path]]:
    text_dir = work / "_novel_text"
    out: dict[int, list[Path]] = {}
    if not text_dir.is_dir():
        return out
    for f in sorted(text_dir.glob("novel_text*.md")):
        m = _RE_NOVEL_TEXT.match(f.name)
        if m:
            out.setdefault(int(m.group(1)), []).append(f)
    return out


def _scene_ids(work: Path) -> dict[int, set[str]]:
    found: dict[int, set[str]] = {}
    for root in (*kind_roots(work, "metron"), *kind_roots(work, "writing")):
        for d in root.iterdir():
            m = _RE_SCENE.match(d.name)
            if d.is_dir() and m:
                found.setdefault(int(m.group(1)), set()).add(d.name)
    return found


def fold_chapter(chapter: int, scenes: list[SceneStatus], has_text: bool) -> ChapterStatus:
    if not scenes:
        if has_text:
            return ChapterStatus(
                chapter, UNDETERMINED, [], "本文はあるが場面の記録（METRON・執筆接続の場面フォルダ）がない"
            )
        return ChapterStatus(chapter, NOT_STARTED, [], "")
    states = {s.state for s in scenes}
    if HELD in states:
        state = HELD
    elif states == {DONE}:
        state = DONE
    elif states == {NOT_STARTED}:
        state = NOT_STARTED
    else:
        state = IN_PROGRESS
    return ChapterStatus(chapter, state, scenes)


def _measure_from(work: Path) -> int | None:
    from inspection_flags import InspectionConfigError, load_inspection_flags

    try:
        return load_inspection_flags(work / "config.md").measure_from
    except InspectionConfigError:
        return None


def collect_chapters(work: Path) -> tuple[list[ChapterStatus], list[int]]:
    texts = _chapter_text_files(work)
    scene_map = _scene_ids(work)
    measure_from = _measure_from(work)
    chapters: list[ChapterStatus] = []
    excluded: list[int] = []
    for chapter in sorted(set(texts) | set(scene_map)):
        if measure_from is not None and chapter < measure_from:
            excluded.append(chapter)
            continue
        scene_ids = sorted(scene_map.get(chapter, ()))
        digests = published_digests(work, scene_ids)
        scenes = [judge_scene(work, sid, chapter, digests) for sid in scene_ids]
        chapters.append(fold_chapter(chapter, scenes, chapter in texts))
    return chapters, excluded


# ── _meta.md との突合 ────────────────────────────────────────────────


def read_next_task(meta_text: str) -> str | None:
    m = _RE_NEXT_TASK.search(meta_text)
    return m.group(1).strip() if m else None


def reconcile_with_meta(meta_text: str, chapters: list[ChapterStatus]) -> list[str]:
    """`_meta.md` の「次回のタスク」と、実際の章の状態の食い違いを文にして返す。"""
    if not meta_text:
        return ["_meta.md がありません"]
    task = read_next_task(meta_text)
    if task is None:
        return ["_meta.md に「次回のタスク」の行がありません"]
    if not task or task.startswith(("(", "（")):
        return ["「次回のタスク」が未記入です"]

    by_chapter = {c.chapter: c for c in chapters}
    mentioned = sorted({int(n) for n in _RE_CHAPTER_REF.findall(task)})
    notes: list[str] = []
    for n in mentioned:
        c = by_chapter.get(n)
        if c is not None and c.state == DONE:
            notes.append(f"次回タスクは第{n}章を指していますが、第{n}章は「できている」です")
    pending = [c for c in chapters if c.state in (IN_PROGRESS, HELD, NOT_STARTED)]
    if pending and not mentioned:
        first = pending[0]
        notes.append(
            f"次に手を付ける章は第{first.chapter}章（{STATE_LABEL[first.state]}）ですが、"
            "次回タスクに章の記載がありません"
        )
    elif pending and mentioned and all(n not in {c.chapter for c in pending} for n in mentioned):
        first = pending[0]
        notes.append(
            f"次回タスクが指す章に未完了がありません。未完了は第{first.chapter}章"
            f"（{STATE_LABEL[first.state]}）です"
        )
    return notes


# ── 達成判定 ─────────────────────────────────────────────────────────


def _chapter_chars(files: list[Path]) -> int:
    from novel_char_count import count_chars

    return sum(count_chars(f.read_text(encoding="utf-8"), strip_fm=True) for f in files)


def evaluate(
    work: Path,
    *,
    chapter: int | None = None,
    chars: int | None = None,
    tolerance: tuple[float, float] = (0.97, 1.03),
    project_check: bool = True,
) -> GoalStatus:
    chapters, excluded = collect_chapters(work)
    meta_path = work / "_meta.md"
    meta_text = meta_path.read_text(encoding="utf-8") if meta_path.is_file() else ""
    status = GoalStatus(chapters, excluded, reconcile_with_meta(meta_text, chapters))

    if project_check:
        from novel_status import _run_project_check

        res = _run_project_check(work)
        status.checks.append(
            Check(
                "プロジェクト検査",
                MET if res.get("ok") else UNMET,
                "" if res.get("ok") else "; ".join(str(i) for i in res.get("issues", []))[:200],
            )
        )

    scoped = [c for c in chapters if chapter is None or c.chapter == chapter]
    if chapter is not None and not scoped:
        status.checks.append(Check(f"第{chapter}章", UNMET, "本文も場面の記録もない"))
    for c in scoped:
        if c.state == DONE:
            status.checks.append(Check(f"第{c.chapter}章の保存", MET, f"{c.done_count}場面すべて保存済み"))
        elif c.state == UNDETERMINED:
            status.checks.append(Check(f"第{c.chapter}章の保存", "undetermined", c.detail))
        else:
            status.checks.append(
                Check(f"第{c.chapter}章の保存", UNMET, f"{STATE_LABEL[c.state]}（{_scene_summary(c)}）")
            )

    if chars is not None:
        if chapter is None:
            status.checks.append(Check("字数", "undetermined", "--chars には --chapter が必要です"))
        else:
            files = _chapter_text_files(work).get(chapter, [])
            if not files:
                status.checks.append(Check(f"第{chapter}章の字数", UNMET, "本文ファイルがない"))
            else:
                total = _chapter_chars(files)
                lo, hi = int(chars * tolerance[0]), int(chars * tolerance[1])
                status.checks.append(
                    Check(
                        f"第{chapter}章の字数",
                        MET if lo <= total <= hi else UNMET,
                        f"{total}字（許容 {lo}〜{hi}字）",
                    )
                )
    return status


def _scene_summary(c: ChapterStatus) -> str:
    return f"{c.done_count}/{len(c.scenes)}場面が保存済み" if c.scenes else "場面なし"


# ── 出力 ─────────────────────────────────────────────────────────────


def render_meta_block(status: GoalStatus, today: date | None = None) -> str:
    today = today or date.today()
    lines = [
        BLOCK_BEGIN,
        "### goal の状況（自動生成: tools/goal_status.py）",
        f"更新: {today.isoformat()}。この枠の中は書き換わります。手書きのメモは枠の外へ書いてください。",
        "",
        "| 章 | 状態 | 保存済み場面 | 備考 |",
        "|---|---|---|---|",
    ]
    for c in status.chapters:
        note = c.detail or "; ".join(
            f"{s.scene_id}: {s.detail}" for s in c.scenes if s.state != DONE
        )
        lines.append(
            f"| 第{c.chapter}章 | {STATE_LABEL[c.state]} | {_scene_summary(c)} | {note} |"
        )
    if not status.chapters:
        lines.append("| — | — | — | 章の記録がありません |")
    if status.excluded:
        lines.append("")
        lines.append("計測対象外（下書き期）: " + "、".join(f"第{n}章" for n in status.excluded))
    held = [s for c in status.chapters for s in c.scenes if s.state == HELD]
    if held:
        lines.append("")
        lines.append("保留: " + "、".join(f"{s.scene_id}（{s.detail}）" for s in held))
    if status.reconcile:
        lines.append("")
        lines.append("突合（次回のタスクと実際の状態）:")
        lines.extend(f"- {n}" for n in status.reconcile)
    lines.append(BLOCK_END)
    return "\n".join(lines)


def apply_meta_block(meta_text: str, block: str) -> str:
    """自動生成ブロックだけを置き換える。枠が無ければ「## 2.」の前（無ければ末尾）に足す。"""
    if _RE_BLOCK.search(meta_text):
        return _RE_BLOCK.sub(lambda _m: block, meta_text, count=1)
    m = _RE_META_SECTION2.search(meta_text)
    if m:
        return meta_text[: m.start()] + block + "\n\n" + meta_text[m.start():]
    sep = "" if meta_text.endswith("\n\n") else ("\n" if meta_text.endswith("\n") else "\n\n")
    return meta_text + sep + block + "\n"


def write_meta(work: Path, status: GoalStatus, today: date | None = None) -> bool:
    path = work / "_meta.md"
    if not path.is_file():
        return False
    old = path.read_text(encoding="utf-8")
    new = apply_meta_block(old, render_meta_block(status, today))
    if new == old:
        return True
    tmp = path.with_suffix(".md.tmp")
    tmp.write_text(new, encoding="utf-8", newline="\n")
    os.replace(tmp, path)
    return True


def render_text(status: GoalStatus) -> str:
    out: list[str] = []
    out.append("章の状態")
    for c in status.chapters:
        out.append(f"  第{c.chapter}章  {STATE_LABEL[c.state]}  {_scene_summary(c)}")
        for s in c.scenes:
            if s.state != DONE:
                out.append(f"      {s.scene_id}: {STATE_LABEL[s.state]}（{s.detail}）")
        if c.detail:
            out.append(f"      {c.detail}")
    if not status.chapters:
        out.append("  （章の記録がありません）")
    if status.excluded:
        out.append("  計測対象外: " + "、".join(f"第{n}章" for n in status.excluded))
    if status.reconcile:
        out.append("突合")
        out.extend(f"  ! {n}" for n in status.reconcile)
    if status.checks:
        out.append("達成判定")
        mark = {MET: "OK ", UNMET: "NG ", "undetermined": "?? "}
        for chk in status.checks:
            out.append(f"  [{mark[chk.status]}] {chk.name}  {chk.detail}".rstrip())
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    from console_io import configure_stdio_utf8

    configure_stdio_utf8()
    p = argparse.ArgumentParser(description="goal の状況（場面単位で判定し章に畳む）")
    p.add_argument("work_dir", help="novels/NNN_作品名")
    p.add_argument("--chapter", type=int, help="達成判定の対象章（省略時は全章）")
    p.add_argument("--chars", type=int, help="仕上がり目標字数（--chapter と併用）")
    p.add_argument("--tolerance", default="0.97,1.03", help="字数の許容帯（下限,上限の倍率）")
    p.add_argument("--no-project-check", action="store_true", help="プロジェクト検査を省く")
    p.add_argument("--json", action="store_true", help="JSON で出力")
    p.add_argument("--write-meta", action="store_true", help="_meta.md の自動生成ブロックを更新する")
    args = p.parse_args(argv)
    if args.chars is not None and args.chapter is None:
        p.error("--chars には --chapter が必要です")

    work = Path(args.work_dir)
    if not work.is_dir():
        print(f"ERROR: {work} が見つかりません", file=sys.stderr)
        return 2
    try:
        lo, hi = (float(x) for x in args.tolerance.split(","))
    except ValueError:
        print("ERROR: --tolerance は 0.97,1.03 の形で指定してください", file=sys.stderr)
        return 2

    status = evaluate(
        work,
        chapter=args.chapter,
        chars=args.chars,
        tolerance=(lo, hi),
        project_check=not args.no_project_check,
    )
    if args.write_meta:
        if not write_meta(work, status):
            print("ERROR: _meta.md がありません", file=sys.stderr)
            return 2
    if args.json:
        print(json.dumps(asdict(status) | {"ok": status.ok}, ensure_ascii=False, indent=2))
    else:
        print(render_text(status))
        if args.write_meta:
            print("_meta.md の自動生成ブロックを更新しました")
    return 0 if status.ok else 1


if __name__ == "__main__":
    sys.exit(main())
