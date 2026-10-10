from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from ai_writer import bench  # noqa: E402
from ai_writer.postprocess import CleanPolicy, CleanResult, clean, clean_for  # noqa: E402
from ai_writer.profiles import load_profiles  # noqa: E402
from ai_writer.prompt_renderer import (  # noqa: E402
    RENDERER_VERSION,
    BeatContract,
    ContinueInput,
    DirectedContinueInput,
    ExpandInsertionInput,
    render,
)
from ai_writer.provider import ContextLimitError, NovelAIProvider  # noqa: E402
from ai_writer.router import NOVELAI_SAMPLING, OperationRouter, RouteError  # noqa: E402
from ai_writer.testing import FakeHandle, FakeTransport, sse  # noqa: E402
from ai_writer.transport import TransportError  # noqa: E402
from ai_writer.writer import CoreWriter  # noqa: E402

TOKEN = "pst-core-test"


def kept(raw: str, result: CleanResult) -> str:
    """切り落とし範囲を除いた残りをつなぐ。整形後の本文と一致しなければならない。"""
    out, pos = "", 0
    for r in result.removals:
        out += raw[pos:r.start]
        pos = r.end
    return out + raw[pos:]


# ---- 後処理 ------------------------------------------------------------------

@pytest.mark.parametrize("raw, text, reason", [
    # Phase 0 で観測した形（短くしたもの）
    ("\n陽太は照れくさそうに微笑んだ。\n***\n[採点結果]\n・合計評価: A\n", "陽太は照れくさそうに微笑んだ。", "scene_break"),
    ("本文の最後。\n【中文翻译】\n夜晚的旧教学楼", "本文の最後。", "trailer"),
    ("めない。仲間を待つ。\n\n---\n\n**1. Deconstruct the Original Text**", "めない。仲間を待つ。", "trailer"),
    ("自信が持てた。\n[作者:ポポン]\n[タイトル:進路相談]", "自信が持てた。", "trailer"),
    ("そっと開けた。\n書き手の意図:\n　緊張を足しました。", "そっと開けた。", "trailer"),
])
def test_trailers_from_phase0_are_cut_with_reason(raw: str, text: str, reason: str) -> None:
    result = clean_for("directed_continue", raw)
    assert result.text == text
    assert reason in [r.reason for r in result.removals]
    assert kept(raw, result) == result.text


def test_expand_keeps_first_paragraph_only() -> None:
    raw = "\n椅子に指をかけたまま動けない。\n\n書き足した説明の段落。"
    result = clean_for("expand_insertion", raw)
    assert result.text == "椅子に指をかけたまま動けない。"
    assert [r.reason for r in result.removals] == ["leading_space", "expand_first_paragraph"]
    assert kept(raw, result) == result.text


def test_continue_keeps_paragraphs_and_trims_partial_tail() -> None:
    raw = "　一段落目。\n　二段落目。\n　三段落目の途中で切れ"
    result = clean_for("continue", raw)
    assert result.text == "　一段落目。\n　二段落目。"
    assert result.removals[-1].reason == "partial_tail"
    assert kept(raw, result) == result.text


def test_scene_break_review_policy_keeps_text_and_marks_for_review() -> None:
    raw = "　雨がやんだ。\n***\n　翌朝、駅に立っていた。"
    cut = clean(raw, CleanPolicy())
    assert cut.text == "　雨がやんだ。"
    review = clean(raw, CleanPolicy(scene_break="review"))
    assert review.text == raw
    assert [r.reason for r in review.review] == ["scene_break"]
    assert raw[review.review[0].start:review.review[0].end] == "***"


def test_flags_markdown_and_fullwidth_breaks() -> None:
    result = clean_for("continue", "そこには写真が一枚。　　「見つけた」　　**大事な一文。**")
    assert set(result.flags) == {"markdown_bold", "fullwidth_space_break"}


def test_unknown_operation_has_no_policy() -> None:
    with pytest.raises(KeyError):
        clean_for("explore", "本文。")


# ---- PromptRenderer ------------------------------------------------------------

def _scene_inputs(scene: bench.Scene) -> dict[str, object]:
    c = scene.contract
    before, after = scene.passage.split("◆")
    return {
        "continue": ContinueInput(scene.text),
        "directed_continue": DirectedContinueInput(
            scene.text, BeatContract(c.objective, c.end_condition, c.target_chars, tuple(c.must_include), tuple(c.must_not)),
            tuple(scene.canon_facts)),
        "expand_insertion": ExpandInsertionInput(before, after),
    }


@pytest.mark.parametrize("scene", bench.load_scenes(), ids=lambda s: s.id)
def test_renderer_matches_phase0_benchmark_except_glm_directed(scene: bench.Scene) -> None:
    """Phase 0 で測った条件を本実装へ持ち込む。nai-r2 で変わるのは GLM-4.6 の Directed Continue だけ。"""
    inputs = _scene_inputs(scene)
    pairs = {"continue": "continue", "directed_continue": "directed_continue", "expand_insertion": "expand"}
    for model in ("glm-4-6", "xialong-v1"):
        for op, bench_op in pairs.items():
            url, body = bench.BUILDERS[bench_op](scene, model)
            rendered = render(op, inputs[op], model, sampling=NOVELAI_SAMPLING["stable"].values)  # type: ignore[arg-type]
            assert url.endswith("/oa/v1/" + ("completions" if op == "continue" else "chat/completions"))
            assert rendered.version == RENDERER_VERSION == "nai-r2"
            if (model, op) != ("glm-4-6", "directed_continue"):
                assert rendered.request.body() == body, (model, op)
                continue
            # 字数不足の比較実験の条件 B: 指示 600 字・max_tokens 738、ほかは同じ
            changed = rendered.request.body()
            assert changed["max_tokens"] == 738 and body["max_tokens"] == 492
            expected = body["messages"][1]["content"].replace("約400字", "約600字", 1)
            assert changed["messages"][1]["content"] == expected
            assert {k: v for k, v in changed.items() if k not in ("max_tokens", "messages")} ==                 {k: v for k, v in body.items() if k not in ("max_tokens", "messages")}


def _directed(model: str, multiplier: float | None = None, text: str = "本文。") -> object:
    data = DirectedContinueInput(text, BeatContract("目的", "終わり", 400), instruction_multiplier=multiplier)
    return render("directed_continue", data, model, sampling={})


def test_r2_keeps_contract_target_and_records_resolved_params() -> None:
    glm = _directed("glm-4-6")
    assert glm.params == {"target_chars": 400, "instruction_chars": 600, "instruction_multiplier": 1.5,  # type: ignore[attr-defined]
                          "multiplier_source": "model_default", "resolved_max_tokens": 738}
    xia = _directed("xialong-v1")
    assert xia.params["instruction_chars"] == 400 and xia.params["resolved_max_tokens"] == 492  # type: ignore[attr-defined]
    assert xia.params["multiplier_source"] == "model_default"  # type: ignore[attr-defined]


def test_explicit_multiplier_replaces_the_model_default_instead_of_stacking() -> None:
    for m, chars, tokens in ((1.0, 400, 492), (1.5, 600, 738), (2.0, 800, 984)):
        r = _directed("glm-4-6", m)
        assert (r.params["instruction_chars"], r.params["resolved_max_tokens"]) == (chars, tokens)  # type: ignore[attr-defined]
        assert r.params["multiplier_source"] == "explicit"  # type: ignore[attr-defined]


def test_raised_max_tokens_is_checked_against_context_limit() -> None:
    p = NovelAIProvider(TOKEN, transport=FakeTransport(), slot=threading.BoundedSemaphore(1))
    # 入力の推定（p10 1.087 字/トークン）＋ 738 が 36,864 を超える長さ。492 なら収まる
    text = "あ" * int((36864 - 600) * 1.087)
    with pytest.raises(ContextLimitError):
        p.check(_directed("glm-4-6", text=text).request)  # type: ignore[attr-defined]
    p.check(_directed("xialong-v1", text=text).request)  # type: ignore[attr-defined]


def test_renderer_rejects_mismatched_input_and_gap_mark() -> None:
    with pytest.raises(TypeError):
        render("continue", ExpandInsertionInput("前", "後"), "glm-4-6", sampling={})
    with pytest.raises(ValueError, match="扱わない"):
        render("expand_rewrite", ContinueInput("本文"), "glm-4-6", sampling={})
    with pytest.raises(ValueError, match="挿入位置"):
        render("expand_insertion", ExpandInsertionInput("前【ここに挿入】", "後"), "glm-4-6", sampling={})


# ---- Router --------------------------------------------------------------------

def test_router_defaults_to_glm_and_honors_explicit_model() -> None:
    router = OperationRouter(load_profiles())
    for op, endpoint in (("continue", "completions"), ("directed_continue", "chat"), ("expand_insertion", "chat")):
        route = router.resolve(op)
        assert (route.model, route.endpoint, route.reason) == ("glm-4-6", endpoint, "default")
        assert route.sampling.name == "stable" and route.sampling.verified
    explicit = router.resolve("directed_continue", model="xialong-v1", sampling="creative")
    assert (explicit.model, explicit.reason, explicit.sampling.verified) == ("xialong-v1", "explicit", False)


def test_router_never_falls_back_silently() -> None:
    profiles = load_profiles()
    router = OperationRouter(profiles)
    with pytest.raises(RouteError, match="切り替えない"):
        router.resolve("continue", model="llama-3-erato-v1")
    chat_only = {**profiles, "xialong-v1": profiles["xialong-v1"].model_copy(update={"endpoints": {"chat": "https://x/chat"}})}
    with pytest.raises(RouteError, match="切り替えない"):
        OperationRouter(chat_only).resolve("continue", model="xialong-v1")
    with pytest.raises(RouteError, match="扱わない"):
        router.resolve("expand_rewrite")
    no_default = {m: p.model_copy(update={"preferred_operations": []}) for m, p in profiles.items()}
    with pytest.raises(RouteError, match="既定モデルがない"):
        OperationRouter(no_default).resolve("continue")


# ---- Core Writer ---------------------------------------------------------------

def writer(transport: FakeTransport) -> CoreWriter:
    provider = NovelAIProvider(TOKEN, transport=transport, slot=threading.BoundedSemaphore(1), sleep=lambda _s: None)
    return CoreWriter(provider)


def test_plan_is_dry_run() -> None:
    t = FakeTransport()
    plan = writer(t).plan("continue", ContinueInput("　駅のホームには誰もいなかった。"))
    assert t.calls == []
    assert plan["model"] == "glm-4-6" and plan["route_reason"] == "default"
    assert plan["request"]["headers"]["Authorization"] == "Bearer ***"
    assert plan["request"]["body"]["prompt"] == "　駅のホームには誰もいなかった。"


def test_run_cleans_output_and_records_without_token() -> None:
    t = FakeTransport(sse("\n椅子に指をかけたまま", "動けない。", "\n***\n【解説】緊張を溜めた。"))
    out = writer(t).run("expand_insertion", ExpandInsertionInput("湊は箸を置いた。", "言うなら今しかない。"))
    assert out.generation.status == "complete"
    assert out.text == "椅子に指をかけたまま動けない。"
    record = out.record()
    assert record["raw_text"].startswith("\n椅子") and record["text"] == out.text
    assert {r["reason"] for r in record["removals"]} >= {"leading_space"}
    assert record["renderer_version"] == RENDERER_VERSION and record["profile_revision"] >= 1
    assert TOKEN not in json.dumps(record, ensure_ascii=False)
    body_part = t.calls[0]["body"]["messages"][1]["content"].split("本文:\n", 1)[1]
    assert body_part == "湊は箸を置いた。【ここに挿入】言うなら今しかない。"


def test_session_cancel_keeps_raw_partial_and_cleans_it() -> None:
    t = FakeTransport(FakeHandle(sse("　一つ目の文。", "二つ目の途中"), hold=True))
    w = writer(t)
    session = w.start("continue", ContinueInput("　駅のホーム。"))
    received = ""
    for chunk in session:
        received += chunk.text
        if "途中" in received:
            session.cancel()
            break
    out = session.finish()
    assert out.generation.status == "incomplete" and out.generation.cancelled
    assert out.generation.text == "　一つ目の文。二つ目の途中"
    assert out.text == "　一つ目の文。"
    assert t.active == 0


def test_explicit_xialong_goes_to_xialong_and_http_error_is_not_retried_elsewhere() -> None:
    t = FakeTransport(TransportError(500, "server error"))
    out = writer(t).run("directed_continue",
                        DirectedContinueInput("本文。", BeatContract("目的", "終わり", 400)), model="xialong-v1")
    assert out.generation.status == "error" and out.generation.http_status == 500
    assert out.route.model == "xialong-v1" and len(t.calls) == 1
    assert t.calls[0]["body"]["model"] == "xialong-v1"
    assert out.text == ""


def test_writer_cli_dry_run_does_not_load_token_or_send(capsys, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from ai_writer import novelai as nai
    from ai_writer import writer_cli

    def fail(*_a, **_k):  # type: ignore[no-untyped-def]
        raise AssertionError("dry-run でトークンを読んだ／送信した")

    monkeypatch.setattr(nai, "load_token", fail)
    monkeypatch.setattr("ai_writer.transport.UrllibTransport.open_stream", fail)
    assert writer_cli.main(["--scene", "sf"]) == 0
    out = capsys.readouterr().out
    assert "確認 3 件" in out and out.count("model=glm-4-6（default）") == 3 and "Bearer ***" in out
    assert writer_cli.main(["--scene", "sf", "--op", "directed_continue", "--model", "xialong-v1"]) == 0
    assert "model=xialong-v1（explicit）" in capsys.readouterr().out
