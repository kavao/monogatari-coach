#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成時タグマスキング（置換／除外）。

YAML IR 正本は書き換えず、プロンプト組み立て後のトークン列に対して適用する。
キャラ／漫画（step1-panels）／挿絵 batch から共通利用する純関数群。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any


def normalize_tag(tag: str) -> str:
    """照合用キー: strip → 小文字 → 空白を `_`。"""
    return str(tag or "").strip().lower().replace(" ", "_")


def dedupe_preserve(tags: Iterable[str]) -> list[str]:
    """空でないタグを順序保持で重複除去する。"""
    out: list[str] = []
    seen: set[str] = set()
    for raw in tags:
        token = str(raw).strip() if raw is not None else ""
        if not token or token in seen:
            continue
        seen.add(token)
        out.append(token)
    return out


@dataclass(frozen=True)
class MaskRuleSet:
    """omit / replace の規則集合。"""

    omit_tags: tuple[str, ...] = ()
    # (from_normalized, to_display) — to はプロンプトに載せる表記（空は禁止）
    replace_pairs: tuple[tuple[str, str], ...] = ()

    @staticmethod
    def empty() -> MaskRuleSet:
        return MaskRuleSet()

    def merge(self, other: MaskRuleSet) -> MaskRuleSet:
        """self のあとに other。omit は連結、replace は同 from を後勝ち。"""
        omit = tuple(dedupe_preserve([*self.omit_tags, *other.omit_tags]))
        by_from: dict[str, str] = {}
        order: list[str] = []
        for src, dst in [*self.replace_pairs, *other.replace_pairs]:
            if src not in by_from:
                order.append(src)
            by_from[src] = dst
        pairs = tuple((k, by_from[k]) for k in order)
        return MaskRuleSet(omit_tags=omit, replace_pairs=pairs)

    def replace_map(self) -> dict[str, str]:
        return dict(self.replace_pairs)

    def omit_set_normalized(self) -> set[str]:
        return {normalize_tag(t) for t in self.omit_tags if normalize_tag(t)}

    def conflict_from_in_omit(self) -> list[str]:
        """replace の from が omit にもあるキー（正規化済み）。dry-run 警告用。"""
        omit_n = self.omit_set_normalized()
        out: list[str] = []
        for src, _ in self.replace_pairs:
            if src in omit_n:
                out.append(src)
        return out


@dataclass
class MaskApplyResult:
    tags: list[str]
    replaced: list[tuple[str, str]] = field(default_factory=list)
    omitted: list[str] = field(default_factory=list)


def parse_replace_pairs(raw: object | None) -> list[tuple[str, str]]:
    """YAML / dict / list から (from_normalized, to_display) を返す。

    受け付け形式:
      - [{"from": "a", "to": "b"}, ...]
      - {"a": "b", ...}  （キーが from、値が to）
    空の to は ValueError。
    """
    if raw is None:
        return []
    pairs: list[tuple[str, str]] = []
    if isinstance(raw, Mapping):
        items = list(raw.items())
        for key, value in items:
            src = normalize_tag(str(key))
            dst = str(value).strip() if value is not None else ""
            if not src:
                continue
            if not dst:
                raise ValueError(
                    f"replace_tags: from={key!r} の to が空です。"
                    "削除したい場合は omit_tags を使ってください"
                )
            pairs.append((src, dst))
        return pairs
    if not isinstance(raw, list):
        raise ValueError(
            "replace_tags は list[{from, to}] または mapping である必要があります"
        )
    for i, item in enumerate(raw):
        if not isinstance(item, Mapping):
            raise ValueError(f"replace_tags[{i}] はオブジェクトである必要があります")
        src_raw = item.get("from")
        dst_raw = item.get("to")
        if src_raw is None:
            raise ValueError(f"replace_tags[{i}]: from がありません")
        src = normalize_tag(str(src_raw))
        dst = str(dst_raw).strip() if dst_raw is not None else ""
        if not src:
            raise ValueError(f"replace_tags[{i}]: from が空です")
        if not dst:
            raise ValueError(
                f"replace_tags[{i}]: from={src_raw!r} の to が空です。"
                "削除したい場合は omit_tags を使ってください"
            )
        pairs.append((src, dst))
    return pairs


def parse_omit_tags(raw: object | None) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("omit_tags は list である必要があります")
    return dedupe_preserve(str(x) for x in raw)


def mask_rules_from_mapping(data: object | None) -> MaskRuleSet:
    """character_tag_batch / tag_batch の omit_tags / replace_tags を読む。"""
    if not isinstance(data, dict):
        return MaskRuleSet.empty()
    omit = parse_omit_tags(data.get("omit_tags"))
    pairs = parse_replace_pairs(data.get("replace_tags"))
    return MaskRuleSet(
        omit_tags=tuple(omit),
        replace_pairs=tuple(pairs),
    )


def parse_cli_replace_tags(values: Sequence[str] | None) -> list[tuple[str, str]]:
    """CLI ``--replace-tag old=new``（複数）をペア列にする。"""
    if not values:
        return []
    pairs: list[tuple[str, str]] = []
    for raw in values:
        text = str(raw).strip()
        if not text:
            continue
        if "=" not in text:
            raise ValueError(
                f"--replace-tag は old=new 形式です（得: {raw!r}）"
            )
        left, right = text.split("=", 1)
        src = normalize_tag(left)
        dst = right.strip()
        if not src:
            raise ValueError(f"--replace-tag: from が空です: {raw!r}")
        if not dst:
            raise ValueError(
                f"--replace-tag: to が空です: {raw!r}。"
                "削除したい場合は --omit-tags を使ってください"
            )
        pairs.append((src, dst))
    return pairs


def apply_replace(
    tags: Iterable[str],
    replace_map: Mapping[str, str],
) -> tuple[list[str], list[tuple[str, str]]]:
    """同時マップ置換。1トークンは最大1回。戻り: (新列, [(旧表示, 新表示), ...])。

    ``to`` にカンマ区切りが含まれる場合は複数トークンへ展開する
    （例: ``childlike_mature`` → ``toddler, Short stack, loli``）。
    """
    if not replace_map:
        return dedupe_preserve(tags), []
    out: list[str] = []
    replaced: list[tuple[str, str]] = []
    seen: set[str] = set()
    for raw in tags:
        token = str(raw).strip() if raw is not None else ""
        if not token:
            continue
        key = normalize_tag(token)
        if key in replace_map:
            new_token = replace_map[key]
            replaced.append((token, new_token))
            parts = [p.strip() for p in str(new_token).split(",") if p.strip()]
            if not parts:
                continue
            for part in parts:
                if part in seen:
                    continue
                seen.add(part)
                out.append(part)
            continue
        if token in seen:
            continue
        seen.add(token)
        out.append(token)
    return out, replaced


def apply_omit(
    tags: Iterable[str],
    omit_tags: Iterable[str],
) -> tuple[list[str], list[str]]:
    """正規化キーで除外。戻り: (新列, 除外された表示トークン列)。"""
    omit_n = {normalize_tag(t) for t in omit_tags if normalize_tag(t)}
    if not omit_n:
        return dedupe_preserve(tags), []
    out: list[str] = []
    omitted: list[str] = []
    seen: set[str] = set()
    for raw in tags:
        token = str(raw).strip() if raw is not None else ""
        if not token:
            continue
        if normalize_tag(token) in omit_n:
            omitted.append(token)
            continue
        if token in seen:
            continue
        seen.add(token)
        out.append(token)
    return out, omitted


def apply_mask(
    tags: Iterable[str],
    rules: MaskRuleSet | None,
) -> MaskApplyResult:
    """compose 後のタグ列に replace → omit → 重複除去を適用する。"""
    base = dedupe_preserve(tags)
    if rules is None or rules == MaskRuleSet.empty():
        return MaskApplyResult(tags=base)
    after_replace, replaced = apply_replace(base, rules.replace_map())
    after_omit, omitted = apply_omit(after_replace, rules.omit_tags)
    return MaskApplyResult(
        tags=after_omit,
        replaced=replaced,
        omitted=omitted,
    )


def mask_rules_from_layers_dict(data: dict[str, Any] | None) -> MaskRuleSet:
    """TagBatchLayers 相当の dict からも読めるエイリアス。"""
    return mask_rules_from_mapping(data)


def merge_mask_results(*parts: MaskApplyResult) -> MaskApplyResult:
    """複数セグメントのマスク結果をログ用に合算する。"""
    tags: list[str] = []
    replaced: list[tuple[str, str]] = []
    omitted: list[str] = []
    for part in parts:
        tags.extend(part.tags)
        replaced.extend(part.replaced)
        omitted.extend(part.omitted)
    return MaskApplyResult(tags=tags, replaced=replaced, omitted=omitted)


def mask_csv_or_pipe_prompt(
    prompt: str,
    rules: MaskRuleSet | None,
) -> tuple[str, MaskApplyResult]:
    """カンマ区切り、または ``base | char`` パイプ区切りのタグ列プロンプトにマスクを適用する。

    自然文プロンプトには使わない（カンマ分割で文が壊れるため）。
    """
    text = str(prompt or "")
    if rules is None or rules == MaskRuleSet.empty() or not text.strip():
        return text, MaskApplyResult(tags=[])
    if "|" in text:
        segments = [p.strip() for p in text.split("|")]
        results: list[MaskApplyResult] = []
        new_parts: list[str] = []
        for seg in segments:
            tokens = [t.strip() for t in seg.split(",") if t.strip()]
            result = apply_mask(tokens, rules)
            results.append(result)
            new_parts.append(", ".join(result.tags))
        return " | ".join(new_parts), merge_mask_results(*results)
    tokens = [t.strip() for t in text.split(",") if t.strip()]
    result = apply_mask(tokens, rules)
    return ", ".join(result.tags), result


def load_novel_mask_rules(
    novel_dir: Any,
    *,
    primary_key: str,
    fallback_key: str | None = None,
) -> MaskRuleSet:
    """作品 ``_meta.yaml`` からマスク規則を読む。

    ``primary_key``（例: manga_tag_batch）を先に読み、
    ``fallback_key``（例: character_tag_batch）があればその omit/replace を下敷きにし、
    primary を後勝ちでマージする。
    """
    from pathlib import Path

    from novel_meta_yaml import load_meta_yaml

    path = Path(novel_dir)
    meta = load_meta_yaml(path) or {}
    primary = mask_rules_from_mapping(meta.get(primary_key))
    if not fallback_key:
        return primary
    fallback = mask_rules_from_mapping(meta.get(fallback_key))
    return fallback.merge(primary)

