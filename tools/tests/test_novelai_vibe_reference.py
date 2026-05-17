#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from image_provider_generate import (  # noqa: E402
    build_novelai_reference_coefficients,
    load_reference_vibe_items_from_file,
)


def _mini_bundle(path: Path, vibes: list[dict]) -> None:
    path.write_text(
        json.dumps({"identifier": "test", "version": 1, "vibes": vibes}),
        encoding="utf-8",
    )


def test_bundle_import_info_preserved_with_multiplier_one(tmp_path: Path) -> None:
    bundle = tmp_path / "test.naiv4vibebundle"
    _mini_bundle(
        bundle,
        [
            {
                "encodings": {"m": {"u": {"encoding": "A" * 40}}},
                "importInfo": {"strength": 0.22, "information_extracted": 0.4},
            },
            {
                "encodings": {"m": {"u": {"encoding": "B" * 40}}},
                "importInfo": {"strength": 0.2, "information_extracted": 0.37},
            },
        ],
    )
    items = load_reference_vibe_items_from_file(bundle)
    assert len(items) == 2
    assert items[0].strength == pytest.approx(0.22)
    assert items[1].strength == pytest.approx(0.2)
    assert items[0].from_bundle_meta is True

    strengths, ies, normalize = build_novelai_reference_coefficients(
        [bundle.as_posix()],
        tmp_path,
        strength_multiplier=1.0,
        information_extracted_multiplier=1.0,
    )
    assert strengths == pytest.approx([0.22, 0.2])
    assert ies == pytest.approx([0.4, 0.37])
    assert normalize is False


def test_bundle_multiplier_scales_all_slots(tmp_path: Path) -> None:
    bundle = tmp_path / "scale.naiv4vibebundle"
    _mini_bundle(
        bundle,
        [
            {
                "encodings": {"m": {"u": {"encoding": "C" * 40}}},
                "importInfo": {"strength": 0.2, "information_extracted": 0.5},
            },
            {
                "encodings": {"m": {"u": {"encoding": "D" * 40}}},
                "importInfo": {"strength": 0.4, "information_extracted": 1.0},
            },
        ],
    )
    strengths, ies, _normalize = build_novelai_reference_coefficients(
        [bundle.as_posix()],
        tmp_path,
        strength_multiplier=0.5,
        information_extracted_multiplier=2.0,
    )
    assert strengths == pytest.approx([0.1, 0.2])
    assert ies == pytest.approx([1.0, 1.0])  # clamped at 1.0


def test_flat2_bundle_matches_novelai_export(tmp_path: Path) -> None:
    flat2 = ROOT / "_how_to/image_refs/novelai/2026-05-17_flat2.naiv4vibebundle"
    if not flat2.is_file():
        pytest.skip("flat2 bundle not in workspace")
    strengths, ies, normalize = build_novelai_reference_coefficients(
        [flat2.as_posix()],
        ROOT,
        strength_multiplier=1.0,
        information_extracted_multiplier=1.0,
    )
    assert len(strengths) == 2
    assert strengths == pytest.approx([0.22, 0.2])
    assert ies == pytest.approx([0.4, 0.37])
    assert normalize is False
