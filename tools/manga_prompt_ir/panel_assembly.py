"""コマ画像を枠に収めた、レイヤー付き PSD と PNG を書き出す（純粋な層）。

作品やページ YAML を知らない。入力はキャンバスの大きさ、コマごとの画像と枠の矩形（ピクセル）だけ。
Monogatari Coach 固有のモジュール（スキーマ・_assets の命名・ルール）は import しない。
将来 GraphAssist の pip パッケージへ移す候補（計画 20260930_manga-panel-assembly-psd の C10）。

PSD の構成（下から）:
    背景（ロック）
    コマ n  ← グループ（ロックしない）
        コマnの枠（土台）  ← 枠の形の不透明レイヤー（ロック）
        コマnの画像        ← 元画像まるごと。土台にクリッピング（ロックしない）
    枠線（ロック）
    写植  ← グループ（ロックしない。渡されたときだけ）
        フキダシ n  ← フキダシ1つにつき1グループ（効果音は「効果音 n」）
            フキダシ nの文字  ← 上
            フキダシ nの画像  ← 下（効果音には無い）
    ネーム（参考）（非表示・ロック。渡されたときだけ）

psd-tools 1.22.0 で確かめた制約（計画 C3）:
- グループのマスクは読み戻せない PSD になるので使わない。枠はクリッピングで表す
- PSD を RGB モードで作ると、RGBA レイヤーの透明がユーザーマスクとして書かれ、編集ソフトで余計な
  「マスク」の子レイヤーになる。RGBA モードで作り、土台は不透明の RGB 画像にする
- 日本語のレイヤー名は name setter 経由で付ける（frompil の name= は保存で失敗する）
- Layer.lock() は新規レイヤーで値が残らないので、PROTECTED_SETTING を直接書く
"""

from __future__ import annotations

import hashlib
import math
import os
import shutil
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from PIL import Image, ImageChops, ImageDraw, ImageFilter


class PanelAssemblyError(ValueError):
    """配置や書き出しを正直に終えられないとき。"""


Box = tuple[int, int, int, int]  # left, top, right, bottom（right / bottom は含まない）


@dataclass(frozen=True)
class PanelInput:
    image_path: Path
    frame: Box
    label: str
    # 元画像の中で枠の中央に寄せたい点（0〜1、左上原点）。None なら画像の中央
    focus: tuple[float, float] | None = None


@dataclass(frozen=True)
class Placement:
    """コマ画像をキャンバス上のどこに、どの大きさで置くか（はみ出しは切らない）。"""

    left: int
    top: int
    width: int
    height: int
    scale: float
    source_size: tuple[int, int]


@dataclass
class AssemblyResult:
    psd_path: Path | None
    png_path: Path | None
    placements: list[Placement] = field(default_factory=list)


def cover_placement(
    source_size: tuple[int, int],
    frame: Box,
    focus: tuple[float, float] | None = None,
) -> Placement:
    """枠を隙間なく埋める配置。倍率は横・縦を枠に合わせる倍率の大きい方。

    focus（元画像の中の点。0〜1）を指定すると、その点が枠の中央に来るように寄せる。
    ただし枠を埋めることを優先し、白い隙間が出る位置までは動かさない。
    """
    src_w, src_h = source_size
    left, top, right, bottom = frame
    frame_w, frame_h = right - left, bottom - top
    if src_w <= 0 or src_h <= 0:
        raise PanelAssemblyError(f"画像の大きさが不正です: {source_size}")
    if frame_w <= 0 or frame_h <= 0:
        raise PanelAssemblyError(f"枠の大きさが不正です: {frame}")
    scale = max(frame_w / src_w, frame_h / src_h)
    width = max(frame_w, round(src_w * scale))
    height = max(frame_h, round(src_h * scale))
    if focus is None:
        offset_x = (frame_w - width) // 2
        offset_y = (frame_h - height) // 2
    else:
        fx, fy = focus
        if not (0.0 <= fx <= 1.0 and 0.0 <= fy <= 1.0):
            raise PanelAssemblyError(f"focus は 0〜1 で指定してください: {focus}")
        # 焦点を枠の中央へ。はみ出し量（0 以下）の範囲に収めて、枠の中に白を出さない
        offset_x = min(0, max(frame_w - width, round(frame_w / 2 - fx * width)))
        offset_y = min(0, max(frame_h - height, round(frame_h / 2 - fy * height)))
    return Placement(
        left=left + offset_x,
        top=top + offset_y,
        width=width,
        height=height,
        scale=scale,
        source_size=(src_w, src_h),
    )


def frame_line_image(canvas_size: tuple[int, int], frames: Sequence[Box], width: int) -> Image.Image:
    layer = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    for left, top, right, bottom in frames:
        draw.rectangle((left, top, right - 1, bottom - 1), outline=(0, 0, 0, 255), width=width)
    return layer


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _load_rgb(path: Path) -> Image.Image:
    with Image.open(path) as raw:
        return raw.convert("RGB")


def _check_frames(canvas_size: tuple[int, int], panels: Sequence[PanelInput]) -> None:
    width, height = canvas_size
    for panel in panels:
        left, top, right, bottom = panel.frame
        if not (0 <= left < right <= width and 0 <= top < bottom <= height):
            raise PanelAssemblyError(f"{panel.label} の枠がキャンバスの外に出ています: {panel.frame}")


def plan_placements(panels: Sequence[PanelInput]) -> list[Placement]:
    """画像を開いて実寸を測り、配置だけを計算する（書き出しはしない）。"""
    placements = []
    for panel in panels:
        with Image.open(panel.image_path) as raw:
            size = raw.size
        placements.append(cover_placement(size, panel.frame, panel.focus))
    return placements


@dataclass(frozen=True)
class LetteringItem:
    """フキダシ1つ分。画像はキャンバスと同じ大きさの RGBA（透明の外側は切り詰めて置く）。"""

    name: str
    balloon: Image.Image | None = None
    text: Image.Image | None = None
    # 文字レイヤーの名前に添える台詞（「フキダシ 1の文字：これ、見て。」）。長いときは切り詰める
    text_label: str | None = None


Lettering = Sequence[LetteringItem]


# フキダシの描き方（描画のための区分。.bubbles.yaml の bubble_type は speech / thought / narration / sfx の4つ）
BALLOON_STYLES = {
    "speech": "台詞: 楕円＋しっぽ",
    "shout": "叫び: ギザギザ＋しっぽ",
    "thought": "心の声: 楕円＋しっぽの向きに小さな丸2つ",
    "narration": "ナレーション: 四角",
    "sfx": "効果音: 枠なし",
}


def _burst_polygon(frame: Box, spikes: int = 18) -> list[tuple[int, int]]:
    left, top, right, bottom = frame
    cx, cy = (left + right) / 2, (top + bottom) / 2
    rx, ry = (right - left) / 2, (bottom - top) / 2
    points = []
    for index in range(spikes * 2):
        angle = math.pi * index / spikes
        scale = 1.0 if index % 2 == 0 else 0.82
        points.append((round(cx + rx * scale * math.cos(angle)), round(cy + ry * scale * math.sin(angle))))
    return points


def balloon_image(
    canvas_size: tuple[int, int],
    kind: str,
    frame: Box,
    tail: Sequence[tuple[int, int]] | None,
    line_width: int,
) -> Image.Image | None:
    """フキダシ1つをキャンバス大の RGBA で描く。kind は BALLOON_STYLES のいずれか。効果音（sfx）は None。

    形としっぽを合わせた外周に線を引くので、付け根に線が残らない。
    """
    if kind == "sfx":
        return None
    if kind not in BALLOON_STYLES:
        raise PanelAssemblyError(f"フキダシの描き方が不明です: {kind}（{', '.join(BALLOON_STYLES)}）")
    shape = Image.new("L", canvas_size, 0)
    draw = ImageDraw.Draw(shape)
    left, top, right, bottom = frame
    if kind == "narration":
        draw.rectangle((left, top, right - 1, bottom - 1), fill=255)
    elif kind == "shout":
        draw.polygon(_burst_polygon(frame), fill=255)
    else:
        draw.ellipse((left, top, right - 1, bottom - 1), fill=255)
    if tail and len(tail) >= 3:
        if kind in ("speech", "shout"):
            draw.polygon([tuple(point) for point in tail], fill=255)
        elif kind == "thought":
            # しっぽの先へ向かって小さくなる丸を2つ
            base_x = (tail[0][0] + tail[-1][0]) / 2
            base_y = (tail[0][1] + tail[-1][1]) / 2
            tip_x, tip_y = tail[len(tail) // 2]
            radius = max(4, round(min(right - left, bottom - top) * 0.07))
            for ratio, size in ((0.45, 1.0), (0.9, 0.6)):
                x = base_x + (tip_x - base_x) * ratio
                y = base_y + (tip_y - base_y) * ratio
                r = max(3, round(radius * size))
                draw.ellipse((round(x - r), round(y - r), round(x + r), round(y + r)), fill=255)
    grown = shape.filter(ImageFilter.MaxFilter(line_width * 2 + 1))
    outline = ImageChops.subtract(grown, shape)
    layer = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
    layer.paste((255, 255, 255, 255), (0, 0), shape)
    layer.paste((0, 0, 0, 255), (0, 0), outline)
    return layer


def ink_to_layer(image: Image.Image) -> Image.Image:
    """白地に黒で描いた画像を、黒の濃さを不透明度にした RGBA（黒一色）に変える。"""
    gray = image.convert("L")
    layer = Image.new("RGBA", gray.size, (0, 0, 0, 255))
    layer.putalpha(gray.point(lambda value: 255 - value))
    return layer


def _trimmed(layer: Image.Image) -> tuple[Image.Image, int, int] | None:
    """キャンバス大の RGBA レイヤーを中身のある範囲に切り詰める。空なら None。"""
    rgba = layer.convert("RGBA")
    bbox = rgba.getchannel("A").getbbox()
    if bbox is None:
        return None
    return rgba.crop(bbox), bbox[1], bbox[0]


def render_png(
    canvas_size: tuple[int, int],
    panels: Sequence[PanelInput],
    placements: Sequence[Placement],
    frame_width: int,
    lettering: Lettering | None = None,
) -> Image.Image:
    """PSD と同じ見た目の PNG を直接描く（非表示のレイヤーは含めない）。"""
    flat = Image.new("RGB", canvas_size, (255, 255, 255))
    for panel, place in zip(panels, placements):
        image = _load_rgb(panel.image_path).resize((place.width, place.height), Image.LANCZOS)
        left, top, right, bottom = panel.frame
        crop = image.crop((left - place.left, top - place.top, right - place.left, bottom - place.top))
        flat.paste(crop, (left, top))
    lines = frame_line_image(canvas_size, [p.frame for p in panels], frame_width)
    flat.paste(lines, (0, 0), lines)
    for item in lettering or ():
        for layer in (item.balloon, item.text):
            if layer is not None:
                rgba = layer.convert("RGBA")
                flat.paste(rgba, (0, 0), rgba)
    return flat


def replace_together(
    pairs: Sequence[tuple[Path | None, Path]],
    keep_dir: Path | None = None,
) -> list[tuple[Path, Path]]:
    """書き終えたファイル（staged）で、置き場のファイル（final）を一式で置き換える。

    staged が None の組は、置き場のファイルを退避するだけ（新しい版には無いファイル）。
    既存の final は keep_dir へ移す（None なら一時的に脇へ置き、成功したら消す）。
    途中で失敗したら、置いた新しいファイルを消し、既存のファイルを元に戻してから例外を送出する。
    戻り値は keep_dir へ移した (元, 退避先) の組。
    """
    moved: list[tuple[Path, Path]] = []
    placed: list[Path] = []
    try:
        for _staged, final in pairs:
            if not final.exists():
                continue
            if keep_dir is not None:
                keep_dir.mkdir(parents=True, exist_ok=True)
                backup = keep_dir / final.name
            else:
                backup = final.with_name(f"{final.name}.{os.getpid()}.bak")
            shutil.move(str(final), str(backup))
            moved.append((final, backup))
        for staged, final in pairs:
            if staged is None:
                continue
            final.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(staged), str(final))
            placed.append(final)
    except BaseException:
        for final in placed:
            if final.exists():
                final.unlink()
        for final, backup in moved:
            if backup.exists() and not final.exists():
                shutil.move(str(backup), str(final))
        raise
    if keep_dir is None:
        for _final, backup in moved:
            if backup.exists():
                backup.unlink()
        return []
    return moved


def write_assembly(
    canvas_size: tuple[int, int],
    panels: Sequence[PanelInput],
    *,
    psd_path: Path,
    png_path: Path,
    frame_width: int,
    name_reference: Image.Image | None = None,
    lettering: Lettering | None = None,
    dpi: int | None = None,
) -> AssemblyResult:
    """PSD と PNG を書き出す。PNG を先に作り、PSD を書いてから両方を置く。"""
    try:
        from psd_tools import PSDImage
        from psd_tools.api.layers import Group, PixelLayer
        from psd_tools.constants import ProtectedFlags, Resource, Tag
        from psd_tools.psd.image_resources import ImageResource
        from psd_tools.psd.tagged_blocks import ProtectedSetting
    except ImportError as exc:  # pragma: no cover - 依存が無い環境
        raise PanelAssemblyError(
            "PSD の書き出しには psd-tools が必要です（uv sync で入ります）"
        ) from exc

    if not panels:
        raise PanelAssemblyError("コマがありません")
    _check_frames(canvas_size, panels)
    placements = plan_placements(panels)
    lock_flags = int(ProtectedFlags.POSITION | ProtectedFlags.COMPOSITE | ProtectedFlags.TRANSPARENCY)

    def named(layer: Any, name: str) -> Any:
        layer.name = name
        return layer

    def locked(layer: Any) -> Any:
        layer.tagged_blocks.set_data(Tag.PROTECTED_SETTING, ProtectedSetting(lock_flags))
        return layer

    psd = PSDImage.new("RGBA", canvas_size, color=(255, 255, 255, 255))
    if dpi is not None:
        # 解像度（ID 1005）。無いと編集ソフトは 72dpi として扱い、印刷サイズが大きくなる。
        # 16.16 固定小数点の横・縦の解像度と、単位（1 = ピクセル／インチ、1 = インチ）
        resolution = struct.pack(">IHHIHH", int(dpi) << 16, 1, 1, int(dpi) << 16, 1, 1)
        psd.image_resources[Resource.RESOLUTION_INFO] = ImageResource(
            key=int(Resource.RESOLUTION_INFO), name="", data=resolution
        )
    locked(named(PixelLayer.frompil(Image.new("RGB", canvas_size, (255, 255, 255)), psd, name="bg"), "背景"))
    for index, (panel, place) in enumerate(zip(panels, placements), start=1):
        group = named(Group.new(psd, name=f"panel{index}"), panel.label)
        left, top, right, bottom = panel.frame
        base = Image.new("RGB", (right - left, bottom - top), (255, 255, 255))
        locked(named(PixelLayer.frompil(base, group, name="base", top=top, left=left), f"{panel.label}の枠（土台）"))
        image = _load_rgb(panel.image_path).resize((place.width, place.height), Image.LANCZOS)
        layer = named(
            PixelLayer.frompil(image, group, name="img", top=place.top, left=place.left),
            f"{panel.label}の画像",
        )
        layer.clipping = True
    lines = frame_line_image(canvas_size, [p.frame for p in panels], frame_width)
    locked(named(PixelLayer.frompil(lines, psd, name="frames"), "枠線"))
    if lettering:
        # 写植は動かす対象なのでロックしない。フキダシ1つにつき1グループで、画像が下、文字が上
        lettering_group = named(Group.new(psd, name="lettering"), "写植")
        for index, item in enumerate(lettering, start=1):
            group = named(Group.new(lettering_group, name=f"bubble{index}"), item.name)
            for layer, suffix, ascii_name in ((item.balloon, "の画像", "balloon"), (item.text, "の文字", "text")):
                if layer is None:
                    continue
                trimmed = _trimmed(layer)
                if trimmed is None:
                    continue
                image, top, left = trimmed
                layer_name = f"{item.name}{suffix}"
                if ascii_name == "text" and item.text_label:
                    label = " ".join(item.text_label.split())
                    layer_name += "：" + (label if len(label) <= 40 else label[:39] + "…")
                named(PixelLayer.frompil(image, group, name=ascii_name, top=top, left=left), layer_name)
    if name_reference is not None:
        ref = locked(named(PixelLayer.frompil(name_reference.convert("RGB"), psd, name="name"), "ネーム（参考）"))
        ref.visible = False

    png = render_png(canvas_size, panels, placements, frame_width, lettering)
    psd_path = Path(psd_path)
    png_path = Path(png_path)
    psd_path.parent.mkdir(parents=True, exist_ok=True)
    png_path.parent.mkdir(parents=True, exist_ok=True)
    # 途中で失敗して片方だけ新しくならないよう、一時ファイルに書いてから一式で置き換える
    psd_tmp = psd_path.with_suffix(psd_path.suffix + ".tmp")
    png_tmp = png_path.with_suffix(png_path.suffix + ".tmp")
    try:
        psd.save(psd_tmp)
        png.save(png_tmp, format="PNG", **({"dpi": (dpi, dpi)} if dpi is not None else {}))
        replace_together([(psd_tmp, psd_path), (png_tmp, png_path)])
    finally:
        for tmp in (psd_tmp, png_tmp):
            if tmp.exists():
                tmp.unlink()
    return AssemblyResult(psd_path=psd_path, png_path=png_path, placements=list(placements))
