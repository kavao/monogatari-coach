"""manga_tag_step2 の置換表に基づく Step2 要約の機械言い換え。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml

_RULES_CONFIG_CACHE: Step2RulesConfig | None = None
_DEFAULT_RULES_PATH = Path(__file__).resolve().parent / "data" / "step2_paraphrase_rules.yaml"
_ENV_RULES = "MONOCRI_STEP2_PARAPHRASE_RULES"
_HOWTO_RULES_NAME = Path("_how_to") / "step2_paraphrase_rules.yaml"

# whole_text: avoid が部分一致したらそのコマ本文全体を use に差し替え（画像生成向けの抽象一文に寄せる）
# substring: 従来どおり文中の該当部分のみ replace（文章の繋がりを残したいとき）
_APPLY_MODES = frozenset({"whole_text", "substring"})
_DEFAULT_APPLY_MODE = "whole_text"


@dataclass(frozen=True)
class Step2RulesConfig:
    """ルール YAML の apply_mode と replacements の組。"""

    apply_mode: str
    pairs: list[tuple[str, str]]


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


def _parse_rules_yaml(raw: object) -> Step2RulesConfig:
    if not isinstance(raw, dict):
        return Step2RulesConfig(_DEFAULT_APPLY_MODE, [])
    mode = str(raw.get("apply_mode") or _DEFAULT_APPLY_MODE).strip().lower()
    if mode not in _APPLY_MODES:
        mode = _DEFAULT_APPLY_MODE
    reps = raw.get("replacements") or []
    out: list[tuple[str, str]] = []
    for item in reps:
        if not isinstance(item, dict):
            continue
        av = str(item.get("avoid") or "").strip()
        us = str(item.get("use") or "").strip()
        if av and us:
            out.append((av, us))
    return Step2RulesConfig(mode, out)


def load_step2_rules_config(path: Path | None = None) -> Step2RulesConfig:
    """YAML から apply_mode と (avoid, use) 一覧を読む。"""
    p = path or resolve_default_rules_path()
    raw = yaml.safe_load(Path(p).read_text(encoding="utf-8"))
    return _parse_rules_yaml(raw)


def load_replacement_pairs(path: Path | None = None) -> list[tuple[str, str]]:
    """YAML から (avoid, use) のリストのみ読み込む（後方互換・テスト用）。

    ``path`` が省略時は :func:`resolve_default_rules_path` を使う。
    """
    return load_step2_rules_config(path).pairs


def load_rules_config_cached(path: Path | None = None) -> Step2RulesConfig:
    global _RULES_CONFIG_CACHE
    if path is None and _RULES_CONFIG_CACHE is not None:
        return _RULES_CONFIG_CACHE
    cfg = load_step2_rules_config(path)
    if path is None:
        _RULES_CONFIG_CACHE = cfg
    return cfg


def _apply_substring(text: str, pairs: list[tuple[str, str]]) -> str:
    """avoid を長い順に部分置換（すべての該当箇所）。"""
    result = str(text)
    for avoid, use in sorted(pairs, key=lambda x: len(x[0]), reverse=True):
        if avoid in result:
            result = result.replace(avoid, use)
    return result


def _apply_whole_text(text: str, pairs: list[tuple[str, str]]) -> str:
    """avoid が一度でも部分一致したら、本文全体を対応する use に差し替える。

    複数ルールが該当しうるときは avoid が長い順に試し、最初にマッチしたルールだけ使う。
    """
    result = str(text)
    for avoid, use in sorted(pairs, key=lambda x: len(x[0]), reverse=True):
        if avoid in result:
            return use
    return result


def apply_step2_paraphrase(
    text: str,
    *,
    rules: list[tuple[str, str]] | None = None,
    apply_mode: str | None = None,
) -> str:
    """Step2 要約へルールを適用する。

    - ``rules`` 省略時: 既定 YAML の ``apply_mode``（既定 ``whole_text``）と replacements を使用。
    - ``rules`` 指定時: そのリストを使い、``apply_mode`` 省略なら ``whole_text``。
    """
    if not text or not str(text).strip():
        return text

    if rules is not None:
        pairs = rules
        mode = apply_mode or _DEFAULT_APPLY_MODE
    else:
        cfg = load_rules_config_cached()
        pairs = cfg.pairs
        mode = apply_mode or cfg.apply_mode

    if mode not in _APPLY_MODES:
        mode = _DEFAULT_APPLY_MODE
    if not pairs:
        return text

    if mode == "substring":
        return _apply_substring(text, pairs)
    return _apply_whole_text(text, pairs)


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
