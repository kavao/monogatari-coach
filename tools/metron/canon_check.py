"""CANON 不変チェック（length_ops「事実確認」）の指示と判定。provider は呼ばない。

検査は別の呼び出しとして行い、モデルの自己申告を採用の根拠にしない。ここでは
検査用の指示文を作り、返ってきた JSON を事実単位で判定するだけである。
"""

from __future__ import annotations

import json
import re
from typing import Annotated, Literal

from pydantic import Field, ValidationError

from .episodes import ChildEpisode
from .models import StrictModel


class FactFinding(StrictModel):
    kind: Literal["added", "changed", "missing"]
    fact: str = Field(min_length=1)
    evidence: str = ""
    # missing のとき、要約文で上位の意味として覆われているなら、その要約文を書く。
    covered_by: str | None = None


class CondenseFinding(StrictModel):
    episode_id: str
    state_change_kept: bool
    carry_back_kept: bool
    emotion_direction_kept: bool


class CanonCheckResult(StrictModel):
    completed: Literal[True]
    input_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    facts_before: list[Annotated[str, Field(pattern=r"\S")]] = Field(min_length=1)
    facts_after: list[Annotated[str, Field(pattern=r"\S")]] = Field(min_length=1)
    findings: list[FactFinding]
    condense: list[CondenseFinding]


class EventConflict(StrictModel):
    event_id: str
    description: str = Field(min_length=1)
    text_evidence: str = ""


class PrecheckResult(StrictModel):
    completed: Literal[True]
    input_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    facts: list[Annotated[str, Field(pattern=r"\S")]] = Field(min_length=1)
    conflicts: list[EventConflict]


class CanonCheckError(ValueError):
    """検査結果が JSON として読めない、または形が違う。"""


_FENCE = re.compile(r"```(?:json)?\s*(\{.*\})\s*```", re.DOTALL)


def _parse(text: str, model):
    match = _FENCE.search(text)
    body = match.group(1) if match else text.strip()
    try:
        return model.model_validate(json.loads(body))
    except (json.JSONDecodeError, ValidationError) as error:
        raise CanonCheckError(f"canon check result is not valid: {error}") from error


def parse_canon_check(text: str) -> CanonCheckResult:
    return _parse(text, CanonCheckResult)


def parse_precheck(text: str) -> PrecheckResult:
    return _parse(text, PrecheckResult)


def evaluate_canon_check(
    result: CanonCheckResult, *, operation: str, episode: ChildEpisode | None = None
) -> tuple[bool, list[str]]:
    """a 追加・b 変更は常に不合格。c 欠落は収束の要約で覆われ、CHK-C1〜C3 が通るときだけ可。"""

    reasons: list[str] = []
    for item in result.findings:
        if item.kind == "added":
            reasons.append(f"added fact (OP-E): {item.fact}")
        elif item.kind == "changed":
            reasons.append(f"changed fact (OP-W): {item.fact}")
        elif operation != "condense" or not item.covered_by:
            reasons.append(f"missing fact (OP-S): {item.fact}")
    if operation == "condense":
        target = episode.id if episode else None
        checks = [item for item in result.condense if target is None or item.episode_id == target]
        if not checks:
            reasons.append("condense check (CHK-C1-C3) is missing")
        for item in checks:
            if not item.state_change_kept:
                reasons.append(f"CHK-C1 state change lost in {item.episode_id} (OP-S)")
            if not item.carry_back_kept:
                reasons.append(f"CHK-C2 carry-back lost in {item.episode_id} (OP-S)")
            if not item.emotion_direction_kept:
                reasons.append(f"CHK-C3 emotional direction reversed in {item.episode_id}")
    return not reasons, reasons


_SCHEMA = """{
  "completed": true,
  "input_sha256": "<指示に記載された入力ハッシュをそのまま写す>",
  "facts_before": ["調整前の本文と既出事実リストにある事実を一文ずつ"],
  "facts_after": ["調整後の本文にある事実を一文ずつ"],
  "findings": [
    {"kind": "added | changed | missing", "fact": "事実", "evidence": "根拠の本文",
     "covered_by": "missing のとき、上位の意味として覆っている要約文（無ければ null）"}
  ],
  "condense": [
    {"episode_id": "ID", "state_change_kept": true, "carry_back_kept": true,
     "emotion_direction_kept": true}
  ]
}"""


def build_canon_check_prompt(
    *,
    operation: str,
    known_facts: str,
    original: str,
    candidate: str,
    input_sha256: str,
    episode: ChildEpisode | None = None,
) -> str:
    lines = [
        "あなたは小説の事実確認の担当です。文章の良し悪しは評価しません。",
        "物語世界で起きたこと（出来事・行動・所持品・関係・情報の授受・心境の変化・過去・因果）が、",
        "調整の前後で変わっていないかだけを、事実を一文ずつに分けて照合してください。",
        "",
        "判定:",
        "- added: 調整後の本文にあり、調整前の本文にも既出事実リストにも無い事実",
        "- changed: 既出事実と矛盾する調整後の本文",
        "- missing: 調整前の本文にあり、調整後の本文から消えた事実（調整前の本文に無かった事実は対象外）",
        "- 言い回し・描写の細かさ・感覚の書き足しは事実の変化に数えない",
        "",
        "既出事実リスト:",
        known_facts or "（調整前の本文に書かれていることだけ）",
        "",
        "調整前の本文:",
        original,
        "",
        "調整後の本文:",
        candidate,
    ]
    if operation == "condense" and episode is not None:
        lines.extend([
            "",
            f"これは子エピソード {episode.id} を要約へ畳む収束です。消えた事実が要約文で上位の意味として",
            "覆われていれば、missing の covered_by にその要約文を書いてください。次も確かめてください:",
            "- state_change_kept: 次の変化が要約文から読み取れるか: "
            + ("、".join(f"{item.who}: {item.after}" for item in episode.state_change) or "（記録なし）"),
            "- carry_back_kept: 次の要素が要約文に残っているか: "
            + ("、".join(item.what for item in episode.carry_back) or "（なし。true とする）"),
            "- emotion_direction_kept: 元の場面の感情の向き（肯定／否定／保留）が反転していないか",
        ])
    lines.extend(["", f"入力ハッシュ: {input_sha256}",
                  "検査を最後まで終えたときだけ completed: true を返し、全項目を省略せず書く。",
                  "事実を最低一文ずつ記録する。指摘なしなら findings は空配列とする。",
                  "収束では condense に CHK-C1〜C3 の結果を書き、収束以外では空配列とする。",
                  "次の JSON だけを出力してください:", _SCHEMA])
    return "\n".join(lines)


_PRECHECK_SCHEMA = """{
  "completed": true,
  "input_sha256": "<指示に記載された入力ハッシュをそのまま写す>",
  "facts": ["本文にある事実を一文ずつ"],
  "conflicts": [{"event_id": "EVT-0000", "description": "食い違いの内容", "text_evidence": "根拠の本文"}]
}"""


def build_precheck_prompt(*, events_text: str, text: str, input_sha256: str) -> str:
    return "\n".join([
        "あなたは小説の事実確認の担当です。",
        "時系列イベントの記録と本文が食い違っていないかを確かめてください。",
        "本文がイベントより詳しいこと、イベントに無い事実が本文にあることは食い違いに数えません。",
        "両立しない記述（本文では鍵を渡したのに、イベントでは渡していない等）だけを conflicts に挙げます。",
        "",
        "イベント:",
        events_text,
        "",
        "本文:",
        text,
        "",
        f"入力ハッシュ: {input_sha256}",
        "照合を完了したときだけ completed: true を返す。事実を最低一文記録し、conflicts も省略しない。",
        "次の JSON だけを出力してください:",
        _PRECHECK_SCHEMA,
    ])
