"""Validate and project local-frame bubble sidecars.

Design coordinates stay normalized. Pixel projection is not actual geometry
until the output image hash is bound. layout_geometry is never used as a
bubble source.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image

from manga_prompt_ir.page_edit import PageEditError, sha256_file
from manga_prompt_ir.schemas.bubble_frame import BubbleDesignDocument, NormalizedRect
from manga_prompt_ir.schemas.manga_page import MangaPagePrompt
from manga_prompt_ir.text_ids import assigned_text_id

LOCAL_FRAME_KINDS = ("dialogue", "narration")
UNSUPPORTED_KINDS = ("monologue", "sfx")


class BubbleGeometryError(PageEditError):
    """Invalid bubble sidecar or projection."""


def _as_dict(page: dict[str, Any] | MangaPagePrompt) -> dict[str, Any]:
    if isinstance(page, MangaPagePrompt):
        return page.model_dump(mode="json")
    return page


def page_lettering_targets(page: dict[str, Any] | MangaPagePrompt) -> list[dict[str, Any]]:
    model = page if isinstance(page, MangaPagePrompt) else MangaPagePrompt.model_validate(page)
    targets: list[dict[str, Any]] = []
    for panel in model.panels:
        mapping = {
            "dialogue": panel.text.dialogue,
            "narration": panel.text.narration,
            "monologue": panel.text.monologue,
            "sfx": panel.text.sfx,
        }
        for kind, items in mapping.items():
            for index, item in enumerate(items, start=1):
                content = str(getattr(item, "content", item) or "").strip()
                if not content:
                    continue
                text_id = assigned_text_id(
                    item, panel_id=panel.panel_id, kind=kind, index=index
                )
                targets.append(
                    {
                        "text_id": text_id,
                        "panel_id": int(panel.panel_id),
                        "type": kind,
                    }
                )
    return targets


def local_frame_targets(page: dict[str, Any] | MangaPagePrompt) -> list[dict[str, Any]]:
    targets = page_lettering_targets(page)
    unsupported = [item for item in targets if item["type"] in UNSUPPORTED_KINDS]
    if unsupported:
        ids = ", ".join(f"{item['text_id']}({item['type']})" for item in unsupported)
        raise BubbleGeometryError(f"local frame MVP は speech/narration のみです: {ids}")
    return [item for item in targets if item["type"] in LOCAL_FRAME_KINDS]


def load_bubble_design(data: dict[str, Any]) -> BubbleDesignDocument:
    try:
        return BubbleDesignDocument.model_validate(data)
    except Exception as exc:
        raise BubbleGeometryError(str(exc)) from exc


def require_clean_source(
    record: dict[str, Any] | None,
    *,
    image_path: str | Path | None = None,
) -> None:
    if not isinstance(record, dict) or not record:
        raise BubbleGeometryError("local frame には泡抑止済みの生成記録が必要です")
    frame_mode = str(record.get("bubble_frame_mode") or "").strip()
    text_mode = str(record.get("text_mode") or "").strip()
    if frame_mode == "local" and text_mode in {"letter_later", "generate"}:
        raise BubbleGeometryError(
            "bubble_frame_mode=local は text_mode=letter_later / generate と併用できません"
        )
    suppressed = record.get("bubbles_suppressed")
    if suppressed is True:
        suppressed_ok = True
    elif isinstance(suppressed, str) and suppressed.strip().lower() in {"true", "1", "yes"}:
        suppressed_ok = True
    else:
        suppressed_ok = False
    if frame_mode != "local" or text_mode != "none" or not suppressed_ok:
        raise BubbleGeometryError(
            "local frame の入力は bubble_frame_mode=local かつ text_mode=none "
            "かつ bubbles_suppressed=true の生成記録付き PNG に限ります"
        )
    if image_path is None:
        return
    declared = str(record.get("source_sha256") or "").strip().lower()
    if len(declared) != 64:
        raise BubbleGeometryError("local frame の生成記録に入力 PNG の source_sha256 が必要です")
    actual = sha256_file(image_path)
    if declared != actual:
        raise BubbleGeometryError("生成記録の source_sha256 が入力 PNG と一致しません")


def validate_bubble_design(
    page: dict[str, Any] | MangaPagePrompt,
    data: dict[str, Any],
    *,
    source_generation: dict[str, Any] | None = None,
    image_path: str | Path | None = None,
) -> BubbleDesignDocument:
    require_clean_source(source_generation, image_path=image_path)
    document = load_bubble_design(data)
    targets = local_frame_targets(page)
    by_id = {item["text_id"]: item for item in targets}
    bubble_ids = [bubble.text_id for bubble in document.bubbles]
    missing = [item["text_id"] for item in targets if item["text_id"] not in set(bubble_ids)]
    extra = [text_id for text_id in bubble_ids if text_id not in by_id]
    if extra:
        raise BubbleGeometryError("未知の text_id です: " + ", ".join(extra))
    if missing:
        raise BubbleGeometryError("manifest に対して bubbles が不足しています: " + ", ".join(missing))
    if len(bubble_ids) != len(targets):
        raise BubbleGeometryError(
            f"local frame の件数と bubbles 件数が一致しません: {len(targets)}/{len(bubble_ids)}"
        )
    known_panels = {int(panel.panel_id) for panel in MangaPagePrompt.model_validate(_as_dict(page)).panels}
    for bubble in document.bubbles:
        target = by_id[bubble.text_id]
        if int(bubble.panel_id) != int(target["panel_id"]):
            raise BubbleGeometryError(
                f"panel_id が一致しません: {bubble.text_id} "
                f"geometry={bubble.panel_id} manifest={target['panel_id']}"
            )
        if int(bubble.panel_id) not in known_panels:
            raise BubbleGeometryError(f"未知の panel_id です: {bubble.panel_id}")
        expected_type = "speech" if target["type"] == "dialogue" else "narration"
        if bubble.bubble_type != expected_type:
            raise BubbleGeometryError(
                f"bubble_type が text 種別と一致しません: {bubble.text_id} "
                f"{bubble.bubble_type}/{expected_type}"
            )
    return document


def _project_rect(rect: NormalizedRect, width: int, height: int) -> list[int]:
    left = round(rect.x * width)
    top = round(rect.y * height)
    right = round(rect.right() * width)
    bottom = round(rect.bottom() * height)
    if right <= left or bottom <= top:
        raise BubbleGeometryError("投影後の矩形の幅または高さが0です")
    if left < 0 or top < 0 or right > width or bottom > height:
        raise BubbleGeometryError("投影後の矩形が画像範囲外です")
    return [left, top, right, bottom]


def project_bubble_design(
    page: dict[str, Any] | MangaPagePrompt,
    data: dict[str, Any],
    *,
    image_size: tuple[int, int],
    source_generation: dict[str, Any] | None = None,
    image_path: str | Path | None = None,
) -> dict[str, Any]:
    document = validate_bubble_design(
        page,
        data,
        source_generation=source_generation,
        image_path=image_path,
    )
    width, height = image_size
    if width < 1 or height < 1:
        raise BubbleGeometryError("画像サイズが不正です")
    bubbles: list[dict[str, Any]] = []
    texts: list[dict[str, Any]] = []
    for bubble in document.bubbles:
        frame_px = _project_rect(bubble.frame_rect, width, height)
        text_px = _project_rect(bubble.text_rect, width, height)
        if (
            text_px[0] < frame_px[0]
            or text_px[1] < frame_px[1]
            or text_px[2] > frame_px[2]
            or text_px[3] > frame_px[3]
        ):
            raise BubbleGeometryError(
                f"投影後の text_rect_px が frame_rect_px の内側にありません: {bubble.text_id}"
            )
        projected: dict[str, Any] = {
            "text_id": bubble.text_id,
            "panel_id": bubble.panel_id,
            "bubble_type": bubble.bubble_type,
            "kind": "design_projected",
            "frame_rect_px": frame_px,
            "text_rect_px": text_px,
            "allow_overlap": bubble.allow_overlap,
        }
        if bubble.tail is not None:
            projected["tail_px"] = [
                [round(point[0] * width), round(point[1] * height)]
                for point in bubble.tail.points
            ]
        bubbles.append(projected)
        texts.append(
            {
                "text_id": bubble.text_id,
                "panel_id": bubble.panel_id,
                "kind": "design_projected",
                "rect_px": text_px,
            }
        )
    return {
        "kind": "design_projected",
        "coordinate_space": "pixel",
        "image_size": [width, height],
        "bubbles": bubbles,
        "texts": texts,
    }


def bind_bubble_actual(
    projected: dict[str, Any],
    *,
    image_path: str | Path,
    page: dict[str, Any] | MangaPagePrompt,
) -> dict[str, Any]:
    from manga_prompt_ir.page_edit import bind_actual_geometry, project_design_geometry

    path = Path(image_path)
    if projected.get("kind") != "design_projected":
        raise BubbleGeometryError("枠合成前の projected geometry が必要です")
    if projected.get("coordinate_space") != "pixel":
        raise BubbleGeometryError("actual bind の前に正規化座標を画素へ投影してください")
    digest = sha256_file(path)
    with Image.open(path) as image:
        width, height = image.size
    declared_size = projected.get("image_size") or []
    if list(declared_size) != [width, height]:
        raise BubbleGeometryError("投影時の画像寸法と bind 画像の寸法が一致しません")
    page_dict = _as_dict(page)
    design_panels = project_design_geometry(page_dict, image_size=(width, height))
    actual_texts = []
    for item in projected.get("texts") or []:
        actual_texts.append(
            {
                "text_id": item["text_id"],
                "panel_id": item.get("panel_id"),
                "rect_px": list(item["rect_px"]),
            }
        )
    bound = bind_actual_geometry(
        {
            "kind": "actual",
            "source_sha256": digest,
            "panels": [
                {"panel_id": item["panel_id"], "rect_px": item["rect_px"]}
                for item in design_panels["panels"]
            ],
            "texts": actual_texts,
        },
        image_path=path,
        page=page_dict,
    )
    bubbles = []
    for item in projected.get("bubbles") or []:
        bubble = dict(item)
        bubble["kind"] = "actual"
        bubbles.append(bubble)
    bound["bubbles"] = bubbles
    bound["coordinate_space"] = "pixel"
    return bound
