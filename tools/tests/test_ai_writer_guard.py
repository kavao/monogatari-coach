from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from ai_writer.entities import (  # noqa: E402
    KnownEntityDictionary,
    extract_candidates,
    parse_character_names,
    unknown_candidates,
)
from ai_writer.guard import MinimumGuard  # noqa: E402
from ai_writer.numerics import extract_numbers, kanji_to_int  # noqa: E402
from ai_writer.prompt_renderer import (  # noqa: E402
    BeatContract,
    ContinueInput,
    DirectedContinueInput,
    ExpandInsertionInput,
    render,
)
from ai_writer.provider import NovelAIProvider  # noqa: E402
from ai_writer.testing import FakeTransport, sse  # noqa: E402
from ai_writer.validator_fixtures import load_fixtures  # noqa: E402
from ai_writer.writer import CoreWriter  # noqa: E402

STABLE = {"temperature": 0.8, "top_p": 0.9}


# ---- 数値 ----------------------------------------------------------------------

@pytest.mark.parametrize("text, value", [
    ("千九百四十五", 1945), ("二〇二六", 2026), ("十一", 11), ("三百", 300), ("二万五千", 25000), ("一億二千万", 120000000),
])
def test_kanji_to_int(text: str, value: int) -> None:
    assert kanji_to_int(text) == value


def test_numbers_normalize_across_scripts() -> None:
    keys = [n.key for n in extract_numbers("1945年と１９４５年と千九百四十五年。3人、３人、三人。")]
    assert keys == [(1945, "年")] * 3 + [(3, "人")] * 3


def test_number_idioms_and_unitless_kanji_are_ignored() -> None:
    text = "十分に休んだ。一番好き。三日月。一人称は私。一緒に統一した。千夏は二人で来た。"
    assert [(n.value, n.unit) for n in extract_numbers(text)] == [(2, "人")]
    assert [(n.value, n.unit) for n in extract_numbers("十分間待った。ヶ月とか3ヶ月、三か月")] == [(10, "分間"), (3, "か月"), (3, "か月")]


# ---- 固有名 --------------------------------------------------------------------

def test_candidates_cover_names_roles_and_places() -> None:
    got = [(c.text, c.kind) for c in extract_candidates("奥の書庫から司書の森先生が顔を出した。「美沙子、忘れない」セレスティアは微笑んだ。")]
    assert ("森", "person") in got and ("美沙子", "name_like") in got and ("セレスティア", "katakana") in got
    assert ("司書", "role") in got and ("書庫", "place_noun") in got
    assert ("先生", "role") not in got  # 敬称は名前と一緒に扱う


def test_common_nouns_are_not_name_candidates() -> None:
    assert extract_candidates("椅子に座った様子で、スマートフォンをポケットにしまった。") == []


def test_parse_character_names_from_profile() -> None:
    text = "# 登場人物プロフィール\n\n## 吉田 彩花（よしだ あやか）\n\n- **名前**: 吉田 彩花（よしだ あやか）\n- **一人称**: 私\n"
    assert parse_character_names(text) >= {"吉田彩花", "吉田", "彩花", "よしだ", "あやか"}


def test_dictionary_from_work_folder(tmp_path: Path) -> None:
    (tmp_path / "character.md").write_text("## 早紀（さき）\n\n- **名前**: 早紀（さき）\n", encoding="utf-8")
    (tmp_path / "world.md").write_text("舞台は県立北高校の図書室。司書の森先生がいる。\n", encoding="utf-8")
    d = KnownEntityDictionary.from_work(tmp_path)
    assert d.knows("早紀") and d.knows("森") and d.knows("県立北高校")
    assert unknown_candidates("森先生と早紀が話した。", known=d, sources=()) == []


def test_validator_fixtures_named_and_unnamed_new_entities() -> None:
    """Validator Fixture の新しい人物・場所はすべて候補になり、違反なしの 8 件では候補が出ない。"""
    for fs in load_fixtures():
        d = KnownEntityDictionary()
        for n in fs.context.known_entities.characters + fs.context.known_entities.locations + fs.context.known_entities.items:
            d.add(n, "fixture")
        c = fs.contract
        sources = (fs.context.preceding_text, *fs.context.canon_facts, c.objective, *c.must_include, *c.must_not, c.end_condition)
        for case in fs.cases:
            found = unknown_candidates(case.candidate, known=d, sources=sources)
            types = {v.type for v in case.expected.violations}
            if case.polarity == "negative":
                assert found == [], case.id
            if types & {"new_character", "new_location"}:
                assert found, case.id


# ---- Guard ---------------------------------------------------------------------

def _directed(text: str, facts: tuple[str, ...]) -> DirectedContinueInput:
    return DirectedContinueInput(text, BeatContract("リンが航行の方針を決める", "リンが手動操縦に切り替えた直後", 400,
                                                    ("酸素残量", "航路図"), ("救助船が来る",)), facts)


def test_numeric_delta_points_to_conflicting_value() -> None:
    data = _directed("「ノア、酸素残量は？」「残り十一時間です」", ("最寄りの中継ステーションまで、通常航行で十時間かかる。",))
    rendered = render("directed_continue", data, "glm-4-6", sampling=STABLE)
    report = MinimumGuard().check("時速四千キロなら八時間で着ける。酸素は十一時間ある。", data, rendered)
    nums = [(f.text, f.detail) for f in report.findings if f.check == "numeric_delta"]
    assert nums == [("四千キロ", "元の情報にない数値"), ("八時間", "元の情報では同じ単位が 十一時間・十時間")]  # 本文にある十一時間は出さない
    assert report.status == "warning"


@pytest.mark.parametrize("leak", ["【ここに挿入】", "この場面の契約", "新しい出来事、新しい人物、新しい場所、新しい事実を足さない。"])
def test_instruction_leakage_fails(leak: str) -> None:
    data = ExpandInsertionInput("湊は箸を置いた。", "言うなら今しかない。")
    rendered = render("expand_insertion", data, "glm-4-6", sampling=STABLE)
    report = MinimumGuard().check(f"胸がざわついた。{leak}", data, rendered)
    assert report.status == "fail"
    assert any(f.check == "instruction_leakage" for f in report.findings)


def test_story_text_is_not_mistaken_for_leakage() -> None:
    data = ContinueInput("　条件: 雨の日だけ、彼女は駅に来る。")  # 本文に「条件:」があっても漏れではない
    rendered = render("continue", data, "glm-4-6", sampling=STABLE)
    assert MinimumGuard().check("　条件: 雨の日だけ、と彼は繰り返した。", data, rendered).status == "pass"


def test_phase1_live_expand_passes_but_state_contradiction_is_out_of_scope() -> None:
    """Phase 1 実 API の Expand 出力。箸の状態の矛盾は Minimum Guard の範囲外（Phase 2 の Semantic Validator）。"""
    data = ExpandInsertionInput("　湊は箸を置いた。", "言うなら今しかない、と思った。")
    rendered = render("expand_insertion", data, "glm-4-6", sampling=STABLE)
    out = "背筋に緊張が走り、湯気に曇った窓ガラスに視線を落とした。握りしめた箸先が、じんわりと汗で湿っていく。"
    report = MinimumGuard().check(out, data, rendered)
    assert report.status == "pass"
    assert "semantic（Phase 2）" in report.not_run


def test_core_writer_attaches_guard_report_to_record() -> None:
    t = FakeTransport(sse("　その時、背後で", "駅員が咳払いをした。"))
    provider = NovelAIProvider("pst-guard-test", transport=t, slot=threading.BoundedSemaphore(1), sleep=lambda _s: None)
    known = KnownEntityDictionary()
    known.add("悠真", "character")
    out = CoreWriter(provider, guard=MinimumGuard(known)).run("continue", ContinueInput("　悠真はベンチの下に手を伸ばした。"))
    assert out.guard is not None and out.guard.status == "warning"
    record = out.record()
    assert record["guard"]["status"] == "warning"
    assert [f["text"] for f in record["guard"]["findings"]] == ["駅員"]
    json.dumps(record, ensure_ascii=False)
    t.scripts.append(sse("本文。"))
    assert CoreWriter(provider).run("continue", ContinueInput("本文。")).record()["guard"] is None


# ---- 冒頭反復（mg-2） ----------------------------------------------------------------

BATTLE = ("　黒い狼の魔獣が、低く唸りながら間合いを詰めてくる。カイは折れた剣を構え直した。\n"
          "　魔獣が跳んだ。カイは身を沈め、牙が頭上をかすめるのを感じた。振り向きざまに剣を振るうが、硬い毛皮に弾かれる。")


def _opening(output: str, text: str = BATTLE) -> list[str]:
    from ai_writer.guard import check_opening_repetition

    data = DirectedContinueInput(text, BeatContract("目的", "終わり", 400))
    return [f.detail for f in check_opening_repetition(output, data)]


def test_opening_repetition_from_length_experiment_b2() -> None:
    """字数不足の比較実験 B #2（battle）の冒頭。元の文の後ろ半分の写しから続けて 2 文。"""
    out = "牙が頭上をかすめるのを感じた。振り向きざまに剣を振るうが、硬い毛皮に弾かれる。間合いを取ろうと後ずさる。"
    assert _opening(out) == ["冒頭で元の本文の文を 2 文そのまま繰り返している"]


def test_opening_repetition_ignores_paraphrase_short_lines_and_later_quotes() -> None:
    assert _opening("牙が頭上をかすめた。カイは剣を握り直した。") == []  # 言い換え
    assert _opening("「うん」\n　カイは剣を握り直した。", "「うん」と言った。\n" + BATTLE) == []  # 短い台詞
    assert _opening("カイは息を整えた。振り向きざまに剣を振るうが、硬い毛皮に弾かれる。") == []  # 冒頭でない


def test_guard_report_includes_opening_repetition() -> None:
    data = DirectedContinueInput(BATTLE, BeatContract("目的", "終わり", 400))
    rendered = render("directed_continue", data, "glm-4-6", sampling=STABLE)
    report = MinimumGuard().check("振り向きざまに剣を振るうが、硬い毛皮に弾かれる。息が切れる。", data, rendered)
    assert report.version == "mg-2" and "opening_repetition" in report.checks_run
    assert [(f.check, f.severity) for f in report.findings] == [("opening_repetition", "warning")]
