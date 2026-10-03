#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
漫画ページ YAML に、コマ割りの型（data/panel_layout_templates.yaml）から layout_geometry を起こす。

各コマの weight（無ければ beat_type の既定の重み）から、最も重いコマが最大の枠になる型に絞り、
直前のページと同じ型を避けて、シード固定で1つ選ぶ。選んだ型は manga.layout_template_id に残し、
manga.panel_layout と各コマの composition.layout / layout_en も型の文章に書き換える。
最も重いコマを最大の枠に置ける型が無いページは、--allow-mismatch を付けない限り書き込まない。
--page で絞っても、章の全ページをページ番号順にたどり、直前のページの型を避ける。

使い方:
    python tools/novel_manga_layout_apply.py novels/001_タイトル [オプション]

オプション:
    （既定）         提案を表示するだけで YAML を書き換えない
    --apply          YAML に layout_geometry と manga.layout_template_id を書き込む
    --overwrite      既に layout_geometry があるページも置き換える（既定は触らない）
    --manga-stem S   対象を manga_01 などの章に絞る
    --page PATH      対象ページを指定（複数可）
    --seed N         抽選のシード（既定 0。同じシード・同じ入力なら同じ型）
    --name-dir DIR   提案の番号付きネーム画像を DIR に書き出す（--apply 時は画像の書き出しに成功したページだけ YAML を書く）
    --allow-mismatch 最も重いコマを最大の枠に置けないページにも型を当てる
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

import yaml

_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from manga_prompt_ir.layout_templates import (  # noqa: E402
    LayoutTemplateError,
    apply_layout_choice,
    choose_layout_template,
)
from manga_prompt_ir.name_renderer import render_name_image  # noqa: E402
from manga_prompt_ir.schemas.manga_page import MangaPagePrompt  # noqa: E402

_PAGE_RE = re.compile(r"^(?P<stem>.+)_p(?P<num>\d+)\.ya?ml$")


def load_yaml(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"YAML ルートがマッピングではありません: {path}")
    return data


def dump_yaml(data: dict) -> str:
    return yaml.dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False, width=120)


def discover_pages(novel_dir: Path, stem: str | None) -> list[Path]:
    pages_dir = novel_dir / "manga" / "pages"
    found = []
    for path in pages_dir.glob("*.y*ml"):
        match = _PAGE_RE.match(path.name)
        if not match or path.name.endswith(".bubbles.yaml"):
            continue
        if stem and match.group("stem") != stem:
            continue
        found.append(path)
    return sorted(found, key=_page_sort_key)


def resolve_targets(novel_dir: Path, stem: str | None, explicit: list[str]) -> tuple[list[Path], set[Path]]:
    """章のページをページ番号順に全部返し、あわせて書き換え対象の集合を返す。

    --page で絞っても、直前のページの型を避けるために章の全ページをたどる（対象外は履歴に読むだけ）。
    """
    if not explicit:
        pages = discover_pages(novel_dir, stem)
        return pages, {path.resolve() for path in pages}
    targets = {
        (Path(item) if Path(item).is_absolute() else novel_dir / item).resolve() for item in explicit
    }
    missing = [str(path) for path in targets if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"指定したページがありません: {', '.join(sorted(missing))}")
    chapters = {_chapter(path) for path in targets}
    pages = [path for path in discover_pages(novel_dir, None) if _chapter(path) in chapters]
    outside = targets - {path.resolve() for path in pages}
    if outside:
        raise FileNotFoundError(
            "manga/pages/ の manga_XX_pYY.yaml 以外は指定できません: " + ", ".join(sorted(map(str, outside)))
        )
    return pages, targets


def _page_sort_key(path: Path) -> tuple[str, int, str]:
    match = _PAGE_RE.match(path.name)
    if not match:
        return (path.name, 0, path.name)
    return (match.group("stem"), int(match.group("num")), path.name)


def _chapter(path: Path) -> str:
    match = _PAGE_RE.match(path.name)
    return match.group("stem") if match else path.stem


def _format_rect(rect: dict[str, Any]) -> str:
    return f"x={rect['x']:.3f} y={rect['y']:.3f} w={rect['w']:.3f} h={rect['h']:.3f}"


def _existing_template_id(path: Path) -> str:
    try:
        data = load_yaml(path)
    except Exception:  # noqa: BLE001 - 履歴に読めないページは型なし扱い
        return ""
    manga = data.get("manga") if isinstance(data.get("manga"), dict) else {}
    return str(manga.get("layout_template_id") or "")


def run(args: argparse.Namespace) -> int:
    novel_dir = Path(args.novel_dir)
    try:
        pages, targets = resolve_targets(novel_dir, args.manga_stem, args.page)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if not pages:
        print("対象の漫画ページ YAML がありません。", file=sys.stderr)
        return 1

    history: dict[str, list[str]] = {}
    proposed = skipped = errors = mismatched = 0
    for path in pages:
        chapter_history = history.setdefault(_chapter(path), [])
        if path.resolve() not in targets:
            chapter_history.append(_existing_template_id(path))
            continue
        label = path.name
        try:
            data = load_yaml(path)
            MangaPagePrompt.model_validate(data)
        except Exception as exc:  # noqa: BLE001 - report and continue
            print(f"[エラー] {label}: 読み込み・検証に失敗しました: {exc}")
            chapter_history.append("")
            errors += 1
            continue

        manga = data.get("manga") if isinstance(data.get("manga"), dict) else {}
        existing_template = str(manga.get("layout_template_id") or "")
        intent = (data.get("meta") or {}).get("intent")
        if intent != "manga_page":
            print(f"[対象外] {label}: meta.intent={intent!r}（漫画ページだけを扱います）")
            chapter_history.append(existing_template)
            skipped += 1
            continue
        if str(data.get("schema_version", "1.0")) != "1.1":
            print(f"[対象外] {label}: schema 1.0 です。先に novel_manga_ir_migrate.py で 1.1 に移行してください")
            chapter_history.append(existing_template)
            skipped += 1
            continue
        if data.get("layout_geometry") is not None and not args.overwrite:
            print(f"[既存] {label}: layout_geometry があるため触りません（置き換えるときは --overwrite）")
            chapter_history.append(existing_template)
            skipped += 1
            continue

        panels = [panel for panel in data.get("panels") or [] if isinstance(panel, dict)]
        try:
            choice = choose_layout_template(
                panels,
                previous_template_ids=chapter_history[-2:],
                seed=f"{args.seed}|{path.name}",
            )
            new_data = apply_layout_choice(data, choice)
            MangaPagePrompt.model_validate(new_data)
        except LayoutTemplateError as exc:
            print(f"[対象外] {label}: {exc}")
            chapter_history.append(existing_template)
            skipped += 1
            continue
        except Exception as exc:  # noqa: BLE001
            print(f"[エラー] {label}: 提案した矩形が検証に通りません: {exc}")
            chapter_history.append(existing_template)
            errors += 1
            continue

        template = choice.template
        tag = "[不一致]" if choice.mismatch else "[提案]"
        print(
            f"{tag} {label}: {template.template_id}（{template.label_ja}） "
            f"fit={choice.fit:.2f} 重みと面積の逆転={choice.inversions}"
        )
        print(f"       候補: {', '.join(choice.candidates)}")
        print(f"       panel_layout: {template.panel_layout_ja}")
        for panel_id, weight, slot, item in zip(
            [int(panel["panel_id"]) for panel in panels],
            choice.panel_weights,
            template.slots,
            new_data["layout_geometry"]["panels"],
        ):
            print(
                f"       panel {panel_id}: weight={weight:g} → {slot.layout_ja}"
                f"（{slot.size_class}・面積={slot.area:.2f}）  {_format_rect(item['rect'])}"
            )
        if choice.mismatch:
            print(
                "       最も重いコマを最大の枠に置ける型がありません。重みを見直すか、手で矩形を書いてください"
                "（それでも当てるときは --allow-mismatch）"
            )
            mismatched += 1
            if not args.allow_mismatch:
                chapter_history.append(existing_template)
                continue
        # ネーム画像を先に作る。失敗したら YAML は書き換えず、履歴にも未保存の型を残さない。
        if args.name_dir:
            out = Path(args.name_dir) / f"{path.stem}_name_numbered.png"
            try:
                record = render_name_image(new_data, out, numbered=True)
            except Exception as exc:  # noqa: BLE001
                print(f"[エラー] {label}: ネーム画像を書き出せません（YAML は変更していません）: {exc}")
                chapter_history.append(existing_template)
                errors += 1
                continue
            print(f"       ネーム画像: {record['path']}")
        chapter_history.append(template.template_id)
        proposed += 1
        if args.apply:
            path.write_text(dump_yaml(new_data), encoding="utf-8", newline="\n")
            print(f"       書き込みました: {path}")

    mode = "書き込み" if args.apply else "提案のみ（--apply で書き込み）"
    print(f"\n{mode}: 提案 {proposed} / 不一致 {mismatched} / 対象外・既存 {skipped} / エラー {errors}")
    return 1 if errors else 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="コマ割りの型から漫画ページ YAML の layout_geometry を起こす（既定は提案のみ）",
    )
    p.add_argument("novel_dir", help="novels/<NNN_タイトル>/ のパス")
    p.add_argument("--apply", action="store_true", help="YAML に書き込む（省略時は提案の表示だけ）")
    p.add_argument("--overwrite", action="store_true", help="既存の layout_geometry も置き換える")
    p.add_argument("--manga-stem", default=None, help="対象の章（例: manga_01）")
    p.add_argument("--page", action="append", default=[], help="対象ページ YAML（作品フォルダからの相対パス可、複数可）")
    p.add_argument("--seed", default="0", help="抽選のシード（既定 0）")
    p.add_argument("--name-dir", default=None, help="番号付きネーム画像の出力先ディレクトリ")
    p.add_argument(
        "--allow-mismatch",
        action="store_true",
        help="最も重いコマを最大の枠に置ける型が無いページにも、当てはまりが最良の型を当てる",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    return run(build_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
