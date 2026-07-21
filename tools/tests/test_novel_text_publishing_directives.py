from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import novel_char_count  # noqa: E402
import novel_text_rewrite_lint  # noqa: E402


def test_character_count_excludes_publishing_directives_only() -> None:
    text = (
        "<!-- scene: ch01-002 -->\n"
        "本文\n"
        "<!-- illustration: illust_001 -->\n"
    )

    assert novel_char_count.count_chars(text, strip_fm=True) == len("本文\n")

    regular_comment = "<!-- editorial note -->\n本文\n"
    assert novel_char_count.count_chars(regular_comment, strip_fm=True) == len(regular_comment)


def test_rewrite_lint_skips_publishing_directive_lines() -> None:
    assert novel_text_rewrite_lint.should_skip_line("<!-- scene: ch01-002 -->", [])
    assert novel_text_rewrite_lint.should_skip_line(
        "<!-- illustration: illust_001 -->", []
    )
    assert not novel_text_rewrite_lint.should_skip_line("<!-- editorial note -->", [])
