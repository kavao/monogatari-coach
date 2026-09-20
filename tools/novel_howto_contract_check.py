#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
作品 `_meta.md` の Gate B 創作技法契約を読み取り専用で点検する。

- ファイルを書き換えない。
- Gate A（novel_project_check）の必須にはしない。
- 新形式の selected 実在、旧形式の正規化 WARN、索引混在を報告する。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

INDEX_OR_TEMPLATE_NAMES = frozenset(
    {
        "_index.md",
        "episode_.md",
        "epsode_common.md",
        "epsode_mature.md",
        "meta.md",
        "character.md.example",
        "readme.md",
    }
)

PLACEHOLDER = re.compile(r"例:|またはなし|^\(.*\)$")
GATE_B_START = re.compile(r"^##\s*3\.5\b|^##\s*.*Gate B", re.I)
NEXT_H2 = re.compile(r"^##\s+")
SELECTED_HEAD = re.compile(r"\*\*selected\*\*", re.I)
NOT_APP_HEAD = re.compile(r"\*\*not_applicable\*\*|創作技法契約", re.I)
OLD_LIST_HEAD = re.compile(r"読んだ\s*_how_to", re.I)
REL_ID_LINE = re.compile(r"^\s*-\s*relative_id\s*:\s*(.+?)\s*$", re.I)
FIELD_LINE = re.compile(
    r"^\s*-\s*(standard_path|working_path|effective_path)\s*:\s*(.+?)\s*$",
    re.I,
)
BULLET_PATH = re.compile(r"^\s*-\s+(.+)$")


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _strip_md(value: str) -> str:
    text = value.replace("`", "").strip()
    text = re.sub(r"\s*[（(].*$", "", text).strip()
    return text


def normalize_recorded_path(raw: str) -> tuple[str, list[str]]:
    """記録文字列を relative_id に落とす。警告を返す。"""
    warnings: list[str] = []
    text = _strip_md(raw)
    if " / " in text:
        warnings.append(f"複数パス併記: {raw.strip()}")
        text = text.split(" / ", 1)[0].strip().strip("`")
    text = text.replace("\\", "/").lstrip("./")
    lower = text.lower()
    if lower.startswith("how_to/") and not lower.startswith("_how_to"):
        warnings.append(f"旧形式 how_to/: {raw.strip()}")
        text = "_how_to/" + text[len("how_to/") :]
        lower = text.lower()
    if lower.startswith("_how_to.example/"):
        rel = text[len("_how_to.example/") :]
    elif lower.startswith("_how_to/"):
        rel = text[len("_how_to/") :]
    else:
        if text and "/" in text:
            warnings.append(f"プレフィックス無し: {raw.strip()}")
        rel = text
    return rel.lstrip("./"), warnings


def is_index_or_template(relative_id: str) -> bool:
    name = Path(relative_id.replace("\\", "/")).name.lower()
    return name in INDEX_OR_TEMPLATE_NAMES


def extract_gate_b(text: str) -> str:
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if GATE_B_START.search(line):
            start = i
            break
    if start is None:
        return ""
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if NEXT_H2.match(lines[j]) and not GATE_B_START.search(lines[j]):
            end = j
            break
    return "\n".join(lines[start:end])


def _empty_path(value: str) -> bool:
    text = _strip_md(value)
    if not text:
        return True
    if PLACEHOLDER.search(text):
        return True
    if text in {"なし", "無", "-", "—"}:
        return True
    return False


@dataclass
class Leaf:
    relative_id: str
    recorded: str
    standard_path: str = ""
    working_path: str = ""
    effective_path: str = ""
    warnings: list[str] = field(default_factory=list)
    index_like: bool = False


@dataclass
class ContractCheck:
    format: str
    selected: list[Leaf] = field(default_factory=list)
    not_applicable: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    required_missing: list[str] = field(default_factory=list)
    present: list[str] = field(default_factory=list)
    pack_id: str = ""
    pack_path: str = ""

    def leaf_count(self) -> int:
        return sum(1 for leaf in self.selected if not leaf.index_like)

    def as_dict(self) -> dict[str, object]:
        return {
            "format": self.format,
            "pack_id": self.pack_id,
            "pack_path": self.pack_path,
            "selected_count": self.leaf_count(),
            "not_applicable": self.not_applicable,
            "warnings": self.warnings,
            "errors": self.errors,
            "required_missing": self.required_missing,
            "present": self.present,
            "selected": [
                {
                    "relative_id": leaf.relative_id,
                    "working_path": leaf.working_path,
                    "standard_path": leaf.standard_path,
                    "effective_path": leaf.effective_path,
                    "index_like": leaf.index_like,
                    "warnings": leaf.warnings,
                }
                for leaf in self.selected
            ],
        }


def parse_new_selected(section: str) -> list[Leaf]:
    leaves: list[Leaf] = []
    current: Leaf | None = None
    in_selected = False
    for line in section.splitlines():
        if SELECTED_HEAD.search(line):
            in_selected = True
            continue
        if in_selected and (
            re.search(r"\*\*not_applicable\*\*", line, re.I)
            or re.search(r"\*\*選定補助\*\*", line)
            or re.search(r"\*\*pack_add\*\*|\*\*pack_exclude\*\*|\*\*pack_id\*\*", line, re.I)
        ):
            if current:
                leaves.append(current)
                current = None
            in_selected = False
            continue
        if not in_selected:
            continue
        match = REL_ID_LINE.match(line)
        if match:
            if current:
                leaves.append(current)
            raw = match.group(1)
            if PLACEHOLDER.search(raw):
                current = None
                continue
            rel, warns = normalize_recorded_path(raw)
            current = Leaf(
                relative_id=rel,
                recorded=raw,
                warnings=warns,
                index_like=is_index_or_template(rel),
            )
            continue
        if current is None:
            continue
        field_match = FIELD_LINE.match(line)
        if field_match:
            key = field_match.group(1).lower()
            value = field_match.group(2)
            if _empty_path(value):
                continue
            path = _strip_md(value)
            if key == "working_path":
                current.working_path = path
            elif key == "standard_path":
                current.standard_path = path
            elif key == "effective_path":
                current.effective_path = path
    if current:
        leaves.append(current)
    return leaves


def parse_legacy_list(section: str) -> tuple[list[Leaf], list[str]]:
    leaves: list[Leaf] = []
    not_app: list[str] = []
    in_list = False
    for line in section.splitlines():
        if OLD_LIST_HEAD.search(line):
            in_list = True
            continue
        if in_list and re.match(r"^-\s+\*\*", line):
            break
        if not in_list:
            continue
        stripped = line.strip()
        if re.match(r"^-\s*非該当", stripped) or stripped.startswith("非該当"):
            not_app.append(stripped.lstrip("- ").strip())
            continue
        match = BULLET_PATH.match(line)
        if not match:
            continue
        body = match.group(1)
        if body.startswith("**"):
            break
        if body.startswith("非該当"):
            not_app.append(body)
            continue
        rel, warns = normalize_recorded_path(body)
        if not rel:
            continue
        leaf = Leaf(
            relative_id=rel,
            recorded=body,
            warnings=warns,
            index_like=is_index_or_template(rel),
        )
        leaves.append(leaf)
    return leaves, not_app


def _pack_token_ok(text: str) -> bool:
    token = _strip_md(text)
    if not token or _empty_path(token):
        return False
    if PLACEHOLDER.search(token):
        return False
    return True


def parse_pack_fields(section: str) -> tuple[str, list[str], list[str]]:
    pack_id = ""
    add: list[str] = []
    exclude: list[str] = []
    mode = ""
    for line in section.splitlines():
        if re.search(r"\*\*selected\*\*|\*\*not_applicable\*\*|\*\*選定補助\*\*", line, re.I):
            mode = ""
        id_match = re.search(r"\*\*pack_id\*\*\s*:\s*(.+)$", line, re.I)
        if not id_match:
            id_match = re.search(r"^\s*-\s*pack_id\s*:\s*(.+)$", line, re.I)
        if id_match:
            token = id_match.group(1)
            if _pack_token_ok(token):
                pack_id = _strip_md(token).split()[0]
            continue
        if re.search(r"\*\*pack_add\*\*|^\s*-\s*pack_add\s*:", line, re.I):
            mode = "add"
            continue
        if re.search(r"\*\*pack_exclude\*\*|^\s*-\s*pack_exclude\s*:", line, re.I):
            mode = "exclude"
            continue
        if mode not in {"add", "exclude"}:
            continue
        rel_match = REL_ID_LINE.match(line)
        if rel_match:
            token = rel_match.group(1)
            if _pack_token_ok(token):
                (add if mode == "add" else exclude).append(_strip_md(token))
            continue
        match = BULLET_PATH.match(line)
        if not match:
            continue
        body = match.group(1).strip()
        if body.startswith("why:") or body.startswith("role:"):
            continue
        if _pack_token_ok(body):
            (add if mode == "add" else exclude).append(_strip_md(body))
    return pack_id, add, exclude


def load_pack_leaves(root: Path, pack_id: str) -> tuple[list[str], str, list[str]]:
    errors: list[str] = []
    posix = _posix(pack_id)
    if is_unsafe_path(posix) or "/" in posix or "\\" in posix:
        return [], "", [f"pack_id が不正: {pack_id}"]
    working = root / "_how_to" / "howto_packs" / f"{pack_id}.yaml"
    standard = root / "_how_to.example" / "howto_packs" / f"{pack_id}.yaml"
    path = working if working.is_file() else standard
    if not path.is_file():
        return [], "", [f"パックが無い: {pack_id}"]
    try:
        import yaml
    except ImportError:
        return [], "", ["PyYAML が必要です"]
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, UnicodeDecodeError) as exc:
        return [], str(path.as_posix()), [f"パック YAML を読めない: {exc}"]
    except yaml.YAMLError as exc:
        return [], str(path.as_posix()), [f"パック YAML が不正: {exc}"]
    if not isinstance(data, dict):
        return [], str(path.as_posix()), [f"パック YAML が不正: {path}"]
    file_id = str(data.get("pack_id") or "").strip()
    if file_id and file_id != pack_id:
        errors.append(f"pack_id 不一致: 契約 {pack_id} vs ファイル {file_id}")
    leaves_raw = data.get("leaves") or []
    if not isinstance(leaves_raw, list):
        return [], str(path.as_posix()), [f"packs.leaves が配列ではない: {pack_id}"]
    leaves: list[str] = []
    for item in leaves_raw:
        rel = _posix(str(item).strip())
        if not rel:
            continue
        if relative_id_errors(rel):
            errors.append(f"パック内 relative_id が不正: {rel}")
            continue
        if is_index_or_template(rel):
            errors.append(f"パックに索引または雛形: {rel}")
            continue
        leaves.append(rel)
    pack_path = ""
    joined = safe_join_howto(
        root,
        f"_how_to/howto_packs/{pack_id}.yaml"
        if working.is_file()
        else f"_how_to.example/howto_packs/{pack_id}.yaml",
    )
    if joined is not None:
        pack_path = str(joined.as_posix())
    else:
        pack_path = str(path.as_posix())
    return leaves, pack_path, errors


def merge_pack_into_selected(
    selected: list[Leaf],
    pack_leaves: list[str],
    pack_add: list[str],
    pack_exclude: list[str],
) -> list[Leaf]:
    have = {leaf.relative_id for leaf in selected}
    exclude = set(pack_exclude)
    extra: list[Leaf] = []
    for rel in list(pack_leaves) + list(pack_add):
        if rel in exclude or rel in have:
            continue
        extra.append(
            Leaf(
                relative_id=rel,
                recorded=rel,
                index_like=is_index_or_template(rel),
            )
        )
        have.add(rel)
    return extra + selected


def parse_not_applicable_new(section: str) -> list[str]:
    rows: list[str] = []
    in_na = False
    for line in section.splitlines():
        if re.search(r"\*\*not_applicable\*\*", line, re.I):
            in_na = True
            continue
        if in_na and re.search(r"\*\*選定補助\*\*|\*\*発動した", line):
            break
        if not in_na:
            continue
        match = BULLET_PATH.match(line)
        if match:
            body = match.group(1).strip()
            if body.startswith("why:") or body.startswith("role:"):
                continue
            if PLACEHOLDER.search(body):
                continue
            rows.append(body)
    return rows


def _posix(raw: str) -> str:
    text = raw.replace("\\", "/").strip()
    while len(text) > 1 and text.endswith("/"):
        text = text[:-1]
    return text
    return raw.replace("\\", "/").strip()


def is_unsafe_path(posix: str) -> bool:
    if not posix:
        return True
    if posix.startswith("/") or posix.startswith("\\"):
        return True
    if len(posix) >= 2 and posix[1] == ":":
        return True
    return any(part == ".." or part == "" for part in posix.split("/") if part != ".")


def is_working_prefix(posix: str) -> bool:
    return posix.startswith("_how_to/") and not posix.startswith("_how_to.example/")


def is_standard_prefix(posix: str) -> bool:
    return posix.startswith("_how_to.example/")


def relative_id_errors(relative_id: str) -> list[str]:
    posix = _posix(relative_id)
    errors: list[str] = []
    if is_unsafe_path(posix) or posix.startswith("_how_to"):
        errors.append(f"relative_id が不正: {relative_id}")
    return errors


def recorded_file_errors(raw: str, relative_id: str, *, kind: str) -> list[str]:
    posix = _posix(raw)
    errors: list[str] = []
    if is_unsafe_path(posix):
        errors.append(f"拒否（絶対パスまたは ..）: {raw}")
        return errors
    if kind == "working":
        if not is_working_prefix(posix):
            errors.append(f"working_path は _how_to/ 配下のみ: {raw}")
            return errors
    elif kind == "standard":
        if not is_standard_prefix(posix):
            errors.append(f"standard_path は _how_to.example/ 配下のみ: {raw}")
            return errors
    else:
        if not is_working_prefix(posix) and not is_standard_prefix(posix):
            errors.append(f"許可ルート外: {raw}")
            return errors
    rel_from_path, _ = normalize_recorded_path(posix)
    if rel_from_path != relative_id:
        errors.append(f"relative_id と不一致: {relative_id} vs {raw}")
    return errors


def safe_join_howto(root: Path, posix_rel: str) -> Path | None:
    """許可ルート配下に収まるときだけ Path を返す。"""
    posix_rel = _posix(posix_rel)
    if is_unsafe_path(posix_rel):
        return None
    if not is_working_prefix(posix_rel) and not is_standard_prefix(posix_rel):
        return None
    root_res = root.resolve()
    candidate = (root / posix_rel).resolve()
    try:
        candidate.relative_to(root_res)
    except ValueError:
        return None
    for allowed in (root_res / "_how_to.example", root_res / "_how_to"):
        try:
            candidate.relative_to(allowed)
            return candidate
        except ValueError:
            continue
    return None


def resolve_effective(
    leaf: Leaf, root: Path, *, new_format: bool
) -> tuple[Path | None, list[str]]:
    errors: list[str] = []
    errors.extend(relative_id_errors(leaf.relative_id))
    if errors:
        return None, errors

    if leaf.working_path:
        errors.extend(
            recorded_file_errors(leaf.working_path, leaf.relative_id, kind="working")
        )
        if errors:
            return None, errors
        return safe_join_howto(root, leaf.working_path), []

    if leaf.standard_path:
        errors.extend(
            recorded_file_errors(leaf.standard_path, leaf.relative_id, kind="standard")
        )
        if errors:
            return None, errors
        return safe_join_howto(root, leaf.standard_path), []

    if new_format:
        return safe_join_howto(root, f"_how_to.example/{leaf.relative_id}"), []

    working = safe_join_howto(root, f"_how_to/{leaf.relative_id}")
    if working is not None and working.is_file():
        return working, []
    return safe_join_howto(root, f"_how_to.example/{leaf.relative_id}"), []


def check_meta(meta_text: str, root: Path) -> ContractCheck:
    section = extract_gate_b(meta_text)
    if not section:
        return ContractCheck(format="missing", warnings=["Gate B 節が無い"])
    if SELECTED_HEAD.search(section) or "創作技法契約" in section:
        result = ContractCheck(format="new")
        result.selected = parse_new_selected(section)
        result.not_applicable = parse_not_applicable_new(section)
        new_format = True
        pack_id, pack_add, pack_exclude = parse_pack_fields(section)
        if pack_id:
            result.pack_id = pack_id
            pack_leaves, pack_path, pack_errors = load_pack_leaves(root, pack_id)
            result.pack_path = pack_path
            result.errors.extend(pack_errors)
            result.selected = merge_pack_into_selected(
                result.selected, pack_leaves, pack_add, pack_exclude
            )
    elif OLD_LIST_HEAD.search(section):
        result = ContractCheck(format="legacy")
        result.warnings.append("旧形式（grandfather）。selected 必須ではない")
        leaves, na = parse_legacy_list(section)
        result.selected = leaves
        result.not_applicable = na
        new_format = False
    else:
        return ContractCheck(format="missing", warnings=["Gate B に契約一覧が無い"])

    for leaf in result.selected:
        result.warnings.extend(leaf.warnings)
        if leaf.index_like:
            if new_format:
                result.errors.append(
                    f"新形式の selected に索引または雛形: {leaf.relative_id}"
                )
            else:
                result.warnings.append(
                    f"索引または雛形が契約行にある: {leaf.relative_id}"
                )
            continue
        path, path_errors = resolve_effective(leaf, root, new_format=new_format)
        if path_errors:
            result.errors.extend(path_errors)
            continue
        if path is None:
            result.required_missing.append(leaf.relative_id)
            result.warnings.append(
                f"実在しない（検査結果 required_missing）: {leaf.relative_id}"
            )
            continue
        leaf.effective_path = str(path.as_posix())
        if path.is_file():
            result.present.append(leaf.relative_id)
        else:
            result.required_missing.append(leaf.relative_id)
            result.warnings.append(
                f"実在しない（検査結果 required_missing）: {leaf.relative_id}"
            )
    return result


def check_novel(novel_dir: Path, root: Path | None = None) -> ContractCheck:
    root = root or repo_root()
    meta = novel_dir / "_meta.md"
    if not meta.is_file():
        return ContractCheck(format="missing", warnings=[f"_meta.md が無い: {meta}"])
    text = meta.read_text(encoding="utf-8")
    return check_meta(text, root)


def _print_human(result: ContractCheck) -> None:
    print(f"形式: {result.format}")
    if result.pack_id:
        print(f"pack_id: {result.pack_id}")
    print(f"selected/葉 件数: {result.leaf_count()}")
    print(f"not_applicable 件数: {len(result.not_applicable)}")
    print(f"実在: {len(result.present)}")
    print(f"required_missing: {len(result.required_missing)}")
    print(f"errors: {len(result.errors)}")
    for item in result.required_missing:
        print(f"  MISSING {item}")
    for err in result.errors:
        print(f"  ERROR {err}")
    for warn in result.warnings:
        print(f"  WARN {warn}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Gate B 創作技法契約の読み取り専用チェック（_meta.md を書き換えない）"
    )
    parser.add_argument("novel", type=Path, help="novels/<作品> フォルダ")
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="リポジトリ根（省略時はこのスクリプトの親）",
    )
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="required_missing または新形式の errors があれば終了コード 1。Gate A では使わない",
    )
    args = parser.parse_args(argv)
    novel = args.novel
    if not novel.is_absolute():
        base = args.repo_root or repo_root()
        novel = (base / novel).resolve()
    if not novel.is_dir():
        print(f"作品フォルダが無い: {novel}", file=sys.stderr)
        return 2
    result = check_novel(novel, root=args.repo_root or repo_root())
    if args.json:
        print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
    else:
        _print_human(result)
    if args.strict and (result.required_missing or result.errors):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
