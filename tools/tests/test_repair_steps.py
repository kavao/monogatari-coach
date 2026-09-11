from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_metron import _beat, _plan, _calibration
from test_writing_bridge import _copy_ok, _run_cli, ROOT
from metron.analyze import analyze_marked_text
from metron.classify import classify_metrics
from metron.markers import embed_beat_markers
from metron.repair_steps import begin_repair, next_job, submit_result, RepairJob, RepairSession, digest
from metron.repair import repair_scene
from writing_bridge.commands import prepare, receive, inspect
from writing_bridge.models import ArtifactRefsDocument, RequestKind
from writing_bridge.repair import repair_begin, repair_next, repair_submit, read_state
from writing_bridge.errors import BridgeError
from writing_bridge.hashes import raw_sha256, read_normalized, text_sha256
from writing_bridge.storage import load_json_model, write_model


def _session():
    plan = _plan(_beat("b1", chars_hint=30), chars_floor=30)
    analyzed = analyze_marked_text(embed_beat_markers([("b1", "出発した。")]), plan, run=1)
    calibration = _calibration(missing_span_ratio=0.0, beat_thin_ratio=0.01)
    return begin_repair(analyzed.metrics, plan, calibration, clean_text=analyzed.clean_text,
                        spans=analyzed.spans, model="fixture-writer", context="人物状態: 屋外")


def test_steps_resume_pending_empty_failure_and_limits():
    state = _session()
    job = next_job(state)
    assert job.operation == "deepen" and job.attempt == 1
    assert "人物状態" in job.prompt and job.prompt_hash == digest(job.prompt)
    state = RepairSession.model_validate_json(state.model_dump_json())
    assert next_job(state) == job
    submit_result(state, job_id=job.job_id, model=state.model, error="lost job")
    submit_result(state, job_id=job.job_id, model=state.model, error="lost job")
    assert len(state.history) == 1
    with pytest.raises(ValueError, match="different result"):
        submit_result(state, job_id=job.job_id, model=state.model, candidate="different")
    second = next_job(state)
    assert second.attempt == 2
    submit_result(state, job_id=second.job_id, model=state.model, candidate="", review="confirmed")
    seam = next_job(state)
    assert seam.operation == "seam"
    submit_result(state, job_id=seam.job_id, model=state.model, error="failed")
    result = next_job(state)
    assert not isinstance(result, RepairJob)
    assert result.final_text.strip() == "出発した。"
    assert len(state.history) == 3
    assert result.escalated_beats == ("b1",)


@pytest.mark.parametrize("candidate,review,reason", [
    ("出発した。", "confirmed", "identical"),
    ("短。", "confirmed", "length"),
    ("まったく違う文を書き直して元の文章を失った。", "confirmed", "retention"),
    ("出発した。追加。", "unverified", "meaning review"),
    ("出発した。視点を変えた。", "rejected", "meaning review"),
    ("<!--beat:wrong-->出発した。追加。<!--/beat:wrong-->", "confirmed", "markers"),
])
def test_candidate_rejection_keeps_working_text(candidate, review, reason):
    state = _session()
    job = next_job(state)
    before = dict(state.working_texts)
    submit_result(state, job_id=job.job_id, model=state.model, candidate=candidate, review=review)
    assert reason in state.history[0].rejection
    next_job(state)
    assert state.working_texts == before


def test_steps_same_results_as_sync_wrapper():
    state = _session()
    calls = []
    def generate(job):
        calls.append(job.operation)
        return ("出発した。" + "風が吹く。" * 8 if job.operation == "deepen"
                else job.prompt.split("結合稿:\n", 1)[1])
    while isinstance(job := next_job(state), RepairJob):
        submit_result(state, job_id=job.job_id, model=state.model,
                      candidate=generate(job), review="confirmed")
    sync_calls = []
    def deepen(prompt):
        sync_calls.append("deepen")
        return "出発した。" + "風が吹く。" * 8
    def seam(prompt):
        sync_calls.append("seam")
        return prompt.split("結合稿:\n", 1)[1]
    sync = repair_scene(state.metrics, state.beat_plan, state.calibration,
        clean_text=state.clean_text, spans=state.spans, expander=deepen, seam_corrector=seam)
    assert job == sync
    assert calls == sync_calls == ["deepen", "seam"]


def _bridge(tmp_path, *, calibrated=True):
    work = _copy_ok(tmp_path)
    repo = tmp_path / "repo"
    (repo / "config").mkdir(parents=True)
    calibration = _calibration(calibrated=calibrated, missing_span_ratio=0.0,
                               beat_thin_ratio=0.01, ending_rush_threshold=0.0)
    (repo / "config" / "metron_models.yaml").write_text(yaml.safe_dump(
        {"models": {"fixture-writer": calibration.model_dump(mode="json")}}), encoding="utf-8")
    beats = work / "_metron/ch01-001/beats.yaml"
    data = yaml.safe_load(beats.read_text(encoding="utf-8"))
    data["generation"]["chars_floor"] = 500
    for beat in data["beats"]:
        beat["budget"]["chars_hint"] = 200
    beats.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    prepare(work, scene_id="ch01-001", text_path="_novel_text/novel_text01.md",
            request_kind=RequestKind.NEW, model_id="fixture-writer",
            selector=None, links_path=None, repo_root=repo)
    receive(work, scene_id="ch01-001", run_id="run-0001",
            candidate=work / "_metron/ch01-001/marked.md", request_id=None)
    return work, repo, work / "_writing/ch01-001/run-0001"


def _begin(work, repo):
    return repair_begin(work, scene_id="ch01-001", run_id="run-0001",
                        model="fixture-writer", authorization="test-only fixture repair", repo_root=repo)


def _next(work, repo):
    return repair_next(work, scene_id="ch01-001", run_id="run-0001", repo_root=repo)


def _submit(work, repo, job, candidate=None, error=None, model="fixture-writer", review="confirmed"):
    return repair_submit(work, scene_id="ch01-001", run_id="run-0001", job_id=job.job_id,
                         model=model, candidate=candidate, error=error, review=review, repo_root=repo)


def test_bridge_roundtrip_remeasures_and_marks_c1_stale(tmp_path):
    work, repo, run = _bridge(tmp_path)
    original = (work / "_novel_text/novel_text01.md").read_bytes()
    _begin(work, repo)
    _next(work, repo)
    first = read_state(run / "repair_state.json").session.pending
    _next(work, repo)
    assert read_state(run / "repair_state.json").session.pending == first
    assert first.prompt_hash == digest(first.prompt)
    assert "expected_checks" in first.prompt and "場面契約" in first.prompt
    for _ in range(12):
        state = read_state(run / "repair_state.json")
        if state.status == "completed":
            break
        job = state.session.pending
        assert "expected_checks" in job.prompt
        candidate = tmp_path / "response.md"
        body = (state.session.working_texts[job.beat_id] + "風を感じた。" * 40
                if job.operation == "deepen" else job.prompt.split("結合稿:\n", 1)[1])
        candidate.write_text(body, encoding="utf-8")
        _submit(work, repo, job, candidate=candidate)
    else:
        pytest.fail("repair did not terminate within its attempt limits")
    state = read_state(run / "repair_state.json")
    assert state.status == "completed"
    report = json.loads((run / "report.json").read_text(encoding="utf-8"))
    assert report["text_state"] != "success"  # Fresh C1 evidence is required.
    assert report["repair_history"]
    assert all(item["review"] == "confirmed" for item in report["repair_history"])
    assert (work / "_novel_text/novel_text01.md").read_bytes() == original
    output = (work / state.output_path).read_text(encoding="utf-8")
    assert output.startswith("# 第一章")
    assert list((work / "_metron/ch01-001").glob("metrics.*.yaml"))
    body = read_normalized(work / state.output_path)
    context = json.loads((run / "context.json").read_text(encoding="utf-8"))
    items = []
    for expected in context["expected_checks"]:
        quote = "旅行用の上着" if expected["dimension"] == "outfit" else "駅の券売機の前に立った"
        start = body.index(quote)
        item = {key: expected[key] for key in ("event_id", "actor_id", "dimension", "state_at")}
        item.update(value=expected["expected_value"], quote=quote, start=start, end=start + len(quote),
                    range_sha256=digest(quote), recorder="agent", confirmation="match")
        items.append(item)
    evidence = tmp_path / "fresh.json"
    evidence.write_text(json.dumps(dict(schema=1, request_id="WRQ-0001",
        text_sha256=text_sha256(body), expected_total=len(items), items=items), ensure_ascii=False), encoding="utf-8")
    inspect(work, scene_id="ch01-001", run_id="run-0001", observations_path=evidence,
            marked_path=None, repo_root=repo)
    final = json.loads((run / "report.json").read_text(encoding="utf-8"))
    assert final["text_state"] == "success"
    assert final["target_text_sha256"] == text_sha256(body)


@pytest.mark.parametrize("target", ["characters", "links", "beats", "calibration", "candidate", "base"])
def test_bridge_rejects_changed_repair_inputs(tmp_path, target):
    work, repo, run = _bridge(tmp_path)
    _begin(work, repo)
    _next(work, repo)
    state = read_state(run / "repair_state.json")
    paths = {"characters": work / "chronos/entities/characters.yaml",
             "links": run / "links.yaml", "beats": work / "_metron/ch01-001/beats.yaml",
             "calibration": repo / "config/metron_models.yaml",
             "candidate": work / state.source_path, "base": work / "_novel_text/novel_text01.md"}
    path = paths[target]
    path.write_text(path.read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8")
    with pytest.raises(BridgeError, match="changed|hash|match|inputs"):
        _next(work, repo)
    assert len(read_state(run / "repair_state.json").session.history) == 0


def test_model_provenance_and_unapproved_model(tmp_path):
    work, repo, run = _bridge(tmp_path, calibrated=False)
    with pytest.raises(BridgeError) as error:
        _begin(work, repo)
    assert error.value.code == "MODEL_UNCALIBRATED"
    assert not (run / "repair_state.json").exists()


def test_bridge_double_submit_and_wrong_model(tmp_path):
    work, repo, run = _bridge(tmp_path)
    _begin(work, repo)
    _next(work, repo)
    job = read_state(run / "repair_state.json").session.pending
    with pytest.raises(BridgeError, match="model"):
        _submit(work, repo, job, error="lost", model="other-model")
    _submit(work, repo, job, error="lost")
    _submit(work, repo, job, error="lost")
    assert len(read_state(run / "repair_state.json").session.history) == 1
    with pytest.raises(BridgeError, match="different result"):
        _submit(work, repo, job, error="different")


def test_cli_process_handoff(tmp_path):
    work, repo, run = _bridge(tmp_path)
    common = [str(work), "--scene-id", "ch01-001", "--run-id", "run-0001", "--repo-root", str(repo)]
    begun = _run_cli("repair-begin", *common, "--model", "fixture-writer",
                     "--authorization", "test fixture only")
    assert begun.returncode == 0, begun.stderr
    first = _run_cli("repair-next", *common)
    assert first.returncode == 0, first.stderr
    job = read_state(run / "repair_state.json").session.pending
    response = _run_cli("repair-submit", *common, "--job-id", job.job_id,
                        "--model", "fixture-writer", "--error", "explicit failure")
    assert response.returncode == 0, response.stderr
    assert len(read_state(run / "repair_state.json").session.history) == 1
    resumed = _run_cli("repair-next", *common)
    assert resumed.returncode == 0, resumed.stderr
    assert read_state(run / "repair_state.json").session.pending.attempt == 2


def test_fresh_observation_detects_state_change_after_repair(tmp_path):
    work, repo, run = _bridge(tmp_path)
    _begin(work, repo)
    _next(work, repo)
    state = read_state(run / "repair_state.json")
    job = state.session.pending
    quote = "彼は上着を脱ぎ、部屋着に戻った。"
    candidate = tmp_path / "changed.md"
    candidate.write_text(state.session.working_texts[job.beat_id] + quote, encoding="utf-8")
    _submit(work, repo, job, candidate=candidate)
    state = read_state(run / "repair_state.json")
    body = read_normalized(work / state.output_path)
    context = json.loads((run / "context.json").read_text(encoding="utf-8"))
    expected = next(item for item in context["expected_checks"] if item["dimension"] == "outfit")
    start = body.index(quote)
    item = {key: expected[key] for key in ("event_id", "actor_id", "dimension", "state_at")}
    item.update(value="home", quote=quote, start=start, end=start + len(quote),
                range_sha256=digest(quote), recorder="agent", confirmation="match")
    observations = tmp_path / "observations.json"
    observations.write_text(json.dumps(dict(schema=1, request_id="WRQ-0001",
        text_sha256=text_sha256(body), expected_total=len(context["expected_checks"]),
        items=[item]), ensure_ascii=False), encoding="utf-8")
    inspect(work, scene_id="ch01-001", run_id="run-0001", observations_path=observations,
            marked_path=None, repo_root=repo)
    report = json.loads((run / "report.json").read_text(encoding="utf-8"))
    assert report["text_state"] == "failed"
    assert any(item["code"] == "TEXT_STATE_MISMATCH" for item in report["findings"])


def test_replay_after_failure_between_confirmation_and_receive(tmp_path, monkeypatch):
    import writing_bridge.repair as bridge
    work, repo, run = _bridge(tmp_path)
    _begin(work, repo)
    _next(work, repo)
    state = read_state(run / "repair_state.json")
    job = state.session.pending
    candidate = tmp_path / "expanded.md"
    candidate.write_text(state.session.working_texts[job.beat_id] + "足音が響く。" * 20, encoding="utf-8")
    original_receive = bridge.commands.receive
    def interrupted(*args, **kwargs):
        raise OSError("simulated crash")
    monkeypatch.setattr(bridge.commands, "receive", interrupted)
    with pytest.raises(OSError, match="simulated crash"):
        _submit(work, repo, job, candidate=candidate)
    assert len(read_state(run / "repair_state.json").session.history) == 1
    monkeypatch.setattr(bridge.commands, "receive", original_receive)
    _next(work, repo)
    assert len(read_state(run / "repair_state.json").session.history) == 1
    assert (run / "report.json").is_file()


def test_scene_lock_rejects_other_process(tmp_path):
    from writing_bridge.locking import scene_lock
    work, repo, run = _bridge(tmp_path)
    _begin(work, repo)
    with scene_lock(work, "ch01-001"):
        result = _run_cli("repair-next", str(work), "--scene-id", "ch01-001",
                          "--run-id", "run-0001", "--repo-root", str(repo))
    assert result.returncode == 2
    assert "JOB_CONFLICT" in result.stderr
    assert read_state(run / "repair_state.json").session.pending is None


def test_truncated_never_generates():
    state = _session()
    state.metrics.metrics.finish_reason = "length"
    result = next_job(state)
    assert not isinstance(result, RepairJob)
    assert not state.history


def test_truncated_missing_beat_does_not_regenerate():
    plan = _plan(_beat("b1", chars_hint=1), _beat("b2", chars_hint=1), chars_floor=1)
    analyzed = analyze_marked_text(
        embed_beat_markers([("b1", "出発した。")]),
        plan,
        run=1,
        finish_reason="length",
    )
    classified = classify_metrics(
        analyzed.metrics,
        plan,
        _calibration(missing_span_ratio=0.0, beat_thin_ratio=0.01),
        spans=analyzed.spans,
    )
    assert any(item.failure.value == "GenerationTruncated" for item in classified.findings)
    missing = [item for item in classified.findings if item.failure.value == "BeatMissing"]
    assert missing
    assert all(not item.auto_repair for item in missing)
    state = begin_repair(
        analyzed.metrics,
        plan,
        _calibration(missing_span_ratio=0.0, beat_thin_ratio=0.01),
        clean_text=analyzed.clean_text,
        spans=analyzed.spans,
        model="fixture-writer",
    )
    result = next_job(state)
    assert not isinstance(result, RepairJob)
    assert "b2" in result.escalated_beats


def test_regeneration_is_once_and_failed_output_keeps_original():
    state = _session()
    state.calibration.missing_span_ratio = 0.9
    job = next_job(state)
    assert job.operation == "regenerate"
    submit_result(state, job_id=job.job_id, model=state.model, error="provider failed")
    operations = [job.operation]
    while isinstance(job := next_job(state), RepairJob):
        operations.append(job.operation)
        submit_result(state, job_id=job.job_id, model=state.model, error="provider failed")
    assert operations.count("regenerate") == 1
    assert job.final_text.strip() == "出発した。"


def test_steps_reject_long_paraphrase():
    state = _session()
    original = "彼は窓辺に腰を下ろし、遠くの山並みに沈む夕日を静かに眺めていた。"
    plan = state.beat_plan
    analyzed = analyze_marked_text(embed_beat_markers([("b1", original)]), plan, run=1)
    state = begin_repair(analyzed.metrics, plan, state.calibration, clean_text=analyzed.clean_text,
                         spans=analyzed.spans, model=state.model)
    state.beat_plan.generation.chars_floor = 200
    job = next_job(state)
    submit_result(state, job_id=job.job_id, model=state.model,
                  candidate=original + original.replace("静かに", "ゆっくり"), review="confirmed")
    assert "paraphrases" in state.history[0].rejection


def test_issued_prompt_tampering_is_not_silently_replaced(tmp_path):
    work, repo, run = _bridge(tmp_path)
    _begin(work, repo)
    _next(work, repo)
    prompt = run / "jobs/JOB-0001.prompt.md"
    prompt.write_text("different instructions", encoding="utf-8")
    with pytest.raises(BridgeError, match="modified"):
        _next(work, repo)
    assert prompt.read_text(encoding="utf-8") == "different instructions"


@pytest.mark.parametrize("candidate", ["<!--/beat:b1-->出発した。追加。", "<!--beat:broken 出発した。追加。"])
def test_malformed_markers_are_rejected(candidate):
    state = _session()
    job = next_job(state)
    submit_result(state, job_id=job.job_id, model=state.model, candidate=candidate, review="confirmed")
    assert "markers" in state.history[0].rejection


def test_steps_seam_rejects_prose_moved_outside():
    plan = _plan(_beat("b1", chars_hint=1), chars_floor=1)
    analyzed = analyze_marked_text(embed_beat_markers([("b1", "出発した。")]), plan, run=1)
    state = begin_repair(
        analyzed.metrics,
        plan,
        _calibration(missing_span_ratio=0.0, beat_thin_ratio=0.01),
        clean_text=analyzed.clean_text,
        spans=analyzed.spans,
        model="fixture-writer",
    )
    job = next_job(state)
    assert job.operation == "seam"
    submit_result(
        state,
        job_id=job.job_id,
        model=state.model,
        candidate="<!--beat:b1--><!--/beat:b1-->出発した。追加。",
        review="confirmed",
    )
    assert state.history[0].rejection
    result = next_job(state)
    assert not isinstance(result, RepairJob)
    assert result.final_text.strip() == "出発した。"


def _patch_metrics_finish_reason(work: Path, run: Path, *, finish_reason: str, chars=None):
    refs = load_json_model(run / "artifact_refs.json", ArtifactRefsDocument)
    assert refs.metron is not None
    metrics_path = work / refs.metron["metrics"].path
    data = yaml.safe_load(metrics_path.read_text(encoding="utf-8"))
    data["metrics"]["finish_reason"] = finish_reason
    if chars is not None:
        data["metrics"]["scene"]["chars"] = chars
        for beat in data["metrics"]["beats"]:
            beat["chars"] = chars
    metrics_path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    refs.metron["metrics"].raw_sha256 = raw_sha256(metrics_path)
    write_model(run / "artifact_refs.json", refs, json_format=True)


def test_repair_begin_keeps_truncated_finish_reason(tmp_path):
    work, repo, run = _bridge(tmp_path)
    inspect(
        work,
        scene_id="ch01-001",
        run_id="run-0001",
        observations_path=None,
        marked_path=None,
        repo_root=repo,
    )
    _patch_metrics_finish_reason(work, run, finish_reason="length")
    _begin(work, repo)
    _next(work, repo)
    state = read_state(run / "repair_state.json")
    assert state.session.metrics.metrics.finish_reason == "length"
    assert state.session.pending is None
    assert all(item.job.operation != "deepen" for item in state.session.history)


def test_equal_length_other_candidate_does_not_inherit_truncation(tmp_path):
    work, repo, run = _bridge(tmp_path)
    original = work / "_metron/ch01-001/marked.md"
    receive(
        work,
        scene_id="ch01-001",
        run_id="run-0001",
        candidate=original,
        request_id=None,
        finish_reason="length",
    )
    inspect(
        work,
        scene_id="ch01-001",
        run_id="run-0001",
        observations_path=None,
        marked_path=None,
        repo_root=repo,
    )
    other = tmp_path / "same_len.md"
    other.write_text(
        original.read_text(encoding="utf-8").replace("旅行用の上着", "通学用の上着"),
        encoding="utf-8",
    )
    receive(work, scene_id="ch01-001", run_id="run-0001", candidate=other, request_id=None)
    (run / "observations.json").unlink(missing_ok=True)
    inspect(
        work,
        scene_id="ch01-001",
        run_id="run-0001",
        observations_path=None,
        marked_path=None,
        repo_root=repo,
    )
    refs = load_json_model(run / "artifact_refs.json", ArtifactRefsDocument)
    metrics = yaml.safe_load((work / refs.metron["metrics"].path).read_text(encoding="utf-8"))
    assert metrics["metrics"].get("finish_reason") in {None, "null"}
    _begin(work, repo)
    _next(work, repo)
    state = read_state(run / "repair_state.json")
    assert state.session.metrics.metrics.finish_reason is None
    assert state.session.pending is not None
    assert state.session.pending.operation == "deepen"


def test_submit_result_rejects_candidate_with_error():
    state = _session()
    job = next_job(state)
    with pytest.raises(ValueError, match="either candidate or explicit error"):
        submit_result(
            state,
            job_id=job.job_id,
            model=state.model,
            candidate="出発した。追加。",
            error="failed",
            review="confirmed",
        )


def test_active_repair_rejects_old_candidate_after_output(tmp_path):
    work, repo, run = _bridge(tmp_path)
    _begin(work, repo)
    _next(work, repo)
    state = read_state(run / "repair_state.json")
    job = state.session.pending
    candidate = tmp_path / "expanded.md"
    candidate.write_text(
        state.session.working_texts[job.beat_id] + "足音が響く。" * 20,
        encoding="utf-8",
    )
    _submit(work, repo, job, candidate=candidate)
    receive(
        work,
        scene_id="ch01-001",
        run_id="run-0001",
        candidate=work / "_metron/ch01-001/marked.md",
        request_id=None,
    )
    with pytest.raises(BridgeError) as caught:
        _next(work, repo)
    assert caught.value.code == "STALE_EVIDENCE"


def test_receive_finish_reason_blocks_deepen(tmp_path):
    work, repo, run = _bridge(tmp_path)
    receive(
        work,
        scene_id="ch01-001",
        run_id="run-0001",
        candidate=work / "_metron/ch01-001/marked.md",
        request_id=None,
        finish_reason="length",
    )
    refs = load_json_model(run / "artifact_refs.json", ArtifactRefsDocument)
    assert refs.generation is not None
    assert refs.generation.finish_reason == "length"
    _begin(work, repo)
    _next(work, repo)
    state = read_state(run / "repair_state.json")
    assert state.session.metrics.metrics.finish_reason == "length"
    assert state.session.pending is None


def test_seam_reordering_keeps_previous_texts():
    plan = _plan(_beat("b1", chars_hint=1), _beat("b2", chars_hint=1))
    analyzed = analyze_marked_text(embed_beat_markers([("b1", "出発した。"), ("b2", "到着した。")]), plan, run=1)
    state = begin_repair(analyzed.metrics, plan, _calibration(missing_span_ratio=0.0, beat_thin_ratio=0.01),
                         clean_text=analyzed.clean_text, spans=analyzed.spans, model="fixture-writer")
    job = next_job(state)
    assert job.operation == "seam"
    original = dict(state.working_texts)
    submit_result(state, job_id=job.job_id, model=state.model, review="confirmed",
                  candidate=embed_beat_markers([("b2", "到着した。"), ("b1", "出発した。")]))
    assert "reordered" in state.history[0].rejection
    result = next_job(state)
    assert result.beat_texts == original


def test_repair_active_submit_defers_unverified_c1(tmp_path):
    work, repo, run = _bridge(tmp_path)
    _begin(work, repo)
    _next(work, repo)
    job = read_state(run / "repair_state.json").session.pending
    code, message = _submit(work, repo, job, error="lost")
    assert code == 0, message
    report = json.loads((run / "report.json").read_text(encoding="utf-8"))
    assert any(item.get("code") == "TEXT_STATE_UNVERIFIED" for item in report["findings"])
    assert read_state(run / "repair_state.json").status == "active"


def test_repair_completed_without_observations_exits_one(tmp_path):
    work, repo, run = _bridge(tmp_path)
    _begin(work, repo)
    _next(work, repo)
    last_code = None
    for _ in range(12):
        state = read_state(run / "repair_state.json")
        if state.status in {"completed", "escalated"}:
            break
        job = state.session.pending
        last_code, message = _submit(work, repo, job, error="lost")
        assert "TEXT_STATE_UNVERIFIED" in (run / "report.json").read_text(encoding="utf-8")
        del message
    else:
        pytest.fail("repair did not terminate within its attempt limits")
    assert last_code == 1
    code, _ = inspect(
        work,
        scene_id="ch01-001",
        run_id="run-0001",
        observations_path=None,
        marked_path=None,
        repo_root=repo,
    )
    assert code == 1


def test_terminal_repair_rejects_new_hash_and_keeps_state(tmp_path):
    work, repo, run = _bridge(tmp_path)
    _begin(work, repo)
    _next(work, repo)
    for _ in range(16):
        state = read_state(run / "repair_state.json")
        if state.status == "completed":
            break
        job = state.session.pending
        candidate = tmp_path / "response.md"
        body = (
            state.session.working_texts[job.beat_id] + "風を感じた。" * 40
            if job.operation == "deepen"
            else job.prompt.split("結合稿:\n", 1)[1]
        )
        candidate.write_text(body, encoding="utf-8")
        _submit(work, repo, job, candidate=candidate)
    else:
        pytest.fail("repair did not terminate")
    before = (run / "repair_state.json").read_text(encoding="utf-8")
    state = read_state(run / "repair_state.json")
    assert state.status == "completed"
    other = tmp_path / "new-draft.md"
    other.write_text("まったく別の新候補である。\n", encoding="utf-8")
    with pytest.raises(BridgeError) as caught:
        receive(
            work,
            scene_id="ch01-001",
            run_id="run-0001",
            candidate=other,
            request_id=None,
        )
    assert caught.value.code == "JOB_CONFLICT"
    assert "terminal" in str(caught.value)
    assert (run / "repair_state.json").read_text(encoding="utf-8") == before


def test_escalated_scene_floor_does_not_issue_jobs(tmp_path):
    work = _copy_ok(tmp_path)
    repo = tmp_path / "repo"
    (repo / "config").mkdir(parents=True)
    calibration = _calibration(
        calibrated=True,
        missing_span_ratio=0.0,
        beat_thin_ratio=0.01,
        ending_rush_threshold=0.0,
    )
    (repo / "config" / "metron_models.yaml").write_text(
        yaml.safe_dump({"models": {"fixture-writer": calibration.model_dump(mode="json")}}),
        encoding="utf-8",
    )
    beats = work / "_metron/ch01-001/beats.yaml"
    data = yaml.safe_load(beats.read_text(encoding="utf-8"))
    data["generation"]["chars_floor"] = 500
    for beat in data["beats"]:
        beat["expandable"] = False
        beat["budget"]["chars_hint"] = 1
    beats.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    prepare(
        work,
        scene_id="ch01-001",
        text_path="_novel_text/novel_text01.md",
        request_kind=RequestKind.NEW,
        model_id="fixture-writer",
        selector=None,
        links_path=None,
        repo_root=repo,
    )
    receive(
        work,
        scene_id="ch01-001",
        run_id="run-0001",
        candidate=work / "_metron/ch01-001/marked.md",
        request_id=None,
    )
    run = work / "_writing/ch01-001/run-0001"
    _begin(work, repo)
    code, message = _next(work, repo)
    state = read_state(run / "repair_state.json")
    assert state.status == "escalated"
    assert state.session.pending is None
    assert any(item.startswith("SCENE_FLOOR_NO_ELIGIBLE") for item in state.notes)
    jobs_dir = run / "jobs"
    jobs = list(jobs_dir.glob("JOB-*.json")) if jobs_dir.is_dir() else []
    assert jobs == []
    _next(work, repo)
    again = list(jobs_dir.glob("JOB-*.json")) if jobs_dir.is_dir() else []
    assert again == []
    assert "escalated" in message
    other = tmp_path / "another.md"
    other.write_text("新run向けの別稿。\n", encoding="utf-8")
    with pytest.raises(BridgeError) as caught:
        receive(work, scene_id="ch01-001", run_id="run-0001", candidate=other, request_id=None)
    assert caught.value.code == "JOB_CONFLICT"
