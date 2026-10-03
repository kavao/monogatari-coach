#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
漫画ページ YAML の layout_geometry（ネームの枠）に、コマ単位の画像を収めた PSD と PNG を書き出す。

コマ画像は manga/_assets/<manga_XX>/comic/<page>_kNN_*.png（NN はコマの並び順）から取り、
切らずに「中央合わせ・枠を隙間なく埋める大きさ」で置く。枠はクリッピングで表すので、
編集ソフトでコマ画像を動かすと枠の中の見え方だけが変わる。背景・土台・枠線・ネームはロックする。

出力（計画 20260930_manga-panel-assembly-psd の C6 案A）:
    manga/_assets/<manga_XX>/assembled/<page>_assembled.psd
    manga/_assets/<manga_XX>/assembled/<page>_assembled.png   （同じ見た目の確認用）
    manga/_assets/<manga_XX>/assembled/<page>_assembly.json   （採用画像の記録）
    manga/_assets/<manga_XX>/assembled/<page>_lettering.txt   （台詞の一覧。文字のあるページだけ）

写植: ページに台詞があり render_instruction.text_mode が none でないとき、PSD の「写植」グループに
「フキダシ n」（中に文字と画像）を置く。位置は manga/pages/<page>.bubbles.yaml（設計位置）。
写植は画像の目安で、編集できる文字ではない。縦書きの打ち直しはクリップスタジオ / Photoshop で行う想定で、
そのための台詞の一覧を <page>_lettering.txt に書き出す（番号は PSD のフキダシ番号と同じ）。
.bubbles.yaml が無いページは、写植の画像は作らず一覧だけを書き出す。.bubbles.yaml がページの台詞と1対1で
対応しないとき、または下書きのあとで台詞・枠が変わったとき（source.page_digest が違う）は、そのページを書き出さない。

使い方:
    python tools/novel_manga_assemble_psd.py novels/001_タイトル [オプション]

オプション:
    （既定）         使う画像・倍率・はみ出しを表示するだけで、何も書かない
    --apply          PSD・PNG・採用画像の記録を書き出す
    --overwrite      既にある PSD / PNG を置き換える（既定は触らない）。4つのファイル（PSD・PNG・記録・台詞の一覧）を
                     作業用フォルダに書き終えてから一式で置き換え、前の版は assembled/old/<実行日時>/ へ退避する
                     （途中で失敗したら前の版を元に戻す）
    --manga-stem S   対象を manga_01 などの章に絞る
    --page PATH      対象ページを指定（作品フォルダからの相対パス可、複数可）
    --dpi N          キャンバスの解像度（既定 200。キャンバスは B5 182×257mm）
    --no-name-ref    非表示のネーム（参考）レイヤーを入れない
    --reselect       採用画像の記録を使わず、各コマの最新の画像を選び直す（コマを作り直したあとに使う。
                     既存の PSD / PNG を置き換えるには --overwrite も要る）
    --focus P:ID=X,Y 見せたい点を指定する（例: manga_01_p04:1=0.5,0.2 は p04 の panel_id 1 で、元画像の
                     横 50%・縦 20% の点を枠の中央へ寄せる。枠を埋めることを優先する）。複数可。
                     指定は採用画像の記録（assembly.json）に残り、次回も使われる（--reselect で画像を
                     選び直したコマでは外れる）
    --max-scale N    コマ画像の拡大率がこれを超えたら警告する（既定 1.5。実質の解像度が下がるため）
    --font PATH      写植のフォント（既定: 環境変数 MONOCRI_LETTERING_FONT、無ければ 游ゴシック Medium
                     → Noto Sans JP → MS ゴシック の順で見つかったもの）
    --no-lettering   写植と台詞の一覧を作らない
    --font-mm N      写植の文字の大きさ（mm。既定 3.5 ≒ 14級。200dpi で 28px）。入りきらないフキダシでは 75% まで小さくする

採用画像: assembly.json に記録があればそれを使う（SHA-256 が合わなければ止める）。
記録が無いとき、候補が1枚ならそれ、複数なら最新（ファイル名の日時が最も新しいもの）を使い警告する。
PSD の書き出しには psd-tools を使う（pyproject.toml の依存。uv sync で入る）。
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

import yaml
from PIL import Image

_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from manga_prompt_ir.bubble_draft import TEXT_RATIO  # noqa: E402
from manga_prompt_ir.bubble_geometry import (  # noqa: E402
    BubbleGeometryError,
    bubble_source_digest,
    check_bubbles_match_page,
    load_bubble_design,
)
from manga_prompt_ir.name_renderer import render_name_image  # noqa: E402
from manga_prompt_ir.page_edit import PageEditError, letter_page  # noqa: E402
from manga_prompt_ir.panel_assembly import (  # noqa: E402
    LetteringItem,
    PanelAssemblyError,
    PanelInput,
    balloon_image,
    ink_to_layer,
    plan_placements,
    replace_together,
    sha256_file,
    write_assembly,
)
from manga_prompt_ir.schemas.manga_page import MangaPagePrompt  # noqa: E402
from manga_prompt_ir.text_ids import assigned_text_id  # noqa: E402

B5_MM = (182, 257)
DEFAULT_DPI = 200
_PAGE_RE = re.compile(r"^(?P<stem>.+)_p(?P<num>\d+)\.ya?ml$")
RECORD_VERSION = 1
FONT_ENV = "MONOCRI_LETTERING_FONT"
DEFAULT_FONT_CANDIDATES = (
    Path("C:/Windows/Fonts/YuGothM.ttc"),
    Path("C:/Windows/Fonts/NotoSansJP-VF.ttf"),
    Path("C:/Windows/Fonts/msgothic.ttc"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    Path("/System/Library/Fonts/ヒラギノ角ゴシック W4.ttc"),
)
# 写植の文字の大きさは印刷の寸法で決める（既定 3.5mm ≒ 14級。商業誌の漫画の本文は 13〜14級が一般的）
FONT_MM_DEFAULT = 3.5
# 写植を1列に収めるために試す大きさ（基準に対する比。最小 75%）
SINGLE_LINE_SIZE_STEPS = (1.0, 0.9, 0.8, 0.75)
# 台詞の bubble_type にこれらが含まれていたら「叫び」（ギザギザ）で描く
SHOUT_HINTS = ("shout", "scream", "yell", "burst", "叫", "怒鳴", "大声", "絶叫", "ギザ")
KIND_LABELS = {"dialogue": "台詞", "monologue": "心の声", "narration": "ナレーション", "sfx": "効果音"}


def canvas_size(dpi: int) -> tuple[int, int]:
    return (round(B5_MM[0] / 25.4 * dpi), round(B5_MM[1] / 25.4 * dpi))


def frame_line_width(dpi: int) -> int:
    return max(2, round(dpi * 0.03))


def frame_px(rect: dict[str, float], size: tuple[int, int]) -> tuple[int, int, int, int]:
    """正規化矩形を B5 キャンバスの画素へ（計画 C2 案a: 枠は B5 基準に直接当てる）。"""
    width, height = size
    left = round(rect["x"] * width)
    top = round(rect["y"] * height)
    right = round((rect["x"] + rect["w"]) * width)
    bottom = round((rect["y"] + rect["h"]) * height)
    return left, top, right, bottom


def load_yaml(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"YAML ルートがマッピングではありません: {path}")
    return data


def discover_pages(novel_dir: Path, stem: str | None, explicit: list[str]) -> list[Path]:
    if explicit:
        pages = []
        for item in explicit:
            path = Path(item) if Path(item).is_absolute() else novel_dir / item
            if not path.is_file():
                raise FileNotFoundError(f"指定したページがありません: {path}")
            pages.append(path)
        return pages
    found = []
    for path in (novel_dir / "manga" / "pages").glob("*.y*ml"):
        match = _PAGE_RE.match(path.name)
        if not match:
            continue
        if stem and match.group("stem") != stem:
            continue
        found.append(path)
    return sorted(found, key=lambda p: (_PAGE_RE.match(p.name).group("stem"), int(_PAGE_RE.match(p.name).group("num"))))


def chapter_of(path: Path) -> str:
    match = _PAGE_RE.match(path.name)
    if not match:
        raise ValueError(f"manga_XX_pYY.yaml の形ではありません: {path.name}")
    return match.group("stem")


def load_record(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def resolve_panel_image(
    assets_dir: Path, page_stem: str, koma: int, record_entry: dict[str, Any] | None
) -> tuple[Path, str | None]:
    """採用画像を決める。戻り値は（パス, 警告）。記録と食い違えば止める。"""
    if record_entry and record_entry.get("image"):
        path = assets_dir / record_entry["image"]
        if not path.is_file():
            raise PanelAssemblyError(f"k{koma:02d}: 記録された採用画像がありません: {record_entry['image']}")
        expected = record_entry.get("sha256")
        if expected and sha256_file(path) != expected:
            raise PanelAssemblyError(
                f"k{koma:02d}: 採用画像の中身が記録と違います（取り違えの恐れ）: {record_entry['image']}"
            )
        return path, None
    candidates = sorted((assets_dir / "comic").glob(f"{page_stem}_k{koma:02d}_*.png"))
    if not candidates:
        raise PanelAssemblyError(f"k{koma:02d}: コマ画像がありません（comic/{page_stem}_k{koma:02d}_*.png）")
    if len(candidates) == 1:
        return candidates[0], None
    return candidates[-1], f"k{koma:02d}: 候補が{len(candidates)}枚あるので最新を使います（{candidates[-1].name}）"


def parse_focus_args(values: list[str]) -> dict[tuple[str, int], tuple[float, float]]:
    """--focus manga_01_p04:1=0.5,0.2 を {(ページ, panel_id): (x, y)} に。"""
    out: dict[tuple[str, int], tuple[float, float]] = {}
    for raw in values:
        try:
            target, point = raw.split("=", 1)
            page_stem, panel_id = target.rsplit(":", 1)
            fx, fy = (float(v) for v in point.split(","))
        except ValueError as exc:
            raise ValueError(f"--focus の形は ページ:panel_id=X,Y です（例: manga_01_p04:1=0.5,0.2）: {raw}") from exc
        if not (0.0 <= fx <= 1.0 and 0.0 <= fy <= 1.0):
            raise ValueError(f"--focus の X,Y は 0〜1 です: {raw}")
        out[(page_stem.strip(), int(panel_id))] = (fx, fy)
    return out


def lettering_font_px(dpi: int, font_mm: float) -> int:
    """印刷の寸法（mm）の文字の大きさを、キャンバスの画素に。3.5mm・200dpi → 28px。"""
    return max(12, round(font_mm / 25.4 * dpi))


def resolve_font(cli_font: Path | None) -> Path | None:
    if cli_font is not None:
        return cli_font if cli_font.is_file() else None
    env = os.environ.get(FONT_ENV, "").strip()
    if env:
        return Path(env) if Path(env).is_file() else None
    for candidate in DEFAULT_FONT_CANDIDATES:
        if candidate.is_file():
            return candidate
    return None


def collect_texts(model: MangaPagePrompt) -> list[dict[str, Any]]:
    """ページの台詞を読み順（コマ順）で集める。"""
    texts: list[dict[str, Any]] = []
    for panel in model.panels:
        for kind in ("dialogue", "narration", "monologue", "sfx"):
            for index, item in enumerate(getattr(panel.text, kind), start=1):
                content = str(getattr(item, "content", item) or "").strip()
                if not content:
                    continue
                texts.append(
                    {
                        "text_id": assigned_text_id(item, panel_id=panel.panel_id, kind=kind, index=index),
                        "panel_id": int(panel.panel_id),
                        "kind": kind,
                        "speaker": getattr(item, "speaker", None),
                        "content": content,
                        # 台詞の bubble_type（自由記述）。「叫び」の描き分けに使う
                        "bubble_hint": str(getattr(item, "bubble_type", "") or ""),
                    }
                )
    return texts


def load_bubbles(page_path: Path, page: dict) -> tuple[list[dict[str, Any]] | None, str | None]:
    """.bubbles.yaml を読み、ページとの対応を確かめる。戻り値は（フキダシ, 警告）。

    台詞と1対1で対応しない、または下書きのあとで台詞・枠が変わっている（source.page_digest が違う）ときは
    BubbleGeometryError で止める。古い位置のまま写植が欠けた PSD を作らないため。
    source の無い設計（手書き）は対応だけを確かめ、警告を返す。
    """
    sidecar = page_path.with_name(f"{page_path.stem}.bubbles.yaml")
    if not sidecar.is_file():
        return None, None
    data = yaml.safe_load(sidecar.read_text(encoding="utf-8")) or {}
    document = load_bubble_design(data)
    redraft = "（下書きを作り直すときは novel_manga_bubbles_draft.py --apply --overwrite）"
    try:
        check_bubbles_match_page(page, document)
    except BubbleGeometryError as exc:
        raise BubbleGeometryError(f"{sidecar.name} がページの台詞と対応しません: {exc}{redraft}") from exc
    warning = None
    if document.source is None:
        warning = f"{sidecar.name} に更新元（source）が無いため、台詞・枠の変更は確かめられません（対応のみ確認）"
    elif document.source.page_digest != bubble_source_digest(page):
        raise BubbleGeometryError(f"{sidecar.name} を作ったあとで、ページの台詞か枠が変わっています{redraft}")
    return [bubble.model_dump() for bubble in document.bubbles], warning


def bubble_names(bubbles: list[dict[str, Any]]) -> dict[str, str]:
    """text_id → 「フキダシ n」「効果音 n」（.bubbles.yaml の並び順＝読み順）。"""
    names: dict[str, str] = {}
    counters = {"bubble": 0, "sfx": 0}
    for bubble in bubbles:
        key = "sfx" if bubble["bubble_type"] == "sfx" else "bubble"
        counters[key] += 1
        names[bubble["text_id"]] = f"{'効果音' if key == 'sfx' else 'フキダシ'} {counters[key]}"
    return names


def _to_px(rect: dict[str, float], size: tuple[int, int]) -> tuple[int, int, int, int]:
    return (
        round(rect["x"] * size[0]),
        round(rect["y"] * size[1]),
        round((rect["x"] + rect["width"]) * size[0]),
        round((rect["y"] + rect["height"]) * size[1]),
    )


def text_box(bubble: dict[str, Any], size: tuple[int, int]) -> tuple[int, int, int, int]:
    """文字を置く範囲。.bubbles.yaml の text_rect は幅 1024px 前後のページ画像向けで狭いので、
    フキダシの枠に対して TEXT_RATIO（楕円 75%・四角 84%。下書き bubble_draft と同じ比）まで広げる。
    text_rect の方が広いときはそちらを使う。"""
    left, top, right, bottom = _to_px(bubble["frame_rect"], size)
    width, height = right - left, bottom - top
    if bubble["bubble_type"] == "sfx":
        return _to_px(bubble["text_rect"], size)
    ratio_w = ratio_h = TEXT_RATIO[bubble["bubble_type"]]
    cx, cy = (left + right) / 2, (top + bottom) / 2
    inner = (
        round(cx - width * ratio_w / 2),
        round(cy - height * ratio_h / 2),
        round(cx + width * ratio_w / 2),
        round(cy + height * ratio_h / 2),
    )
    given = _to_px(bubble["text_rect"], size)
    area = lambda box: (box[2] - box[0]) * (box[3] - box[1])  # noqa: E731
    return inner if area(inner) >= area(given) else given


def balloon_style(bubble_type: str, hint: str) -> str:
    """.bubbles.yaml の bubble_type と台詞の bubble_type（自由記述）から、描き方を決める（BALLOON_STYLES）。"""
    if bubble_type == "speech" and any(word in hint.lower() for word in SHOUT_HINTS):
        return "shout"
    return bubble_type


def build_lettering(
    page: dict,
    texts: list[dict[str, Any]],
    bubbles: list[dict[str, Any]],
    size: tuple[int, int],
    font: Path,
    font_size: int,
    line_width: int,
) -> tuple[list[LetteringItem], list[str]]:
    """フキダシ1つにつき、フキダシの画像と文字の画像を作る。文字は既存の写植 letter_page で描く。"""
    names = bubble_names(bubbles)
    by_id = {text["text_id"]: text for text in texts}
    items: list[LetteringItem] = []
    warnings: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        blank = Path(tmp) / "blank.png"
        Image.new("RGB", size, (255, 255, 255)).save(blank)
        blank_sha = sha256_file(blank)
        for bubble in bubbles:
            text_id = bubble["text_id"]
            name = names[text_id]
            text = by_id.get(text_id)
            if text is None:
                warnings.append(f"{name}: text_id {text_id} の台詞がページにありません")
                continue
            tail = (bubble.get("tail") or {}).get("points")
            tail_px = [(round(x * size[0]), round(y * size[1])) for x, y in tail] if tail else None
            style = balloon_style(bubble["bubble_type"], text.get("bubble_hint", ""))
            balloon = balloon_image(size, style, _to_px(bubble["frame_rect"], size), tail_px, line_width)
            geometry = {
                "kind": "actual",
                "source_sha256": blank_sha,
                "texts": [{"text_id": text_id, "rect_px": list(text_box(bubble, size))}],
            }
            # 1列（横書きなら1行）に収まる大きさを、基準の大きさから 75% まで順に試す。
            # どれも1列に収まらないときは、基準の大きさで折り返した結果を使う（写植は目安なので止めない）
            chosen: Path | None = None
            first_fit: Path | None = None
            for step, ratio in enumerate(SINGLE_LINE_SIZE_STEPS):
                size_px = max(12, round(font_size * ratio))
                out = Path(tmp) / f"{text_id}_{step}.png"
                try:
                    result = letter_page(page, blank, out, font_path=font, geometry=geometry, font_size=size_px)
                except PageEditError as exc:
                    warnings.append(f"{name}: 写植できません: {exc}")
                    break
                placed = [item for item in result["placed"] if item["text_id"] == text_id]
                if not placed:
                    continue
                if first_fit is None:
                    first_fit = out
                box = placed[0]["box_px"]
                span = (box[2] - box[0]) if placed[0]["writing_direction"] == "vertical" else (box[3] - box[1])
                if span <= size_px * 1.6:
                    chosen = out
                    break
            chosen = chosen or first_fit
            text_layer = None
            if chosen is not None:
                with Image.open(chosen) as inked:
                    text_layer = ink_to_layer(inked)
            else:
                warnings.append(f"{name}: 文字がフキダシの文字枠に収まりません（{text['content']}）")
            items.append(LetteringItem(name=name, balloon=balloon, text=text_layer, text_label=text["content"]))
    return items, warnings


def lettering_text(page_rel: str, texts: list[dict[str, Any]], names: dict[str, str]) -> str:
    """クリップスタジオ等で打ち直すための台詞の一覧。"""
    lines = [
        f"# 写植の台詞一覧: {page_rel}",
        "# PSD の写植は画像の目安です。縦書きの文字はクリップスタジオ / Photoshop で打ち直してください。",
        "# 番号は PSD の「写植」グループの番号と同じです。",
        "",
    ]

    def header(text: dict[str, Any]) -> str:
        parts = [f"コマ {text['panel_id']}", KIND_LABELS.get(text["kind"], text["kind"])]
        if text.get("speaker"):
            parts.append(str(text["speaker"]))
        return "・".join(parts)

    placed = [t for t in texts if t["text_id"] in names]
    placed.sort(key=lambda t: list(names).index(t["text_id"]))
    for text in placed:
        lines += [f"{names[text['text_id']]}（{header(text)}）", text["content"], ""]
    rest = [t for t in texts if t["text_id"] not in names]
    if rest:
        lines += ["# フキダシの設計位置（.bubbles.yaml）が無い台詞", ""]
        for text in rest:
            lines += [f"（{header(text)}）", text["content"], ""]
    return "\n".join(lines).rstrip() + "\n"


def unique_run_dir(base: Path, stamp: str) -> Path:
    candidate = base / stamp
    index = 2
    while candidate.exists():
        candidate = base / f"{stamp}_{index}"
        index += 1
    return candidate


def render_name_reference(page: dict, size: tuple[int, int]) -> Image.Image:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "name.png"
        render_name_image(page, out, numbered=True, canvas_size=size)
        with Image.open(out) as image:
            return image.convert("RGB")


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

    try:
        focus_args = parse_focus_args(args.focus)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    size = canvas_size(args.dpi)
    run_stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    old_dirs: dict[Path, Path] = {}
    line_width = frame_line_width(args.dpi)
    print(f"キャンバス: B5 {B5_MM[0]}×{B5_MM[1]}mm・{args.dpi}dpi → {size[0]}×{size[1]} px（枠線 {line_width}px）")
    planned = skipped = errors = 0
    for path in pages:
        label = path.name
        try:
            chapter = chapter_of(path)
            page = load_yaml(path)
            MangaPagePrompt.model_validate(page)
        except Exception as exc:  # noqa: BLE001 - report and continue
            print(f"[エラー] {label}: 読み込み・検証に失敗しました: {exc}")
            errors += 1
            continue
        if (page.get("meta") or {}).get("intent") != "manga_page":
            print(f"[対象外] {label}: 漫画ページではありません")
            skipped += 1
            continue
        geometry = (page.get("layout_geometry") or {}).get("panels") or []
        if not geometry:
            print(f"[対象外] {label}: layout_geometry がありません（novel_manga_layout_apply.py で起こしてください）")
            skipped += 1
            continue

        assets_dir = path.parents[1] / "_assets" / chapter
        out_dir = assets_dir / "assembled"
        psd_path = out_dir / f"{path.stem}_assembled.psd"
        png_path = out_dir / f"{path.stem}_assembled.png"
        record_path = out_dir / f"{path.stem}_assembly.json"
        if (psd_path.exists() or png_path.exists()) and not args.overwrite:
            print(f"[既存] {label}: {psd_path.name} / {png_path.name} があるため触りません（置き換えるときは --overwrite）")
            skipped += 1
            continue

        previous = load_record(record_path)
        record = {} if args.reselect else previous
        entries = {int(item.get("koma")): item for item in record.get("panels") or [] if "koma" in item}
        previous_entries = {int(item.get("koma")): item for item in previous.get("panels") or [] if "koma" in item}
        panels: list[PanelInput] = []
        warnings: list[str] = []
        try:
            for koma, item in enumerate(geometry, start=1):
                image_path, warning = resolve_panel_image(assets_dir, path.stem, koma, entries.get(koma))
                if warning:
                    warnings.append(warning)
                panel_id = int(item["panel_id"])
                focus = focus_args.get((path.stem, panel_id))
                if focus is None and entries.get(koma, {}).get("focus"):
                    focus = tuple(entries[koma]["focus"])
                if (
                    focus is None
                    and args.reselect
                    and previous_entries.get(koma, {}).get("focus")
                    and previous_entries[koma].get("image") != image_path.relative_to(assets_dir).as_posix()
                ):
                    warnings.append(f"k{koma:02d}: 画像を選び直したので、前の見せる位置（focus）は外しました")
                panels.append(
                    PanelInput(
                        image_path=image_path,
                        frame=frame_px(item["rect"], size),
                        label=f"コマ {item['panel_id']}",
                        focus=focus,
                    )
                )
            placements = plan_placements(panels)
        except (PanelAssemblyError, OSError) as exc:
            print(f"[エラー] {label}: {exc}")
            errors += 1
            continue

        print(f"[計画] {label}: {len(panels)}コマ → {out_dir.relative_to(novel_dir).as_posix()}/")
        for warning in warnings:
            print(f"       警告: {warning}")
        for koma, (panel, place, item) in enumerate(zip(panels, placements, geometry), start=1):
            left, top, right, bottom = panel.frame
            fw, fh = right - left, bottom - top
            focus_note = f"  見せる位置 {panel.focus[0]:.2f},{panel.focus[1]:.2f}" if panel.focus else ""
            print(
                f"       panel {item['panel_id']}（k{koma:02d}）: {panel.image_path.name} "
                f"{place.source_size[0]}×{place.source_size[1]} → 枠 {fw}×{fh}（比 {fw / fh:.2f}） "
                f"倍率 {place.scale:.2f}  はみ出し 横{place.width - fw}px 縦{place.height - fh}px{focus_note}"
            )
            if place.scale > args.max_scale:
                message = (
                    f"panel {item['panel_id']}（k{koma:02d}）: 拡大率 {place.scale:.2f} が {args.max_scale:g} を超えています"
                    f"（実質 約{args.dpi / place.scale:.0f}dpi。画像を大きく作るか、拡大は GraphAssist 側で）"
                )
                warnings.append(message)
                print(f"       警告: {message}")
        model = MangaPagePrompt.model_validate(page)
        texts = collect_texts(model)
        text_mode = model.render_instruction.text_mode
        lettering_txt_path = out_dir / f"{path.stem}_lettering.txt"
        bubbles: list[dict[str, Any]] | None = None
        font = None
        font_size = lettering_font_px(args.dpi, args.font_mm)
        make_lettering = bool(texts) and text_mode != "none" and not args.no_lettering
        if make_lettering:
            try:
                bubbles, bubble_warning = load_bubbles(path, page)
            except Exception as exc:  # noqa: BLE001
                print(f"[エラー] {label}: .bubbles.yaml を使えません: {exc}")
                errors += 1
                continue
            if bubble_warning:
                print(f"       警告: {bubble_warning}")
                warnings.append(bubble_warning)
            font = resolve_font(args.font)
            if bubbles is None:
                print(f"       写植: {len(texts)} 件の台詞。.bubbles.yaml が無いので画像は作らず、一覧だけ書き出します")
            elif font is None:
                print("       警告: 写植のフォントが見つからないので画像は作らず、一覧だけ書き出します（--font で指定）")
                warnings.append("写植のフォントが見つからない")
            else:
                print(f"       写植: フキダシ {len(bubbles)} 件・台詞 {len(texts)} 件・{font.name}・{font_size}px（画像の目安）")
        elif texts and text_mode == "none":
            print("       写植: 作りません（text_mode: none）")
        planned += 1
        if not args.apply:
            continue

        lettering_items: list[LetteringItem] = []
        if make_lettering and bubbles is not None and font is not None:
            lettering_items, lettering_warnings = build_lettering(
                page, texts, bubbles, size, font, font_size, max(2, line_width - 2)
            )
            for message in lettering_warnings:
                print(f"       警告: {message}")
            warnings.extend(lettering_warnings)
        # 4つのファイルを作業用フォルダにすべて書いてから、一式で置き換える。
        # 置き換えの途中で失敗したら、新しいファイルを消して前の版を元に戻す
        if out_dir not in old_dirs:
            old_dirs[out_dir] = unique_run_dir(out_dir / "old", run_stamp)
        moves: list[tuple[Path, Path]] = []
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(dir=out_dir, prefix=".staging_") as staging_name:
                staging = Path(staging_name)
                name_ref = None if args.no_name_ref else render_name_reference(page, size)
                result = write_assembly(
                    size,
                    panels,
                    psd_path=staging / psd_path.name,
                    png_path=staging / png_path.name,
                    frame_width=line_width,
                    name_reference=name_ref,
                    lettering=lettering_items or None,
                    dpi=args.dpi,
                )
                new_record = {
                    "record_version": RECORD_VERSION,
                    "page": path.relative_to(novel_dir).as_posix(),
                    "canvas": {"paper": "B5", "dpi": args.dpi, "size": list(size)},
                    "panels": [
                        {
                            "koma": koma,
                            "panel_id": item["panel_id"],
                            "image": panel.image_path.relative_to(assets_dir).as_posix(),
                            "sha256": sha256_file(panel.image_path),
                            "source_size": list(place.source_size),
                            "frame_px": list(panel.frame),
                            "placement": {
                                "left": place.left,
                                "top": place.top,
                                "width": place.width,
                                "height": place.height,
                                "scale": round(place.scale, 6),
                            },
                            **({"focus": [round(panel.focus[0], 4), round(panel.focus[1], 4)]} if panel.focus else {}),
                        }
                        for koma, (panel, place, item) in enumerate(zip(panels, result.placements, geometry), start=1)
                    ],
                    "outputs": {"psd": psd_path.name, "png": png_path.name},
                    "lettering": (
                        {
                            "items": len(lettering_items),
                            "font": font.name if font else None,
                            "font_size": font_size,
                            "text": lettering_txt_path.name,
                        }
                        if make_lettering
                        else None
                    ),
                    "warnings": warnings,
                }
                staged_txt: Path | None = None
                if make_lettering:
                    names = bubble_names(bubbles) if bubbles else {}
                    staged_txt = staging / lettering_txt_path.name
                    staged_txt.write_text(
                        lettering_text(path.relative_to(novel_dir).as_posix(), texts, names), encoding="utf-8"
                    )
                    new_record["outputs"]["lettering"] = lettering_txt_path.name
                staged_record = staging / record_path.name
                staged_record.write_text(json.dumps(new_record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                # 新しい版に台詞の一覧が無いときも、前の版の一覧は退避する（古い一覧を残さない）
                moves = replace_together(
                    [
                        (staging / psd_path.name, psd_path),
                        (staging / png_path.name, png_path),
                        (staged_record, record_path),
                        (staged_txt, lettering_txt_path),
                    ],
                    keep_dir=old_dirs[out_dir],
                )
        except (PanelAssemblyError, OSError) as exc:
            print(f"[エラー] {label}: 書き出せませんでした（前の版はそのまま残しています）: {exc}")
            errors += 1
            continue
        if moves:
            print(f"       前の版を退避しました: {old_dirs[out_dir].relative_to(novel_dir).as_posix()}/")
        written = [psd_path.name, png_path.name, record_path.name] + ([lettering_txt_path.name] if make_lettering else [])
        print(f"       書き出しました: {' / '.join(written)}")

    mode = "書き出し" if args.apply else "計画のみ（--apply で書き出し）"
    print(f"\n{mode}: 対象 {planned} / 対象外・既存 {skipped} / エラー {errors}")
    return 1 if errors else 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="コマ画像をネームの枠に収めた PSD と PNG を書き出す（既定は計画の表示のみ）",
    )
    p.add_argument("novel_dir", help="novels/<NNN_タイトル>/ のパス")
    p.add_argument("--apply", action="store_true", help="PSD・PNG・採用画像の記録を書き出す")
    p.add_argument("--overwrite", action="store_true", help="既にある PSD / PNG を置き換える")
    p.add_argument("--manga-stem", default=None, help="対象の章（例: manga_01）")
    p.add_argument("--page", action="append", default=[], help="対象ページ YAML（作品フォルダからの相対パス可、複数可）")
    p.add_argument("--dpi", type=int, default=DEFAULT_DPI, help="キャンバスの解像度（既定 200。B5）")
    p.add_argument("--no-name-ref", action="store_true", help="非表示のネーム（参考）レイヤーを入れない")
    p.add_argument(
        "--focus",
        action="append",
        default=[],
        help="見せたい点（ページ:panel_id=X,Y。例: manga_01_p04:1=0.5,0.2）。記録に残り次回も使われる",
    )
    p.add_argument("--max-scale", type=float, default=1.5, help="拡大率の警告のしきい値（既定 1.5）")
    p.add_argument("--font", type=Path, default=None, help=f"写植のフォント（既定: {FONT_ENV} か 游ゴシック Medium など）")
    p.add_argument("--no-lettering", action="store_true", help="写植と台詞の一覧を作らない")
    p.add_argument(
        "--font-mm", type=float, default=FONT_MM_DEFAULT, help="写植の文字の大きさ（mm。既定 3.5 ≒ 14級。200dpi で 28px）"
    )
    p.add_argument(
        "--reselect",
        action="store_true",
        help="採用画像の記録を使わず、各コマの最新の画像を選び直す（コマを作り直したあとに使う）",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.dpi < 50 or args.dpi > 600:
        print("--dpi は 50〜600 で指定してください", file=sys.stderr)
        return 2
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
