from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import image_provider_edit_batch as batch_module
from image_edit.restyle import RestyleError, load_restyle_plan
from image_provider_edit import main


def _source(path: Path, *, rgba: bool) -> None:
    mode = "RGBA" if rgba else "RGB"
    color = (20, 40, 60, 128) if rgba else (20, 40, 60)
    Image.new(mode, (128, 64), color).save(path)
    path.with_suffix(".json").write_text(
        json.dumps({"prompt": "1girl", "negative_prompt": "lowres"}), encoding="utf-8"
    )


def test_batch_dry_run_groups_items_in_one_directory(tmp_path: Path, capsys) -> None:
    first = tmp_path / "p01_k01.png"
    second = tmp_path / "p01_k02.png"
    _source(first, rgba=True)
    _source(second, rgba=False)
    options = tmp_path / "options.json"
    options.write_text(json.dumps({"quality_toggle": False}), encoding="utf-8")

    assert (
        main(
            [
                "--input",
                str(first),
                "--batch",
                "--input",
                str(second),
                "--model",
                "v4-5-full",
                "--no-style-reference",
                "--provider-options",
                str(options),
                "--output-dir",
                str(tmp_path / "comic"),
                "--alpha-background",
                "white",
                "--dry-run",
            ]
        )
        == 0
    )
    batch = json.loads(capsys.readouterr().out)
    output_dir = Path(batch["output_dir"])
    assert output_dir == Path(batch["batch_plan_path"]).parent
    assert output_dir.name == batch["batch_id"]
    assert output_dir.parent.name == "_restyle"
    assert len(batch["items"]) == 2
    assert len({item["plan_path"] for item in batch["items"]}) == 2

    plans = [load_restyle_plan(Path(item["plan_path"])) for item in batch["items"]]
    assert {Path(plan["output_dir"]) for plan in plans} == {output_dir}
    assert {Path(plan["plan_path"]).parent for plan in plans} == {output_dir}
    prepared = [Path(plan["prepared_image"]["path"]) for plan in plans if plan["prepared_image"]]
    assert len(prepared) == 1
    assert prepared[0].parent == output_dir
    assert (output_dir / "batch_plan.json").is_file()
    assert not (output_dir / "batch_run.json").exists()


def _dry_batch(
    tmp_path: Path, capsys, sources: list[Path], *extra: str
) -> dict:
    args = ["--batch"]
    for source in sources:
        args.extend(["--input", str(source)])
    args.extend(
        [
            "--model",
            "v4-5-full",
            "--no-style-reference",
            "--output-dir",
            str(tmp_path / "comic"),
            "--dry-run",
            *extra,
        ]
    )
    assert main(args) == 0
    return json.loads(capsys.readouterr().out)


def test_batch_shared_prompt_is_applied_to_every_item(tmp_path: Path, capsys) -> None:
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    _source(first, rgba=False)
    _source(second, rgba=False)
    batch = _dry_batch(tmp_path, capsys, [first, second], "--prompt", "shared prompt")
    plans = [load_restyle_plan(Path(item["plan_path"])) for item in batch["items"]]
    assert {plan["prompt"]["source_value"] for plan in plans} == {"shared prompt"}
    assert {plan["prompt"]["source"] for plan in plans} == {"--prompt"}


def test_batch_rejects_duplicate_stems(tmp_path: Path, capsys) -> None:
    first = tmp_path / "one" / "frame.png"
    second = tmp_path / "two" / "frame.png"
    first.parent.mkdir()
    second.parent.mkdir()
    _source(first, rgba=False)
    _source(second, rgba=False)
    assert (
        main(
            [
                "--batch",
                "--input",
                str(first),
                "--input",
                str(second),
                "--model",
                "v4-5-full",
                "--no-style-reference",
                "--output-dir",
                str(tmp_path / "comic"),
                "--dry-run",
            ]
        )
        == 2
    )
    assert "stem" in capsys.readouterr().err


def test_batch_execute_writes_run_record_and_rejects_rerun(
    tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    _source(first, rgba=False)
    _source(second, rgba=False)
    batch = _dry_batch(tmp_path, capsys, [first, second])
    calls: list[str] = []

    def fake_execute(*, root, plan, provider_cfg):
        calls.append(plan["batch_item_id"])
        return {
            "run_id": plan["run_id"],
            "source_image": plan["source_image"],
            "candidates": [],
        }

    monkeypatch.setattr(batch_module, "execute_restyle", fake_execute)
    plan_path = batch["batch_plan_path"]
    assert main(["--batch", "--execute", "--batch-plan", plan_path]) == 0
    run_path = Path(batch["output_dir"]) / "batch_run.json"
    run = json.loads(run_path.read_text(encoding="utf-8"))
    assert run["status"] == "success"
    assert [item["status"] for item in run["items"]] == ["success", "success"]
    assert len(calls) == 2

    assert main(["--batch", "--execute", "--batch-plan", plan_path]) == 2
    assert "再executeを拒否" in capsys.readouterr().err
    assert len(calls) == 2


def test_batch_execute_records_partial_failure_and_pending_items(
    tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    sources = [tmp_path / f"item_{index}.png" for index in range(3)]
    for source in sources:
        _source(source, rgba=False)
    batch = _dry_batch(tmp_path, capsys, sources)
    calls: list[str] = []

    def fake_execute(*, root, plan, provider_cfg):
        calls.append(plan["batch_item_id"])
        if len(calls) == 2:
            raise RestyleError("fixture failure")
        return {"run_id": plan["run_id"], "source_image": plan["source_image"], "candidates": []}

    monkeypatch.setattr(batch_module, "execute_restyle", fake_execute)
    assert main(["--batch", "--execute", "--batch-plan", batch["batch_plan_path"]]) == 2
    run = json.loads((Path(batch["output_dir"]) / "batch_run.json").read_text(encoding="utf-8"))
    assert run["status"] == "partial_failure"
    assert [item["status"] for item in run["items"]] == ["success", "failed", "pending"]
    assert run["failure"]["remaining_items"] == ["item_2"]
    assert "再executeは行いません" in capsys.readouterr().err
