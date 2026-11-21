#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""表現ミックス（通常小説の文章ウェイト）の解決と検証。

    uv run python tools/novel_expression_mix.py novels/<作品> resolve
    uv run python tools/novel_expression_mix.py novels/<作品> validate
    uv run python tools/novel_expression_mix.py validate

作業用 `_how_to/expression/` に同名ファイルがあれば、その1ファイルだけを使う（標準と合成しない）。
完了ゲートにはしない。既存の beats.yaml は書き換えない。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

_TOOLS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _TOOLS_DIR.parent

HIGH_BAND = 1.5
MID_BAND = 0.75
ALLOWED_METRON_KEYS = {"type", "budget", "dialogue_turns", "independent_beat", "chars_hint", "paragraphs"}
ALLOWED_BUDGET = {"sensory", "interiority", "dialogue_turns"}
ALLOWED_TYPE = {"action", "dialogue"}
GENRE_ID_RE = re.compile(r"genre/([A-Za-z0-9_]+)(?:\.md)?")
CAT_ID_TOKEN = r"[A-Za-z][A-Za-z0-9_]*(?:-[A-Za-z0-9_]+)*"
CAT_ID_RE = re.compile(rf"^{CAT_ID_TOKEN}$")
WEIGHT_LINE_RE = re.compile(rf"^[-*]\s+\*?\*?({CAT_ID_TOKEN})\*?\*?\s*[:：]\s*(.*)$")
WEIGHT_TOKEN_RE = re.compile(r"^[+-]?(?:\d+(?:\.\d+)?|\.\d+)$")
INTERIORITY_RE = re.compile(r"INTERIORITY\s*(\+\+|--|\+|-)(?!\+)")
SPECIFIED_RE = re.compile(r"指定\*?\*?\s*[:：]\s*(指定なし|ジャンル既定|custom|保留)")
FLAG_LINE_RE = re.compile(r"^(?:[-*]\s+)?\*?\*?状態\*?\*?\s*[:：]\s*(.*)$")
HEADING_MIX = re.compile(r"^##\s+(?:3\.8\s+)?表現ミックス\s*$")
GENRE_FIELD_RE = re.compile(r"^\s*[-*]\s+\*\*ジャンル\*\*\s*[:：]\s*(.*)$")
OFF_SPECIFIED = {"指定なし", "保留"}

BAND_JA = {"high": "高", "mid": "中", "low": "低"}
SENSORY_BUDGET = {"low": 1, "mid": 2, "high": 4}
INTERIORITY_BUDGET = {"low": 0, "mid": 1, "high": 3}
DIALOGUE_TURNS = {"low": [0, 1], "mid": [1, 4], "high": [3, 8]}
PARAGRAPHS = {"low": [2, 5], "mid": [3, 6], "high": [4, 8]}
CHARS_HINT = {"low": 280, "mid": 360, "high": 520}


class MixError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def repo_root() -> Path:
    return _REPO_ROOT


def _load_yaml(path: Path) -> Any:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise MixError("READ_FAIL", f"読めない: {path.as_posix()}") from exc
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise MixError("YAML", f"YAML が壊れている: {path.as_posix()}: {exc}") from exc
    return data


def pick_file(root: Path, rel: str) -> Path | None:
    """作業用があればそれだけ。無ければ標準。どちらも無ければ None。"""
    working = root / "_how_to" / rel
    example = root / "_how_to.example" / rel
    if working.is_file():
        return working
    if example.is_file():
        return example
    return None


def _as_weight(value: Any, *, where: str, key: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MixError("WEIGHT_TYPE", f"{where}: `{key}` の重みは数である必要がある")
    number = float(value)
    if number < 0:
        raise MixError("WEIGHT_NEGATIVE", f"{where}: `{key}` の重みが負")
    return number


def load_catalog(root: Path) -> tuple[Path, dict[str, dict[str, Any]]]:
    path = pick_file(root, "expression/catalog.yaml")
    if path is None:
        raise MixError("NO_CATALOG", "expression/catalog.yaml が無い")
    data = _load_yaml(path)
    if not isinstance(data, dict) or not isinstance(data.get("categories"), dict):
        raise MixError("CATALOG", f"catalog の categories が無い: {path.as_posix()}")
    categories: dict[str, dict[str, Any]] = {}
    for cat_id, spec in data["categories"].items():
        if not isinstance(cat_id, str) or not CAT_ID_RE.fullmatch(cat_id):
            raise MixError("CATALOG_ID", f"カテゴリ ID が不正: `{cat_id}`: {path.as_posix()}")
        if not isinstance(spec, dict):
            raise MixError("CATALOG_SPEC", f"`{cat_id}` の定義が辞書ではない: {path.as_posix()}")
        if "metron" not in spec:
            raise MixError("METRON_MISSING", f"`{cat_id}` の metron が無い（写し先の欠落）: {path.as_posix()}")
        metron = spec.get("metron")
        if metron is None:
            categories[cat_id] = spec
            continue
        if not isinstance(metron, dict):
            raise MixError("METRON", f"`{cat_id}` の metron が辞書でも null でもない: {path.as_posix()}")
        unknown = set(metron) - ALLOWED_METRON_KEYS
        if unknown:
            raise MixError(
                "METRON_KEY",
                f"`{cat_id}` の metron に未知の鍵: {', '.join(sorted(unknown))}",
            )
        if not metron:
            raise MixError("METRON_EMPTY", f"`{cat_id}` の metron が空（写し先の欠落）")
        budget = metron.get("budget")
        if budget is not None and budget not in ALLOWED_BUDGET:
            raise MixError("METRON_BUDGET", f"`{cat_id}` の budget 写し先が不正: {budget}")
        beat_type = metron.get("type")
        if beat_type is not None and beat_type not in ALLOWED_TYPE:
            raise MixError("METRON_TYPE", f"`{cat_id}` の type 写し先が不正: {beat_type}")
        categories[cat_id] = spec
    if not categories:
        raise MixError("CATALOG_EMPTY", f"catalog が空: {path.as_posix()}")
    return path, categories


def load_weights_file(path: Path, catalog: dict[str, Any], *, where: str) -> dict[str, float]:
    data = _load_yaml(path)
    if not isinstance(data, dict) or not isinstance(data.get("weights"), dict):
        raise MixError("WEIGHTS", f"{where}: weights が無い: {path.as_posix()}")
    out: dict[str, float] = {}
    for key, value in data["weights"].items():
        if key not in catalog:
            raise MixError("UNKNOWN_ID", f"{where}: 未知のカテゴリ `{key}`: {path.as_posix()}")
        out[str(key)] = _as_weight(value, where=where, key=str(key))
    return out


def load_default(root: Path, catalog: dict[str, Any]) -> tuple[Path, dict[str, float]]:
    path = pick_file(root, "expression/default.yaml")
    if path is None:
        raise MixError("NO_DEFAULT", "expression/default.yaml が無い")
    return path, load_weights_file(path, catalog, where="default")


def load_profile(root: Path, genre_id: str, catalog: dict[str, Any]) -> tuple[Path | None, dict[str, float]]:
    path = pick_file(root, f"expression/profiles/{genre_id}.yaml")
    if path is None:
        return None, {}
    return path, load_weights_file(path, catalog, where=f"profile:{genre_id}")


def validate_tree(root: Path) -> list[str]:
    """カタログと、存在する default / profiles を検証する。問題があれば MixError。"""
    catalog_path, catalog = load_catalog(root)
    notes = [f"catalog: {catalog_path.as_posix()} ({len(catalog)} IDs)"]
    default_path, default_weights = load_default(root, catalog)
    notes.append(f"default: {default_path.as_posix()} ({len(default_weights)} weights)")
    for tree in (root / "_how_to" / "expression" / "profiles", root / "_how_to.example" / "expression" / "profiles"):
        if not tree.is_dir():
            continue
        for path in sorted(tree.glob("*.yaml")):
            load_weights_file(path, catalog, where=f"profile:{path.stem}")
            notes.append(f"profile: {path.as_posix()}")
    return notes


def _heading_level(line: str) -> int | None:
    stripped = line.strip()
    if not stripped.startswith("#"):
        return None
    marks = 0
    for char in stripped:
        if char != "#":
            break
        marks += 1
    if marks < 1 or marks > 6:
        return None
    if marks < len(stripped) and stripped[marks] not in " \t":
        return None
    return marks


def extract_section(text: str, matcher: re.Pattern[str]) -> str:
    lines = text.splitlines()
    start: int | None = None
    start_level = 2
    for index, line in enumerate(lines):
        if matcher.match(line.strip()):
            start = index
            start_level = _heading_level(line) or 2
            break
    if start is None:
        return ""
    end = len(lines)
    for index in range(start + 1, len(lines)):
        level = _heading_level(lines[index])
        if level is not None and level <= start_level:
            end = index
            break
    return "\n".join(lines[start:end])


def parse_genre_ids(meta_text: str) -> list[str]:
    for line in meta_text.splitlines():
        match = GENRE_FIELD_RE.match(line)
        if not match:
            continue
        rest = match.group(1)
        found = [item.lower() for item in GENRE_ID_RE.findall(rest)]
        # 順序を保ちつつ重複を除く
        unique: list[str] = []
        for item in found:
            if item not in unique:
                unique.append(item)
        return unique
    return []


def parse_interiority_cap(meta_text: str) -> str | None:
    """見せ方軸の INTERIORITY 記号。無ければ None。"""
    section = extract_section(meta_text, re.compile(r"^##\s+(?:3\.7\s+)?見せ方軸\s*$"))
    if not section:
        return None
    found = INTERIORITY_RE.findall(section)
    if not found:
        return None
    return found[0]


def interiority_is_low(mark: str | None) -> bool:
    return mark in {"-", "--"}


@dataclass
class Freeze:
    flag: str | None
    specified: str | None
    weights: dict[str, float] = field(default_factory=dict)


def parse_flag_line(section: str) -> str | None:
    """状態の値は行全体が ON か OFF。接尾・空・混在は失敗。行が無ければ None。"""
    valid: list[str] = []
    invalid: list[str] = []
    for line in section.splitlines():
        match = FLAG_LINE_RE.match(line.strip())
        if not match:
            continue
        token = match.group(1).strip().strip("*").strip()
        if token in {"ON", "OFF"}:
            valid.append(token)
        else:
            invalid.append(token if token else "（空）")
    if invalid:
        raise MixError("FLAG", f"_meta.md 表現ミックス: 状態は ON か OFF（得た値: {invalid[0]}）")
    if not valid:
        return None
    if len(set(valid)) > 1:
        raise MixError("FLAG", "_meta.md 表現ミックス: 状態行の値が食い違う")
    return valid[0]


def effective_flag(freeze: Freeze) -> tuple[str, str, bool]:
    """(ON|OFF, explicit|implicit, enabled)。状態行だけが起草の可否。節なしと OFF は使わない。"""
    if freeze.flag == "ON":
        return "ON", "explicit", True
    if freeze.flag == "OFF":
        return "OFF", "explicit", False
    return "OFF", "implicit", False


def mix_is_enabled(meta_text: str) -> bool:
    """作品 _meta.md の状態が ON か。不正な状態行は使わない。"""
    section = extract_section(meta_text, HEADING_MIX)
    if not section:
        return False
    try:
        flag = parse_flag_line(section)
    except MixError:
        return False
    _, _, enabled = effective_flag(Freeze(flag=flag, specified=None))
    return enabled


def parse_freeze(meta_text: str, catalog: dict[str, Any]) -> Freeze:
    section = extract_section(meta_text, HEADING_MIX)
    if not section:
        return Freeze(flag=None, specified=None)
    specified = None
    for line in section.splitlines():
        match = SPECIFIED_RE.search(line)
        if match:
            specified = match.group(1)
            break
    flag = parse_flag_line(section)
    weights: dict[str, float] = {}
    in_weights = False
    for line in section.splitlines():
        stripped = line.strip()
        if re.match(r"^[-*]\s+\*\*重み", stripped):
            in_weights = True
            continue
        if in_weights:
            level = _heading_level(line)
            if level is not None:
                break
            if stripped.startswith("- **") and "重み" not in stripped and WEIGHT_LINE_RE.match(stripped) is None:
                if re.match(r"^[-*]\s+\*\*", stripped):
                    in_weights = False
            match = WEIGHT_LINE_RE.match(stripped)
            if match:
                key, raw = match.group(1), match.group(2).strip()
                if key not in catalog:
                    raise MixError("UNKNOWN_ID", f"_meta.md 表現ミックス: 未知のカテゴリ `{key}`")
                if not raw:
                    raise MixError("WEIGHT_TYPE", f"_meta.md 表現ミックス: `{key}` の重みが空")
                if not WEIGHT_TOKEN_RE.fullmatch(raw):
                    raise MixError("WEIGHT_TYPE", f"_meta.md 表現ミックス: `{key}` の重みが数ではない: {raw}")
                weights[key] = _as_weight(float(raw), where="_meta.md", key=key)
    return Freeze(flag=flag, specified=specified, weights=weights)


def normalize(weights: dict[str, float], catalog_ids: list[str]) -> dict[str, float]:
    values = [weights.get(key, 0.0) for key in catalog_ids]
    mean = sum(values) / len(values) if values else 1.0
    if mean <= 0:
        return {key: 0.0 for key in catalog_ids}
    return {key: (weights.get(key, 0.0) / mean) for key in catalog_ids}


def band_of(normalized: float) -> str:
    if normalized >= HIGH_BAND:
        return "high"
    if normalized >= MID_BAND:
        return "mid"
    return "low"


def stronger_band(*bands: str) -> str:
    order = {"low": 0, "mid": 1, "high": 2}
    return max(bands, key=lambda item: order.get(item, 0))


def _metron_map(spec: dict[str, Any]) -> dict[str, Any] | None:
    metron = spec.get("metron")
    return metron if isinstance(metron, dict) else None


def _bands_mapped(bands: dict[str, str], catalog: dict[str, Any], *, key: str, value: str) -> list[str]:
    found: list[str] = []
    for cat_id, spec in catalog.items():
        metron = _metron_map(spec)
        if metron is not None and metron.get(key) == value:
            found.append(bands.get(cat_id, "mid"))
    return found


def beat_defaults(
    bands: dict[str, str],
    catalog: dict[str, Any],
    *,
    interiority_capped: bool,
) -> dict[str, Any]:
    sensory_parts = _bands_mapped(bands, catalog, key="budget", value="sensory")
    sensory_band = stronger_band(*sensory_parts) if sensory_parts else "mid"
    interior_parts = _bands_mapped(bands, catalog, key="budget", value="interiority")
    interior_band = stronger_band(*interior_parts) if interior_parts else "mid"
    if interiority_capped:
        interior_band = "low"
    dialogue_parts = _bands_mapped(bands, catalog, key="budget", value="dialogue_turns")
    dialogue_band = stronger_band(*dialogue_parts) if dialogue_parts else "mid"
    process_parts = _bands_mapped(bands, catalog, key="chars_hint", value="up")
    process_parts.extend(_bands_mapped(bands, catalog, key="paragraphs", value="up"))
    process_band = stronger_band(*process_parts) if process_parts else "mid"
    gesture_high = any(
        bands.get(cat_id) == "high" and (_metron_map(spec) or {}).get("dialogue_turns") == "low"
        for cat_id, spec in catalog.items()
    )
    prefer_action = gesture_high and dialogue_band == "low"
    return {
        "sensory": SENSORY_BUDGET[sensory_band],
        "interiority": INTERIORITY_BUDGET[interior_band],
        "dialogue_turns": DIALOGUE_TURNS[dialogue_band],
        "paragraphs": PARAGRAPHS[process_band],
        "chars_hint": CHARS_HINT[process_band],
        "prefer_action_over_dialogue": prefer_action,
        "independent_sound_beat": False,
        "bands_used": {
            "sensory": sensory_band,
            "interiority": interior_band,
            "dialogue": dialogue_band,
            "process": process_band,
        },
    }


@dataclass
class MixResult:
    catalog_path: str
    default_path: str
    genre_ids: list[str]
    sources: list[str]
    weights: dict[str, float]
    normalized: dict[str, float]
    bands: dict[str, str]
    conflicts: list[dict[str, Any]]
    freeze: str | None
    flag: str
    flag_source: str
    enabled: bool
    interiority_mark: str | None
    interiority_capped: bool
    beat_defaults: dict[str, Any]
    advice: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "catalog_path": self.catalog_path,
            "default_path": self.default_path,
            "genre_ids": self.genre_ids,
            "sources": self.sources,
            "weights": self.weights,
            "normalized": {key: round(value, 4) for key, value in self.normalized.items()},
            "bands": self.bands,
            "conflicts": self.conflicts,
            "freeze": self.freeze,
            "flag": self.flag,
            "flag_source": self.flag_source,
            "enabled": self.enabled,
            "interiority_mark": self.interiority_mark,
            "interiority_capped": self.interiority_capped,
            "beat_defaults": self.beat_defaults,
            "advice": self.advice,
        }


def resolve_mix(work: Path, *, root: Path | None = None) -> MixResult:
    root = root or repo_root()
    work = work.resolve()
    meta_path = work / "_meta.md"
    if not meta_path.is_file():
        raise MixError("NO_META", f"_meta.md が無い: {meta_path.as_posix()}")
    meta_text = meta_path.read_text(encoding="utf-8")

    catalog_path, catalog = load_catalog(root)
    default_path, weights = load_default(root, catalog)
    catalog_ids = list(catalog)
    sources = [f"default:{default_path.as_posix()}"]
    genre_ids = parse_genre_ids(meta_text)
    conflicts: list[dict[str, Any]] = []

    profile_values: dict[str, dict[str, float]] = {}
    for genre_id in sorted(genre_ids):
        path, overlay = load_profile(root, genre_id, catalog)
        if path is None:
            sources.append(f"profile:{genre_id}:なし（default のまま）")
            continue
        sources.append(f"profile:{genre_id}:{path.as_posix()}")
        profile_values[genre_id] = overlay
        for key, value in overlay.items():
            earlier = [
                (other, other_weights[key])
                for other, other_weights in profile_values.items()
                if other != genre_id and key in other_weights and other_weights[key] != value
            ]
            if earlier:
                conflicts.append(
                    {
                        "category": key,
                        "values": {**{other: other_val for other, other_val in earlier}, genre_id: value},
                    }
                )
            weights[key] = value

    freeze = parse_freeze(meta_text, catalog)
    flag, flag_source, enabled = effective_flag(freeze)
    if freeze.flag == "ON" and freeze.specified == "指定なし":
        raise MixError("FLAG_ON_UNSPECIFIED", "_meta.md 表現ミックス: 状態 ON のときは ジャンル既定 か custom")
    freeze_label = freeze.specified
    sources.append(f"flag:{flag}:{flag_source}")
    if enabled:
        missing = [key for key in catalog_ids if key not in freeze.weights]
        if missing:
            raise MixError(
                "WEIGHT_INCOMPLETE",
                "_meta.md 表現ミックス: 状態 ON のときはカタログの重みを全部書く（欠け: "
                + ", ".join(missing)
                + "）",
            )
        sources.append("freeze:_meta.md")
        weights = dict(freeze.weights)
    elif freeze.weights:
        sources.append("freeze:_meta.md")
        weights.update(freeze.weights)
    if freeze.specified in OFF_SPECIFIED:
        sources.append(f"freeze:{freeze.specified}")
    elif freeze.specified == "ジャンル既定":
        sources.append("freeze:ジャンル既定")
    elif freeze.specified is None:
        sources.append("freeze:節なし")
    elif freeze.specified == "custom" and not freeze.weights:
        sources.append("freeze:custom（重みなし）")

    mark = parse_interiority_cap(meta_text)
    capped = interiority_is_low(mark)
    if capped:
        weights["interiority"] = min(weights.get("interiority", 0.0), MID_BAND * 0.5)

    normalized = normalize(weights, catalog_ids)
    if capped:
        normalized["interiority"] = min(normalized.get("interiority", 0.0), MID_BAND - 0.01)
    bands = {key: band_of(normalized[key]) for key in catalog_ids}
    if capped:
        bands["interiority"] = "low"

    defaults = beat_defaults(bands, catalog, interiority_capped=capped)
    advice: list[str] = []
    if conflicts:
        advice.append("複数ジャンルのプロファイルが同じカテゴリで衝突している。作者へ一言確認する。")
    if capped:
        advice.append("見せ方軸の INTERIORITY が低いので、内面の重みを上げても独白を増やさない。")
    if bands.get("gesture") == "high" and bands.get("dialogue") == "low":
        advice.append("所作を厚くする。会話 Beat は増やさない。")
    if bands.get("sound") == "high":
        advice.append("現場音は budget.sensory へ写す。独立 Beat にしない。")
    if bands.get("metaphor") == "high":
        advice.append("比喩は助言のみ。崩れる文は書かない。METRON には写さない。")
    if not enabled:
        advice.append("状態は OFF。新規 beats には写さない。完了ゲートにしない。")
    else:
        advice.append("状態は ON。新規 beats の sensory / interiority / dialogue_turns へ既定を写す。完了ゲートにしない。")

    filled = {key: weights.get(key, 0.0) for key in catalog_ids}
    return MixResult(
        catalog_path=catalog_path.as_posix(),
        default_path=default_path.as_posix(),
        genre_ids=genre_ids,
        sources=sources,
        weights=filled,
        normalized=normalized,
        bands=bands,
        conflicts=conflicts,
        freeze=freeze_label,
        flag=flag,
        flag_source=flag_source,
        enabled=enabled,
        interiority_mark=mark,
        interiority_capped=capped,
        beat_defaults=defaults,
        advice=advice,
    )


def format_result(result: MixResult) -> str:
    lines = [
        f"catalog: {result.catalog_path}",
        f"default: {result.default_path}",
        "genre: " + ("、".join(result.genre_ids) or "なし"),
        f"flag: {result.flag} ({result.flag_source})",
        f"enabled: {str(result.enabled).lower()}",
        "freeze: " + (result.freeze or "節なし"),
        "sources:",
    ]
    for source in result.sources:
        lines.append(f"  - {source}")
    lines.append("bands:")
    for key, band in result.bands.items():
        weight = result.weights.get(key, 0.0)
        norm = result.normalized.get(key, 0.0)
        lines.append(f"  - {key}: {BAND_JA[band]} (weight {weight:g}, norm {norm:.2f})")
    if result.conflicts:
        lines.append("conflicts:")
        for item in result.conflicts:
            detail = ", ".join(f"{gid}={val:g}" for gid, val in item["values"].items())
            lines.append(f"  - {item['category']}: {detail}")
    defaults = result.beat_defaults
    lines.append("new beats.yaml defaults (do not rewrite existing):")
    lines.append(f"  sensory: {defaults['sensory']}")
    lines.append(f"  interiority: {defaults['interiority']}")
    turns = defaults["dialogue_turns"]
    lines.append(f"  dialogue_turns: [{turns[0]}, {turns[1]}]")
    paras = defaults["paragraphs"]
    lines.append(f"  paragraphs: [{paras[0]}, {paras[1]}]")
    lines.append(f"  chars_hint: {defaults['chars_hint']}")
    lines.append(f"  prefer_action_over_dialogue: {defaults['prefer_action_over_dialogue']}")
    lines.append("  independent_sound_beat: false")
    if result.advice:
        lines.append("advice:")
        for item in result.advice:
            lines.append(f"  - {item}")
    return "\n".join(lines)


def _parse_argv(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="表現ミックスの解決と検証（完了ゲートではない）")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--root", type=Path, default=None, help=argparse.SUPPRESS)
    parser.add_argument("tokens", nargs="+", help="novels/<作品> resolve|validate  /  validate")
    args = parser.parse_args(argv)
    tokens = list(args.tokens)
    work: Path | None = None
    command: str
    if len(tokens) == 1 and tokens[0] == "validate":
        command = "validate"
    elif len(tokens) >= 2 and tokens[-1] in {"resolve", "validate"}:
        command = tokens[-1]
        work = Path(tokens[0] if len(tokens) == 2 else " ".join(tokens[:-1]))
    elif tokens[0] in {"resolve", "validate"} and len(tokens) >= 2:
        command = tokens[0]
        work = Path(" ".join(tokens[1:]))
    else:
        parser.error("使い方: novels/<作品> resolve|validate  /  validate")
    args.command = command
    args.work = work
    return args


def main(argv: list[str] | None = None) -> int:
    args = _parse_argv(argv)
    root = (args.root or repo_root()).resolve()
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except AttributeError:
        pass
    try:
        if args.command == "validate" and args.work is None:
            notes = validate_tree(root)
            if args.json:
                print(json.dumps({"ok": True, "notes": notes}, ensure_ascii=False, indent=2))
            else:
                print("validate: ok")
                for note in notes:
                    print(f"  {note}")
            return 0
        if args.work is None:
            raise MixError("NO_WORK", "作品フォルダが無い")
        if args.command == "validate":
            validate_tree(root)
            result = resolve_mix(args.work, root=root)
            if args.json:
                print(json.dumps({"ok": True, **result.as_dict()}, ensure_ascii=False, indent=2))
            else:
                print("validate: ok")
                print(format_result(result))
            return 0
        result = resolve_mix(args.work, root=root)
        if args.json:
            print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
        else:
            print(format_result(result))
        return 0
    except MixError as exc:
        if args.json:
            print(json.dumps({"ok": False, "code": exc.code, "error": str(exc)}, ensure_ascii=False, indent=2))
        else:
            print(f"error [{exc.code}]: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
