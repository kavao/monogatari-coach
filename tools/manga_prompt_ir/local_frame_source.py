"""Build the P1 local-frame generation record from a saved PNG."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from manga_prompt_ir.page_edit import sha256_file
from manga_prompt_ir.page_render_plan import PageRenderPlan


def bubbles_suppressed_flag(frame_mode: str, text_mode: str) -> bool:
    return str(frame_mode) == "local" and str(text_mode) == "none"


def build_local_frame_source_record(
    *,
    image_path: str | Path,
    plan: PageRenderPlan | dict[str, Any],
    resolved_model: str | None = None,
) -> dict[str, Any]:
    if isinstance(plan, PageRenderPlan):
        frame_mode = plan.bubble_frame_mode
        text_mode = plan.text_mode
        capability_key = plan.capability_key
        settings = plan.effective_settings
    else:
        raw_settings = plan.get("effective_settings")
        settings = raw_settings if isinstance(raw_settings, dict) else plan
        frame_mode = str(plan.get("bubble_frame_mode") or settings.get("bubble_frame_mode") or "")
        text_mode = str(plan.get("text_mode") or settings.get("text_mode") or "")
        capability_key = str(plan.get("capability_key") or settings.get("capability_key") or "")
    if not bubbles_suppressed_flag(frame_mode, text_mode):
        from manga_prompt_ir.bubble_geometry import BubbleGeometryError

        raise BubbleGeometryError(
            "local frame 記録は bubble_frame_mode=local かつ text_mode=none の生成だけです"
        )
    path = Path(image_path)
    digest = sha256_file(path)
    model = resolved_model or (
        settings.get("resolved_model") if isinstance(settings, dict) else None
    )
    return {
        "bubble_frame_mode": "local",
        "text_mode": "none",
        "bubbles_suppressed": True,
        "source_sha256": digest,
        "capability_key": capability_key,
        "resolved_model": model,
        "saved_png": str(path),
    }
