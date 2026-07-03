#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
character.md の構造 lint。

人間向けの人物プロフィール本文を、_how_to のチェックリスト YAML に基づいて確認する。
見た目・画像生成の機械正本は tag/characters/*.yaml のまま扱い、本ツールは Plan 段階の
書き漏れ検出に絞る。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    print("error: PyYAML が必要です。pip install pyyaml", file=sys.stderr)
    raise


DEFAULT_CHECKLIST = Path("_how_to.example") / "character_checklist.yaml"
USER_CHECKLIST = Path("_how_to") / "character_checklist.yaml"
ENV_CHECKLIST = "MONOCRI_CHARACTER_CHECKLIST"


@dataclass
class Issue:
    level: str
    message: str
    character: str | None = None

    def to_dict(self) -> dict[str, str]:
        out = {"level": self.level, "message": self.message}
        if self.character:
            out["character"] = self.character
        return out


@dataclass
class FieldOccurrence:
    label: str
    canonical: str
    content: str
    children: list[str] = field(default_factory=list)
    source: str = "label"


@dataclass
class CharacterSection:
    heading: str
    start_line: int
    lines: list[str]
    fields: dict[str, FieldOccurrence] = field(default_factory=dict)
    raw_labels: list[str] = field(default_factory=list)


FIELD_HINTS = {
    "名前": "正式名。必要なら読み仮名も添える。",
    "年齢": "年齢・立場・所属など。",
    "性格": "基本気質、他者への接し方、緊張時に出る癖。",
    "一人称": "地の文・台詞で使う一人称。",
    "口調": "語尾、よく使う言い回し、感情が揺れた時の話し方。",
    "目標": "物語上で何を望み、何を達成したいか。",
    "外見": "髪・目・体格・肌・特徴・小物など、画像化でぶれやすい要素。",
    "外見の個性": "キャラクターを見分ける外見の核を3〜5点。Tag Mode 前の識別用。",
    "身長": "数値（例: 約135cm）または明確なサイズ感。兄妹・対比がある作品では特に必須。",
    "服装": "普段着、場面別衣装、制服・仕事着など。",
    "ボディーの特徴": "物語上重要な身体的特徴。作品の表現方針に合わせて必要範囲だけ書く。",
}


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"{path}: YAML ルートがオブジェクトではありません")
    return data


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in override.items():
        if (
            key in out
            and isinstance(out[key], dict)
            and isinstance(value, dict)
        ):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def resolve_path(raw: str, root: Path) -> Path:
    p = Path(raw)
    if not p.is_absolute():
        p = root / p
    return p.resolve()


def resolve_target(path: Path, root: Path) -> tuple[Path | None, Path]:
    p = path if path.is_absolute() else (root / path)
    p = p.resolve()
    if p.is_dir():
        return p, p / "character.md"
    return (p.parent if p.name == "character.md" else None), p


def resolve_checklist(root: Path, novel_dir: Path | None) -> tuple[dict[str, Any], list[str]]:
    sources: list[str] = []
    env_value = os.environ.get(ENV_CHECKLIST)
    if env_value:
        base_path = resolve_path(env_value, root)
    else:
        user_path = root / USER_CHECKLIST
        base_path = user_path if user_path.is_file() else root / DEFAULT_CHECKLIST

    if not base_path.is_file():
        raise FileNotFoundError(f"チェックリスト YAML が見つかりません: {base_path}")

    config = load_yaml(base_path)
    sources.append(str(base_path))

    if novel_dir:
        novel_path = novel_dir / "character_checklist.yaml"
        if novel_path.is_file():
            config = deep_merge(config, load_yaml(novel_path))
            sources.append(str(novel_path))

    return config, sources


def config_format(config: dict[str, Any]) -> dict[str, Any]:
    fmt = config.get("format") or {}
    if not isinstance(fmt, dict):
        fmt = {}
    merged = dict(fmt)
    for key in (
        "heading_required_pattern",
        "character_heading_pattern",
        "skip_headings",
        "table_policy",
    ):
        if key in config and key not in merged:
            merged[key] = config[key]
    return merged


def normalize_label(label: str) -> str:
    label = label.strip()
    label = re.sub(r"\s+", " ", label)
    return label.rstrip("：:")


def build_alias_map(config: dict[str, Any]) -> dict[str, str]:
    fields_cfg = config.get("fields") or {}
    alias_map: dict[str, str] = {}
    if isinstance(fields_cfg, dict):
        for canonical, spec in fields_cfg.items():
            canonical_s = normalize_label(str(canonical))
            alias_map[canonical_s] = canonical_s
            if isinstance(spec, dict):
                for alias in spec.get("aliases") or []:
                    alias_map[normalize_label(str(alias))] = canonical_s
    return alias_map


def canonicalize(label: str, alias_map: dict[str, str]) -> str:
    label = normalize_label(label)
    if label in alias_map:
        return alias_map[label]
    for alias, canonical in alias_map.items():
        if label == alias or label.startswith(alias + "（") or label.startswith(alias + "("):
            return canonical
    return label


def resolve_profile(config: dict[str, Any], profile: str) -> dict[str, Any]:
    profiles = config.get("profiles") or {}
    if not isinstance(profiles, dict) or profile not in profiles:
        known = ", ".join(sorted(profiles)) if isinstance(profiles, dict) else ""
        raise KeyError(f"profile が見つかりません: {profile}" + (f"（候補: {known}）" if known else ""))

    seen: set[str] = set()

    def visit(name: str) -> dict[str, Any]:
        if name in seen:
            raise ValueError(f"profile extends が循環しています: {name}")
        seen.add(name)
        spec = profiles.get(name)
        if not isinstance(spec, dict):
            raise ValueError(f"profiles.{name} はオブジェクトである必要があります")
        merged: dict[str, Any] = {"require_fields": [], "optional_fields": []}
        extends = spec.get("extends")
        parents: list[str]
        if isinstance(extends, str):
            parents = [extends]
        elif isinstance(extends, list):
            parents = [str(x) for x in extends]
        else:
            parents = []
        for parent in parents:
            merged = deep_merge(merged, visit(parent))
        for list_key in ("require_fields", "optional_fields"):
            values: list[str] = []
            for value in merged.get(list_key) or []:
                if str(value) not in values:
                    values.append(str(value))
            for value in spec.get(list_key) or []:
                if str(value) not in values:
                    values.append(str(value))
            merged[list_key] = values
        for key, value in spec.items():
            if key not in ("extends", "require_fields", "optional_fields"):
                merged[key] = value
        seen.remove(name)
        return merged

    return visit(profile)


def is_table_row(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("|") and stripped.endswith("|") and stripped.count("|") >= 2


def table_row_parts(line: str) -> list[str]:
    return [part.strip() for part in line.strip().strip("|").split("|")]


LABEL_RE = re.compile(r"^[-*]\s+\*\*(.+?)\*\*\s*[：:]\s*(.*)$")
CHILD_RE = re.compile(r"^\s+[-*]\s+(?:\*\*(.+?)\*\*|([^：:]+))\s*[：:]\s*(.*)$")
CHILD_BULLET_RE = re.compile(r"^\s+[-*]\s+(.+?)\s*$")
HEADING3_RE = re.compile(r"^\s*#{3,6}\s+(.+?)\s*$")


def collect_until(lines: list[str], start: int) -> str:
    chunks: list[str] = []
    for line in lines[start:]:
        if LABEL_RE.match(line) or HEADING3_RE.match(line) or line.startswith("## "):
            break
        if is_table_row(line):
            break
        chunks.append(line.strip())
    return "\n".join(x for x in chunks if x)


def collect_children(lines: list[str], start: int) -> list[str]:
    children: list[str] = []
    for line in lines[start:]:
        if LABEL_RE.match(line) or HEADING3_RE.match(line) or line.startswith("## "):
            break
        m = CHILD_RE.match(line)
        if m:
            children.append(normalize_label(m.group(1) or m.group(2) or ""))
            continue
        bm = CHILD_BULLET_RE.match(line)
        if bm:
            child_text = re.split(r"[。.!?、,]", bm.group(1).strip(), maxsplit=1)[0]
            children.append(normalize_label(child_text[:40]))
    return children


def add_field(
    section: CharacterSection,
    alias_map: dict[str, str],
    label: str,
    content: str,
    *,
    children: list[str] | None = None,
    source: str,
) -> None:
    raw = normalize_label(label)
    canonical = canonicalize(raw, alias_map)
    section.raw_labels.append(raw)
    current = section.fields.get(canonical)
    occ = FieldOccurrence(
        label=raw,
        canonical=canonical,
        content=content.strip(),
        children=children or [],
        source=source,
    )
    if current is None:
        section.fields[canonical] = occ
        return
    if len(occ.content) > len(current.content):
        current.content = occ.content
        current.label = occ.label
        current.source = occ.source
    for child in occ.children:
        if child not in current.children:
            current.children.append(child)


def parse_fields(section: CharacterSection, alias_map: dict[str, str]) -> None:
    lines = section.lines
    table_header_seen = False
    for index, line in enumerate(lines):
        m = LABEL_RE.match(line)
        if m:
            label, inline = m.group(1), m.group(2)
            rest = collect_until(lines, index + 1)
            content = "\n".join(x for x in (inline.strip(), rest) if x)
            add_field(
                section,
                alias_map,
                label,
                content,
                children=collect_children(lines, index + 1),
                source="label",
            )
            continue

        hm = HEADING3_RE.match(line)
        if hm:
            label = hm.group(1)
            content = collect_until(lines, index + 1)
            add_field(
                section,
                alias_map,
                label,
                content,
                children=collect_children(lines, index + 1),
                source="heading",
            )
            continue

        if is_table_row(line):
            parts = table_row_parts(line)
            if len(parts) < 2:
                continue
            if all(re.fullmatch(r"[-:\s]+", part) for part in parts):
                continue
            if parts[0] in {"項目", "ラベル", "field", "Field"}:
                table_header_seen = True
                continue
            if table_header_seen or len(parts) >= 2:
                add_field(section, alias_map, parts[0], parts[1], source="table")


def split_characters(
    text: str,
    *,
    character_heading_pattern: str,
    skip_headings: list[str],
) -> tuple[list[CharacterSection], list[Issue]]:
    issues: list[Issue] = []
    sections: list[CharacterSection] = []
    pattern = re.compile(character_heading_pattern)
    lines = text.splitlines()
    current: CharacterSection | None = None

    for line_no, line in enumerate(lines, start=1):
        if line.startswith("## "):
            heading = line[3:].strip()
            if heading in skip_headings:
                current = None
                continue
            if pattern.search(heading):
                current = CharacterSection(heading=heading, start_line=line_no, lines=[])
                sections.append(current)
            else:
                issues.append(Issue("WARN", f"キャラクター見出し候補ではないため読み飛ばしました: {heading}"))
                current = None
            continue
        if current is not None:
            current.lines.append(line)

    return sections, issues


def text_len(value: str) -> int:
    value = re.sub(r"[*_`#>|-]", "", value)
    value = re.sub(r"\s+", "", value)
    return len(value)


def field_spec(config: dict[str, Any], canonical: str) -> dict[str, Any]:
    fields = config.get("fields") or {}
    if isinstance(fields, dict) and isinstance(fields.get(canonical), dict):
        return fields[canonical]
    return {}


def field_hint(label: str) -> str:
    return FIELD_HINTS.get(label, "この人物について、物語上必要な情報を具体的に書く。")


def infer_gender(section: CharacterSection, config: dict[str, Any], alias_map: dict[str, str]) -> str | None:
    """gender_detection 設定から male / female を推定。不明なら None。"""
    gd = config.get("gender_detection")
    if not isinstance(gd, dict):
        return None
    field_name = canonicalize(str(gd.get("field") or "年齢"), alias_map)
    occ = section.fields.get(field_name)
    if not occ:
        return None
    haystack = f"{occ.content} {occ.label}"
    patterns = gd.get("patterns")
    if not isinstance(patterns, dict):
        return None
    matched: list[str] = []
    for gender_key in ("male", "female"):
        tokens = patterns.get(gender_key) or []
        if not isinstance(tokens, list):
            continue
        for token in tokens:
            if str(token) and str(token) in haystack:
                matched.append(gender_key)
                break
    if len(matched) == 1:
        return matched[0]
    if len(matched) > 1:
        return None
    return None


def normalize_child_label(label: str) -> str:
    return normalize_label(label)


def check_body_gender_rules(
    section: CharacterSection,
    config: dict[str, Any],
    alias_map: dict[str, str],
) -> list[Issue]:
    """body_gender_rules: 性別ごとのボディー子項目の必須・禁止。"""
    issues: list[Issue] = []
    rules = config.get("body_gender_rules")
    if not isinstance(rules, dict):
        return issues

    parent = canonicalize(str(rules.get("parent_field") or "ボディーの特徴"), alias_map)
    body = section.fields.get(parent)
    if not body:
        return issues

    gender = infer_gender(section, config, alias_map)
    if gender is None:
        issues.append(
            Issue(
                "WARN",
                "性別を推定できませんでした。年齢・立場に「男性」「女性」「若妖精」等を明記すると "
                "body_gender_rules の検証が有効になります。",
                section.heading,
            )
        )
        return issues

    gender_rules = rules.get(gender)
    if not isinstance(gender_rules, dict):
        return issues

    children = {normalize_child_label(c) for c in body.children}

    for label in gender_rules.get("require_child_labels") or []:
        child = normalize_child_label(str(label))
        if child not in children:
            issues.append(
                Issue(
                    "ERROR",
                    f"ボディーの特徴（{gender}）に必須の子項目がありません: {child}",
                    section.heading,
                )
            )

    for label in gender_rules.get("forbid_child_labels") or []:
        child = normalize_child_label(str(label))
        if child in children:
            issues.append(
                Issue(
                    "ERROR",
                    f"ボディーの特徴に {gender} 向けではない子項目があります: {child}",
                    section.heading,
                )
            )

    return issues


def missing_field_snippet(label: str) -> str:
    return f"- **{label}**: TODO（{field_hint(label)}）"


def section_table_conversion(section: CharacterSection) -> str | None:
    table_fields = [occ for occ in section.fields.values() if occ.source == "table"]
    if not table_fields:
        return None
    lines = [f"## {section.heading}"]
    for occ in table_fields:
        lines.append(f"- **{occ.label}**: {occ.content or 'TODO'}")
    return "\n".join(lines)


def build_suggestions(
    sections: list[CharacterSection],
    *,
    required_fields: list[str],
) -> list[dict[str, Any]]:
    suggestions: list[dict[str, Any]] = []
    for section in sections:
        missing = [label for label in required_fields if label not in section.fields]
        if missing:
            suggestions.append(
                {
                    "type": "missing_fields",
                    "character": section.heading,
                    "message": "必須項目の追記案です。TODO 部分を人物設定に合わせて書き換えてください。",
                    "markdown": "\n".join(missing_field_snippet(label) for label in missing),
                }
            )

        converted = section_table_conversion(section)
        if converted:
            suggestions.append(
                {
                    "type": "table_to_labels",
                    "character": section.heading,
                    "message": "表形式から `- **ラベル**:` 形式への変換案です。既存の小見出し・自由記述は残して統合してください。",
                    "markdown": converted,
                }
            )
    return suggestions


def check_character_file(
    character_md: Path,
    *,
    novel_dir: Path | None = None,
    profile: str = "plan",
    strict: bool = False,
    suggest: bool = False,
    root: Path | None = None,
) -> dict[str, Any]:
    root = root or repo_root()
    config, config_sources = resolve_checklist(root, novel_dir)
    fmt = config_format(config)
    heading_required_pattern = str(fmt.get("heading_required_pattern") or r"^# 登場人物")
    character_heading_pattern = str(fmt.get("character_heading_pattern") or r"^.+（.+）$")
    skip_headings = [str(x) for x in (fmt.get("skip_headings") or [])]
    table_policy = str(fmt.get("table_policy") or "warn").lower()
    if strict and table_policy == "warn":
        table_policy = "error"

    profile_spec = resolve_profile(config, profile)
    alias_map = build_alias_map(config)
    required_fields = [canonicalize(str(x), alias_map) for x in profile_spec.get("require_fields") or []]

    result: dict[str, Any] = {
        "ok": True,
        "character_md": str(character_md),
        "novel_dir": str(novel_dir) if novel_dir else None,
        "profile": profile,
        "strict": strict,
        "suggest": suggest,
        "config_sources": config_sources,
        "characters": [],
        "errors": [],
        "warnings": [],
        "suggestions": [],
    }

    issues: list[Issue] = []
    if not character_md.is_file():
        issues.append(Issue("ERROR", f"character.md が見つかりません: {character_md}"))
    else:
        text = character_md.read_text(encoding="utf-8")
        first_nonempty = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
        if not re.search(heading_required_pattern, first_nonempty):
            issues.append(
                Issue(
                    "ERROR",
                    f"先頭ヘッダが想定外です: {first_nonempty!r}（期待: {heading_required_pattern}）",
                )
            )
        if any(is_table_row(line) for line in text.splitlines()):
            level = "ERROR" if table_policy == "error" else "WARN"
            issues.append(Issue(level, "Markdown 表形式を検出しました。`- **ラベル**:` 形式への移行を推奨します。"))

        sections, split_issues = split_characters(
            text,
            character_heading_pattern=character_heading_pattern,
            skip_headings=skip_headings,
        )
        issues.extend(split_issues)
        if not sections:
            issues.append(Issue("ERROR", f"キャラクター見出しが見つかりません（pattern: {character_heading_pattern}）"))

        for section in sections:
            parse_fields(section, alias_map)
            char_issues: list[Issue] = []
            for required in required_fields:
                if required not in section.fields:
                    char_issues.append(Issue("ERROR", f"必須項目がありません: {required}", section.heading))

            for canonical, occ in section.fields.items():
                spec = field_spec(config, canonical)
                min_chars = spec.get("min_chars")
                if isinstance(min_chars, int) and text_len(occ.content) < min_chars:
                    char_issues.append(
                        Issue(
                            "WARN",
                            f"{canonical} が短い可能性があります（{text_len(occ.content)} < {min_chars} 文字）",
                            section.heading,
                        )
                    )
                when_present = spec.get("when_present") if isinstance(spec, dict) else None
                if isinstance(when_present, dict):
                    min_children = when_present.get("min_children")
                    if isinstance(min_children, int) and len(occ.children) < min_children:
                        level = "ERROR" if canonical in required_fields else "WARN"
                        char_issues.append(
                            Issue(
                                level,
                                f"{canonical} の子項目が少ない可能性があります（{len(occ.children)} < {min_children}）",
                                section.heading,
                            )
                        )
                    for child in when_present.get("require_child_labels") or []:
                        child_s = normalize_child_label(str(child))
                        child_set = {normalize_child_label(c) for c in occ.children}
                        if child_s not in child_set:
                            level = "ERROR" if canonical in required_fields else "WARN"
                            char_issues.append(
                                Issue(
                                    level,
                                    f"{canonical} の子項目がありません: {child_s}",
                                    section.heading,
                                )
                            )

            if profile_spec.get("apply_body_gender_rules"):
                char_issues.extend(check_body_gender_rules(section, config, alias_map))

            issues.extend(char_issues)
            result["characters"].append(
                {
                    "heading": section.heading,
                    "start_line": section.start_line,
                    "fields": sorted(section.fields.keys()),
                    "raw_labels": section.raw_labels,
                }
            )

        if suggest:
            result["suggestions"] = build_suggestions(
                sections,
                required_fields=required_fields,
            )

    errors = [issue.to_dict() for issue in issues if issue.level == "ERROR"]
    warnings = [issue.to_dict() for issue in issues if issue.level == "WARN"]
    result["errors"] = errors
    result["warnings"] = warnings
    result["ok"] = not errors
    return result


def print_text_result(result: dict[str, Any]) -> None:
    print(f"character.md: {result['character_md']}")
    print(f"profile: {result['profile']}")
    print("checklist:")
    for source in result.get("config_sources") or []:
        print(f"  - {source}")

    print("characters:")
    for char in result.get("characters") or []:
        fields = ", ".join(char.get("fields") or [])
        print(f"  - {char['heading']} (line {char['start_line']}): {fields}")

    if result.get("warnings"):
        print("\nWARN:")
        for issue in result["warnings"]:
            prefix = f"[{issue['character']}] " if issue.get("character") else ""
            print(f"  - {prefix}{issue['message']}")

    if result.get("errors"):
        print("\nERROR:")
        for issue in result["errors"]:
            prefix = f"[{issue['character']}] " if issue.get("character") else ""
            print(f"  - {prefix}{issue['message']}")

    if result.get("suggestions"):
        print("\nSUGGEST:")
        for index, suggestion in enumerate(result["suggestions"], start=1):
            character = suggestion.get("character")
            title = f"{index}. {suggestion.get('type', 'suggestion')}"
            if character:
                title += f" [{character}]"
            print(f"  {title}")
            print(f"  {suggestion.get('message', '')}")
            markdown = suggestion.get("markdown")
            if markdown:
                print("  ```markdown")
                for line in str(markdown).splitlines():
                    print(f"  {line}")
                print("  ```")

    print("\n=== 結果: " + ("OK" if result["ok"] else "NG") + " ===")


def main(argv: list[str] | None = None) -> int:
    from console_io import configure_stdio_utf8

    configure_stdio_utf8()

    root = repo_root()
    parser = argparse.ArgumentParser(
        description="character.md を _how_to のチェックリスト YAML に基づいて lint する"
    )
    parser.add_argument("target", type=Path, help="novels/NNN_作品名 または character.md")
    parser.add_argument("--profile", default="plan", help="profiles.<name> を指定（既定: plan）")
    parser.add_argument("--strict", action="store_true", help="移行猶予の WARN を ERROR 扱いにする")
    parser.add_argument("--suggest", action="store_true", help="不足項目の追記案や表形式の変換案を表示する")
    parser.add_argument("--json", action="store_true", help="JSON で出力")
    args = parser.parse_args(argv)

    try:
        novel_dir, character_md = resolve_target(args.target, root)
        result = check_character_file(
            character_md,
            novel_dir=novel_dir,
            profile=args.profile,
            strict=args.strict,
            suggest=args.suggest,
            root=root,
        )
    except (FileNotFoundError, KeyError, ValueError, yaml.YAMLError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print_text_result(result)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
