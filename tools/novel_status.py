#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""作品ダッシュボード: 作品の状態を1コマンドで確認する（読み取り専用）。

Usage:
    python tools/novel_status.py novels/066_作品名
    python tools/novel_status.py novels/066_作品名 --validate
    python tools/novel_status.py novels/066_作品名 --next
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from novel_meta_yaml import find_meta_yaml_path, load_meta_yaml  # noqa: E402
from novel_char_count import collect_targets, count_chars  # noqa: E402

_W = 52  # 区切り線の幅


def _bar(char: str = "─") -> str:
    return char * _W


def _section(title: str) -> None:
    print(f"\n  {title}")
    print(f"  {'─' * (_W - 2)}")


def _row(label: str, value: str) -> None:
    print(f"  {label:<26}{value}")


# ── プロジェクトチェック ─────────────────────────────────────────────


def _run_subprocess(cmd: list) -> tuple[str, str, int]:
    """subprocess を実行し (stdout, stderr, returncode) を UTF-8 文字列で返す。"""
    result = subprocess.run(cmd, capture_output=True)
    def _decode(b: bytes | None) -> str:
        if not b:
            return ""
        for enc in ("utf-8", "cp932", "latin-1"):
            try:
                return b.decode(enc)
            except UnicodeDecodeError:
                continue
        return b.decode("utf-8", errors="replace")
    return _decode(result.stdout), _decode(result.stderr), result.returncode


def _run_project_check(work_dir: Path) -> dict:
    stdout, stderr, _ = _run_subprocess([
        sys.executable,
        str(_TOOLS_DIR / "novel_project_check.py"),
        str(work_dir),
        "--json",
    ])
    try:
        return json.loads(stdout)
    except Exception:
        return {"ok": False, "issues": [stderr.strip() or "不明なエラー"]}


# ── 文字数 ───────────────────────────────────────────────────────────


def _get_char_counts(work_dir: Path) -> list[tuple[str, int]]:
    repo_root = _TOOLS_DIR.parent
    targets = collect_targets([work_dir], repo_root)
    rows = []
    for path in targets:
        text = path.read_text(encoding="utf-8")
        count = count_chars(text, strip_fm=True)
        rows.append((path.name, count))
    return rows


# ── 漫画 YAML ────────────────────────────────────────────────────────


def _get_manga_yaml_count(work_dir: Path) -> int:
    pages_dir = work_dir / "manga" / "pages"
    if not pages_dir.is_dir():
        return 0
    return len(list(pages_dir.glob("*.yaml")))


def _run_validate(work_dir: Path) -> tuple[bool, str]:
    stdout, stderr, returncode = _run_subprocess([
        sys.executable,
        str(_TOOLS_DIR / "novel_prompt_ir_validate.py"),
        str(work_dir),
    ])
    ok = returncode == 0
    summary = (stdout + stderr).strip().splitlines()
    last = summary[-1] if summary else "(出力なし)"
    return ok, last


def _get_latest_image_timestamp(work_dir: Path) -> str:
    assets_dir = work_dir / "manga" / "_assets"
    if not assets_dir.is_dir():
        return "なし"
    images = []
    for ext in ("*.png", "*.jpg", "*.webp"):
        images.extend(assets_dir.rglob(ext))
    if not images:
        return "なし"
    latest = max(images, key=lambda p: p.stat().st_mtime)
    ts = datetime.fromtimestamp(latest.stat().st_mtime)
    return f"{ts.strftime('%Y-%m-%d %H:%M')}  ({latest.name})"


# ── _meta.yaml ───────────────────────────────────────────────────────


def _get_meta_info(work_dir: Path) -> dict:
    data = load_meta_yaml(work_dir)
    if not data:
        return {}
    novelai = data.get("novelai", {})
    return {
        "portion_default": novelai.get("portion_default"),
        "portions": list(novelai.get("portions", {}).keys()),
        "workflows": list(data.get("workflows", {}).keys()),
    }


# ── 次の一言（状態機械） ─────────────────────────────────────────────


def _is_chat_mode(work_dir: Path) -> bool:
    """_meta.md の「執筆モード」行を読んでチャットモードか判定する。"""
    meta_md = work_dir / "_meta.md"
    if not meta_md.is_file():
        return False
    try:
        content = meta_md.read_text(encoding="utf-8")
        return "チャットモード" in content
    except Exception:
        return False


def _has_images(work_dir: Path) -> bool:
    assets_dir = work_dir / "manga" / "_assets"
    if not assets_dir.is_dir():
        return False
    for ext in ("*.png", "*.jpg", "*.webp"):
        if any(assets_dir.rglob(ext)):
            return True
    return False


def determine_next_step(work_dir: Path) -> tuple[str, str]:
    """ファイルシステムの状態から次のステップを判定する。

    Returns:
        (ラベル, チャットに貼り付ける一言 または CLI コマンド)
    """
    is_chat = _is_chat_mode(work_dir)

    # 1. 本文の有無
    novel_text_dir = work_dir / "_novel_text"
    text_files = (
        sorted(novel_text_dir.glob("novel_text*.md"))
        if novel_text_dir.is_dir()
        else []
    )
    has_text = any(f.stat().st_size > 100 for f in text_files)

    if not has_text:
        if is_chat:
            return ("チャットモード開始", "チャットモードで Phase 0 から始めてください")
        return ("Plan Mode", "企画書を作成してください（proposal.md から）")

    # 2. キャラクタータグ YAML の有無
    tag_chars_dir = work_dir / "tag" / "characters"
    has_char_yaml = tag_chars_dir.is_dir() and bool(
        list(tag_chars_dir.glob("*.yaml"))
    )

    if not has_char_yaml:
        return ("Tag Mode", "キャラクタータグを作成してください")

    # 3. 漫画ページ YAML の有無
    manga_pages_dir = work_dir / "manga" / "pages"
    manga_yaml_files = (
        list(manga_pages_dir.glob("*.yaml")) if manga_pages_dir.is_dir() else []
    )
    has_manga_ir = bool(manga_yaml_files)
    manga_dir_exists = (work_dir / "manga").is_dir()

    if not has_manga_ir:
        if manga_dir_exists:
            return ("Manga Tag Mode", "漫画タグを作成してください")
        if is_chat:
            return ("次のセグメント執筆", "次のセグメントを執筆してください")
        return ("執筆", "本文の執筆を続けてください")

    # 4. 生成画像の有無
    if not _has_images(work_dir):
        rel = str(work_dir).replace("\\", "/")
        return (
            "画像生成 (dry-run)",
            f"python tools/image_provider_novel_manga_batch.py {rel}"
            " --source step1-panels --dry-run",
        )

    # 5. 画像あり → 次の執筆へ
    if is_chat:
        return ("次のセグメント執筆", "次のセグメントを執筆してください")
    return ("執筆・清書", "本文の清書または次の章の執筆をしてください")


# ── メイン出力 ────────────────────────────────────────────────────────


def main() -> int:
    from console_io import configure_stdio_utf8

    configure_stdio_utf8()

    parser = argparse.ArgumentParser(
        description="作品ダッシュボード（読み取り専用）"
    )
    parser.add_argument("work_dir", help="novels/NNN_作品名")
    parser.add_argument(
        "--validate",
        action="store_true",
        help="漫画 IR の検証（novel_prompt_ir_validate.py）を実行して結果を表示",
    )
    parser.add_argument(
        "--next",
        action="store_true",
        help="次の一言だけを出力して終了（スクリプト連携・手軽な確認向け）",
    )
    args = parser.parse_args()

    work_dir = Path(args.work_dir)
    if not work_dir.is_dir():
        print(f"ERROR: {work_dir} が見つかりません", file=sys.stderr)
        return 1

    # --next: 次の一言だけ出力して終了
    if args.next:
        label, suggestion = determine_next_step(work_dir)
        print(f"[{label}]")
        print(suggestion)
        return 0

    print(f"\n  {'═' * _W}")
    print(f"  {work_dir.name}")
    print(f"  {'═' * _W}")

    # ── プロジェクト状態
    _section("プロジェクト状態")
    check = _run_project_check(work_dir)
    mark = "OK" if check.get("ok") else "NG"
    print(f"  [{mark}]", end="")
    if check.get("ok"):
        print("  必須ファイル・ディレクトリが揃っています")
    else:
        print()
        for issue in check.get("issues", []):
            print(f"       ! {issue}")
        for f in check.get("required_files", []):
            if not f.get("ok"):
                print(f"       ! 不足: {f['name']}")
        for d in check.get("required_dirs", []):
            if not d.get("ok"):
                print(f"       ! 不足: {d['name']}/")

    # ── 本文文字数
    _section("本文文字数")
    char_rows = _get_char_counts(work_dir)
    if char_rows:
        total = 0
        for name, count in char_rows:
            _row(name, f"{count:>7,} 字")
            total += count
        if len(char_rows) > 1:
            print(f"  {'─' * 38}")
            _row("合計", f"{total:>7,} 字  ({len(char_rows)} ファイル)")
        else:
            print(f"  {'─' * 38}")
            _row("合計", f"{total:>7,} 字  ({len(char_rows)} ファイル)")
    else:
        print("  _novel_text/ に本文ファイルがありません")

    # ── 漫画ページ IR
    _section("漫画ページ IR")
    manga_count = _get_manga_yaml_count(work_dir)
    _row("manga/pages/*.yaml", f"{manga_count} 件")
    if args.validate and manga_count > 0:
        ok, msg = _run_validate(work_dir)
        mark_v = "OK" if ok else "NG"
        _row("IR 検証", f"[{mark_v}]  {msg[:40]}")
    elif manga_count > 0:
        print("         (検証するには --validate を付けてください)")
    _row("最新生成画像", _get_latest_image_timestamp(work_dir))

    # ── _meta.yaml
    _section("_meta.yaml")
    meta_path = find_meta_yaml_path(work_dir)
    if meta_path:
        info = _get_meta_info(work_dir)
        _row("portion_default", info.get("portion_default") or "(未設定)")
        portions = info.get("portions", [])
        _row("portions", ", ".join(portions) if portions else "(なし)")
        workflows = info.get("workflows", [])
        _row("workflows", ", ".join(workflows) if workflows else "(未登録)")
    else:
        print("  _meta.yaml が見つかりません")

    # ── 次の一言
    _section("次の一言")
    label, suggestion = determine_next_step(work_dir)
    print(f"  [{label}]")
    print(f"  → {suggestion}")

    print(f"\n  {'═' * _W}\n")

    return 0 if check.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
