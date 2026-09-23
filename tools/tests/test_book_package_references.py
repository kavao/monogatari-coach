from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from book_package.references import (  # noqa: E402
    extract_illustration_directives,
    extract_scene_anchors,
)


def test_extract_scene_anchors_preserves_logical_chapter_and_sequence() -> None:
    anchors = extract_scene_anchors(
        "<!-- scene: ch01-003 -->\n本文\n<!-- scene: ch01-010 -->"
    )
    assert [(anchor.id, anchor.chapter_id, anchor.sequence) for anchor in anchors] == [
        ("ch01-003", "ch01", 3),
        ("ch01-010", "ch01", 10),
    ]


def test_extract_illustration_directives_reads_publication_ids() -> None:
    directives = extract_illustration_directives(
        "# 登場人物\n<!-- illustration: illust_character_nanashi -->"
    )
    assert [directive.illustration_id for directive in directives] == [
        "illust_character_nanashi"
    ]
