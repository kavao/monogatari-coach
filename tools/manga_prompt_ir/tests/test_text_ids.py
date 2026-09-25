from __future__ import annotations

from manga_prompt_ir.text_ids import assigned_text_id


def test_assigned_text_id_uses_explicit_value() -> None:
    assert assigned_text_id({"text_id": "keep-me"}, panel_id=2, kind="dialogue", index=1) == "keep-me"


def test_assigned_text_id_fallback_is_page_local() -> None:
    assert assigned_text_id({}, panel_id=2, kind="dialogue", index=1) == "p2-dialogue-01"
    assert assigned_text_id(None, panel_id=10, kind="narration", index=2) == "p10-narration-02"
