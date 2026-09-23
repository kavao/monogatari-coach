from __future__ import annotations

from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from book_package.review import review_package  # noqa: E402


FIXTURES = ROOT / "tools" / "fixtures" / "book_package"


def _make_package(tmp_path: Path) -> Path:
    package = tmp_path / "001_test"
    package.mkdir()
    shutil.copy(FIXTURES / "book.yaml", package / "book.yaml")
    shutil.copy(FIXTURES / "rights.yaml", package / "rights.yaml")
    (package / "book_matter" / "frontmatter").mkdir(parents=True)
    (package / "book_matter" / "backmatter").mkdir(parents=True)
    (package / "_novel_text").mkdir()
    (package / "book_matter" / "frontmatter" / "characters.md").write_text(
        "# 登場人物\n<!-- illustration: illust_cover -->\n", encoding="utf-8"
    )
    (package / "book_matter" / "backmatter" / "afterword.md").write_text(
        "# あとがき\n", encoding="utf-8"
    )
    (package / "_novel_text" / "novel_text01.md").write_text(
        "<!-- scene: ch01-003 -->\n本文\n", encoding="utf-8"
    )
    return package


def test_writing_review_accepts_incomplete_export_metadata(tmp_path: Path) -> None:
    package = _make_package(tmp_path)

    result = review_package(package, gate="writing", target="paper")

    assert result.has_errors is False
    assert {finding.rule for finding in result.findings} >= {"P-C01", "P-R02"}
    assert all(
        finding.severity != "error"
        for finding in result.findings
        if finding.rule == "P-C01"
    )


def test_export_review_requires_colophon_rights_and_ebook_cover(tmp_path: Path) -> None:
    package = _make_package(tmp_path)

    result = review_package(package, gate="export", target="ebook")

    errors = {finding.rule for finding in result.findings if finding.severity == "error"}
    assert {"P-C01", "P-R01", "P-E01"} <= errors


def test_export_review_uses_rights_copyright_fallback(tmp_path: Path) -> None:
    package = _make_package(tmp_path)
    rights_path = package / "rights.yaml"
    rights_path.write_text(
        rights_path.read_text(encoding="utf-8").replace('notice: "© 2026 著者名"', "notice: null"),
        encoding="utf-8",
    )

    result = review_package(package, gate="export", target="paper")

    assert any(
        finding.rule == "P-C02" and finding.severity == "error"
        for finding in result.findings
    )


def test_review_rejects_unknown_illustration_directive(tmp_path: Path) -> None:
    package = _make_package(tmp_path)
    (package / "book_matter" / "frontmatter" / "characters.md").write_text(
        "<!-- illustration: illust_missing -->", encoding="utf-8"
    )

    result = review_package(package)

    assert any(
        finding.rule == "P-I05" and finding.severity == "error"
        for finding in result.findings
    )
