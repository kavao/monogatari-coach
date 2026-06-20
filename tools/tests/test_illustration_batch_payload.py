"""挿絵バッチ: payload 組み立てと provider 別 resolution のテスト。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from image_provider_novel_illustration_batch import build_job_payload  # noqa: E402


def test_build_job_payload_novelai_includes_reference_fields() -> None:
    ref = {
        "reference_image_paths": ["/tmp/a.naiv4vibebundle"],
        "reference_strength_multiple": [0.3],
        "reference_information_extracted_multiple": [0.5],
    }
    job = {
        "prompt": "p",
        "negative_prompt": "n",
        "prompt_formatter": "tag_csv",
        "negative_mode": "native",
        "output_dir": "/out",
        "prefix": "illustration_00_p01",
    }
    payload = build_job_payload(
        "novelai",
        job,
        aspect_ratio="book_cover",
        model=None,
        resolution="2k",
        novelai_ref_fields=ref,
    )
    assert payload["reference_image_paths"] == ref["reference_image_paths"]
    assert payload["aspect_ratio_preset"] == "book_cover"
    assert "resolution" not in payload


def test_build_job_payload_grok_includes_resolution() -> None:
    job = {
        "prompt": "p",
        "negative_prompt": "n",
        "prompt_formatter": "natural_sections",
        "negative_mode": "inline",
        "output_dir": "/out",
        "prefix": "illustration_01_p01",
    }
    payload = build_job_payload(
        "grok_pro",
        job,
        aspect_ratio="book_cover",
        model="quality",
        resolution="2k",
        novelai_ref_fields={},
    )
    assert payload["resolution"] == "2k"
    assert payload["model"] == "quality"
