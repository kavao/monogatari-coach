#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Plan and safely apply a manga-prompt-ir 1.0 -> 1.1 migration.

The dry-run remains the only way to create a migration plan.  Applying an
existing plan is explicit, hash-guarded, backed up, and never performed as a
bulk implicit migration.
"""

from __future__ import annotations

import argparse
import copy
import contextlib
import hashlib
import io
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

import yaml

_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from manga_prompt_ir.schemas.manga_page import MangaPagePrompt  # noqa: E402


MIGRATOR_VERSION = "1.1-apply"
PLAN_FORMAT_VERSION = 2
BACKUP_DIR_NAME = "_manga_ir_backup"


def repo_root() -> Path:
    return _TOOLS_DIR.parent


def load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"YAML root must be a mapping: {path}")
    return data


def canonical_hash(data: dict[str, Any]) -> str:
    payload = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def raw_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def yaml_text(data: dict[str, Any]) -> str:
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=120)


def atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def atomic_write_text(path: Path, text: str) -> None:
    atomic_write_bytes(path, text.encode("utf-8"))


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def page_paths(novel_dir: Path | None, explicit: list[str]) -> list[Path]:
    if explicit:
        return sorted(
            Path(value).resolve() if Path(value).is_absolute() else Path(value).resolve()
            for value in explicit
        )
    if novel_dir is None:
        raise ValueError("作品フォルダまたは --manga-page が必要です")
    pages_dir = novel_dir / "manga" / "pages"
    if not pages_dir.is_dir():
        raise FileNotFoundError(f"manga/pages/ がありません: {pages_dir}")
    paths = sorted(pages_dir.glob("*.yaml"))
    if not paths:
        raise FileNotFoundError(f"manga/pages/*.yaml がありません: {pages_dir}")
    return paths


def add_change(
    changes: list[dict[str, Any]],
    *,
    path: str,
    old: Any,
    new: Any,
    category: str,
    reason: str,
) -> None:
    changes.append(
        {
            "path": path,
            "old": old,
            "new": new,
            "category": category,
            "reason": reason,
        }
    )


def _subject_id(panel_id: Any, index: int) -> str:
    return f"p{panel_id}-s{index:02d}"


def _text_id(panel_id: Any, kind: str, index: int) -> str:
    return f"p{panel_id}-{kind}-{index:02d}"


def _structured_text_item(item: Any, text_id: str) -> dict[str, Any]:
    if isinstance(item, dict):
        structured = copy.deepcopy(item)
        structured.setdefault("text_id", text_id)
        return structured
    return {"text_id": text_id, "content": item}


def _unresolved_text_mode(data: dict[str, Any]) -> dict[str, Any]:
    instruction = data.get("render_instruction")
    manga = data.get("manga")
    declared = []
    if isinstance(instruction, dict) and "text_policy" in instruction:
        declared.append("render_instruction.text_policy")
    if isinstance(manga, dict) and "text_policy" in manga:
        declared.append("manga.text_policy")
    return {
        "path": "/render_instruction/text_mode",
        "reason": (
            "1.0のtext_policy省略・既定値から実行方針を捏造しない。"
            "1.1でgenerate / letter_later / noneを明示する"
        ),
        "declared_policy_paths": declared,
    }


def migrate_page(path: Path) -> dict[str, Any]:
    source = load_yaml(path)
    source_hash = canonical_hash(source)
    source_raw_hash = raw_hash(path)
    source_schema = str(source.get("schema_version", "1.0"))
    relative_path = path.as_posix()

    try:
        MangaPagePrompt.model_validate(source)
    except Exception as exc:
        return {
            "path": relative_path,
            "status": "error",
            "source_schema": source_schema,
            "source_sha256": source_hash,
            "source_raw_sha256": source_raw_hash,
            "changes": [],
            "unresolved": [],
            "errors": [str(exc)],
        }

    if source_schema == "1.1":
        return {
            "path": relative_path,
            "status": "up_to_date",
            "source_schema": source_schema,
            "source_sha256": source_hash,
            "source_raw_sha256": source_raw_hash,
            "proposed_sha256": source_hash,
            "changes": [],
            "unresolved": [],
            "proposed_data": source,
        }
    if source_schema != "1.0":
        return {
            "path": relative_path,
            "status": "error",
            "source_schema": source_schema,
            "source_sha256": source_hash,
            "source_raw_sha256": source_raw_hash,
            "changes": [],
            "unresolved": [],
            "errors": [f"移行対象はschema 1.0/1.1です: {source_schema!r}"],
        }

    raw_panels = [panel for panel in as_list(source.get("panels")) if isinstance(panel, dict)]
    panel_ids = [panel.get("panel_id") for panel in raw_panels]
    if len(panel_ids) != len(set(panel_ids)):
        return {
            "path": relative_path,
            "status": "blocked",
            "source_schema": source_schema,
            "source_sha256": source_hash,
            "source_raw_sha256": source_raw_hash,
            "changes": [],
            "unresolved": [
                {
                    "path": "/panels/*/panel_id",
                    "reason": "panel_idが重複しており、版をまたぐIDを一意に提案できない",
                }
            ],
            "errors": [],
        }

    proposed = copy.deepcopy(source)
    changes: list[dict[str, Any]] = []
    unresolved = [_unresolved_text_mode(source)]
    proposed["schema_version"] = "1.1"
    id_map: dict[str, list[dict[str, Any]]] = {"subjects": [], "texts": []}
    add_change(
        changes,
        path="/schema_version",
        old="1.0",
        new="1.1",
        category="normalization",
        reason="1.1の追加項目を読込可能にするための版昇格",
    )

    for panel_index, panel in enumerate(proposed.get("panels") or []):
        if not isinstance(panel, dict):
            continue
        panel_id = panel.get("panel_id")
        for subject_index, subject in enumerate(panel.get("subjects") or [], start=1):
            if not isinstance(subject, dict) or subject.get("subject_id"):
                continue
            value = _subject_id(panel_id, subject_index)
            subject["subject_id"] = value
            id_map["subjects"].append(
                {
                    "path": f"/panels/{panel_index}/subjects/{subject_index - 1}",
                    "panel_id": panel_id,
                    "subject_id": value,
                }
            )
            add_change(
                changes,
                path=f"/panels/{panel_index}/subjects/{subject_index - 1}/subject_id",
                old=None,
                new=value,
                category="structure_completion",
                reason="既存panel_idと配列位置から再実行可能な版内対応IDを提案",
            )

        text = panel.get("text") or {}
        if not isinstance(text, dict):
            continue
        for kind in ("dialogue", "monologue", "narration", "sfx"):
            items = text.get(kind) or []
            if not isinstance(items, list):
                continue
            converted: list[Any] = []
            changed_shape = False
            for item_index, item in enumerate(items, start=1):
                if isinstance(item, dict) and item.get("text_id"):
                    converted.append(item)
                    continue
                value = _text_id(panel_id, kind, item_index)
                converted_item = _structured_text_item(item, value)
                converted.append(converted_item)
                changed_shape = True
                id_map["texts"].append(
                    {
                        "path": f"/panels/{panel_index}/text/{kind}/{item_index - 1}",
                        "panel_id": panel_id,
                        "type": kind,
                        "text_id": value,
                    }
                )
                add_change(
                    changes,
                    path=f"/panels/{panel_index}/text/{kind}/{item_index - 1}",
                    old=item,
                    new=converted_item,
                    category="structure_completion",
                    reason="配列位置由来の一意なtext_idを付与し、文字列を構造化する",
                )
            if changed_shape:
                text[kind] = converted

    try:
        MangaPagePrompt.model_validate(proposed)
    except Exception as exc:
        return {
            "path": relative_path,
            "status": "error",
            "source_schema": source_schema,
            "source_sha256": source_hash,
            "source_raw_sha256": source_raw_hash,
            "changes": changes,
            "unresolved": unresolved,
            "errors": [f"提案データのschema 1.1検証に失敗: {exc}"],
        }

    return {
        "path": relative_path,
        "status": "proposed" if changes else "no_change",
        "source_schema": source_schema,
        "source_sha256": source_hash,
        "source_raw_sha256": source_raw_hash,
        "proposed_sha256": canonical_hash(proposed),
        "id_map": id_map,
        "changes": changes,
        "unresolved": unresolved,
        "errors": [],
        "proposed_data": proposed,
    }


class MigrationConflict(RuntimeError):
    """The requested apply/restore no longer matches the recorded state."""


def _resolve_root(raw_root: str | None, override: Path | None) -> Path:
    if override is not None:
        root = override if override.is_absolute() else (repo_root() / override)
        root = root.resolve()
        if raw_root and Path(raw_root).resolve() != root:
            raise MigrationConflict("計画のsource_rootと指定された作品フォルダが一致しません")
        return root
    if raw_root:
        return Path(raw_root).resolve()
    raise MigrationConflict("計画にsource_rootがありません。作品フォルダを明示してください")


def _resolve_entry_path(raw_path: str, root: Path) -> Path:
    candidate = Path(raw_path)
    resolved = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    if not resolved.is_relative_to(root):
        raise MigrationConflict(f"作品フォルダ外のページは適用できません: {resolved}")
    return resolved


def _relative_path(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root).as_posix()


def _plan_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def _load_json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def _load_apply_entries(
    plan: dict[str, Any],
    plan_path: Path,
    root: Path,
    *,
    selected_paths: set[Path] | None = None,
) -> list[dict[str, Any]]:
    if plan.get("tool") != "novel_manga_ir_migrate":
        raise MigrationConflict("別のツールの計画は適用できません")
    if plan.get("plan_format_version") != PLAN_FORMAT_VERSION:
        raise MigrationConflict("古い、または未対応の計画形式です。dry-runを再実行してください")
    if plan.get("dry_run") is not True or plan.get("apply_supported") is not True:
        raise MigrationConflict("dry-runで作成されたapply対応計画ではありません")
    if plan.get("target_schema") != "1.1":
        raise MigrationConflict("apply対象schemaは1.1に固定されています")
    pages = plan.get("pages")
    if not isinstance(pages, list):
        raise MigrationConflict("計画のpagesが配列ではありません")
    if any(not isinstance(entry, dict) for entry in pages):
        raise MigrationConflict("計画のpagesにobjectでない要素があります")

    selected_pages = pages
    if selected_paths is not None:
        selected_pages = []
        matched: set[Path] = set()
        for entry in pages:
            raw_path = entry.get("path")
            if not isinstance(raw_path, str) or not raw_path:
                continue
            target = _resolve_entry_path(raw_path, root)
            if target in selected_paths:
                selected_pages.append(entry)
                matched.add(target)
        missing = selected_paths - matched
        if missing:
            raise MigrationConflict(
                "計画に含まれないapply対象ページです: "
                + ", ".join(sorted(path.as_posix() for path in missing))
            )

    blocked = [entry for entry in selected_pages if entry.get("status") in {"error", "blocked"}]
    if blocked:
        labels = ", ".join(str(entry.get("path", "?")) for entry in blocked)
        raise MigrationConflict(f"error/blockedのページを含む計画は適用できません: {labels}")
    unsupported = [
        entry
        for entry in selected_pages
        if entry.get("status") not in {"proposed", "no_change", "up_to_date"}
    ]
    if unsupported:
        raise MigrationConflict("未知のページstatusを含む計画は適用できません")

    entries: list[dict[str, Any]] = []
    seen_paths: set[Path] = set()
    for entry in selected_pages:
        if entry.get("status") != "proposed":
            continue
        if not isinstance(entry, dict):
            raise MigrationConflict("ページ計画の要素がobjectではありません")
        path_value = entry.get("path")
        if not isinstance(path_value, str) or not path_value:
            raise MigrationConflict("ページ計画にpathがありません")
        target = _resolve_entry_path(path_value, root)
        if target in seen_paths:
            raise MigrationConflict(f"同じページが計画に重複しています: {target}")
        seen_paths.add(target)
        source_hash = entry.get("source_sha256")
        source_raw_sha256 = entry.get("source_raw_sha256")
        proposed_hash = entry.get("proposed_sha256")
        proposed_data = entry.get("proposed_data")
        if not all(isinstance(value, str) and value for value in (source_hash, source_raw_sha256, proposed_hash)):
            raise MigrationConflict(
                f"{path_value}: canonical/raw/proposed hashが揃っていません。dry-runを再実行してください"
            )
        if not isinstance(proposed_data, dict):
            raise MigrationConflict(f"{path_value}: proposed_dataがobjectではありません")
        if not target.is_file():
            raise MigrationConflict(f"対象ページがありません: {target}")
        current_bytes = target.read_bytes()
        current = load_yaml(target)
        if raw_hash(target) != source_raw_sha256:
            raise MigrationConflict(f"{path_value}: raw hashが一致しません。外部変更を検出しました")
        if canonical_hash(current) != source_hash:
            raise MigrationConflict(f"{path_value}: canonical hashが一致しません。外部変更を検出しました")
        try:
            MangaPagePrompt.model_validate(proposed_data)
        except Exception as exc:
            raise MigrationConflict(f"{path_value}: proposed_dataのschema 1.1検証に失敗: {exc}") from exc
        if canonical_hash(proposed_data) != proposed_hash:
            raise MigrationConflict(f"{path_value}: proposed_dataのhashが計画と一致しません")
        entries.append(
            {
                "entry": entry,
                "target": target,
                "relative_path": _relative_path(target, root),
                "current_bytes": current_bytes,
                "proposed_data": proposed_data,
            }
        )
    return entries


def _manga_stem(path: Path) -> str:
    match = re.match(r"(.+)_p\d+$", path.stem)
    return match.group(1) if match else path.stem


def _derived_specs(root: Path, entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    seen: set[Path] = set()
    pages_dir = root / "manga" / "pages"
    for item in entries:
        target: Path = item["target"]
        stem = _manga_stem(target)
        output = root / "manga" / f"{stem}.md"
        if output in seen:
            continue
        seen.add(output)
        inputs = sorted(pages_dir.glob(f"{stem}_p*.yaml")) if pages_dir.is_dir() else []
        if not inputs:
            inputs = [target]
        specs.append(
            {
                "kind": "markdown_export",
                "path": _relative_path(output, root),
                "inputs": [_relative_path(path, root) for path in inputs],
                "target": output,
            }
        )
    return specs


def _backup_existing_file(path: Path, backup_path: Path) -> bool:
    if not path.exists():
        return False
    if not path.is_file():
        raise MigrationConflict(f"ファイル以外の派生物は退避できません: {path}")
    if backup_path.exists():
        if backup_path.read_bytes() != path.read_bytes():
            raise MigrationConflict(f"既存退避ファイルが一致しません: {backup_path}")
    else:
        atomic_write_bytes(backup_path, path.read_bytes())
    return True


def _rollback_pages(records: list[dict[str, Any]]) -> None:
    for record in records:
        try:
            atomic_write_bytes(record["target"], record["current_bytes"])
        except OSError:
            pass


def _rollback_derived(specs: list[dict[str, Any]]) -> None:
    for spec in specs:
        target: Path = spec["target"]
        try:
            if spec.get("previous_exists"):
                atomic_write_bytes(target, spec["previous_bytes"])
            elif target.exists():
                target.unlink()
        except OSError:
            pass


def _regenerate_markdown(specs: list[dict[str, Any]]) -> None:
    from novel_prompt_ir_export_md import main as export_main

    for spec in specs:
        input_paths = [str(Path(path)) for path in spec["inputs_abs"]]
        argv = [
            "--manga-page",
            *input_paths,
            "--output-dir",
            str(spec["root"]),
            "--manga-stem",
            Path(spec["path"]).stem,
            "--novelai-pipe-tags",
        ]
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = export_main(argv)
        if result != 0:
            detail = (stderr.getvalue() or stdout.getvalue()).strip()
            raise MigrationConflict(
                f"派生Markdownの再生成に失敗しました: {spec['path']} {detail}"
            )
        spec["output_log"] = stdout.getvalue().strip()


def apply_plan(
    plan_path: Path,
    *,
    novel_dir: Path | None = None,
    regenerate_derived: bool = False,
    only_pages: list[str] | None = None,
) -> dict[str, Any]:
    plan_path = plan_path.resolve()
    plan = _load_json_object(plan_path)
    root = _resolve_root(plan.get("source_root"), novel_dir)
    plan_pages = plan.get("pages")
    if not isinstance(plan_pages, list):
        raise MigrationConflict("計画のpagesが配列ではありません")
    selected_paths = None
    if only_pages:
        selected_paths = {
            _resolve_entry_path(raw_path, root) for raw_path in only_pages
        }
    elif sum(1 for entry in plan_pages if isinstance(entry, dict) and entry.get("status") == "proposed") > 1:
        raise MigrationConflict(
            "複数ページのapplyには --only-page を指定してください（作品一括移行はしません）"
        )
    entries = _load_apply_entries(plan, plan_path, root, selected_paths=selected_paths)
    if not entries:
        return {
            "status": "no_change",
            "plan_path": plan_path.as_posix(),
            "source_root": root.as_posix(),
            "pages": [],
            "derived": {"requested": regenerate_derived, "regenerated": []},
        }

    backup_root = root / BACKUP_DIR_NAME / f"plan_{_plan_digest(plan_path)}"
    page_records: list[dict[str, Any]] = []
    for item in entries:
        target: Path = item["target"]
        backup = backup_root / "pages" / item["relative_path"]
        _backup_existing_file(target, backup)
        page_records.append(
            {
                "path": item["relative_path"],
                "target": target,
                "backup_path": _relative_path(backup, root),
                "backup": backup,
                "current_bytes": item["current_bytes"],
                "source_sha256": item["entry"]["source_sha256"],
                "source_raw_sha256": item["entry"]["source_raw_sha256"],
                "proposed_sha256": item["entry"]["proposed_sha256"],
                "proposed_data": item["proposed_data"],
            }
        )

    if regenerate_derived and not plan.get("derived_artifacts"):
        raise MigrationConflict(
            "派生物再生成には作品フォルダ付きのdry-run計画が必要です"
        )
    derived_specs = _derived_specs(root, entries) if regenerate_derived else []
    planned_derived = {
        str(item.get("path")): item
        for item in plan.get("derived_artifacts", [])
        if isinstance(item, dict)
    }
    for spec in derived_specs:
        spec["root"] = root
        spec["inputs_abs"] = [root / path for path in spec["inputs"]]
        planned = planned_derived.get(spec["path"])
        if planned is None:
            raise MigrationConflict(f"派生物が計画にありません: {spec['path']}")
        input_hashes = planned.get("input_raw_sha256")
        if not isinstance(input_hashes, dict):
            raise MigrationConflict(f"派生物入力hashが計画にありません: {spec['path']}")
        for input_path in spec["inputs"]:
            expected = input_hashes.get(input_path)
            current_input = root / input_path
            if not isinstance(expected, str) or not current_input.is_file():
                raise MigrationConflict(f"派生物入力が計画と一致しません: {input_path}")
            if raw_hash(current_input) != expected:
                raise MigrationConflict(f"派生物入力が外部変更されています: {input_path}")
        spec["previous_exists"] = spec["target"].is_file()
        if spec["target"].exists() and not spec["previous_exists"]:
            raise MigrationConflict(f"派生物出力先がファイルではありません: {spec['target']}")
        spec["previous_bytes"] = spec["target"].read_bytes() if spec["previous_exists"] else b""
        if spec["previous_exists"]:
            backup = backup_root / "derived" / spec["path"]
            _backup_existing_file(spec["target"], backup)
            spec["backup"] = backup
            spec["backup_path"] = _relative_path(backup, root)

    applied: list[dict[str, Any]] = []
    try:
        for record in page_records:
            if raw_hash(record["target"]) != record["source_raw_sha256"]:
                raise MigrationConflict(
                    f"apply直前に対象ページが変更されています: {record['target']}"
                )
            atomic_write_text(record["target"], yaml_text(record["proposed_data"]))
            applied.append(record)
        if derived_specs:
            for spec in derived_specs:
                target = spec["target"]
                if spec["previous_exists"]:
                    if raw_hash(target) != hashlib.sha256(spec["previous_bytes"]).hexdigest():
                        raise MigrationConflict(f"apply直前に派生物が変更されています: {target}")
                elif target.exists():
                    raise MigrationConflict(f"apply直前に派生物出力先が出現しました: {target}")
            _regenerate_markdown(derived_specs)

        manifest_path = backup_root / "apply-manifest.json"
        manifest_pages = []
        for record in page_records:
            manifest_pages.append(
                {
                    "path": record["path"],
                    "backup_path": record["backup_path"],
                    "source_sha256": record["source_sha256"],
                    "source_raw_sha256": record["source_raw_sha256"],
                    "applied_sha256": record["proposed_sha256"],
                    "applied_raw_sha256": raw_hash(record["target"]),
                }
            )
        manifest_derived = []
        for spec in derived_specs:
            manifest_derived.append(
                {
                    "kind": spec["kind"],
                    "path": spec["path"],
                    "inputs": spec["inputs"],
                    "previous_exists": spec["previous_exists"],
                    "previous_raw_sha256": (
                        hashlib.sha256(spec["previous_bytes"]).hexdigest()
                        if spec["previous_exists"]
                        else None
                    ),
                    "backup_path": spec.get("backup_path"),
                    "applied_raw_sha256": raw_hash(spec["target"]),
                }
            )
        manifest = {
            "tool": "novel_manga_ir_migrate",
            "tool_version": MIGRATOR_VERSION,
            "operation": "apply",
            "plan_path": plan_path.as_posix(),
            "source_root": root.as_posix(),
            "backup_root": _relative_path(backup_root, root),
            "pages": manifest_pages,
            "derived": manifest_derived,
        }
        atomic_write_text(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    except Exception:
        _rollback_pages(applied)
        _rollback_derived(derived_specs)
        raise

    return {
        "status": "applied",
        "plan_path": plan_path.as_posix(),
        "source_root": root.as_posix(),
        "backup_manifest": _relative_path(manifest_path, root),
        "pages": manifest_pages,
        "derived": {
            "requested": regenerate_derived,
            "regenerated": [item["path"] for item in manifest_derived],
            "deferred": [] if regenerate_derived else ["compatible Markdown export"],
        },
    }


def restore_manifest(manifest_path: Path, *, novel_dir: Path | None = None) -> dict[str, Any]:
    manifest_path = manifest_path.resolve()
    manifest = _load_json_object(manifest_path)
    if manifest.get("tool") != "novel_manga_ir_migrate" or manifest.get("operation") != "apply":
        raise MigrationConflict("apply manifestではありません")
    root = _resolve_root(manifest.get("source_root"), novel_dir)
    page_items = manifest.get("pages")
    derived_items = manifest.get("derived")
    if not isinstance(page_items, list) or not isinstance(derived_items, list):
        raise MigrationConflict("apply manifestのpages/derivedが配列ではありません")

    restore_items: list[dict[str, Any]] = []
    for item in page_items:
        target = _resolve_entry_path(str(item.get("path", "")), root)
        backup = _resolve_entry_path(str(item.get("backup_path", "")), root)
        if not target.is_file() or raw_hash(target) != item.get("applied_raw_sha256"):
            raise MigrationConflict(f"復元前の対象ページが変更されています: {target}")
        if not backup.is_file() or raw_hash(backup) != item.get("source_raw_sha256"):
            raise MigrationConflict(f"退避ページが一致しません: {backup}")
        restore_items.append({"target": target, "backup": backup, "current": target.read_bytes()})

    restore_derived: list[dict[str, Any]] = []
    for item in derived_items:
        target = _resolve_entry_path(str(item.get("path", "")), root)
        applied_sha = item.get("applied_raw_sha256")
        if not target.is_file() or raw_hash(target) != applied_sha:
            raise MigrationConflict(f"復元前の派生物が変更されています: {target}")
        previous_exists = bool(item.get("previous_exists"))
        backup_value = item.get("backup_path")
        backup = _resolve_entry_path(str(backup_value), root) if backup_value else None
        previous_bytes = b""
        if previous_exists:
            if backup is None or not backup.is_file():
                raise MigrationConflict(f"派生物の退避がありません: {target}")
            previous_bytes = backup.read_bytes()
            if hashlib.sha256(previous_bytes).hexdigest() != item.get("previous_raw_sha256"):
                raise MigrationConflict(f"派生物の退避が一致しません: {backup}")
        restore_derived.append(
            {
                "target": target,
                "previous_exists": previous_exists,
                "previous_bytes": previous_bytes,
                "current": target.read_bytes(),
                "path": item.get("path"),
            }
        )

    written_pages: list[dict[str, Any]] = []
    try:
        for item in restore_items:
            atomic_write_bytes(item["target"], item["backup"].read_bytes())
            written_pages.append(item)
        for item in restore_derived:
            if item["previous_exists"]:
                atomic_write_bytes(item["target"], item["previous_bytes"])
            else:
                item["target"].unlink()
    except Exception:
        for item in written_pages:
            _rollback_pages([{"target": item["target"], "current_bytes": item["current"]}])
        for item in restore_derived:
            atomic_write_bytes(item["target"], item["current"])
        raise

    for item, manifest_item in zip(restore_items, page_items, strict=True):
        if raw_hash(item["target"]) != manifest_item["source_raw_sha256"]:
            raise MigrationConflict(f"復元後のhash確認に失敗しました: {item['target']}")
    for item, manifest_item in zip(restore_derived, derived_items, strict=True):
        if item["previous_exists"]:
            if raw_hash(item["target"]) != manifest_item["previous_raw_sha256"]:
                raise MigrationConflict(f"派生物の復元後hash確認に失敗しました: {item['target']}")
        elif item["target"].exists():
            raise MigrationConflict(f"派生物の復元後削除確認に失敗しました: {item['target']}")
    return {
        "status": "restored",
        "manifest_path": manifest_path.as_posix(),
        "source_root": root.as_posix(),
        "pages": [item.get("path") for item in page_items],
        "derived": [item.get("path") for item in derived_items],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="漫画IR schema 1.0 -> 1.1 のdry-run、hash付きapply、復元"
    )
    parser.add_argument("novel_dir", nargs="?", type=Path, help="作品フォルダ")
    parser.add_argument("--manga-page", action="append", default=[], help="対象ページYAML")
    parser.add_argument("--to-version", choices=["1.1"], default="1.1")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="正本を書き換えず差分計画を出力")
    mode.add_argument("--apply-plan", type=Path, help="既存のdry-run計画をhash検証して適用")
    mode.add_argument("--restore-manifest", type=Path, help="apply manifestからhash検証して復元")
    parser.add_argument(
        "--only-page",
        action="append",
        default=[],
        help="apply対象を計画内のページに限定（複数指定可。作品一括移行を防ぐ）",
    )
    parser.add_argument("--regenerate-derived", action="store_true", help="apply後に互換Markdownを再生成")
    parser.add_argument("--output", type=Path, help="計画またはapply/復元結果JSONの保存先")
    args = parser.parse_args(argv)

    if args.regenerate_derived and not args.apply_plan:
        parser.error("--regenerate-derived は --apply-plan と併用してください")

    if args.apply_plan:
        if args.manga_page:
            parser.error("--apply-plan では --manga-page を指定できません")
        try:
            result = apply_plan(
                args.apply_plan,
                novel_dir=args.novel_dir,
                regenerate_derived=bool(args.regenerate_derived),
                only_pages=args.only_page,
            )
        except Exception as exc:
            print(f"Migration apply failed: {exc}", file=sys.stderr)
            return 2
        rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered, encoding="utf-8")
        print(rendered, end="")
        return 0

    if args.restore_manifest:
        if args.manga_page or args.regenerate_derived or args.only_page:
            parser.error("--restore-manifest ではページ指定・派生物再生成・apply対象指定を使えません")
        try:
            result = restore_manifest(args.restore_manifest, novel_dir=args.novel_dir)
        except Exception as exc:
            print(f"Migration restore failed: {exc}", file=sys.stderr)
            return 2
        rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered, encoding="utf-8")
        print(rendered, end="")
        return 0

    if args.only_page:
        parser.error("--only-page は --apply-plan と併用してください")
    if not args.dry_run:
        parser.error("計画作成には --dry-run、適用には --apply-plan、復元には --restore-manifest が必要です")

    novel_dir = args.novel_dir
    if novel_dir is not None and not novel_dir.is_absolute():
        novel_dir = (repo_root() / novel_dir).resolve()
    try:
        paths = page_paths(novel_dir, args.manga_page)
    except Exception as exc:
        parser.error(str(exc))

    pages = []
    for path in paths:
        try:
            entry = migrate_page(path)
            if novel_dir is not None:
                try:
                    entry["path"] = path.relative_to(novel_dir).as_posix()
                except ValueError:
                    pass
        except Exception as exc:
            entry = {"path": path.as_posix(), "status": "error", "errors": [str(exc)]}
        pages.append(entry)

    derived_artifacts: list[dict[str, Any]] = []
    if novel_dir is not None:
        derived_seen: set[str] = set()
        for path in paths:
            stem = _manga_stem(path)
            output = f"manga/{stem}.md"
            if output in derived_seen:
                continue
            derived_seen.add(output)
            source_pages = sorted((novel_dir / "manga" / "pages").glob(f"{stem}_p*.yaml"))
            derived_artifacts.append(
                {
                    "kind": "markdown_export",
                    "path": output,
                    "inputs": [
                        page.relative_to(novel_dir).as_posix() for page in source_pages
                    ],
                    "input_raw_sha256": {
                        page.relative_to(novel_dir).as_posix(): raw_hash(page)
                        for page in source_pages
                    },
                    "requires_opt_in": "--regenerate-derived",
                }
            )

    plan = {
        "tool": "novel_manga_ir_migrate",
        "tool_version": MIGRATOR_VERSION,
        "plan_format_version": PLAN_FORMAT_VERSION,
        "target_schema": args.to_version,
        "dry_run": True,
        "apply_supported": True,
        "source_root": novel_dir.as_posix() if novel_dir is not None else None,
        "derived_artifacts": derived_artifacts,
        "pages": pages,
    }
    rendered = json.dumps(plan, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 1 if any(page.get("status") == "error" for page in pages) else 0


if __name__ == "__main__":
    raise SystemExit(main())
