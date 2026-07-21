from __future__ import annotations

from pathlib import Path
import shutil
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from book_package.diff import diff_against_lock  # noqa: E402
from book_package.lock import LockError, write_lock  # noqa: E402
from book_package.review import review_package  # noqa: E402


FIXTURES = ROOT / "tools" / "fixtures" / "book_package"


def _make_lockable_package(tmp_path: Path) -> Path:
    package = tmp_path / "001_test"
    package.mkdir()
    book_yaml = (FIXTURES / "book.yaml").read_text(encoding="utf-8")
    book_yaml = book_yaml.replace("publish_date: null", "publish_date: 2026-09-13")
    book_yaml = book_yaml.replace("publisher: null", 'publisher: "サークル名"')
    book_yaml = book_yaml.replace("contact: null", 'contact: "contact@example.com"')
    book_yaml = book_yaml.replace(
        "    status: planned\n    asset: null\n  - id: illust_001",
        "    status: approved\n    asset: illustrations/_assets/illustration_00/cover.png\n  - id: illust_001",
        1,
    )
    (package / "book.yaml").write_text(book_yaml, encoding="utf-8")
    shutil.copy(FIXTURES / "rights.yaml", package / "rights.yaml")
    (package / "book_matter" / "frontmatter").mkdir(parents=True)
    (package / "book_matter" / "backmatter").mkdir(parents=True)
    (package / "_novel_text").mkdir()
    (package / "illustrations" / "_assets" / "illustration_00").mkdir(parents=True)
    (package / "book_matter" / "frontmatter" / "characters.md").write_text(
        "<!-- illustration: illust_cover -->", encoding="utf-8"
    )
    (package / "book_matter" / "backmatter" / "afterword.md").write_text(
        "# あとがき", encoding="utf-8"
    )
    (package / "_novel_text" / "novel_text01.md").write_text(
        "<!-- scene: ch01-003 -->\n本文", encoding="utf-8"
    )
    (package / "illustrations" / "_assets" / "illustration_00" / "cover.png").write_bytes(
        b"cover"
    )
    return package


def test_lock_writes_reviewed_snapshot_and_clean_diff(tmp_path: Path) -> None:
    package = _make_lockable_package(tmp_path)

    lock_path = write_lock(package, target="paper")

    assert lock_path.is_file()
    payload = diff_against_lock(package)
    assert payload == {"added": [], "removed": [], "changed": []}


def test_diff_reports_changed_manuscript(tmp_path: Path) -> None:
    package = _make_lockable_package(tmp_path)
    write_lock(package, target="paper")
    (package / "_novel_text" / "novel_text01.md").write_text(
        "<!-- scene: ch01-003 -->\n改稿本文", encoding="utf-8"
    )

    payload = diff_against_lock(package)

    assert payload["changed"] == ["_novel_text/novel_text01.md"]


def test_review_warns_when_inputs_changed_since_lock(tmp_path: Path) -> None:
    package = _make_lockable_package(tmp_path)
    write_lock(package, target="paper")
    (package / "_novel_text" / "novel_text01.md").write_text(
        "<!-- scene: ch01-003 -->\n改稿本文", encoding="utf-8"
    )

    result = review_package(package, gate="export", target="paper")

    assert any(
        finding.rule == "P-E02" and finding.severity == "warning"
        for finding in result.findings
    )


def test_lock_refuses_export_gate_errors(tmp_path: Path) -> None:
    package = _make_lockable_package(tmp_path)
    (package / "book.yaml").write_text(
        (package / "book.yaml").read_text(encoding="utf-8").replace(
            "contact: \"contact@example.com\"", "contact: null"
        ),
        encoding="utf-8",
    )

    with pytest.raises(LockError, match="Export-gate"):
        write_lock(package, target="paper")
