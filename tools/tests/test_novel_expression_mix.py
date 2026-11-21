"""表現ミックス resolve / validate。"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import novel_expression_mix as mix  # noqa: E402
from writing_bridge.context_build import extract_usage_notes  # noqa: E402

EXAMPLE_EXPR = ROOT / "_how_to.example" / "expression"


def _copy_example_expression(dest: Path) -> None:
    src = ROOT / "_how_to.example" / "expression"
    shutil.copytree(src, dest / "_how_to.example" / "expression")
    md = ROOT / "_how_to.example" / "expression.md"
    if md.is_file():
        shutil.copy2(md, dest / "_how_to.example" / "expression.md")


def _freeze_weights(root: Path, overrides: dict[str, float] | None = None) -> str:
    catalog = yaml.safe_load((root / "_how_to.example" / "expression" / "catalog.yaml").read_text(encoding="utf-8"))
    default = yaml.safe_load((root / "_how_to.example" / "expression" / "default.yaml").read_text(encoding="utf-8"))
    values = {key: 1.0 for key in catalog["categories"]}
    values.update(default.get("weights") or {})
    if overrides:
        values.update(overrides)
    return "- **重み**:\n" + "".join(f"  - {key}: {value:g}\n" for key, value in values.items())


def _write_meta(work: Path, *, genre: str = "genre/human_drama.md", showing: str = "", freeze: str = "") -> None:
    work.mkdir(parents=True, exist_ok=True)
    parts = [
        "# I. 内部メタ情報\n",
        "## 3.5 Plan Mode Gate B 記録\n",
        f"- **ジャンル**: {genre}\n",
    ]
    if showing:
        parts.append("## 3.7 見せ方軸\n")
        parts.append(showing.rstrip() + "\n")
    if freeze:
        parts.append("## 3.8 表現ミックス\n")
        parts.append(freeze.rstrip() + "\n")
    (work / "_meta.md").write_text("".join(parts), encoding="utf-8")


def test_example_catalog_validate() -> None:
    notes = mix.validate_tree(ROOT)
    assert any("catalog" in item for item in notes)
    assert any("human_drama" in item for item in notes)


def test_human_drama_bands(tmp_path: Path) -> None:
    _copy_example_expression(tmp_path)
    work = tmp_path / "novels" / "001_hd"
    _write_meta(work)
    result = mix.resolve_mix(work, root=tmp_path)
    assert result.flag == "OFF"
    assert result.flag_source == "implicit"
    assert result.enabled is False
    assert result.genre_ids == ["human_drama"]
    assert result.bands["daily"] == "high"
    assert result.bands["gesture"] == "high"
    assert result.bands["sound"] == "low"
    assert result.bands["dialogue"] == "mid"
    assert result.beat_defaults["independent_sound_beat"] is False
    assert result.beat_defaults["prefer_action_over_dialogue"] is False


def test_dungeon_beats_nudge(tmp_path: Path) -> None:
    _copy_example_expression(tmp_path)
    work = tmp_path / "novels" / "002_dungeon"
    _write_meta(work, genre="genre/dungeon.md")
    result = mix.resolve_mix(work, root=tmp_path)
    assert result.bands["sensory"] == "high"
    assert result.bands["sound"] == "high"
    assert result.bands["process"] == "high"
    assert result.bands["daily"] == "low"
    assert result.beat_defaults["sensory"] >= 4
    assert result.beat_defaults["chars_hint"] >= 360


def test_working_catalog_is_self_contained(tmp_path: Path) -> None:
    _copy_example_expression(tmp_path)
    working_cat = tmp_path / "_how_to" / "expression" / "catalog.yaml"
    working_cat.parent.mkdir(parents=True)
    working_cat.write_text(
        "schema_version: '1'\ncategories:\n  action:\n    label: 動作\n    metron:\n      type: action\n",
        encoding="utf-8",
    )
    with pytest.raises(mix.MixError) as exc:
        mix.validate_tree(tmp_path)
    assert exc.value.code == "UNKNOWN_ID"


def test_working_profile_replaces_example(tmp_path: Path) -> None:
    _copy_example_expression(tmp_path)
    dest = tmp_path / "_how_to" / "expression" / "profiles"
    dest.mkdir(parents=True)
    (dest / "human_drama.yaml").write_text(
        "schema_version: '1'\ngenre_id: human_drama\nweights:\n  sound: 2.0\n  daily: 0.4\n",
        encoding="utf-8",
    )
    work = tmp_path / "novels" / "003_hd"
    _write_meta(work)
    result = mix.resolve_mix(work, root=tmp_path)
    assert result.bands["sound"] == "high"
    assert result.bands["daily"] == "low"
    assert any("_how_to/expression/profiles/human_drama.yaml" in item.replace("\\", "/") for item in result.sources)


def test_work_freeze_overrides(tmp_path: Path) -> None:
    _copy_example_expression(tmp_path)
    work = tmp_path / "novels" / "004_custom"
    _write_meta(
        work,
        freeze="- **状態**: ON\n- **指定**: custom\n" + _freeze_weights(tmp_path, {"sound": 2.0, "daily": 0.3}),
    )
    result = mix.resolve_mix(work, root=tmp_path)
    assert result.freeze == "custom"
    assert result.flag == "ON"
    assert result.flag_source == "explicit"
    assert result.enabled is True
    assert result.bands["sound"] == "high"
    assert result.bands["daily"] == "low"


def test_interiority_cap(tmp_path: Path) -> None:
    _copy_example_expression(tmp_path)
    work = tmp_path / "novels" / "005_cap"
    _write_meta(
        work,
        genre="genre/romcom.md",
        showing="- **プリセット**: gekiga_style\n  - 情報: 胸の内は動作で見せる（INTERIORITY --）\n",
    )
    result = mix.resolve_mix(work, root=tmp_path)
    assert result.interiority_capped is True
    assert result.bands["interiority"] == "low"
    assert result.beat_defaults["interiority"] == 0


def test_unknown_id_in_freeze_fails(tmp_path: Path) -> None:
    _copy_example_expression(tmp_path)
    work = tmp_path / "novels" / "006_bad"
    _write_meta(work, freeze="- **指定**: custom\n- **重み**:\n  - contact_sound: 2.0\n")
    with pytest.raises(mix.MixError) as exc:
        mix.resolve_mix(work, root=tmp_path)
    assert exc.value.code == "UNKNOWN_ID"


def test_negative_weight_fails(tmp_path: Path) -> None:
    _copy_example_expression(tmp_path)
    path = tmp_path / "_how_to.example" / "expression" / "default.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["weights"]["action"] = -1
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    with pytest.raises(mix.MixError) as exc:
        mix.validate_tree(tmp_path)
    assert exc.value.code == "WEIGHT_NEGATIVE"


def test_genre_conflicts_are_reported(tmp_path: Path) -> None:
    _copy_example_expression(tmp_path)
    work = tmp_path / "novels" / "007_mix"
    _write_meta(work, genre="genre/human_drama.md / genre/dungeon.md")
    result = mix.resolve_mix(work, root=tmp_path)
    assert "human_drama" in result.genre_ids and "dungeon" in result.genre_ids
    cats = {item["category"] for item in result.conflicts}
    assert "daily" in cats
    assert result.conflicts


def test_gesture_high_dialogue_low_prefers_action(tmp_path: Path) -> None:
    _copy_example_expression(tmp_path)
    dest = tmp_path / "_how_to" / "expression" / "profiles"
    dest.mkdir(parents=True)
    (dest / "human_drama.yaml").write_text(
        "schema_version: '1'\nweights:\n  gesture: 2.0\n  dialogue: 0.2\n",
        encoding="utf-8",
    )
    work = tmp_path / "novels" / "008_gesture"
    _write_meta(work)
    result = mix.resolve_mix(work, root=tmp_path)
    assert result.beat_defaults["prefer_action_over_dialogue"] is True
    assert result.beat_defaults["dialogue_turns"] == [0, 1]


def test_cli_resolve_json(tmp_path: Path, capsys) -> None:
    _copy_example_expression(tmp_path)
    work = tmp_path / "novels" / "009_cli"
    _write_meta(work)
    code = mix.main([str(work), "resolve", "--json", "--root", str(tmp_path)])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["flag"] == "OFF"
    assert payload["enabled"] is False


def test_explicit_on_is_enabled(tmp_path: Path) -> None:
    _copy_example_expression(tmp_path)
    work = tmp_path / "novels" / "010_on"
    _write_meta(
        work,
        freeze="- **状態**: ON\n- **指定**: ジャンル既定\n"
        + _freeze_weights(tmp_path, {"daily": 2.0, "gesture": 2.0, "dialogue": 1.2, "sound": 0.4, "metaphor": 0.4}),
    )
    result = mix.resolve_mix(work, root=tmp_path)
    assert result.flag == "ON"
    assert result.flag_source == "explicit"
    assert result.enabled is True
    assert result.bands["daily"] == "high"


def test_explicit_off_is_not_enabled(tmp_path: Path) -> None:
    _copy_example_expression(tmp_path)
    work = tmp_path / "novels" / "011_off"
    _write_meta(work, freeze="- **状態**: OFF\n")
    result = mix.resolve_mix(work, root=tmp_path)
    assert result.flag == "OFF"
    assert result.flag_source == "explicit"
    assert result.enabled is False


def test_unknown_flag_fails_validate(tmp_path: Path) -> None:
    _copy_example_expression(tmp_path)
    work = tmp_path / "novels" / "012_badflag"
    _write_meta(work, freeze="- **状態**: YES\n")
    with pytest.raises(mix.MixError) as exc:
        mix.resolve_mix(work, root=tmp_path)
    assert exc.value.code == "FLAG"
    assert mix.main([str(work), "validate", "--root", str(tmp_path)]) == 1


def test_on_with_unspecified_fails(tmp_path: Path) -> None:
    _copy_example_expression(tmp_path)
    work = tmp_path / "novels" / "013_on_none"
    _write_meta(work, freeze="- **状態**: ON\n- **指定**: 指定なし\n")
    with pytest.raises(mix.MixError) as exc:
        mix.resolve_mix(work, root=tmp_path)
    assert exc.value.code == "FLAG_ON_UNSPECIFIED"


def test_cli_validate_catalog() -> None:
    assert mix.main(["validate"]) == 0


def test_expression_md_has_context_usage_notes() -> None:
    text = (ROOT / "_how_to.example" / "expression.md").read_text(encoding="utf-8")
    notes = extract_usage_notes(text)
    joined = "\n".join(notes)
    assert "実効の表現ミックス" in joined
    assert "重み表" in joined
    assert "action:" not in joined


def test_official_profiles_exist() -> None:
    for name in ("human_drama", "romcom", "dungeon"):
        path = EXAMPLE_EXPR / "profiles" / f"{name}.yaml"
        assert path.is_file(), path


def test_slash_and_suffix_flags_fail(tmp_path: Path) -> None:
    _copy_example_expression(tmp_path)
    work = tmp_path / "novels" / "014_slash"
    _write_meta(work, freeze="- **状態**: ON/OFF\n")
    with pytest.raises(mix.MixError) as slash:
        mix.resolve_mix(work, root=tmp_path)
    assert slash.value.code == "FLAG"
    work2 = tmp_path / "novels" / "015_extra"
    _write_meta(work2, freeze="- **状態**: OFF-extra\n")
    with pytest.raises(mix.MixError) as extra:
        mix.resolve_mix(work2, root=tmp_path)
    assert extra.value.code == "FLAG"
    assert mix.main([str(work2), "validate", "--root", str(tmp_path)]) == 1


def test_later_invalid_flag_fails_validate(tmp_path: Path) -> None:
    _copy_example_expression(tmp_path)
    work = tmp_path / "novels" / "016_later"
    _write_meta(work, freeze="- **状態**: ON\n- **指定**: ジャンル既定\n- **状態**: maybe\n")
    with pytest.raises(mix.MixError) as exc:
        mix.resolve_mix(work, root=tmp_path)
    assert exc.value.code == "FLAG"
    assert mix.main([str(work), "validate", "--root", str(tmp_path)]) == 1


def test_empty_flag_with_genre_default_is_not_enabled(tmp_path: Path) -> None:
    _copy_example_expression(tmp_path)
    work = tmp_path / "novels" / "017_empty"
    _write_meta(work, freeze="- **状態**:\n- **指定**: ジャンル既定\n")
    with pytest.raises(mix.MixError) as empty:
        mix.resolve_mix(work, root=tmp_path)
    assert empty.value.code == "FLAG"
    work2 = tmp_path / "novels" / "018_no_flag"
    _write_meta(work2, freeze="- **指定**: ジャンル既定\n")
    result = mix.resolve_mix(work2, root=tmp_path)
    assert result.flag == "OFF"
    assert result.enabled is False
    assert result.flag_source == "implicit"


def test_genre_default_keeps_frozen_weights(tmp_path: Path) -> None:
    _copy_example_expression(tmp_path)
    dest = tmp_path / "_how_to" / "expression" / "profiles"
    dest.mkdir(parents=True)
    (dest / "human_drama.yaml").write_text(
        "schema_version: '1'\nweights:\n  dialogue: 3.0\n",
        encoding="utf-8",
    )
    work = tmp_path / "novels" / "019_freeze"
    _write_meta(
        work,
        freeze="- **状態**: ON\n- **指定**: ジャンル既定\n" + _freeze_weights(tmp_path, {"dialogue": 1.0}),
    )
    result = mix.resolve_mix(work, root=tmp_path)
    assert result.enabled is True
    assert result.weights["dialogue"] == 1.0
    assert result.beat_defaults["dialogue_turns"] == [1, 4]


def test_custom_junk_weights_fail(tmp_path: Path) -> None:
    _copy_example_expression(tmp_path)
    work = tmp_path / "novels" / "020_neg"
    _write_meta(
        work,
        freeze="- **状態**: ON\n- **指定**: custom\n- **重み**:\n  - dialogue: -2.5\n",
    )
    with pytest.raises(mix.MixError) as neg:
        mix.resolve_mix(work, root=tmp_path)
    assert neg.value.code == "WEIGHT_NEGATIVE"
    assert mix.main([str(work), "validate", "--root", str(tmp_path)]) == 1
    work2 = tmp_path / "novels" / "021_oops"
    _write_meta(
        work2,
        freeze="- **状態**: ON\n- **指定**: custom\n- **重み**:\n  - dialogue: 3oops\n",
    )
    with pytest.raises(mix.MixError) as oops:
        mix.resolve_mix(work2, root=tmp_path)
    assert oops.value.code == "WEIGHT_TYPE"
    assert mix.main([str(work2), "validate", "--root", str(tmp_path)]) == 1


def test_missing_metron_fails_validate(tmp_path: Path) -> None:
    _copy_example_expression(tmp_path)
    path = tmp_path / "_how_to.example" / "expression" / "catalog.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    del data["categories"]["sound"]["metron"]
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    with pytest.raises(mix.MixError) as exc:
        mix.validate_tree(tmp_path)
    assert exc.value.code == "METRON_MISSING"


def test_null_sensory_map_drops_that_category(tmp_path: Path) -> None:
    _copy_example_expression(tmp_path)
    path = tmp_path / "_how_to.example" / "expression" / "catalog.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["categories"]["sensory"]["metron"] = None
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    work = tmp_path / "novels" / "022_nullmap"
    _write_meta(
        work,
        freeze="- **状態**: ON\n- **指定**: custom\n" + _freeze_weights(tmp_path, {"sensory": 2.0}),
    )
    result = mix.resolve_mix(work, root=tmp_path)
    assert result.bands["sensory"] == "high"
    assert result.beat_defaults["sensory"] == 2


def test_custom_category_budget_feeds_sensory(tmp_path: Path) -> None:
    _copy_example_expression(tmp_path)
    src = ROOT / "_how_to.example" / "expression" / "catalog.yaml"
    data = yaml.safe_load(src.read_text(encoding="utf-8"))
    data["categories"]["contact_sound"] = {"label": "接触音", "metron": {"budget": "sensory"}}
    dest = tmp_path / "_how_to" / "expression"
    dest.mkdir(parents=True)
    (dest / "catalog.yaml").write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    work = tmp_path / "novels" / "023_custom_cat"
    _write_meta(
        work,
        freeze="- **状態**: ON\n- **指定**: custom\n"
        + _freeze_weights(
            tmp_path,
            {"contact_sound": 2.0, "sensory": 0.4, "sound": 0.4, "environment": 0.4},
        ),
    )
    result = mix.resolve_mix(work, root=tmp_path)
    assert result.beat_defaults["sensory"] == 4


def test_on_without_weights_fails_validate(tmp_path: Path) -> None:
    _copy_example_expression(tmp_path)
    work = tmp_path / "novels" / "024_noweights"
    _write_meta(work, freeze="- **状態**: ON\n- **指定**: ジャンル既定\n")
    with pytest.raises(mix.MixError) as exc:
        mix.resolve_mix(work, root=tmp_path)
    assert exc.value.code == "WEIGHT_INCOMPLETE"
    assert mix.main([str(work), "validate", "--root", str(tmp_path)]) == 1


def test_on_with_partial_weights_fails_validate(tmp_path: Path) -> None:
    _copy_example_expression(tmp_path)
    work = tmp_path / "novels" / "025_partial"
    _write_meta(
        work,
        freeze="- **状態**: ON\n- **指定**: ジャンル既定\n- **重み**:\n  - dialogue: 1.0\n",
    )
    with pytest.raises(mix.MixError) as exc:
        mix.resolve_mix(work, root=tmp_path)
    assert exc.value.code == "WEIGHT_INCOMPLETE"
    assert "daily" in str(exc.value)
    assert mix.main([str(work), "validate", "--root", str(tmp_path)]) == 1


def test_empty_weight_value_fails(tmp_path: Path) -> None:
    _copy_example_expression(tmp_path)
    work = tmp_path / "novels" / "026_emptyw"
    _write_meta(
        work,
        freeze="- **状態**: ON\n- **指定**: custom\n- **重み**:\n  - dialogue:\n",
    )
    with pytest.raises(mix.MixError) as exc:
        mix.resolve_mix(work, root=tmp_path)
    assert exc.value.code == "WEIGHT_TYPE"
    assert mix.main([str(work), "validate", "--root", str(tmp_path)]) == 1


def test_added_catalog_category_does_not_shift_frozen_mix(tmp_path: Path) -> None:
    _copy_example_expression(tmp_path)
    work = tmp_path / "novels" / "027_grow"
    _write_meta(
        work,
        freeze="- **状態**: ON\n- **指定**: ジャンル既定\n" + _freeze_weights(tmp_path, {"dialogue": 1.0}),
    )
    before = mix.resolve_mix(work, root=tmp_path)
    assert before.beat_defaults["dialogue_turns"] == [1, 4]
    catalog_path = tmp_path / "_how_to.example" / "expression" / "catalog.yaml"
    catalog = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
    catalog["categories"]["new_cat"] = {"label": "追加", "metron": {"type": "action"}}
    catalog_path.write_text(yaml.safe_dump(catalog, allow_unicode=True), encoding="utf-8")
    default_path = tmp_path / "_how_to.example" / "expression" / "default.yaml"
    default = yaml.safe_load(default_path.read_text(encoding="utf-8"))
    default["weights"]["new_cat"] = 8.0
    default_path.write_text(yaml.safe_dump(default, allow_unicode=True), encoding="utf-8")
    profile_path = tmp_path / "_how_to.example" / "expression" / "profiles" / "human_drama.yaml"
    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    profile["weights"]["new_cat"] = 8.0
    profile_path.write_text(yaml.safe_dump(profile, allow_unicode=True), encoding="utf-8")
    with pytest.raises(mix.MixError) as exc:
        mix.resolve_mix(work, root=tmp_path)
    assert exc.value.code == "WEIGHT_INCOMPLETE"
    assert "new_cat" in str(exc.value)
    assert mix.main([str(work), "validate", "--root", str(tmp_path)]) == 1


def test_hyphenated_catalog_id_can_freeze(tmp_path: Path) -> None:
    _copy_example_expression(tmp_path)
    catalog_path = tmp_path / "_how_to.example" / "expression" / "catalog.yaml"
    catalog = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
    catalog["categories"]["custom-measure"] = {"label": "独自計測", "metron": None}
    catalog_path.write_text(yaml.safe_dump(catalog, allow_unicode=True), encoding="utf-8")
    notes = mix.validate_tree(tmp_path)
    assert any("catalog" in item for item in notes)
    work = tmp_path / "novels" / "028_hyphen"
    _write_meta(
        work,
        freeze="- **状態**: ON\n- **指定**: custom\n"
        + _freeze_weights(tmp_path, {"custom-measure": 1.5}),
    )
    result = mix.resolve_mix(work, root=tmp_path)
    assert result.weights["custom-measure"] == 1.5
    assert mix.main([str(work), "validate", "--root", str(tmp_path)]) == 0
