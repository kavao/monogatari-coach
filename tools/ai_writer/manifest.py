"""Generation Manifest（計画書 §48〜49、Phase 1）。

1 回の生成について、何を参照し、どの版の部品でどう生成したかを残す。参照した設定（人物・世界・契約・本文）は
ID だけでなく内容の SHA-256 を記録し、あとで設定が変わったら ``stale_refs`` で検出できるようにする
（探索機能の計画 E4「参照版が古い場合は再レビュー」）。

ハッシュは UTF-8 で NFC に正規化した本文から取る（改行コードの違いは同一とみなすため、CRLF を LF にそろえる）。
トークンなどの秘密は持たない（``request`` の部分は持たず、要求本文の hash だけを残す）。
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from novel_char_count import count_chars

from .writer import WriterOutput

MANIFEST_VERSION = 1
RefKind = Literal["character", "world", "lore", "canon", "contract", "scene", "beat", "constraint", "source_text", "other"]


def content_hash(text: str) -> str:
    normalized = unicodedata.normalize("NFC", text.replace("\r\n", "\n"))
    return "sha256:" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SourceRef:
    kind: RefKind
    id: str
    hash: str
    path: str | None = None
    """ファイルの場所。リポジトリ内なら相対パス、外なら絶対パス。``stale_refs`` で読み直す。"""
    revision: str | None = None

    @classmethod
    def from_text(cls, kind: RefKind, id: str, text: str, *, revision: str | None = None) -> SourceRef:
        return cls(kind=kind, id=id, hash=content_hash(text), revision=revision)

    @classmethod
    def from_file(cls, kind: RefKind, path: Path, repo_root: Path, *, id: str | None = None) -> SourceRef:
        """リポジトリ内ならリポジトリからの相対パス、外なら絶対パスで記録する（``stale_refs`` はどちらも読める）。"""
        resolved = path.resolve()
        try:
            rel = resolved.relative_to(repo_root.resolve()).as_posix()
        except ValueError:
            rel = resolved.as_posix()
        return cls(kind=kind, id=id or rel, hash=content_hash(path.read_text(encoding="utf-8")), path=rel)

    @classmethod
    def from_data(cls, kind: RefKind, id: str, data: Any) -> SourceRef:
        """契約などの構造化データ。キー順をそろえた JSON の hash。"""
        return cls(kind=kind, id=id, hash=content_hash(json.dumps(data, ensure_ascii=False, sort_keys=True, default=str)))


def work_refs(work_dir: Path, repo_root: Path) -> list[SourceRef]:
    """作品フォルダの設定ファイル（あるものだけ）を参照として記録する。"""
    table: tuple[tuple[str, RefKind], ...] = (("character.md", "character"), ("world.md", "world"),
                                              ("design_specification.md", "lore"), ("_meta.md", "canon"))
    return [SourceRef.from_file(kind, work_dir / name, repo_root) for name, kind in table if (work_dir / name).is_file()]


@dataclass
class GenerationManifest:
    manifest_version: int
    created_at: str
    provider: str
    model: str
    capability_revision: int
    operation: str
    route_reason: str
    renderer_version: str
    postprocess_version: str
    guard_version: str | None
    prompt_hash: str
    sampling_profile: str
    sampling_values: dict[str, Any]
    sampling_verified: bool
    max_tokens: int
    context_tokens: int | None
    context_tokens_method: str | None
    output_tokens: int
    output_chars: int
    raw_chars: int
    generation_status: str
    finish_reason: str | None
    validation_status: str | None
    scene_id: str | None = None
    beat_id: str | None = None
    constraint_ids: list[str] = field(default_factory=list)
    refs: list[SourceRef] = field(default_factory=list)
    render_params: dict[str, Any] = field(default_factory=dict)
    """PromptRenderer が解決した目安（契約の目標字数、指示字数、倍率と出典、出力上限）。"""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GenerationManifest:
        data = dict(data)
        data["refs"] = [SourceRef(**r) for r in data.get("refs", [])]
        return cls(**data)


def build_manifest(output: WriterOutput, *, provider: str = "novelai", refs: list[SourceRef] | None = None,
                   scene_id: str | None = None, beat_id: str | None = None, constraint_ids: list[str] | None = None,
                   now: dt.datetime | None = None) -> GenerationManifest:
    req = output.rendered.request
    body_hash = content_hash(json.dumps(req.body(), ensure_ascii=False, sort_keys=True))
    created = (now or dt.datetime.now(dt.timezone.utc)).isoformat(timespec="seconds")
    return GenerationManifest(
        manifest_version=MANIFEST_VERSION, created_at=created, provider=provider, model=output.route.model,
        capability_revision=output.route.profile_revision, operation=output.route.operation,
        route_reason=output.route.reason, renderer_version=output.rendered.version,
        postprocess_version=output.cleaned.version, guard_version=output.guard.version if output.guard else None,
        prompt_hash=body_hash, sampling_profile=output.route.sampling.name,
        sampling_values=dict(output.route.sampling.values), sampling_verified=output.route.sampling.verified,
        max_tokens=req.max_tokens,
        context_tokens=output.context_tokens.tokens if output.context_tokens else None,
        context_tokens_method=output.context_tokens.method if output.context_tokens else None,
        output_tokens=output.generation.output_tokens,
        output_chars=count_chars(output.cleaned.text, strip_fm=False),
        raw_chars=count_chars(output.generation.text, strip_fm=False),
        generation_status=output.generation.status, finish_reason=output.generation.finish_reason,
        validation_status=output.guard.status if output.guard else None,
        scene_id=scene_id, beat_id=beat_id, constraint_ids=list(constraint_ids or []), refs=list(refs or []),
        render_params=dict(output.rendered.params))


@dataclass(frozen=True)
class StaleRef:
    ref: SourceRef
    reason: Literal["changed", "missing"]
    current_hash: str | None


def stale_refs(manifest: GenerationManifest, repo_root: Path) -> list[StaleRef]:
    """ファイルを参照した ref を読み直し、内容が変わった・消えたものを返す（文字列で渡した ref は対象外）。"""
    out: list[StaleRef] = []
    for ref in manifest.refs:
        if not ref.path:
            continue
        path = repo_root / ref.path
        if not path.is_file():
            out.append(StaleRef(ref, "missing", None))
            continue
        current = content_hash(path.read_text(encoding="utf-8"))
        if current != ref.hash:
            out.append(StaleRef(ref, "changed", current))
    return out
