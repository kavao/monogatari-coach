"""Capability Profile の読み込みと検証（計画書 §3）。

プロファイルは ``tools/ai_writer/profiles/*.yaml``。各 capability は ``verified`` を持ち、
``verified: true``（実測）なら ``source`` と ``verified_at`` を必須にして、推測と実測を区別する。
capability ごとの追加欄（``tokens``、``concurrency``、``chars_per_token_output`` など）はそのまま保持する。
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

PROFILE_DIR = Path(__file__).resolve().parent / "profiles"
OPERATIONS = ("continue", "directed_continue", "expand_insertion", "expand_rewrite")
EndpointKind = Literal["chat", "completions"]


class ProfileError(ValueError):
    """プロファイルの形式・整合の誤り。"""


class Capability(BaseModel):
    """1 つの能力。共通欄のほかは capability ごとの追加欄として保持する。"""

    model_config = ConfigDict(extra="allow")

    supported: bool | Literal["unknown", "partial"] | None = None
    verified: bool
    source: str | None = None
    verified_at: dt.date | None = None

    @model_validator(mode="after")
    def _verified_needs_evidence(self) -> Capability:
        if self.verified and (not self.source or self.verified_at is None):
            raise ValueError("verified: true には source と verified_at が要る（推測と実測を区別するため）")
        return self

    def extra(self, key: str, default: Any = None) -> Any:
        return (self.model_extra or {}).get(key, default)


class CapabilityProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    provider: str
    model: str
    family: str
    revision: int
    requires_tier: str | None = None
    endpoints: dict[EndpointKind, str]
    capabilities: dict[str, Capability]
    expand_modes: dict[str, Capability] = Field(default_factory=dict)
    preferred_operations: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _lift_expand_modes(cls, data: Any) -> Any:
        # YAML では capabilities.expand_modes に入れ子で書く。型を分けるため取り出す。
        if isinstance(data, dict):
            caps = dict(data.get("capabilities") or {})
            if "expand_modes" in caps:
                data = {**data, "capabilities": caps, "expand_modes": caps.pop("expand_modes")}
        return data

    @field_validator("preferred_operations")
    @classmethod
    def _known_operations(cls, value: list[str]) -> list[str]:
        unknown = [v for v in value if v not in OPERATIONS]
        if unknown:
            raise ValueError(f"未知の操作 {unknown}（{', '.join(OPERATIONS)} のどれか）")
        return value

    # ---- よく使う値 ----

    def capability(self, name: str) -> Capability | None:
        return self.capabilities.get(name)

    def supports(self, name: str) -> bool:
        cap = self.capability(name)
        return bool(cap and cap.supported is True)

    def endpoint(self, kind: EndpointKind) -> str:
        if kind not in self.endpoints:
            raise ProfileError(f"{self.id}: endpoint {kind} がない")
        return self.endpoints[kind]

    @property
    def context_limit_tokens(self) -> int | None:
        cap = self.capability("context_limit")
        return int(cap.extra("tokens")) if cap and cap.extra("tokens") is not None else None

    @property
    def concurrency(self) -> int:
        cap = self.capability("rate_limit")
        value = cap.extra("concurrency") if cap else None
        return int(value) if value else 1

    def chars_per_token(self, stat: Literal["p10", "median", "p90"] = "median") -> float | None:
        cap = self.capability("token_count")
        table = cap.extra("chars_per_token_output") if cap else None
        if isinstance(table, dict) and table.get(stat) is not None:
            return float(table[stat])
        return None


def load_profile(path: Path) -> CapabilityProfile:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        return CapabilityProfile.model_validate(raw)
    except (yaml.YAMLError, ValueError) as e:
        raise ProfileError(f"{path.name}: {e}") from e


def load_profiles(directory: Path = PROFILE_DIR) -> dict[str, CapabilityProfile]:
    """``model`` をキーにした辞書を返す。同じ model の重複はエラー。"""
    profiles: dict[str, CapabilityProfile] = {}
    for path in sorted(directory.glob("*.yaml")):
        profile = load_profile(path)
        if profile.model in profiles:
            raise ProfileError(f"model {profile.model} のプロファイルが重複（{path.name}）")
        profiles[profile.model] = profile
    return profiles


def default_model_for(operation: str, profiles: dict[str, CapabilityProfile]) -> str | None:
    """``preferred_operations`` にその操作を持つモデル（Operation Router 初期値の素材）。複数ならエラー。"""
    if operation not in OPERATIONS:
        raise ProfileError(f"未知の操作 {operation}")
    hits = [m for m, p in profiles.items() if operation in p.preferred_operations]
    if len(hits) > 1:
        raise ProfileError(f"{operation} の既定モデルが複数 {hits}")
    return hits[0] if hits else None
