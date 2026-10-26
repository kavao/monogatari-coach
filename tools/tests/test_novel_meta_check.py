"""_meta.md の形の判定と移行（_workingspace/plans/20261024_work-folder-layout.md §3.2・M7）。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import novel_meta_check as m  # noqa: E402

TEMPLATE = (ROOT / "_how_to.example" / "meta.md").read_text(encoding="utf-8").replace("\r\n", "\n")

LEGACY = """# _meta.md — 試作の作品

## 1. 執筆フェーズ・ステータス
- **現在のフェーズ**: 執筆
- **次回のタスク**: 第3章を書く

### 章別文字数
| 章 | 本文 | 実文字数 | 状態 | 計測 |
|---|---|---:|---|---|
| 第1章 | novel_text01 | 3,000 | 初稿 | 2026-10-24 |
| 合計 | — | 3,000 | — | 2026-10-24 |

- **出来事同期**: 2026-10-24 第1章 更新 op=sr-1

## 2. 執筆用コンテキスト・アンカー
- **直近の重要イベント**: 駅で別れた

```text
# これは見出しではない（コードブロックの中）
## これも見出しではない
```

## 評価・足切り履歴

| 日時 | ゲート | 総合点 | 判定 | ファイル |
|------|--------|--------|------|---------|
| 20261024_1200 | 用語照合 | — | 抑える1 | `_reader/terminology_20261024_1200.md` |

## 4. 外部メタ（投稿用・後日）
- **キャッチコピー**: 未稿

## 9. 作品だけのメモ
- 自由なメモ
"""


def test_check_forms() -> None:
    assert m.check_text(TEMPLATE).form == "new"
    assert m.check_text(LEGACY).form == "legacy"
    partial = "# I. 内部メタ情報\n\n## 1. 執筆フェーズ・ステータス\n- x\n"
    assert m.check_text(partial).form == "partial"


def test_template_is_already_migrated() -> None:
    plan = m.migrate_text(TEMPLATE)
    m.verify_migration(TEMPLATE, plan.text, plan.added)
    assert m.check_text(plan.text).form == "new"
    assert m.migrate_text(plan.text).text == plan.text


def test_migrate_legacy_keeps_blocks_and_records() -> None:
    plan = m.migrate_text(LEGACY)
    m.verify_migration(LEGACY, plan.text, plan.added)
    after = plan.text
    assert m.check_text(after).form == "new"
    # 機械が読む記録は同じに取れる（足した評価履歴の見出し行・goal の枠は足した節の分）
    before_records = m.machine_records(LEGACY)
    after_records = m.machine_records(after)
    assert after_records["next_task"] == before_records["next_task"]
    assert after_records["story_sync"] == before_records["story_sync"]
    assert after_records["char_table"] == before_records["char_table"]
    assert after_records["evaluation_rows"] == before_records["evaluation_rows"]
    # 見出しの変換は一覧に出る
    assert ("## 評価・足切り履歴", "## 4. 評価履歴（改訂前後の推移）") in plan.renamed
    assert ("## 4. 外部メタ（投稿用・後日）", "## 1. カクヨム基本項目") in plan.renamed
    # コードブロックの中の # は見出しにならず、中身ごと同じ節に残る
    code = "```text\n# これは見出しではない（コードブロックの中）\n## これも見出しではない\n```"
    assert code in after
    # 対応の決まらない節は未分類へそのまま
    assert "# 移行前の節（未分類）" in after
    assert "## 9. 作品だけのメモ\n- 自由なメモ" in after
    assert plan.unclassified == ["## 9. 作品だけのメモ"]
    # 部の順と、足した節
    assert after.index("# I. 内部メタ情報") < after.index("# II. 外部メタ情報") < after.index("# IV. 評価・足切り履歴")
    assert "## 1.5 goal の状況" in plan.added
    assert "章別文字数" not in "".join(plan.added)  # 章別文字数の表は自動では足さない
    # 2回目は差分なし
    assert m.migrate_text(after).text == after


def test_duplicate_sections_are_joined_under_first() -> None:
    text = "## 1. 執筆フェーズ・ステータス\n- a\n\n## 次回のタスク\n- **次回のタスク**: 続き\n"
    plan = m.migrate_text(text)
    m.verify_migration(text, plan.text, plan.added)
    assert "## 1. 執筆フェーズ・ステータス\n- a\n\n### 次回のタスク\n- **次回のタスク**: 続き" in plan.text
    assert m.migrate_text(plan.text).text == plan.text


def test_unmapped_section_with_machine_record_stops() -> None:
    text = "## 1. 執筆フェーズ・ステータス\n- a\n\n## 謎の節\n- **出来事同期**: 2026-10-24 第1章 更新\n"
    with pytest.raises(m.MetaError) as error:
        m.migrate_text(text)
    assert error.value.code == "UNMAPPED_RECORD"


def test_tools_read_migrated_meta() -> None:
    import goal_status

    after = m.migrate_text(LEGACY).text
    # goal_status は「## 2. 執筆用コンテキスト」の前に自動生成ブロックを置ける（枠はすでにある）
    updated = goal_status.apply_meta_block(after, "<!-- goal-status:begin -->\nX\n<!-- goal-status:end -->")
    assert "<!-- goal-status:begin -->\nX\n<!-- goal-status:end -->" in updated
    assert updated.count("<!-- goal-status:begin -->") == 1


# --- 必要な節だけ足す ---


def test_ensure_section_adds_only_that_section() -> None:
    text = "# IV. 評価・足切り履歴\n\n## 1. 足切りステータス\n- 未\n"
    updated = m.ensure_section_text(text, "IV.4")
    assert "## 4. 評価履歴（改訂前後の推移）\n| 日時 | ゲート |" in updated
    for line in text.splitlines():
        assert line in updated.splitlines()
    assert m.ensure_section_text(updated, "IV.4") == updated


def test_showing_axes_is_not_added_by_migration_but_by_ensure() -> None:
    plan = m.migrate_text(LEGACY)
    assert "## 3.7 見せ方軸" not in plan.text
    text = (
        "# I. 内部メタ情報\n\n## 3.6 検査レイヤの予定（METRON / CHRONOS）\n- a\n\n"
        "# II. 外部メタ情報\n\n## 1. カクヨム基本項目\n- b\n"
    )
    updated = m.ensure_section_text(text, m.ENSURE_NAMES["showing-axes"])
    assert updated.index("## 3.6 検査レイヤ") < updated.index("## 3.7 見せ方軸") < updated.index("# II.")
    assert m.ensure_section_text(updated, "I.3.7") == updated


def test_ensure_section_inserts_before_later_sections() -> None:
    text = "# I. 内部メタ情報\n\n## 1. 執筆フェーズ・ステータス\n- a\n\n## 3. 執筆制約・メタ指示\n- b\n"
    updated = m.ensure_section_text(text, "I.2")
    assert updated.index("## 2. 執筆用コンテキスト") < updated.index("## 3. 執筆制約")
    assert updated.index("## 1. 執筆フェーズ") < updated.index("## 2. 執筆用コンテキスト")


# --- CLI と退避 ---


def test_cli_dry_run_then_migrate_with_backup(tmp_path: Path, capsys) -> None:
    work = tmp_path / "001_sample"
    work.mkdir()
    meta = work / "_meta.md"
    meta.write_text(LEGACY, encoding="utf-8")
    assert m.main(["migrate", str(work), "--dry-run"]) == 0
    assert meta.read_text(encoding="utf-8") == LEGACY
    assert "見出しの変換" in capsys.readouterr().out
    assert m.main(["migrate", str(work)]) == 0
    backup = work / "_novel_text_backup" / "_meta_v001.md"
    assert backup.read_text(encoding="utf-8") == LEGACY
    assert m.check_text(meta.read_text(encoding="utf-8")).form == "new"
    capsys.readouterr()
    assert m.main(["migrate", str(work)]) == 0
    assert "移す必要はありません" in capsys.readouterr().out
    assert not (work / "_novel_text_backup" / "_meta_v002.md").exists()


@pytest.mark.parametrize("newline", ["\r\n", "\n"])
def test_cli_keeps_original_bytes_and_newline(tmp_path: Path, newline: str) -> None:
    work = tmp_path / "001_sample"
    work.mkdir()
    meta = work / "_meta.md"
    original = LEGACY.replace("\n", newline).encode("utf-8")
    meta.write_bytes(original)
    assert m.main(["migrate", str(work)]) == 0
    assert (work / "_novel_text_backup" / "_meta_v001.md").read_bytes() == original
    after = meta.read_bytes()
    assert after.count(b"\n") == after.count(newline.encode("ascii"))  # 元の改行コードだけで書く
    assert m.check_text(after.decode("utf-8").replace("\r\n", "\n")).form == "new"
    assert m.main(["ensure-section", str(work), "evaluation-history"]) == 0  # 節はすでにある
    assert meta.read_bytes() == after


def test_cli_ensure_section(tmp_path: Path) -> None:
    work = tmp_path / "001_sample"
    work.mkdir()
    (work / "_meta.md").write_text("## 1. 執筆フェーズ・ステータス\n- a\n", encoding="utf-8")
    assert m.main(["ensure-section", str(work), "evaluation-history"]) == 0
    assert "## 4. 評価履歴" in (work / "_meta.md").read_text(encoding="utf-8")
    assert (work / "_novel_text_backup" / "_meta_v001.md").is_file()


# --- 実作品（読み取りだけ。作品フォルダがある環境だけで走る） ---

NOVELS = ROOT / "novels"


@pytest.mark.skipif(not NOVELS.is_dir(), reason="作品フォルダが無い環境")
def test_all_real_metas_migrate_safely_in_memory() -> None:
    failures = []
    for path in sorted(NOVELS.glob("*/_meta.md")):
        text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
        try:
            plan = m.migrate_text(text)
            m.verify_migration(text, plan.text, plan.added)
            assert m.check_text(plan.text).form == "new"
        except (m.MetaError, AssertionError) as error:
            failures.append(f"{path.parent.name}: {error}")
    assert failures == []


# --- レビュー指摘（M7〜M10）---


def test_code_block_with_separators_is_kept_intact() -> None:
    text = (
        "## 1. 執筆フェーズ・ステータス\n- a\n\n"
        "```text\n---\n\n---\n```\n\n"
        "## 2. 執筆用コンテキスト・アンカー\n- b\n"
    )
    plan = m.migrate_text(text)
    m.verify_migration(text, plan.text, plan.added)
    assert "```text\n---\n\n---\n```" in plan.text


def test_verification_detects_changed_code_block() -> None:
    before = "## 1. 執筆フェーズ・ステータス\n```text\n---\n\n---\n```\n"
    plan = m.migrate_text(before)
    after = plan.text.replace("```text\n---\n\n---\n```", "```text\n---\n```")
    assert after != plan.text
    with pytest.raises(m.MetaError) as error:
        m.verify_migration(before, after, plan.added)
    assert error.value.code == "CODE_BLOCK_CHANGED"


def _story_reflection_prepared(tmp_path: Path, capsys) -> Path:
    """ストーリー反映の操作を begin だけした（prepared の）作品。"""
    import json

    from test_story_reflection_op import _hashes, _novel, _run_json, _write

    novel = _novel(tmp_path)
    new_design = _write(tmp_path / "d.md", "## 第18章\n\n1. 新確定\n\n## 予定\n\n1. 未執筆\n")
    new_meta = _write(tmp_path / "m.md", "# meta\n\n- **出来事同期**: 2026-10-24 第18章 更新 op=x\n")
    evidence = _write(tmp_path / "e.json", json.dumps(_hashes(novel, design=new_design, meta=new_meta)))
    code, payload = _run_json(tmp_path, capsys, "begin", str(novel), "--evidence", str(evidence))
    assert code == 0 and payload["current"]["status"] == "prepared"
    return novel


@pytest.mark.parametrize("command", [["ensure-section", "evaluation-history"], ["migrate"]])
def test_meta_writes_are_refused_while_story_reflection_is_active(tmp_path: Path, capsys, command) -> None:
    from story_reflection_op import NovelPaths, cmd_inspect

    novel = _story_reflection_prepared(tmp_path, capsys)
    before = (novel / "_meta.md").read_text(encoding="utf-8")
    capsys.readouterr()
    args = [command[0], str(novel), *command[1:]]
    assert m.main(args) == 2
    assert "STORY_REFLECTION_ACTIVE" in capsys.readouterr().out
    assert (novel / "_meta.md").read_text(encoding="utf-8") == before
    assert cmd_inspect(NovelPaths(novel))["verdict"] == "active"  # 進行中の操作は壊れていない


def test_meta_write_takes_story_reflection_lock_and_releases_it(tmp_path: Path) -> None:
    from story_reflection_op import NovelPaths

    work = tmp_path / "001_sample"
    work.mkdir()
    (work / "_meta.md").write_text("## 1. 執筆フェーズ・ステータス\n- a\n", encoding="utf-8")
    assert m.main(["ensure-section", str(work), "evaluation-history"]) == 0
    assert not NovelPaths(work).lock.exists()  # 書き終えたら排他を放す
    with m._StoryReflectionGuard(work):
        assert NovelPaths(work).lock.exists()  # 書く間はストーリー反映と同じ排他を持つ
        with pytest.raises(m.MetaError) as error:
            with m._StoryReflectionGuard(work):
                pass
        assert error.value.code == "STORY_REFLECTION_ACTIVE"
