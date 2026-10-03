from __future__ import annotations

import os
from hashlib import sha256
from pathlib import Path
import subprocess
import sys

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from chronos.extraction import (
    approve_candidate,
    diff_candidate,
    link_source,
    list_pending_candidates,
    reject_candidate,
    stage_candidates,
)
from chronos.models import (
    Character,
    CharacterFile,
    CharacterStateConfig,
    ChronosConfig,
    Event,
    EventSource,
    ExtractGate,
    Location,
    LocationFile,
    PerChapterCount,
    Scene,
    SceneFile,
    DimensionSpec,
    DimensionType,
    Severity,
)
from chronos.scaffold import init_chronos
from chronos.storage import atomic_write_model, load_yaml
from chronos.store import ChronosLoadError, load_store, write_config, write_event_file


CLI = TOOLS / "chronos_cli.py"


def _new_work(tmp_path: Path, manuscript: str | None = None) -> Path:
    novel = tmp_path / "novel"
    chronos = init_chronos(novel)
    (novel / "chronos" / "entities").mkdir(exist_ok=True)
    atomic_write_model(
        chronos / "entities" / "characters.yaml",
        CharacterFile(characters=[Character(id="CHR-akane", name="青葉茜")]),
    )
    atomic_write_model(
        chronos / "entities" / "locations.yaml",
        LocationFile(locations=[Location(id="LOC-kitchen", name="台所")]),
    )
    atomic_write_model(
        chronos / "scenes.yaml",
        SceneFile(scenes=[Scene(id="ch01-001", chapter=1, order=1)]),
    )
    atomic_write_model(
        chronos / "chronos.config.yaml",
        ChronosConfig(
            extract_gate=ExtractGate(
                profile="night-step",
                unit="一夜に閉じた出来事",
                include=["decision", "state_change"],
                exclude="反復",
                per_chapter=PerChapterCount(min=2, max=4),
            )
        ),
    )
    if manuscript is not None:
        text_path = novel / "_novel_text" / "novel_text01.md"
        text_path.parent.mkdir(parents=True)
        text_path.write_text(manuscript, encoding="utf-8")
    return novel


def _proposal(tmp_path: Path, *, quote: str, title: str = "内定を日付にする", **extra: object) -> Path:
    payload = {
        "schema": 1,
        "scene_id": "ch01-001",
        "source_file": "_novel_text/novel_text01.md",
        "candidates": [
            {
                "title": title,
                "type": "decision",
                "actors": ["CHR-akane"],
                "location": "LOC-kitchen",
                "source_quote": quote,
                **extra,
            }
        ],
    }
    path = tmp_path / "proposals.yaml"
    path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
    )


def test_extract_stage_approve_rebases_span_and_keeps_pending_out_of_events(tmp_path: Path) -> None:
    quote = "茜は内定通知の日付を確かめた。"
    novel = _new_work(tmp_path, f"<!-- scene: ch01-001 -->\n{quote}\n")
    proposal = _proposal(tmp_path, quote=quote)
    original_text = (novel / "_novel_text" / "novel_text01.md").read_text(encoding="utf-8")

    _, message = stage_candidates(novel, proposal)
    assert "staged 1 candidate" in message
    assert "WARNING CHR022: chapter 1 projects 1" in message
    store = load_store(novel)
    assert store.events == []
    candidate_cache = chronos_cache = store.root / ".cache" / "extract" / "ch01-001.yaml"
    candidate = load_yaml(candidate_cache)["candidates"][0]
    assert candidate["source"]["span"][0] == original_text.index(quote)
    old_file_digest = candidate["source_file_digest"]

    text_path = novel / "_novel_text" / "novel_text01.md"
    text_path.write_text("<!-- scene: ch01-001 -->\n章頭を追記した。\n" + original_text.split("\n", 1)[1], encoding="utf-8")
    _, message = approve_candidate(novel, "CEX-0001")
    assert "approved CEX-0001" in message
    approved = load_store(novel).events[0]
    assert approved.source is not None and approved.source.span is not None
    assert approved.source.span[0] == text_path.read_text(encoding="utf-8").index(quote)
    assert load_yaml(candidate_cache)["candidates"][0]["source_file_digest"] != old_file_digest
    assert "章頭を追記した。" in text_path.read_text(encoding="utf-8")


def test_check_does_not_require_or_read_manuscript_and_reports_gate_counts(tmp_path: Path) -> None:
    novel = _new_work(tmp_path)
    write_event_file(
        novel / "chronos" / "events" / "ch01.yaml",
        [
            Event(
                id="EVT-0001",
                title="必須欄が不足した手入力イベント",
                type="decision",
                actors=["CHR-akane"],
                origin="authored",
                source=EventSource(scene="ch01-001"),
            )
        ],
    )
    result = _run_cli("check", str(novel))
    assert result.returncode == 0, result.stderr
    assert "0 effective events, 1 excluded events, 0 confirmed order edges" in result.stdout
    assert "CHR020 warning" in result.stdout

    config = load_store(novel).config
    config.rules["CHR020"] = Severity.OFF
    write_config(novel / "chronos" / "chronos.config.yaml", config)
    suppressed = _run_cli("check", str(novel))
    assert suppressed.returncode == 0
    assert "CHR020" not in suppressed.stdout
    assert "1 excluded events" in suppressed.stdout


def test_unknown_actor_name_is_kept_out_of_actors(tmp_path: Path) -> None:
    quote = "茜は内定通知の日付を確かめた。"
    novel = _new_work(tmp_path, f"<!-- scene: ch01-001 -->\n{quote}\n")
    proposal = _proposal(tmp_path, quote=quote, actors=["CHR-unknown"])
    with pytest.raises(ValueError, match="unregistered actor IDs"):
        stage_candidates(novel, proposal)


def test_unresolved_actor_mention_stays_separate_and_blocks_approval(tmp_path: Path) -> None:
    quote = "茜は内定通知の日付を確かめた。"
    novel = _new_work(tmp_path, f"<!-- scene: ch01-001 -->\n{quote}\n")
    proposal = _proposal(tmp_path, quote=quote, unresolved_actor_mentions=["事務所の同僚"])
    stage_candidates(novel, proposal)
    candidate = load_yaml(novel / "chronos" / ".cache" / "extract" / "ch01-001.yaml")["candidates"][0]
    assert candidate["proposal"]["actors"] == ["CHR-akane"]
    assert candidate["proposal"]["unresolved_actor_mentions"] == ["事務所の同僚"]
    with pytest.raises(ValueError, match="unresolved actor mentions remain"):
        approve_candidate(novel, "CEX-0001")


def test_ambiguous_source_requires_explicit_link_source(tmp_path: Path) -> None:
    quote = "茜は弁当箱を閉じた。"
    novel = _new_work(tmp_path, f"<!-- scene: ch01-001 -->\n{quote}\n{quote}\n")
    stage_candidates(novel, _proposal(tmp_path, quote=quote))
    cache_path = novel / "chronos" / ".cache" / "extract" / "ch01-001.yaml"
    staged = load_yaml(cache_path)["candidates"][0]
    assert staged["source_match_count"] == 2
    assert staged["source"].get("span") is None
    with pytest.raises(ValueError, match="source interval is not unique"):
        approve_candidate(novel, "CEX-0001")

    text = (novel / "_novel_text" / "novel_text01.md").read_text(encoding="utf-8")
    target_start = text.rindex(quote)
    link_source(novel, "CEX-0001", start=target_start, end=target_start + len(quote))
    approve_candidate(novel, "CEX-0001")
    event = load_store(novel).events[0]
    assert event.source is not None and event.source.span == (target_start, target_start + len(quote))


def test_update_requires_diff_confirmation_and_preserves_locked_fields(tmp_path: Path) -> None:
    quote = "茜は内定通知の日付を確かめた。"
    novel = _new_work(tmp_path, f"<!-- scene: ch01-001 -->\n{quote}\n")
    first = _proposal(tmp_path, quote=quote)
    stage_candidates(novel, first)
    approve_candidate(novel, "CEX-0001", lock_fields=("title",))

    update = _proposal(tmp_path, quote=quote, title="採用日を確認する")
    stage_candidates(novel, update)
    cache_path = novel / "chronos" / ".cache" / "extract" / "ch01-001.yaml"
    staged = load_yaml(cache_path)["candidates"][0]
    assert staged["candidate_id"] == "CEX-0001"
    assert staged["kind"] == "update"
    _, diff = diff_candidate(novel, "CEX-0001")
    assert "UNAPPLIED (locked)" in diff
    with pytest.raises(ValueError, match="--confirm-update"):
        approve_candidate(novel, "CEX-0001")
    approve_candidate(novel, "CEX-0001", confirm_update=True)
    updated = load_store(novel).events[0]
    assert updated.id == "EVT-0001"
    assert updated.title == "内定を日付にする"
    assert updated.locked_fields == ["title"]

    (novel / "chronos" / ".cache" / "extract" / "ch01-001.yaml").unlink()
    new_quote = "茜は新しい日付を手帳に記した。"
    text_path = novel / "_novel_text" / "novel_text01.md"
    text_path.write_text(text_path.read_text(encoding="utf-8") + new_quote + "\n", encoding="utf-8")
    stage_candidates(novel, _proposal(tmp_path, quote=new_quote, title="日付を手帳に写す"))
    staged = load_yaml(novel / "chronos" / ".cache" / "extract" / "ch01-001.yaml")["candidates"][0]
    assert staged["candidate_id"] == "CEX-0002"


def test_same_title_different_source_intervals_remain_distinct(tmp_path: Path) -> None:
    first_quote = "茜は採用通知を封筒へ戻した。"
    second_quote = "健は卵を五つ並べた。"
    novel = _new_work(tmp_path, f"<!-- scene: ch01-001 -->\n{first_quote}\n{second_quote}\n")
    proposal = tmp_path / "two-same-title.yaml"
    proposal.write_text(
        yaml.safe_dump(
            {
                "schema": 1,
                "scene_id": "ch01-001",
                "source_file": "_novel_text/novel_text01.md",
                "candidates": [
                    {"title": "同じ題名", "type": "decision", "actors": ["CHR-akane"], "location": "LOC-kitchen", "source_quote": first_quote},
                    {"title": "同じ題名", "type": "decision", "actors": ["CHR-akane"], "location": "LOC-kitchen", "source_quote": second_quote},
                ],
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    stage_candidates(novel, proposal)
    candidates = load_yaml(novel / "chronos" / ".cache" / "extract" / "ch01-001.yaml")["candidates"]
    assert [item["candidate_id"] for item in candidates] == ["CEX-0001", "CEX-0002"]


def test_pending_list_is_scene_ordered_and_excludes_rejected_candidates(tmp_path: Path) -> None:
    first_quote = "茜は採用通知を封筒へ戻した。"
    second_quote = "健は卵を五つ並べた。"
    novel = _new_work(tmp_path, f"<!-- scene: ch01-001 -->\n{first_quote}\n{second_quote}\n")
    proposal = tmp_path / "two-pending.yaml"
    proposal.write_text(
        yaml.safe_dump(
            {
                "schema": 1,
                "scene_id": "ch01-001",
                "source_file": "_novel_text/novel_text01.md",
                "candidates": [
                    {"title": "先の場面", "type": "decision", "actors": ["CHR-akane"], "location": "LOC-kitchen", "source_quote": first_quote},
                    {"title": "後の場面", "type": "state_change", "actors": ["CHR-akane"], "location": "LOC-kitchen", "source_quote": second_quote},
                ],
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    stage_candidates(novel, proposal)
    reject_candidate(novel, "CEX-0002")
    _, output = list_pending_candidates(novel)
    assert output.startswith("pending candidates: 1")
    assert "CEX-0001" in output and "先の場面" in output
    assert "CEX-0002" not in output and "後の場面" not in output


def test_authored_event_at_same_source_interval_is_not_reextracted(tmp_path: Path) -> None:
    quote = "茜は採用通知を封筒へ戻した。"
    novel = _new_work(tmp_path, f"<!-- scene: ch01-001 -->\n{quote}\n")
    source_start = (novel / "_novel_text" / "novel_text01.md").read_text(encoding="utf-8").index(quote)
    chronos = novel / "chronos"
    write_event_file(
        chronos / "events" / "ch01.yaml",
        [
            Event(
                id="EVT-0001",
                title="作者が既に登録した出来事",
                type="decision",
                actors=["CHR-akane"],
                location="LOC-kitchen",
                origin="authored",
                source=EventSource(
                    scene="ch01-001",
                    span=(source_start, source_start + len(quote)),
                    digest=sha256(quote.encode("utf-8")).hexdigest(),
                ),
            )
        ],
    )
    _, message = stage_candidates(novel, _proposal(tmp_path, quote=quote))
    assert "staged 0 candidate(s)" in message
    assert load_store(novel).events[0].title == "作者が既に登録した出来事"


def test_rejected_candidate_survives_cache_deletion_and_cex_is_not_reused(tmp_path: Path) -> None:
    quote = "茜は採用通知を封筒へ戻した。"
    novel = _new_work(tmp_path, f"<!-- scene: ch01-001 -->\n{quote}\n")
    stage_candidates(novel, _proposal(tmp_path, quote=quote))
    reject_candidate(novel, "CEX-0001")
    cache = novel / "chronos" / ".cache" / "extract" / "ch01-001.yaml"
    cache.unlink()
    _, message = stage_candidates(novel, _proposal(tmp_path, quote=quote))
    assert "staged 0 candidate(s)" in message

    new_quote = "健は卵を五つ並べた。"
    text_path = novel / "_novel_text" / "novel_text01.md"
    text_path.write_text(text_path.read_text(encoding="utf-8") + new_quote + "\n", encoding="utf-8")
    stage_candidates(novel, _proposal(tmp_path, quote=new_quote))
    new_candidate = load_yaml(cache)["candidates"][0]
    assert new_candidate["candidate_id"] == "CEX-0002"


def test_approved_update_is_listed_and_reapproval_state_survives_reextract(tmp_path: Path) -> None:
    quote = "茜は内定通知の日付を確かめた。"
    novel = _new_work(tmp_path, f"<!-- scene: ch01-001 -->\n{quote}\n")
    stage_candidates(novel, _proposal(tmp_path, quote=quote))
    approve_candidate(novel, "CEX-0001")

    update = _proposal(tmp_path, quote=quote, title="採用日を確認する")
    stage_candidates(novel, update)
    _, listing = list_pending_candidates(novel)
    assert listing.startswith("pending candidates: 1")
    assert "CEX-0001  [update]" in listing
    assert "採用日を確認する" in listing
    _, diff = diff_candidate(novel, "CEX-0001")
    assert "title:" in diff and "[proposed]" in diff

    approved = _run_cli("approve", str(novel), "CEX-0001", "--confirm-update")
    assert approved.returncode == 0, approved.stderr
    assert load_store(novel).events[0].title == "採用日を確認する"
    review = load_yaml(novel / "chronos" / "extract_reviews.yaml")["records"][0]
    assert review["review"] == "approved"
    assert review["update_review"] == "approved"

    _, message = stage_candidates(novel, update)
    assert "staged 0 candidate(s)" in message
    assert list_pending_candidates(novel)[1] == "pending candidates: 0"


def test_rejecting_update_keeps_approved_event_and_allows_a_new_update(tmp_path: Path) -> None:
    quote = "茜は内定通知の日付を確かめた。"
    novel = _new_work(tmp_path, f"<!-- scene: ch01-001 -->\n{quote}\n")
    stage_candidates(novel, _proposal(tmp_path, quote=quote))
    approve_candidate(novel, "CEX-0001")

    rejected_update = _proposal(tmp_path, quote=quote, title="却下する改題案")
    stage_candidates(novel, rejected_update)
    reject_candidate(novel, "CEX-0001")
    record = load_yaml(novel / "chronos" / "extract_reviews.yaml")["records"][0]
    assert record["review"] == "approved"
    assert record["event_id"] == "EVT-0001"
    assert record["update_review"] == "rejected"
    assert load_store(novel).events[0].title == "内定を日付にする"

    _, message = stage_candidates(novel, rejected_update)
    assert "staged 0 candidate(s)" in message
    assert list_pending_candidates(novel)[1] == "pending candidates: 0"

    newer_update = _proposal(tmp_path, quote=quote, title="採用日を確かめる")
    stage_candidates(novel, newer_update)
    assert list_pending_candidates(novel)[1].startswith("pending candidates: 1")
    assert "採用日を確かめる" in list_pending_candidates(novel)[1]


def test_ambiguous_quote_digest_and_linked_identity_survive_reextract(tmp_path: Path) -> None:
    quote = "茜は弁当箱を閉じた。"
    novel = _new_work(tmp_path, f"<!-- scene: ch01-001 -->\n{quote}\n{quote}\n")
    proposal = _proposal(tmp_path, quote=quote)
    stage_candidates(novel, proposal)
    cache = novel / "chronos" / ".cache" / "extract" / "ch01-001.yaml"
    candidate = load_yaml(cache)["candidates"][0]
    assert candidate["source"]["digest"] == sha256(quote.encode("utf-8")).hexdigest()
    assert candidate["source_match_count"] == 2

    stage_candidates(novel, proposal)
    assert len(load_yaml(cache)["candidates"]) == 1
    assert len(load_yaml(novel / "chronos" / "extract_reviews.yaml")["records"]) == 1
    assert list_pending_candidates(novel)[1].startswith("pending candidates: 1")

    text = (novel / "_novel_text" / "novel_text01.md").read_text(encoding="utf-8")
    target_start = text.rindex(quote)
    link_source(novel, "CEX-0001", start=target_start, end=target_start + len(quote))
    stage_candidates(novel, proposal)
    candidate = load_yaml(cache)["candidates"][0]
    assert candidate["candidate_id"] == "CEX-0001"
    assert candidate["source"]["span"] == [target_start, target_start + len(quote)]
    assert candidate["source_match_count"] == 1


def test_legacy_ambiguous_cache_restores_missing_review_digest(tmp_path: Path) -> None:
    quote = "茜は弁当箱を閉じた。"
    novel = _new_work(tmp_path, f"<!-- scene: ch01-001 -->\n{quote}\n{quote}\n")
    proposal = _proposal(tmp_path, quote=quote)
    stage_candidates(novel, proposal)
    cache_path = novel / "chronos" / ".cache" / "extract" / "ch01-001.yaml"
    old_cache = load_yaml(cache_path)
    old_cache["candidates"][0]["source"]["digest"] = None
    cache_path.write_text(yaml.safe_dump(old_cache, allow_unicode=True, sort_keys=False), encoding="utf-8")
    reviews_path = novel / "chronos" / "extract_reviews.yaml"
    old_reviews = load_yaml(reviews_path)
    old_reviews["records"][0]["source_digest"] = None
    reviews_path.write_text(yaml.safe_dump(old_reviews, allow_unicode=True, sort_keys=False), encoding="utf-8")

    stage_candidates(novel, proposal)
    refreshed = load_yaml(cache_path)["candidates"]
    review = load_yaml(reviews_path)["records"]
    assert len(refreshed) == 1 and refreshed[0]["candidate_id"] == "CEX-0001"
    assert refreshed[0]["source"]["digest"] == sha256(quote.encode("utf-8")).hexdigest()
    assert len(review) == 1 and review[0]["source_digest"] == refreshed[0]["source"]["digest"]


def test_partial_reextract_preserves_other_pending_cache_candidates(tmp_path: Path) -> None:
    first_quote = "茜は採用通知を封筒へ戻した。"
    second_quote = "健は卵を五つ並べた。"
    novel = _new_work(tmp_path, f"<!-- scene: ch01-001 -->\n{first_quote}\n{second_quote}\n")
    stage_candidates(novel, _proposal(tmp_path, quote=first_quote, title="先の候補"))
    stage_candidates(novel, _proposal(tmp_path, quote=second_quote, title="後の候補"))
    _, listing = list_pending_candidates(novel)
    assert listing.startswith("pending candidates: 2")
    assert "CEX-0001" in listing and "CEX-0002" in listing
    assert "candidate cache missing" not in listing


def test_cli_approve_lock_option_sets_author_selected_fields(tmp_path: Path) -> None:
    quote = "茜は内定通知の日付を確かめた。"
    novel = _new_work(tmp_path, f"<!-- scene: ch01-001 -->\n{quote}\n")
    proposal = _proposal(tmp_path, quote=quote)
    staged = _run_cli("extract", str(novel), str(proposal))
    assert staged.returncode == 0, staged.stderr
    approved = _run_cli("approve", str(novel), "CEX-0001", "--lock", "title,actors")
    assert approved.returncode == 0, approved.stderr
    assert load_store(novel).events[0].locked_fields == ["actors", "title"]


def test_old_cached_candidate_locks_are_ignored_in_favor_of_approve_options(tmp_path: Path) -> None:
    quote = "茜は内定通知の日付を確かめた。"
    novel = _new_work(tmp_path, f"<!-- scene: ch01-001 -->\n{quote}\n")
    stage_candidates(novel, _proposal(tmp_path, quote=quote))
    cache_path = novel / "chronos" / ".cache" / "extract" / "ch01-001.yaml"
    legacy_cache = load_yaml(cache_path)
    legacy_cache["candidates"][0]["proposal"]["locked_fields"] = ["title"]
    cache_path.write_text(yaml.safe_dump(legacy_cache, allow_unicode=True, sort_keys=False), encoding="utf-8")

    assert list_pending_candidates(novel)[1].startswith("pending candidates: 1")
    approve_candidate(novel, "CEX-0001")
    assert load_store(novel).events[0].locked_fields == []


def test_candidate_document_cannot_choose_locked_fields(tmp_path: Path) -> None:
    quote = "茜は内定通知の日付を確かめた。"
    novel = _new_work(tmp_path, f"<!-- scene: ch01-001 -->\n{quote}\n")
    with pytest.raises(ValueError, match="locked_fields"):
        stage_candidates(novel, _proposal(tmp_path, quote=quote, locked_fields=["title"]))


def test_approval_rejects_any_candidate_that_would_create_chr001_cycle(tmp_path: Path) -> None:
    quote = "茜は内定通知の日付を確かめた。"
    novel = _new_work(tmp_path, f"<!-- scene: ch01-001 -->\n{quote}\n")
    stage_candidates(novel, _proposal(tmp_path, quote=quote))
    approve_candidate(novel, "CEX-0001")

    cyclic = _proposal(tmp_path, quote=quote, time={"after": ["EVT-0001"]})
    stage_candidates(novel, cyclic)
    with pytest.raises(ValueError, match="CHR001 cycle"):
        approve_candidate(novel, "CEX-0001", confirm_update=True)
    assert load_store(novel).events[0].title == "内定を日付にする"


def test_approval_allows_candidate_unrelated_to_preexisting_chr001_cycle(tmp_path: Path) -> None:
    quote = "茜は内定通知の日付を確かめた。"
    novel = _new_work(tmp_path, f"<!-- scene: ch01-001 -->\n{quote}\n")
    write_event_file(
        novel / "chronos" / "events" / "ch01.yaml",
        [
            Event(
                id="EVT-0001",
                title="既存イベントA",
                type="decision",
                actors=["CHR-akane"],
                location="LOC-kitchen",
                source=EventSource(scene="ch01-001"),
                time={"after": ["EVT-0002"]},
            ),
            Event(
                id="EVT-0002",
                title="既存イベントB",
                type="decision",
                actors=["CHR-akane"],
                location="LOC-kitchen",
                source=EventSource(scene="ch01-001"),
                time={"after": ["EVT-0001"]},
            ),
        ],
    )

    stage_candidates(novel, _proposal(tmp_path, quote=quote, title="新しい独立イベント"))
    approve_candidate(novel, "CEX-0001")

    store = load_store(novel)
    assert {event.id for event in store.events} == {"EVT-0001", "EVT-0002", "EVT-0003"}


def test_approval_rejects_candidate_joining_preexisting_chr001_cycle(tmp_path: Path) -> None:
    quote = "茜は内定通知の日付を確かめた。"
    novel = _new_work(tmp_path, f"<!-- scene: ch01-001 -->\n{quote}\n")
    write_event_file(
        novel / "chronos" / "events" / "ch01.yaml",
        [
            Event(
                id="EVT-0001",
                title="既存イベントA",
                type="decision",
                actors=["CHR-akane"],
                location="LOC-kitchen",
                source=EventSource(scene="ch01-001"),
                time={"after": ["EVT-0002"]},
            ),
            Event(
                id="EVT-0002",
                title="既存イベントB",
                type="decision",
                actors=["CHR-akane"],
                location="LOC-kitchen",
                source=EventSource(scene="ch01-001"),
                time={"after": ["EVT-0001"]},
            ),
        ],
    )

    proposal = _proposal(
        tmp_path,
        quote=quote,
        title="既存の循環へ割り込む",
        time={"after": ["EVT-0001"], "before": ["EVT-0002"]},
    )
    stage_candidates(novel, proposal)
    with pytest.raises(ValueError, match="CHR001 cycle.*EVT-0003"):
        approve_candidate(novel, "CEX-0001")
    assert {event.id for event in load_store(novel).events} == {"EVT-0001", "EVT-0002"}


def test_reextracting_same_newly_approved_proposal_creates_no_update_candidate(tmp_path: Path) -> None:
    quote = "茜は内定通知の日付を確かめた。"
    novel = _new_work(tmp_path, f"<!-- scene: ch01-001 -->\n{quote}\n")
    proposal = _proposal(tmp_path, quote=quote)
    stage_candidates(novel, proposal)
    approve_candidate(novel, "CEX-0001")

    review = load_yaml(novel / "chronos" / "extract_reviews.yaml")["records"][0]
    assert review["update_review"] == "approved"
    assert review["update_digest"]
    _, message = stage_candidates(novel, proposal)
    assert "staged 0 candidate(s)" in message
    assert list_pending_candidates(novel)[1] == "pending candidates: 0"


def test_update_with_no_effective_event_field_changes_is_not_staged(tmp_path: Path) -> None:
    quote = "茜は内定通知の日付を確かめた。"
    novel = _new_work(tmp_path, f"<!-- scene: ch01-001 -->\n{quote}\n")
    stage_candidates(novel, _proposal(tmp_path, quote=quote))
    approve_candidate(novel, "CEX-0001")

    normalized_noop = _proposal(tmp_path, quote=quote, effects_on={})
    _, message = stage_candidates(novel, normalized_noop)
    assert "staged 0 candidate(s)" in message
    assert list_pending_candidates(novel)[1] == "pending candidates: 0"


def test_gate_unset_accepts_legacy_event_source_and_locks(tmp_path: Path) -> None:
    novel = _new_work(tmp_path)
    config = load_store(novel).config
    config.extract_gate = None
    atomic_write_model(novel / "chronos" / "chronos.config.yaml", config)
    legacy = Event(
        id="EVT-0001",
        title="既存の旧形式イベント",
        source=EventSource(span=(-2, -2), digest="legacy-digest"),
        locked_fields=["legacy_lock"],
    )
    write_event_file(novel / "chronos" / "events" / "ch01.yaml", [legacy])
    loaded = load_store(novel)
    assert loaded.events[0].source is not None
    assert loaded.events[0].source.digest == "legacy-digest"
    assert loaded.events[0].locked_fields == ["legacy_lock"]


def test_unplaced_candidate_cannot_be_approved(tmp_path: Path) -> None:
    quote = "茜は採用通知を封筒へ戻した。"
    novel = _new_work(tmp_path, f"# 第一章\n{quote}\n")
    proposal = _proposal(tmp_path, quote=quote)
    payload = yaml.safe_load(proposal.read_text(encoding="utf-8"))
    payload["scene_id"] = None
    proposal.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")
    stage_candidates(novel, proposal)
    with pytest.raises(ValueError, match="SCENE_ID_REQUIRED"):
        approve_candidate(novel, "CEX-0001")
    assert load_store(novel).events == []


def test_relation_state_approval_requires_comparable_prior_order(tmp_path: Path) -> None:
    quote = "茜は右肩の力を抜いた。"
    novel = _new_work(tmp_path, f"<!-- scene: ch01-001 -->\n{quote}\n")
    chronos = novel / "chronos"
    config = ChronosConfig(
        character_state=CharacterStateConfig(
            dimensions={"present": DimensionSpec(type=DimensionType.BOOL, default=False)}
        ),
        extract_gate=ExtractGate(
            profile="relation-state",
            unit="人物状態の変化",
            include=["state_change"],
            exclude="状態変化を伴わない反復",
            required_fields=["scene", "actors", "location", "title", "type", "effects_on"],
        ),
    )
    atomic_write_model(chronos / "chronos.config.yaml", config)
    write_event_file(
        chronos / "events" / "ch01.yaml",
        [
            Event(
                id="EVT-0001",
                title="先行状態",
                type="state_change",
                actors=["CHR-akane"],
                location="LOC-kitchen",
                origin="authored",
                source=EventSource(scene="ch01-001"),
                effects_on={"CHR-akane": {"present": True}},
            )
        ],
    )
    proposal = _proposal(
        tmp_path,
        quote=quote,
        title="肩の力が抜ける",
        type="state_change",
        effects_on={"CHR-akane": {"present": False}},
    )
    stage_candidates(novel, proposal)
    with pytest.raises(ValueError, match="incomparable for CHR-akane"):
        approve_candidate(novel, "CEX-0001")

    payload = yaml.safe_load(proposal.read_text(encoding="utf-8"))
    payload["candidates"][0]["time"] = {"after": ["EVT-0001"]}
    proposal.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")
    stage_candidates(novel, proposal)
    approve_candidate(novel, "CEX-0001")
    assert len(load_store(novel).selection.events) == 2


def test_relation_state_gate_requires_state_dimensions(tmp_path: Path) -> None:
    novel = _new_work(tmp_path)
    config = load_store(novel).config
    config.extract_gate = ExtractGate(
        profile="relation-state",
        unit="state changes",
        include=["state_change"],
        exclude="no state change",
    )
    atomic_write_model(novel / "chronos" / "chronos.config.yaml", config)
    with pytest.raises(ChronosLoadError, match="requires character_state.dimensions"):
        load_store(novel)
