"""章末ステータスの表示（CHAPTER_STATUS）の共通処理。

正本は `.rulesync/rules/workflow-specification.md`「章末ステータスの表示（CHAPTER_STATUS）」。
ここには、config.md の行の読取り、本文の章末ブロック・通知の行の検出と除外、
作品の `status_display.md` の「本文内の通知」節の読取りを一か所に置く。
字数・句読点・lint・書き出し・組版・writing_bridge はこのモジュールを使い、印の形を
自分で持たない。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
import re

from inspection_flags import _basic_info_table_rows, _split_table_row, _is_separator_row


class ChapterStatusConfigError(ValueError):
    """config.md の CHAPTER_STATUS 行が読み取れない。"""


class ChapterStatusMode(str, Enum):
    OFF = "OFF"
    SYNOPSIS = "SYNOPSIS"
    TEXT = "TEXT"


MODE_KEY = "CHAPTER_STATUS"
STYLE_KEY = "CHAPTER_STATUS_STYLE"
STYLES = ("notice_log", "status_window", "diff", "experience_log", "card")
DEFAULT_MODE = ChapterStatusMode.SYNOPSIS

BLOCK_BEGIN = "<!-- status:begin -->"
BLOCK_END = "<!-- status:end -->"
LINE_MARK = "<!-- status:line -->"

_BEGIN_RE = re.compile(r"^[ \t]*<!--\s*status:begin\s*-->[ \t]*$")
_END_RE = re.compile(r"^[ \t]*<!--\s*status:end\s*-->[ \t]*$")
_LINE_RE = re.compile(r"^[ \t]*<!--\s*status:line\s*-->[ \t]?")
_MARKER_ONLY_RE = re.compile(r"^[ \t]*<!--\s*status:(?:begin|end)\s*-->[ \t]*$")


@dataclass(frozen=True)
class ChapterStatusConfig:
    mode: ChapterStatusMode = DEFAULT_MODE
    style: str | None = None
    explicit: frozenset[str] = field(default_factory=frozenset)
    source: str = "implicit"

    def as_dict(self) -> dict[str, object]:
        return {
            MODE_KEY: self.mode.value,
            STYLE_KEY: self.style,
            "explicit": sorted(self.explicit),
            "source": self.source,
        }


def parse_chapter_status(text: str, *, source: str = "config.md") -> ChapterStatusConfig:
    """`## 基本情報` の表から CHAPTER_STATUS / CHAPTER_STATUS_STYLE を読む。行なしは SYNOPSIS。"""

    values: dict[str, str] = {}
    for cells in _basic_info_table_rows(text.splitlines()):
        if not cells:
            continue
        key = cells[0]
        normalized = key.upper()
        if normalized not in (MODE_KEY, STYLE_KEY):
            continue
        if key != normalized:
            raise ChapterStatusConfigError(f"key must be uppercase {normalized}: {key!r}")
        if len(cells) != 2:
            raise ChapterStatusConfigError(f"row must have exactly 2 columns: {key}")
        if key in values:
            raise ChapterStatusConfigError(f"duplicate row: {key}")
        values[key] = cells[1].strip()

    raw_mode = values.get(MODE_KEY)
    if raw_mode is None:
        mode = DEFAULT_MODE
    else:
        try:
            mode = ChapterStatusMode(raw_mode)
        except ValueError as error:
            raise ChapterStatusConfigError(
                f"unknown value for {MODE_KEY}: {raw_mode!r} (expected OFF, SYNOPSIS or TEXT)"
            ) from error
    style = values.get(STYLE_KEY) or None
    if style is not None and style not in STYLES:
        raise ChapterStatusConfigError(
            f"unknown value for {STYLE_KEY}: {style!r} (expected one of {', '.join(STYLES)})"
        )
    if mode is ChapterStatusMode.TEXT and style is None:
        raise ChapterStatusConfigError(f"{MODE_KEY} TEXT requires {STYLE_KEY}")
    if mode is not ChapterStatusMode.TEXT and style is not None:
        raise ChapterStatusConfigError(f"{STYLE_KEY} is only allowed when {MODE_KEY} is TEXT")
    return ChapterStatusConfig(
        mode=mode,
        style=style,
        explicit=frozenset(values),
        source=source if values else "implicit:no-row",
    )


def load_chapter_status(config_path: str | Path) -> ChapterStatusConfig:
    path = Path(config_path)
    if not path.exists():
        return ChapterStatusConfig(source="implicit:missing-config")
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as error:
        raise ChapterStatusConfigError(f"config.md could not be read: {path}: {error}") from error
    return parse_chapter_status(text, source=str(path))


# ── 本文の章末ブロックと通知の行 ─────────────────────────────


@dataclass(frozen=True)
class BlockSpan:
    """章末ブロックの位置。start / end は文字の位置（印の行と末尾の改行を含む）。"""

    start: int
    end: int
    content: str
    start_line: int  # 1 始まり


@dataclass(frozen=True)
class BlockScan:
    blocks: tuple[BlockSpan, ...]
    errors: tuple[str, ...]
    line_marks: tuple[int, ...]  # status:line の行番号（1 始まり）


def scan(text: str) -> BlockScan:
    """章末ブロック（begin〜end）と通知の行を探す。閉じていない・入れ子の印は errors に入れる。"""

    blocks: list[BlockSpan] = []
    errors: list[str] = []
    line_marks: list[int] = []
    offset = 0
    open_start: int | None = None
    open_line = 0
    content: list[str] = []
    for number, line in enumerate(text.splitlines(keepends=True), start=1):
        bare = line.rstrip("\r\n")
        if _BEGIN_RE.match(bare):
            if open_start is not None:
                errors.append(f"line {number}: status:begin inside another block (line {open_line})")
            else:
                open_start, open_line, content = offset, number, []
        elif _END_RE.match(bare):
            if open_start is None:
                errors.append(f"line {number}: status:end without status:begin")
            else:
                blocks.append(
                    BlockSpan(open_start, offset + len(line), "".join(content), open_line)
                )
                open_start = None
        elif open_start is not None:
            content.append(line)
        elif _LINE_RE.match(bare):
            line_marks.append(number)
        offset += len(line)
    if open_start is not None:
        errors.append(f"line {open_line}: status:begin is not closed")
    return BlockScan(tuple(blocks), tuple(errors), tuple(line_marks))


def body_end(text: str) -> int:
    """本文として編集してよい範囲の終わり。最初の章末ブロックの始まり（なければ末尾）。

    ブロックの直前の空行も本文の外として扱い、追記がブロックとの間の空行の前に入るようにする。
    """

    result = scan(text)
    if not result.blocks:
        return len(text)
    start = result.blocks[0].start
    while start >= 2 and text[start - 1] == "\n" and text[start - 2] == "\n":
        start -= 1
    return start


def split_body_and_tail(text: str) -> tuple[str, str]:
    """本文（編集してよい範囲）と、章末ブロックを含む末尾に分ける。"""

    end = body_end(text)
    return text[:end], text[end:]


def strip_for_measure(text: str) -> str:
    """字数・句読点の測定用に、章末ブロックと通知の行を取り除く。"""

    result = scan(text)
    spans: list[tuple[int, int]] = []
    for block in result.blocks:
        start = block.start
        # 本文とブロックの間の空行も測らない（保存の形の違いで字数が揺れないように）。
        while start >= 2 and text[start - 1] == "\n" and text[start - 2] == "\n":
            start -= 1
        spans.append((start, block.end))
    pieces: list[str] = []
    cursor = 0
    for start, end in spans:
        pieces.append(text[cursor:start])
        cursor = end
    pieces.append(text[cursor:])
    kept = "".join(pieces)
    if not result.line_marks:
        return kept
    return "".join(
        line for line in kept.splitlines(keepends=True) if not _LINE_RE.match(line.rstrip("\r\n"))
    )


def unmark_for_output(text: str) -> str:
    """外部投稿用に、印のコメントだけを外して中身を残す。"""

    out: list[str] = []
    for line in text.splitlines(keepends=True):
        bare = line.rstrip("\r\n")
        if _MARKER_ONLY_RE.match(bare):
            continue
        match = _LINE_RE.match(bare)
        if match:
            line = line[match.end():]
        out.append(line)
    return "".join(out)


def status_line_numbers(text: str) -> set[int]:
    """lint が本文として検査しない行（ブロックの印・中身、通知の行）の番号（1 始まり）。"""

    result = scan(text)
    skipped: set[int] = set(result.line_marks)
    for block in result.blocks:
        count = block.content.count("\n") + 2
        skipped.update(range(block.start_line, block.start_line + count))
    return skipped


def replace_block(text: str, new_content: str | None) -> str:
    """章末ブロックを置き換える（None は外す）。ブロックがなければ末尾に足す。"""

    result = scan(text)
    if result.errors:
        raise ValueError("; ".join(result.errors))
    if len(result.blocks) > 1:
        raise ValueError("more than one status block in the file")
    if result.blocks and text[result.blocks[0].end:].strip():
        raise ValueError("text after the status block")
    body = split_body_and_tail(text)[0].rstrip("\n")
    if new_content is None:
        return body + "\n" if body else ""
    return body + "\n\n" + render_block(new_content)


def render_block(content: str) -> str:
    inner = content.strip("\n")
    return f"{BLOCK_BEGIN}\n{inner}\n{BLOCK_END}\n"


# ── 旧形式の章末ブロック（印のない既存稿） ───────────────────────

_RULE_RE = re.compile(r"^-{3,}\s*$")
_BOLD_HEADING_RE = re.compile(r"^\*\*[^*]+\*\*\s*$")
_LIST_RE = re.compile(r"^\s*-\s+\S")
_STATUS_HEADING_RE = re.compile(r"^#{1,6}\s.*ステータス")


def find_legacy_blocks(text: str) -> list[int]:
    """印のない旧形式の章末ブロックの開始行（1 始まり）を返す。

    形は二つ。`---` のあとの太字見出しと箇条書き（例「**ボディーの変化・経験ログ**」）、
    「ステータス」を含む見出し（例「#### ■…（最終ステータス）」）。印の中は対象外。
    """

    skipped = status_line_numbers(text)
    lines = text.splitlines()
    found: list[int] = []
    for index, line in enumerate(lines):
        number = index + 1
        if number in skipped:
            continue
        if _STATUS_HEADING_RE.match(line):
            found.append(number)
            continue
        if not _RULE_RE.match(line):
            continue
        rest = [(i, l) for i, l in enumerate(lines[index + 1 :], start=index + 1) if l.strip()]
        if len(rest) >= 2 and _BOLD_HEADING_RE.match(rest[0][1]) and _LIST_RE.match(rest[1][1]):
            found.append(rest[0][0] + 1)
    return found


# ── 作品の status_display.md ─────────────────────────────

STATUS_DISPLAY_NAME = "status_display.md"
NOTICE_SECTION = "本文内の通知"
NOTICE_REQUIRED = ("主体", "出方", "届く範囲", "きっかけ", "やりとり", "置き方", "書式", "頻度の方針")


@dataclass(frozen=True)
class NoticeDefinition:
    enabled: bool
    items: dict[str, str]
    missing: tuple[str, ...]
    brackets: tuple[tuple[str, str], ...]

    @property
    def usable(self) -> bool:
        """使うと決めてあり、必須の項目がすべて埋まっている。"""

        return self.enabled and not self.missing


NO_NOTICE = NoticeDefinition(False, {}, (), ())


def _section_lines(text: str, title: str) -> list[str]:
    lines = text.splitlines()
    heading = re.compile(rf"^##\s+{re.escape(title)}\s*$")
    start = next((i for i, l in enumerate(lines) if heading.match(l)), None)
    if start is None:
        return []
    end = next(
        (i for i in range(start + 1, len(lines)) if re.match(r"^#{1,2}\s", lines[i])), len(lines)
    )
    return lines[start + 1 : end]


def _table(lines: list[str]) -> list[list[str]]:
    rows: list[list[str]] = []
    started = False
    for line in lines:
        cells = _split_table_row(line)
        if cells is None:
            if started:
                break
            continue
        if not started:
            started = True
            continue  # 見出し行
        if _is_separator_row(cells):
            continue
        rows.append(cells)
    return rows


def parse_brackets(value: str) -> tuple[tuple[str, str], ...]:
    """「【】 《》」のような値を括弧の組にする。2 文字の語だけを組とみなす。"""

    pairs: list[tuple[str, str]] = []
    for token in re.split(r"[\s、,／/]+", value.strip()):
        token = token.strip("`")
        if len(token) == 2 and token[0] != token[1]:
            pairs.append((token[0], token[1]))
    return tuple(pairs)


def parse_notice_definition(text: str) -> NoticeDefinition:
    rows = _table(_section_lines(text, NOTICE_SECTION))
    items = {row[0].strip(): (row[1].strip() if len(row) > 1 else "") for row in rows if row}
    enabled = items.get("使うか", "").startswith("使う")
    missing = tuple(key for key in NOTICE_REQUIRED if not items.get(key))
    brackets = parse_brackets(items.get("括弧", ""))
    return NoticeDefinition(enabled, items, missing if enabled else (), brackets)


def work_dir_for(text_path: Path) -> Path | None:
    """`novels/<作品>/_novel_text/x.md` から作品フォルダを返す。"""

    for parent in text_path.resolve().parents:
        if parent.name in ("_novel_text", "_novel_text_re"):
            return parent.parent
    return None


def load_notice_definition(work_dir: Path | None) -> NoticeDefinition:
    if work_dir is None:
        return NO_NOTICE
    path = work_dir / STATUS_DISPLAY_NAME
    if not path.is_file():
        return NO_NOTICE
    try:
        return parse_notice_definition(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError):
        return NO_NOTICE


def bracketed_spans(line: str, brackets: tuple[tuple[str, str], ...]) -> list[tuple[int, int]]:
    """書式で決めた括弧で囲まれた範囲（括弧を含む）。"""

    spans: list[tuple[int, int]] = []
    for open_, close in brackets:
        start = 0
        while True:
            i = line.find(open_, start)
            if i < 0:
                break
            j = line.find(close, i + 1)
            if j < 0:
                break
            spans.append((i, j + 1))
            start = j + 1
    return spans
