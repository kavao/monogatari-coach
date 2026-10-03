#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
漫画ページ YAML の台詞と layout_geometry から、フキダシの設計位置の下書き（<page>.bubbles.yaml）を作る。

各コマの枠の上側に、右から左へフキダシを並べる（入りきらなければ下の段、それでも入らなければ文字を小さく）。
大きさは写植（novel_manga_assemble_psd.py）と同じ B5 キャンバス・文字の大きさで、縦書きが収まるように決める。
しっぽはコマの中央やや下へ向ける。あくまで下書きで、位置やしっぽの向きは編集ソフトで直す前提。

フキダシの種類（.bubbles.yaml の bubble_type。台詞の種類で決まる）:
    台詞（dialogue）→ speech / 心の声（monologue）→ thought / ナレーション（narration）→ narration / 効果音（sfx）→ sfx
PSD での描き分け（novel_manga_assemble_psd.py）は panel_assembly.BALLOON_STYLES を参照。台詞の bubble_type に
「shout」「叫」「大声」などがあると「叫び」（ギザギザ）で描く。

保存先: manga/pages/<page>.bubbles.yaml（既存の枠描画・写植と同じ設計データ。先頭に「自動の下書き」と書く）。

使い方:
    python tools/novel_manga_bubbles_draft.py novels/001_タイトル [オプション]

オプション:
    （既定）         配置の計画を表示するだけで、何も書かない
    --apply          .bubbles.yaml を書き出す
    --overwrite      既にある .bubbles.yaml を置き換える（前のものは manga/pages/_old/<実行日時>/ へ退避）
    --manga-stem S   対象を manga_01 などの章に絞る
    --page PATH      対象ページを指定（作品フォルダからの相対パス可、複数可）
    --dpi N          大きさの計算に使うキャンバスの解像度（既定 200。写植と同じ値にする）
    --font-mm N      写植の文字の大きさ（mm。既定 3.5 ≒ 14級。写植と同じ値にする）
"""

from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from manga_prompt_ir.bubble_draft import DraftText, draft_panel  # noqa: E402
from manga_prompt_ir.bubble_geometry import (  # noqa: E402
    TEXT_BUBBLE_TYPES,
    bubble_source_digest,
    check_bubbles_match_page,
    load_bubble_design,
)
from manga_prompt_ir.schemas.manga_page import MangaPagePrompt  # noqa: E402
from novel_manga_assemble_psd import (  # noqa: E402
    DEFAULT_DPI,
    FONT_MM_DEFAULT,
    canvas_size,
    collect_texts,
    discover_pages,
    frame_px,
    lettering_font_px,
    load_yaml,
    unique_run_dir,
)

HEADER = (
    "# 自動の下書き（tools/novel_manga_bubbles_draft.py）。フキダシの位置としっぽの向きは編集ソフトで直す前提。\n"
    "# 座標はページに対する割合（0〜1、左上原点）。bubble_type は speech / thought / narration / sfx。\n"
)


def _normalize(box: tuple[int, int, int, int], size: tuple[int, int], *, outward: bool) -> dict[str, float]:
    """ピクセルの矩形を 0〜1 に。枠は外へ、文字の範囲は内へ丸めて、内側に収まる関係を保つ。"""
    import math

    width, height = size
    if outward:
        x0 = math.floor(box[0] / width * 10000) / 10000
        y0 = math.floor(box[1] / height * 10000) / 10000
        x1 = math.ceil(box[2] / width * 10000) / 10000
        y1 = math.ceil(box[3] / height * 10000) / 10000
    else:
        x0 = math.ceil(box[0] / width * 10000) / 10000
        y0 = math.ceil(box[1] / height * 10000) / 10000
        x1 = math.floor(box[2] / width * 10000) / 10000
        y1 = math.floor(box[3] / height * 10000) / 10000
    x0, y0 = max(0.0, x0), max(0.0, y0)
    x1, y1 = min(1.0, x1), min(1.0, y1)
    return {"x": x0, "y": y0, "width": round(x1 - x0, 4), "height": round(y1 - y0, 4)}


def draft_page(
    page: dict, size: tuple[int, int], font_px: float, page_name: str = "page"
) -> tuple[dict[str, Any], list[str]]:
    """ページ1枚分の .bubbles.yaml の中身と、警告を返す。"""
    model = MangaPagePrompt.model_validate(page)
    texts = collect_texts(model)
    geometry = {int(item["panel_id"]): item for item in (page.get("layout_geometry") or {}).get("panels") or []}
    warnings: list[str] = []
    bubbles: list[dict[str, Any]] = []
    for panel in model.panels:
        panel_id = int(panel.panel_id)
        items = [
            DraftText(
                text_id=text["text_id"],
                bubble_type=TEXT_BUBBLE_TYPES[text["kind"]],
                chars=len(text["content"]),
                font_px=font_px,
            )
            for text in texts
            if text["panel_id"] == panel_id
        ]
        if not items:
            continue
        frame = frame_px(geometry[panel_id]["rect"], size)
        result = draft_panel(frame, items)
        if not result.fitted:
            warnings.append(f"panel {panel_id}: 台詞がコマに入りきらないので、重ねて置きました（allow_overlap）")
        elif result.scale < 0.999:
            warnings.append(f"panel {panel_id}: 入りきらないので文字の大きさを {result.scale:.0%} にして並べました")
        for bubble in result.bubbles:
            entry: dict[str, Any] = {
                "text_id": bubble.text_id,
                "panel_id": panel_id,
                "bubble_type": bubble.bubble_type,
                "frame_rect": _normalize(bubble.frame, size, outward=True),
                "text_rect": _normalize(bubble.text, size, outward=False),
            }
            if bubble.tail:
                entry["tail"] = {
                    "points": [[round(x / size[0], 4), round(y / size[1], 4)] for x, y in bubble.tail]
                }
            if bubble.allow_overlap:
                entry["allow_overlap"] = True
            bubbles.append(entry)
    document = {
        "kind": "design_projected",
        "coordinate_space": "normalized",
        # 下書きを作ったときの台詞と枠。PSD の組み立てはこれとページを比べ、変わっていれば止める
        "source": {"page": page_name, "page_digest": bubble_source_digest(page)},
        "bubbles": bubbles,
    }
    check_bubbles_match_page(page, load_bubble_design(document))  # 型とページとの対応の検証
    return document, warnings


def stale_note(sidecar: Path, page: dict) -> str:
    """既存の下書きがページと食い違っていれば、その旨の一言（PSD の組み立てはこのページで止まる）。"""
    try:
        document = load_bubble_design(yaml.safe_load(sidecar.read_text(encoding="utf-8")) or {})
        check_bubbles_match_page(page, document)
    except Exception:  # noqa: BLE001
        return "。ページの台詞と対応していません"
    if document.source is not None and document.source.page_digest != bubble_source_digest(page):
        return "。作ったあとでページの台詞か枠が変わっています"
    return ""


def run(args: argparse.Namespace) -> int:
    novel_dir = Path(args.novel_dir)
    try:
        pages = discover_pages(novel_dir, args.manga_stem, args.page)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if not pages:
        print("対象の漫画ページ YAML がありません。", file=sys.stderr)
        return 1
    size = canvas_size(args.dpi)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    old_dir: Path | None = None
    planned = skipped = errors = 0
    for path in pages:
        label = path.name
        sidecar = path.with_name(f"{path.stem}.bubbles.yaml")
        try:
            page = load_yaml(path)
            model = MangaPagePrompt.model_validate(page)
        except Exception as exc:  # noqa: BLE001
            print(f"[エラー] {label}: 読み込み・検証に失敗しました: {exc}")
            errors += 1
            continue
        if model.render_instruction.text_mode == "none":
            print(f"[対象外] {label}: text_mode が none です")
            skipped += 1
            continue
        if not collect_texts(model):
            print(f"[対象外] {label}: 台詞がありません")
            skipped += 1
            continue
        if not (page.get("layout_geometry") or {}).get("panels"):
            print(f"[対象外] {label}: layout_geometry がありません")
            skipped += 1
            continue
        if sidecar.exists() and not args.overwrite:
            print(f"[既存] {label}: {sidecar.name} があるため触りません（置き換えるときは --overwrite）{stale_note(sidecar, page)}")
            skipped += 1
            continue
        try:
            document, warnings = draft_page(page, size, lettering_font_px(args.dpi, args.font_mm), path.name)
        except Exception as exc:  # noqa: BLE001
            print(f"[エラー] {label}: 下書きを作れません: {exc}")
            errors += 1
            continue
        counts: dict[str, int] = {}
        for bubble in document["bubbles"]:
            counts[bubble["bubble_type"]] = counts.get(bubble["bubble_type"], 0) + 1
        summary = "・".join(f"{kind} {count}" for kind, count in counts.items())
        print(f"[計画] {label}: フキダシ {len(document['bubbles'])} 件（{summary}）→ {sidecar.name}")
        for warning in warnings:
            print(f"       警告: {warning}")
        planned += 1
        if not args.apply:
            continue
        if sidecar.exists():
            old_dir = old_dir or unique_run_dir(path.parent / "_old", stamp)
            old_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(sidecar), str(old_dir / sidecar.name))
            print(f"       前の下書きを退避しました: {old_dir.relative_to(novel_dir).as_posix()}/")
        sidecar.write_text(
            HEADER + yaml.safe_dump(document, allow_unicode=True, sort_keys=False), encoding="utf-8", newline="\n"
        )
        print(f"       書き出しました: {sidecar.relative_to(novel_dir).as_posix()}")
    mode = "書き出し" if args.apply else "計画のみ（--apply で書き出し）"
    print(f"\n{mode}: 対象 {planned} / 対象外・既存 {skipped} / エラー {errors}")
    return 1 if errors else 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="フキダシの設計位置の下書き（.bubbles.yaml）を作る（既定は計画の表示のみ）")
    p.add_argument("novel_dir", help="novels/<NNN_タイトル>/ のパス")
    p.add_argument("--apply", action="store_true", help=".bubbles.yaml を書き出す")
    p.add_argument("--overwrite", action="store_true", help="既にある .bubbles.yaml を置き換える（前のものは退避）")
    p.add_argument("--manga-stem", default=None, help="対象の章（例: manga_01）")
    p.add_argument("--page", action="append", default=[], help="対象ページ YAML（複数可）")
    p.add_argument("--dpi", type=int, default=DEFAULT_DPI, help="大きさの計算に使う解像度（既定 200）")
    p.add_argument(
        "--font-mm", type=float, default=FONT_MM_DEFAULT, help="写植の文字の大きさ（mm。既定 3.5。写植と同じ値にする）"
    )
    return p


def main(argv: list[str] | None = None) -> int:
    return run(build_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
