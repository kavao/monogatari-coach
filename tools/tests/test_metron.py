from __future__ import annotations

from datetime import date
from pathlib import Path
import subprocess
import sys

import pytest
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from metron.analyze import analyze_marked_text
from metron.calibrate import CalibrationSample, ModelCalibration, calibrate_samples
from metron.classify import (
    CalibrationNotReady,
    classify_metrics,
    plan_generation_calls,
    resolve_granularity,
)
from metron.markers import embed_beat_markers, fact_marker, parse_markers
from metron.models import (
    Beat,
    BeatBudget,
    BeatPlan,
    SceneContract,
    SceneDefinition,
)
from metron.prompt import build_beat_prompt, to_prompt_budget
from metron.regression import build_regression_observation
from metron.repair import (
    build_beat_continuation_context,
    original_retention_ratio,
    repair_scene,
    run_marked_seam_correction,
    run_expand_loop,
    run_seam_correction,
    strip_generation_markers,
    write_final,
)
from metron.report import render_report
from metron.storage import atomic_write_model


def _beat(
    beat_id: str,
    *,
    type: str = "action",
    chars_hint: int = 10,
    paragraphs: tuple[int, int | None] = (1, None),
    dialogue_turns: tuple[int, int | None] = (0, None),
    weight: str = "normal",
    isolated: bool = False,
) -> Beat:
    return Beat(
        id=beat_id,
        type=type,  # type: ignore[arg-type]
        intent="検証用の意図",
        weight=weight,  # type: ignore[arg-type]
        isolated=isolated,
        budget=BeatBudget(
            paragraphs=paragraphs,
            dialogue_turns=dialogue_turns,
            sensory=0,
            interiority=0,
            new_facts=0,
            chars_hint=chars_hint,
        ),
    )


def _plan(*beats: Beat) -> BeatPlan:
    return BeatPlan(beats=list(beats))


def _calibration(**overrides: object) -> ModelCalibration:
    values: dict[str, object] = {
        "calibrated": True,
        "calibrated_at": date(2026, 8, 31),
        "reliable_span_chars": 30,
        "missing_span_ratio": 0.2,
        "beat_thin_ratio": 0.3,
        "ending_rush_threshold": 0.5,
        "too_short_ratio": 0.2,
        "expand_retention_threshold": 0.8,
        "samples": 10,
    }
    values.update(overrides)
    return ModelCalibration.model_validate(values)


def test_models_marker_offsets_prompt_boundary() -> None:
    plan = _plan(*[_beat(f"b{i}") for i in range(1, 5)])
    text = embed_beat_markers(
        [("b1", "e\u0301。" + fact_marker("f1")), ("b2", "二文。"), ("b3", "三文。"), ("b4", "終文。")]
    )
    result = parse_markers(text, expected_beats=[beat.id for beat in plan.beats])
    assert result.coverage
    assert "<!--beat:" not in result.clean_text
    assert "<!--fact:" not in result.clean_text
    assert result.clean_text.count("é") == 1
    assert result.fact_annotations["b1"] == ("f1",)
    assert result.spans[0].end > result.spans[0].start

    prompt = build_beat_prompt(plan.beats[0], previous_context="直前の文。")
    assert "chars_hint" not in prompt
    assert "10" not in prompt
    assert not hasattr(to_prompt_budget(plan.beats[0].budget), "chars_hint")


def test_marker_errors_and_head_tail_rule() -> None:
    malformed = parse_markers(
        "<!--beat:b1-->本文<!--beat:b2-->入れ子<!--/beat:b1-->",
        expected_beats=["b1", "b2"],
    )
    assert not malformed.coverage
    assert malformed.errors

    three = _plan(*[_beat(f"b{i}") for i in range(1, 4)])
    analyzed = analyze_marked_text(
        embed_beat_markers([(beat.id, "本文。") for beat in three.beats]),
        three,
        run=1,
    )
    assert analyzed.metrics.metrics.scene.head_tail_ratio is None


def test_analysis_report_and_classification() -> None:
    plan = _plan(
        _beat("b1", paragraphs=(2, None), chars_hint=10),
        _beat("b2", chars_hint=10),
        _beat("b3", chars_hint=10),
        _beat("b4", chars_hint=10),
    )
    analyzed = analyze_marked_text(
        embed_beat_markers(
            [("b1", "短い。"), ("b2", "普通の本文です。"), ("b3", "普通の本文です。"), ("b4", "終わり。")]
        ),
        plan,
        run=3,
    )
    report = render_report(analyzed.metrics, plan)
    assert "METRON V0 レポート" in report
    assert "b1" in report
    result = classify_metrics(
        analyzed.metrics,
        plan,
        _calibration(beat_thin_ratio=0.01),
        spans=analyzed.spans,
    )
    assert any(item.failure.value == "BeatThin" for item in result.findings)
    assert not any(item.failure.value == "TooShort" for item in result.findings)


def test_truncation_and_too_short_are_non_repair_findings() -> None:
    plan = _plan(*[_beat(f"b{i}", chars_hint=100) for i in range(1, 5)])
    analyzed = analyze_marked_text(
        embed_beat_markers([(beat.id, "十分な本文です。") for beat in plan.beats]),
        plan,
        run=1,
        finish_reason="max_tokens",
    )
    truncated = classify_metrics(
        analyzed.metrics,
        plan,
        _calibration(missing_span_ratio=0.0),
        spans=analyzed.spans,
    )
    assert {item.failure.value for item in truncated.findings} == {"GenerationTruncated"}

    complete = analyze_marked_text(
        embed_beat_markers([(beat.id, "短文。") for beat in plan.beats]),
        plan,
        run=2,
    )
    short = classify_metrics(
        complete.metrics,
        plan,
        _calibration(missing_span_ratio=0.0, beat_thin_ratio=0.0, too_short_ratio=0.5),
        spans=complete.spans,
    )
    assert any(item.failure.value == "TooShort" and not item.auto_repair for item in short.findings)


def test_calibration_granularity_and_independent_calls() -> None:
    samples = [
        CalibrationSample(model="m", chars_hint=400, observed_chars=400, span_ratios=[1.0], budget_ratios=[1.0], scene_ratio=1.0),
        CalibrationSample(model="m", chars_hint=800, observed_chars=600, span_ratios=[0.35], budget_ratios=[0.8], scene_ratio=0.75),
        CalibrationSample(model="m", chars_hint=1200, observed_chars=700, span_ratios=[0.3], budget_ratios=[0.5], scene_ratio=0.58),
    ]
    calibration = calibrate_samples(samples, model_id="m")
    assert calibration.calibrated
    assert calibration.missing_span_ratio != calibration.beat_thin_ratio
    plan = BeatPlan(
        generation={"granularity": "auto"},
        beats=[
            _beat("b1", chars_hint=20),
            _beat("b2", chars_hint=20, weight="heavy"),
            _beat("b3", chars_hint=20),
            _beat("b4", chars_hint=20, type="hook"),
        ],
    )
    assert resolve_granularity(plan, _calibration(reliable_span_chars=30)) == "beat"
    effective, calls = plan_generation_calls(plan, _calibration(reliable_span_chars=1000))
    assert effective == "scene"
    assert [call.beat_ids for call in calls] == [["b1"], ["b2"], ["b3"], ["b4"]]
    assert calls[1].isolated and not calls[2].isolated and calls[3].isolated


def test_repair_retention_loop_seam_and_marker_free_final() -> None:
    beat = _beat("b1")
    assert original_retention_ratio("一文。", "一文。追加。") == 1.0
    attempts = iter(["別文。", "一文。追加。"])
    repaired = run_expand_loop(
        beat,
        "一文。",
        lambda _prompt: next(attempts),
        retention_threshold=0.8,
    )
    assert repaired.accepted and repaired.attempts == 2

    marked = run_expand_loop(
        beat,
        "一文。",
        lambda _prompt: "<!--beat:b1-->一文。追加。<!--/beat:b1-->",
        retention_threshold=0.8,
    )
    assert marked.accepted and "<!--beat:" not in marked.final_text

    escalated = run_expand_loop(
        beat,
        "一文。",
        lambda _prompt: "別文。",
        retention_threshold=0.8,
    )
    assert escalated.escalated and escalated.final_text == "一文。"
    assert "三文目。" in build_beat_continuation_context("一文目。\n二文目。\n三文目。", 2)

    corrected, accepted, _ = run_seam_correction("一文。", lambda _prompt: "一文。追加。")
    assert accepted and corrected == "一文。追加。"
    assert "<!--beat:b1-->" not in strip_generation_markers("<!--beat:b1-->本文<!--/beat:b1-->")


def test_repair_scene_applies_expand_and_seam_once() -> None:
    plan = _plan(
        _beat("b1", paragraphs=(2, None)),
        _beat("b2"),
        _beat("b3"),
        _beat("b4"),
    )
    analyzed = analyze_marked_text(
        embed_beat_markers([(beat.id, "本文。") for beat in plan.beats]),
        plan,
        run=4,
    )
    calls: list[str] = []

    def expand(prompt: str) -> str:
        calls.append(prompt)
        return "本文。補足。"

    repaired = repair_scene(
        analyzed.metrics,
        plan,
        _calibration(beat_thin_ratio=0.01),
        clean_text=analyzed.clean_text,
        spans=analyzed.spans,
        expander=expand,
        seam_corrector=lambda prompt: prompt.split("結合稿:\n", 1)[1] + "補正。",
    )
    assert repaired.expansions["b1"].accepted
    assert repaired.seam_correction_applied
    assert len(calls) == 1
    assert "<!--beat:" not in repaired.final_text


def test_ending_rush_skips_final_expand_and_remeasures_after_seam(tmp_path: Path) -> None:
    plan = _plan(*[_beat(f"b{i}") for i in range(1, 4)], _beat("b4", type="hook"))
    long_text = "一二三四五六七八九十。"
    analyzed = analyze_marked_text(
        embed_beat_markers(
            [("b1", long_text), ("b2", long_text), ("b3", long_text), ("b4", "終わる。")]
        ),
        plan,
        run=5,
    )
    calibration = _calibration(
        missing_span_ratio=0.2,
        beat_thin_ratio=0.5,
        ending_rush_threshold=0.8,
    )
    expand_calls: list[str] = []

    def must_not_expand(prompt: str) -> str:
        expand_calls.append(prompt)
        return "失敗。"

    def regenerate(prompt: str) -> str:
        assert "Beat b4" in prompt
        return "末尾を再生成した。"

    repaired = repair_scene(
        analyzed.metrics,
        plan,
        calibration,
        clean_text=analyzed.clean_text,
        spans=analyzed.spans,
        expander=must_not_expand,
        regenerator=regenerate,
        seam_corrector=lambda prompt: prompt.split("結合稿:\n", 1)[1],
    )
    assert not expand_calls
    assert repaired.regenerated_beats == ("b4",)
    assert "b4" not in repaired.expansions
    assert repaired.verification_metrics.metrics.run == 6
    assert repaired.verification_metrics.metrics.scene.chars > analyzed.metrics.metrics.scene.chars

    final_path = tmp_path / "FINAL.md"
    write_final(final_path, "<!--beat:b1-->本文。<!--/beat:b1-->")
    assert "<!--beat:" not in final_path.read_text(encoding="utf-8")
    with pytest.raises(FileExistsError):
        write_final(final_path, "上書き禁止。")


def test_marked_seam_rejects_new_repeated_opening() -> None:
    plan = _plan(_beat("b1"), _beat("b2"))
    beat_texts = {"b1": "状況を説明する。", "b2": "別の行動を始める。"}

    def duplicate_opening(prompt: str) -> str:
        return prompt.split("結合稿:\n", 1)[1].replace(
            "別の行動を始める。", "状況を説明する。"
        )

    result = run_marked_seam_correction(plan, beat_texts, duplicate_opening)
    assert not result.accepted
    assert "repeated Beat opening" in result.reason


def test_unapproved_calibration_is_blocked() -> None:
    with pytest.raises(CalibrationNotReady):
        resolve_granularity(_plan(_beat("b1")), ModelCalibration())


def test_cli_analyze_report_and_classify(tmp_path: Path) -> None:
    contract = SceneContract(scene=SceneDefinition(id="ch03-002", pov="alice"))
    plan = _plan(*[_beat(f"b{i}") for i in range(1, 5)])
    calibration = _calibration()
    contract_path = tmp_path / "contract.yaml"
    beats_path = tmp_path / "beats.yaml"
    config_path = tmp_path / "metron_models.yaml"
    draft_path = tmp_path / "marked.md"
    atomic_write_model(contract_path, contract)
    atomic_write_model(beats_path, plan)
    class Config(BaseModel):
        models: dict[str, dict[str, object]]

    atomic_write_model(
        config_path,
        Config(models={"m": calibration.model_dump(mode="json")}),
    )
    draft_path.write_text(
        embed_beat_markers([(beat.id, "本文です。") for beat in plan.beats]),
        encoding="utf-8",
    )
    output_dir = tmp_path / contract.scene.id
    command = [
        sys.executable,
        str(ROOT / "tools" / "metron_cli.py"),
        "analyze",
        "--contract",
        str(contract_path),
        "--beats",
        str(beats_path),
        "--draft",
        str(draft_path),
        "--output-dir",
        str(output_dir),
        "--run",
        "1",
        "--model",
        "m",
    ]
    analyzed = subprocess.run(command, capture_output=True, text=True)
    assert analyzed.returncode == 0, analyzed.stderr
    assert (output_dir / "metrics.001.yaml").exists()
    report = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "metron_cli.py"),
            "report",
            "--metrics",
            str(output_dir / "metrics.001.yaml"),
            "--beats",
            str(beats_path),
        ],
        capture_output=True,
        text=True,
    )
    assert report.returncode == 0 and "METRON V0" in report.stdout
    classified = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "metron_cli.py"),
            "classify",
            "--metrics",
            str(output_dir / "metrics.001.yaml"),
            "--beats",
            str(beats_path),
            "--spans",
            str(output_dir / "spans.001.yaml"),
            "--config",
            str(config_path),
            "--model",
            "m",
        ],
        capture_output=True,
        text=True,
    )
    assert classified.returncode == 0, classified.stderr

    blocked = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "metron_cli.py"),
            "classify",
            "--metrics",
            str(output_dir / "metrics.001.yaml"),
            "--beats",
            str(beats_path),
            "--config",
            str(ROOT / "config" / "metron_models.yaml"),
            "--model",
            "<model-id>",
        ],
        capture_output=True,
        text=True,
    )
    assert blocked.returncode == 2
    assert "not approved" in blocked.stderr
