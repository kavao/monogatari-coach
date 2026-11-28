# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_TOOLS_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_TOOLS_ROOT))

from tag_prompt_mask import (  # noqa: E402
    MaskRuleSet,
    apply_mask,
    apply_omit,
    apply_replace,
    mask_rules_from_mapping,
    normalize_tag,
    parse_cli_replace_tags,
    parse_replace_pairs,
)


def test_normalize_tag() -> None:
    assert normalize_tag("  Long Hair ") == "long_hair"
    assert normalize_tag("Blue_Eyes") == "blue_eyes"


def test_apply_replace_simultaneous_no_chain() -> None:
    # A→B と B→C があっても、元が A のトークンは B で止まり C にはならない
    tags, replaced = apply_replace(
        ["a", "x"],
        {"a": "b", "b": "c"},
    )
    assert tags == ["b", "x"]
    assert replaced == [("a", "b")]


def test_apply_replace_expands_comma_separated_to() -> None:
    tags, replaced = apply_replace(
        ["childlike_mature", "keep"],
        {"childlike_mature": "toddler, Short stack, loli"},
    )
    assert tags == ["toddler", "Short stack", "loli", "keep"]
    assert replaced == [("childlike_mature", "toddler, Short stack, loli")]


def test_apply_omit() -> None:
    tags, omitted = apply_omit(["solo", "Long Hair", "1girl"], ["long hair", "solo"])
    assert tags == ["1girl"]
    assert omitted == ["solo", "Long Hair"]


def test_apply_mask_order_replace_then_omit() -> None:
    rules = MaskRuleSet(
        omit_tags=("gone",),
        replace_pairs=(("old", "new"), ("gone_src", "gone")),
    )
    result = apply_mask(["keep", "old", "gone_src", "gone"], rules)
    assert result.tags == ["keep", "new"]
    assert ("old", "new") in result.replaced
    assert ("gone_src", "gone") in result.replaced
    assert "gone" in result.omitted


def test_mask_rules_from_mapping_list_and_dict() -> None:
    from_list = mask_rules_from_mapping(
        {
            "omit_tags": ["a", "a", "b"],
            "replace_tags": [{"from": "Old Token", "to": "new_token"}],
        }
    )
    assert from_list.omit_tags == ("a", "b")
    assert from_list.replace_pairs == (("old_token", "new_token"),)

    from_map = mask_rules_from_mapping({"replace_tags": {"Foo Bar": "baz"}})
    assert from_map.replace_pairs == (("foo_bar", "baz"),)


def test_empty_to_raises() -> None:
    with pytest.raises(ValueError, match="omit_tags"):
        parse_replace_pairs([{"from": "a", "to": ""}])


def test_merge_replace_later_wins() -> None:
    a = MaskRuleSet(replace_pairs=(("x", "one"),), omit_tags=("o1",))
    b = MaskRuleSet(replace_pairs=(("x", "two"), ("y", "z")), omit_tags=("o2",))
    m = a.merge(b)
    assert m.replace_map() == {"x": "two", "y": "z"}
    assert m.omit_tags == ("o1", "o2")


def test_conflict_from_in_omit() -> None:
    rules = MaskRuleSet(
        omit_tags=("bad",),
        replace_pairs=(("bad", "good"),),
    )
    assert rules.conflict_from_in_omit() == ["bad"]


def test_parse_cli_replace_tags() -> None:
    assert parse_cli_replace_tags(["Old=New", "a=b"]) == [
        ("old", "New"),
        ("a", "b"),
    ]
    with pytest.raises(ValueError, match="old=new"):
        parse_cli_replace_tags(["noequals"])


def test_pipe_sides_independent() -> None:
    """左右それぞれに apply_mask する想定のスモーク。"""
    rules = MaskRuleSet(replace_pairs=(("left_only", "L"),), omit_tags=("drop",))
    left = apply_mask(["left_only", "shared"], rules)
    right = apply_mask(["drop", "shared", "right"], rules)
    assert left.tags == ["L", "shared"]
    assert right.tags == ["shared", "right"]


def test_mask_csv_or_pipe_prompt() -> None:
    from tag_prompt_mask import mask_csv_or_pipe_prompt

    rules = MaskRuleSet(
        replace_pairs=(("childlike_mature", "toddler"),),
        omit_tags=("fairy",),
    )
    out, result = mask_csv_or_pipe_prompt(
        "solo, childlike_mature, fairy | black hair, childlike_mature",
        rules,
    )
    assert "toddler" in out
    assert "childlike_mature" not in out
    assert "fairy" not in out
    assert " | " in out
    assert result.replaced


def test_load_novel_mask_rules_fallback(tmp_path: Path) -> None:
    from tag_prompt_mask import load_novel_mask_rules

    novel = tmp_path / "novel"
    novel.mkdir()
    (novel / "_meta.yaml").write_text(
        """
version: 1
character_tag_batch:
  omit_tags: [fairy]
  replace_tags:
    - from: childlike_mature
      to: toddler
manga_tag_batch:
  omit_tags: [extra_omit]
""".strip(),
        encoding="utf-8",
    )
    rules = load_novel_mask_rules(
        novel,
        primary_key="manga_tag_batch",
        fallback_key="character_tag_batch",
    )
    assert "fairy" in rules.omit_tags
    assert "extra_omit" in rules.omit_tags
    assert rules.replace_map()["childlike_mature"] == "toddler"


def test_load_novel_mask_rules_illustration_falls_back_to_character(
    tmp_path: Path,
) -> None:
    from tag_prompt_mask import load_novel_mask_rules

    novel = tmp_path / "novel"
    novel.mkdir()
    (novel / "_meta.yaml").write_text(
        """
version: 1
character_tag_batch:
  omit_tags: [pointed ears]
  replace_tags:
    - from: childlike_mature
      to: toddler, Short stack
""".strip(),
        encoding="utf-8",
    )
    rules = load_novel_mask_rules(
        novel,
        primary_key="illustration_tag_batch",
        fallback_key="character_tag_batch",
    )
    assert "pointed ears" in rules.omit_tags
    assert rules.replace_map()["childlike_mature"] == "toddler, Short stack"


def test_negative_omit_preserves_unmatched_order_and_duplicates() -> None:
    from tag_prompt_mask import apply_negative_omit

    source = "  Child Body, keep, keep, CHILD_BODY, childhood, (child:1.2) "
    assert apply_negative_omit(source, []) == (source, [])
    result, omitted = apply_negative_omit(source, ["child_body", "absent"])
    assert result == "keep, keep, childhood, (child:1.2)"
    assert omitted == ["Child Body", "CHILD_BODY"]


def test_negative_omit_meta_combines_sections_and_rejects_bad_type(tmp_path) -> None:
    from tag_prompt_mask import load_novel_negative_omit

    meta = tmp_path / "_meta.yaml"
    meta.write_text("character_tag_batch:\n  omit_negative_tags: [child]\nmanga_tag_batch:\n  omit_negative_tags: [loli, child]\n", encoding="utf-8")
    assert load_novel_negative_omit(tmp_path, primary_key="manga_tag_batch", fallback_key="character_tag_batch") == ("child", "loli")
    meta.write_text("character_tag_batch:\n  omit_negative_tags: child\n", encoding="utf-8")
    with pytest.raises(ValueError, match="omit_negative_tags"):
        load_novel_negative_omit(tmp_path, primary_key="character_tag_batch")


def test_character_batch_negative_dry_run(tmp_path, monkeypatch, capsys) -> None:
    from types import SimpleNamespace
    import image_provider_novel_tag_batch as batch
    import image_provider_novel_manga_batch as manga

    novel = tmp_path / "novel"
    char_dir = novel / "tag" / "characters"
    char_dir.mkdir(parents=True)
    (novel / "_meta.yaml").write_text("character_tag_batch:\n  prepend_negative_tags: [child]\n  append_negative_tags: [loli]\n  omit_negative_tags: [child, yaml_bad]\n", encoding="utf-8")
    (char_dir / "one.yaml").write_text("character_id: one\nnegative_tags: [yaml_bad, keep]\nprompt_variants:\n  - variant_id: normal\n    danbooru_tags: [1girl]\n", encoding="utf-8")
    monkeypatch.setattr(manga, "resolve_novelai_reference", lambda *a, **kw: SimpleNamespace(paths=[], source="none", strength=0.5, information_extracted=0.5))
    assert batch.main([str(novel), "--provider", "forge", "--dry-run", "--negative-prompt", "child, keep, cli_bad", "--omit-negative-tags", "loli", "cli_bad"]) == 0
    out = capsys.readouterr().out
    assert "omit_negative_tags: child, yaml_bad, loli, cli_bad" in out
    assert "negative omitted: child, child, cli_bad, yaml_bad, loli" in out
    layers = batch.load_novel_tag_batch_layers(novel).merge(batch.TagBatchLayers(omit_negative_tags=("loli", "cli_bad")))
    source = batch.compose_negative_prompt("child, keep, cli_bad", ["yaml_bad", "keep"], layers)
    from tag_prompt_mask import apply_negative_omit
    assert apply_negative_omit(source, layers.omit_negative_tags)[0] == "keep, keep"

    import json
    captured = {}
    def fake_run(command, **kwargs):
        captured.update(json.loads(Path(command[3]).read_text(encoding="utf-8")))
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")
    monkeypatch.setattr(batch.subprocess, "run", fake_run)
    assert batch.main([str(novel), "--provider", "forge", "--negative-prompt", "child, keep, cli_bad", "--omit-negative-tags", "loli", "cli_bad"]) == 0
    assert captured["negative_prompt"] == "keep, keep"
    assert batch.main([str(novel), "--provider", "forge", "--omit-negative-tags", "lowres"]) == 0
    assert "lowres" not in captured["negative_prompt"].split(", ")
    assert "worst quality" in captured["negative_prompt"]
