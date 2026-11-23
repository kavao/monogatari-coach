#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""改訂枝（novel_branch.py）の fork / list / diff。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import novel_branch as nb  # noqa: E402
import novel_code_allocate as nca  # noqa: E402

_META = """# _meta.md

# I. 内部メタ情報（Internal Meta: 執筆管理・AI指示用）

## 1. 執筆フェーズ・ステータス

- 現在: 第2章まで

## 2. 執筆用コンテキスト・アンカー

- 伏線: なし
"""

_CONFIG = """# config.md — 「元」

## 基本情報

| 項目 | 内容 |
|------|------|
| novel_ID | 051 |
| 作品名 | 元 |
| 資料上の別名 | フォルダ名略称「051_元」 |
| METRON | {metron} |
| CHRONOS | OFF |
| AUDIT_LOG | ON |
"""


def _trunk(novels: Path, *, metron: str = "ON") -> Path:
    work = novels / "051_元"
    (work / "_novel_text").mkdir(parents=True)
    (work / "config.md").write_text(_CONFIG.format(metron=metron), encoding="utf-8")
    (work / "_meta.md").write_text(_META, encoding="utf-8")
    for name in ("proposal.md", "design_specification.md", "character.md", "world.md"):
        (work / name).write_text(f"# {name}\n\n1. 一項\n", encoding="utf-8")
    (work / "_novel_text" / "novel_text01.md").write_text("第一章の本文。", encoding="utf-8")
    (work / "_novel_text_backup").mkdir()
    (work / "_novel_text_backup" / "novel_text01_v001.md").write_text("旧", encoding="utf-8")
    (work / "_reader" / "_work").mkdir(parents=True)
    (work / "_reader" / "20261101_1200.md").write_text("評価", encoding="utf-8")
    (work / "_reader" / "_work" / "x.json").write_text("{}", encoding="utf-8")
    (work / "_work" / "metron" / "ch01").mkdir(parents=True)
    (work / "_work" / "metron" / "ch01" / "report.json").write_text("{}", encoding="utf-8")
    (work / "_metron").mkdir()
    (work / "tag" / "characters").mkdir(parents=True)
    (work / "tag" / "characters" / "a.yaml").write_text("id: a\n", encoding="utf-8")
    (work / "tag" / "a.png").write_bytes(b"\x89PNG")
    (work / "tag.zip").write_bytes(b"PK")
    (work / "references").mkdir()
    (work / "references" / "memo.md").write_text("参考", encoding="utf-8")
    (work / "__pycache__").mkdir()
    return work


@pytest.fixture()
def novels(tmp_path: Path) -> Path:
    root = tmp_path / "novels"
    root.mkdir()
    return root


def _rels(plan: nb.ForkPlan) -> set[str]:
    return {e.rel for e in plan.copies}


def test_dry_run_skeleton_text_default(novels: Path) -> None:
    trunk = _trunk(novels)
    (trunk / "_story_reflection_op.json").write_text("{}", encoding="utf-8")
    plan = nb.build_fork_plan(trunk, novels_root=novels, reason="revision")

    assert plan.scope == "skeleton_text"
    assert plan.label == "051a"
    assert Path(plan.target).name == "051a_元"
    rels = _rels(plan)
    assert {"config.md", "_meta.md", "_novel_text/novel_text01.md"} <= rels
    assert not any(r.startswith(("_work", "_metron", "_reader", "_novel_text_backup", "tag", "references")) for r in rels)
    assert "_story_reflection_op.json" not in rels
    assert "tag.zip" not in rels
    assert "_reader" in plan.empty_dirs
    assert any("METRON ON" in w for w in plan.warnings)
    assert {"rel": "config.md", "count": 1} in plan.self_references
    # dry-run は何も作らない
    assert not (novels / "051a_元").exists()


def test_skeleton_excludes_text(novels: Path) -> None:
    trunk = _trunk(novels)
    plan = nb.build_fork_plan(trunk, novels_root=novels, scope="skeleton", reason="revision")
    assert not any(r.startswith("_novel_text/") for r in _rels(plan))
    assert set(plan.empty_dirs) == {"_novel_text", "_reader"}


def test_full_keeps_confirm_layers_out_unless_included(novels: Path) -> None:
    trunk = _trunk(novels)
    plan = nb.build_fork_plan(trunk, novels_root=novels, scope="full", reason="compare")
    rels = _rels(plan)
    assert "tag/characters/a.yaml" in rels
    assert "references/memo.md" in rels
    assert "tag/a.png" not in rels
    assert not any(r.startswith(("_reader/", "_novel_text_backup/", "_work/")) for r in rels)
    assert "tag.zip" not in rels

    plan2 = nb.build_fork_plan(
        trunk, novels_root=novels, scope="full", reason="compare", includes=["images", "reader", "backup", "archives"]
    )
    rels2 = _rels(plan2)
    assert {"tag/a.png", "_reader/20261101_1200.md", "_novel_text_backup/novel_text01_v001.md", "tag.zip"} <= rels2
    # _reader/_work は --include reader でも写さない
    assert not any(r.startswith("_reader/_work") for r in rels2)
    assert not any(r.startswith("_work/") for r in rels2)


def test_apply_creates_branch_and_links(novels: Path) -> None:
    trunk = _trunk(novels)
    plan = nb.build_fork_plan(trunk, novels_root=novels, reason="revision")
    result = nb.apply_fork(plan, novels_root=novels, note="発表から時間がたった", today="2026-11-23")

    branch = novels / "051a_元"
    assert result["verify"]["ok"], result["verify"]["issues"]
    config = (branch / "config.md").read_text(encoding="utf-8")
    assert "| novel_ID | 051 |\n| branch | a |\n| parent_ID | 051 |\n| branch_reason | revision |\n| 作品名 |" in config
    assert (trunk / "config.md").read_text(encoding="utf-8") == _CONFIG.format(metron="ON")
    assert (branch / "_work" / "metron").is_dir()
    assert not any((branch / "_work" / "metron").iterdir())
    assert (branch / "_reader").is_dir() and not any((branch / "_reader").iterdir())
    assert not (branch / "_metron").exists()
    assert not (branch / "_story_reflection_op.json").exists()

    branch_meta = (branch / "_meta.md").read_text(encoding="utf-8")
    assert "### 改訂枝" in branch_meta
    assert "`novels/051_元`" in branch_meta
    assert "発表から時間がたった" in branch_meta
    # 雛形の ## 見出しの並びは変えない（改訂枝は I.1 の中）
    i1 = branch_meta.index("## 1. 執筆フェーズ・ステータス")
    sub = branch_meta.index("### 改訂枝")
    i2 = branch_meta.index("## 2. 執筆用コンテキスト・アンカー")
    assert i1 < sub < i2

    trunk_meta = (trunk / "_meta.md").read_text(encoding="utf-8")
    assert "`novels/051a_元` を作った（revision・skeleton_text）" in trunk_meta
    assert trunk_meta.index("### 改訂枝") < trunk_meta.index("## 2. 執筆用コンテキスト・アンカー")
    assert (trunk / "_novel_text_backup" / "_meta_v001.md").read_text(encoding="utf-8") == _META

    # 採番は分岐で消費しない
    assert nca.scan_novels(novels)["next_code"] == 52
    assert nca.scan_novels(novels)["duplicates"] == []


def test_second_branch_gets_b_and_does_not_copy_trunk_history(novels: Path) -> None:
    trunk = _trunk(novels, metron="OFF")
    nb.apply_fork(nb.build_fork_plan(trunk, novels_root=novels, reason="revision"), novels_root=novels, today="2026-11-23")
    plan = nb.build_fork_plan(trunk, novels_root=novels, reason="compare")
    assert plan.label == "051b"
    nb.apply_fork(plan, novels_root=novels, today="2026-11-24")

    b_meta = (novels / "051b_元" / "_meta.md").read_text(encoding="utf-8")
    assert "051a_元" not in b_meta
    assert b_meta.count("### 改訂枝") == 1
    trunk_meta = (trunk / "_meta.md").read_text(encoding="utf-8")
    assert trunk_meta.count("### 改訂枝") == 1
    assert "051a_元" in trunk_meta and "051b_元" in trunk_meta
    assert not (novels / "051b_元" / "_work").exists()  # METRON OFF は scaffold しない


def test_project_check_accepts_branch(novels: Path) -> None:
    from novel_project_check import check_novel_project

    trunk = _trunk(novels)
    nb.apply_fork(nb.build_fork_plan(trunk, novels_root=novels, reason="revision"), novels_root=novels)
    kwargs = dict(min_file_bytes=1, require_tag_md=False, require_manga_dir=False, require_character_structure=False)
    trunk_result = check_novel_project(trunk, **kwargs)
    branch_result = check_novel_project(novels / "051a_元", **kwargs)
    # 枝は元と同じ判定になる（novel_ID / フォルダ名の検査で落ちない）
    assert not [i for i in branch_result["issues"] if "novel_ID" in i]
    assert branch_result["ok"] == trunk_result["ok"]


def test_apply_refuses_when_trunk_story_reflection_is_unfinished(novels: Path) -> None:
    trunk = _trunk(novels)
    (trunk / "_story_reflection_op.json").write_text("{}", encoding="utf-8")
    plan = nb.build_fork_plan(trunk, novels_root=novels, reason="revision")
    with pytest.raises(nb.BranchError) as e:
        nb.apply_fork(plan, novels_root=novels)
    assert e.value.code == "TRUNK_BUSY"
    assert not (novels / "051a_元").exists()
    assert not any(p.name.endswith(".forking") for p in novels.iterdir())
    assert (trunk / "_meta.md").read_text(encoding="utf-8") == _META


def test_apply_requires_reason(novels: Path) -> None:
    trunk = _trunk(novels)
    plan = nb.build_fork_plan(trunk, novels_root=novels)
    with pytest.raises(nb.BranchError) as e:
        nb.apply_fork(plan, novels_root=novels)
    assert e.value.code == "NO_REASON"
    assert not (novels / "051a_元").exists()


def test_refuses_branch_of_branch_and_existing(novels: Path) -> None:
    trunk = _trunk(novels)
    nb.apply_fork(nb.build_fork_plan(trunk, novels_root=novels, reason="revision"), novels_root=novels)
    with pytest.raises(nb.BranchError) as e:
        nb.build_fork_plan(novels / "051a_元", novels_root=novels, reason="revision")
    assert e.value.code == "BRANCH_OF_BRANCH"
    with pytest.raises(nb.BranchError) as e:
        nb.build_fork_plan(trunk, novels_root=novels, reason="revision", branch="a")
    assert e.value.code == "BRANCH_EXISTS"
    with pytest.raises(nb.BranchError):
        nb.build_fork_plan(trunk, novels_root=novels, branch="ab")


def test_cli_dry_run_by_default(novels: Path, capsys) -> None:
    _trunk(novels)
    assert nb.main(["--novels-dir", str(novels), "fork", "--from", "051", "--reason", "revision"]) == 0
    out = capsys.readouterr().out
    assert "dry-run" in out and "051a_元" in out
    assert not (novels / "051a_元").exists()


def test_list_and_diff(novels: Path, capsys) -> None:
    trunk = _trunk(novels)
    nb.apply_fork(nb.build_fork_plan(trunk, novels_root=novels, reason="revision"), novels_root=novels)
    branch = novels / "051a_元"
    (branch / "_novel_text" / "novel_text01.md").write_text("第一章の本文を直した。", encoding="utf-8")
    (branch / "_novel_text" / "novel_text02.md").write_text("第二章。", encoding="utf-8")
    (branch / "design_specification.md").write_text("# d\n\n1. 一項\n2. 二項\n", encoding="utf-8")

    rows = nb.list_branches(novels)
    assert [(r["role"], r["folder"], r["verify_ok"]) for r in rows] == [("元", "051_元", True), ("改訂枝", "051a_元", True)]

    data = nb.diff_works(trunk, branch, list(nb.DIFF_LAYERS))
    text = data["layers"]["text"]
    assert text["changed"] == ["_novel_text/novel_text01.md"]
    assert text["added"] == ["_novel_text/novel_text02.md"]
    assert text["total"] == {"a": 7, "b": 11 + 4}
    design = data["layers"]["design"]
    assert design["shape"]["design_specification.md"]["b"]["numbered"] == 2
    assert data["reader_files"]["b"] == 0
    assert "config.md" in data["layers"]["canon"]["changed"]

    assert nb.main(["--novels-dir", str(novels), "diff", "051", "051a", "--layer", "text"]) == 0
    assert "合計: 7 → 15（+8）" in capsys.readouterr().out


def test_images_are_held_back_wherever_they_are(novels: Path) -> None:
    trunk = _trunk(novels)
    (trunk / "cover.png").write_bytes(b"\x89PNG")
    (trunk / "references" / "map.jpg").write_bytes(b"\xff\xd8")
    for scope in ("skeleton", "full"):
        rels = _rels(nb.build_fork_plan(trunk, novels_root=novels, scope=scope, reason="revision", includes=["references"] if scope == "skeleton" else None))
        assert "cover.png" not in rels and "references/map.jpg" not in rels, scope
        assert "references/memo.md" in rels
    rels = _rels(nb.build_fork_plan(trunk, novels_root=novels, scope="full", reason="revision", includes=["images"]))
    assert {"cover.png", "references/map.jpg", "tag/a.png"} <= rels


def test_diff_total_counts_only_novel_text_files(novels: Path) -> None:
    trunk = _trunk(novels, metron="OFF")
    nb.apply_fork(nb.build_fork_plan(trunk, novels_root=novels, reason="revision"), novels_root=novels)
    branch = novels / "051a_元"
    (branch / "_novel_text" / "matter").mkdir()
    (branch / "_novel_text" / "matter" / "afterword.md").write_text("あとがき六字", encoding="utf-8")
    (branch / "_novel_text" / "memo.md").write_text("メモ", encoding="utf-8")
    text = nb.diff_works(trunk, branch, ["text"])["layers"]["text"]
    # 変更ファイルには出るが、文字数は novel_char_count.py と同じ対象だけ
    assert "_novel_text/matter/afterword.md" in text["added"]
    assert [r["file"] for r in text["chars"]] == ["_novel_text/novel_text01.md"]
    assert text["total"] == {"a": 7, "b": 7}


def test_cli_accepts_explicit_dry_run(novels: Path, capsys) -> None:
    _trunk(novels)
    assert nb.main(["--novels-dir", str(novels), "fork", "--from", "051", "--reason", "revision", "--dry-run"]) == 0
    assert "--dry-run を付けていたら外す" in capsys.readouterr().out
    assert not (novels / "051a_元").exists()
    with pytest.raises(SystemExit):
        nb.main(["--novels-dir", str(novels), "fork", "--from", "051", "--dry-run", "--apply"])


def test_refuses_fork_when_trunk_code_is_duplicated(novels: Path) -> None:
    trunk = _trunk(novels)
    other = novels / "051_別作品"
    other.mkdir()
    (other / "config.md").write_text(_CONFIG.format(metron="OFF"), encoding="utf-8")
    with pytest.raises(nb.BranchError) as e:
        nb.build_fork_plan(trunk, novels_root=novels, reason="revision")
    assert e.value.code == "AMBIGUOUS_TRUNK"


def test_branch_config_rows_follow_novel_id_even_after_blank_line() -> None:
    text = "## 基本情報\n\n| novel_ID | 051 |\n| 作品名 | 元 |\n"
    out = nb.branch_config_text(text, branch="a", parent_digits="051", reason="revision")
    assert out == (
        "## 基本情報\n\n| novel_ID | 051 |\n| branch | a |\n| parent_ID | 051 |\n"
        "| branch_reason | revision |\n| 作品名 | 元 |\n"
    )
    crlf = text.replace("\n", "\r\n")
    out_crlf = nb.branch_config_text(crlf, branch="a", parent_digits="051", reason="revision")
    assert "| novel_ID | 051 |\r\n| branch | a |\r\n" in out_crlf


def test_branch_meta_says_what_the_branch_lacks(novels: Path) -> None:
    trunk = _trunk(novels)
    plan = nb.build_fork_plan(trunk, novels_root=novels, scope="skeleton", reason="revision")
    nb.apply_fork(plan, novels_root=novels, today="2026-11-23")
    meta = (novels / "051a_元" / "_meta.md").read_text(encoding="utf-8")
    line = next(l for l in meta.splitlines() if l.startswith("- **写す前の記録**"))
    assert "`051_元` の時点" in line
    assert "`_novel_text/ の中身`" in line and "`_reader/ の中身`" in line and "`tag/`" in line
    # 機械の記録は「無いもの」に並べない（写さないのが当然のため）
    assert "_work" not in line and "_metron" not in line


def test_trunk_record_failure_after_create_is_reported(novels: Path, monkeypatch) -> None:
    trunk = _trunk(novels)
    plan = nb.build_fork_plan(trunk, novels_root=novels, reason="revision")

    def boom(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr(nb, "_record_on_trunk", boom)
    result = nb.apply_fork(plan, novels_root=novels)
    assert (novels / "051a_元").is_dir()
    assert result["trunk_meta"].startswith("未記録")
    assert any("disk full" in w for w in result["warnings"])


def test_insert_branch_record_legacy_meta() -> None:
    out = nb.insert_branch_record("# 古いメタ\n\n- メモ\n", ["- 行"])
    assert out.endswith("## 改訂枝\n\n- 行\n")
    out2 = nb.insert_branch_record(out, ["- 次"])
    assert out2.count("## 改訂枝") == 1 and out2.endswith("- 行\n- 次\n")
