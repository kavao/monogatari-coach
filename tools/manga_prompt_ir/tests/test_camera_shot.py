from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

_TOOLS = Path(__file__).resolve().parents[2]
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

from manga_prompt_ir.camera_shot import (  # noqa: E402
    camera_shot_advisories_for_page,
    load_camera_shot_vocab,
    normalize_camera_token,
    resolve_camera_en_token,
)


def _page(panels: list, *, notes: list[str] | None = None, intent: str = "manga_page"):
    return SimpleNamespace(
        meta=SimpleNamespace(intent=intent),
        panels=panels,
        render_instruction=SimpleNamespace(
            user_directives=SimpleNamespace(page_notes=notes or ["hold k1-k2 on purpose"])
        ),
    )


def _panel(
    pid: int,
    *,
    angle_en=None,
    angle=None,
    shot_en=None,
    shot=None,
    view_en=None,
    view=None,
):
    return SimpleNamespace(
        panel_id=pid,
        camera=SimpleNamespace(
            angle=angle,
            angle_en=angle_en,
            shot_size=shot,
            shot_size_en=shot_en,
            view=view,
            view_en=view_en,
        ),
    )


def test_vocab_has_six_angle_and_six_shot_tokens() -> None:
    vocab = load_camera_shot_vocab()
    assert len(vocab["angle_en"]) == 6
    assert len(vocab["shot_size_en"]) == 6
    assert len(vocab["view_en"]) == 6
    assert "eye level" in vocab["angle_en"]
    assert "medium close-up" in vocab["shot_size_en"]
    assert "contact close-up" in vocab["view_en"]


def test_normalize_trim_underscore_and_case() -> None:
    assert normalize_camera_token("  Eye_Level  ") == "eye level"
    assert normalize_camera_token("") is None
    assert normalize_camera_token("close-up") == "close-up"


def test_resolve_prefers_en_and_skips_japanese_legacy() -> None:
    assert (
        resolve_camera_en_token({"angle_en": "low angle", "angle": "あおり"}, "angle_en", "angle")
        == "low angle"
    )
    assert resolve_camera_en_token({"angle": "あおり"}, "angle_en", "angle") is None
    assert resolve_camera_en_token({"angle": "eye level"}, "angle_en", "angle") == "eye level"
    assert resolve_camera_en_token({"angle_en": "  "}, "angle_en", "angle") is None
    assert resolve_camera_en_token({}, "angle_en", "angle") is None


def test_unknown_token_is_advisory_empty_is_not() -> None:
    page = _page(
        [
            _panel(1, angle_en="dutch angle", shot_en="medium shot", view_en="unknown view"),
            _panel(2, angle_en="eye level", shot_en=""),
        ]
    )
    notes = camera_shot_advisories_for_page("p.yaml", page)
    assert any("dutch angle" in item for item in notes)
    assert any("unknown view" in item and "view_en" in item for item in notes)
    assert not any("shot_size_en" in item and "panel 2" in item for item in notes)


def test_adjacent_same_angle_and_shot_is_advisory() -> None:
    page = _page(
        [
            _panel(1, angle_en="eye level", shot_en="medium shot", view_en="solo bust"),
            _panel(2, angle_en="eye_level", shot_en="medium shot", view_en="two faces"),
            _panel(3, angle_en="high angle", shot_en="medium shot"),
        ]
    )
    notes = camera_shot_advisories_for_page("p.yaml", page)
    assert any("panel 1 と panel 2" in item for item in notes)
    assert not any("panel 2 と panel 3" in item for item in notes)


def test_page_notes_do_not_skip_adjacent_match() -> None:
    page = _page(
        [
            _panel(1, angle_en="low angle", shot_en="long shot"),
            _panel(2, angle_en="low angle", shot_en="long shot"),
        ],
        notes=["k1-k2 は意図的に据え置き"],
    )
    notes = camera_shot_advisories_for_page("p.yaml", page)
    assert any("両方同じ" in item for item in notes)


def test_missing_tokens_skip_adjacent_check() -> None:
    page = _page(
        [
            _panel(1, angle_en="eye level", shot_en=None),
            _panel(2, angle_en="eye level", shot_en=None),
        ]
    )
    assert camera_shot_advisories_for_page("p.yaml", page) == []


def test_illustration_intent_is_skipped() -> None:
    page = _page(
        [
            _panel(1, angle_en="eye level", shot_en="medium shot"),
            _panel(2, angle_en="eye level", shot_en="medium shot"),
        ],
        intent="illustration",
    )
    assert camera_shot_advisories_for_page("p.yaml", page) == []


def test_legacy_english_angle_key_is_checked() -> None:
    page = _page(
        [
            _panel(1, angle="worm's eye", shot="full body"),
        ]
    )
    notes = camera_shot_advisories_for_page("p.yaml", page)
    assert any("worm's eye" in item and "angle_en" in item for item in notes)
    assert not any("shot_size_en" in item for item in notes)


def test_legacy_english_view_key_is_checked() -> None:
    page = _page([_panel(1, angle="eye level", shot="full body", view="face to face")])
    notes = camera_shot_advisories_for_page("p.yaml", page)
    assert any("face to face" in item and "view_en" in item for item in notes)


def test_099_manga_04_pilot_has_no_camera_advisories() -> None:
    import yaml

    pages = sorted((_TOOLS.parent / "novels").glob("099_*/manga/pages/manga_04_p*.yaml"))
    if not pages:
        return
    notes: list[str] = []
    for path in pages:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        notes.extend(camera_shot_advisories_for_page(path.as_posix(), data))
    assert notes == []
