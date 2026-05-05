"""Tests for manga_tag_step2-aligned Step2 string replacement."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_TOOLS = Path(__file__).resolve().parents[2]
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

import manga_prompt_ir.step2_paraphrase as step2_mod  # noqa: E402

from manga_prompt_ir.step2_paraphrase import (  # noqa: E402
    apply_step2_paraphrase,
    load_replacement_pairs,
    resolve_default_rules_path,
    resolve_step2_paraphrase_flag,
)


def test_apply_whole_text_replaces_entire_body_when_avoid_matches() -> None:
    rules = [
        ("長いフレーズABC", "短い"),
        ("殴りかかる", "腕を振りかぶる構図"),
    ]
    assert apply_step2_paraphrase("人物が殴りかかる", rules=rules) == "腕を振りかぶる構図"
    assert apply_step2_paraphrase("長いフレーズABCと短い", rules=rules) == "短い"


def test_longer_avoid_matched_first_whole_text() -> None:
    """長い avoid を先に試すため、aaaa は aaa にマッチし本文全体が Y になる。"""
    rules = [("aa", "X"), ("aaa", "Y")]
    assert apply_step2_paraphrase("aaaa", rules=rules) == "Y"


def test_substring_mode_legacy_partial_replace() -> None:
    rules = [
        ("長いフレーズABC", "短い"),
        ("殴りかかる", "腕を振りかぶる構図"),
    ]
    assert (
        apply_step2_paraphrase("人物が殴りかかる", rules=rules, apply_mode="substring")
        == "人物が腕を振りかぶる構図"
    )
    assert (
        apply_step2_paraphrase("長いフレーズABCと短い", rules=rules, apply_mode="substring")
        == "短いと短い"
    )


def test_substring_longer_avoid_first() -> None:
    rules = [("aa", "X"), ("aaa", "Y")]
    assert apply_step2_paraphrase("aaaa", rules=rules, apply_mode="substring") == "Ya"


def test_default_yaml_loads_whole_text() -> None:
    bundled = _TOOLS / "manga_prompt_ir" / "data" / "step2_paraphrase_rules.yaml"
    pairs = load_replacement_pairs(bundled)
    assert pairs, "step2_paraphrase_rules.yaml should define replacements"
    sample = "腰に跨っている人物"
    out = apply_step2_paraphrase(sample, rules=pairs)
    assert out == "上に乗っている"
    assert "跨っ" not in out


@pytest.mark.parametrize(
    ("yes", "no", "expected"),
    [
        (False, False, None),
        (True, False, True),
        (False, True, False),
        (True, True, False),
    ],
)
def test_resolve_flag(yes: bool, no: bool, expected: bool | None) -> None:
    assert resolve_step2_paraphrase_flag(yes, no) == expected


def test_resolve_default_prefers_howto(tmp_path, monkeypatch) -> None:
    root = tmp_path
    (root / "_how_to").mkdir()
    howto = root / "_how_to" / "step2_paraphrase_rules.yaml"
    howto.write_text(
        "apply_mode: whole_text\nreplacements:\n  - avoid: hello\n    use: hi\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(step2_mod, "repo_root", lambda: root)
    monkeypatch.delenv("MONOCRI_STEP2_PARAPHRASE_RULES", raising=False)
    assert resolve_default_rules_path().resolve() == howto.resolve()


def test_resolve_default_env_overrides_howto(tmp_path, monkeypatch) -> None:
    root = tmp_path
    (root / "_how_to").mkdir()
    (root / "_how_to" / "step2_paraphrase_rules.yaml").write_text(
        "replacements:\n  - avoid: x\n    use: y\n",
        encoding="utf-8",
    )
    custom = root / "my_rules.yaml"
    custom.write_text("replacements: []\n", encoding="utf-8")
    monkeypatch.setattr(step2_mod, "repo_root", lambda: root)
    monkeypatch.setenv("MONOCRI_STEP2_PARAPHRASE_RULES", str(custom))
    assert resolve_default_rules_path().resolve() == custom.resolve()
