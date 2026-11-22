from __future__ import annotations

import json
import re

import pytest
import yaml

from test_metron import _calibration
from test_writing_bridge import _copy_ok
from test_writing_bridge_ops_speed import _pad_marked, _set_flags, _set_floor
from writing_bridge.commands import inspect, prepare, receive
from writing_bridge.errors import BridgeError
from writing_bridge.findings import SAVE_NEXT_ACTION
from writing_bridge.hashes import raw_sha256
from writing_bridge.models import ReportDocument, RequestKind, Selector, SelectorKind
from writing_bridge.publish import publish
from writing_bridge.repair import read_state, repair_begin, repair_next


def _ready(tmp_path, *, missing=False, thin=False, hints=(80, 60, 60), calibrated=True,
           finish_reason=None):
    work = _copy_ok(tmp_path)
    _set_flags(work, chronos="OFF")
    _set_floor(work, 300, hints)
    plan = work / "_metron/ch01-001/beats.yaml"
    data = yaml.safe_load(plan.read_text(encoding="utf-8"))
    if thin:
        data["beats"][0]["budget"]["paragraphs"] = [3, 4]
        plan.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    _pad_marked(work, 150)
    marked = work / "_metron/ch01-001/marked.md"
    if missing:
        text = marked.read_text(encoding="utf-8")
        text = re.sub(r"<!--beat:say_goodbye-->.*?<!--/beat:say_goodbye-->", "", text, flags=re.S)
        marked.write_text(text, encoding="utf-8")
    repo = tmp_path / "repo"
    (repo / "config").mkdir(parents=True)
    calibration = _calibration(calibrated=True, missing_span_ratio=0.0,
                               beat_thin_ratio=0.01, ending_rush_threshold=0.0)
    models = {"fixture-writer": calibration.model_dump(mode="json")} if calibrated else {}
    (repo / "config/metron_models.yaml").write_text(yaml.safe_dump({"models": models}), encoding="utf-8")
    prepare(work, scene_id="ch01-001", text_path="_novel_text/novel_text01.md",
            request_kind=RequestKind.NEW, model_id="fixture-writer", repo_root=repo,
            selector=Selector(kind=SelectorKind.HEADING, value="第一章　駅までの道"),
            links_path=None, allow_publish=True)
    receive(work, scene_id="ch01-001", run_id="run-0001", candidate=marked, request_id=None,
            finish_reason=finish_reason)
    return work, repo, work / "_work/writing/ch01-001/run-0001"


def _begin(work, repo, intent="auto"):
    return repair_begin(work, scene_id="ch01-001", run_id="run-0001", model="fixture-writer",
                        authorization="test", repo_root=repo, intent=intent)


def _publish(work, repo, *, dry_run=False):
    return publish(work, scene_id="ch01-001", run_id="run-0001", authorization="test",
                   repo_root=repo, dry_run=dry_run)


def test_under_floor_auto_not_needed_and_inspect_suggests_save(tmp_path):
    work, repo, run = _ready(tmp_path)
    code, message = inspect(work, scene_id="ch01-001", run_id="run-0001",
                            observations_path=None, marked_path=None, repo_root=repo)
    report = json.loads((run / "report.json").read_text(encoding="utf-8"))
    assert code == 0 and report["length_status"] == "refine_pending"
    assert report["next_action"] == SAVE_NEXT_ACTION
    assert "分量は清書待ち（場面 " in message
    assert "分量は清書待ち（場面 " in (run / "report.md").read_text(encoding="utf-8")
    with pytest.raises(BridgeError) as error:
        _begin(work, repo)
    assert error.value.code == "REPAIR_NOT_NEEDED"


def test_explicit_deepen_selects_extra_even_when_all_hints_met(tmp_path):
    work, repo, run = _ready(tmp_path, hints=(1, 1, 1))
    assert _begin(work, repo, "explicit_deepen")[0] == 0
    repair_next(work, scene_id="ch01-001", run_id="run-0001", repo_root=repo)
    state = read_state(run / "repair_state.json")
    assert state.session.scene_floor_deepen
    assert state.session.pending and state.session.pending.operation == "deepen"


def test_beat_thin_is_auto_repairable_but_does_not_block_publish(tmp_path):
    work, repo, run = _ready(tmp_path, thin=True)
    inspect(work, scene_id="ch01-001", run_id="run-0001", observations_path=None,
            marked_path=None, repo_root=repo)
    report = json.loads((run / "report.json").read_text(encoding="utf-8"))
    assert any(item["code"] == "BeatThin" and item["auto_repair"] for item in report["findings"])
    assert report["next_action"] == SAVE_NEXT_ACTION
    assert "自動修復: pending" in (run / "report.md").read_text(encoding="utf-8")
    assert _begin(work, repo)[0] == 0
    # A separate run without an active repair can publish the same advisory.
    work2, repo2, _ = _ready(tmp_path / "second", thin=True)
    assert _publish(work2, repo2)[0] == 0


@pytest.mark.parametrize("dry_run", [False, True])
def test_publish_rejects_missing_beat_before_writing(tmp_path, dry_run):
    work, repo, run = _ready(tmp_path, missing=True)
    target = work / "_novel_text/novel_text01.md"
    before = raw_sha256(target)
    with pytest.raises(BridgeError) as error:
        _publish(work, repo, dry_run=dry_run)
    assert any(code in str(error.value) for code in ("BeatMissing", "coverage", "span_order"))
    assert raw_sha256(target) == before
    if dry_run:
        assert not (run / "publish_state.json").exists()


def test_short_only_publishes_and_reports_refinement_pending(tmp_path):
    work, repo, run = _ready(tmp_path)
    code, message = _publish(work, repo)
    assert code == 0 and "分量は清書待ち" in message
    assert json.loads((run / "report.json").read_text(encoding="utf-8"))["length_status"] == "refine_pending"


def test_old_report_without_length_status_loads():
    report = ReportDocument.model_validate({"schema": 1, "request_id": "WRQ-0001", "run_id": "run-0001",
        "target_text_sha256": "sha256:" + "0" * 64, "text_save": "skipped", "metron": "skipped",
        "chronos_registered": "skipped", "text_state": "skipped"})
    assert report.length_status is None


@pytest.mark.parametrize("missing", [False, True])
def test_uncalibrated_publish_checks_mapping_and_reports_limit(tmp_path, missing):
    work, repo, run = _ready(tmp_path, calibrated=False, missing=missing)
    if missing:
        with pytest.raises(BridgeError) as error:
            _publish(work, repo, dry_run=True)
        assert "MODEL_UNCALIBRATED" in str(error.value)
        assert "coverage" in str(error.value) or "span_order" in str(error.value)
    else:
        code, message = _publish(work, repo, dry_run=True)
        assert code == 0 and "MODEL_UNCALIBRATED" in message
        code, message = _publish(work, repo)
        assert code == 0
        report = json.loads((run / "report.json").read_text(encoding="utf-8"))
        assert any(item["code"] == "MODEL_UNCALIBRATED" for item in report["findings"])


def test_status_block_skips_new_metron_publish_check(tmp_path, monkeypatch):
    import importlib
    from test_writing_bridge_status_block import _with_block, _publish_scene, _status_block_run

    work = _with_block(tmp_path)
    _publish_scene(work)
    module = importlib.import_module("writing_bridge.publish")
    def unexpected(*args, **kwargs):
        pytest.fail("status_block must bypass the METRON publish check")
    monkeypatch.setattr(module, "_check_metron_before_publish", unexpected)
    code, message = _status_block_run(work, "《記録》技能が第二段階に至った\n", "run-0002")
    assert code == 0 and "published status block" in message


def test_relay_reuses_saved_prompt_after_length_display_change(tmp_path):
    import novel_beat_draft as draft
    from test_novel_beat_draft import _work

    work = _work(tmp_path)
    out = work / "_work/writing/ch01-001/run-0001/beat_draft"
    with pytest.raises(draft.BeatDraftError) as waiting:
        draft.draft(work, "ch01-001", "run-0001", candidates=1, relay=True, log=lambda _: None)
    assert waiting.value.code == 3
    prompt = (out / "beat1.prompt.md").read_bytes()
    (out / "beat1.c1.md").write_text("　悠希は目を開けた。\n", encoding="utf-8")
    with pytest.raises(draft.BeatDraftError) as resumed:
        draft.draft(work, "ch01-001", "run-0001", candidates=1, relay=True, log=lambda _: None)
    assert resumed.value.code == 3 and "Beat 2/3" in str(resumed.value)
    assert (out / "beat1.prompt.md").read_bytes() == prompt


def test_auto_thin_does_not_repeat_deepen_just_to_reach_floor():
    from test_metron import _beat, _plan
    from metron.analyze import analyze_marked_text
    from metron.repair import marked_text_for_measurement
    from metron.repair_steps import RepairJob, begin_repair, next_job, submit_result

    plan = _plan(_beat("a", chars_hint=1, paragraphs=(2, None)), chars_floor=500)
    text = "　母は切符を確認した。"
    analyzed = analyze_marked_text(marked_text_for_measurement(plan, {"a": text}), plan, run=1)
    state = begin_repair(analyzed.metrics, plan, _calibration(missing_span_ratio=0.0),
                         clean_text=analyzed.clean_text, spans=analyzed.spans,
                         model="m", seam_enabled=False)
    job = next_job(state)
    assert isinstance(job, RepairJob) and job.operation == "deepen"
    submit_result(state, job_id=job.job_id, model="m",
                  candidate=text + "\n\n　兄は財布を鞄へしまった。", review="confirmed")
    assert not isinstance(next_job(state), RepairJob)


def test_chronos_publish_reuses_inspect_measurement(tmp_path, monkeypatch):
    from test_writing_bridge_publish import _ready as chrono_ready, ROOT, OBS, AUTH
    from writing_bridge import commands

    work = chrono_ready(tmp_path)
    calls = []
    original = commands.analyze_marked_text
    def analyze(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)
    monkeypatch.setattr(commands, "analyze_marked_text", analyze)
    code, _ = publish(work, scene_id="ch01-001", run_id="run-0001", authorization=AUTH,
                      repo_root=ROOT, observations_path=OBS)
    assert code == 0 and len(calls) == 1


@pytest.mark.parametrize("calibrated", [False, True])
def test_truncated_draft_is_required_with_or_without_calibration(tmp_path, calibrated):
    """打ち切りは finish_reason だけで決まる。校正されていないモデルでも保存を案内せず、正本へ書かない。"""
    work, repo, run = _ready(tmp_path, calibrated=calibrated, finish_reason="length")
    inspect(work, scene_id="ch01-001", run_id="run-0001", observations_path=None,
            marked_path=None, repo_root=repo)
    report = json.loads((run / "report.json").read_text(encoding="utf-8"))
    codes = [item["code"] for item in report["findings"]]
    assert codes.count("GenerationTruncated") == 1
    assert report["next_action"] is None
    target = work / "_novel_text/novel_text01.md"
    before = raw_sha256(target)
    for dry_run in (True, False):
        with pytest.raises(BridgeError) as error:
            _publish(work, repo, dry_run=dry_run)
        assert "GenerationTruncated" in str(error.value)
    assert raw_sha256(target) == before
    assert not (run / "publish_state.json").exists()


def test_required_refusal_keeps_the_run_retryable(tmp_path):
    """必須で止まった publish は publish_state.json を残さず、直した候補で同じ run から保存できる。"""
    work, repo, run = _ready(tmp_path)
    marked = work / "_metron/ch01-001/marked.md"
    fixed = marked.read_text(encoding="utf-8")
    broken = re.sub(r"<!--beat:say_goodbye-->.*?<!--/beat:say_goodbye-->", "", fixed, flags=re.S)
    broken_path = tmp_path / "broken.md"
    broken_path.write_text(broken, encoding="utf-8")
    receive(work, scene_id="ch01-001", run_id="run-0001", candidate=broken_path, request_id=None)
    with pytest.raises(BridgeError):
        _publish(work, repo)
    assert not (run / "publish_state.json").exists()
    fixed_path = tmp_path / "fixed.md"
    fixed_path.write_text(fixed, encoding="utf-8")
    receive(work, scene_id="ch01-001", run_id="run-0001", candidate=fixed_path, request_id=None)
    code, _ = _publish(work, repo)
    assert code == 0
    assert (run / "publish_state.json").is_file()


def test_broken_calibration_config_stops_publish_with_bridge_error(tmp_path):
    work, repo, run = _ready(tmp_path)
    (repo / "config/metron_models.yaml").write_text("models: [", encoding="utf-8")
    with pytest.raises(BridgeError) as error:
        _publish(work, repo, dry_run=True)
    assert error.value.code == "CONFIG_ERROR"


@pytest.mark.parametrize("enabled", [True, False])
def test_explicit_deepen_job_context_carries_expression_mix_only_when_on(tmp_path, monkeypatch, enabled):
    """計画 §11.2: ミックス ON の作品だけ、深化で足す文の種類を Deepen のジョブへ渡す。重み表は渡さない。"""
    from types import SimpleNamespace
    import novel_expression_mix as mix

    work, repo, run = _ready(tmp_path)
    (work / "_meta.md").write_text("# meta\n\n## 3.8 表現ミックス\n\n- **状態**: ON\n", encoding="utf-8")
    monkeypatch.setattr(mix, "mix_is_enabled", lambda text: enabled)
    monkeypatch.setattr(mix, "resolve_mix", lambda work_root, root=None: SimpleNamespace(
        enabled=enabled, interiority_capped=True,
        bands={"sound": "high", "metaphor": "high", "daily": "low", "action": "mid"}))
    monkeypatch.setattr(mix, "load_catalog", lambda root: (None, {
        "sound": {"label": "現場音"}, "metaphor": {"label": "比喩"},
        "daily": {"label": "生活行動"}, "action": {"label": "動作"}}))
    _begin(work, repo, intent="explicit_deepen")
    context = read_state(run / "repair_state.json").session.context
    if enabled:
        section = context.split("表現ミックス（作品の _meta.md。状態 ON）:", 1)[1]
        assert "先に足す: 現場音" in section and "比喩" not in section.split("足さない")[0].split("先に足す: ")[1]
        assert "足さない: 生活行動" in section and "独白を足さない" in section
        assert "weights" not in section and "0." not in section
    else:
        assert "表現ミックス（作品の _meta.md" not in context


def test_bridge_repairs_start_with_dialogue_cap_and_deepen_guidance(tmp_path):
    """執筆接続で新しく始めた修復は会話の上限の印を持ち、明示の Deepen の文脈には全体の深化の注意が入る。"""
    work, repo, run = _ready(tmp_path)
    _begin(work, repo, intent="explicit_deepen")
    session = read_state(run / "repair_state.json").session
    assert session.dialogue_cap is True
    assert "全体の深化の注意" in session.context and "欠如の実況" in session.context


def test_old_repair_state_without_dialogue_cap_loads_with_the_cap_off():
    from metron.repair_steps import RepairSession
    assert RepairSession.model_fields["dialogue_cap"].default is False


def test_deepen_start_caps_the_work_target_even_when_missing_beats_come_first():
    """欠落 Beat を先に埋める（blocked=False）ときも止めずに記録し、作業目標は +15% に抑える。"""
    from test_metron import _beat, _plan
    from metron.models import LengthTarget
    from writing_bridge.repair import _deepen_start

    plan = _plan(_beat("a", chars_hint=10), chars_floor=50)
    target, notes = _deepen_start(LengthTarget(target_chars=1000), plan, 100, blocked=False)
    assert target.target_chars == 115
    assert any(note.startswith("DESIGN_DENSITY") for note in notes)
    assert any(note.startswith("LENGTH_TARGET_CAPPED") for note in notes)
