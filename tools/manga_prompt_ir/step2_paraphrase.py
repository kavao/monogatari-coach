"""manga_tag_step2 の置換表に基づく Step2 要約の機械言い換え。"""

from __future__ import annotations

import os
from pathlib import Path
import yaml

_RULES_CACHE: list[tuple[str, str]] | None = None
_DEFAULT_RULES_PATH = Path(__file__).resolve().parent / "data" / "step2_paraphrase_rules.yaml"
_ENV_RULES = "MONOCRI_STEP2_PARAPHRASE_RULES"
_HOWTO_RULES_NAME = Path("_how_to") / "step2_paraphrase_rules.yaml"


def repo_root() -> Path:
    """tools/manga_prompt_ir/step2_paraphrase.py から見たリポジトリルート。"""
    return Path(__file__).resolve().parent.parent.parent


def resolve_default_rules_path() -> Path:
    """既定のルール YAML の実体パスを返す。

    優先順位:
    1. 環境変数 ``MONOCRI_STEP2_PARAPHRASE_RULES``（絶対パス、またはリポジトリルートからの相対パス）
    2. リポジトリ直下 ``_how_to/step2_paraphrase_rules.yaml`` が存在すればそれ（ユーザー設計用）
    3. ツール同梱 ``tools/manga_prompt_ir/data/step2_paraphrase_rules.yaml``
    """
    env = os.environ.get(_ENV_RULES, "").strip()
    if env:
        p = Path(env).expanduser()
        if not p.is_absolute():
            p = (repo_root() / p).resolve()
        return p
    howto = repo_root() / _HOWTO_RULES_NAME
    if howto.is_file():
        return howto.resolve()
    return _DEFAULT_RULES_PATH.resolve()


def load_replacement_pairs(path: Path | None = None) -> list[tuple[str, str]]:
    """YAML から (avoid, use) のリストを読み込む。

    ``path`` が省略時は :func:`resolve_default_rules_path` を使う。
    """
    p = path or resolve_default_rules_path()
    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return []
    reps = raw.get("replacements") or []
    out: list[tuple[str, str]] = []
    for item in reps:
        if not isinstance(item, dict):
            continue
        av = str(item.get("avoid") or "").strip()
        us = str(item.get("use") or "").strip()
        if av and us:
            out.append((av, us))
    return out


def load_rules_cached(path: Path | None = None) -> list[tuple[str, str]]:
    global _RULES_CACHE
    if path is None and _RULES_CACHE is not None:
        return _RULES_CACHE
    pairs = load_replacement_pairs(path)
    if path is None:
        _RULES_CACHE = pairs
    return pairs


def apply_step2_paraphrase(
    text: str,
    *,
    rules: list[tuple[str, str]] | None = None,
) -> str:
    """avoid 語を長い順に置換する（部分一致・すべて該当）。"""
    if not text or not str(text).strip():
        return text
    pairs = rules if rules is not None else load_rules_cached()
    if not pairs:
        return text
    result = str(text)
    for avoid, use in sorted(pairs, key=lambda x: len(x[0]), reverse=True):
        if avoid in result:
            result = result.replace(avoid, use)
    return result


def paraphrase_enabled_from_env() -> bool:
    v = os.environ.get("MONOCRI_STEP2_PARAPHRASE", "").strip().lower()
    return v in ("1", "true", "yes")


def resolve_step2_paraphrase_flag(cli_yes: bool, cli_no: bool) -> bool | None:
    """None のときは panel_step2_description 内で環境変数を参照する。"""
    if cli_no:
        return False
    if cli_yes:
        return True
    return None


def effective_paraphrase(apply_paraphrase: bool | None) -> bool:
    """apply_paraphrase が None のとき環境変数で決める。"""
    if apply_paraphrase is not None:
        return bool(apply_paraphrase)
    return paraphrase_enabled_from_env()
