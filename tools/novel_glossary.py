#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
world.md の用語集（`## 用語` / `## 用語（承認待ち）`）を読み、構造と表記を照合する。

LLM / provider は呼ばず、作品ファイルを書き換えない。
照合するのは、用語集の構造（必須列・ID・名前の衝突）と、正式名称・許容表記・避ける表記の出現だけ。
名前のない規則、癖の規則への格上げ、定義の型と使い方のずれは機械では拾えない。
検出0件を「未定義概念なし」と報告しない（書き方と判定は _how_to.example/world_glossary.md）。

終了コード: 0 = 構造のエラーなし / 1 = 構造のエラーあり（--strict では避ける表記の出現も） / 2 = 作品フォルダや world.md が無い
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

FORMAL = "formal"
PENDING = "pending"
LEGACY = "legacy"

STANDARD = "standard"
MISSING = "missing"

FORM_LABEL = {STANDARD: "新しい形式", LEGACY: "旧形式（読取互換）", MISSING: "未整備"}

KINDS = frozenset({"場所", "組織", "制度", "技術", "現象", "物", "行為", "役職", "その他"})

COLUMNS = {
    "用語ID": "term_id",
    "正式名称": "name",
    "種別": "kind",
    "定義・適用範囲": "definition",
    "許容表記・略称": "allowed",
    "避ける表記": "avoid",
    "備考": "note",
}
REQUIRED_COLUMNS = ("正式名称", "定義・適用範囲")

SCAN_DEFAULT = ("world.md", "character.md", "design_specification.md", "proposal.md")

_RE_HEADING = re.compile(r"^(#{2,4})\s+(.+?)\s*$")
_RE_NUM_PREFIX = re.compile(r"^(?:\d+(?:\.\d+)*[.\s　]+)")
_RE_SEPARATOR = re.compile(r":?-{2,}:?")
_RE_TRAILING_NOTE = re.compile(r"[（(][^）)]*[）)]\s*$")
_RE_BULLET = re.compile(
    r"^\s*[-*]\s+(?:\*\*(?P<bold>[^*]+?)\*\*\s*[:：]|\*\*(?P<boldin>[^*]+?)[:：]\*\*|(?P<plain>[^:：*]+?)\s*[:：])"
    r"\s*(?P<definition>.*)$"
)
_RE_FORMAL_ID = re.compile(r"^term_\d+$")
_RE_PENDING_ID = re.compile(r"^term_p\d+$")
_EMPTY = frozenset({"", "―", "-", "—", "ー", "なし"})
_PENDING_TITLES = frozenset({"用語（承認待ち）", "用語(承認待ち)"})

NOT_PROOF = (
    "機械の照合が0件でも、未定義概念が無いとは言えません。名前のない規則・癖の格上げ・定義の型のずれは"
    "文脈レビューで確かめます（_how_to.example/world_glossary.md §5）。"
)


@dataclass
class Term:
    name: str
    definition: str
    section: str
    line: int
    term_id: str = ""
    kind: str = ""
    allowed: list[str] = field(default_factory=list)
    avoid: list[str] = field(default_factory=list)
    note: str = ""

    @property
    def surfaces(self) -> list[str]:
        return [self.name, *self.allowed]


@dataclass
class Issue:
    level: str  # error / warning
    code: str
    message: str
    line: int | None = None


@dataclass
class Section:
    kind: str
    title: str
    start: int  # 見出しの行（1始まり）
    end: int  # 次の同格以上の見出しの行（含まない）


@dataclass
class Glossary:
    form: str
    sections: list[Section] = field(default_factory=list)
    terms: list[Term] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)
    text: str = ""
    missing_columns: set[tuple[str, str]] = field(default_factory=set)  # (節の種類, 列名)

    def by_section(self, kind: str) -> list[Term]:
        return [t for t in self.terms if t.section == kind]

    def defined_terms(self) -> list[Term]:
        """正式な用語（新しい形式）または旧形式の用語。承認待ちは定義済みに数えない。"""
        return [t for t in self.terms if t.section in (FORMAL, LEGACY)]

    def in_glossary(self, line_no: int) -> bool:
        return any(s.start <= line_no < s.end for s in self.sections if s.kind != LEGACY or self.form == LEGACY)

    def section_text(self) -> str:
        lines = self.text.splitlines()
        return "\n".join(
            "\n".join(lines[s.start - 1 : s.end - 1]) for s in self.sections if s.kind in (FORMAL, PENDING)
        )


@dataclass
class Hit:
    file: str
    line: int
    text: str
    term_id: str
    term_name: str
    context: str


@dataclass
class Candidate:
    file: str
    line: int
    text: str
    in_setting: bool


@dataclass
class Report:
    novel: str
    error: str | None = None
    glossary: Glossary | None = None
    scanned: list[str] = field(default_factory=list)
    avoid_hits: list[Hit] = field(default_factory=list)
    usage: dict[str, dict[str, int]] = field(default_factory=dict)
    katakana: list[Candidate] = field(default_factory=list)
    hashes: dict[str, str] = field(default_factory=dict)

    def exit_code(self, strict: bool = False) -> int:
        if self.error:
            return 2
        assert self.glossary is not None
        if any(i.level == "error" for i in self.glossary.issues):
            return 1
        return 1 if strict and self.avoid_hits else 0


# ── 用語集の読込 ─────────────────────────────────────────────────────


def section_kind(title: str) -> str | None:
    """見出しの文字列から用語集の節の種類を返す。用語集でなければ None。"""
    plain = _RE_NUM_PREFIX.sub("", title.strip()).strip()
    if plain == "用語":
        return FORMAL
    if plain in _PENDING_TITLES:
        return PENDING
    if "用語" in plain:
        return LEGACY
    return None


def _sections(lines: list[str]) -> list[Section]:
    headings = []
    for i, line in enumerate(lines, start=1):
        m = _RE_HEADING.match(line)
        if m:
            headings.append((i, len(m.group(1)), m.group(2)))
    out = []
    for idx, (line_no, level, title) in enumerate(headings):
        kind = section_kind(title)
        if kind is None:
            continue
        end = len(lines) + 1
        for next_line, next_level, _ in headings[idx + 1 :]:
            if next_level <= level:
                end = next_line
                break
        out.append(Section(kind, title, line_no, end))
    return out


def _cells(line: str) -> list[str] | None:
    stripped = line.strip()
    if not stripped.startswith("|"):
        return None
    return [c.strip() for c in stripped.strip("|").split("|")]


def _is_separator(cells: list[str]) -> bool:
    return all(_RE_SEPARATOR.fullmatch(c) for c in cells if c) and any(cells)


def _value(text: str) -> str:
    return "" if text.strip() in _EMPTY else text.strip()


def _surface_list(text: str) -> list[str]:
    out = []
    for part in re.split(r"[、,]", _value(text)):
        part = _RE_TRAILING_NOTE.sub("", part.strip()).strip()
        if part and part not in _EMPTY:
            out.append(part)
    return out


def _has_standard_table(lines: list[str], section: Section) -> bool:
    """`正式名称` の列を持つ表があれば新しい形式。`## 用語` でも箇条書きや2列の表なら旧形式。"""
    for line_no in range(section.start + 1, section.end):
        cells = _cells(lines[line_no - 1])
        if cells is not None and not _is_separator(cells):
            return "正式名称" in cells
    return False


def _parse_standard(lines: list[str], section: Section, glossary: Glossary) -> list[Term]:
    issues = glossary.issues
    header: list[str] | None = None
    terms: list[Term] = []
    for line_no in range(section.start + 1, section.end):
        cells = _cells(lines[line_no - 1])
        if cells is None:
            continue
        if _is_separator(cells):
            continue
        if header is None:
            header = cells
            missing = [c for c in REQUIRED_COLUMNS if c not in header]
            if missing:
                issues.append(Issue("error", "missing_column", f"{section.title}: 必須の列がない: {'、'.join(missing)}", line_no))
                return terms
            for absent in ("用語ID", "種別"):
                if absent not in header:
                    glossary.missing_columns.add((section.kind, absent))
                    issues.append(Issue("warning", "missing_column", f"{section.title}: {absent} の列がない", line_no))
            continue
        row = {COLUMNS[h]: (cells[i] if i < len(cells) else "") for i, h in enumerate(header) if h in COLUMNS}
        if not any(_value(v) for v in row.values()):
            continue
        terms.append(
            Term(
                name=_value(row.get("name", "")),
                definition=_value(row.get("definition", "")),
                section=section.kind,
                line=line_no,
                term_id=_value(row.get("term_id", "")),
                kind=_value(row.get("kind", "")),
                allowed=_surface_list(row.get("allowed", "")),
                avoid=_surface_list(row.get("avoid", "")),
                note=_value(row.get("note", "")),
            )
        )
    if header is None:
        issues.append(Issue("error", "no_table", f"{section.title}: 表がない", section.start))
    return terms


def _parse_legacy(lines: list[str], section: Section) -> list[Term]:
    terms: list[Term] = []
    in_table = False
    sub: tuple[str, int] | None = None
    sub_body: list[str] = []

    def flush_sub() -> None:
        if sub is not None:
            terms.append(Term(sub[0], " ".join(sub_body).strip(), LEGACY, sub[1]))

    for line_no in range(section.start + 1, section.end):
        line = lines[line_no - 1]
        heading = _RE_HEADING.match(line)
        if heading:
            flush_sub()
            sub, sub_body = (_RE_NUM_PREFIX.sub("", heading.group(2)).strip(), line_no), []
            continue
        cells = _cells(line)
        if cells is not None:
            if _is_separator(cells):
                in_table = True
                continue
            if not in_table:
                continue  # 表の見出し行
            if cells and _value(cells[0]):
                terms.append(Term(cells[0], _value(cells[1]) if len(cells) > 1 else "", LEGACY, line_no))
            continue
        in_table = False
        bullet = _RE_BULLET.match(line)
        if bullet and sub is None:
            raw = (bullet.group("bold") or bullet.group("boldin") or bullet.group("plain") or "").strip()
            for name in re.split(r"\s*[/／]\s*", raw):
                if name:
                    terms.append(Term(name, bullet.group("definition").strip(), LEGACY, line_no))
            continue
        if sub is not None and line.strip():
            sub_body.append(line.strip())
    flush_sub()
    return terms


def parse_glossary(text: str) -> Glossary:
    lines = text.splitlines()
    sections = _sections(lines)
    for section in sections:
        if section.kind == FORMAL and not _has_standard_table(lines, section):
            section.kind = LEGACY
    kinds = {s.kind for s in sections}
    if FORMAL in kinds or PENDING in kinds:
        form = STANDARD
    elif LEGACY in kinds:
        form = LEGACY
    else:
        return Glossary(MISSING, text=text, issues=[Issue("error", "no_glossary", "用語集（## 用語）がない。未整備として扱う")])

    glossary = Glossary(form, sections, text=text)
    for section in sections:
        if form == STANDARD and section.kind == LEGACY:
            glossary.issues.append(
                Issue("warning", "legacy_ignored", f"{section.title}: 新しい形式の ## 用語 があるので、旧形式の節は読まない", section.start)
            )
            continue
        if section.kind == LEGACY:
            glossary.terms.extend(_parse_legacy(lines, section))
        else:
            glossary.terms.extend(_parse_standard(lines, section, glossary))
    if form == STANDARD and FORMAL not in kinds:
        glossary.issues.append(Issue("error", "no_formal", "## 用語（承認待ち）だけがあり、正式な ## 用語 がない"))
    glossary.issues.extend(check_structure(glossary))
    return glossary


# ── 構造の検査 ───────────────────────────────────────────────────────


def check_structure(glossary: Glossary) -> list[Issue]:
    issues: list[Issue] = []
    names: dict[str, Term] = {}
    surfaces: dict[str, Term] = {}
    ids: dict[str, Term] = {}
    for term in glossary.terms:
        if not term.name:
            issues.append(Issue("error", "empty_name", "正式名称が空", term.line))
            continue
        if not term.definition:
            level = "warning" if term.section == LEGACY else "error"
            issues.append(Issue(level, "empty_definition", f"{term.name}: 定義が空", term.line))
        if term.name in names:
            first = names[term.name]
            code = "pending_duplicates_formal" if {first.section, term.section} == {FORMAL, PENDING} else "duplicate_name"
            level = "warning" if term.section == LEGACY else "error"
            issues.append(Issue(level, code, f"{term.name}: 名前が重複（{first.line}行目）", term.line))
        names.setdefault(term.name, term)
        if term.section == LEGACY:
            continue
        if not term.term_id:
            if (term.section, "用語ID") not in glossary.missing_columns:
                issues.append(Issue("warning", "missing_id", f"{term.name}: 用語ID が空", term.line))
        else:
            pattern = _RE_PENDING_ID if term.section == PENDING else _RE_FORMAL_ID
            if not pattern.match(term.term_id):
                expected = "term_pNNN" if term.section == PENDING else "term_NNN"
                issues.append(Issue("warning", "id_pattern", f"{term.term_id}: {expected} の形ではない", term.line))
            if term.term_id in ids:
                issues.append(Issue("error", "duplicate_id", f"{term.term_id}: ID が重複（{ids[term.term_id].line}行目）", term.line))
            ids.setdefault(term.term_id, term)
        if not term.kind:
            if (term.section, "種別") not in glossary.missing_columns:
                issues.append(Issue("warning", "missing_kind", f"{term.name}: 種別が空", term.line))
        elif term.kind not in KINDS:
            issues.append(Issue("warning", "unknown_kind", f"{term.name}: 種別「{term.kind}」は {'・'.join(sorted(KINDS))} にない", term.line))
        for alias in term.allowed:
            other = surfaces.get(alias)
            if other is not None and other is not term:
                issues.append(Issue("warning", "shared_alias", f"{alias}: {other.name} と {term.name} の両方を指す。備考に使い分けを書く", term.line))
        for surface in term.surfaces:
            surfaces.setdefault(surface, term)
    for term in glossary.terms:
        for word in term.avoid:
            owner = surfaces.get(word)
            if owner is not None:
                issues.append(Issue("error", "avoid_conflict", f"{word}: {term.name} の避ける表記が、{owner.name} の名前・許容表記と同じ", term.line))
    return issues


# ── 表記の照合 ───────────────────────────────────────────────────────


def _claim(line: str, words: list[tuple[str, Term]]) -> list[tuple[int, int, str, Term]]:
    """長い語から先に、重ならない出現位置を取る。"""
    taken: list[tuple[int, int, str, Term]] = []
    for word, term in sorted(words, key=lambda item: -len(item[0])):
        start = line.find(word)
        while start != -1:
            end = start + len(word)
            if not any(s < end and start < e for s, e, _, _ in taken):
                taken.append((start, end, word, term))
            start = line.find(word, start + 1)
    return taken


def scan_file(glossary: Glossary, rel: str, text: str, usage: dict[str, dict[str, int]]) -> list[Hit]:
    registered = [(s, t) for t in glossary.terms for s in t.surfaces if len(s) >= 2]
    avoid = [(w, t) for t in glossary.terms for w in t.avoid]
    hits: list[Hit] = []
    skip_glossary = rel == "world.md"
    for line_no, line in enumerate(text.splitlines(), start=1):
        if skip_glossary and glossary.in_glossary(line_no):
            continue
        claimed = _claim(line, registered)
        for _, _, _, term in claimed:
            key = term.term_id or term.name
            usage.setdefault(key, {})
            usage[key][rel] = usage[key].get(rel, 0) + 1
        for start, end, word, term in _claim(line, avoid):
            if any(s <= start and end <= e for s, e, _, _ in claimed):
                continue  # 登録した長い語の一部
            hits.append(Hit(rel, line_no, word, term.term_id, term.name, line.strip()[:80]))
    return hits


def katakana_candidates(glossary: Glossary, rel: str, text: str, setting_text: str) -> list[Candidate]:
    """カタカナの未登録候補（確度低）。ai_writer.entities の規則を流用する。"""
    from ai_writer.entities import extract_candidates

    surfaces = [s for t in glossary.terms for s in t.surfaces]
    out = []
    seen: set[str] = set()
    for c in extract_candidates(text):
        if c.kind != "katakana" or c.text in seen:
            continue
        if any(c.text in s or s in c.text for s in surfaces):
            continue
        seen.add(c.text)
        out.append(Candidate(rel, text.count("\n", 0, c.start) + 1, c.text, c.text in setting_text))
    return out


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def default_files(work: Path) -> list[str]:
    files = [name for name in SCAN_DEFAULT if (work / name).is_file()]
    text_dir = work / "_novel_text"
    if text_dir.is_dir():
        files.extend(f"_novel_text/{p.name}" for p in sorted(text_dir.glob("novel_text*.md")))
    return files


def check_novel(work: Path, files: list[str] | None = None, *, katakana: bool = False) -> Report:
    report = Report(str(work))
    if not work.is_dir():
        report.error = f"作品フォルダがない: {work}"
        return report
    world = work / "world.md"
    if not world.is_file():
        report.error = "world.md がない"
        return report
    world_text = world.read_text(encoding="utf-8")
    glossary = parse_glossary(world_text)
    report.glossary = glossary
    report.hashes["world.md#用語"] = _sha256(glossary.section_text())
    setting_text = world_text + "".join(
        (work / n).read_text(encoding="utf-8") for n in ("character.md",) if (work / n).is_file()
    )
    for rel in files or default_files(work):
        path = work / rel
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        report.scanned.append(rel)
        report.hashes[rel] = _sha256(text)
        if glossary.form == MISSING:
            continue
        report.avoid_hits.extend(scan_file(glossary, rel, text, report.usage))
        if katakana and rel.startswith("_novel_text/"):
            report.katakana.extend(katakana_candidates(glossary, rel, text, setting_text))
    return report


# ── 出力 ─────────────────────────────────────────────────────────────


def render_text(report: Report) -> str:
    if report.error:
        return f"[ERROR] {report.error}"
    glossary = report.glossary
    assert glossary is not None
    lines = [f"作品: {report.novel}"]
    if glossary.form == STANDARD:
        lines.append(
            f"用語集: {FORM_LABEL[STANDARD]}（正式 {len(glossary.by_section(FORMAL))} / 承認待ち {len(glossary.by_section(PENDING))}）"
        )
    elif glossary.form == LEGACY:
        lines.append(f"用語集: {FORM_LABEL[LEGACY]}（{len(glossary.terms)} 語。許容表記・避ける表記は照合しない）")
    else:
        lines.append(f"用語集: {FORM_LABEL[MISSING]}（照合は未実施。検出0件とは扱わない）")
    lines.append(f"対象: {', '.join(report.scanned) or '（なし）'}")

    errors = [i for i in glossary.issues if i.level == "error"]
    warnings = [i for i in glossary.issues if i.level == "warning"]
    lines.append(f"構造: error {len(errors)} / warning {len(warnings)}")
    for issue in errors + warnings:
        where = f"world.md:{issue.line} " if issue.line else ""
        lines.append(f"  - [{issue.level}] {where}{issue.code}: {issue.message}")

    lines.append(f"避ける表記の出現: {len(report.avoid_hits)} 件")
    for hit in report.avoid_hits:
        target = f"{hit.term_name}（{hit.term_id}）" if hit.term_id else hit.term_name
        lines.append(f"  - {hit.file}:{hit.line} 「{hit.text}」→ {target}｜{hit.context}")

    pending = [t for t in glossary.by_section(PENDING) if t.term_id in report.usage or t.name in report.usage]
    if pending:
        lines.append("承認待ちの語の使用（宣言した新語）:")
        for term in pending:
            counts = report.usage.get(term.term_id or term.name, {})
            lines.append(f"  - {term.name}（{term.term_id}）: " + "、".join(f"{f} ×{n}" for f, n in counts.items()))
    unused = [t for t in glossary.defined_terms() if (t.term_id or t.name) not in report.usage]
    if unused and glossary.form == STANDARD:
        lines.append("対象に出てこない正式な用語: " + "、".join(t.name for t in unused))

    if report.katakana:
        lines.append(f"カタカナの未登録候補（確度低）: {len(report.katakana)} 件")
        for c in report.katakana:
            note = "設定資料にあり" if c.in_setting else "設定資料になし"
            lines.append(f"  - {c.file}:{c.line} {c.text}（{note}）")
    lines.append(NOT_PROOF)
    return "\n".join(lines)


def to_payload(report: Report, strict: bool = False) -> dict:
    glossary = report.glossary
    return {
        "novel": report.novel,
        "error": report.error,
        "form": glossary.form if glossary else None,
        "terms": [asdict(t) for t in glossary.terms] if glossary else [],
        "issues": [asdict(i) for i in glossary.issues] if glossary else [],
        "scanned": report.scanned,
        "avoid_hits": [asdict(h) for h in report.avoid_hits],
        "usage": report.usage,
        "katakana": [asdict(c) for c in report.katakana],
        "hashes": report.hashes,
        "note": NOT_PROOF,
        "exit_code": report.exit_code(strict),
    }


def main(argv: list[str] | None = None) -> int:
    from console_io import configure_stdio_utf8

    configure_stdio_utf8()
    parser = argparse.ArgumentParser(description="world.md の用語集の構造と、本文・設定の表記を照合する（書き換えない）")
    parser.add_argument("novel", type=Path, help="作品フォルダ")
    parser.add_argument("--files", nargs="+", help="照合するファイル（作品フォルダからの相対。既定: 設定3点・企画書・本文全章）")
    parser.add_argument("--katakana", action="store_true", help="本文のカタカナの未登録候補も出す（確度低）")
    parser.add_argument("--strict", action="store_true", help="避ける表記の出現も終了コード 1 にする")
    parser.add_argument("--json", action="store_true", help="JSON で出す")
    args = parser.parse_args(argv)

    report = check_novel(args.novel, args.files, katakana=args.katakana)
    if args.json:
        print(json.dumps(to_payload(report, args.strict), ensure_ascii=False, indent=2))
    else:
        print(render_text(report))
    return report.exit_code(args.strict)


if __name__ == "__main__":
    sys.exit(main())
