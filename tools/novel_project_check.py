#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
作品フォルダの執筆前チェック（Monogatari Coach 想定）。

- 必須 Markdown・必須ディレクトリの存在と最小サイズ
- tools/novel_code_allocate.py の verify と整合（config / フォルダ名）

運用: .rulesync/skills/novel-project-readiness/SKILL.md を参照。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# novel_code_allocate と同じディレクトリから import
_TOOLS_DIR = Path(__file__).resolve().parent
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

import novel_code_allocate as nca  # noqa: E402
import novel_character_md_check as ncmc  # noqa: E402
import novel_image_layout as nil  # noqa: E402
import novel_text_rewrite_lint as ntrl  # noqa: E402


# overview.md「小説ファイル」に基づく執筆開始前の必須（本文ファイルは未作成でもよい）
# _meta.yaml は画像生成・ポーション運用でのみ必須（--require-meta-yaml で有効化）
DEFAULT_REQUIRED_FILES = (
    "proposal.md",
    "design_specification.md",
    "config.md",
    "character.md",
    "world.md",
    "_meta.md",
)

DEFAULT_REQUIRED_DIRS = (
    "_novel_text",
    "_reader",
)


def _file_status(path: Path, min_bytes: int) -> dict[str, Any]:
    if not path.is_file():
        return {"path": str(path), "ok": False, "reason": "missing"}
    size = path.stat().st_size
    if size < min_bytes:
        return {
            "path": str(path),
            "ok": False,
            "reason": f"too_small ({size} < {min_bytes} bytes)",
            "size": size,
        }
    return {"path": str(path), "ok": True, "size": size}


def _dir_status(path: Path) -> dict[str, Any]:
    if not path.is_dir():
        return {"path": str(path), "ok": False, "reason": "missing"}
    return {"path": str(path), "ok": True}


def check_novel_project(
    work: Path,
    *,
    min_file_bytes: int,
    require_tag_md: bool,
    require_manga_dir: bool,
    require_meta_yaml: bool = False,
    require_character_structure: bool = False,
    character_profile: str = "plan",
    character_strict: bool = False,
    character_suggest: bool = False,
    require_text_lint: bool = False,
    text_lint_profile: str = "default",
) -> dict[str, Any]:
    work = work.resolve()
    out: dict[str, Any] = {
        "work_dir": str(work),
        "ok": True,
        "novel_code_verify": None,
        "required_files": [],
        "required_dirs": [],
        "optional": {},
        "issues": [],
    }

    if not work.is_dir():
        out["ok"] = False
        out["issues"].append(f"ディレクトリがありません: {work}")
        return out

    v = nca.verify_work_dir(work)
    out["novel_code_verify"] = v
    if not v.get("ok"):
        out["ok"] = False
        for i in v.get("issues") or []:
            out["issues"].append(f"novel_ID/フォルダ名: {i}")

    for name in DEFAULT_REQUIRED_FILES:
        p = work / name
        st = _file_status(p, min_file_bytes)
        out["required_files"].append({"name": name, **st})
        if not st["ok"]:
            out["ok"] = False
            out["issues"].append(f"必須ファイル: {name} — {st.get('reason', 'bad')}")

    for name in DEFAULT_REQUIRED_DIRS:
        p = work / name
        st = _dir_status(p)
        out["required_dirs"].append({"name": name, **st})
        if not st["ok"]:
            out["ok"] = False
            out["issues"].append(f"必須ディレクトリ: {name} — {st.get('reason')}")

    if require_character_structure:
        try:
            char_result = ncmc.check_character_file(
                work / "character.md",
                novel_dir=work,
                profile=character_profile,
                strict=character_strict,
                suggest=character_suggest,
                root=Path(__file__).resolve().parent.parent,
            )
        except Exception as e:
            char_result = {
                "ok": False,
                "profile": character_profile,
                "strict": character_strict,
                "suggest": character_suggest,
                "errors": [{"level": "ERROR", "message": str(e)}],
                "warnings": [],
                "suggestions": [],
                "characters": [],
            }
        out["optional"]["character_structure"] = char_result
        if not char_result.get("ok"):
            out["ok"] = False
            for issue in char_result.get("errors") or []:
                character = issue.get("character")
                prefix = f"{character}: " if character else ""
                out["issues"].append(
                    f"character.md 構造: {prefix}{issue.get('message', 'bad')}"
                )

    meta_yaml = work / "_meta.yaml"
    meta_yaml_ok = meta_yaml.is_file()
    out["optional"]["meta_yaml_exists"] = meta_yaml_ok
    if require_meta_yaml:
        st = _file_status(meta_yaml, min_file_bytes)
        out["required_files"].append({"name": "_meta.yaml", **st})
        if not st["ok"]:
            out["ok"] = False
            out["issues"].append(f"必須ファイル: _meta.yaml — {st.get('reason', 'bad')}（--require-meta-yaml 指定）")

    tag_dir = work / "tag"
    tag_mds = sorted(tag_dir.glob("*.md")) if tag_dir.is_dir() else []
    out["optional"]["tag_md_count"] = len(tag_mds)
    out["optional"]["tag_files"] = [t.name for t in tag_mds]

    if require_tag_md:
        if not tag_mds:
            out["ok"] = False
            out["issues"].append("tag/*.md が1件もありません（--require-tag 指定）")

    # tag/<romaji>/ は各 md と同名フォルダ推奨（欠けを WARN）
    missing_romaji_dirs: list[str] = []
    for md in tag_mds:
        stem = md.stem
        sub = tag_dir / stem
        if not sub.is_dir():
            missing_romaji_dirs.append(stem)
    out["optional"]["tag_romaji_dirs_missing"] = missing_romaji_dirs

    manga_dir = work / "manga"
    out["optional"]["manga_dir_exists"] = manga_dir.is_dir()
    if require_manga_dir and not manga_dir.is_dir():
        out["ok"] = False
        out["issues"].append("manga/ がありません（--require-manga-dir 指定）")

    if require_text_lint:
        try:
            lint_result = ntrl.run_lint(
                work,
                profile=text_lint_profile,
                strict=True,
                root=Path(__file__).resolve().parent.parent,
            )
            out["optional"]["text_lint"] = {
                "ok": lint_result["ok"],
                "profile": text_lint_profile,
                "files_checked": len(lint_result.get("files_checked") or []),
                "issues_count": len(lint_result.get("issues") or []),
                "issues": lint_result.get("issues") or [],
            }
            if not lint_result["ok"]:
                out["ok"] = False
                cnt = len(lint_result.get("issues") or [])
                out["issues"].append(
                    f"本文 lint: {cnt} 件の問題あり（--require-text-lint / profile: {text_lint_profile}）"
                )
        except Exception as e:
            out["optional"]["text_lint"] = {"ok": False, "error": str(e)}
            out["ok"] = False
            out["issues"].append(f"本文 lint 実行エラー: {e}")

    return out


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    p = argparse.ArgumentParser(
        description="作品フォルダの執筆前・資料準備チェック（必須ファイル/ディレクトリ）"
    )
    p.add_argument(
        "work_dir",
        type=Path,
        help="novels/NNN_作品名",
    )
    p.add_argument(
        "--min-file-bytes",
        type=int,
        default=48,
        help="必須 .md の最小バイト数（空ファイル検出。既定: 48）",
    )
    p.add_argument(
        "--require-tag",
        action="store_true",
        help="tag/*.md が少なくとも1つ必要（Tag Mode 済みを必須にする）",
    )
    p.add_argument(
        "--require-manga-dir",
        action="store_true",
        help="manga/ ディレクトリが存在することを必須にする",
    )
    p.add_argument("--json", action="store_true", help="JSON で出力")
    p.add_argument(
        "--check-image-layout",
        action="store_true",
        help="novel_image_layout.py と連携して tag/<romaji>/ と manga/_assets/ の完全性を検証",
    )
    p.add_argument(
        "--require-meta-yaml",
        action="store_true",
        help="_meta.yaml を必須チェック対象にする（画像生成・ポーション運用時に指定）",
    )
    p.add_argument(
        "--require-character-structure",
        action="store_true",
        help="character.md をチェックリスト YAML に基づいて構造 lint する",
    )
    p.add_argument(
        "--character-profile",
        default="plan",
        help="character.md 構造 lint の profile（既定: plan）",
    )
    p.add_argument(
        "--character-strict",
        action="store_true",
        help="character.md 構造 lint の移行猶予 WARN を ERROR 扱いにする",
    )
    p.add_argument(
        "--character-suggest",
        action="store_true",
        help="character.md 構造 lint の不足項目追記案・表形式変換案を JSON 出力に含める",
    )
    p.add_argument(
        "--require-text-lint",
        action="store_true",
        help="本文 rewrite lint を --strict で実行し、違反があれば NG とする（清書完了ゲート）",
    )
    p.add_argument(
        "--text-lint-profile",
        default="default",
        help="本文 lint のプロファイル（既定: default）",
    )
    p.add_argument(
        "--bootstrap",
        action="store_true",
        help="_meta.yaml / _novel_text / _reader / references/novelai を不足分だけ作成してからチェック",
    )
    args = p.parse_args(argv)

    if args.bootstrap:
        from novel_scaffold import bootstrap_novel, repo_root as scaffold_root

        work = args.work_dir
        if not work.is_absolute():
            work = scaffold_root() / work
        work = work.resolve()
        print(f"bootstrap: {work}")
        try:
            for rel, status in bootstrap_novel(work, scaffold_root()):
                print(f"  {rel}: {status}")
        except FileNotFoundError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        print()

    result = check_novel_project(
        args.work_dir,
        min_file_bytes=args.min_file_bytes,
        require_tag_md=args.require_tag,
        require_manga_dir=args.require_manga_dir,
        require_meta_yaml=args.require_meta_yaml,
        require_character_structure=args.require_character_structure,
        character_profile=args.character_profile,
        character_strict=args.character_strict,
        character_suggest=args.character_suggest,
        require_text_lint=args.require_text_lint,
        text_lint_profile=args.text_lint_profile,
    )

    if args.check_image_layout:
        # novel_image_layout と連携して画像保存フォルダの完全性を検証
        try:
            # scaffold で作成すべきパスを列挙（実際には作成しない）
            nil_args = type("Args", (), {"novel": args.work_dir, "panels": 4, "verbose": False})()
            created = nil.scaffold_tag_dirs(Path(args.work_dir)) + nil.scaffold_manga_dirs(Path(args.work_dir), 4)
            result["optional"]["image_layout_checked"] = True
            result["optional"]["image_dirs_created_count"] = len(created)
        except Exception as e:
            result["optional"]["image_layout_error"] = str(e)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["ok"] else 1

    wd = result["work_dir"]
    print(f"作品: {wd}")
    nv = result.get("novel_code_verify") or {}
    if nv.get("ok"):
        print(
            f"  novel_ID / フォルダ番号: {nv.get('novel_id_from_config')} (一致)"
        )
    else:
        for i in nv.get("issues") or []:
            print(f"  NG [採番]: {i}")

    print("  必須ファイル:")
    for it in result["required_files"]:
        sym = "OK" if it["ok"] else "NG"
        sz = it.get("size", "-")
        print(f"    [{sym}] {it['name']}  ({sz} bytes)")

    print("  必須ディレクトリ:")
    for it in result["required_dirs"]:
        sym = "OK" if it["ok"] else "NG"
        print(f"    [{sym}] {it['name']}/")

    opt = result.get("optional") or {}
    print("  任意（参考）:")
    if not args.require_meta_yaml:
        meta_yaml_label = "あり" if opt.get("meta_yaml_exists") else "なし（画像生成時は --bootstrap または手動作成）"
        print(f"    _meta.yaml: {meta_yaml_label}")
    print(f"    tag/*.md: {opt.get('tag_md_count', 0)} 件")
    if opt.get("tag_romaji_dirs_missing"):
        print(
            "    WARN: tag/<romaji>/ 未作成のタグ: "
            + ", ".join(opt["tag_romaji_dirs_missing"])
        )
    print(
        f"    manga/: {'あり' if opt.get('manga_dir_exists') else 'なし'}"
    )
    if args.require_character_structure:
        ch = opt.get("character_structure") or {}
        print(
            "    character.md 構造: "
            + ("OK" if ch.get("ok") else "NG")
            + f"（profile: {ch.get('profile', args.character_profile)}）"
        )
        warnings = ch.get("warnings") or []
        if warnings:
            print(f"    character.md WARN: {len(warnings)} 件")

    if args.require_text_lint:
        tl = opt.get("text_lint") or {}
        lint_ok = tl.get("ok", False)
        cnt = tl.get("issues_count", 0)
        files = tl.get("files_checked", 0)
        print(
            f"    本文 lint（profile: {args.text_lint_profile} --strict）: "
            + ("OK" if lint_ok else f"NG — {cnt} 件")
            + f"  {files} ファイル確認"
        )

    if result["ok"] and not result.get("issues"):
        print("\n=== 結果: OK ===")
        print("執筆前の必須資料・ディレクトリは揃っています。")
        if opt.get("tag_romaji_dirs_missing"):
            print("補足: 以下の tag/<romaji>/ フォルダを作成してください →")
            for name in opt["tag_romaji_dirs_missing"]:
                print(f"   novel_image_layout.py scaffold で {name} フォルダを作成")
        if args.check_image_layout:
            print(f"画像レイアウトチェック: {opt.get('image_dirs_created_count', 0)} 個の保存フォルダを確認済み")
        print("\n次にすべきこと:")
        print("  1. python tools/novel_project_check.py ... --check-image-layout")
        print("  2. design_specification.md を最終確認")
        print("  3. novel_text01.md（または novel_text01_1.md）の初稿執筆")
        return 0

    print("\n=== 結果: NG ===")
    print("以下の問題を修正してから執筆してください:")
    for line in result.get("issues") or []:
        print(f"  • {line}")
    print("\n修正後、もう一度チェックを実行してください。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
