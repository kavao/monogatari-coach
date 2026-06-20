"""ユーザ指示（`render_instruction.user_directives`）と
コマ別の `required_prompt_tags` / `omit_prompt_tags` を扱う共通ロジック。

generator (`image_provider_novel_manga_batch.py`)・
exporter  (`novel_prompt_ir_export_md.py`)・
validator (`novel_prompt_ir_validate.py`) から共有して呼ぶ。

dict ベースで動作するため、Pydantic モデルのインスタンスでも
`.model_dump()` 後の dict・素の YAML ロード結果のどちらでも使える。
"""

from __future__ import annotations

from typing import Any, Iterable


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return list(value)
    return [value]


def _str_list(value: Any) -> list[str]:
    return [str(v) for v in _as_list(value) if v is not None and str(v) != ""]


def page_default_required(page: Any) -> list[str]:
    """ページ単位で「必ず追加するタグ」（既定値）。"""
    if not isinstance(page, dict):
        return []
    instruction = page.get("render_instruction") or {}
    if not isinstance(instruction, dict):
        return []
    directives = instruction.get("user_directives") or {}
    if not isinstance(directives, dict):
        return []
    defaults = directives.get("defaults") or {}
    if not isinstance(defaults, dict):
        return []
    return _str_list(defaults.get("required_prompt_tags"))


def page_default_omit(page: Any) -> list[str]:
    """ページ単位で「必ず除外するタグ」（既定値）。"""
    if not isinstance(page, dict):
        return []
    instruction = page.get("render_instruction") or {}
    if not isinstance(instruction, dict):
        return []
    directives = instruction.get("user_directives") or {}
    if not isinstance(directives, dict):
        return []
    defaults = directives.get("defaults") or {}
    if not isinstance(defaults, dict):
        return []
    return _str_list(defaults.get("omit_prompt_tags"))


def panel_required(panel: Any) -> list[str]:
    """コマ単位で「必ず追加するタグ」。"""
    if not isinstance(panel, dict):
        return []
    return _str_list(panel.get("required_prompt_tags"))


def panel_omit(panel: Any) -> list[str]:
    """コマ単位で「必ず除外するタグ」。"""
    if not isinstance(panel, dict):
        return []
    return _str_list(panel.get("omit_prompt_tags"))


def required_tags_for_panel(page: Any, panel: Any) -> list[str]:
    """ページ既定とコマ上書きを合算した「必ず追加」タグ列（重複除去）。"""
    seen: set[str] = set()
    out: list[str] = []
    for tag in [*page_default_required(page), *panel_required(panel)]:
        if tag and tag not in seen:
            seen.add(tag)
            out.append(tag)
    return out


def omit_tags_for_panel(page: Any, panel: Any) -> set[str]:
    """ページ既定とコマ上書きを合算した「必ず除外」タグの集合。"""
    return {tag for tag in [*page_default_omit(page), *panel_omit(panel)] if tag}


def apply_to_tags(
    tags: Iterable[str],
    page: Any,
    panel: Any,
) -> list[str]:
    """タグ列に対し、ユーザ指示の required/omit を強制適用する。

    手順:
      1. 受け取ったタグ列の重複を保ちながら順序を維持。
      2. ページ既定とコマ上書きの required を末尾に加算。
      3. 既存／追加分すべてに対し、ページ既定とコマ上書きの omit を除外。

    返り値は順序保持の重複なしリスト（`unique` 相当）。
    """
    base = [str(t) for t in tags if t is not None and str(t) != ""]
    required = required_tags_for_panel(page, panel)
    combined: list[str] = []
    seen: set[str] = set()
    for tag in [*base, *required]:
        if tag in seen:
            continue
        seen.add(tag)
        combined.append(tag)
    omit = omit_tags_for_panel(page, panel)
    if not omit:
        return combined
    return [tag for tag in combined if tag not in omit]
