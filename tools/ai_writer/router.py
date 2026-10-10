"""Operation Router と Sampling Profile（計画書 §5〜6、Phase 1）。

- 操作ごとの既定モデルは Capability Profile の ``preferred_operations`` から引く（Phase 0 の結論で 3 操作とも GLM-4.6）。
- 利用者がモデルを明示したら、そのモデルをそのまま使う。使えない場合は理由を返し、別モデルへ黙って切り替えない
  （探索機能の計画 ``20261009_ai_writer_creative_exploration.md`` §2）。
- Sampling Profile は抽象名（creative / stable / precise）をモデル別の値に変換する。Provider 間で値を直接共有しない（§6）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from .profiles import CapabilityProfile, EndpointKind, ProfileError, default_model_for

ENDPOINT_FOR: dict[str, EndpointKind] = {
    "continue": "completions",
    "directed_continue": "chat",
    "expand_insertion": "chat",
}
SamplingName = Literal["creative", "stable", "precise"]


@dataclass(frozen=True)
class SamplingProfile:
    name: SamplingName
    values: dict[str, Any]
    verified: bool
    note: str


# NovelAI の OpenAI 互換エンドポイント（GLM-4.6 / Xialong）向け。stable だけが Phase 0 で測った値。
NOVELAI_SAMPLING: dict[str, SamplingProfile] = {
    "stable": SamplingProfile("stable", {"temperature": 0.8, "top_p": 0.9}, True,
                              "Phase 0 の Spike・Expand 比較・日本語 Benchmark で使った値"),
    "creative": SamplingProfile("creative", {"temperature": 1.0, "top_p": 0.95}, False,
                                "未検証。探索機能の評価（E2）で効果を確かめる"),
    "precise": SamplingProfile("precise", {"temperature": 0.6, "top_p": 0.85}, False,
                               "未検証。編集系（Phase 3）で効果を確かめる"),
}


class RouteError(ValueError):
    pass


@dataclass(frozen=True)
class Route:
    operation: str
    model: str
    endpoint: EndpointKind
    sampling: SamplingProfile
    reason: Literal["default", "explicit"]
    profile_revision: int


class OperationRouter:
    def __init__(self, profiles: dict[str, CapabilityProfile]) -> None:
        self.profiles = profiles

    def resolve(self, operation: str, *, model: str | None = None, sampling: SamplingName = "stable") -> Route:
        if operation not in ENDPOINT_FOR:
            raise RouteError(f"Phase 1 の Router が扱わない操作: {operation}（{', '.join(ENDPOINT_FOR)}）")
        endpoint = ENDPOINT_FOR[operation]
        if model is None:
            try:
                chosen = default_model_for(operation, self.profiles)
            except ProfileError as e:
                raise RouteError(str(e)) from e
            if chosen is None:
                raise RouteError(f"{operation} の既定モデルがない（preferred_operations に未設定）。モデルを明示する")
            reason: Literal["default", "explicit"] = "default"
        else:
            if model not in self.profiles:
                raise RouteError(f"未知のモデル {model}。別モデルへは切り替えない")
            chosen = model
            reason = "explicit"
        profile = self.profiles[chosen]
        if endpoint not in profile.endpoints:
            raise RouteError(f"{chosen} は {operation} に要る {endpoint} エンドポイントを持たない。別モデルへは切り替えない")
        if profile.provider != "novelai":
            raise RouteError(f"{chosen} の provider {profile.provider} の Sampling 変換がない")
        if sampling not in NOVELAI_SAMPLING:
            raise RouteError(f"未知の Sampling Profile {sampling}")
        return Route(operation, chosen, endpoint, NOVELAI_SAMPLING[sampling], reason, profile.revision)
