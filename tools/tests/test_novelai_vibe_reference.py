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
    merge_provider_defaults,
    _clamp_reference_coefficient,
)

# merge_provider_defaults(provider="novelai", ...) に必要な最低限のフィールド
_NOVELAI_MIN_CFG: dict = {
    "default_model": "nai-diffusion-5-full",
    "vibe_model": "nai-diffusion-4-5-full",
    "model_aliases": {
        "v5-full": "nai-diffusion-5-full",
        "v4-5-full": "nai-diffusion-4-5-full",
    },
    "default_width": 1024,
    "default_height": 1024,
    "default_steps": 28,
    "default_cfg_scale": 6.5,
    "default_sampler_name": "k_euler_ancestral",
}

# _is_probably_base64 を通過する最低限の擬似 base64（長さ 24 以上・許可文字のみ）
_FAKE_B64 = "A" * 40


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


def test_base64_direct_gets_default_coefficients(tmp_path: Path) -> None:
    """reference_image_multiple に base64 を直接渡したとき strength/IE が既定値で補完される。"""
    merged = merge_provider_defaults(
        "novelai",
        _NOVELAI_MIN_CFG,
        {"prompt": "test", "reference_image_multiple": [_FAKE_B64]},
        root=tmp_path,
    )
    assert merged["reference_image_multiple"] == [_FAKE_B64]
    assert merged["reference_strength_multiple"] == pytest.approx([0.6])
    assert merged["reference_information_extracted_multiple"] == pytest.approx([1.0])


def test_base64_direct_with_scalar_strength_multiplier(tmp_path: Path) -> None:
    """reference_image_multiple base64 直指定 + スカラー乗数が正しく適用される。"""
    merged = merge_provider_defaults(
        "novelai",
        _NOVELAI_MIN_CFG,
        {
            "prompt": "test",
            "reference_image_multiple": [_FAKE_B64],
            "reference_strength_multiple": 0.5,
        },
        root=tmp_path,
    )
    assert merged["reference_strength_multiple"] == pytest.approx([0.3])  # 0.6 * 0.5
    assert merged["reference_information_extracted_multiple"] == pytest.approx([1.0])


def test_base64_direct_two_slots_get_default_coefficients(tmp_path: Path) -> None:
    """base64 を 2 件渡したとき、strength/IE がそれぞれ 2 件補完される。"""
    merged = merge_provider_defaults(
        "novelai",
        _NOVELAI_MIN_CFG,
        {"prompt": "test", "reference_image_multiple": [_FAKE_B64, _FAKE_B64]},
        root=tmp_path,
    )
    assert merged["reference_strength_multiple"] == pytest.approx([0.6, 0.6])
    assert merged["reference_information_extracted_multiple"] == pytest.approx([1.0, 1.0])


def test_clamp_lower_bound_is_0_01() -> None:
    """係数 0 を渡したとき 0.01 に丸められる（API エラー回避）。"""
    assert _clamp_reference_coefficient(0.0) == pytest.approx(0.01)
    assert _clamp_reference_coefficient(-1.0) == pytest.approx(0.01)


def test_clamp_upper_bound_is_1_0() -> None:
    """係数が 1.0 を超えたとき 1.0 に丸められる。"""
    assert _clamp_reference_coefficient(2.0) == pytest.approx(1.0)
    assert _clamp_reference_coefficient(1.5) == pytest.approx(1.0)


def test_clamp_midrange_unchanged() -> None:
    """0.01〜1.0 の範囲は変化しない。"""
    assert _clamp_reference_coefficient(0.6) == pytest.approx(0.6)
    assert _clamp_reference_coefficient(0.01) == pytest.approx(0.01)
    assert _clamp_reference_coefficient(1.0) == pytest.approx(1.0)


def test_bundle_multiplier_zero_clamps_to_0_01(tmp_path: Path) -> None:
    """乗数 0 を渡したとき strength が 0.01 に丸められる（下限 clamp）。"""
    bundle = tmp_path / "zero.naiv4vibebundle"
    _mini_bundle(
        bundle,
        [
            {
                "encodings": {"m": {"u": {"encoding": "E" * 40}}},
                "importInfo": {"strength": 0.5, "information_extracted": 0.8},
            }
        ],
    )
    strengths, ies, _ = build_novelai_reference_coefficients(
        [bundle.as_posix()],
        tmp_path,
        strength_multiplier=0.0,
        information_extracted_multiplier=0.0,
    )
    assert strengths == pytest.approx([0.01])
    assert ies == pytest.approx([0.01])


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


def test_vibe_refs_pin_unspecified_model_to_v45(tmp_path: Path) -> None:
    merged = merge_provider_defaults(
        "novelai",
        _NOVELAI_MIN_CFG,
        {"prompt": "test", "reference_image_multiple": [_FAKE_B64]},
        root=tmp_path,
    )
    assert merged["model"] == "nai-diffusion-4-5-full"


def test_vibe_refs_keep_explicit_v45(tmp_path: Path) -> None:
    merged = merge_provider_defaults(
        "novelai",
        _NOVELAI_MIN_CFG,
        {
            "prompt": "test",
            "model": "v4-5-full",
            "reference_image_multiple": [_FAKE_B64],
        },
        root=tmp_path,
    )
    assert merged["model"] == "nai-diffusion-4-5-full"


def test_vibe_refs_reject_explicit_v5(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Vibe Transfer"):
        merge_provider_defaults(
            "novelai",
            _NOVELAI_MIN_CFG,
            {
                "prompt": "test",
                "model": "v5-full",
                "reference_image_multiple": [_FAKE_B64],
            },
            root=tmp_path,
        )


def test_vibe_refs_reject_explicit_v5_inpainting(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Vibe Transfer"):
        merge_provider_defaults(
            "novelai",
            _NOVELAI_MIN_CFG,
            {
                "prompt": "test",
                "model": "nai-diffusion-5-full-inpainting",
                "reference_image_multiple": [_FAKE_B64],
            },
            root=tmp_path,
        )
