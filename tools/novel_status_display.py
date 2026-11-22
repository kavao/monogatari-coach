#!/usr/bin/env python3
"""作品の章末ステータス（CHAPTER_STATUS）を扱う：status_display.md の作成、検査、ブロックの書込み・移動。

正本は `.rulesync/rules/workflow-specification.md`「章末ステータスの表示（CHAPTER_STATUS）」。

サブコマンド:
  init   葉 `_how_to.example/status_display.md` から型のテンプレートを写し、作品の status_display.md を作る
         （既存は上書きしない）。
  check  本文の章末ブロックを検査する。章の完了は推測しない。章完了の手順が
         `--completed-chapter N` で渡した章だけ、ブロックの欠落を判定する。ブロックと台帳の値は
         機械で確かめられる範囲（項目名の出ている行の値）だけ照らし合わせて WARN にする。
         意味の照合は一貫性監査（text）で行う。
  write  METRON OFF の作品で、章の最後のファイルの末尾へブロックを書く（`--remove` で外す）。
         旧版を `_novel_text_backup/<元ファイル名>_vNNN.md` へ退避してから書く。
         METRON ON の作品では書かない（writing_bridge の `prepare --request-kind status_block` を使う）。
  move   分割章で、章の最後のファイルが変わったときにブロックを移す。記録
         （`_work/status_moves/chNN.json`）を書き、移動先に書く → 移動元から外す → 完了、の順に進め、
         止まったら同じコマンドで記録の段階から続ける。METRON ON の作品では書込みをせず、
         status_block の run で書いたかを確かめて段階を進める。

例:
  uv run python tools/novel_status_display.py init novels/050_作品名 --style notice_log --notice heaven_voice
  uv run python tools/novel_status_display.py check novels/050_作品名 --completed-chapter 3
  uv run python tools/novel_status_display.py write novels/050_作品名 --chapter 3 --content-file block.txt
  uv run python tools/novel_status_display.py move novels/050_作品名 --chapter 3
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

import chapter_status as cs  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LEAF = ROOT / "_how_to.example" / "status_display.md"
BACKUP_DIR = "_novel_text_backup"
_FILE_RE = re.compile(r"^novel_text(\d+)(?:_(\d+))?\.md$")

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_USAGE = 2
EXIT_WAITING = 3


class StatusDisplayError(RuntimeError):
    """ツールが続けられない（入力の誤り・設定の誤り・既存ファイル）。"""


# ── 葉のテンプレート ─────────────────────────────


def _fenced_after(text: str, heading: str) -> str:
    """見出しの直後にある最初のコードブロックの中身。"""

    lines = text.splitlines()
    pattern = re.compile(rf"^#{{2,4}}\s+{re.escape(heading)}\s*$")
    start = next((i for i, line in enumerate(lines) if pattern.match(line)), None)
    if start is None:
        raise StatusDisplayError(f"葉に見出しがありません: {heading}")
    inside = False
    body: list[str] = []
    for line in lines[start + 1 :]:
        if line.startswith("```"):
            if inside:
                return "\n".join(body) + "\n"
            inside = True
            continue
        if inside:
            body.append(line)
        elif re.match(r"^#{2,4}\s", line):
            break
    raise StatusDisplayError(f"葉のコードブロックがありません: {heading}")


def _table_after(text: str, heading: str) -> str:
    lines = text.splitlines()
    pattern = re.compile(rf"^#{{2,4}}\s+{re.escape(heading)}\s*$")
    start = next((i for i, line in enumerate(lines) if pattern.match(line)), None)
    if start is None:
        raise StatusDisplayError(f"葉に見出しがありません: {heading}")
    table: list[str] = []
    for line in lines[start + 1 :]:
        if line.startswith("|"):
            table.append(line)
        elif table:
            break
    if not table:
        raise StatusDisplayError(f"葉の表がありません: {heading}")
    return "\n".join(table) + "\n"


def render_status_display(
    title: str, style: str, *, notice: str | None = None, leaf_text: str | None = None,
    today: date | None = None,
) -> str:
    if style not in cs.STYLES:
        raise StatusDisplayError(f"未知の型: {style}（{', '.join(cs.STYLES)}）")
    leaf = leaf_text if leaf_text is not None else LEAF.read_text(encoding="utf-8")
    skeleton = _fenced_after(leaf, "5. 作品の status_display.md の骨組み")
    template = _fenced_after(leaf, f"テンプレート: {style}")
    stamp = (today or date.today()).isoformat()
    text = skeleton.replace("〈作品名〉", title).replace("〈ID〉", style).replace("〈写した日〉", stamp)
    text = text.replace(
        "（型のテンプレート。本文の章末ブロックはこの書式で書く）",
        "本文の章末ブロックはこの書式で書く。\n\n```text\n" + template + "```",
    )
    if notice is not None:
        table = _table_after(leaf, f"演出の例: {notice}")
        text = re.sub(
            r"(## 本文内の通知\n\n)(\|.*\n)+",
            lambda m: m.group(1) + table,
            text,
            count=1,
        )
    return text


def _title_of(work: Path) -> str:
    config = work / "config.md"
    if config.is_file():
        for line in config.read_text(encoding="utf-8-sig").splitlines():
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) == 2 and cells[0] == "作品名" and cells[1]:
                return cells[1]
    return work.name.partition("_")[2] or work.name


def cmd_init(work: Path, style: str, notice: str | None) -> str:
    target = work / cs.STATUS_DISPLAY_NAME
    if target.exists():
        raise StatusDisplayError(f"既にあります（上書きしない）: {target}")
    text = render_status_display(_title_of(work), style, notice=notice)
    with target.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(text)
    return target.as_posix()


# ── 章とファイル ─────────────────────────────


@dataclass(frozen=True)
class ChapterFile:
    path: Path
    chapter: int
    part: int  # 項番号（項なしは 0）


def chapter_files(work: Path) -> dict[int, list[ChapterFile]]:
    chapters: dict[int, list[ChapterFile]] = {}
    for path in sorted((work / "_novel_text").glob("novel_text*.md")):
        match = _FILE_RE.match(path.name)
        if not match:
            continue
        item = ChapterFile(path, int(match.group(1)), int(match.group(2) or 0))
        chapters.setdefault(item.chapter, []).append(item)
    for files in chapters.values():
        files.sort(key=lambda f: f.part)
    return chapters


def last_file(work: Path, chapter: int) -> Path:
    files = chapter_files(work).get(chapter)
    if not files:
        raise StatusDisplayError(f"第{chapter}章の本文ファイルがありません")
    return files[-1].path


def block_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _blocks_in(path: Path) -> list[cs.BlockSpan]:
    return list(cs.scan(path.read_text(encoding="utf-8")).blocks)


_CHAPTER_KEY_RE = re.compile(r"^第?0*(\d+)章?$")
_UNCONFIRMED = {"", "未確認", "-", "—", "ー"}


@dataclass(frozen=True)
class LedgerRow:
    chapter: int
    item: str
    value: str


def _status_display_text(work: Path) -> str | None:
    path = work / cs.STATUS_DISPLAY_NAME
    return path.read_text(encoding="utf-8") if path.is_file() else None


def ledger_rows(text: str) -> list[LedgerRow]:
    rows: list[LedgerRow] = []
    for cells in cs._table(cs._section_lines(text, "台帳")):
        if len(cells) < 3:
            continue
        match = _CHAPTER_KEY_RE.match(cells[0].strip())
        if match:
            rows.append(LedgerRow(int(match.group(1)), cells[1].strip(), cells[2].strip()))
    return rows


def defined_items(text: str) -> list[str]:
    return [cells[0].strip() for cells in cs._table(cs._section_lines(text, "項目の定義")) if cells and cells[0].strip()]


def _ledger_has_chapter(work: Path, chapter: int) -> bool:
    text = _status_display_text(work)
    return text is not None and any(row.chapter == chapter for row in ledger_rows(text))


def _value_segment(line: str, item: str, others: list[str]) -> str:
    """行のうち、項目名のあとから次の項目名の手前まで。差分（旧 → 新）なら新しい値の側。"""

    segment = line[line.index(item) + len(item):]
    cut = min((segment.find(o) for o in others if o != item and o and o in segment), default=-1)
    if cut >= 0:
        segment = segment[:cut]
    if "→" in segment:
        segment = segment.rsplit("→", 1)[1]
    return segment


def _value_in(segment: str, value: str) -> bool:
    # 数字の途中で一致させない（台帳 10 が本文 100 に当たらないように）。
    return re.search(rf"(?<![0-9０-９]){re.escape(value)}(?![0-9０-９])", segment) is not None


def compare_block_with_ledger(
    chapter: int, content: str, rows: list[LedgerRow], items: list[str]
) -> list[str]:
    """機械で確かめられる食い違いだけを返す（警告）。

    - 台帳の項目がブロックの行に名前で出ているのに、その行に台帳の値が無い。
    - 項目の定義がある作品で、台帳の項目が定義に無い。
    項目名がブロックに出ていないとき（差分型で動かなかった値など）と、数値でない経験の記述の
    意味の照合は、機械では判定しない（一貫性監査の手順で読む）。
    """

    findings: list[str] = []
    lines = [line for line in content.splitlines() if line.strip()]
    names = [row.item for row in rows] + items
    for row in rows:
        if row.chapter != chapter:
            continue
        if items and row.item not in items:
            findings.append(f"第{chapter}章: 台帳の項目「{row.item}」が「項目の定義」にありません")
        if row.value in _UNCONFIRMED or not row.item:
            continue
        holders = [line for line in lines if row.item in line]
        if not holders:
            continue
        if not any(_value_in(_value_segment(line, row.item, names), row.value) for line in holders):
            shown = holders[0].strip()
            findings.append(
                f"第{chapter}章: 章末ブロックの「{shown}」が台帳の値（{row.item} = {row.value}）と合いません"
            )
    return findings


# ── 移動の記録 ─────────────────────────────


def _moves_dir(work: Path) -> Path:
    from work_paths import new_only_location

    return new_only_location(work, "status_moves")


def move_record_path(work: Path, chapter: int) -> Path:
    return _moves_dir(work) / f"ch{chapter:02d}.json"


def load_move_record(work: Path, chapter: int) -> dict[str, object] | None:
    path = move_record_path(work, chapter)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _save_move_record(work: Path, record: dict[str, object]) -> None:
    path = move_record_path(work, int(record["chapter"]))  # type: ignore[arg-type]
    path.parent.mkdir(parents=True, exist_ok=True)
    record["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


# ── check ─────────────────────────────


def check_work(work: Path, *, completed_chapter: int | None = None) -> dict[str, object]:
    config = cs.load_chapter_status(work / "config.md")
    errors: list[str] = []
    warnings: list[str] = []
    infos: list[str] = []
    chapters = chapter_files(work)
    display = _status_display_text(work)
    rows = ledger_rows(display) if display is not None else []
    items = defined_items(display) if display is not None else []
    for chapter, files in sorted(chapters.items()):
        holders: list[tuple[Path, cs.BlockSpan]] = []
        for item in files:
            result = cs.scan(item.path.read_text(encoding="utf-8"))
            errors.extend(f"{item.path.name}: {error}" for error in result.errors)
            if len(result.blocks) > 1:
                errors.append(f"{item.path.name}: 一つのファイルにブロックが {len(result.blocks)} 個あります")
            holders.extend((item.path, block) for block in result.blocks)
        if len(holders) == 1:
            warnings.extend(compare_block_with_ledger(chapter, holders[0][1].content, rows, items))
        if len(holders) > 1:
            record = load_move_record(work, chapter)
            hashes = {block_hash(block.content) for _, block in holders}
            if record and record.get("stage") != "done" and hashes == {record.get("block_hash")}:
                infos.append(f"第{chapter}章: ブロックの移動中（記録 {move_record_path(work, chapter).name}）。move で続ける")
            else:
                names = "、".join(path.name for path, _ in holders)
                errors.append(f"第{chapter}章: ブロックが二つ以上あります（{names}）")
        elif holders and holders[0][0] != files[-1].path:
            warnings.append(
                f"第{chapter}章: ブロックが最後のファイル（{files[-1].path.name}）ではなく "
                f"{holders[0][0].name} にあります。作者に確かめてから move で移す"
            )
    if completed_chapter is not None:
        if completed_chapter not in chapters:
            errors.append(f"第{completed_chapter}章の本文ファイルがありません")
        elif config.mode is cs.ChapterStatusMode.TEXT:
            if not any(_blocks_in(item.path) for item in chapters[completed_chapter]):
                errors.append(
                    f"第{completed_chapter}章: CHAPTER_STATUS=TEXT ですが章末ブロックがありません"
                    f"（{chapters[completed_chapter][-1].path.name} の末尾に置く）"
                )
            if not _ledger_has_chapter(work, completed_chapter):
                warnings.append(f"第{completed_chapter}章: status_display.md の台帳にこの章の行がありません")
    return {
        "mode": config.mode.value,
        "style": config.style,
        "completed_chapter": completed_chapter,
        "errors": errors,
        "warnings": warnings,
        "infos": infos,
        "ok": not errors,
    }


# ── write / move ─────────────────────────────


def _metron_on(work: Path) -> bool:
    from inspection_flags import InspectionFlag, load_inspection_flags

    return load_inspection_flags(work / "config.md").metron is InspectionFlag.ON


def backup_text(work: Path, path: Path) -> Path:
    """`_novel_text_backup/<元ファイル名>_vNNN.md` へ退避する（novel-refinement-output と同じ採番）。"""

    directory = work / BACKUP_DIR
    directory.mkdir(parents=True, exist_ok=True)
    pattern = re.compile(rf"^{re.escape(path.stem)}_v(\d{{3,}})\.md$")
    numbers = [int(m.group(1)) for p in directory.iterdir() if (m := pattern.match(p.name))]
    target = directory / f"{path.stem}_v{(max(numbers) + 1 if numbers else 1):03d}.md"
    shutil.copy2(path, target)
    return target


def _write_file(path: Path, text: str) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        stream.write(text)


def _set_block(work: Path, path: Path, content: str | None) -> Path:
    backup = backup_text(work, path)
    _write_file(path, cs.replace_block(path.read_text(encoding="utf-8"), content))
    return backup


def cmd_write(work: Path, chapter: int, content: str | None) -> dict[str, object]:
    if _metron_on(work):
        raise StatusDisplayError(
            "METRON ON の作品では書かない。writing_bridge の prepare --request-kind status_block の run で書く"
        )
    target = last_file(work, chapter)
    for item in chapter_files(work)[chapter]:
        if item.path != target and _blocks_in(item.path):
            raise StatusDisplayError(
                f"第{chapter}章のブロックが {item.path.name} にあります。先に move で最後のファイルへ移す"
            )
    backup = _set_block(work, target, content)
    return {"file": target.name, "backup": backup.relative_to(work).as_posix(), "removed": content is None}


def cmd_move(work: Path, chapter: int) -> tuple[int, list[str]]:
    """記録の段階から一歩ずつ進める。戻り値は（終了コード, 表示する行）。"""

    messages: list[str] = []
    metron = _metron_on(work)
    record = load_move_record(work, chapter)
    target = last_file(work, chapter)
    if record is None or record.get("stage") == "done":
        sources = [
            item.path for item in chapter_files(work)[chapter]
            if item.path != target and _blocks_in(item.path)
        ]
        if not sources:
            return EXIT_OK, [f"第{chapter}章: 移すブロックはありません（最後のファイルは {target.name}）"]
        if len(sources) > 1:
            raise StatusDisplayError(f"第{chapter}章: 移動元が二つ以上あります。手で片付けず作者へ報告する")
        if _blocks_in(target):
            raise StatusDisplayError(f"第{chapter}章: 移動先 {target.name} に別のブロックがあります（記録なし）")
        block = _blocks_in(sources[0])[0]
        record = {
            "chapter": chapter,
            "source": sources[0].name,
            "target": target.name,
            "block_hash": block_hash(block.content),
            "content": block.content,
            "stage": "recorded",
        }
        _save_move_record(work, record)
        messages.append(f"記録しました: {move_record_path(work, chapter).relative_to(work).as_posix()}")
    source_path = work / "_novel_text" / str(record["source"])
    target_path = work / "_novel_text" / str(record["target"])
    wanted = str(record["block_hash"])

    def has_block(path: Path) -> bool:
        return any(block_hash(b.content) == wanted for b in _blocks_in(path))

    def require_only_recorded() -> None:
        # 書く前・段階を進める前に、両方のファイルに記録と違うブロックが無いことを確かめる。
        # 中断のあいだに移動先へ別のブロックが入った（上書きしてしまう）、移動元のブロックが
        # 書き換わった（両方に残ったまま完了になる）のどちらも、書かずに止める。
        for role, path in (("移動先", target_path), ("移動元", source_path)):
            if not path.exists():
                continue
            blocks = _blocks_in(path)
            if len(blocks) > 1 or any(block_hash(b.content) != wanted for b in blocks):
                raise StatusDisplayError(
                    f"第{chapter}章: {role} {path.name} に記録（{move_record_path(work, chapter).name}）と"
                    f"違うブロックがあります（段階 {record['stage']}）。書き込まずに止めます。"
                    "手で片付けず作者へ報告する"
                )

    require_only_recorded()
    if record["stage"] == "recorded":
        if not has_block(target_path):
            if metron:
                messages.append(
                    f"移動先 {target_path.name} へ status_block の run でブロックを書いてから、もう一度 move を実行する"
                )
                return EXIT_WAITING, messages
            backup = _set_block(work, target_path, str(record["content"]))
            messages.append(f"移動先に書きました: {target_path.name}（旧版 {backup.name}）")
        record["stage"] = "written"
        _save_move_record(work, record)
    def require_target() -> None:
        # 移動元から外す前・完了にする前に、移動先に記録どおりのブロックがあることを確かめ直す。
        # 中断のあいだに移動先のブロックが外れていたら、唯一残る移動元のブロックを消さない。
        if not target_path.exists() or not has_block(target_path):
            raise StatusDisplayError(
                f"第{chapter}章: 移動先 {target_path.name} に記録どおりのブロックがありません"
                f"（段階 {record['stage']}）。移動元からは外しません。手で片付けず作者へ報告する"
            )

    if record["stage"] == "written":
        require_only_recorded()
        require_target()
        if source_path.exists() and has_block(source_path):
            if metron:
                messages.append(
                    f"移動元 {source_path.name} から status_block の run でブロックを外してから、もう一度 move を実行する"
                )
                return EXIT_WAITING, messages
            backup = _set_block(work, source_path, None)
            messages.append(f"移動元から外しました: {source_path.name}（旧版 {backup.name}）")
        record["stage"] = "removed"
        _save_move_record(work, record)
    if record["stage"] == "removed":
        require_only_recorded()
        require_target()
        # 外したあとの中断のあいだに、移動元へ同じブロックが戻されていれば（旧版から戻したなど）
        # 二つ残ったまま完了にしない。戻した意図は分からないので、外し直さずに止める。
        if source_path.exists() and _blocks_in(source_path):
            raise StatusDisplayError(
                f"第{chapter}章: 移動元 {source_path.name} にブロックが残っています（段階 removed）。"
                "完了にせず止めます。手で片付けず作者へ報告する"
            )
        record["stage"] = "done"
        _save_move_record(work, record)
        messages.append(f"第{chapter}章: 移動が完了しました（{record['source']} → {record['target']}）")
    return EXIT_OK, messages


# ── CLI ─────────────────────────────


def main(argv: list[str] | None = None) -> int:
    from console_io import configure_stdio_utf8

    configure_stdio_utf8()
    parser = argparse.ArgumentParser(description="作品の章末ステータス（CHAPTER_STATUS）を扱う")
    sub = parser.add_subparsers(dest="command", required=True)
    p_init = sub.add_parser("init", help="作品の status_display.md を葉から作る（上書きしない）")
    p_init.add_argument("work", type=Path)
    p_init.add_argument("--style", required=True, choices=cs.STYLES)
    p_init.add_argument("--notice", help="本文内の通知の演出の例の ID（葉 §4）")
    p_check = sub.add_parser("check", help="章末ブロックを検査する")
    p_check.add_argument("work", type=Path)
    p_check.add_argument("--completed-chapter", type=int, help="完了を確かめた章。この章だけ欠落を判定する")
    p_check.add_argument("--json", action="store_true")
    p_write = sub.add_parser("write", help="METRON OFF の作品で章末ブロックを書く・外す")
    p_write.add_argument("work", type=Path)
    p_write.add_argument("--chapter", type=int, required=True)
    group = p_write.add_mutually_exclusive_group(required=True)
    group.add_argument("--content-file", type=Path, help="ブロックの中身（印は付けない）")
    group.add_argument("--remove", action="store_true")
    p_move = sub.add_parser("move", help="分割章でブロックを最後のファイルへ移す（再開できる）")
    p_move.add_argument("work", type=Path)
    p_move.add_argument("--chapter", type=int, required=True)
    args = parser.parse_args(argv)
    work = args.work.resolve()
    try:
        if args.command == "init":
            print(f"作りました: {cmd_init(work, args.style, args.notice)}")
            return EXIT_OK
        if args.command == "check":
            result = check_work(work, completed_chapter=args.completed_chapter)
            if args.json:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                style = f"（型: {result['style']}）" if result["style"] else ""
                print(f"章末ステータス: {result['mode']}{style}")
                for key, mark in (("errors", "x"), ("warnings", "!"), ("infos", "i")):
                    for line in result[key]:  # type: ignore[union-attr]
                        print(f"  {mark} {line}")
                print("結果: OK" if result["ok"] else "結果: NG")
            return EXIT_OK if result["ok"] else EXIT_FINDINGS
        if args.command == "write":
            content = None if args.remove else args.content_file.read_text(encoding="utf-8")
            result = cmd_write(work, args.chapter, content)
            action = "外しました" if result["removed"] else "書きました"
            print(f"{action}: {result['file']}（旧版 {result['backup']}）")
            return EXIT_OK
        if args.command == "move":
            code, messages = cmd_move(work, args.chapter)
            for line in messages:
                print(line)
            return code
    except (StatusDisplayError, cs.ChapterStatusConfigError, ValueError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_USAGE
    return EXIT_USAGE


if __name__ == "__main__":
    raise SystemExit(main())
