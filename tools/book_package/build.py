"""Resolve a locked paper package into a renderer-neutral build manifest."""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import struct
from typing import Any, Literal

import yaml

from .diff import LockDiffError, diff_against_lock
from .paths import (
    ManuscriptSource,
    apply_manuscript_source,
    resolve_manuscript_source,
    resolve_package_path,
)
from .references import extract_illustration_directives
from .review import review_package
from .schemas import BookPackage, load_book_package


Target = Literal["paper"]
ProfileName = Literal["jis_b5", "bunko"]

JIS_B5_WIDTH_MM = 182.0
JIS_B5_HEIGHT_MM = 257.0
# ISO A6。日本の文庫本仕上がりに近い寸法として proof 用に使う。
BUNKO_WIDTH_MM = 105.0
BUNKO_HEIGHT_MM = 148.0
POINTS_PER_MM = 72.0 / 25.4

_SCENE_DIRECTIVE = re.compile(r"^\s*<!--\s*scene:\s*ch\d{2,}-\d{3,}\s*-->\s*$")


class BuildError(ValueError):
    """A locked package cannot be rendered safely."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def profile_definition(name: ProfileName) -> dict[str, Any]:
    if name == "jis_b5":
        return {
            "name": name,
            "trim_size": "JIS B5",
            "width_mm": JIS_B5_WIDTH_MM,
            "height_mm": JIS_B5_HEIGHT_MM,
            "writing_direction": "vertical",
            "proof_only": True,
            "margins_mm": {
                "top": 18.0,
                "bottom": 18.0,
                "inner": 18.0,
                "outer": 15.0,
            },
            "minimum_image_dpi": 250,
        }
    if name == "bunko":
        return {
            "name": name,
            "trim_size": "文庫（ISO A6）",
            "width_mm": BUNKO_WIDTH_MM,
            "height_mm": BUNKO_HEIGHT_MM,
            "writing_direction": "vertical",
            "proof_only": True,
            "margins_mm": {
                "top": 12.0,
                "bottom": 12.0,
                "inner": 14.0,
                "outer": 11.0,
            },
            "minimum_image_dpi": 250,
        }
    raise BuildError(f"Unsupported paper profile: {name}")


def png_dimensions(path: Path) -> tuple[int, int]:
    """Return PNG pixel dimensions without depending on an image library."""

    with path.open("rb") as handle:
        header = handle.read(24)
    if header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        raise BuildError(f"PNG ファイルではありません: {path}")
    return struct.unpack(">II", header[16:24])


def _load_lock(lock_path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(lock_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise BuildError(f"book.lock.yaml を読み込めません: {exc}") from exc
    if not isinstance(data, dict):
        raise BuildError("book.lock.yaml のルートは mapping である必要があります。")
    return data


def _ensure_clean_lock(
    package_root: Path,
    target: Target,
    *,
    manuscript_source: ManuscriptSource,
) -> dict[str, Any]:
    lock_path = package_root / "book.lock.yaml"
    if not lock_path.is_file():
        raise BuildError("PDF を作る前に book_lock.py で入力一式を lock してください。")
    lock = _load_lock(lock_path)
    if lock.get("export_target") != target:
        actual = lock.get("export_target")
        raise BuildError(f"book.lock.yaml の対象が {target} ではありません: {actual}")
    locked_source = lock.get("manuscript_source", "novel_text")
    if locked_source != manuscript_source:
        raise BuildError(
            "book.lock.yaml の manuscript_source が一致しません: "
            f"lock={locked_source} requested={manuscript_source}。"
            "同じ --manuscript-source で book_lock.py を再実行してください。"
        )
    try:
        delta = diff_against_lock(package_root, manuscript_source=manuscript_source)
    except (LockDiffError, ValueError) as exc:
        raise BuildError(f"book.lock.yaml と入力一式を比較できません: {exc}") from exc
    if any(delta.values()):
        changed = ", ".join(
            path for group in ("added", "removed", "changed") for path in delta[group]
        )
        raise BuildError(
            "book.lock.yaml 作成後に入力一式が変わっています。"
            f" book_diff.py を確認して再 lock してください: {changed}"
        )
    return lock


def _blocks_from_text(text: str) -> list[dict[str, str]]:
    blocks: list[dict[str, str]] = []
    paragraph: list[str] = []

    def flush_paragraph() -> None:
        if paragraph:
            blocks.append({"kind": "paragraph", "text": "\n".join(paragraph)})
            paragraph.clear()

    for raw_line in text.splitlines():
        directives = extract_illustration_directives(raw_line)
        if directives:
            flush_paragraph()
            blocks.extend(
                {"kind": "illustration", "illustration_id": directive.illustration_id}
                for directive in directives
            )
            continue
        if _SCENE_DIRECTIVE.fullmatch(raw_line):
            flush_paragraph()
            continue
        stripped = raw_line.strip()
        if not stripped:
            flush_paragraph()
            continue
        if stripped == "---":
            flush_paragraph()
            blocks.append({"kind": "rule"})
            continue
        if stripped.startswith("#"):
            flush_paragraph()
            blocks.append({"kind": "heading", "text": stripped.lstrip("#").strip()})
            continue
        paragraph.append(raw_line.rstrip())
    flush_paragraph()
    return blocks


def _approved_illustrations(package_root: Path, book: BookPackage) -> dict[str, dict[str, Any]]:
    approved: dict[str, dict[str, Any]] = {}
    for illustration in book.illustrations:
        if illustration.status != "approved" or illustration.asset is None:
            continue
        asset = resolve_package_path(package_root, illustration.asset)
        if not asset.is_file():
            raise BuildError(f"採用済み挿絵がありません: {illustration.id} ({illustration.asset})")
        try:
            width_px, height_px = png_dimensions(asset)
        except BuildError:
            width_px = height_px = 0
        approved[illustration.id] = {
            "id": illustration.id,
            "type": illustration.type,
            "asset": illustration.asset,
            "width_px": width_px,
            "height_px": height_px,
        }
    return approved


def build_manifest(
    package_root: str | Path,
    *,
    target: Target = "paper",
    profile: ProfileName = "jis_b5",
    manuscript_source: ManuscriptSource | None = None,
) -> dict[str, Any]:
    """Resolve a clean Phase 1 lock into a renderer-neutral paper manifest."""

    root = Path(package_root).resolve()
    book = load_book_package(root / "book.yaml")
    resolved_source = resolve_manuscript_source(
        cli=manuscript_source, book_source=book.manuscript.source
    )
    review = review_package(
        root, gate="export", target=target, manuscript_source=resolved_source
    )
    if review.has_errors:
        errors = "; ".join(
            f"{finding.rule}: {finding.message}"
            for finding in review.findings
            if finding.severity == "error"
        )
        raise BuildError(f"export review に error があります: {errors}")

    lock_path = root / "book.lock.yaml"
    lock = _ensure_clean_lock(root, target, manuscript_source=resolved_source)
    illustrations = _approved_illustrations(root, book)

    entries: list[dict[str, Any]] = []
    for section, declarations in (
        ("frontmatter", book.manuscript.frontmatter),
        ("chapters", book.manuscript.chapters),
        ("backmatter", book.manuscript.backmatter),
    ):
        for entry in declarations:
            files: list[dict[str, Any]] = []
            for declared_path in entry.source_files():
                source_path = apply_manuscript_source(declared_path, resolved_source)
                source = resolve_package_path(root, source_path)
                text = source.read_text(encoding="utf-8")
                files.append(
                    {
                        "path": source_path,
                        "sha256": sha256_file(source),
                        "blocks": _blocks_from_text(text),
                    }
                )
            entries.append(
                {
                    "section": section,
                    "id": entry.id,
                    "title": entry.title,
                    "start_page_policy": entry.start_page_policy,
                    "files": files,
                }
            )

    referenced_ids = {
        block["illustration_id"]
        for entry in entries
        for source in entry["files"]
        for block in source["blocks"]
        if block["kind"] == "illustration"
    }
    missing = sorted(referenced_ids - illustrations.keys())
    if missing:
        raise BuildError(
            "本文で参照された挿絵は status: approved と asset が必要です: "
            + ", ".join(missing)
        )

    return {
        "manifest_version": 1,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "target": target,
        "profile": profile_definition(profile),
        "package": {
            "root": root.as_posix(),
            "title": book.book.title,
            "author": book.book.author.model_dump(mode="json"),
            "writing_direction": book.format.writing_direction,
        },
        "lock": {
            "path": "book.lock.yaml",
            "sha256": sha256_file(lock_path),
            "generated_at": lock.get("generated_at"),
            "export_target": lock.get("export_target"),
            "manuscript_source": resolved_source,
        },
        "entries": entries,
        "illustrations": [illustrations[key] for key in sorted(illustrations)],
        "review": {
            "errors": sum(finding.severity == "error" for finding in review.findings),
            "warnings": sum(finding.severity == "warning" for finding in review.findings),
        },
        "placements": [],
    }


def write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
