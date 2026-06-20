"""NovelAI aspect_ratio_preset → width/height 解決のテスト。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from image_provider_generate import merge_provider_defaults, resolve_novelai_dimensions  # noqa: E402


NOVELAI_CFG = {
    "default_model": "nai-diffusion-4-5-full",
    "default_width": 1024,
    "default_height": 1024,
    "default_steps": 28,
    "default_cfg_scale": 6.5,
    "default_sampler_name": "k_euler_ancestral",
    "aspect_ratio_presets": {
        "square": {"width": 1024, "height": 1024},
        "book_cover": {"width": 832, "height": 1216},
    },
}


def test_resolve_novelai_dimensions_default() -> None:
    w, h = resolve_novelai_dimensions(NOVELAI_CFG, {})
    assert (w, h) == (1024, 1024)


def test_resolve_novelai_dimensions_book_cover() -> None:
    w, h = resolve_novelai_dimensions(
        NOVELAI_CFG, {"aspect_ratio_preset": "book_cover"}
    )
    assert (w, h) == (832, 1216)


def test_merge_provider_defaults_novelai_book_cover() -> None:
    merged = merge_provider_defaults(
        "novelai",
        NOVELAI_CFG,
        {"aspect_ratio_preset": "book_cover", "prompt": "test"},
    )
    assert merged["width"] == 832
    assert merged["height"] == 1216


def test_resolve_novelai_dimensions_unknown_preset() -> None:
    with pytest.raises(ValueError, match="aspect_ratio_preset"):
        resolve_novelai_dimensions(
            NOVELAI_CFG, {"aspect_ratio_preset": "unknown_ratio"}
        )
