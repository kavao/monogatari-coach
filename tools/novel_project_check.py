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
import re
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


_RE_SLUSH_SCORE = re.compile(r"(?<!\d)(\d{1,3})\s*/\s*100(?!\d)")
_RE_SLUSH_G3_STATUS = re.compile(r"足切りステータス[:：]\s*G3合格")
_RE_SLUSH_PASS = re.compile(r"読むべき")
_NEW_READER_PAT = re.compile(r"^\d{8}_\d{4}\.md$")


def _check_slush_g3(work: Path) -> dict[str, Any]:
    """G3 足切り通過確認。_meta.md または最新 _reader/*.md を参照する。"""
    # 1. _meta.md の 足切りステータス: G3合格 を確認
    meta = work / "_meta.md"
    if meta.is_file():
        try:
            text = meta.read_text(encoding="utf-8", errors="replace")
            if _RE_SLUSH_G3_STATUS.search(text):
                return {"ok": True, "source": "_meta.md", "detail": "足切りステータス: G3合格"}
        except OSError:
            pass

    # 2. _reader/ の最新 YYYYMMDD_HHMM.md を確認
    reader_dir = work / "_reader"
    if not reader_dir.is_dir():
        return {"ok": False, "source": None, "detail": "_reader/ が存在しない"}

    candidates = sorted(
        [f for f in reader_dir.glob("*.md") if _NEW_READER_PAT.match(f.name)],
        reverse=True,
    )
    if not candidates:
        return {"ok": False, "source": None, "detail": "_reader/YYYYMMDD_HHMM.md が存在しない"}

    for f in candidates[:3]:  # 最新3件を確認
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        scores = [int(m.group(1)) for m in _RE_SLUSH_SCORE.finditer(text) if int(m.group(1)) <= 100]
        score = max(scores) if scores else None
        passed = bool(_RE_SLUSH_PASS.search(text))
        if score is not None and score >= 55 and passed:
            return {
                "ok": True,
                "source": f.name,
                "detail": f"判定: 読むべき / スコア: {score} / 100",
            }

    latest = candidates[0].name
    return {
        "ok": False,
        "source": latest,
        "detail": "G3 足切り通過の記録なし（スコア ≥ 55 かつ「読むべき」の _reader/*.md が見つからない）",
    }


_RE_NOVEL_TEXT = re.compile(r"^novel_text(\d+)(?:_(\d+))?\.md$")
_RE_SCHEDULE_HEADING = re.compile(r"^#{1,6}\s*.*執筆スケジュール")
_RE_SCHEDULE_LINE = re.compile(r"第(\d+)章[^：:\n]*[：:]\s*(.+?)\s*$")
_RE_SUBPART_KEYWORD = re.compile(r"(前半|後半|項|分割|_1|_2|_3)")
_STATUS_NOT_STARTED = ("未着手", "未定", "予定")


def _novel_text_files(work: Path) -> list[Path]:
    text_dir = work / "_novel_text"
    if not text_dir.is_dir():
        return []
    return sorted(f for f in text_dir.glob("novel_text*.md") if _RE_NOVEL_TEXT.match(f.name))


def _written_chapter_map(files: list[Path]) -> dict[int, list[int | None]]:
    """章番号 → 項番号（項なしは None）のリスト。"""
    out: dict[int, list[int | None]] = {}
    for f in files:
        m = _RE_NOVEL_TEXT.match(f.name)
        if not m:
            continue
        chapter = int(m.group(1))
        sub = int(m.group(2)) if m.group(2) else None
        out.setdefault(chapter, []).append(sub)
    return out


def _parse_schedule(design_text: str) -> dict[int, str]:
    """design_specification.md の「執筆スケジュール」節から 章番号→状態文字列 を抽出。"""
    lines = design_text.splitlines()
    in_schedule = False
    schedule: dict[int, str] = {}
    for line in lines:
        if _RE_SCHEDULE_HEADING.search(line):
            in_schedule = True
            continue
        if in_schedule:
            # 次の見出しでスケジュール節を抜ける
            if re.match(r"^#{1,6}\s", line):
                break
            m = _RE_SCHEDULE_LINE.search(line)
            if m:
                schedule[int(m.group(1))] = m.group(2).strip()
    return schedule


def _check_story_sync(work: Path) -> dict[str, Any]:
    """本文ファイルと design_specification.md 執筆スケジュールの食い違いを WARNING 検出。

    意味内容までは判定せず、章番号・ファイル存在・スケジュール表記の形式的ズレのみを見る。
    """
    warnings: list[str] = []
    files = _novel_text_files(work)
    chapters = _written_chapter_map(files)

    design = work / "design_specification.md"
    schedule: dict[int, str] = {}
    design_ok = design.is_file()
    if design_ok:
        try:
            schedule = _parse_schedule(design.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            design_ok = False

    if not files:
        return {
            "ok": True,
            "written_chapters": [],
            "schedule_chapters": sorted(schedule.keys()),
            "warnings": warnings,
            "detail": "本文ファイルがまだ無いため同期チェックはスキップ",
        }

    if not design_ok:
        warnings.append("design_specification.md が読めないため執筆スケジュールと照合できません")
        return {
            "ok": False,
            "written_chapters": sorted(chapters.keys()),
            "schedule_chapters": [],
            "warnings": warnings,
        }

    # 1. 本文があるのにスケジュールが未着手のまま
    for chapter in sorted(chapters.keys()):
        status = schedule.get(chapter)
        if status is None:
            warnings.append(
                f"第{chapter}章の本文ファイルがあるのに、執筆スケジュールに第{chapter}章の記載がありません"
            )
            continue
        if any(token in status for token in _STATUS_NOT_STARTED):
            warnings.append(
                f"第{chapter}章の本文ファイルがあるのに、執筆スケジュールが「{status}」のままです"
            )

    # 2. 前後半・項ファイルがあるのに、スケジュールに分割記載がない
    design_text_l = ""
    if design_ok:
        try:
            design_text_l = design.read_text(encoding="utf-8", errors="replace")
        except OSError:
            design_text_l = ""
    for chapter, subs in sorted(chapters.items()):
        has_sub = any(s is not None for s in subs)
        if has_sub:
            status = schedule.get(chapter, "")
            # スケジュール行または設計書全体に分割の手掛かりがあるか
            if not _RE_SUBPART_KEYWORD.search(status) and not _RE_SUBPART_KEYWORD.search(
                design_text_l
            ):
                warnings.append(
                    f"第{chapter}章は前半・後半（項）ファイルに分割されていますが、"
                    f"design_specification.md に分割の記載が見当たりません"
                )

    return {
        "ok": not warnings,
        "written_chapters": sorted(chapters.keys()),
        "schedule_chapters": sorted(schedule.keys()),
        "warnings": warnings,
    }


def _illustration_page_yaml_paths(work: Path) -> list[Path]:
    pages = work / "illustrations" / "pages"
    if not pages.is_dir():
        return []
    return sorted(pages.glob("illustration_*.yaml"))


def _needs_cover_plan(work: Path) -> bool:
    for path in _illustration_page_yaml_paths(work):
        if path.stem.startswith("illustration_00"):
            return True
    return False


def check_novel_project(
    work: Path,
    *,
    min_file_bytes: int,
    require_tag_md: bool,
    require_manga_dir: bool,
    require_meta_yaml: bool = False,
    require_illustration_plan: bool = False,
    require_character_structure: bool = True,
    character_profile: str = "plan",
    character_strict: bool = False,
    character_suggest: bool = False,
    require_text_lint: bool = False,
    text_lint_profile: str = "default",
    require_slush_g3: bool = False,
    check_story_sync: bool = False,
    strict_story_sync: bool = False,
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
        "warnings": [],
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

    ill_pages = _illustration_page_yaml_paths(work)
    out["optional"]["illustration_page_yaml_count"] = len(ill_pages)
    if require_illustration_plan:
        plans_dir = work / "illustrations" / "plans"
        chapter_plan = plans_dir / "chapter_plan.md"
        cover_plan = plans_dir / "cover_plan.md"
        cover_required = _needs_cover_plan(work)
        chapter_st = _file_status(chapter_plan, min_file_bytes)
        cover_st = _file_status(cover_plan, min_file_bytes) if cover_required else {"ok": True}
        out["optional"]["illustration_plan"] = {
            "chapter_plan_ok": chapter_st["ok"],
            "cover_plan_required": cover_required,
            "cover_plan_ok": cover_st["ok"],
        }
        out["required_files"].append({"name": "illustrations/plans/chapter_plan.md", **chapter_st})
        if not chapter_st["ok"]:
            out["ok"] = False
            out["issues"].append(
                f"必須ファイル: illustrations/plans/chapter_plan.md — "
                f"{chapter_st.get('reason', 'bad')}（--require-illustration-plan 指定）"
            )
        if cover_required:
            out["required_files"].append({"name": "illustrations/plans/cover_plan.md", **cover_st})
            if not cover_st["ok"]:
                out["ok"] = False
                out["issues"].append(
                    f"必須ファイル: illustrations/plans/cover_plan.md — "
                    f"{cover_st.get('reason', 'bad')}（表紙 YAML あり・--require-illustration-plan 指定）"
                )

    if require_slush_g3:
        g3_result = _check_slush_g3(work)
        out["optional"]["slush_g3"] = g3_result
        if not g3_result["ok"]:
            out["ok"] = False
            out["issues"].append(f"足切り G3: {g3_result['detail']}（--require-slush-g3 指定）")

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

    if check_story_sync:
        sync_result = _check_story_sync(work)
        out["optional"]["story_sync"] = sync_result
        for w in sync_result.get("warnings") or []:
            if strict_story_sync:
                out["ok"] = False
                out["issues"].append(f"本文・設計書同期: {w}（--strict-story-sync 指定）")
            else:
                out["warnings"].append(f"本文・設計書同期: {w}")

    return out


def main(argv: list[str] | None = None) -> int:
    from console_io import configure_stdio_utf8

    configure_stdio_utf8()

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
        "--require-illustration-plan",
        action="store_true",
        help=(
            "illustrations/plans/chapter_plan.md を必須にする。"
            "illustration_00*.yaml がある場合は cover_plan.md も必須"
        ),
    )
    p.add_argument(
        "--require-meta-yaml",
        action="store_true",
        help="_meta.yaml を必須チェック対象にする（画像生成・ポーション運用時に指定）",
    )
    p.add_argument(
        "--no-character-structure",
        action="store_true",
        help="character.md のチェックリスト構造 lint をスキップする（既定は実行）",
    )
    p.add_argument(
        "--require-character-structure",
        action="store_true",
        help="character.md 構造 lint を明示的に有効化（既定で有効。無効化は --no-character-structure）",
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
        "--require-slush-g3",
        action="store_true",
        help=(
            "G3 足切り通過を必須チェックにする。"
            "_meta.md の「足切りステータス: G3合格」または最新 _reader/YYYYMMDD_HHMM.md の"
            "スコア ≥ 55 かつ「読むべき」判定を確認する。"
        ),
    )
    p.add_argument(
        "--check-story-sync",
        action="store_true",
        help=(
            "本文ファイル（_novel_text/novel_text*.md）と design_specification.md の"
            "執筆スケジュール・章分割の食い違いを WARNING 表示する（既定では NG にしない）"
        ),
    )
    p.add_argument(
        "--strict-story-sync",
        action="store_true",
        help="--check-story-sync の食い違いを WARNING ではなく NG（失敗）扱いにする",
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

    require_character_structure = not args.no_character_structure
    if args.require_character_structure:
        require_character_structure = True

    result = check_novel_project(
        args.work_dir,
        min_file_bytes=args.min_file_bytes,
        require_tag_md=args.require_tag,
        require_manga_dir=args.require_manga_dir,
        require_meta_yaml=args.require_meta_yaml,
        require_illustration_plan=args.require_illustration_plan,
        require_character_structure=require_character_structure,
        character_profile=args.character_profile,
        character_strict=args.character_strict,
        character_suggest=args.character_suggest,
        require_text_lint=args.require_text_lint,
        text_lint_profile=args.text_lint_profile,
        require_slush_g3=args.require_slush_g3,
        check_story_sync=args.check_story_sync or args.strict_story_sync,
        strict_story_sync=args.strict_story_sync,
    )

    if args.check_image_layout:
        # novel_image_layout と連携して画像保存フォルダの完全性を検証
        try:
            # scaffold で作成すべきパスを列挙（実際には作成しない）
            nil_args = type("Args", (), {"novel": args.work_dir, "panels": 4, "verbose": False})()
            created = (
                nil.scaffold_tag_dirs(Path(args.work_dir))
                + nil.scaffold_manga_dirs(Path(args.work_dir), 4)
                + nil.scaffold_illustration_plans(Path(args.work_dir))
                + nil.scaffold_illustration_dirs(Path(args.work_dir))
            )
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
    ill_count = opt.get("illustration_page_yaml_count", 0)
    if ill_count:
        print(f"    illustrations/pages/*.yaml: {ill_count} 件")
    if args.require_illustration_plan:
        ip = opt.get("illustration_plan") or {}
        ch_ok = ip.get("chapter_plan_ok", False)
        print(
            "    挿絵計画 chapter_plan.md: "
            + ("OK" if ch_ok else "NG")
        )
        if ip.get("cover_plan_required"):
            cv_ok = ip.get("cover_plan_ok", False)
            print(
                "    挿絵計画 cover_plan.md: "
                + ("OK" if cv_ok else "NG")
            )
    if require_character_structure:
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

    if args.require_slush_g3:
        g3 = opt.get("slush_g3") or {}
        g3_ok = g3.get("ok", False)
        detail = g3.get("detail", "—")
        src = g3.get("source") or "—"
        print(
            f"    足切り G3: {'OK' if g3_ok else 'NG'} — {detail}  [{src}]"
        )

    if args.check_story_sync or args.strict_story_sync:
        ss = opt.get("story_sync") or {}
        written = ss.get("written_chapters") or []
        sched = ss.get("schedule_chapters") or []
        ss_warns = ss.get("warnings") or []
        print(
            "    本文・設計書同期: "
            + ("OK" if ss.get("ok") else f"要確認 — {len(ss_warns)} 件")
            + f"（本文章: {written} / スケジュール章: {sched}）"
        )
        for w in ss_warns:
            print(f"      - {w}")

    if result.get("warnings"):
        print("\n  警告（WARNING・NG ではない）:")
        for line in result["warnings"]:
            print(f"    ! {line}")

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
