#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
_novel_text/*.md の rewrite 機械 lint。

rewrite.md（§1・§9）の機械判定しやすい体裁規則を YAML 定義に基づいて検出し、
行番号付きで報告する。安全な機械置換は --fix で自動修正できる。

使い方:
    python tools/novel_text_rewrite_lint.py novels/069_成長の前兆父の手の下で
    python tools/novel_text_rewrite_lint.py novels/069_…/_novel_text/novel_text03_2.md
    python tools/novel_text_rewrite_lint.py novels/069_… --strict
    python tools/novel_text_rewrite_lint.py novels/069_… --json
    python tools/novel_text_rewrite_lint.py novels/069_… --profile minimal
    python tools/novel_text_rewrite_lint.py novels/069_… --fix
    python tools/novel_text_rewrite_lint.py novels/069_… --fix --fix-dry-run

終了コード:
    0: error なし（--strict なしなら warning のみも 0）
    1: error あり（--strict 時は warning も 1）
    2: 引数・設定ファイル不正

環境変数:
    MONOCRI_TEXT_REWRITE_RULES: ルール YAML のパスを上書き
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    print("error: PyYAML が必要です。pip install pyyaml", file=sys.stderr)
    raise


DEFAULT_RULES = Path("_how_to.example") / "novel_text_rewrite_rules.yaml"
USER_RULES = Path("_how_to") / "novel_text_rewrite_rules.yaml"
ENV_RULES = "MONOCRI_TEXT_REWRITE_RULES"
NOVEL_RULES_NAME = "novel_text_rewrite_rules.yaml"

# 安全な機械置換のみ。章メタ（A ルール）は自動修正しない。
# 各関数は「行末改行なし」の行文字列を受け取り、修正後の文字列を返す。
_ASCII_COMMA_IN_PROSE = re.compile(r"(?<![0-9A-Za-z]),")


_FIXERS: dict[str, Any] = {
    "dialogue_leading_indent": lambda line: (
        line[1:] if (line.startswith("　「") or line.startswith("　『")) else line
    ),
    "dialogue_trailing_period": lambda line: line.replace("。」", "」"),
    "ellipsis_ascii": lambda line: re.sub(r"\.{2,}", "……", line),
    "ascii_comma_in_prose": lambda line: _ASCII_COMMA_IN_PROSE.sub("、", line),
    "paragraph_indent": lambda line: "　" + line,
}
FIXABLE_RULE_IDS: frozenset[str] = frozenset(_FIXERS)


# ──────────────────────────────────────────────────────────────────────────────
# データ構造
# ──────────────────────────────────────────────────────────────────────────────


@dataclass
class Issue:
    level: str          # "error" | "warning" | "info"
    rule_id: str
    message: str
    file: str
    line: int
    matched: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "rule_id": self.rule_id,
            "file": self.file,
            "line": self.line,
            "matched": self.matched,
            "message": self.message,
        }

    def format_text(self) -> str:
        return (
            f"{self.file}:{self.line} {self.level} [{self.rule_id}]"
            f" 「{self.matched}」 — {self.message}"
        )


@dataclass
class RuleDef:
    id: str
    level: str          # "error" | "warning" | "info"
    patterns: list[re.Pattern[str]]
    message: str
    raw_patterns: list[str] = field(default_factory=list)


# ──────────────────────────────────────────────────────────────────────────────
# YAML 読み込み・マージ
# ──────────────────────────────────────────────────────────────────────────────


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"{path}: YAML ルートがオブジェクトではありません")
    return data


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in override.items():
        if key in out and isinstance(out[key], list) and isinstance(value, list):
            # リストは追記マージ（重複除去）
            seen = {json.dumps(x, ensure_ascii=False) for x in out[key]}
            out[key] = list(out[key])
            for item in value:
                k = json.dumps(item, ensure_ascii=False)
                if k not in seen:
                    out[key].append(item)
                    seen.add(k)
        elif key in out and isinstance(out[key], dict) and isinstance(value, dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def resolve_config(root: Path, novel_dir: Path | None) -> tuple[dict[str, Any], list[str]]:
    sources: list[str] = []
    env_value = os.environ.get(ENV_RULES)
    if env_value:
        base_path = Path(env_value)
        if not base_path.is_absolute():
            base_path = root / base_path
    else:
        user_path = root / USER_RULES
        base_path = user_path if user_path.is_file() else root / DEFAULT_RULES

    if not base_path.is_file():
        raise FileNotFoundError(f"ルール YAML が見つかりません: {base_path}")

    config = load_yaml(base_path)
    sources.append(str(base_path))

    if novel_dir:
        novel_rules = novel_dir / NOVEL_RULES_NAME
        if novel_rules.is_file():
            config = deep_merge(config, load_yaml(novel_rules))
            sources.append(str(novel_rules))

    return config, sources


# ──────────────────────────────────────────────────────────────────────────────
# ルール解決
# ──────────────────────────────────────────────────────────────────────────────


def _compile(pattern_str: str) -> re.Pattern[str]:
    return re.compile(pattern_str)


def build_all_rules(config: dict[str, Any]) -> dict[str, RuleDef]:
    """config から全 RuleDef を id → RuleDef で返す。"""
    all_rules: dict[str, RuleDef] = {}

    # ellipsis.forbidden → RuleDef
    ellipsis_cfg = config.get("ellipsis") or {}
    for entry in ellipsis_cfg.get("forbidden") or []:
        if not isinstance(entry, dict):
            continue
        rid = str(entry.get("id") or "")
        if not rid:
            continue
        raw = [str(entry["pattern"])] if "pattern" in entry else []
        level = str(entry.get("level") or "warning").lower()
        msg = str(entry.get("message") or "")
        compiled = [_compile(p) for p in raw]
        all_rules[rid] = RuleDef(id=rid, level=level, patterns=compiled, message=msg, raw_patterns=raw)

    # rules[] → RuleDef
    for rule in config.get("rules") or []:
        if not isinstance(rule, dict):
            continue
        rid = str(rule.get("id") or "")
        if not rid:
            continue
        raw = [str(p) for p in (rule.get("patterns") or [])]
        level = str(rule.get("level") or "warning").lower()
        msg = str(rule.get("message") or "")
        compiled = [_compile(p) for p in raw]
        all_rules[rid] = RuleDef(id=rid, level=level, patterns=compiled, message=msg, raw_patterns=raw)

    return all_rules


def resolve_profile(config: dict[str, Any], profile_name: str) -> list[str]:
    """profile_name から有効な rule_id リストを返す。"""
    profiles = config.get("profiles") or {}
    if not isinstance(profiles, dict) or profile_name not in profiles:
        known = ", ".join(sorted(profiles)) if isinstance(profiles, dict) else ""
        raise KeyError(
            f"profile が見つかりません: {profile_name}"
            + (f"（候補: {known}）" if known else "")
        )

    seen: set[str] = set()

    def collect(name: str) -> list[str]:
        if name in seen:
            raise ValueError(f"profile extends が循環しています: {name}")
        seen.add(name)
        spec = profiles.get(name)
        if not isinstance(spec, dict):
            raise ValueError(f"profiles.{name} はオブジェクトである必要があります")
        ids: list[str] = []
        extends = spec.get("extends")
        for parent in ([extends] if isinstance(extends, str) else extends or []):
            for rid in collect(str(parent)):
                if rid not in ids:
                    ids.append(rid)
        for rid in spec.get("rules") or []:
            rid = str(rid)
            if rid not in ids:
                ids.append(rid)
        seen.remove(name)
        return ids

    return collect(profile_name)


# ──────────────────────────────────────────────────────────────────────────────
# ファイル走査
# ──────────────────────────────────────────────────────────────────────────────


def should_skip_line(line: str, skip_patterns: list[re.Pattern[str]]) -> bool:
    for pat in skip_patterns:
        if pat.search(line):
            return True
    return False


def allowlist_suppresses(line: str, allowlist: list[re.Pattern[str]]) -> bool:
    """allowlist のいずれかがマッチする行は検出を免除する。"""
    for pat in allowlist:
        if pat.search(line):
            return True
    return False


_INDENT_CHAR = "　"          # 全角スペース（U+3000）
_DIALOGUE_OPEN = ("「", "『")    # インデント不要の行頭文字


def _check_paragraph_indent(
    lines: list[str],
    rule: RuleDef,
    skip_patterns: list[re.Pattern[str]],
    allowlist: list[re.Pattern[str]],
    rel_path: str,
) -> list[Issue]:
    """
    段落インデントの stateful チェック。

    ルール（rewrite.md §1）:
      - 見出し行（# で始まる）: チェック対象外
      - 「 または 『 で始まる行: インデント不要
      - skip_patterns にマッチする行（Markdown リスト・表・太字見出し等）: 非本文のためスキップ
      - それ以外の本文行（見出し直後の第1行を含む）: 全角スペース 1 字（U+3000）で始まること
    """
    issues: list[Issue] = []

    for lineno, raw_line in enumerate(lines, start=1):
        # 見出し → チェック対象外
        if re.match(r"^\s*#", raw_line):
            continue

        # 空行・front matter → スキップ
        stripped = raw_line.strip()
        if not stripped or stripped == "---":
            continue

        # skip_patterns にマッチする行（Markdown 非本文要素）→ スキップ
        if should_skip_line(raw_line, skip_patterns):
            continue

        # allowlist にマッチする行はスキップ
        if allowlist_suppresses(raw_line, allowlist):
            continue

        # 「 または 『 で直接始まる行: インデント不要（§1 の除外規定）
        if raw_line.startswith(_DIALOGUE_OPEN):
            continue

        # インデントチェック本体: 全角スペースで始まっていない
        if not raw_line.startswith(_INDENT_CHAR):
            matched = raw_line[:24] + ("…" if len(raw_line) > 24 else "")
            issues.append(
                Issue(
                    level=rule.level,
                    rule_id=rule.id,
                    message=rule.message,
                    file=rel_path,
                    line=lineno,
                    matched=matched,
                )
            )

    return issues


def lint_file(
    path: Path,
    *,
    active_rules: list[RuleDef],
    skip_patterns: list[re.Pattern[str]],
    allowlist: list[re.Pattern[str]],
    rel_path: str,
) -> list[Issue]:
    issues: list[Issue] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        return [Issue("error", "file_read", str(e), rel_path, 0)]

    lines = text.splitlines()

    # paragraph_indent は stateful なので通常の regex ループから分離する
    regex_rules = [r for r in active_rules if r.id != "paragraph_indent"]
    indent_rule = next((r for r in active_rules if r.id == "paragraph_indent"), None)

    for lineno, raw_line in enumerate(lines, start=1):
        if should_skip_line(raw_line, skip_patterns):
            continue
        if allowlist_suppresses(raw_line, allowlist):
            continue
        for rule in regex_rules:
            for pat in rule.patterns:
                m = pat.search(raw_line)
                if m:
                    issues.append(
                        Issue(
                            level=rule.level,
                            rule_id=rule.id,
                            message=rule.message,
                            file=rel_path,
                            line=lineno,
                            matched=m.group(),
                        )
                    )
                    break  # 同ルール内で1マッチあれば十分

    if indent_rule:
        issues.extend(_check_paragraph_indent(lines, indent_rule, skip_patterns, allowlist, rel_path))

    return issues


def collect_target_files(target: Path, globs: list[str], root: Path) -> list[tuple[Path, str]]:
    """走査対象 (絶対パス, 相対表示パス) のリストを返す。"""
    pairs: list[tuple[Path, str]] = []

    if target.is_file():
        rel = str(target.relative_to(root)) if target.is_absolute() else str(target)
        pairs.append((target.resolve(), rel))
        return pairs

    # ディレクトリ → glob パターンで展開
    for pattern in globs:
        for matched in sorted(target.glob(pattern)):
            if matched.is_file():
                try:
                    rel = str(matched.relative_to(root))
                except ValueError:
                    rel = str(matched)
                pairs.append((matched.resolve(), rel))

    return pairs


def fix_file(
    path: Path,
    *,
    active_rules: list[RuleDef],
    skip_patterns: list[re.Pattern[str]],
    allowlist: list[re.Pattern[str]],
    rel_path: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    """ファイルを lint し、修正可能な issue を in-place（または dry-run）で修正する。"""
    issues_before = lint_file(
        path,
        active_rules=active_rules,
        skip_patterns=skip_patterns,
        allowlist=allowlist,
        rel_path=rel_path,
    )

    fixable_by_line: dict[int, list[Issue]] = {}
    unfixable: list[Issue] = []
    for issue in issues_before:
        if issue.rule_id in FIXABLE_RULE_IDS:
            fixable_by_line.setdefault(issue.line, []).append(issue)
        else:
            unfixable.append(issue)

    if not fixable_by_line:
        return {
            "file": rel_path,
            "fixed_count": 0,
            "unfixed_issues": [i.to_dict() for i in unfixable],
            "modified": False,
            "dry_run": dry_run,
        }

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        return {
            "file": rel_path,
            "error": str(e),
            "fixed_count": 0,
            "unfixed_issues": [i.to_dict() for i in issues_before],
            "modified": False,
            "dry_run": dry_run,
        }

    lines = text.splitlines(keepends=True)
    fixed_count = 0

    for lineno, line_issues in fixable_by_line.items():
        idx = lineno - 1
        if idx < 0 or idx >= len(lines):
            continue
        raw = lines[idx]
        # 行末改行を分離して内容だけ修正
        stripped = raw.rstrip("\r\n")
        eol = raw[len(stripped):]
        content = stripped
        for issue in line_issues:
            fixer = _FIXERS.get(issue.rule_id)
            if fixer:
                content = fixer(content)
        if content != stripped:
            lines[idx] = content + eol
            fixed_count += 1

    new_text = "".join(lines)
    modified = new_text != text

    if not dry_run and modified:
        path.write_text(new_text, encoding="utf-8")

    return {
        "file": rel_path,
        "fixed_count": fixed_count,
        "unfixed_issues": [i.to_dict() for i in unfixable],
        "modified": modified,
        "dry_run": dry_run,
    }


# ──────────────────────────────────────────────────────────────────────────────
# 出力
# ──────────────────────────────────────────────────────────────────────────────


def print_text_result(result: dict[str, Any], *, verbose: bool = False) -> None:
    if verbose:
        print(f"target: {result['target']}")
        print(f"profile: {result['profile']}")
        print(f"strict: {result['strict']}")
        print("rules:")
        print(f"  config: {result.get('config_sources')}")
        print(f"  active: {result.get('active_rules')}")
        print()

    issues = result.get("issues") or []
    errors = [i for i in issues if i["level"] == "error"]
    warnings = [i for i in issues if i["level"] == "warning"]
    infos = [i for i in issues if i["level"] == "info"]

    for issue in issues:
        level_label = issue["level"].upper()
        print(
            f"{issue['file']}:{issue['line']} {level_label} [{issue['rule_id']}]"
            f" 「{issue['matched']}」 — {issue['message']}"
        )

    if issues:
        print()
    print(
        f"=== 結果: {'NG' if not result['ok'] else 'OK'}"
        f"  error={len(errors)}  warning={len(warnings)}  info={len(infos)} ==="
    )


def print_fix_summary(fix_results: list[dict[str, Any]], final_result: dict[str, Any]) -> None:
    total_fixed = sum(r.get("fixed_count", 0) for r in fix_results)
    total_modified = sum(1 for r in fix_results if r.get("modified"))
    dry_run = any(r.get("dry_run") for r in fix_results)

    label = "（dry-run）" if dry_run else ""
    for r in fix_results:
        if r.get("error"):
            print(f"  ERROR {r['file']}: {r['error']}")
        elif r.get("fixed_count", 0) > 0:
            action = "修正対象" if dry_run else "修正"
            print(f"  {action}: {r['file']}  {r['fixed_count']} 件")

    print()
    if dry_run:
        print(f"=== dry-run: {total_fixed} 件を修正できます（{total_modified} ファイル）===")
        print("実際に修正するには --fix （--fix-dry-run なし）で実行してください。")
    else:
        print(f"=== fix 完了{label}: {total_fixed} 件修正（{total_modified} ファイル更新）===")

    # 残存 issue を表示
    remaining = final_result.get("issues") or []
    if remaining:
        print()
        print(f"残存 issue: {len(remaining)} 件（--fix では自動修正できないもの、または修正後に再検出されたもの）")
        for issue in remaining:
            level_label = issue["level"].upper()
            print(
                f"  {issue['file']}:{issue['line']} {level_label} [{issue['rule_id']}]"
                f" 「{issue['matched']}」 — {issue['message']}"
            )


# ──────────────────────────────────────────────────────────────────────────────
# エントリーポイント
# ──────────────────────────────────────────────────────────────────────────────


def run_lint(
    target: Path,
    *,
    profile: str = "default",
    strict: bool = False,
    root: Path | None = None,
) -> dict[str, Any]:
    root = root or repo_root()

    # ターゲット解決
    if not target.is_absolute():
        target = (root / target).resolve()
    else:
        target = target.resolve()

    novel_dir: Path | None = None
    if target.is_dir():
        novel_dir = target
    elif target.is_file():
        # ファイルが _novel_text/ 直下なら 2 階層上が作品フォルダ
        if target.parent.name == "_novel_text":
            novel_dir = target.parent.parent

    # 設定読み込み
    config, config_sources = resolve_config(root, novel_dir)

    # デフォルト設定
    defaults = config.get("defaults") or {}
    target_globs: list[str] = [str(g) for g in (defaults.get("target_globs") or ["_novel_text/novel_text*.md"])]
    skip_raw: list[str] = [str(p) for p in (defaults.get("skip_line_patterns") or [])]
    skip_patterns = [_compile(p) for p in skip_raw]

    allowlist_raw: list[str] = [str(p) for p in (config.get("allowlist_patterns") or [])]
    allowlist = [_compile(p) for p in allowlist_raw]

    # ルール解決
    all_rules = build_all_rules(config)
    try:
        active_ids = resolve_profile(config, profile)
    except KeyError as e:
        raise KeyError(str(e)) from e

    active_rules: list[RuleDef] = []
    for rid in active_ids:
        rule = all_rules.get(rid)
        if rule is None:
            # 未定義 rule_id は警告のみ（strict_all の paragraph_indent など未実装分）
            continue
        r = RuleDef(
            id=rule.id,
            level="error" if (strict and rule.level == "warning") else rule.level,
            patterns=rule.patterns,
            message=rule.message,
            raw_patterns=rule.raw_patterns,
        )
        active_rules.append(r)

    # ファイル収集
    pairs = collect_target_files(target, target_globs, root)

    # lint 実行
    all_issues: list[Issue] = []
    for abs_path, rel in pairs:
        all_issues.extend(
            lint_file(
                abs_path,
                active_rules=active_rules,
                skip_patterns=skip_patterns,
                allowlist=allowlist,
                rel_path=rel,
            )
        )

    errors = [i for i in all_issues if i.level == "error"]
    ok = len(errors) == 0

    return {
        "ok": ok,
        "target": str(target),
        "profile": profile,
        "strict": strict,
        "config_sources": config_sources,
        "active_rules": active_ids,
        "files_checked": [rel for _, rel in pairs],
        "issues": [i.to_dict() for i in all_issues],
    }


def run_fix(
    target: Path,
    *,
    profile: str = "default",
    strict: bool = False,
    dry_run: bool = False,
    root: Path | None = None,
) -> dict[str, Any]:
    """ファイルを lint し、修正可能な issue を in-place で修正してから再 lint する。"""
    root = root or repo_root()

    if not target.is_absolute():
        target = (root / target).resolve()
    else:
        target = target.resolve()

    novel_dir: Path | None = None
    if target.is_dir():
        novel_dir = target
    elif target.is_file():
        if target.parent.name == "_novel_text":
            novel_dir = target.parent.parent

    config, config_sources = resolve_config(root, novel_dir)

    defaults = config.get("defaults") or {}
    target_globs: list[str] = [str(g) for g in (defaults.get("target_globs") or ["_novel_text/novel_text*.md"])]
    skip_raw: list[str] = [str(p) for p in (defaults.get("skip_line_patterns") or [])]
    skip_patterns = [_compile(p) for p in skip_raw]
    allowlist_raw: list[str] = [str(p) for p in (config.get("allowlist_patterns") or [])]
    allowlist = [_compile(p) for p in allowlist_raw]

    all_rules = build_all_rules(config)
    try:
        active_ids = resolve_profile(config, profile)
    except KeyError as e:
        raise KeyError(str(e)) from e

    active_rules: list[RuleDef] = []
    for rid in active_ids:
        rule = all_rules.get(rid)
        if rule is None:
            continue
        r = RuleDef(
            id=rule.id,
            level="error" if (strict and rule.level == "warning") else rule.level,
            patterns=rule.patterns,
            message=rule.message,
            raw_patterns=rule.raw_patterns,
        )
        active_rules.append(r)

    pairs = collect_target_files(target, target_globs, root)

    fix_results: list[dict[str, Any]] = []
    for abs_path, rel in pairs:
        fix_results.append(
            fix_file(
                abs_path,
                active_rules=active_rules,
                skip_patterns=skip_patterns,
                allowlist=allowlist,
                rel_path=rel,
                dry_run=dry_run,
            )
        )

    # 修正後の lint（dry_run の場合は元ファイルを再 lint するため残存 issue は before と同じ）
    remaining_lint = run_lint(target, profile=profile, strict=strict, root=root)

    return {
        "fix_results": fix_results,
        "final_lint": remaining_lint,
        "total_fixed": sum(r.get("fixed_count", 0) for r in fix_results),
        "dry_run": dry_run,
    }


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    root = repo_root()
    parser = argparse.ArgumentParser(
        description="_novel_text/*.md を rewrite ルールに基づいて lint する"
    )
    parser.add_argument(
        "target",
        type=Path,
        help="novels/NNN_作品名（ディレクトリ）または novel_textXX.md（単一ファイル）",
    )
    parser.add_argument(
        "--profile",
        default="default",
        help="使用するルールプロファイル（既定: default）",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="warning も error 扱いにする（清書完了ゲートに使用）",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="結果を JSON で出力",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="設定ファイルパス・有効ルール一覧を表示",
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help="修正可能な issue を in-place で自動修正し、残存 issue を報告する（章メタは対象外）",
    )
    parser.add_argument(
        "--fix-dry-run",
        action="store_true",
        help="--fix と同じ対象を確認するが、ファイルを変更しない",
    )
    args = parser.parse_args(argv)

    if args.fix or args.fix_dry_run:
        try:
            fix_result = run_fix(
                args.target,
                profile=args.profile,
                strict=args.strict,
                dry_run=args.fix_dry_run,
                root=root,
            )
        except FileNotFoundError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        except (KeyError, ValueError, yaml.YAMLError) as e:
            print(f"error: {e}", file=sys.stderr)
            return 2

        if args.json:
            print(json.dumps(fix_result, ensure_ascii=False, indent=2))
        else:
            print_fix_summary(fix_result["fix_results"], fix_result["final_lint"])

        return 0 if fix_result["final_lint"]["ok"] else 1

    try:
        result = run_lint(
            args.target,
            profile=args.profile,
            strict=args.strict,
            root=root,
        )
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except (KeyError, ValueError, yaml.YAMLError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print_text_result(result, verbose=args.verbose)

    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
