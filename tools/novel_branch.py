#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Monogatari Coach — 改訂枝（作品分岐）の作成・一覧・差分。

改訂枝は git のブランチではなく、作品フォルダの兄弟である。元 `novels/051_タイトル`（旧版）の隣に
`novels/051a_タイトル`（改訂枝）を作る。番号は 051 のまま（次の新作 052 を消費しない）。
計画: _workingspace/plans/20261122_novel-compare-branch.md

    uv run python tools/novel_branch.py fork --from novels/051_タイトル            # dry-run（既定）
    uv run python tools/novel_branch.py fork --from novels/051_タイトル \\
        --scope skeleton_text --reason revision --note "発表から2年たち、設定を今の方針で直す" --apply
    uv run python tools/novel_branch.py list [novels/051_タイトル | 051]
    uv run python tools/novel_branch.py diff 051 051a [--layer text,design]

- fork は既定で dry-run。写すパス・写さないパス・概算サイズを出して止まる。書くのは `--apply` のときだけ。
- 範囲は skeleton（骨格）/ skeleton_text（骨格と本文。既定）/ full（全体）。
- 機械の記録（`_work/`、旧 `_writing/` `_metron/` `_story_reflection_op.*` `_story_work/`）、キャッシュ、
  lock、移行中の印は、どの範囲でも写さない。写すと未計測の本文が計測済みに見える。
- 評価（`_reader/` の中身）、旧版（`_novel_text_backup/`）、画像の実体、CHRONOS の記録、出版の lock と出力、
  圧縮ファイルは、`--include` で明示したときだけ写す。
- 枝の config.md の基本情報表へ branch / parent_ID / branch_reason を足す。METRON / CHRONOS / AUDIT_LOG は
  元の値を引き継ぐ。METRON ON なら空の `_work/metron/` だけ用意する（計測済みにはしない）。
- 枝と元の `_meta.md` の「1. 執筆フェーズ・ステータス」節へ `### 改訂枝` を足す。元は書く前に
  `_novel_text_backup/_meta_vNNN.md` へ退避し、ストーリー反映と同じ排他を取る。
- 反映（promote）・取り込み（absorb）は第2版。第1版の着地は並存。
"""

from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import hashlib
import json
import re
import shutil
import string
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

import novel_code_allocate as nca  # noqa: E402

SCOPES = ("skeleton", "skeleton_text", "full")
DEFAULT_SCOPE = "skeleton_text"
SCOPE_LABELS = {
    "skeleton": "骨格",
    "skeleton_text": "骨格と本文",
    "full": "全体",
}
REASON_LABELS = {"revision": "改訂", "compare": "比較"}

# 範囲ごとに写す層
SCOPE_LAYERS: dict[str, frozenset[str]] = {
    "skeleton": frozenset({"canon"}),
    "skeleton_text": frozenset({"canon", "text"}),
    "full": frozenset({"canon", "text", "source", "references", "assets", "other"}),
}

# `--include` で明示したときだけ写す層（骨格の範囲では source / references も含む）
INCLUDE_CHOICES = (
    "source",
    "references",
    "reader",
    "backup",
    "images",
    "chronos",
    "publication",
    "archives",
)
LAYER_LABELS = {
    "canon": "骨格資料（作品直下のファイル）",
    "text": "本文（_novel_text/）",
    "source": "原資料（_source_material/）",
    "references": "参考資料（references/）",
    "assets": "画像・漫画の YAML など（tag/ manga/ illustrations/ cover/）",
    "other": "そのほかのフォルダ",
    "reader": "評価（_reader/ の中身）",
    "backup": "旧版（_novel_text_backup/）",
    "images": "画像の実体",
    "chronos": "CHRONOS の記録（chronos/）",
    "publication": "出版の lock と出力",
    "archives": "圧縮ファイル",
}

# どの範囲でも写さない（作品直下の名前）
DENY_TOP = {
    "_work": "機械の記録（場面ハッシュ・run パスが元フォルダ前提）",
    "_writing": "機械の記録（執筆接続の旧い置き場）",
    "_metron": "機械の記録（METRON の旧い置き場）",
    "_story_work": "機械の記録（旧い構成）",
    "_story_reflection_op.json": "機械の記録（ストーリー反映）",
    "_story_reflection_op.jsonl": "機械の記録（ストーリー反映）",
    "_story_reflection_op.lock": "作業中の lock",
}
# 入れ子の機械の記録（work_paths の reader の旧い置き場と、旧い構成の印）
DENY_NESTED = {
    "_reader/_work": "機械の記録（評価の中間の旧い置き場）",
    "_reader/_sr_staging": "機械の記録（旧い構成）",
}
# どの深さでも写さない
DENY_ANY_NAMES = {"__pycache__", ".pytest_cache", ".migrating"}
DENY_ANY_SUFFIXES = (".lock", ".tmp", ".pyc")

TOP_DIR_LAYERS = {
    "_novel_text": "text",
    "_reader": "reader",
    "_novel_text_backup": "backup",
    "_source_material": "source",
    "references": "references",
    "chronos": "chronos",
    "_publication_output": "publication",
    "tag": "assets",
    "manga": "assets",
    "illustrations": "assets",
    "cover": "assets",
}
PUBLICATION_FILES = {"book.lock.yaml"}
ARCHIVE_SUFFIXES = (".zip", ".7z", ".rar", ".tar", ".gz")
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".psd", ".bmp", ".tif", ".tiff", ".avif")
IMAGE_SKIP_REASON = "確認する層: 画像の実体（--include images で写せる）"
TEXT_SUFFIXES = (".md", ".yaml", ".yml", ".json", ".txt", ".csv")
# 写したあとも空で用意する置き場
EMPTY_DIRS = ("_novel_text", "_reader")

BRANCH_HEADING = "### 改訂枝"


class BranchError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


# ── 解決 ─────────────────────────────────────────────────────────────────


def repo_root() -> Path:
    return _TOOLS_DIR.parent


def resolve_work(value: str, novels_root: Path) -> Path:
    """フォルダのパス、または番号（051 / 051a）から作品フォルダを一つに決める。"""
    path = Path(value)
    candidates = [path] if path.is_absolute() else [repo_root() / path, novels_root / path]
    for candidate in candidates:
        if candidate.is_dir() and nca.parse_folder_name(candidate.name):
            return candidate.resolve()
    m = re.fullmatch(r"(\d+)([a-z])?", value.strip())
    if not m:
        raise BranchError("NOT_FOUND", f"作品フォルダが見つかりません: {value}")
    code, branch = int(m.group(1)), m.group(2)
    found = [
        child
        for child in sorted(novels_root.iterdir())
        if child.is_dir()
        and (p := nca.parse_folder_name(child.name)) is not None
        and p.code == code
        and p.branch == branch
    ]
    if not found:
        raise BranchError("NOT_FOUND", f"番号 {value} の作品フォルダが {novels_root.as_posix()} にありません")
    if len(found) > 1:
        raise BranchError(
            "AMBIGUOUS",
            f"番号 {value} の作品フォルダが複数あります（フォルダのパスで指定する）: "
            + ", ".join(f.name for f in found),
        )
    return found[0].resolve()


def siblings_of(code: int, novels_root: Path) -> list[tuple[nca.FolderName, Path]]:
    out = []
    for child in sorted(novels_root.iterdir()):
        if not child.is_dir():
            continue
        parsed = nca.parse_folder_name(child.name)
        if parsed and parsed.code == code:
            out.append((parsed, child))
    return out


def next_branch_letter(code: int, novels_root: Path) -> str:
    used = {p.branch for p, _ in siblings_of(code, novels_root) if p.branch}
    # 規則外の大文字の枝（051A_）も、NTFS では小文字と同居できないので使用済みに数える
    for child in novels_root.iterdir():
        m = re.match(r"^(\d+)([A-Za-z])_", child.name)
        if child.is_dir() and m and int(m.group(1)) == code:
            used.add(m.group(2).lower())
    for letter in string.ascii_lowercase:
        if letter not in used:
            return letter
    raise BranchError("NO_BRANCH_LETTER", f"番号 {code} の枝 a–z はすべて使われています")


# ── 複製の計画 ───────────────────────────────────────────────────────────


@dataclass
class Entry:
    rel: str
    layer: str
    size: int


@dataclass
class Skipped:
    rel: str
    reason: str
    size: int = 0


@dataclass
class ForkPlan:
    trunk: str
    target: str
    label: str
    branch: str
    scope: str
    reason: str | None
    includes: list[str]
    copies: list[Entry] = field(default_factory=list)
    skipped: list[Skipped] = field(default_factory=list)
    empty_dirs: list[str] = field(default_factory=list)
    self_references: list[dict[str, Any]] = field(default_factory=list)
    flags: dict[str, str] = field(default_factory=dict)
    text_files: int = 0
    warnings: list[str] = field(default_factory=list)

    @property
    def copy_bytes(self) -> int:
        return sum(e.size for e in self.copies)

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["copy_bytes"] = self.copy_bytes
        return data


def _tree_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def _denied(name: str) -> bool:
    return name in DENY_ANY_NAMES or name.endswith(DENY_ANY_SUFFIXES) or name.startswith(".")


def _layer_of_top(child: Path) -> str | None:
    """作品直下の項目の層。None はどの範囲でも写さない。"""
    name = child.name
    if name in DENY_TOP or _denied(name):
        return None
    if child.is_file():
        if name in PUBLICATION_FILES:
            return "publication"
        if name.lower().endswith(ARCHIVE_SUFFIXES):
            return "archives"
        return "canon"
    return TOP_DIR_LAYERS.get(name, "other")


def _allowed_layers(scope: str, includes: list[str]) -> set[str]:
    return set(SCOPE_LAYERS[scope]) | set(includes)


def build_fork_plan(
    trunk: Path,
    *,
    novels_root: Path,
    scope: str = DEFAULT_SCOPE,
    reason: str | None = None,
    branch: str | None = None,
    title: str | None = None,
    includes: list[str] | None = None,
) -> ForkPlan:
    trunk = trunk.resolve()
    includes = sorted(set(includes or []))
    if scope not in SCOPES:
        raise BranchError("BAD_SCOPE", f"範囲は {' / '.join(SCOPES)} のどれか: {scope}")
    bad = [i for i in includes if i not in INCLUDE_CHOICES]
    if bad:
        raise BranchError("BAD_INCLUDE", f"--include は {', '.join(INCLUDE_CHOICES)} から選ぶ: {', '.join(bad)}")
    if reason is not None and reason not in nca.BRANCH_REASONS:
        raise BranchError("BAD_REASON", f"--reason は revision（改訂）か compare（比較）: {reason}")
    parsed = nca.parse_folder_name(trunk.name)
    if parsed is None:
        raise BranchError("BAD_TRUNK", f"元フォルダの名前が採番規則に一致しません: {trunk.name}")
    if parsed.branch:
        raise BranchError(
            "BRANCH_OF_BRANCH",
            f"{trunk.name} は改訂枝です。枝からは分岐しません（元 {parsed.digits}_… から分岐する）",
        )
    verified = nca.verify_work_dir(trunk)
    if not verified.get("ok"):
        raise BranchError("TRUNK_NOT_VERIFIED", "元フォルダの verify が通りません: " + "; ".join(verified.get("issues") or []))
    trunks = nca.find_trunk_folders(novels_root, parsed.code)
    if len(trunks) > 1:
        # parent_ID は番号だけなので、同じ番号の元が複数あると枝の元が決まらず、枝の文字も取り合いになる
        raise BranchError(
            "AMBIGUOUS_TRUNK",
            f"番号 {parsed.digits} の元フォルダが複数あります（{', '.join(t.name for t in trunks)}）。"
            "どれが元か決まらないので分岐しません。先に番号の重複を解消する",
        )

    if branch is None:
        branch = next_branch_letter(parsed.code, novels_root)
    elif not re.fullmatch(r"[a-z]", branch):
        raise BranchError("BAD_BRANCH", f"枝は英小文字1文字（a–z）: {branch!r}")
    title_part = re.sub(r"[\s　]+", "_", title.strip()) if title else parsed.title
    if not title_part or "/" in title_part or "\\" in title_part:
        raise BranchError("BAD_TITLE", f"フォルダ名に使えない題です: {title!r}")
    target = novels_root.resolve() / f"{parsed.digits}{branch}_{title_part}"
    for p, child in siblings_of(parsed.code, novels_root):
        if p.branch == branch:
            raise BranchError("BRANCH_EXISTS", f"枝 {parsed.digits}{branch} はすでにあります: {child.name}")
    if any(c.name.lower() == target.name.lower() for c in novels_root.iterdir()):
        raise BranchError("TARGET_EXISTS", f"同じ名前のフォルダがすでにあります: {target.name}")

    from inspection_flags import load_inspection_flags

    flags = load_inspection_flags(trunk / "config.md")
    audit = _audit_value(trunk / "config.md")
    plan = ForkPlan(
        trunk=trunk.as_posix(),
        target=target.as_posix(),
        label=f"{parsed.digits}{branch}",
        branch=branch,
        scope=scope,
        reason=reason,
        includes=includes,
        flags={"METRON": flags.metron.value, "CHRONOS": flags.chronos.value, "AUDIT_LOG": audit},
    )
    allowed = _allowed_layers(scope, includes)

    for child in sorted(trunk.iterdir()):
        rel = child.name
        layer = _layer_of_top(child)
        if layer is None:
            reason_text = DENY_TOP.get(rel, "キャッシュ・lock・隠しファイル")
            plan.skipped.append(Skipped(rel + ("/" if child.is_dir() else ""), f"どの範囲でも写さない: {reason_text}", _tree_size(child)))
            continue
        if layer not in allowed:
            if layer in INCLUDE_CHOICES:
                hint = f"--include {layer} で写せる"
            elif layer == "text":
                hint = "範囲 skeleton_text か full で写す"
            else:
                hint = "範囲 full で写す"
            plan.skipped.append(
                Skipped(rel + ("/" if child.is_dir() else ""), f"範囲外: {LAYER_LABELS[layer]}（{hint}）", _tree_size(child))
            )
            continue
        if child.is_file():
            if child.suffix.lower() in IMAGE_SUFFIXES and "images" not in allowed:
                # 画像の実体は置き場（作品直下の cover.png など）によらず確認してから写す
                plan.skipped.append(Skipped(rel, IMAGE_SKIP_REASON, child.stat().st_size))
                continue
            plan.copies.append(Entry(rel, layer, child.stat().st_size))
            continue
        _plan_dir(plan, trunk, child, layer, allowed)

    for name in EMPTY_DIRS:
        if not any(e.rel.startswith(name + "/") for e in plan.copies):
            plan.empty_dirs.append(name)
    plan.text_files = sum(1 for e in plan.copies if e.layer == "text" and e.rel.endswith(".md"))
    plan.self_references = _self_references(trunk, plan)
    if plan.flags["METRON"] == "ON" and plan.text_files:
        plan.warnings.append(
            f"METRON ON: 写す本文 {plan.text_files} ファイルは、枝では計測の記録が無い（_work/ を写さないため）。"
            "config の METRON_FROM より前の章を除き、枝で新しい章を書く前に後追い計測が要る"
            "（novel_project_check --check-inspection-layers が止める）"
        )
    if reason is None:
        plan.warnings.append("改訂理由（--reason revision / compare）が未指定。--apply の前に決める")
    return plan


def _plan_dir(plan: ForkPlan, trunk: Path, top: Path, layer: str, allowed: set[str]) -> None:
    for nested, why in DENY_NESTED.items():
        if (trunk / nested).exists() and nested.split("/", 1)[0] == top.name:
            plan.skipped.append(Skipped(nested + "/", f"どの範囲でも写さない: {why}", _tree_size(trunk / nested)))
    for path in sorted(top.rglob("*")):
        rel_path = path.relative_to(trunk)
        rel_posix = rel_path.as_posix()
        if any(rel_posix == n or rel_posix.startswith(n + "/") for n in DENY_NESTED):
            continue
        if any(_denied(part) for part in rel_path.parts):
            if path.is_file() and not any(_denied(part) for part in rel_path.parts[:-1]):
                plan.skipped.append(Skipped(rel_path.as_posix(), "どの範囲でも写さない: キャッシュ・lock・隠しファイル", path.stat().st_size))
            continue
        if not path.is_file():
            continue
        if path.suffix.lower() in IMAGE_SUFFIXES and "images" not in allowed:
            plan.skipped.append(Skipped(rel_path.as_posix(), IMAGE_SKIP_REASON, path.stat().st_size))
            continue
        if path.suffix.lower() in ARCHIVE_SUFFIXES and "archives" not in allowed:
            plan.skipped.append(Skipped(rel_path.as_posix(), "確認する層: 圧縮ファイル（--include archives で写せる）", path.stat().st_size))
            continue
        plan.copies.append(Entry(rel_path.as_posix(), layer, path.stat().st_size))


def _audit_value(config: Path) -> str:
    text = config.read_text(encoding="utf-8") if config.is_file() else ""
    value = nca.read_table_value(text, nca._table_value_re("AUDIT_LOG"))
    return value or "ON"


def _self_references(trunk: Path, plan: ForkPlan) -> list[dict[str, Any]]:
    """写すテキストのうち、元フォルダ名を書いているもの。書き換えず一覧にだけ出す。"""
    hits = []
    for entry in plan.copies:
        if not entry.rel.lower().endswith(TEXT_SUFFIXES):
            continue
        try:
            text = (trunk / entry.rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        count = text.count(trunk.name)
        if count:
            hits.append({"rel": entry.rel, "count": count})
    return hits


# ── 書き込み ─────────────────────────────────────────────────────────────


def branch_config_text(text: str, *, branch: str, parent_digits: str, reason: str) -> str:
    """基本情報表の novel_ID 行の直後へ branch / parent_ID / branch_reason を足す。"""
    if nca.read_table_value(text, nca.BRANCH_TABLE_RE) or nca.read_table_value(text, nca.PARENT_ID_TABLE_RE):
        raise BranchError("CONFIG_HAS_BRANCH", "元の config.md にすでに branch / parent_ID 行があります")
    m = nca.NOVEL_ID_TABLE_RE.search(text)
    if not m:
        raise BranchError("CONFIG_NO_ID", "config.md に | novel_ID | NNN | 行がありません")
    newline = "\r\n" if "\r\n" in text else "\n"
    rows = (
        f"| branch | {branch} |{newline}"
        f"| parent_ID | {parent_digits} |{newline}"
        f"| branch_reason | {reason} |"
    )
    # NOVEL_ID_TABLE_RE は先頭・末尾の \s* が前後の空行や改行まで食うので、行は "novel_ID" の位置から探す
    end = text.find("\n", text.index("novel_ID", m.start()))
    if end == -1:
        return text + newline + rows
    if text[end - 1 : end] == "\r":
        end -= 1
    return text[:end] + newline + rows + text[end:]


def insert_branch_record(text: str, lines: list[str], *, replace: bool = False) -> str:
    """`_meta.md` の「1. 執筆フェーズ・ステータス」節へ `### 改訂枝` を足す（あれば行を足す）。

    `#`・`##` の見出しの並びは変えない（novel_meta_check の節の判定・移行を崩さない）。
    I.1 の節が無い古い形の `_meta.md` では、末尾へ `## 改訂枝` を足す。
    replace=True は既にある `### 改訂枝` の中身を置き換える（枝へ写した元の履歴を残さない）。
    """
    if replace:
        text = _drop_branch_record(text)
    from novel_meta_check import _slot_of, split_blocks

    blocks = split_blocks(text)
    target = next(
        (b for b in blocks[1:] if b.level == 2 and (s := _slot_of(b.heading)) is not None and s.key == "I.1"),
        None,
    )
    if target is None:
        body = text.rstrip("\n")
        if re.search(r"^## 改訂枝\s*$", body, re.MULTILINE):
            return body + "\n" + "\n".join(lines) + "\n"
        return body + "\n\n## 改訂枝\n\n" + "\n".join(lines) + "\n"

    body = target.body
    start = next((i for i, line in enumerate(body) if line.strip() == BRANCH_HEADING), None)
    if start is None:
        while body and not body[-1].strip():
            body.pop()
        body.extend(["", BRANCH_HEADING, "", *lines, ""])
    else:
        end = next((i for i in range(start + 1, len(body)) if body[i].startswith("#")), len(body))
        insert_at = end
        while insert_at > start + 1 and not body[insert_at - 1].strip():
            insert_at -= 1
        body[insert_at:insert_at] = lines
        if insert_at + len(lines) >= len(body) or body[insert_at + len(lines)].strip():
            body.insert(insert_at + len(lines), "")

    out: list[str] = list(blocks[0].body)
    for block in blocks[1:]:
        out.append(block.heading)
        out.extend(block.body)
    return "\n".join(out)


def _drop_branch_record(text: str) -> str:
    """`### 改訂枝`（または古い形の `## 改訂枝`）の小節を、次の見出しの手前まで消す。"""
    lines = text.split("\n")
    out: list[str] = []
    skipping = False
    level = 0
    for line in lines:
        stripped = line.strip()
        if stripped in (BRANCH_HEADING, "## 改訂枝"):
            skipping = True
            level = len(stripped) - len(stripped.lstrip("#"))
            continue
        if skipping:
            m = re.match(r"^(#{1,6})\s", line)
            if m and len(m.group(1)) <= level:
                skipping = False
            else:
                continue
        out.append(line)
    return "\n".join(out)


def _branch_meta_lines(plan: ForkPlan, trunk_name: str, note: str | None, today: str) -> list[str]:
    reason = plan.reason or ""
    extra = "、".join(LAYER_LABELS[i] for i in plan.includes) or "なし"
    measured = (
        "METRON ON。写した本文は未計測（新しい章の前に後追い計測）"
        if plan.flags.get("METRON") == "ON" and plan.text_files
        else f"METRON {plan.flags.get('METRON')}"
    )
    return [
        f"- **元**: `novels/{trunk_name}`（旧版として残す）",
        f"- **切った日**: {today}",
        f"- **理由**: {reason}（{REASON_LABELS.get(reason, '')}）— {note or '（未記入。時期や状況の変化を口語で書く）'}",
        f"- **写した範囲**: {plan.scope}（{SCOPE_LABELS[plan.scope]}）。追加: {extra}",
        f"- **機械の記録**: `_work/` は写していない。{measured}",
        "- **企画**: Gate B は再実施しない（設定の厚さのやり直しを明示されたときだけ検討）",
        f"- **写す前の記録**: この節のほかの進捗・文字数・評価・画像の記述は、元 `{trunk_name}` の時点のもの。"
        + (f"この枝に無いもの: {_absent_summary(plan)}" if _absent_summary(plan) else "枝で改訂したら書き直す"),
    ]


def _absent_summary(plan: ForkPlan) -> str:
    """元にあって枝に写さなかった作品直下の項目（機械の記録は除く）。"""
    names = [
        s.rel
        for s in plan.skipped
        if "/" not in s.rel.rstrip("/") and not s.reason.startswith("どの範囲でも写さない")
    ]
    names += [f"{d}/ の中身" for d in plan.empty_dirs if any(s.rel.rstrip("/") == d for s in plan.skipped)]
    names = [n for n in names if n.rstrip("/") not in plan.empty_dirs]
    return "、".join(f"`{n}`" for n in names)


def apply_fork(plan: ForkPlan, *, novels_root: Path, note: str | None = None, today: str | None = None) -> dict[str, Any]:
    if plan.reason is None:
        raise BranchError("NO_REASON", "--apply には --reason revision / compare が要る")
    trunk = Path(plan.trunk)
    target = Path(plan.target)
    today = today or dt.date.today().isoformat()
    staging = novels_root.resolve() / f".{target.name}.forking"
    if target.exists():
        raise BranchError("TARGET_EXISTS", f"同じ名前のフォルダがすでにあります: {target.name}")
    if staging.exists():
        raise BranchError("STAGING_EXISTS", f"前回の途中の複製が残っています（中を確かめてから消す）: {staging.as_posix()}")
    trunk_parsed = nca.parse_folder_name(trunk.name)
    assert trunk_parsed is not None

    from novel_meta_check import MetaError, _StoryReflectionGuard

    # 元のストーリー反映が途中なら _meta.md も書きかけでありうる。複製の前に断り、複製から
    # 元への記録までを同じ排他の中で行う。
    created = False
    trunk_meta_status = "未記録"
    try:
        with _StoryReflectionGuard(trunk):
            _copy_into_staging(plan, trunk, staging, trunk_parsed.digits, note, today)
            staging.rename(target)
            created = True
            try:
                trunk_meta_status = _record_on_trunk(trunk, plan, today)
            except Exception as error:  # 枝はできている。元の記録だけ失敗として報告する
                trunk_meta_status = f"未記録（{type(error).__name__}: {error}）。枝はできている。元の _meta.md へ手で1行足す"
                plan.warnings.append(f"元の _meta.md に記録できなかった: {error}")
    except MetaError as error:
        if not created:
            shutil.rmtree(staging, ignore_errors=True)
            raise BranchError(
                "TRUNK_BUSY", f"元のストーリー反映を確かめられないか途中です（{error.code}: {error}）。終わってから分岐する"
            ) from error
        # 枝を作ったあと、排他の解放だけが失敗した
        plan.warnings.append(f"ストーリー反映の排他を解放できなかった（{error.code}）。lock-inspect で確かめる")
    except Exception:
        if not created:
            shutil.rmtree(staging, ignore_errors=True)
        raise

    verified = nca.verify_work_dir(target)
    return {
        "target": target.as_posix(),
        "label": plan.label,
        "copied_files": len(plan.copies),
        "copy_bytes": plan.copy_bytes,
        "trunk_meta": trunk_meta_status,
        "verify": verified,
        "warnings": plan.warnings,
    }


def _copy_into_staging(plan: ForkPlan, trunk: Path, staging: Path, parent_digits: str, note: str | None, today: str) -> None:
    staging.mkdir()
    for entry in plan.copies:
        src = trunk / entry.rel
        dst = staging / entry.rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    for name in EMPTY_DIRS:
        (staging / name).mkdir(exist_ok=True)
    config = staging / "config.md"
    raw = config.read_bytes().decode("utf-8")
    config.write_bytes(
        branch_config_text(raw, branch=plan.branch, parent_digits=parent_digits, reason=plan.reason or "").encode("utf-8")
    )
    meta = staging / "_meta.md"
    if meta.is_file():
        raw_meta = meta.read_bytes().decode("utf-8")
        newline = "\r\n" if "\r\n" in raw_meta else "\n"
        updated = insert_branch_record(
            raw_meta.replace("\r\n", "\n"), _branch_meta_lines(plan, trunk.name, note, today), replace=True
        )
        meta.write_bytes(updated.replace("\n", newline).encode("utf-8"))
    else:
        plan.warnings.append("元に _meta.md が無いので、枝の改訂枝の記録を書いていない")
    if plan.flags.get("METRON") == "ON":
        (staging / "_work" / "metron").mkdir(parents=True, exist_ok=True)


def _record_on_trunk(trunk: Path, plan: ForkPlan, today: str) -> str:
    """元の `_meta.md` に作った改訂枝を1行残す。呼び手がストーリー反映の排他を持つ。書く前に退避する。"""
    from novel_meta_check import _backup, _newline_of, _read_meta, _write

    if not (trunk / "_meta.md").is_file():
        return "skip（元に _meta.md が無い）"
    line = (
        f"- {today} `novels/{Path(plan.target).name}` を作った（{plan.reason}・{plan.scope}）。"
        "この作品は旧版として残す"
    )
    path, text, raw = _read_meta(trunk)
    updated = insert_branch_record(text, [line])
    backup = _backup(trunk, raw)
    _write(path, updated, _newline_of(raw))
    return f"記録した（旧版: {backup.relative_to(trunk).as_posix()}）"


# ── 一覧 ─────────────────────────────────────────────────────────────────


def list_branches(novels_root: Path, code: int | None = None) -> list[dict[str, Any]]:
    data = nca.scan_novels(novels_root)
    by_code: dict[int, list[dict[str, Any]]] = {}
    for e in data["entries"]:
        by_code.setdefault(e["code"], []).append(e)
    out = []
    for c, entries in sorted(by_code.items()):
        if code is not None and c != code:
            continue
        if code is None and not any(e["branch"] for e in entries):
            continue
        for e in sorted(entries, key=lambda x: (x["branch"] or "", x["folder"])):
            work = Path(e["path"])
            v = nca.verify_work_dir(work)
            out.append(
                {
                    "code": c,
                    "branch": e["branch"],
                    "folder": e["folder"],
                    "role": "改訂枝" if e["branch"] else "元",
                    "branch_reason": v.get("branch_reason"),
                    "verify_ok": v.get("ok"),
                    "issues": v.get("issues"),
                }
            )
    return out


# ── 差分 ─────────────────────────────────────────────────────────────────

DIFF_LAYERS = ("canon", "design", "profile", "text")
_NUMBERED_RE = re.compile(r"^\s*\d+[.．、)]\s*\S")
_FIELD_RE = re.compile(r"^\s*-\s+\*\*[^*]+\*\*\s*[:：]")
_HEADING_RE = re.compile(r"^#{1,6}\s")


def _diff_files(work: Path, layer: str) -> dict[str, Path]:
    if layer == "design":
        names = ["design_specification.md"]
        return {n: work / n for n in names if (work / n).is_file()}
    if layer == "profile":
        names = ["character.md", "world.md"]
        return {n: work / n for n in names if (work / n).is_file()}
    if layer == "canon":
        return {
            c.name: c
            for c in sorted(work.iterdir())
            if c.is_file() and _layer_of_top(c) == "canon"
        }
    if layer == "text":
        base = work / "_novel_text"
        if not base.is_dir():
            return {}
        return {
            p.relative_to(work).as_posix(): p
            for p in sorted(base.rglob("*"))
            if p.is_file() and not any(_denied(part) for part in p.relative_to(work).parts)
        }
    raise BranchError("BAD_LAYER", f"層は {', '.join(DIFF_LAYERS)} から選ぶ: {layer}")


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _shape(path: Path) -> dict[str, int]:
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    return {
        "headings": sum(1 for line in lines if _HEADING_RE.match(line)),
        "numbered": sum(1 for line in lines if _NUMBERED_RE.match(line)),
        "fields": sum(1 for line in lines if _FIELD_RE.match(line)),
    }


def _is_counted_text(rel: str) -> bool:
    parts = rel.split("/")
    return len(parts) == 2 and parts[0] == "_novel_text" and fnmatch.fnmatch(parts[1], "novel_text*.md")


def _chars(path: Path) -> int:
    from novel_char_count import count_chars

    return count_chars(path.read_text(encoding="utf-8", errors="replace"), strip_fm=True)


def diff_works(a: Path, b: Path, layers: list[str]) -> dict[str, Any]:
    result: dict[str, Any] = {"a": a.as_posix(), "b": b.as_posix(), "layers": {}}
    for layer in layers:
        fa, fb = _diff_files(a, layer), _diff_files(b, layer)
        added = sorted(set(fb) - set(fa))
        removed = sorted(set(fa) - set(fb))
        changed = sorted(k for k in set(fa) & set(fb) if _digest(fa[k]) != _digest(fb[k]))
        entry: dict[str, Any] = {"added": added, "removed": removed, "changed": changed, "same": len(set(fa) & set(fb)) - len(changed)}
        if layer in ("design", "profile"):
            entry["shape"] = {k: {"a": _shape(fa[k]), "b": _shape(fb[k])} for k in changed}
        if layer == "text":
            # novel_char_count.py と同じ対象（_novel_text/ 直下の novel_text*.md）だけを数える
            md = sorted(k for k in set(fa) | set(fb) if _is_counted_text(k))
            rows = []
            for k in md:
                ca = _chars(fa[k]) if k in fa else None
                cb = _chars(fb[k]) if k in fb else None
                rows.append({"file": k, "a": ca, "b": cb})
            entry["chars"] = rows
            entry["total"] = {
                "a": sum(r["a"] or 0 for r in rows),
                "b": sum(r["b"] or 0 for r in rows),
            }
        result["layers"][layer] = entry
    result["reader_files"] = {
        "a": _count_files(a / "_reader"),
        "b": _count_files(b / "_reader"),
    }
    return result


def _count_files(path: Path) -> int:
    return sum(1 for p in path.rglob("*") if p.is_file()) if path.is_dir() else 0


# ── 表示 ─────────────────────────────────────────────────────────────────


def _human(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"


def print_plan(plan: ForkPlan, root: Path) -> None:
    def rel(p: str) -> str:
        try:
            return Path(p).relative_to(root).as_posix()
        except ValueError:
            return p

    print(f"元      : {rel(plan.trunk)}")
    print(f"改訂枝  : {rel(plan.target)}（{plan.label}）")
    print(f"範囲    : {plan.scope}（{SCOPE_LABELS[plan.scope]}）  追加: {', '.join(plan.includes) or 'なし'}")
    print(f"理由    : {plan.reason or '未指定'}")
    print(f"引き継ぐ: " + ", ".join(f"{k} {v}" for k, v in plan.flags.items()))
    print(f"\n写す: {len(plan.copies)} ファイル / {_human(plan.copy_bytes)}")
    by_layer: dict[str, list[Entry]] = {}
    for e in plan.copies:
        by_layer.setdefault(e.layer, []).append(e)
    for layer, entries in by_layer.items():
        print(f"  [{LAYER_LABELS[layer]}] {len(entries)} ファイル / {_human(sum(e.size for e in entries))}")
        for e in entries[:12]:
            print(f"    {e.rel}")
        if len(entries) > 12:
            print(f"    …ほか {len(entries) - 12} ファイル")
    if plan.empty_dirs:
        print("空で用意: " + ", ".join(d + "/" for d in plan.empty_dirs))
    if plan.skipped:
        print(f"\n写さない: {len(plan.skipped)} 件 / {_human(sum(s.size for s in plan.skipped))}")
        for s in plan.skipped[:30]:
            print(f"  {s.rel} — {s.reason}（{_human(s.size)}）")
        if len(plan.skipped) > 30:
            print(f"  …ほか {len(plan.skipped) - 30} 件")
    if plan.self_references:
        print("\n元フォルダ名を書いているファイル（書き換えない。必要なら枝で直す）:")
        for h in plan.self_references:
            print(f"  {h['rel']}（{h['count']} か所）")
    for w in plan.warnings:
        print(f"\nWARNING: {w}")


def print_diff(data: dict[str, Any], root: Path) -> None:
    def rel(p: str) -> str:
        try:
            return Path(p).relative_to(root).as_posix()
        except ValueError:
            return p

    print(f"A: {rel(data['a'])}")
    print(f"B: {rel(data['b'])}")
    for layer, entry in data["layers"].items():
        print(f"\n[{layer}] 同じ {entry['same']} / 内容差 {len(entry['changed'])} / B だけ {len(entry['added'])} / A だけ {len(entry['removed'])}")
        for k in entry["changed"]:
            line = f"  ~ {k}"
            shape = (entry.get("shape") or {}).get(k)
            if shape:
                parts = [
                    f"{label} {shape['a'][key]}→{shape['b'][key]}"
                    for key, label in (("headings", "見出し"), ("numbered", "番号項"), ("fields", "欄"))
                    if shape["a"][key] != shape["b"][key]
                ]
                if parts:
                    line += "（" + "、".join(parts) + "）"
            print(line)
        for k in entry["added"]:
            print(f"  + {k}")
        for k in entry["removed"]:
            print(f"  - {k}")
        if layer == "text" and entry.get("chars"):
            print("  文字数（novel_char_count と同じ数え方）:")
            for r in entry["chars"]:
                a = "—" if r["a"] is None else f"{r['a']:,}"
                b = "—" if r["b"] is None else f"{r['b']:,}"
                print(f"    {r['file']}: {a} → {b}")
            t = entry["total"]
            print(f"    合計: {t['a']:,} → {t['b']:,}（{t['b'] - t['a']:+,}）")
    rf = data["reader_files"]
    print(f"\n_reader/: A {rf['a']} ファイル / B {rf['b']} ファイル（評価は各フォルダに別保存。差分は取らない）")


# ── CLI ──────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    try:
        from console_io import configure_stdio_utf8

        configure_stdio_utf8()
    except Exception:  # pragma: no cover
        pass

    parser = argparse.ArgumentParser(description="改訂枝（作品分岐）の作成・一覧・差分")
    parser.add_argument("--novels-dir", type=Path, default=None, help="novels ディレクトリ（既定: リポジトリルート/novels）")
    sub = parser.add_subparsers(dest="command", required=True)

    p_fork = sub.add_parser("fork", help="元から改訂枝を作る（既定は dry-run）")
    p_fork.add_argument("--from", dest="source", required=True, help="元フォルダ（novels/051_タイトル）か番号（051）")
    p_fork.add_argument("--scope", choices=SCOPES, default=DEFAULT_SCOPE, help=f"範囲（既定 {DEFAULT_SCOPE}）")
    p_fork.add_argument("--reason", choices=nca.BRANCH_REASONS, default=None, help="revision（改訂）/ compare（比較）")
    p_fork.add_argument("--note", default=None, help="改訂の理由を口語で（_meta.md に残す）")
    p_fork.add_argument("--branch", default=None, help="枝の1文字（既定: 未使用の最初の a–z）")
    p_fork.add_argument("--title", default=None, help="フォルダ名の題（既定: 元と同じ）")
    p_fork.add_argument("--include", action="append", default=[], choices=INCLUDE_CHOICES, help="確認する層を写す（複数可）")
    mode = p_fork.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="dry-run をやめて実際に作る")
    mode.add_argument("--dry-run", action="store_true", help="既定と同じ（明示用。何も作らない）")
    p_fork.add_argument("--json", action="store_true")

    p_list = sub.add_parser("list", help="元と改訂枝の一覧")
    p_list.add_argument("target", nargs="?", default=None, help="作品フォルダか番号（省略: 枝のある番号だけ）")
    p_list.add_argument("--json", action="store_true")

    p_diff = sub.add_parser("diff", help="二つの作品フォルダの層ごとの差分")
    p_diff.add_argument("a", help="A（元など）。フォルダか番号（051）")
    p_diff.add_argument("b", help="B（改訂枝など）。フォルダか番号（051a）")
    p_diff.add_argument("--layer", default=",".join(DIFF_LAYERS), help=f"層（カンマ区切り。既定 {','.join(DIFF_LAYERS)}）")
    p_diff.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)
    root = repo_root()
    novels_root = (args.novels_dir or root / "novels").resolve()

    try:
        if args.command == "fork":
            trunk = resolve_work(args.source, novels_root)
            plan = build_fork_plan(
                trunk,
                novels_root=novels_root,
                scope=args.scope,
                reason=args.reason,
                branch=args.branch,
                title=args.title,
                includes=args.include,
            )
            if not args.apply:
                if args.json:
                    print(json.dumps({"dry_run": True, **plan.as_dict()}, ensure_ascii=False, indent=2))
                else:
                    print("dry-run（まだ何も作っていない）\n")
                    print_plan(plan, root)
                    print("\n作るときは同じ指定に --apply を付ける（--dry-run を付けていたら外す。--reason が要る）")
                return 0
            result = apply_fork(plan, novels_root=novels_root, note=args.note)
            if args.json:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                print(f"作りました: {result['target']}（{result['copied_files']} ファイル / {_human(result['copy_bytes'])}）")
                print(f"元の _meta.md: {result['trunk_meta']}")
                v = result["verify"]
                print("verify: " + ("OK" if v.get("ok") else "NG " + "; ".join(v.get("issues") or [])))
                for w in result["warnings"]:
                    print(f"WARNING: {w}")
            return 0 if result["verify"].get("ok") else 1

        if args.command == "list":
            code = None
            if args.target:
                code = nca.parse_folder_name(resolve_work(args.target, novels_root).name).code
            rows = list_branches(novels_root, code)
            if args.json:
                print(json.dumps(rows, ensure_ascii=False, indent=2))
            else:
                if not rows:
                    print("改訂枝はありません")
                for r in rows:
                    mark = "OK" if r["verify_ok"] else "NG"
                    reason = f" {r['branch_reason']}" if r["branch_reason"] else ""
                    print(f"  {r['role']:<4} {r['folder']}{reason}  verify {mark}")
                    for issue in (r["issues"] or []) if not r["verify_ok"] else []:
                        print(f"      - {issue}")
            return 0

        if args.command == "diff":
            a = resolve_work(args.a, novels_root)
            b = resolve_work(args.b, novels_root)
            layers = [x.strip() for x in args.layer.split(",") if x.strip()]
            data = diff_works(a, b, layers)
            if args.json:
                print(json.dumps(data, ensure_ascii=False, indent=2))
            else:
                print_diff(data, root)
            return 0
    except BranchError as error:
        print(f"error: {error.code}: {error}", file=sys.stderr)
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
