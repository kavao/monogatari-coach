"""子エピソード契約（METRON の場面フォルダの ``episodes.yaml``。新しい作品は ``_work/metron/<scene_id>/``、以前の作品は ``_metron/<scene_id>/``）と収束（OP-C）の検査。

契約の書式は ``_how_to.example/length_ops.md`` の「子エピソード契約」。減量では
局所的効果だけの子 → 持ち帰りの軽い子の順に要約へ畳み、持ち帰りは要約に残す。
出来事を物語から消す脱落（OP-S）はここでは扱わない（改稿工程）。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import unicodedata
from typing import Literal

from pydantic import Field, model_validator

from .models import BeatPlan, StrictModel
from .storage import load_model

_ID_PATTERN = r"^[A-Za-z][A-Za-z0-9_-]*$"
_BEAT_ID_PATTERN = r"^[A-Za-z][A-Za-z0-9_-]*$"
# 「雰囲気を出す」「世界観を伝える」のような抽象的な局所的効果は空とみなす。
_ABSTRACT_PAYOFF = re.compile(r"^(雰囲気|世界観|空気感|情緒|余韻)(を|が)?(出す|伝える|描く|ある|出る|醸す)?$")
_SENTENCE_RE = re.compile(r".+?(?:[。！？!?]|$)", re.DOTALL)


class StateChange(StrictModel):
    kind: Literal["info", "relation", "item", "position", "emotion", "goal", "belief"]
    who: str = Field(min_length=1)
    before: str = Field(min_length=1)
    after: str = Field(min_length=1)


class CarryBack(StrictModel):
    what: str = Field(min_length=1)
    used_at: str = Field(min_length=1)


class LocalPayoff(StrictModel):
    kind: Literal["character", "emotion", "theme", "humor", "atmosphere", "rest"]
    what: str = Field(min_length=1)

    @property
    def concrete(self) -> bool:
        return not _ABSTRACT_PAYOFF.fullmatch(self.what.strip())


class EpisodeSpan(StrictModel):
    """Beat 本文の中の範囲。開始と終了の引用は本文に一度だけ現れること。"""

    start: str = Field(min_length=1)
    end: str = Field(min_length=1)


class EpisodeChecks(StrictModel):
    deletion: Literal["pass", "fail", "unchecked"] = "unchecked"
    change: Literal["pass", "fail", "unchecked"] = "unchecked"
    connection: Literal["pass", "fail", "unchecked"] = "unchecked"
    duplication: Literal["pass", "fail", "unchecked"] = "unchecked"
    dominance: Literal["pass", "fail", "unchecked"] = "unchecked"
    strength: Literal["pass", "fail", "unchecked"] = "unchecked"


class ChildEpisode(StrictModel):
    id: str = Field(pattern=_ID_PATTERN)
    beat_id: str = Field(pattern=_BEAT_ID_PATTERN)
    span: EpisodeSpan | None = None
    # D21・6-5: 本文を書く前に設計から登録した子エピソード。範囲は本文を書いたあとに補う。
    # true のあいだは範囲が決まっていないので、収束・脱落の対象にしない（span 省略＝Beat 全体とは別）。
    span_pending: bool = False
    parent: str | None = None
    operator: Literal[
        "INTERRUPT", "PREPARE", "DISCOVER", "RELATE", "HESITATE", "CONSEQUENCE", "MIRROR", "BREATHE"
    ] | None = None
    depth: Literal[1, 2] = 1
    summary: str | None = None
    state_change: list[StateChange] = Field(default_factory=list)
    connections: list[str] = Field(default_factory=list)
    carry_back: list[CarryBack] = Field(default_factory=list)
    local_payoff: list[LocalPayoff] = Field(default_factory=list)
    est_chars: int | None = Field(default=None, ge=0)
    order_note: str | None = None
    chronos: bool = True
    checks: EpisodeChecks = Field(default_factory=EpisodeChecks)

    @model_validator(mode="after")
    def validate_pending(self) -> "ChildEpisode":
        if self.span_pending and self.span is not None:
            raise ValueError("span_pending must be false once span is written")
        return self

    @property
    def concrete_payoff(self) -> list[LocalPayoff]:
        return [item for item in self.local_payoff if item.concrete]


class EpisodesDocument(StrictModel):
    scene_id: str = Field(pattern=r"^ch\d{2,}-\d{3,}$")
    episodes: list[ChildEpisode] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_ids(self) -> "EpisodesDocument":
        ids = [item.id for item in self.episodes]
        if len(ids) != len(set(ids)):
            raise ValueError("child episode IDs must be unique")
        return self


class EpisodeError(ValueError):
    """契約が BeatPlan や本文と対応しない。"""


def load_episodes(path: str | Path) -> EpisodesDocument:
    return load_model(path, EpisodesDocument)


def validate_against_plan(document: EpisodesDocument, plan: BeatPlan, *, scene_id: str) -> None:
    if document.scene_id != scene_id:
        raise EpisodeError(f"episodes.scene_id {document.scene_id!r} does not match {scene_id!r}")
    known = {beat.id for beat in plan.beats}
    unknown = sorted({item.beat_id for item in document.episodes} - known)
    if unknown:
        raise EpisodeError("unknown beat_id in episodes: " + ", ".join(unknown))


def addition_issues(episode: ChildEpisode) -> list[str]:
    """加筆工程で子エピソードを足すときの必須条件（length_ops「追加時の規則」）。"""

    issues: list[str] = []
    if not episode.state_change:
        issues.append("state_change is empty")
    if not episode.carry_back and not episode.concrete_payoff:
        issues.append("both carry_back and a concrete local_payoff are empty (padding)")
    if episode.local_payoff and not episode.concrete_payoff:
        issues.append("local_payoff is abstract; write what the reader feels concretely")
    if not episode.connections:
        issues.append("connections is empty (no link to the parent episode)")
    if not episode.chronos:
        issues.append("an added child episode must be registered in CHRONOS (chronos: true)")
    return issues


def condense_priority(episode: ChildEpisode) -> tuple[int, int]:
    """畳む順。持ち帰りも局所的効果も無い子 → 局所的効果だけの子 → 持ち帰りの軽い子。"""

    if not episode.carry_back:
        return (0 if not episode.concrete_payoff else 1, 0)
    return (2, len(episode.carry_back))


def locate_span(text: str, episode: ChildEpisode) -> tuple[int, int]:
    """Beat 本文での子エピソードの範囲を返す。引用が無い・重複するときは失敗。"""

    normalized = unicodedata.normalize("NFC", text)
    if episode.span_pending:
        raise EpisodeError(f"{episode.id}: span is pending (registered before writing)")
    if episode.span is None:
        stripped = normalized.strip("\n")
        start = normalized.index(stripped) if stripped else 0
        return start, start + len(stripped)
    start_quote = unicodedata.normalize("NFC", episode.span.start)
    end_quote = unicodedata.normalize("NFC", episode.span.end)
    if normalized.count(start_quote) != 1 or normalized.count(end_quote) != 1:
        raise EpisodeError(f"{episode.id}: span quotes must each appear exactly once in the beat")
    start = normalized.index(start_quote)
    end = normalized.index(end_quote) + len(end_quote)
    if end <= start:
        raise EpisodeError(f"{episode.id}: span end comes before its start")
    return start, end


def splice(text: str, episode: ChildEpisode, replacement: str) -> str:
    normalized = unicodedata.normalize("NFC", text)
    start, end = locate_span(normalized, episode)
    return normalized[:start] + replacement.strip("\n") + normalized[end:]


@dataclass(frozen=True)
class CondenseCheck:
    accepted: bool
    reason: str


def validate_condense(span_text: str, candidate: str) -> CondenseCheck:
    """収束候補の形の検査。上位の意味の保存は CANON 検査か著者確認で確かめる。"""

    clean = unicodedata.normalize("NFC", candidate).strip()
    if not clean:
        return CondenseCheck(False, "candidate is empty")
    if re.search(r"<!--/?beat", clean):
        return CondenseCheck(False, "candidate contains Beat markers")
    if len(clean) >= len(unicodedata.normalize("NFC", span_text).strip()):
        return CondenseCheck(False, "condensed text is not shorter than the episode")
    if not any(part.strip() for part in _SENTENCE_RE.findall(clean)):
        return CondenseCheck(False, "condensed text has no sentence")
    return CondenseCheck(True, "accepted")


def build_condense_prompt(episode: ChildEpisode, span_text: str, *, reduce_chars: int,
                          keep_min_chars: int) -> str:
    keep = [item.what for item in episode.carry_back]
    after = [f"{item.who}: {item.after}" for item in episode.state_change]
    payoff = [item.what for item in episode.concrete_payoff]
    lines = [
        f"子エピソード {episode.id} の規定量調整（収束）。",
        "次の場面を、上位の意味が残る短い要約（一文〜数文）に畳む。",
        f"{reduce_chars}字を目安に減らす。畳んだあとの子エピソードを {keep_min_chars}字より短くしない。",
        "次の要素は必ず残す（後の場面で使われる）:",
        *(f"- {item}" for item in keep or ["（なし）"]),
        "畳んだ文から、この子エピソードで変わったことが読み取れるようにする:",
        *(f"- {item}" for item in after or ["（記録なし。元の場面の変化を残す）"]),
    ]
    if payoff:
        lines.extend(["できれば要点を残す（その場面自体が読者に与えるもの）:", *(f"- {item}" for item in payoff)])
    lines.extend([
        "元の場面の感情の向き（肯定／否定／保留）を反転させない。",
        "出来事そのものを物語からなかったことにしない。新しい出来事・人物・事実を足さない。",
        "畳む対象の本文:",
        span_text,
        "畳んだ文だけを出力する（前後の本文は出力しない）。",
    ])
    return "\n".join(lines)
