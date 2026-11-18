#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import novel_beat_draft as nbd  # noqa: E402
import prose_signals as ps  # noqa: E402
import writer_profiles as wp  # noqa: E402

CHARACTER = """# 登場人物プロフィール

## 悠希（ゆうき）
- **名前**: 悠希
- **身長**: 約172cm
- **性格**: 壊れた物を見ると、直せるかどうかを先に確かめる。
- **外見**: 短い黒髪で、目の下に薄いクマが残る。手の甲に倉庫の棚の傷がある。
- **外見の個性**:
  - 短い黒髪と、目の下の薄いクマが第一印象に残る
- **服装**:
  - **普段着**: 灰色の作業着、布靴、腰の紐。
- **口調**: 物の順を先に出す。

## ノラ（道具小屋の預かり人）
- **名前**: ノラ
- **外見**: 編み込んだ茶髪を耳の上で結んでいる。右手の甲に縄の跡がある。
- **口調**: です・ますで距離を保つ。
"""

DESIGN = """# 小説設計書

## テーマ

直した物の値。

## コンセプト

村の道具を直す。

## 章構成

### 第1章「二本の桶」

1. 悠希が目覚める。
2. ノラが桶を貸す。

### 第2章「石鹸」

1. 石鹸を作る。
"""

WORLD = """# 世界観

## 用語

| 用語ID | 正式名称 | 種別 | 定義・適用範囲 | 許容表記・略称 | 避ける表記 | 備考 |
|--------|----------|------|----------------|----------------|------------|------|
| term_001 | 石倉庫の跡 | 場所 | 崩れた倉庫 | ― | 遺跡 | 初出: 第1章 |
| term_002 | 当番表 | 制度 | 村の表 | ― | シフト表 | 初出: 第2章 |
"""

CONFIG = """# 作品設定

## 基本情報

| 項目 | 内容 |
|------|------|
| novel_ID | 900 |

## 執筆方針
- 近距離三人称。

## ステータス
- 進行中
"""

BEATS = [
    {"id": "wake", "type": "action", "intent": "悠希が石倉庫の跡で目覚め、ノラから井戸の話を聞く", "chars_hint": 200},
    {"id": "buckets", "type": "action", "intent": "悠希が水を二本の桶に分ける", "chars_hint": 200},
    {"id": "lend", "type": "dialogue", "intent": "ノラが桶を貸す", "chars_hint": 200},
]


def _work(tmp_path: Path, model_id: str = "strata-qwen3.8") -> Path:
    work = tmp_path / "900_試験"
    work.mkdir()
    (work / "character.md").write_text(CHARACTER, encoding="utf-8")
    (work / "design_specification.md").write_text(DESIGN, encoding="utf-8")
    (work / "world.md").write_text(WORLD, encoding="utf-8")
    (work / "config.md").write_text(CONFIG, encoding="utf-8")
    run = work / "_work" / "writing" / "ch01-001" / "run-0001"
    run.mkdir(parents=True)
    (run / "request.yaml").write_text(f"schema: 1\nrun_id: run-0001\nmodel:\n  id: {model_id}\n", encoding="utf-8")
    context = {"beats": BEATS, "forbidden": ["魔法で湯を沸かすこと"], "chars_floor": 500}
    (run / "context.json").write_text(json.dumps(context, ensure_ascii=False), encoding="utf-8")
    return work


class FakeWriter:
    """Beat ごとの候補を順に返す。prompts に受け取ったプロンプトを残す。"""

    def __init__(self, outputs: list[str]) -> None:
        self.outputs = list(outputs)
        self.prompts: list[str] = []
        self.seeds: list[int] = []

    def __call__(self, prompt: str, **kwargs) -> dict:
        self.prompts.append(prompt)
        self.seeds.append(kwargs["seed"])
        return {"content": self.outputs.pop(0), "finish_reason": "stop", "model_label": "fake"}


# ── prose_signals ──────────────────────────────────────────────────


def test_overlaps_finds_long_copies_only() -> None:
    prior = "　悠希は桶を井戸の縁に置き、濁った水を布で濾した。"
    assert ps.overlaps("悠希は桶を井戸の縁に置き、別の桶を取った。", prior) == ["悠希は桶を井戸の縁に置き、"]
    assert ps.overlaps("ノラが桶を貸した。", prior) == []


def test_overlaps_do_not_span_dialogue_brackets() -> None:
    prior = "「水です」ノラは言った。「魔法は切れました」"
    assert ps.overlaps("「桶です」ノラは言った。「魔法の話です」", prior) == []
    assert ps.overlaps("「魔法は切れました」と繰り返した。", prior) == []
    assert ps.overlaps("「井戸の魔法は今週で切れました」", "「井戸の魔法は今週で切れました」") == ["井戸の魔法は今週で切れました"]


def test_redescribed_only_for_introduced_people() -> None:
    appearance = ps.appearance_lines(CHARACTER)
    text = "ノラは編み込んだ茶髪を揺らした。悠希は短い黒髪をかいた。"
    assert ps.redescribed(text, {"ノラ"}, appearance) == ["ノラ:編み込んだ茶"]
    assert ps.redescribed(text, set(), appearance) == []


def test_narration_drops_dialogue_and_markers() -> None:
    text = "# 第1章\n<!--beat:a-->\n　桶を置いた。「水です」\n<!--/beat:a-->"
    assert "水です" not in ps.narration(text)
    assert "beat" not in ps.narration(text)
    assert ps.sentences(ps.narration(text)) == ["桶を置いた"]


def test_tell_per_k_counts_conclusion_endings() -> None:
    narr = "悠希は桶が足りないと知った。ノラが桶を置いた。"
    assert ps.tell_per_k(narr) > 0
    assert ps.tell_per_k("ノラが桶を置いた。") == 0


# ── 資料 ──────────────────────────────────────────────────────────


def test_characters_reduced_keeps_appearance_only_for_shown() -> None:
    reduced = nbd.characters_reduced(CHARACTER, {"悠希"})
    assert "短い黒髪で" in reduced and nbd.APPEARANCE_LABEL in reduced
    assert "編み込んだ茶髪" not in reduced
    for dropped in ("約172cm", "第一印象", "灰色の作業着"):
        assert dropped not in reduced
    assert "物の順を先に出す" in reduced


def test_world_reduced_drops_later_terms() -> None:
    reduced = nbd.world_reduced(WORLD, 1)
    assert "石倉庫の跡" in reduced and "当番表" not in reduced


def test_build_materials_picks_chapter_and_skips_showing_axes(tmp_path: Path) -> None:
    work = _work(tmp_path)
    (work / "_meta.md").write_text("## 3.7 見せ方軸\n- 自己像を低く見積もる\n", encoding="utf-8")
    m = nbd.build_materials(work, "ch01-001", ["禁止"], [])
    bg = m.background(set())
    assert m.title_line == "# 第1章「二本の桶」"
    assert "悠希が目覚める" in bg and "石鹸を作る" not in bg
    assert "直した物の値" in bg and "近距離三人称" in bg
    assert "低く見積もる" not in bg
    assert bg.count("forbidden: 禁止") == 1
    assert m.names == ["悠希", "ノラ"]


def test_first_beats_by_name_in_intent() -> None:
    assert nbd.first_beats(BEATS, ["悠希", "ノラ"]) == {"悠希": 0, "ノラ": 0}


def test_chapter_number_requires_ch_prefix() -> None:
    assert nbd.chapter_number("ch12-003") == 12
    with pytest.raises(nbd.BeatDraftError):
        nbd.chapter_number("scene-1")


# ── 選択と組み立て ────────────────────────────────────────────────


def test_draft_rejects_copies_and_assembles(tmp_path: Path) -> None:
    work = _work(tmp_path)
    beat1 = "　悠希は石倉庫の跡で目を開け、ノラから井戸の水が濁っていると聞いた。"
    outputs = [
        beat1, beat1, beat1,
        # Beat 2：前の文の写し（外れる）、ノラの外見の描き直し（外れる）、正しい候補
        "　悠希は石倉庫の跡で目を開け、ノラから井戸の水が濁っていると聞いた。桶を置いた。",
        "　ノラは編み込んだ茶髪を揺らした。悠希は水を二本の桶に分けた。",
        "　悠希は布で水を濾し、澄んだ水と濁った水を二本の桶に分けた。",
        # Beat 3：全部外れる（全落ち）
        "　ノラは編み込んだ茶髪を揺らし、桶を貸した。",
        "　ノラは右手の甲に縄の跡がある手で、桶を貸した。",
        "　ノラは編み込んだ茶髪を耳の上で結び直し、桶を差し出した。",
    ]
    writer = FakeWriter(outputs)
    logs: list[str] = []
    final = nbd.draft(work, "ch01-001", "run-0001", writer=writer, log=logs.append)

    text = final.read_text(encoding="utf-8")
    assert text.startswith("# 第1章「二本の桶」\n")
    for bid in ("wake", "buckets", "lend"):
        assert f"<!--beat:{bid}-->" in text and f"<!--/beat:{bid}-->" in text
    assert "布で水を濾し" in text

    selection = json.loads((final.parent / "selection.json").read_text(encoding="utf-8"))
    b2 = selection["beats"][1]
    assert b2["selected"] == "beat2.c3.md" and not b2["fallback"]
    assert b2["candidates"][0]["overlaps"] and b2["candidates"][1]["redescribed"]
    assert selection["fallback_beats"] == ["lend"]
    assert selection["beats"][0]["show_appearance"] == ["ノラ", "悠希"]

    # 外見は初登場の Beat 1 にだけ渡す。Beat 2 以降のプロンプトには前の本文が全文入る
    assert "編み込んだ茶髪" in writer.prompts[0]
    assert "編み込んだ茶髪" not in writer.prompts[3]
    assert beat1.strip() in writer.prompts[3]
    assert writer.seeds[:4] == [100, 101, 102, 110]
    assert len(logs) == 3


def test_cut_copies_removes_only_self_contained_copies() -> None:
    prior = "　悠希は布で泥混じりの水を濾し、澄んだ水を鍋に移した。「別に、直しただけです。棚の順と同じです」"
    appearance = ps.appearance_lines(CHARACTER)
    text = (
        "　ノラは桶を受け取った。悠希は布で泥混じりの水を濾し、澄んだ水を鍋に移した。\n"
        "「別に、直しただけです。棚の順と同じです」\n"
        "　ノラは編み込んだ茶髪を揺らした。ノラは言った。"
    )
    cut, removed = nbd.cut_copies(text, prior, {"ノラ"}, appearance)
    assert "ノラは桶を受け取った。" in cut and "ノラは言った。" in cut
    assert "濾し" not in cut and "直しただけ" not in cut and "編み込んだ" not in cut
    assert [r["reason"].split(":")[0] for r in removed] == ["前の本文と一致", "前の本文と一致", "外見の描き直し"]
    assert cut.startswith("　ノラは桶を")


def test_lookahead_flags_only_later_events() -> None:
    later = "悠希が汚れた水の桶の取っ手に縄を一巻きする"
    current = "悠希が澄んだ水を沸かし、飲める水と汚れた水を二本の桶に分けて並べる"
    text = "　悠希は飲める水と汚れた水を二本の桶に分けた。汚れた水の桶の取っ手に、縄を一巻きした。"
    assert ps.lookahead(text, later, current) == ["汚れた水の桶の取っ手に縄を一巻き"]
    # 今の出来事にある言い回しと、すでに本文に出た言い回しは先取りにしない
    assert ps.lookahead("　悠希は二本の桶に分けた。", later, current) == []
    assert ps.lookahead(text, later, current, prior="汚れた水の桶の取っ手に縄を一巻きした") == []


def test_forbidden_terms_are_read_from_contract_wording() -> None:
    forbidden = ["魔法で湯を沸かすこと", "当番表という語を書くこと（第2章が初出）", "冬囲いという語を書くこと（用語表に未登録）"]
    terms = ps.forbidden_terms(forbidden)
    assert terms == ["当番表", "冬囲い"]
    assert ps.forbidden_hits("　村の当番表ではない。", terms) == ["当番表"]


def test_lookahead_and_forbidden_candidates_are_rejected(tmp_path: Path) -> None:
    work = _work(tmp_path)
    run = work / "_work" / "writing" / "ch01-001" / "run-0001"
    context = json.loads((run / "context.json").read_text(encoding="utf-8"))
    context["forbidden"] = ["当番表という語を書くこと（第2章が初出）"]
    (run / "context.json").write_text(json.dumps(context, ensure_ascii=False), encoding="utf-8")
    ahead = "　悠希は石倉庫の跡で目を開けた。悠希は水を二本の桶に分けた。"
    banned = "　悠希は石倉庫の跡で目を開けた。村の当番表を思った。"
    clean_text = "　悠希は石倉庫の跡で目を開け、ノラから井戸の話を聞いた。"
    writer = FakeWriter([ahead, banned, clean_text] + ["　悠希は水を分けた。"] * 3 + ["　ノラが桶を貸した。"] * 3)
    final = nbd.draft(work, "ch01-001", "run-0001", writer=writer, log=lambda _: None)
    b1 = json.loads((final.parent / "selection.json").read_text(encoding="utf-8"))["beats"][0]
    rows = {r["candidate"]: r for r in b1["candidates"]}
    assert rows["beat1.c1.md"]["rejected"] and rows["beat1.c1.md"]["lookahead"]
    assert rows["beat1.c2.md"]["rejected"] and rows["beat1.c2.md"]["forbidden"] == ["当番表"]
    assert b1["selected"] == "beat1.c3.md" and not b1["fallback"]


def test_relay_writes_prompt_and_waits_then_resumes(tmp_path: Path) -> None:
    work = _work(tmp_path)
    out = work / "_work" / "writing" / "ch01-001" / "run-0001" / "beat_draft"
    with pytest.raises(nbd.BeatDraftError) as wait:
        nbd.draft(work, "ch01-001", "run-0001", candidates=2, relay=True, log=lambda _: None)
    assert wait.value.code == 3 and "RELAY_WAIT" in str(wait.value) and "beat1.c1.md" in str(wait.value)
    assert (out / "beat1.prompt.md").is_file() and not (out / "beat2.prompt.md").exists()
    texts = ["　悠希は石倉庫の跡で目を開け、ノラから井戸の話を聞いた。", "　悠希は水を二本の桶に分けた。", "　ノラが桶を貸した。"]
    for n, text in enumerate(texts, start=1):
        for c in (1, 2):
            (out / f"beat{n}.c{c}.md").write_text(text + "\n", encoding="utf-8")
        if n < len(texts):
            with pytest.raises(nbd.BeatDraftError) as wait:
                nbd.draft(work, "ch01-001", "run-0001", candidates=2, relay=True, log=lambda _: None)
            assert f"Beat {n + 1}/3" in str(wait.value) and (out / f"beat{n + 1}.prompt.md").is_file()
    final = nbd.draft(work, "ch01-001", "run-0001", candidates=2, relay=True, log=lambda _: None)
    assert "ノラが桶を貸した。" in final.read_text(encoding="utf-8")
    assert json.loads((out / "selection.json").read_text(encoding="utf-8"))["params"]["relay"] is True


def test_relay_allows_unconnected_backend() -> None:
    profile, writer = nbd.resolve_writer({"model": {"id": "grok-4.6"}}, relay=True)
    assert profile.backend == "grok_cli" and writer is None
    with pytest.raises(nbd.BeatDraftError, match="--relay"):
        nbd.resolve_writer({"model": {"id": "grok-4.6"}})


def test_fallback_cut_removes_lookahead_and_forbidden_sentences() -> None:
    later = "悠希が汚れた水の桶の取っ手に縄を一巻きする"
    text = "　悠希は水を沸かした。汚れた水の桶の取っ手に縄を一巻きした。村の当番表ではない。"
    cut, removed = nbd.cut_copies(text, "", set(), {}, later=later, current="悠希が水を沸かす", terms=["当番表"])
    assert cut == "　悠希は水を沸かした。"
    assert [r["reason"].split(":")[0] for r in removed] == ["先取り", "書かない語"]


def test_repeated_lines_catch_catchphrase_forms_from_third_time() -> None:
    # run-0009 で各 Beat の締めに出た型。12字一致では捕まらない
    prior = "「別に、見ただけです」\n「棚の順で分けます」\n「別に、布を折っただけです」\n「棚の順で分けます」"
    assert ps.repeated_lines("「別に、分けただけです」", prior) == ["別に、分けただけです"]
    assert ps.repeated_lines("「ルーベンさん。棚の順で分けます」", prior) == ["ルーベンさん。棚の順で分けます"]
    # 1〜2回目は残す。違う形の台詞は数えない
    assert ps.repeated_lines("「別に、分けただけです」", "「別に、見ただけです」") == []
    assert ps.repeated_lines("「人の許可なく、棚の順を変えられました」", prior) == []
    assert ps.repeated_lines("「はい」", "「はい」\n「はい」") == ["はい"]
    # 候補の中の繰り返しも数える
    assert ps.repeated_lines("「別に、a ただけです」「別に、bただけです」「別に、cただけです」", "") == ["別に、cただけです"]


def test_fallback_cut_removes_third_catchphrase() -> None:
    prior = "「別に、見ただけです」\n「別に、布を折っただけです」"
    text = "　悠希は桶を置いた。\n「別に、分けただけです」\n「水は二本にします」"
    cut, removed = nbd.cut_copies(text, prior, set(), {})
    assert cut == "　悠希は桶を置いた。\n「水は二本にします」"
    assert [r["reason"].split(":")[0] for r in removed] == ["口癖の繰り返し"]


def test_catchphrase_candidate_is_rejected(tmp_path: Path) -> None:
    work = _work(tmp_path)
    beat1 = "　悠希は石倉庫の跡で目を開け、ノラから井戸の話を聞いた。\n「別に、見ただけです」"
    beat2 = "　悠希は水を二本の桶に分けた。\n「別に、分けただけです」"
    rep = "　ノラが桶を貸した。\n「別に、借りただけです」"
    plain = "　ノラが桶を貸した。悠希は受け取った。"
    writer = FakeWriter([beat1] * 3 + [beat2] * 3 + [rep, rep, plain])
    final = nbd.draft(work, "ch01-001", "run-0001", writer=writer, log=lambda _: None)
    b3 = json.loads((final.parent / "selection.json").read_text(encoding="utf-8"))["beats"][2]
    assert b3["candidates"][0]["repeats"] == ["別に、借りただけです"] and b3["candidates"][0]["rejected"]
    assert b3["selected"] == "beat3.c3.md" and not b3["fallback"]


def test_dialogue_lines_lose_leading_space_and_prompt_says_so(tmp_path: Path) -> None:
    assert nbd.clean("　悠希は言った。\n　「水です」\n 『札』") == "　悠希は言った。\n「水です」\n『札』"
    work = _work(tmp_path)
    writer = FakeWriter(["　悠希は目を開けた。\n　「水は」"] * 3 + ["　悠希は桶を置いた。"] * 3 + ["　ノラが桶を貸した。"] * 3)
    final = nbd.draft(work, "ch01-001", "run-0001", writer=writer, log=lambda _: None)
    assert "\n「水は」" in final.read_text(encoding="utf-8")
    assert "会話の行は空白を付けず「から始める" in writer.prompts[0]


def test_fallback_beat_is_cut_and_shortfall_reported(tmp_path: Path) -> None:
    work = _work(tmp_path)
    beat1 = "　悠希は石倉庫の跡で目を開け、ノラから井戸の水が濁っていると聞いた。"
    copy = "　悠希は石倉庫の跡で目を開け、ノラから井戸の水が濁っていると聞いた。悠希は水を二本の桶に分けた。"
    writer = FakeWriter([beat1] * 3 + [copy] * 3 + ["　ノラが桶を貸した。"] * 3)
    final = nbd.draft(work, "ch01-001", "run-0001", writer=writer, log=lambda _: None)
    text = final.read_text(encoding="utf-8")
    assert text.count("石倉庫の跡で目を開け") == 1
    assert "悠希は水を二本の桶に分けた。" in text
    selection = json.loads((final.parent / "selection.json").read_text(encoding="utf-8"))
    b2 = selection["beats"][1]
    assert b2["fallback"] and len(b2["cut"]) == 1
    short = selection["shortfall"]
    assert short["scene_floor"] == 500 and short["scene_short"] == 500 - short["scene_chars"]
    assert {b["beat"] for b in short["beats_short"]} == {"wake", "buckets", "lend"}


def test_density_check_against_instruction_target() -> None:
    beats = [{"id": "a", "chars_instruction": 100}, {"id": "b", "chars_instruction": 100}]
    rows = [{"beat": "a", "chars": 95}, {"beat": "b", "chars": 50}]
    d = nbd.density_check({"instruction_chars": 200}, beats, rows)
    assert d["scene_shortage"] == 0.275 and d["over_limit"]
    assert [b["beat"] for b in d["beats_over_limit"]] == ["b"]
    ok = nbd.density_check({"instruction_chars": 200}, beats, [{"beat": "a", "chars": 95}, {"beat": "b", "chars": 95}])
    assert not ok["over_limit"] and ok["beats_over_limit"] == []


def test_cli_reports_design_density(tmp_path: Path, monkeypatch, capsys) -> None:
    work = _work(tmp_path)
    writer = FakeWriter(["　悠希は目を開けた。"] * 3 + ["　悠希は桶を置いた。"] * 3 + ["　ノラが桶を貸した。"] * 3)
    real = nbd.draft
    monkeypatch.setattr(nbd, "draft", lambda *a, **k: real(*a, **dict(k, writer=writer, log=lambda _: None)))
    code = nbd.main(["run", str(work), "--scene-id", "ch01-001", "--run-id", "run-0001"])
    out = capsys.readouterr().out
    assert code == 0
    assert "DESIGN_DENSITY" in out and "子エピソード" in out
    assert nbd.SUB_EPISODE_LEAF in out and "addition_issues" in out and "設計追加の手順" in out
    assert (nbd.ROOT / nbd.SUB_EPISODE_LEAF).is_file() and (nbd.ROOT / nbd.LENGTH_OPS).is_file()
    selection = json.loads((work / "_work/writing/ch01-001/run-0001/beat_draft/selection.json").read_text(encoding="utf-8"))
    assert selection["design_density"]["over_limit"]


def test_fallback_that_is_all_copy_is_kept_not_emptied(tmp_path: Path) -> None:
    work = _work(tmp_path)
    beat1 = "　悠希は石倉庫の跡で目を開け、ノラから井戸の水が濁っていると聞いた。"
    writer = FakeWriter([beat1] * 6 + ["　ノラが桶を貸した。"] * 3)
    final = nbd.draft(work, "ch01-001", "run-0001", writer=writer, log=lambda _: None)
    selection = json.loads((final.parent / "selection.json").read_text(encoding="utf-8"))
    assert all(r.get("kept") for r in selection["beats"][1]["cut"])
    assert "<!--beat:buckets-->\n　悠希は石倉庫の跡で" in final.read_text(encoding="utf-8")


def test_prompt_uses_instruction_target_not_floor(tmp_path: Path) -> None:
    work = _work(tmp_path)
    run = work / "_work" / "writing" / "ch01-001" / "run-0001"
    context = json.loads((run / "context.json").read_text(encoding="utf-8"))
    context["beats"] = [dict(context["beats"][0], chars_instruction=280)]
    (run / "context.json").write_text(json.dumps(context, ensure_ascii=False), encoding="utf-8")
    writer = FakeWriter(["　悠希は目を開けた。"] * 3)
    nbd.draft(work, "ch01-001", "run-0001", writer=writer, log=lambda _: None)
    assert "およそ280字" in writer.prompts[0] and "およそ200字" not in writer.prompts[0]


def test_draft_resumes_from_saved_candidates(tmp_path: Path) -> None:
    work = _work(tmp_path)
    out = work / "_work" / "writing" / "ch01-001" / "run-0001" / nbd.OUT_DIR
    out.mkdir()
    for i in range(1, 4):
        for c in range(1, 4):
            (out / f"beat{i}.c{c}.md").write_text(f"　候補{i}-{c}の文で、桶が{i * 10 + c}個ある。\n", encoding="utf-8")
    writer = FakeWriter([])
    final = nbd.draft(work, "ch01-001", "run-0001", writer=writer, log=lambda _: None)
    assert writer.prompts == []
    selection = json.loads((final.parent / "selection.json").read_text(encoding="utf-8"))
    assert all(c["reused"] for b in selection["beats"] for c in b["candidates"])


def test_draft_refuses_existing_draft_and_never_touches_novel_text(tmp_path: Path) -> None:
    work = _work(tmp_path)
    out = work / "_work" / "writing" / "ch01-001" / "run-0001" / nbd.OUT_DIR
    out.mkdir()
    (out / "draft.md").write_text("x", encoding="utf-8")
    with pytest.raises(nbd.BeatDraftError):
        nbd.draft(work, "ch01-001", "run-0001", writer=FakeWriter([]), log=lambda _: None)
    assert not (work / "_novel_text").exists()


def test_draft_requires_prepared_run(tmp_path: Path) -> None:
    work = _work(tmp_path)
    with pytest.raises(nbd.BeatDraftError, match="prepare"):
        nbd.draft(work, "ch01-001", "run-0009", writer=FakeWriter([]), log=lambda _: None)


def test_empty_candidate_stops_with_writer_error(tmp_path: Path) -> None:
    work = _work(tmp_path)
    with pytest.raises(nbd.BeatDraftError) as info:
        nbd.draft(work, "ch01-001", "run-0001", writer=FakeWriter(["  "]), log=lambda _: None)
    assert info.value.code == 1


# ── 書き手の段 ────────────────────────────────────────────────────


def _profiles(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "writer_profiles.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def test_profiles_load_and_validate(tmp_path: Path) -> None:
    good = _profiles(tmp_path, "writers:\n  w1:\n    tier: low_context\n    backend: local_openai\n    model: m\n    context_tokens: 262144\n")
    assert wp.load_profiles(good)["w1"].tier == "low_context"
    bad = _profiles(tmp_path, "writers:\n  w1:\n    tier: tiny\n    backend: local_openai\n")
    with pytest.raises(wp.WriterProfileError):
        wp.load_profiles(bad)
    unknown = _profiles(tmp_path, "writers:\n  w1:\n    tier: standard\n    backend: grok_cli\n    temp: 1\n")
    with pytest.raises(wp.WriterProfileError):
        wp.load_profiles(unknown)


def test_repo_profiles_mark_local_writer_low_context() -> None:
    profiles = wp.load_profiles()
    assert profiles["strata-qwen3.8"].tier == "low_context"
    assert profiles["strata-qwen3.8"].backend == "local_openai"
    # prepare の既定の名前は書き手を表さないので、段の表に無い
    assert "local-writer" not in profiles


def test_default_prepare_model_is_not_a_low_context_writer(tmp_path: Path) -> None:
    with pytest.raises(nbd.BeatDraftError, match="prepare --model"):
        nbd.resolve_writer({"model": {"id": "local-writer"}})
    bad = _profiles(tmp_path, "writers:\n  local-writer:\n    tier: low_context\n    backend: local_openai\n")
    with pytest.raises(wp.WriterProfileError, match="既定の名前"):
        wp.load_profiles(bad)


@pytest.mark.parametrize(
    ("tier", "backend", "message"),
    [("standard", "local_openai", "low_context"), ("low_context", "grok_cli", "接続していない")],
)
def test_resolve_writer_refuses_standard_and_unconnected(monkeypatch, tier, backend, message) -> None:
    profile = wp.WriterProfile("w", tier, backend, "m", "w", None)
    monkeypatch.setattr(nbd, "get_profile", lambda model_id: profile)
    with pytest.raises(nbd.BeatDraftError, match=message):
        nbd.resolve_writer({"model": {"id": "w"}})


def test_resolve_writer_refuses_unregistered(monkeypatch) -> None:
    monkeypatch.setattr(nbd, "get_profile", lambda model_id: None)
    with pytest.raises(nbd.BeatDraftError, match="writer_profiles"):
        nbd.resolve_writer({"model": {"id": "unknown"}})


# ── レビュー（2026-11-18）の指摘 ───────────────────────────────────


class TruncatingWriter(FakeWriter):
    """指定した候補（呼び出しの順番）だけ finish_reason=length を返す。"""

    def __init__(self, outputs: list[str], truncated: set[int]) -> None:
        super().__init__(outputs)
        self.truncated = truncated
        self.calls = 0

    def __call__(self, prompt: str, **kwargs) -> dict:
        result = super().__call__(prompt, **kwargs)
        if self.calls in self.truncated:
            result["finish_reason"] = "length"
        self.calls += 1
        return result


def test_truncated_candidate_is_not_selected(tmp_path: Path) -> None:
    work = _work(tmp_path)
    writer = TruncatingWriter(["　悠希は目を開け", "　悠希は石倉庫の跡で目を開けた。"] + ["　悠希は目を開けた。"]
                              + ["　悠希は桶を置いた。"] * 3 + ["　ノラが桶を貸した。"] * 3, {0})
    final = nbd.draft(work, "ch01-001", "run-0001", writer=writer, log=lambda _: None)
    b1 = json.loads((final.parent / "selection.json").read_text(encoding="utf-8"))["beats"][0]
    assert b1["candidates"][0]["truncated"] and b1["candidates"][0]["rejected"]
    assert b1["selected"] != "beat1.c1.md"


def test_all_truncated_candidates_stop_instead_of_completing(tmp_path: Path) -> None:
    work = _work(tmp_path)
    writer = TruncatingWriter(["　悠希は目を"] * 3, {0, 1, 2})
    with pytest.raises(nbd.BeatDraftError, match="GENERATION_TRUNCATED") as stop:
        nbd.draft(work, "ch01-001", "run-0001", writer=writer, log=lambda _: None)
    assert stop.value.code == 1
    assert not (work / "_work/writing/ch01-001/run-0001/beat_draft/draft.md").exists()
    # 保存済みの打切り候補で再開しても、作業稿は完成しない
    with pytest.raises(nbd.BeatDraftError, match="GENERATION_TRUNCATED"):
        nbd.draft(work, "ch01-001", "run-0001", writer=FakeWriter([]), log=lambda _: None)


def test_resume_refuses_candidates_written_from_another_prompt(tmp_path: Path) -> None:
    work = _work(tmp_path)
    out = work / "_work" / "writing" / "ch01-001" / "run-0001" / nbd.OUT_DIR
    with pytest.raises(nbd.BeatDraftError):  # Beat 1 の候補を置いた後、Beat 2 で止まる
        nbd.draft(work, "ch01-001", "run-0001", writer=FakeWriter(["　悠希は目を開けた。"] * 3), log=lambda _: None)
    assert (out / "beat1.c1.md").exists()
    leaf = tmp_path / "leaf.md"
    leaf.write_text("# 葉\n\n新しい資料。\n", encoding="utf-8")
    with pytest.raises(nbd.BeatDraftError, match="STALE_CANDIDATES"):
        nbd.draft(work, "ch01-001", "run-0001", leaves=[leaf], writer=FakeWriter([]), log=lambda _: None)


def test_dialogue_only_candidate_is_scored() -> None:
    row = nbd.score("「水です」\n「はい」", 200, [])
    assert row["no_chain_pct"] == 0.0 and row["chars"] <= 1  # 地の文は改行だけ


def test_plan_works_for_unconnected_backend(tmp_path: Path) -> None:
    work = _work(tmp_path, model_id="grok-4.6")
    text = nbd.plan(work, "ch01-001", "run-0001", [])
    assert "grok-4.6" in text and "grok_cli" in text


def test_world_reduced_uses_glossary_first_chapter_forms() -> None:
    world = WORLD + "| term_003 | 冬囲い | 制度 | 冬の備え | ― | ― | 第3章で初出 |\n"
    reduced = nbd.world_reduced(world, 1)
    assert "石倉庫の跡" in reduced and "当番表" not in reduced and "冬囲い" not in reduced
