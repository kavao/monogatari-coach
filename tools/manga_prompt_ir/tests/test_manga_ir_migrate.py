from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest
import yaml

_TOOLS_ROOT = Path(__file__).resolve().parents[2]
if str(_TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(_TOOLS_ROOT))

from novel_manga_ir_migrate import (  # noqa: E402
    MigrationConflict,
    apply_plan,
    main,
    migrate_page,
    restore_manifest,
)
from novel_prompt_ir_export_md import main as export_main  # noqa: E402


_FIXTURE = _TOOLS_ROOT / "manga_prompt_ir" / "examples" / "manga_provider_direction_fixture.yaml"


def test_migration_dry_run_proposes_ids_and_structured_text_without_writing(tmp_path: Path) -> None:
    page_path = tmp_path / "manga_01_p01.yaml"
    shutil.copy2(_FIXTURE, page_path)
    before = page_path.read_text(encoding="utf-8")

    plan = migrate_page(page_path)

    assert plan["status"] == "proposed"
    assert plan["source_schema"] == "1.0"
    assert plan["proposed_data"]["schema_version"] == "1.1"
    assert plan["proposed_data"]["panels"][0]["subjects"][0]["subject_id"] == "p10-s01"
    assert plan["proposed_data"]["panels"][0]["text"]["dialogue"][0]["text_id"] == (
        "p10-dialogue-01"
    )
    assert isinstance(plan["proposed_data"]["panels"][1]["text"]["monologue"][0], dict)
    assert plan["id_map"]["subjects"][0]["subject_id"] == "p10-s01"
    assert plan["id_map"]["texts"][0]["text_id"] == "p10-dialogue-01"
    assert plan["unresolved"][0]["path"] == "/render_instruction/text_mode"
    assert page_path.read_text(encoding="utf-8") == before


def test_migration_cli_writes_only_the_plan_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    novel_dir = tmp_path / "001_fixture"
    pages_dir = novel_dir / "manga" / "pages"
    pages_dir.mkdir(parents=True)
    page_path = pages_dir / "manga_01_p01.yaml"
    shutil.copy2(_FIXTURE, page_path)
    output = tmp_path / "migration-plan.json"

    rc = main([str(novel_dir), "--dry-run", "--output", str(output)])
    captured = capsys.readouterr()

    assert rc == 0
    assert output.is_file()
    assert json.loads(captured.out)["pages"][0]["status"] == "proposed"
    saved = json.loads(output.read_text(encoding="utf-8"))
    assert saved["apply_supported"] is True
    assert saved["plan_format_version"] == 2
    assert saved["source_root"] == novel_dir.as_posix()
    assert yaml.safe_load(page_path.read_text(encoding="utf-8"))["schema_version"] == "1.0"


def _make_plan(tmp_path: Path) -> tuple[Path, Path, bytes]:
    novel_dir = tmp_path / "001_fixture"
    pages_dir = novel_dir / "manga" / "pages"
    pages_dir.mkdir(parents=True)
    page_path = pages_dir / "manga_01_p01.yaml"
    shutil.copy2(_FIXTURE, page_path)
    before = page_path.read_bytes()
    plan_path = tmp_path / "migration-plan.json"

    assert main([str(novel_dir), "--dry-run", "--output", str(plan_path)]) == 0
    return novel_dir, plan_path, before


def test_migration_apply_is_hash_guarded_and_restorable_with_derived_regeneration(
    tmp_path: Path,
) -> None:
    novel_dir, plan_path, before = _make_plan(tmp_path)
    page_path = novel_dir / "manga" / "pages" / "manga_01_p01.yaml"

    applied = apply_plan(plan_path, regenerate_derived=True)

    assert applied["status"] == "applied"
    assert yaml.safe_load(page_path.read_text(encoding="utf-8"))["schema_version"] == "1.1"
    derived = novel_dir / "manga" / "manga_01.md"
    assert derived.is_file()
    manifest_path = novel_dir / applied["backup_manifest"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    backup_page = novel_dir / manifest["pages"][0]["backup_path"]
    assert backup_page.read_bytes() == before
    assert manifest["derived"][0]["path"] == "manga/manga_01.md"

    restored = restore_manifest(manifest_path)

    assert restored["status"] == "restored"
    assert page_path.read_bytes() == before
    assert not derived.exists()


def test_migration_apply_rejects_stale_source_before_writing(tmp_path: Path) -> None:
    novel_dir, plan_path, _before = _make_plan(tmp_path)
    page_path = novel_dir / "manga" / "pages" / "manga_01_p01.yaml"
    changed = yaml.safe_load(page_path.read_text(encoding="utf-8"))
    changed["meta"]["source_text"] = "外部変更"
    page_path.write_text(yaml.safe_dump(changed, allow_unicode=True, sort_keys=False), encoding="utf-8")
    stale_bytes = page_path.read_bytes()

    with pytest.raises(MigrationConflict, match="raw hash"):
        apply_plan(plan_path)

    assert page_path.read_bytes() == stale_bytes
    assert not (novel_dir / "_manga_ir_backup").exists()


def test_migration_apply_rejects_blocked_pages(tmp_path: Path) -> None:
    novel_dir = tmp_path / "001_fixture"
    pages_dir = novel_dir / "manga" / "pages"
    pages_dir.mkdir(parents=True)
    page_path = pages_dir / "manga_01_p01.yaml"
    page = yaml.safe_load(_FIXTURE.read_text(encoding="utf-8"))
    page["panels"][1]["panel_id"] = page["panels"][0]["panel_id"]
    page_path.write_text(yaml.safe_dump(page, allow_unicode=True, sort_keys=False), encoding="utf-8")
    plan_path = tmp_path / "blocked-plan.json"

    assert main([str(novel_dir), "--dry-run", "--output", str(plan_path)]) == 0
    with pytest.raises(MigrationConflict, match="blocked"):
        apply_plan(plan_path)


def test_migration_apply_requires_explicit_page_selection_for_multiple_pages(tmp_path: Path) -> None:
    novel_dir = tmp_path / "001_fixture"
    pages_dir = novel_dir / "manga" / "pages"
    pages_dir.mkdir(parents=True)
    for name in ("manga_01_p01.yaml", "manga_01_p02.yaml"):
        shutil.copy2(_FIXTURE, pages_dir / name)
    plan_path = tmp_path / "migration-plan.json"

    assert main([str(novel_dir), "--dry-run", "--output", str(plan_path)]) == 0
    with pytest.raises(MigrationConflict, match="--only-page"):
        apply_plan(plan_path)

    applied = apply_plan(plan_path, only_pages=["manga/pages/manga_01_p01.yaml"])

    assert len(applied["pages"]) == 1
    assert yaml.safe_load((pages_dir / "manga_01_p01.yaml").read_text(encoding="utf-8"))["schema_version"] == "1.1"
    assert yaml.safe_load((pages_dir / "manga_01_p02.yaml").read_text(encoding="utf-8"))["schema_version"] == "1.0"


def test_migration_recognizes_schema_1_1_as_up_to_date(tmp_path: Path) -> None:
    page = yaml.safe_load(_FIXTURE.read_text(encoding="utf-8"))
    page["schema_version"] = "1.1"
    path = tmp_path / "page.yaml"
    path.write_text(yaml.safe_dump(page, allow_unicode=True, sort_keys=False), encoding="utf-8")

    plan = migrate_page(path)

    assert plan["status"] == "up_to_date"
    assert plan["changes"] == []


def test_markdown_export_reads_schema_1_1(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    page = yaml.safe_load(_FIXTURE.read_text(encoding="utf-8"))
    page["schema_version"] = "1.1"
    page["dramaturgy"] = {
        "purpose": "手紙の発見で次の選択を予告する",
        "purpose_en": "Foreshadow the next choice through the discovered letter.",
    }
    page["panels"][0]["subjects"][0]["subject_id"] = "p10-s01"
    path = tmp_path / "page.yaml"
    path.write_text(yaml.safe_dump(page, allow_unicode=True, sort_keys=False), encoding="utf-8")

    rc = export_main(["--manga-page", str(path)])
    captured = capsys.readouterr()

    assert rc == 0
    assert "### Step1" in captured.out
    assert "### Schema 1.1 context" in captured.out
    assert "Foreshadow the next choice" in captured.out
    assert "slot_id=p10-s01" in captured.out


def test_migration_blocks_duplicate_panel_ids(tmp_path: Path) -> None:
    page = yaml.safe_load(_FIXTURE.read_text(encoding="utf-8"))
    page["panels"][1]["panel_id"] = page["panels"][0]["panel_id"]
    path = tmp_path / "page.yaml"
    path.write_text(yaml.safe_dump(page, allow_unicode=True, sort_keys=False), encoding="utf-8")

    plan = migrate_page(path)

    assert plan["status"] == "blocked"
    assert plan["changes"] == []
    assert "panel_id" in plan["unresolved"][0]["path"]
