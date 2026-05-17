#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
_meta.md §5 漫画タグ層テーブルを読み取り、対応するページ YAML の
render_instruction.user_directives.defaults へ自動で転記する。

§5 の手動転記リスク（書き忘れ・書き間違い）を防ぐためのツール。

使い方:
    python tools/novel_manga_apply_tag_defaults.py novels/001_タイトル [オプション]

オプション:
    --dry-run     変更内容を表示するだけで YAML ファイルを書き換えない（既定）
    --apply       実際に YAML ファイルを書き換える
    --meta PATH   _meta.md のパスを直接指定（省略時は <novel_dir>/_meta.md）
    --no-note     page_notes への追記を行わない
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

import yaml


# ─────────────────────────────────────────
# YAML ユーティリティ
# ─────────────────────────────────────────

def load_yaml(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError(f"YAML ルートがマッピングではありません: {path}")
    return data


def dump_yaml(data: dict) -> str:
    return yaml.dump(
        data,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
        width=120,
    )


# ─────────────────────────────────────────
# _meta.md §5 パーサー
# ─────────────────────────────────────────

def parse_tag_defaults_table(meta_text: str) -> list[dict]:
    """§5 漫画タグ層のテーブル行を解析して返す。

    戻り値の各要素:
        range_str  : "manga_01_p01–p04" のような区間文字列
        source     : 本文参照（例: "novel_text01 浴室"）
        required   : ["steam", "bathroom", ...]
        omit       : ["outdoor", "sky", ...]
        memo       : メモ文字列
    """
    # §5 見出しを探す
    heading_pattern = re.compile(
        r"###\s*漫画タグ層[（(]区間[・・]?常時上乗せ[）)]?",
        re.MULTILINE,
    )
    m = heading_pattern.search(meta_text)
    if not m:
        return []

    # 見出し以降のテキストからテーブルを抽出
    after_heading = meta_text[m.end():]

    # Markdown テーブル行を収集（`|` で始まり `|` で終わる行）
    table_lines = []
    in_table = False
    for line in after_heading.splitlines():
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|"):
            in_table = True
            table_lines.append(stripped)
        elif in_table and stripped == "":
            break  # 空行でテーブル終了
        elif in_table and not stripped.startswith("|"):
            break  # テーブル以外の行でテーブル終了

    if not table_lines:
        return []

    # ヘッダ行・区切り行を除いてデータ行だけを取り出す
    data_rows = []
    for line in table_lines:
        cells = [c.strip() for c in line.strip("|").split("|")]
        # 区切り行（`---` だけのセルが多い）はスキップ
        if all(re.match(r"^-+$", c) or c == "" for c in cells):
            continue
        # ヘッダ行: 「区間」という文字があればスキップ
        if cells and cells[0] in ("区間", ""):
            continue
        data_rows.append(cells)

    results = []
    for cells in data_rows:
        # カラム: 区間 | 本文参照 | required | omit | メモ
        # 列数が足りない行は補完
        while len(cells) < 5:
            cells.append("")

        range_str = cells[0].strip()
        source = cells[1].strip()
        required_raw = cells[2].strip()
        omit_raw = cells[3].strip()
        memo = cells[4].strip()

        if not range_str:
            continue

        required = _parse_tag_list(required_raw)
        omit = _parse_tag_list(omit_raw)

        results.append(
            {
                "range_str": range_str,
                "source": source,
                "required": required,
                "omit": omit,
                "memo": memo,
            }
        )

    return results


def _parse_tag_list(raw: str) -> list[str]:
    """カンマ区切りのタグ文字列をリストに変換する。"""
    if not raw:
        return []
    tags = [t.strip() for t in raw.split(",")]
    return [t for t in tags if t]


# ─────────────────────────────────────────
# 区間文字列 → ページ YAML パス解決
# ─────────────────────────────────────────

# 範囲区切りとして使われる文字（em dash、en dash、半角ハイフン）
_RANGE_SEP = re.compile(r"[–—-]")


def resolve_page_yamls(range_str: str, pages_dir: Path) -> list[Path]:
    """区間文字列から対応する YAML ファイルパスのリストを返す。

    対応例:
        "manga_01_p01–p04"  → manga_01_p01.yaml, manga_01_p02.yaml, ...
        "manga_01_1_p01–p03" → manga_01_1_p01.yaml, ...
        "manga_01_p05"      → manga_01_p05.yaml のみ
    """
    # ページ番号範囲の区切りがあるか調べる
    parts = _RANGE_SEP.split(range_str, maxsplit=1)

    if len(parts) == 1:
        # 単一ページ
        stem = range_str.strip()
        p = pages_dir / f"{stem}.yaml"
        return [p] if p.exists() else []

    start_str, end_str = parts[0].strip(), parts[1].strip()

    # ステムとページ番号を分離する
    # 例: "manga_01_p01" → stem="manga_01", page_num="01"
    page_num_pattern = re.compile(r"^(.+?)_p(\d+)$")

    m_start = page_num_pattern.match(start_str)
    if not m_start:
        return []

    stem = m_start.group(1)
    start_num = int(m_start.group(2))

    # 終端の end_str は "p04" か "04" か "manga_01_p04" など
    m_end_full = page_num_pattern.match(end_str)
    if m_end_full:
        end_num = int(m_end_full.group(2))
    else:
        # "p04" 形式
        m_end_short = re.match(r"^p(\d+)$", end_str)
        if m_end_short:
            end_num = int(m_end_short.group(1))
        else:
            # 純粋な数字
            try:
                end_num = int(end_str)
            except ValueError:
                return []

    paths = []
    for num in range(start_num, end_num + 1):
        page_id = f"{stem}_p{num:02d}"
        p = pages_dir / f"{page_id}.yaml"
        if p.exists():
            paths.append(p)

    return paths


# ─────────────────────────────────────────
# YAML 更新ロジック
# ─────────────────────────────────────────

def build_note_text(entry: dict) -> str:
    """page_notes に追記するトラッキング文字列を生成する。"""
    parts = [f"_meta §5: {entry['range_str']}"]
    if entry["memo"]:
        parts.append(entry["memo"])
    return " ".join(parts)


def apply_defaults_to_yaml(
    data: dict,
    entry: dict,
    *,
    add_note: bool = True,
) -> tuple[dict, list[str]]:
    """YAML データに §5 のタグ層設定を適用する。

    変更点のリスト（人間向けの説明）を第2要素として返す。
    """
    changes: list[str] = []

    # render_instruction が無ければ作る
    if "render_instruction" not in data:
        data["render_instruction"] = {}
        changes.append("render_instruction キーを新規作成")

    ri = data["render_instruction"]

    # user_directives が無ければ作る
    if "user_directives" not in ri:
        ri["user_directives"] = {}
        changes.append("user_directives キーを新規作成")

    ud = ri["user_directives"]

    # page_notes が無ければ作る
    if "page_notes" not in ud:
        ud["page_notes"] = []

    note_text = build_note_text(entry)

    if add_note:
        # 重複チェック: 同じ区間の note がすでに入っているか
        note_key = f"_meta §5: {entry['range_str']}"
        already_noted = any(note_key in n for n in ud["page_notes"])
        if not already_noted:
            ud["page_notes"].append(note_text)
            changes.append(f"page_notes に追記: {note_text!r}")
        else:
            changes.append(f"page_notes は既存（スキップ）: {note_key!r}")

    # defaults が無ければ作る
    if "defaults" not in ud:
        ud["defaults"] = {}
        changes.append("defaults キーを新規作成")

    defaults = ud["defaults"]

    # required_prompt_tags を上書き（既存との差分を報告）
    old_required = defaults.get("required_prompt_tags", [])
    new_required = entry["required"]
    if sorted(old_required) != sorted(new_required):
        defaults["required_prompt_tags"] = new_required
        changes.append(
            f"required_prompt_tags: {old_required} → {new_required}"
        )
    else:
        changes.append(f"required_prompt_tags: 変更なし {new_required}")

    # omit_prompt_tags を上書き
    old_omit = defaults.get("omit_prompt_tags", [])
    new_omit = entry["omit"]
    if sorted(old_omit) != sorted(new_omit):
        defaults["omit_prompt_tags"] = new_omit
        changes.append(
            f"omit_prompt_tags: {old_omit} → {new_omit}"
        )
    else:
        changes.append(f"omit_prompt_tags: 変更なし {new_omit}")

    return data, changes


# ─────────────────────────────────────────
# メインロジック
# ─────────────────────────────────────────

def run(args: argparse.Namespace) -> int:
    novel_dir = Path(args.novel_dir).resolve()
    if not novel_dir.is_dir():
        print(f"[ERROR] ディレクトリが見つかりません: {novel_dir}", file=sys.stderr)
        return 1

    meta_path = Path(args.meta) if args.meta else novel_dir / "_meta.md"
    if not meta_path.exists():
        print(f"[ERROR] _meta.md が見つかりません: {meta_path}", file=sys.stderr)
        return 1

    pages_dir = novel_dir / "manga" / "pages"
    if not pages_dir.is_dir():
        print(f"[ERROR] manga/pages/ ディレクトリが見つかりません: {pages_dir}", file=sys.stderr)
        return 1

    meta_text = meta_path.read_text(encoding="utf-8")
    entries = parse_tag_defaults_table(meta_text)

    if not entries:
        print("§5 漫画タグ層テーブルが見つかりませんでした。_meta.md を確認してください。")
        return 0

    print(f"§5 テーブル: {len(entries)} 行を読み込みました。")
    print()

    dry_run = not args.apply
    if dry_run:
        print("── DRY RUN モード（--apply を付けると実際に書き換えます）──")
        print()

    total_yaml_count = 0
    total_change_count = 0

    for entry in entries:
        range_str = entry["range_str"]
        yaml_paths = resolve_page_yamls(range_str, pages_dir)

        if not yaml_paths:
            print(f"[WARN] 区間 {range_str!r} に対応する YAML が見つかりません。")
            continue

        print(f"区間: {range_str}  ({len(yaml_paths)} ファイル)")
        if entry["required"]:
            print(f"  required: {', '.join(entry['required'])}")
        if entry["omit"]:
            print(f"  omit:     {', '.join(entry['omit'])}")

        for yaml_path in yaml_paths:
            data = load_yaml(yaml_path)
            updated_data, changes = apply_defaults_to_yaml(
                data,
                entry,
                add_note=not args.no_note,
            )

            real_changes = [c for c in changes if "変更なし" not in c and "スキップ" not in c]
            total_yaml_count += 1
            total_change_count += len(real_changes)

            rel_path = yaml_path.relative_to(novel_dir)
            if real_changes:
                print(f"  {'(dry)' if dry_run else '更新'} {rel_path}")
                for c in real_changes:
                    print(f"    • {c}")
                if not dry_run:
                    yaml_path.write_text(dump_yaml(updated_data), encoding="utf-8")
            else:
                print(f"  スキップ（変更なし）: {rel_path}")

        print()

    print(f"── 完了: {total_yaml_count} ファイル確認、実質変更 {total_change_count} 件 ──")

    if dry_run and total_change_count > 0:
        print("  （実際に書き換えるには --apply を追加してください）")

    return 0


# ─────────────────────────────────────────
# CLI
# ─────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="_meta.md §5 漫画タグ層を manga/pages/*.yaml へ自動転記する",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
例:
  # 変更内容を確認するだけ（書き換えない）
  python tools/novel_manga_apply_tag_defaults.py novels/001_タイトル

  # 実際に書き換える
  python tools/novel_manga_apply_tag_defaults.py novels/001_タイトル --apply

  # _meta.md のパスを直接指定
  python tools/novel_manga_apply_tag_defaults.py novels/001_タイトル --meta path/to/_meta.md --apply

  # page_notes への追記を省略する
  python tools/novel_manga_apply_tag_defaults.py novels/001_タイトル --apply --no-note
""",
    )
    p.add_argument("novel_dir", help="novels/<NNN_タイトル>/ のパス")
    p.add_argument(
        "--apply",
        action="store_true",
        default=False,
        help="実際に YAML を書き換える（省略時は dry-run）",
    )
    p.add_argument(
        "--meta",
        default=None,
        metavar="PATH",
        help="_meta.md のパス（省略時は <novel_dir>/_meta.md）",
    )
    p.add_argument(
        "--no-note",
        action="store_true",
        default=False,
        help="page_notes への '_meta §5:' 追記を行わない",
    )
    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    sys.exit(run(args))


if __name__ == "__main__":
    main()
