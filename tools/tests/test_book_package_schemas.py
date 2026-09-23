from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys

import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from book_package.schemas import (  # noqa: E402
    BookPackage,
    ManuscriptEntry,
    load_book_package,
    load_rights_package,
)


FIXTURES = ROOT / "tools" / "fixtures" / "book_package"


def test_load_phase1_package_fixtures() -> None:
    book = load_book_package(FIXTURES / "book.yaml")
    rights = load_rights_package(FIXTURES / "rights.yaml")

    assert book.book.title == "銀のスライムは洞窟で王になる"
    assert book.manuscript.frontmatter[0].id == "characters"
    assert book.manuscript.chapters[0].source_files() == [
        "_novel_text/novel_text01.md"
    ]
    assert rights.assets["illust_cover"].usage["ebook"].permission == "unconfirmed"


def test_itemized_chapter_uses_ordered_files() -> None:
    entry = ManuscriptEntry(
        id="ch01",
        title="第一章",
        files=["_novel_text/novel_text01_1.md", "_novel_text/novel_text01_2.md"],
    )
    assert entry.source_files() == [
        "_novel_text/novel_text01_1.md",
        "_novel_text/novel_text01_2.md",
    ]


def test_entry_rejects_file_and_files_together() -> None:
    with pytest.raises(ValidationError, match="exactly one"):
        ManuscriptEntry(
            id="ch01",
            title="第一章",
            file="_novel_text/novel_text01.md",
            files=["_novel_text/novel_text01_1.md"],
        )


def test_book_rejects_duplicate_illustration_ids() -> None:
    data = {
        "schema_version": 2,
        "book": {"title": "t", "author": {"name": "a"}},
        "format": {
            "primary": "paperback",
            "writing_direction": "vertical",
            "binding": "right",
            "trim_size": "文庫",
        },
        "manuscript": {
            "chapters": [{"id": "ch01", "title": "第一章", "file": "a.md"}]
        },
        "illustrations": [
            {
                "id": "illust_cover",
                "type": "cover",
                "color": True,
                "brief": "表紙",
                "status": "planned",
            },
            {
                "id": "illust_cover",
                "type": "cover",
                "color": True,
                "brief": "別表紙",
                "status": "planned",
            },
        ],
    }
    with pytest.raises(ValidationError, match="must be unique"):
        BookPackage.model_validate(data)


def test_book_preserves_a_publication_timestamp() -> None:
    data = {
        "schema_version": 2,
        "book": {"title": "t", "author": {"name": "a"}},
        "format": {
            "primary": "paperback",
            "writing_direction": "vertical",
            "binding": "right",
            "trim_size": "B5",
        },
        "manuscript": {
            "chapters": [{"id": "ch01", "title": "第一章", "file": "a.md"}]
        },
        "colophon": {"publish_date": "2026-03-14T00:05:08+09:00"},
    }

    book = BookPackage.model_validate(data)

    assert book.colophon.publish_date == datetime.fromisoformat("2026-03-14T00:05:08+09:00")
