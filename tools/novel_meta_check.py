"""作品の `_meta.md` の形を判定し、雛形（`_how_to.example/meta.md`）の並びへ移す。

計画: _workingspace/plans/20261024_work-folder-layout.md §3.2・§3.5・M7

    uv run python tools/novel_meta_check.py check novels/<作品> [--json]
    uv run python tools/novel_meta_check.py migrate novels/<作品> --dry-run
    uv run python tools/novel_meta_check.py migrate novels/<作品>
    uv run python tools/novel_meta_check.py ensure-section novels/<作品> evaluation-history

- 形の判定: `new`（雛形の4部と必要な節がそろう）/ `partial`（一部だけ）/ `legacy`（4部が無い）。
- 移行: 本文の段落・表・コードブロックは、節（`##` の見出しから次の見出しまで）ごとにひとかたまりのまま
  中身を変えずに雛形の位置へ並べ替える。対応表で見出しだけを雛形の見出しに変え、変えた見出しを一覧にする。
  欠けた節は雛形の見出しで足す（「章別文字数」の表は雛形の決まりで自動では足さない）。対応の決まらない節は
  末尾の「# 移行前の節（未分類）」へそのまま置く。ただし機械が読む記録（次回のタスク・章別文字数・評価履歴・
  出来事同期・goal の自動生成ブロック）を含む節の行き先が決まらないときは、移行を止める。
- 移行の前後で、機械が読む記録が同じに取れることと、2回目の実行で差分が出ないことを確かめてから書く。
- 書く前に旧版を `_novel_text_backup/_meta_vNNN.md` へ元のバイトのまま退避する。新しい版は元の改行コードで書く。
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ── 雛形の並び ───────────────────────────────────────────────────────────

PARTS: list[tuple[str, str, tuple[str, ...]]] = [
    # (部の鍵, 雛形の見出し, 見分ける語)
    ("I", "# I. 内部メタ情報（Internal Meta: 執筆管理・AI指示用）", ("内部メタ情報", "Internal Meta")),
    ("II", "# II. 外部メタ情報（External Meta: カクヨム等投稿サイト・投稿用）", ("外部メタ情報", "外部公開情報", "External Meta")),
    ("III", "# III. 画像・漫画生成設定（Image / Manga Generation）", ("画像・漫画生成設定",)),
    ("IV", "# IV. 評価・足切り履歴（Evaluation Gate Status）", ("評価・足切り履歴", "Evaluation Gate")),
    ("V", "# V. メタ情報生成・更新プロンプト（AIへの指示）", ("メタ情報生成・更新プロンプト",)),
]
REQUIRED_PARTS = ("I", "II", "III", "IV")
UNCLASSIFIED_HEADING = "# 移行前の節（未分類）"


@dataclass(frozen=True)
class Slot:
    key: str
    part: str
    heading: str
    keywords: tuple[str, ...]
    required: bool
    filler: str = "（移行で追加。未記入）"


# 照合の順に並べる（より具体的な語を先に）。
SLOTS: list[Slot] = [
    Slot(
        "I.1",
        "I",
        "## 1. 執筆フェーズ・ステータス",
        ("執筆フェーズ", "執筆ステータス", "進捗", "内部メタ", "内部管理", "現在の章", "次回タスク", "次回のタスク",
         "今シーン", "本文同期", "本文ファイル対応", "対話セッション管理", "進行管理", "更新履歴"),
        True,
    ),
    Slot(
        "I.1.5",
        "I",
        "## 1.5 goal の状況",
        ("goal の状況", "goalの状況"),
        True,
        "`tools/goal_status.py <作品> --write-meta` が、下の枠の中だけを書き換える。手書きのメモは枠の外へ書く。\n\n"
        "<!-- goal-status:begin -->\n（未生成）\n<!-- goal-status:end -->",
    ),
    Slot("I.2", "I", "## 2. 執筆用コンテキスト・アンカー", ("執筆用コンテキスト", "伏線", "AI引き継ぎ"), True),
    Slot("I.3", "I", "## 3. 執筆制約・メタ指示", ("執筆制約",), True),
    Slot("I.3.5", "I", "## 3.5 Plan Mode Gate B 記録", ("Gate B",), True),
    Slot("I.3.6", "I", "## 3.6 検査レイヤの予定（METRON / CHRONOS）", ("検査レイヤの予定",), True),
    Slot(
        "II.1",
        "II",
        "## 1. カクヨム基本項目",
        ("カクヨム基本項目", "外部メタ", "外部投稿", "外部公開", "投稿基本データ", "キャッチコピー", "紹介文",
         "タグ・キーワード", "あらすじ", "書誌"),
        True,
    ),
    Slot("II.2", "II", "## 2. ターゲット・訴求", ("ターゲット・訴求",), True),
    Slot("III.0", "III", "## 0. 機械可読メタ（`_meta.yaml`・定量）", ("機械可読メタ",), False),
    Slot("III.1", "III", "## 1. 色モード", ("色モード", "カラーモード"), False),
    Slot("III.2.1", "III", "## 2.1 漫画写植（任意）", ("漫画写植",), False),
    Slot("III.2", "III", "## 2. 生成 provider 既定（任意）", ("生成 provider", "provider 既定"), False),
    Slot("III.3.1", "III", "## 3.1 表紙（別枠・章挿絵と混在しない）", ("3.1 表紙", "表紙（別枠"), False),
    Slot("III.3.2", "III", "## 3.2 章別挿絵割当表（TPO 正本・計画 MD / YAML より先に更新）", ("章別挿絵割当表",), False),
    Slot("III.3", "III", "## 3. 挿絵・表紙（任意・作品ごと）", ("挿絵・表紙",), False),
    Slot("III.4", "III", "## 4. 漫画 variant 対応（TPO 正本・YAML より先に更新）", ("漫画 variant",), False),
    Slot(
        "III.6",
        "III",
        "## 6. キャラタグ（Tag Mode）方針（任意）",
        ("キャラタグ", "キャラクタータグ", "バリアント方針", "種族方針", "Tag Mode"),
        False,
    ),
    Slot("III.5", "III", "## 5. 漫画タグ層（区間・常時上乗せ・YAML より先に更新）", ("漫画タグ層",), False),
    Slot("III.7", "III", "## 7. 出版パッケージ進捗（完成目安）", ("出版パッケージ進捗",), False),
    Slot("III.x", "III", "## 移行前の画像・漫画生成設定", ("画像・漫画生成設定",), False),
    Slot("IV.1", "IV", "## 1. 足切りステータス", ("足切りステータス",), True),
    Slot("IV.2", "IV", "## 2. 最新 First Reader（足切り）", ("最新 First Reader",), True),
    Slot("IV.3", "IV", "## 3. 最新 Interest Check", ("最新 Interest Check",), True),
    Slot("IV.3b", "IV", "## 最新 Editor Score", ("Editor Score",), False),
    Slot(
        "IV.4",
        "IV",
        "## 4. 評価履歴（改訂前後の推移）",
        ("評価履歴", "評価・足切り履歴"),
        True,
        "| 日時 | ゲート | 総合点 | 判定 | ファイル |\n|------|--------|--------|------|---------|",
    ),
]
SLOT_BY_KEY = {slot.key: slot for slot in SLOTS}
# 雛形の中での並び（照合の順とは別）。
TEMPLATE_ORDER = [
    "I.1", "I.1.5", "I.2", "I.3", "I.3.5", "I.3.6",
    "II.1", "II.2",
    "III.0", "III.1", "III.2", "III.2.1", "III.3", "III.3.1", "III.3.2", "III.4", "III.6", "III.5", "III.7", "III.x",
    "IV.1", "IV.2", "IV.3", "IV.3b", "IV.4",
]

# ensure-section で足せる節（記録を書く工程が使う名前 → 節）。
ENSURE_NAMES = {
    "phase-status": "I.1",
    "goal-status": "I.1.5",
    "context": "I.2",
    "evaluation-history": "IV.4",
    "inspection-plan": "I.3.6",
    "gate-b": "I.3.5",
}

_RE_FENCE = re.compile(r"^\s*(```|~~~)")
_RE_HEADING = re.compile(r"^(#{1,2})\s+(.*\S)\s*$")
GOAL_BEGIN = "<!-- goal-status:begin -->"
GOAL_END = "<!-- goal-status:end -->"


class MetaError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


# ── 分解 ─────────────────────────────────────────────────────────────────


@dataclass
class Block:
    """見出し（`#` か `##`）1行と、次の見出しまでの本文。level 0 は最初の見出しより前。"""

    level: int
    heading: str
    body: list[str] = field(default_factory=list)


def split_blocks(text: str) -> list[Block]:
    """`#`・`##` の見出しで分ける。コードブロックの中の `#` は見出しにしない。`###` 以下は本文に含める。"""
    blocks: list[Block] = [Block(0, "")]
    in_fence = False
    for line in text.split("\n"):
        if _RE_FENCE.match(line):
            in_fence = not in_fence
            blocks[-1].body.append(line)
            continue
        match = None if in_fence else _RE_HEADING.match(line)
        if match:
            blocks.append(Block(len(match.group(1)), line))
        else:
            blocks[-1].body.append(line)
    return blocks


def _part_of(heading: str) -> str | None:
    for key, _, words in PARTS:
        if any(word in heading for word in words):
            return key
    if heading.strip() == UNCLASSIFIED_HEADING:
        return "UNCLASSIFIED"
    return None


def _slot_of(heading: str) -> Slot | None:
    for slot in SLOTS:
        if any(word in heading for word in slot.keywords):
            return slot
    return None


# ── 機械が読む記録 ───────────────────────────────────────────────────────


def machine_records(text: str) -> dict[str, list[str]]:
    """機械やスキルが読み書きする記録。移行の前後でこれが同じに取れることを確かめる。"""
    lines = text.split("\n")
    records: dict[str, list[str]] = {
        "next_task": [line.strip() for line in lines if re.search(r"\*\*次回のタスク\*\*\s*[:：]", line)],
        "story_sync": [line.strip() for line in lines if "出来事同期" in line and line.lstrip().startswith("-")],
        "char_table": [],
        "evaluation_rows": [],
        "goal_block": [],
    }
    in_goal = False
    for line in lines:
        if line.strip() == GOAL_BEGIN:
            in_goal = True
        if in_goal:
            records["goal_block"].append(line)
        if line.strip() == GOAL_END:
            in_goal = False
    # 章別文字数の表（見出しの直後の表）と、評価履歴の表（「日時」「ゲート」の見出し行を持つ表）
    for index, line in enumerate(lines):
        if re.match(r"^#{1,6}\s*章別文字数\s*$", line):
            for row in lines[index + 1 :]:
                if row.startswith("#"):
                    break
                if row.lstrip().startswith("|"):
                    records["char_table"].append(row.strip())
        if line.lstrip().startswith("|") and "日時" in line and "ゲート" in line:
            for row in lines[index:]:
                if not row.lstrip().startswith("|"):
                    break
                records["evaluation_rows"].append(row.strip())
    return records


def _has_machine_record(lines: list[str]) -> bool:
    found = machine_records("\n".join(lines))
    return any(found.values())


# ── 判定 ─────────────────────────────────────────────────────────────────


@dataclass
class CheckResult:
    form: str
    parts: list[str]
    present: list[str]
    missing: list[str]
    duplicates: list[str]
    records: dict[str, int]

    def as_dict(self) -> dict[str, Any]:
        return {
            "form": self.form,
            "parts": self.parts,
            "present_sections": self.present,
            "missing_sections": self.missing,
            "duplicate_sections": self.duplicates,
            "machine_records": self.records,
        }


def check_text(text: str) -> CheckResult:
    parts: list[str] = []
    present: list[str] = []
    duplicates: list[str] = []
    for block in split_blocks(text):
        if block.level == 1:
            part = _part_of(block.heading)
            if part and part not in parts:
                parts.append(part)
        elif block.level == 2:
            slot = _slot_of(block.heading)
            if slot:
                (duplicates if slot.key in present else present).append(slot.key)
    required = [slot.key for slot in SLOTS if slot.required]
    missing = [key for key in required if key not in present]
    has_parts = [part for part in REQUIRED_PARTS if part in parts]
    if len(has_parts) == len(REQUIRED_PARTS) and not missing:
        form = "new"
    elif has_parts:
        form = "partial"
    else:
        form = "legacy"
    records = {key: len(value) for key, value in machine_records(text).items()}
    return CheckResult(form, parts, present, missing, duplicates, records)


# ── 移行 ─────────────────────────────────────────────────────────────────


@dataclass
class MigrationPlan:
    text: str
    renamed: list[tuple[str, str]]
    added: list[str]
    unclassified: list[str]


def _is_layout(line: str) -> bool:
    """空行と、部の区切りの線（---）。移行では整え直すレイアウトの行として扱う。"""
    return not line.strip() or line.strip() == "---"


def _trim(lines: list[str]) -> list[str]:
    """末尾の空行と区切りの線を落とす（区切りは部の前に付け直す）。"""
    while lines and _is_layout(lines[-1]):
        lines = lines[:-1]
    return lines


def migrate_text(text: str) -> MigrationPlan:
    """雛形の並びへ組み直した全文を返す。書かない。止めるべきときは MetaError。"""
    blocks = split_blocks(text)
    preamble: list[str] = []
    part_intro: dict[str, list[str]] = {}
    sections: dict[str, Block] = {}
    extra: dict[str, list[Block]] = {}
    unclassified: list[Block] = []
    renamed: list[tuple[str, str]] = []
    current_part: str | None = None

    for block in blocks:
        if block.level == 0:
            preamble = block.body
            continue
        if block.level == 1:
            part = _part_of(block.heading)
            if part is None and not preamble and not part_intro and not sections:
                # 最初の見出しが部でない h1 なら、作品の題として冒頭に残す。
                preamble = [block.heading, *block.body]
                continue
            if part == "UNCLASSIFIED":
                # ツール自身が作った「移行前の節（未分類）」の下は、2回目でもそのまま未分類に置く。
                current_part = "UNCLASSIFIED"
                if any(not _is_layout(line) for line in block.body):
                    unclassified.append(Block(0, "", block.body))
                continue
            if part is None:
                # 部でない h1（題の重ね書きなど）は見出しと前書きを未分類に置き、その下の節は通常どおり振り分ける。
                current_part = None
                unclassified.append(Block(1, block.heading, block.body))
                continue
            current_part = part
            part_intro.setdefault(part, []).extend(block.body)
            template_heading = next(h for k, h, _ in PARTS if k == part)
            if block.heading.strip() != template_heading:
                renamed.append((block.heading.strip(), template_heading))
            continue
        # level 2
        slot = None if current_part == "UNCLASSIFIED" else _slot_of(block.heading)
        if slot is None:
            if _has_machine_record(block.body):
                raise MetaError(
                    "UNMAPPED_RECORD",
                    f"機械が読む記録を含む節の行き先が決まらない: {block.heading.strip()}（移行を止めた）",
                )
            unclassified.append(block)
            continue
        if slot.key in sections:
            # 同じ節に当たる2つ目以降は、1つ目のあとへ見出しを ### に下げてつなぐ（中身は変えない）。
            demoted = "#" + block.heading.strip()
            extra.setdefault(slot.key, []).append(Block(3, demoted, block.body))
            renamed.append((block.heading.strip(), demoted))
            continue
        sections[slot.key] = block
        if block.heading.strip() != slot.heading:
            renamed.append((block.heading.strip(), slot.heading))

    if _has_machine_record(preamble) and any(part_intro.values()) is False and not sections:
        raise MetaError("UNMAPPED_RECORD", "見出しの無い本文に機械が読む記録がある（移行を止めた）")

    out: list[str] = _trim(list(preamble))
    added: list[str] = []
    for part_key, part_heading, _ in PARTS:
        keys = [key for key in TEMPLATE_ORDER if SLOT_BY_KEY[key].part == part_key]
        part_sections = [key for key in keys if key in sections]
        missing_required = [key for key in keys if SLOT_BY_KEY[key].required and key not in sections]
        if part_key == "V" and part_key not in part_intro:
            continue
        if part_key not in part_intro:
            added.append(part_heading)
        out += ["", "---", "", part_heading] if out else [part_heading]
        intro = _trim(list(part_intro.get(part_key, [])))
        while intro and _is_layout(intro[0]):
            intro = intro[1:]
        if intro:
            out += intro
        for key in keys:
            slot = SLOT_BY_KEY[key]
            if key in sections:
                body = _trim(list(sections[key].body))
                out += ["", slot.heading, *body]
                for joined in extra.get(key, []):
                    out += ["", joined.heading, *_trim(list(joined.body))]
            elif key in missing_required:
                out += ["", slot.heading, slot.filler]
                added.append(slot.heading)
        _ = part_sections
    if unclassified:
        out += ["", "---", "", UNCLASSIFIED_HEADING]
        for block in unclassified:
            body = _trim(list(block.body))
            out += [""] + ([block.heading] if block.heading else []) + body
    result = "\n".join(_cleanup_separators(out)).rstrip("\n") + "\n"
    return MigrationPlan(result, renamed, added, [block.heading.strip() for block in unclassified])


def _cleanup_separators(lines: list[str]) -> list[str]:
    """部の区切り（---）が本文の末尾の --- と重ならないようにする。コードブロックの中は触らない。"""
    out: list[str] = []
    in_fence = False
    prev_fence: list[bool] = []
    for line in lines:
        if _RE_FENCE.match(line):
            in_fence = not in_fence
            out.append(line)
            prev_fence.append(True)
            continue
        if (
            not in_fence
            and line == "---"
            and len(out) >= 2
            and out[-1] == ""
            and out[-2] == "---"
            and not prev_fence[-1]
            and not prev_fence[-2]
        ):
            out.pop()
            prev_fence.pop()
            continue
        out.append(line)
        prev_fence.append(in_fence)
    return out


def _code_blocks(text: str) -> list[str]:
    """コードブロック（開きの行から閉じの行まで）を、ひとかたまりの文字列で取り出す。"""
    blocks: list[str] = []
    current: list[str] | None = None
    for line in text.split("\n"):
        if _RE_FENCE.match(line):
            if current is None:
                current = [line]
            else:
                current.append(line)
                blocks.append("\n".join(current))
                current = None
            continue
        if current is not None:
            current.append(line)
    if current is not None:
        blocks.append("\n".join(current))
    return blocks


def _content_lines(text: str) -> list[str]:
    """照合に使う本文の行。コードブロックの外の見出し・空行・区切りの線（---）は除き、
    コードブロックの中はすべての行を含める（区切りの整理をしないので、中身は同じでなければならない）。"""
    lines: list[str] = []
    in_fence = False
    for line in text.split("\n"):
        if _RE_FENCE.match(line):
            in_fence = not in_fence
            lines.append(line)
            continue
        if in_fence:
            lines.append(line)
        elif not _is_layout(line) and not _RE_HEADING.match(line):
            lines.append(line)
    return lines


def verify_migration(before: str, after: str, added: list[str] | None = None) -> None:
    """受け入れ条件: 機械が読む記録が同じ、本文の行が失われない、2回目で差分なし。

    足した節（added の見出し）の雛形の中身にある記録（評価履歴の表の見出し行、goal の枠）は差し引いて比べる。
    """
    from collections import Counter

    filler_text = "\n".join(
        f"{slot.heading}\n{slot.filler}" for slot in SLOTS if slot.heading in (added or [])
    )
    expected = machine_records(before)
    filler = machine_records(filler_text)
    actual = machine_records(after)
    for kind in expected:
        if Counter(actual[kind]) - Counter(filler[kind]) != Counter(expected[kind]) or (
            Counter(expected[kind]) - Counter(actual[kind])
        ):
            raise MetaError("RECORDS_CHANGED", f"移行の前後で機械が読む記録（{kind}）が一致しない（移行を止めた）")
    # コードブロックはひとかたまりで、中身がそのまま残ること
    if Counter(_code_blocks(after)) - Counter(_code_blocks(before)) or Counter(_code_blocks(before)) - Counter(
        _code_blocks(after)
    ):
        raise MetaError("CODE_BLOCK_CHANGED", "移行でコードブロックの中身が変わる（移行を止めた）")
    # 本文の行（コードブロックの外は見出し・空行・区切りを除く）が失われないこと
    after_counts = Counter(_content_lines(after))
    for line in _content_lines(before):
        if after_counts.get(line, 0) <= 0:
            raise MetaError("LINE_LOST", f"移行で本文の行が失われる: {line[:60]}（移行を止めた）")
        after_counts[line] -= 1
    again = migrate_text(after)
    if again.text != after:
        raise MetaError("NOT_IDEMPOTENT", "2回目の移行で差分が出る（移行を止めた）")


def _in_fence_line(text: str, target: str) -> bool:
    in_fence = False
    for line in text.split("\n"):
        if _RE_FENCE.match(line):
            in_fence = not in_fence
            continue
        if line == target:
            return in_fence
    return False


# ── 必要な節だけ足す ─────────────────────────────────────────────────────


def ensure_section_text(text: str, slot_key: str) -> str:
    """節が無ければ、雛形の位置に近いところへ足す。ほかの行は動かさない。あれば同じ全文を返す。"""
    slot = SLOT_BY_KEY[slot_key]
    blocks = split_blocks(text)
    keys_present: list[str | None] = []
    for b in blocks:
        found = _slot_of(b.heading) if b.level == 2 else None
        keys_present.append(found.key if found else None)
    if slot_key in keys_present:
        return text
    lines = text.split("\n")
    # 雛形で後ろに来る節のうち、いちばん前にある既存の節の直前に入れる。無ければ部の末尾、無ければ末尾。
    order = TEMPLATE_ORDER.index(slot_key)
    later = {key for key in TEMPLATE_ORDER[order + 1 :] if SLOT_BY_KEY[key].part == slot.part}
    insert_at: int | None = None
    line_index = 0
    for block, key in zip(blocks, keys_present):
        start = line_index
        line_index += (1 if block.level else 0) + len(block.body)
        if key in later and insert_at is None:
            insert_at = start
    new_lines = [slot.heading, slot.filler, ""]
    if insert_at is None:
        sep = [""] if lines and lines[-1].strip() else []
        body = lines[:-1] if lines and lines[-1] == "" else lines
        return "\n".join([*body, *sep, *new_lines]).rstrip("\n") + "\n"
    return "\n".join([*lines[:insert_at], *new_lines, *lines[insert_at:]])


# ── ファイル操作 ─────────────────────────────────────────────────────────


def _backup(work: Path, raw: bytes) -> Path:
    """旧版を元のバイトのまま退避する。"""
    backup_dir = work / "_novel_text_backup"
    backup_dir.mkdir(parents=True, exist_ok=True)
    numbers = [
        int(match.group(1))
        for path in backup_dir.glob("_meta_v*.md")
        if (match := re.fullmatch(r"_meta_v(\d+)\.md", path.name))
    ]
    path = backup_dir / f"_meta_v{(max(numbers) + 1 if numbers else 1):03d}.md"
    path.write_bytes(raw)
    return path


def _newline_of(raw: bytes) -> str:
    """元のファイルの改行コード。混在するときは多いほう。"""
    crlf = raw.count(b"\r\n")
    return "\r\n" if crlf and crlf * 2 >= raw.count(b"\n") else "\n"


def _write(path: Path, text: str, newline: str) -> None:
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8", newline=newline)
    os.replace(tmp, path)


class _StoryReflectionGuard:
    """`_meta.md` を書く間、ストーリー反映と同じ排他を持つ。操作が途中なら書かない。

    ストーリー反映の操作（prepared など）は、begin の時点の `_meta.md` のハッシュを記録しており、
    途中で `_meta.md` を変えると再開（resume）が STALE_EVIDENCE になる。読み取りから保存までこの排他を持つ。
    """

    def __init__(self, work: Path) -> None:
        self.work = work
        self.held = None

    def __enter__(self) -> "_StoryReflectionGuard":
        from story_reflection_op import NovelPaths, OpError, acquire_lock, cmd_inspect

        try:
            paths = NovelPaths(self.work)
            snapshot = self._snapshot(paths)
            verdict = cmd_inspect(paths)["verdict"]
        except OpError as error:
            raise MetaError("STORY_REFLECTION", f"ストーリー反映の状態を確かめられない（{error.code}）") from error
        if verdict not in {"terminal_match", "missing", "terminal"}:
            raise MetaError("STORY_REFLECTION_ACTIVE", f"ストーリー反映の操作が途中（{verdict}）。終わってから実行する")
        try:
            self.held = acquire_lock(paths, "meta-" + os.urandom(4).hex())
        except OpError as error:
            raise MetaError("STORY_REFLECTION_ACTIVE", f"ストーリー反映の排他を取れない（{error.code}）") from error
        if self._snapshot(paths) != snapshot:
            # 状態を確かめてから排他を取るまでの間に、新しい操作が始まっていた
            self._release()
            raise MetaError("STORY_REFLECTION_ACTIVE", "ストーリー反映の操作が始まった。終わってから実行する")
        return self

    @staticmethod
    def _snapshot(paths: Any) -> tuple[bytes | None, bytes | None]:
        def read(path: Path) -> bytes | None:
            return path.read_bytes() if path.is_file() else None

        return read(paths.current), read(paths.journal)

    def _release(self) -> None:
        from story_reflection_op import unlink_owned_lock

        if self.held is not None and not unlink_owned_lock(self.held):
            self.held = None
            raise MetaError("LOCK_RELEASE", "ストーリー反映の排他を消せない。lock-inspect で確かめる")
        self.held = None

    def __exit__(self, *exc: object) -> None:
        self._release()


def _read_meta(work: Path) -> tuple[Path, str, bytes]:
    """`_meta.md` のパス、改行を LF にそろえた本文、元のバイト。"""
    path = work / "_meta.md"
    if not path.is_file():
        raise MetaError("NO_META", f"_meta.md が無い: {path}")
    raw = path.read_bytes()
    return path, raw.decode("utf-8").replace("\r\n", "\n"), raw


# ── CLI ──────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="_meta.md の形を判定し、雛形の並びへ移す")
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check", help="形を判定する（書かない）")
    check.add_argument("work", type=Path)
    check.add_argument("--json", action="store_true")
    migrate = sub.add_parser("migrate", help="雛形の並びへ移す")
    migrate.add_argument("work", type=Path)
    migrate.add_argument("--dry-run", action="store_true")
    ensure = sub.add_parser("ensure-section", help="必要な節だけを足す")
    ensure.add_argument("work", type=Path)
    ensure.add_argument("section", choices=sorted(ENSURE_NAMES))
    ensure.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except AttributeError:
        pass
    try:
        path, text, raw = _read_meta(args.work)
        if args.command == "check":
            result = check_text(text)
            if args.json:
                print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
            else:
                print(f"形: {result.form}")
                print("欠けた節: " + ("、".join(SLOT_BY_KEY[k].heading for k in result.missing) or "なし"))
                if result.duplicates:
                    print("重複した節: " + "、".join(result.duplicates))
            return 0
        if args.command == "migrate":
            plan = migrate_text(text)
            verify_migration(text, plan.text, plan.added)
            if plan.text == text:
                print("移す必要はありません（すでに雛形の並び）")
                return 0
            print("見出しの変換:")
            for old, new in plan.renamed:
                print(f"  {old} → {new}")
            print("足す節: " + ("、".join(plan.added) or "なし"))
            print("未分類に置く節: " + ("、".join(plan.unclassified) or "なし"))
            if args.dry_run:
                print("--- 差分 ---")
                sys.stdout.writelines(
                    difflib.unified_diff(
                        text.splitlines(keepends=True), plan.text.splitlines(keepends=True), "before", "after"
                    )
                )
                return 0
            with _StoryReflectionGuard(args.work):
                path, text, raw = _read_meta(args.work)  # 排他を取ってから読み直す
                plan = migrate_text(text)
                verify_migration(text, plan.text, plan.added)
                backup = _backup(args.work, raw)
                _write(path, plan.text, _newline_of(raw))
            print(f"移しました（旧版: {backup.as_posix()}）")
            return 0
        slot_key = ENSURE_NAMES[args.section]
        updated = ensure_section_text(text, slot_key)
        if updated == text:
            print("節はすでにあります")
            return 0
        if args.dry_run:
            print(f"足す節: {SLOT_BY_KEY[slot_key].heading}")
            return 0
        with _StoryReflectionGuard(args.work):
            path, text, raw = _read_meta(args.work)  # 排他を取ってから読み直す
            updated = ensure_section_text(text, slot_key)
            if updated == text:
                print("節はすでにあります")
                return 0
            backup = _backup(args.work, raw)
            _write(path, updated, _newline_of(raw))
        print(f"足しました: {SLOT_BY_KEY[slot_key].heading}（旧版: {backup.as_posix()}）")
        return 0
    except MetaError as error:
        print(f"{error.code}\t{error}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
