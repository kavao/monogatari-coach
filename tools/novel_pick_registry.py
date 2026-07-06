#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pick Registry: merge YAML fragments and resolve list_id → json_weighted_pick / wrappers."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from json_weighted_pick import load_json, navigate

_TOOLS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _TOOLS_DIR.parent

DEFAULT_MERGE_ORDER = (
    "_how_to.example/pick_registry",
    "_how_to/pick_registry",
)


@dataclass
class PickListEntry:
    list_id: str
    domain: str = ""
    visibility: str = "public"
    description: str = ""
    source: str = ""
    path: str = ""
    tool: str = "json_weighted_pick"
    character_pick: dict[str, Any] = field(default_factory=dict)
    fragment: str = ""
    registry_dir: str = ""

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "list_id": self.list_id,
            "domain": self.domain,
            "visibility": self.visibility,
            "description": self.description,
            "source": self.source,
            "path": self.path,
            "tool": self.tool,
            "fragment": self.fragment,
            "registry_dir": self.registry_dir,
        }
        if self.character_pick:
            out["character_pick"] = self.character_pick
        return out


def repo_root() -> Path:
    return _REPO_ROOT


def resolve_registry_dirs(
    *,
    novel_dir: Path | None = None,
    merge_order: list[str] | None = None,
) -> list[Path]:
    order = merge_order or list(DEFAULT_MERGE_ORDER)
    dirs: list[Path] = []
    root = repo_root()
    for item in order:
        token = item.strip()
        if "novels/" in token and "<作品>" in token:
            if novel_dir is None:
                continue
            rel = Path("novels") / novel_dir.name / "pick_registry"
            path = (root / rel).resolve()
        elif token.startswith("novels/") and novel_dir is not None:
            path = (root / token).resolve()
        else:
            path = (root / token).resolve()
        if path.is_dir():
            dirs.append(path)
    return dirs


def load_yaml_mapping(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"YAML root must be a mapping: {path}")
    return data


def load_index(registry_dir: Path) -> dict[str, Any]:
    index_path = registry_dir / "_index.yaml"
    if not index_path.is_file():
        return {}
    return load_yaml_mapping(index_path)


def fragment_files(registry_dir: Path, index: dict[str, Any]) -> list[Path]:
    fragments = index.get("fragments")
    if isinstance(fragments, dict):
        paths: list[Path] = []
        for _key, rel in fragments.items():
            if not isinstance(rel, str) or not rel.strip():
                continue
            candidate = registry_dir / rel
            if candidate.is_file():
                paths.append(candidate)
        if paths:
            return paths
    return sorted(registry_dir.glob("*.yaml")) + sorted(registry_dir.glob("*.yml"))


def resolve_source_path(source: str) -> Path:
    path = Path(source)
    if not path.is_absolute():
        path = repo_root() / path
    return path.resolve()


def parse_pick_lists_from_file(fragment_path: Path, registry_dir: Path) -> dict[str, PickListEntry]:
    data = load_yaml_mapping(fragment_path)
    raw_lists = data.get("pick_lists")
    if not isinstance(raw_lists, dict):
        return {}
    out: dict[str, PickListEntry] = {}
    for list_id, spec in raw_lists.items():
        if not isinstance(spec, dict):
            continue
        out[str(list_id)] = PickListEntry(
            list_id=str(list_id),
            domain=str(spec.get("domain") or ""),
            visibility=str(spec.get("visibility") or "public"),
            description=str(spec.get("description") or ""),
            source=str(spec.get("source") or ""),
            path=str(spec.get("path") or ""),
            tool=str(spec.get("tool") or "json_weighted_pick"),
            character_pick=dict(spec.get("character_pick") or {})
            if isinstance(spec.get("character_pick"), dict)
            else {},
            fragment=fragment_path.name,
            registry_dir=str(registry_dir.relative_to(repo_root())).replace("\\", "/"),
        )
    return out


def merge_registry(
    *,
    novel_dir: Path | None = None,
) -> dict[str, PickListEntry]:
    merged: dict[str, PickListEntry] = {}
    dirs = resolve_registry_dirs(novel_dir=novel_dir)
    for registry_dir in dirs:
        index = load_index(registry_dir)
        for fragment_path in fragment_files(registry_dir, index):
            if fragment_path.name == "_index.yaml":
                continue
            for list_id, entry in parse_pick_lists_from_file(fragment_path, registry_dir).items():
                merged[list_id] = entry
    return merged


def filter_entries(
    entries: dict[str, PickListEntry],
    *,
    domain: str | None = None,
    visibility: str | None = None,
    prefix: str | None = None,
) -> dict[str, PickListEntry]:
    out: dict[str, PickListEntry] = {}
    for list_id, entry in entries.items():
        if domain and entry.domain != domain:
            continue
        if visibility and entry.visibility != visibility:
            continue
        if prefix and not list_id.startswith(prefix):
            continue
        out[list_id] = entry
    return out


def validate_entries(entries: dict[str, PickListEntry]) -> list[str]:
    errors: list[str] = []
    for list_id, entry in sorted(entries.items()):
        if entry.tool == "json_weighted_pick":
            if not entry.source:
                errors.append(f"{list_id}: source が空です")
                continue
            src = resolve_source_path(entry.source)
            if not src.is_file():
                errors.append(f"{list_id}: source が見つかりません: {src}")
                continue
            if not entry.path:
                errors.append(f"{list_id}: path が空です")
                continue
            try:
                data = load_json(src, False)
                navigate(data, entry.path)
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                errors.append(f"{list_id}: path 到達不可 ({entry.path}): {exc}")
        elif entry.tool == "novel_character_pick":
            cp = entry.character_pick
            if not cp.get("gender"):
                errors.append(f"{list_id}: character_pick.gender が必要です")
        else:
            errors.append(f"{list_id}: 未対応 tool: {entry.tool}")
    return errors


def run_json_weighted_pick(
    entry: PickListEntry,
    *,
    seed: int | None,
    count: int,
) -> int:
    src = resolve_source_path(entry.source)
    cmd = [
        sys.executable,
        str(_TOOLS_DIR / "json_weighted_pick.py"),
        str(src),
        "--path",
        entry.path,
        "--count",
        str(count),
    ]
    if seed is not None:
        cmd.extend(["--seed", str(seed)])
    return subprocess.call(cmd)


def run_novel_character_pick(
    entry: PickListEntry,
    *,
    seed: int | None,
    json_out: bool,
) -> int:
    script = repo_root() / "_how_to" / "tools" / "novel_character_pick.py"
    if not script.is_file():
        print(f"error: {script} が見つかりません", file=sys.stderr)
        return 1
    cp = entry.character_pick
    cmd = [
        sys.executable,
        str(script),
        "--gender",
        str(cp.get("gender")),
        "--age-band",
        str(cp.get("age_band") or "若者"),
    ]
    if seed is not None:
        cmd.extend(["--seed", str(seed)])
    if json_out:
        cmd.append("--json")
    return subprocess.call(cmd)


def cmd_list(args: argparse.Namespace) -> int:
    entries = merge_registry(novel_dir=args.novel_dir)
    entries = filter_entries(
        entries,
        domain=args.domain,
        visibility=args.visibility,
        prefix=args.prefix,
    )
    if not entries:
        print("（登録 pick_lists なし）")
        return 0
    for list_id in sorted(entries):
        entry = entries[list_id]
        print(
            f"{list_id}\t{entry.domain}\t{entry.visibility}\t"
            f"{entry.tool}\t{entry.registry_dir}/{entry.fragment}"
        )
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    entries = merge_registry(novel_dir=args.novel_dir)
    entry = entries.get(args.list_id)
    if entry is None:
        print(f"error: list_id が見つかりません: {args.list_id}", file=sys.stderr)
        return 1
    print(yaml.safe_dump(entry.to_dict(), allow_unicode=True, sort_keys=False).rstrip())
    return 0


def cmd_pick(args: argparse.Namespace) -> int:
    entries = merge_registry(novel_dir=args.novel_dir)
    entry = entries.get(args.list_id)
    if entry is None:
        print(f"error: list_id が見つかりません: {args.list_id}", file=sys.stderr)
        return 1
    if entry.tool == "json_weighted_pick":
        return run_json_weighted_pick(entry, seed=args.seed, count=args.count)
    if entry.tool == "novel_character_pick":
        return run_novel_character_pick(entry, seed=args.seed, json_out=args.json)
    print(f"error: 未対応 tool: {entry.tool}", file=sys.stderr)
    return 1


def cmd_validate(args: argparse.Namespace) -> int:
    entries = merge_registry(novel_dir=args.novel_dir)
    if not entries:
        print("error: pick_lists が1件も登録されていません", file=sys.stderr)
        return 1
    errors = validate_entries(entries)
    if errors:
        for line in errors:
            print(f"ERROR: {line}", file=sys.stderr)
        return 1
    print(f"OK: {len(entries)} list_id")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Pick Registry list_id 解決・抽選")
    parser.add_argument(
        "--novel",
        type=Path,
        default=None,
        help="作品フォルダ（novels/NNN_作品名）。作品別 pick_registry を merge に含める",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="登録済み pick_lists 一覧")
    p_list.add_argument("--domain", choices=("character", "episode"), default=None)
    p_list.add_argument("--visibility", choices=("public", "user", "work"), default=None)
    p_list.add_argument("--prefix", default=None)
    p_list.set_defaults(func=cmd_list)

    p_show = sub.add_parser("show", help="list_id の定義を表示")
    p_show.add_argument("list_id")
    p_show.set_defaults(func=cmd_show)

    p_pick = sub.add_parser("pick", help="list_id で抽選実行")
    p_pick.add_argument("list_id")
    p_pick.add_argument("--seed", type=int, default=None)
    p_pick.add_argument("-n", "--count", type=int, default=1)
    p_pick.add_argument("--json", action="store_true", help="novel_character_pick 向け JSON 出力")
    p_pick.set_defaults(func=cmd_pick)

    p_val = sub.add_parser("validate", help="registry 整合性チェック")
    p_val.set_defaults(func=cmd_validate)

    return parser


def main(argv: list[str] | None = None) -> int:
    from console_io import configure_stdio_utf8

    configure_stdio_utf8()
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.novel is not None:
        novel = args.novel
        if not novel.is_absolute():
            novel = (repo_root() / novel).resolve()
        args.novel_dir = novel
    else:
        args.novel_dir = None
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())