#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
設計書・企画書の人物名・地名候補が character.md / world.md に定義されているか照合する。

LLM / provider は呼ばず、作品ファイルを書き換えない。
地の文の一語は拾わない。見出し・Mermaid・読み付き・姓名の分かちだけを候補にする。

終了コード: 0 = 未定義なし / 1 = 未定義あり / 2 = 作品フォルダや必須資料が無い

運用: Gate A の必須にはしない。設定監査の任意前処理。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

SCAN_DEFAULT = ("design_specification.md", "proposal.md")
REQUIRED_DEFS = ("character.md", "world.md")

GENERIC_HEADINGS = frozenset(
    {
        "備考",
        "設定メモ",
        "用語集",
        "世界観概要",
        "設計ダイヤル",
        "地理",
        "地理・自然環境",
        "迷宮の法則（禁止と制約）",
        "迷宮の法則",
        "生態系",
        "社会・経済",
        "社会構造・政治・勢力関係",
        "システム（無いもの）",
        "システム",
        "用語",
        "基本情報",
        "作品基本情報",
        "ログライン",
        "あらすじ",
        "分類",
        "キャラクター紹介",
        "登場人物紹介",
        "作品の魅力",
        "作品の3つの魅力",
        "ストーリー相関図",
        "テーマ",
        "コンセプト",
    }
)

STRUCTURAL_HEADING = re.compile(
    r"(?:^第?\d+\s*章|プロローグ|作品基本|ログライン|あらすじ|キャラクター紹介|"
    r"登場人物紹介|作品の魅力|作品の3つの魅力|分類|テーマ|コンセプト|"
    r"章構成|ストーリー構成|必須構成|作者用|相関図|執筆スケジュール)"
)

KATA_DENY = frozenset(
    {
        "ファイン",
        "カーボン",
        "シール",
        "メカニカル",
        "リビング",
        "ベッド",
        "ゾーン",
        "ランプ",
        "ヒーター",
        "ポンプ",
        "セラミック",
        "アルミ",
        "ストレステスト",
        "フラックス",
        "シリカ",
        "ミスリル",
        "プロローグ",
    }
)

GENERIC_LABEL = re.compile(
    r"(村人|農民|領民|工夫|相場|法則|帰還|地上の門|パーティ|地域社会|"
    r"^地上$|^坑内$|^門$|^税$|^灯穴坑の|"
    r"相関図|必須構成要素)"
)

_RE_HEADING = re.compile(r"^(#{2,3})\s+(.+?)\s*$")
_RE_NUM_PREFIX = re.compile(r"^(?:\d+(?:\.\d+)*[.\s　]+)")
_RE_ANNOTATED = re.compile(
    r"([一-龯ァ-ヴー・ 　]{1,24})[（(]([^）)]{1,48})[）)]"
)
_RE_SPACED_KANJI = re.compile(r"[一-龯々〆ヵヶ]{1,4}[ 　][一-龯々〆ヵヶ]{1,3}")
_RE_KATA_COMPOUND = re.compile(r"[ァ-ヶー]{2,}(?:・[ァ-ヶー]{2,})+")
_RE_KATA_WORD = re.compile(r"[ァ-ヶー]{3,}")
_RE_READING_ONLY = re.compile(r"^[\sぁ-んァ-ヶーA-Za-z・/]+$")
_RE_FIELD_NAME = re.compile(r"^\s*-\s*\*\*(名前|世界名|地名|舞台|都市)\*\*\s*[:：]\s*(.+)$")
_RE_MERMAID_NODE = re.compile(
    r'(?:^|[\s;])[A-Za-z][A-Za-z0-9_]*\s*\[\s*(?:"([^"]+)"|([^\]\n]+))\s*\]'
)
_RE_SUBGRAPH = re.compile(r"^\s*subgraph\s+(.+?)\s*$")
_RE_QUOTE = re.compile(r"『([^』]{1,40})』")
_RE_PLACE_SUFFIX = re.compile(
    r"(王国|辺境伯領|辺境伯家|侯爵家|伯領|伯家|廃工房|辺境工房|工房|"
    r"ギルド|組合|山脈|鉱山|大陸|領都|領|市|坑)$"
)
_RE_PLACE_FROM_PROSE = re.compile(
    r"[ァ-ヶー一-龯]{2,20}(?:"
    r"王国|辺境伯領|辺境伯家|侯爵家|伯領|伯家|廃工房|辺境工房|工房|"
    r"ギルド|組合|山脈|鉱山|大陸|領都|市|坑)"
)
_RE_TABLE_ROW = re.compile(r"^\s*\|(.+)\|\s*$")


@dataclass
class NameRecord:
    kind: str
    canonical: str
    aliases: list[str]
    source: str


@dataclass
class Mention:
    text: str
    kind: str
    source_file: str
    line: int
    extractor: str


@dataclass
class Finding:
    text: str
    kind: str
    source_file: str
    line: int
    extractor: str
    reason: str = "undefined"


@dataclass
class LintResult:
    novel: str
    findings: list[Finding] = field(default_factory=list)
    defined_people: list[str] = field(default_factory=list)
    defined_places: list[str] = field(default_factory=list)
    scanned: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def exit_code(self) -> int:
        if self.error:
            return 2
        return 1 if self.findings else 0


def normalize(text: str) -> str:
    out = text.replace(" ", "").replace("　", "").replace("・", "")
    out = out.replace("ヴ", "ゔ")
    return out.casefold()


def looks_like_reading(text: str) -> bool:
    return bool(_RE_READING_ONLY.fullmatch(text.strip()))


def split_name_parts(name: str) -> list[str]:
    parts: list[str] = []
    for chunk in re.split(r"[ 　・/／]+", name.strip()):
        chunk = chunk.strip()
        if len(chunk) >= 1:
            parts.append(chunk)
    return parts


def aliases_from_raw(raw: str) -> set[str]:
    text = raw.strip().strip("*").strip("\"'")
    if not text:
        return set()
    aliases: set[str] = {text, text.replace(" ", "").replace("　", "")}
    m = _RE_ANNOTATED.fullmatch(text)
    if m:
        core, reading = m.group(1).strip(), m.group(2).strip()
        aliases.add(core)
        aliases.update(split_name_parts(core))
        if looks_like_reading(reading):
            for part in re.split(r"[/／]", reading):
                aliases.add(part.strip())
                aliases.update(split_name_parts(part))
        elif "前世" in reading or "：" in reading or ":" in reading:
            rest = re.sub(r"^[^：:]*[：:]", "", reading).strip()
            aliases.update(aliases_from_raw(rest))
    else:
        aliases.update(split_name_parts(text))
        for m in _RE_ANNOTATED.finditer(text):
            aliases.update(aliases_from_raw(m.group(0)))
    cleaned = {a.strip() for a in aliases if a and a.strip() and a.strip() not in {"前世"}}
    return cleaned


def heading_title(raw: str) -> str:
    title = _RE_NUM_PREFIX.sub("", raw.strip())
    title = re.sub(r"[（(][^）)]+[）)]\s*$", "", title).strip()
    return title or raw.strip()


def add_record(records: list[NameRecord], kind: str, raw: str, source: str) -> None:
    aliases = {a for a in aliases_from_raw(raw) if a}
    if not aliases:
        return
    canonical = heading_title(raw) or raw.strip()
    existing = next((r for r in records if r.kind == kind and r.canonical == canonical), None)
    if existing:
        merged = set(existing.aliases) | aliases
        existing.aliases = sorted(merged, key=len, reverse=True)
        return
    records.append(
        NameRecord(
            kind=kind,
            canonical=canonical,
            aliases=sorted(aliases, key=len, reverse=True),
            source=source,
        )
    )


def parse_character_defs(text: str, filename: str = "character.md") -> list[NameRecord]:
    records: list[NameRecord] = []
    current: str | None = None
    for i, line in enumerate(text.splitlines(), start=1):
        hm = _RE_HEADING.match(line)
        if hm and hm.group(1) == "##":
            title = hm.group(2).strip()
            if title in GENERIC_HEADINGS:
                current = None
                continue
            current = title
            add_record(records, "person", title, f"{filename}:{i}")
            continue
        if current is None:
            continue
        fm = _RE_FIELD_NAME.match(line)
        if fm and fm.group(1) == "名前":
            add_record(records, "person", fm.group(2).strip(), f"{filename}:{i}")
    return records


def _table_cells(line: str) -> list[str]:
    if not _RE_TABLE_ROW.match(line):
        return []
    return [c.strip() for c in line.strip().strip("|").split("|")]


def parse_world_defs(text: str, filename: str = "world.md") -> list[NameRecord]:
    records: list[NameRecord] = []
    in_terms = False
    header_seen = False
    for i, line in enumerate(text.splitlines(), start=1):
        hm = _RE_HEADING.match(line)
        if hm:
            raw = hm.group(2).strip()
            title = heading_title(raw)
            in_terms = title == "用語" or raw.endswith("用語")
            header_seen = False
            if title not in GENERIC_HEADINGS and not in_terms:
                add_record(records, "place", title, f"{filename}:{i}")
                add_record(records, "place", raw, f"{filename}:{i}")
            continue
        fm = _RE_FIELD_NAME.match(line)
        if fm and fm.group(1) != "名前":
            value = fm.group(2)
            for chunk in re.split(r"[と、,]", value):
                chunk = re.sub(r"その直下の", "", chunk)
                chunk = chunk.strip(" 。")
                if chunk:
                    add_record(records, "place", chunk, f"{filename}:{i}")
            continue
        for quoted in _RE_QUOTE.findall(line):
            add_record(records, "place", quoted, f"{filename}:{i}")
        if in_terms:
            cells = _table_cells(line)
            if not cells:
                continue
            if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
                continue
            if cells[0] in {"用語", "意味"}:
                header_seen = True
                continue
            if header_seen or cells[0]:
                add_record(records, "place", cells[0], f"{filename}:{i}")
    for i, line in enumerate(text.splitlines(), start=1):
        if line.startswith("#"):
            continue
        for m in _RE_PLACE_FROM_PROSE.finditer(line):
            add_record(records, "place", m.group(0), f"{filename}:{i}")
    return records


def first_mermaid_label(label: str) -> str:
    text = label.replace("<br/>", "<br>").replace("<br />", "<br>")
    return text.split("<br>")[0].strip()


def is_generic_label(text: str) -> bool:
    stripped = heading_title(text)
    return bool(GENERIC_LABEL.search(stripped) or GENERIC_LABEL.search(text))


def is_structural_heading(text: str) -> bool:
    title = heading_title(_RE_NUM_PREFIX.sub("", text.strip()))
    return bool(
        text.strip() in GENERIC_HEADINGS
        or title in GENERIC_HEADINGS
        or STRUCTURAL_HEADING.search(text)
        or STRUCTURAL_HEADING.search(title)
    )


def name_core_ok(name: str) -> bool:
    n = name.strip()
    if len(n) < 2 or len(n) > 16:
        return False
    if n in {"章", "項", "節"}:
        return False
    if re.search(r"[をがにではへとやも、。：:]", n):
        return False
    if "章" in n or n.startswith("第"):
        return False
    return True


def kata_name_ok(text: str) -> bool:
    parts = [p for p in text.split("・") if p]
    if len(parts) < 2:
        return False
    for part in parts:
        if not (3 <= len(part) <= 8):
            return False
        if any(deny in part for deny in KATA_DENY):
            return False
    return True


def person_shaped(text: str) -> bool:
    title = heading_title(text)
    if _RE_SPACED_KANJI.fullmatch(title) or _RE_KATA_COMPOUND.fullmatch(title):
        return True
    m = _RE_ANNOTATED.fullmatch(text.strip()) or _RE_ANNOTATED.fullmatch(title)
    if m and looks_like_reading(m.group(2)) and name_core_ok(m.group(1)):
        return True
    return bool(_RE_KATA_WORD.fullmatch(title) and title not in KATA_DENY)


def place_shaped(text: str) -> bool:
    title = heading_title(text)
    return bool(_RE_PLACE_SUFFIX.search(title) or _RE_PLACE_FROM_PROSE.fullmatch(title))


def mentions_from_line(line: str, source_file: str, line_no: int, *, mermaid: bool) -> list[Mention]:
    found: list[Mention] = []
    seen: set[str] = set()

    def add(text: str, kind: str, extractor: str) -> None:
        text = text.strip().strip("\"'")
        if not text or is_generic_label(text):
            return
        key = f"{kind}:{normalize(text)}:{extractor}"
        if key in seen:
            return
        seen.add(key)
        found.append(
            Mention(
                text=text,
                kind=kind,
                source_file=source_file,
                line=line_no,
                extractor=extractor,
            )
        )

    hm = _RE_HEADING.match(line)
    if hm:
        raw = hm.group(2).strip()
        if not is_structural_heading(raw) and not is_generic_label(raw):
            if person_shaped(raw):
                add(raw, "person", "heading")
            elif place_shaped(raw):
                add(raw, "place", "heading")

    if mermaid:
        sm = _RE_SUBGRAPH.match(line)
        if sm:
            raw = sm.group(1).strip().strip("\"'")
            if place_shaped(raw) or person_shaped(raw):
                add(raw, "place" if place_shaped(raw) else "person", "subgraph")
        for m in _RE_MERMAID_NODE.finditer(line):
            label = first_mermaid_label(m.group(1) or m.group(2) or "")
            if not label:
                continue
            bare = re.sub(r"[（(][^）)]+[）)]", "", label).strip()
            kata = _RE_KATA_COMPOUND.search(label)
            if person_shaped(label) or _RE_SPACED_KANJI.search(label) or (
                kata is not None and kata_name_ok(kata.group(0))
            ):
                add(label, "person", "mermaid")
            elif _RE_KATA_WORD.fullmatch(bare) and bare not in KATA_DENY:
                add(bare, "person", "mermaid")
            elif place_shaped(label):
                add(label, "place", "mermaid")

    for m in _RE_ANNOTATED.finditer(line):
        core, reading = m.group(1).strip(), m.group(2).strip()
        if not looks_like_reading(reading) or not name_core_ok(core):
            continue
        if any(deny in reading for deny in KATA_DENY):
            continue
        if re.fullmatch(r"[ァ-ヶー]{3,}", reading.strip()) and not person_shaped(core):
            continue
        add(m.group(0), "person", "reading")

    if not mermaid:
        for m in _RE_SPACED_KANJI.finditer(line):
            left, right = re.split(r"[ 　]", m.group(0), maxsplit=1)
            if left.startswith("第") or left.startswith("章"):
                continue
            add(m.group(0), "person", "spaced")
        for m in _RE_KATA_COMPOUND.finditer(line):
            if kata_name_ok(m.group(0)):
                add(m.group(0), "person", "kata")

    fm = _RE_FIELD_NAME.match(line)
    if fm:
        kind = "person" if fm.group(1) == "名前" else "place"
        add(fm.group(2).strip(), kind, "field")
    return found


def extract_mentions(text: str, source_file: str) -> list[Mention]:
    mentions: list[Mention] = []
    mermaid = False
    for i, line in enumerate(text.splitlines(), start=1):
        fence = line.strip()
        if fence.startswith("```"):
            lang = fence[3:].strip().lower()
            if not mermaid and lang.startswith("mermaid"):
                mermaid = True
            else:
                mermaid = False
            continue
        mentions.extend(mentions_from_line(line, source_file, i, mermaid=mermaid))
    return mentions


def _alias_stems(alias: str) -> list[str]:
    stems = [alias]
    rest = alias
    while True:
        stripped = _RE_PLACE_SUFFIX.sub("", rest)
        if stripped == rest or len(stripped) < 2:
            break
        stems.append(stripped)
        rest = stripped
    return stems


def covers(mention: str, records: list[NameRecord]) -> bool:
    mention_n = normalize(mention)
    if not mention_n:
        return False
    for rec in records:
        for alias in rec.aliases:
            alias_n = normalize(alias)
            if len(alias_n) < 2:
                continue
            if mention_n == alias_n or alias_n in mention_n or mention_n in alias_n:
                return True
            if rec.kind == "place":
                for stem in _alias_stems(alias):
                    stem_n = normalize(stem)
                    if len(stem_n) >= 2 and stem_n in mention_n:
                        return True
    return False


def lint_novel(novel_dir: Path, scan_names: tuple[str, ...] = SCAN_DEFAULT) -> LintResult:
    result = LintResult(novel=str(novel_dir))
    if not novel_dir.is_dir():
        result.error = f"作品フォルダがない: {novel_dir}"
        return result
    missing = [n for n in REQUIRED_DEFS if not (novel_dir / n).is_file()]
    if missing:
        result.error = f"定義資料がない: {', '.join(missing)}"
        return result

    people = parse_character_defs((novel_dir / "character.md").read_text(encoding="utf-8"))
    places = parse_world_defs((novel_dir / "world.md").read_text(encoding="utf-8"))
    result.defined_people = [r.canonical for r in people]
    result.defined_places = [r.canonical for r in places]
    lexicon = people + places

    for name in scan_names:
        path = novel_dir / name
        if not path.is_file():
            continue
        result.scanned.append(name)
        for mention in extract_mentions(path.read_text(encoding="utf-8"), name):
            if covers(mention.text, lexicon):
                continue
            result.findings.append(
                Finding(
                    text=mention.text,
                    kind=mention.kind,
                    source_file=mention.source_file,
                    line=mention.line,
                    extractor=mention.extractor,
                )
            )
    return result


def render_text(result: LintResult) -> str:
    if result.error:
        return f"[ERROR] {result.error}"
    lines = [
        f"作品: {result.novel}",
        f"定義: 人物 {len(result.defined_people)} / 地名・用語 {len(result.defined_places)}",
        f"対象: {', '.join(result.scanned) or '（スキャン対象なし）'}",
    ]
    if not result.findings:
        lines.append("[OK] 未定義の人物名・地名候補はありません")
        return "\n".join(lines)
    lines.append(f"[NG] 未定義 {len(result.findings)} 件")
    for f in result.findings:
        lines.append(f"  - {f.source_file}:{f.line} [{f.kind}/{f.extractor}] {f.text}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    from console_io import configure_stdio_utf8

    configure_stdio_utf8()
    parser = argparse.ArgumentParser(
        description="設計書・企画書の人物名・地名候補が character.md / world.md にあるか照合する"
    )
    parser.add_argument("novel", type=Path, help="作品フォルダ")
    parser.add_argument(
        "--scan",
        nargs="+",
        default=list(SCAN_DEFAULT),
        help="照合するファイル名（既定: design_specification.md proposal.md）",
    )
    parser.add_argument("--json", action="store_true", help="JSON で出す")
    args = parser.parse_args(argv)

    result = lint_novel(args.novel, tuple(args.scan))
    if args.json:
        payload = {
            "novel": result.novel,
            "error": result.error,
            "defined_people": result.defined_people,
            "defined_places": result.defined_places,
            "scanned": result.scanned,
            "findings": [asdict(f) for f in result.findings],
            "exit_code": result.exit_code,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(render_text(result))
    return result.exit_code


if __name__ == "__main__":
    sys.exit(main())
