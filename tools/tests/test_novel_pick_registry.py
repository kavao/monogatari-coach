"""Tests for novel_pick_registry.py."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from novel_pick_registry import (  # noqa: E402
    merge_registry,
    parse_pick_lists_from_file,
    resolve_registry_dirs,
    validate_entries,
)

FIXTURE_REGISTRY = ROOT / "tools" / "fixtures" / "pick_registry"


def test_parse_pick_lists_from_file():
    fragment = FIXTURE_REGISTRY / "test.yaml"
    entries = parse_pick_lists_from_file(fragment, FIXTURE_REGISTRY)
    assert "test_sample" in entries
    assert entries["test_sample"].path == "items"


def test_merge_registry_includes_example_and_user():
    entries = merge_registry()
    assert "naming_western_male" in entries
    user_mature = ROOT / "_how_to" / "pick_registry" / "mature.yaml"
    if user_mature.is_file():
        assert "mature_episode_opening" in entries
        assert entries["mature_episode_opening"].visibility == "user"


def test_validate_public_lists():
    entries = merge_registry()
    public = {k: v for k, v in entries.items() if v.visibility == "public"}
    errors = validate_entries(public)
    assert errors == []


def test_cli_validate():
    cmd = [sys.executable, str(ROOT / "tools" / "novel_pick_registry.py"), "validate"]
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


def test_cli_pick_naming(monkeypatch):
    cmd = [
        sys.executable,
        str(ROOT / "tools" / "novel_pick_registry.py"),
        "pick",
        "naming_western_male",
        "--seed",
        "1",
    ]
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    assert proc.returncode == 0
    assert proc.stdout.strip()


def test_resolve_registry_dirs_with_fixture():
    dirs = resolve_registry_dirs(
        merge_order=["tools/fixtures/pick_registry"],
    )
    assert dirs == [FIXTURE_REGISTRY.resolve()]