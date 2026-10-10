"""Candidate Store（計画書 §40〜47、Phase 1）。生成結果を「候補」として保存し、レビューの状態を管理する。

- 保存先は ``<root>/candidates/<candidate_id>/``。``record.json``（生成の記録と Manifest）、``raw.txt``（生出力）、
  ``output.txt``（整形後）は書いたら変えない。同じ ID の上書きはしない（再生成は新しい ID）。
- 生成の状態（complete / incomplete / error）と、レビューの状態（unreviewed / selected / rejected / adopted）は
  別の欄にする（探索機能の計画 §6.2）。レビューの状態は ``review.json`` に履歴付きで持つ。
- 途中で止めた候補（incomplete）には、§47 の 3 つの操作を用意する: 部分結果を採用（``partial=True`` で selected）、
  続きを生成（``continuation_input`` で親を記録して新しい候補を作る）、破棄（rejected）。
- ここから作品の本文・人物・世界設定などの正本へは書かない。``adopted`` は「採用が決まった」という記録で、
  正本への反映は Phase 2 の Accept / Canon Gate と既存の反映手順が受け持つ。
"""

from __future__ import annotations

import datetime as dt
import json
import re
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from metron.storage import atomic_write_text

from .manifest import GenerationManifest
from .prompt_renderer import (
    BeatContract,
    ContinueInput,
    DirectedContinueInput,
    ExpandInsertionInput,
    ExploreBranchInput,
    OperationInput,
)
from .writer import WriterOutput

ReviewStatus = Literal["unreviewed", "selected", "rejected", "adopted"]
_TRANSITIONS: dict[str, set[str]] = {
    "unreviewed": {"selected", "rejected"},
    "selected": {"adopted", "rejected", "unreviewed"},
    "rejected": {"unreviewed"},
    "adopted": set(),  # 採用後の取り消しは正本側の手順で扱う
}


class CandidateError(ValueError):
    pass


_CANDIDATE_ID = re.compile(r"c\d{8}T\d{6}-[0-9a-f]{8}")


def input_to_dict(data: OperationInput) -> dict[str, Any]:
    return {"type": type(data).__name__, **asdict(data)}


def input_from_dict(d: dict[str, Any]) -> OperationInput:
    d = dict(d)
    kind = d.pop("type")
    if kind == "ContinueInput":
        return ContinueInput(**d)
    if kind == "DirectedContinueInput":
        c = d.pop("contract")
        contract = BeatContract(**{**c, "must_include": tuple(c.get("must_include", ())), "must_not": tuple(c.get("must_not", ()))})
        return DirectedContinueInput(contract=contract, text=d["text"], canon_facts=tuple(d.get("canon_facts", ())),
                                     instruction_multiplier=d.get("instruction_multiplier"))
    if kind == "ExpandInsertionInput":
        return ExpandInsertionInput(**d)
    if kind == "ExploreBranchInput":
        return ExploreBranchInput(text=d["text"], fixed=tuple(d.get("fixed", ())), free=tuple(d.get("free", ())),
                                  end_condition=d.get("end_condition"), target_chars=d.get("target_chars", 400))
    raise CandidateError(f"未知の入力の型 {kind}")


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    parent_candidate_id: str | None
    run_id: str | None
    created_at: str
    operation: str
    model: str
    generation_status: str
    cancelled: bool
    raw_text: str
    text: str
    input: dict[str, Any]
    removals: list[dict[str, Any]]
    review_items: list[dict[str, Any]]
    flags: list[str]
    guard: dict[str, Any] | None
    manifest: dict[str, Any]
    error: str | None = None
    generation: dict[str, Any] | None = None
    """生成の要約（初回の断片までの秒数・合計秒数・試行回数・終了理由・出力トークン数）。古い記録には無い。"""

    @property
    def incomplete(self) -> bool:
        return self.generation_status == "incomplete"


@dataclass
class ReviewState:
    status: ReviewStatus = "unreviewed"
    partial: bool = False
    history: list[dict[str, Any]] = field(default_factory=list)


class CandidateStore:
    def __init__(self, root: Path, *, clock: Any = None) -> None:
        self.root = Path(root)
        self._clock = clock or (lambda: dt.datetime.now(dt.timezone.utc))

    # 保存 -------------------------------------------------------------------
    def save(self, output: WriterOutput, manifest: GenerationManifest, *, parent_id: str | None = None,
             run_id: str | None = None) -> Candidate:
        if output.data is None:
            raise CandidateError("WriterOutput に入力（data）がない")
        if parent_id is not None:
            self.load(parent_id)  # 親が存在することを確かめる
        now = self._clock()
        cid = f"c{now.strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:8]}"
        cand = Candidate(
            candidate_id=cid, parent_candidate_id=parent_id, run_id=run_id,
            created_at=now.isoformat(timespec="seconds"), operation=output.route.operation, model=output.route.model,
            generation_status=output.generation.status, cancelled=output.generation.cancelled,
            raw_text=output.generation.text, text=output.cleaned.text, input=input_to_dict(output.data),
            removals=[asdict(r) for r in output.cleaned.removals], review_items=[asdict(r) for r in output.cleaned.review],
            flags=list(output.cleaned.flags), guard=output.guard.to_dict() if output.guard else None,
            manifest=manifest.to_dict(), error=output.generation.error,
            generation={k: getattr(output.generation, k) for k in
                        ("first_chunk_sec", "total_sec", "attempts", "finish_reason", "output_tokens", "http_status")})
        d = self._dir(cid)
        d.mkdir(parents=True, exist_ok=False)  # 同じ ID の上書きはしない
        for name, text in (("record.json", json.dumps(asdict(cand), ensure_ascii=False, indent=2)),
                           ("raw.txt", cand.raw_text), ("output.txt", cand.text)):
            with (d / name).open("x", encoding="utf-8", newline="\n") as f:
                f.write(text)
        self._write_review(cid, ReviewState(history=[self._event("created", "unreviewed", "")]))
        return cand

    # 読み出し ---------------------------------------------------------------
    def load(self, candidate_id: str) -> Candidate:
        path = self._dir(candidate_id) / "record.json"
        if not path.is_file():
            raise CandidateError(f"候補がない: {candidate_id}")
        return Candidate(**json.loads(path.read_text(encoding="utf-8")))

    def review(self, candidate_id: str) -> ReviewState:
        path = self._dir(candidate_id) / "review.json"
        if not path.is_file():
            raise CandidateError(f"候補がない: {candidate_id}")
        return ReviewState(**json.loads(path.read_text(encoding="utf-8")))

    def find(self, *, generation_status: str | None = None, review_status: str | None = None) -> list[Candidate]:
        base = self.root / "candidates"
        out = []
        for d in sorted(base.iterdir()) if base.is_dir() else []:
            if not (d / "record.json").is_file():
                continue
            cand = self.load(d.name)
            if generation_status and cand.generation_status != generation_status:
                continue
            if review_status and self.review(d.name).status != review_status:
                continue
            out.append(cand)
        return out

    # レビュー ---------------------------------------------------------------
    def set_review(self, candidate_id: str, status: ReviewStatus, *, note: str = "", partial: bool = False) -> ReviewState:
        cand = self.load(candidate_id)
        state = self.review(candidate_id)
        if status not in _TRANSITIONS[state.status]:
            raise CandidateError(f"{state.status} から {status} へは変えられない")
        if status in ("selected", "adopted"):
            if cand.generation_status == "error":
                raise CandidateError("生成に失敗した候補は採用できない")
            if cand.incomplete and not (partial or state.partial):
                raise CandidateError("途中で止めた候補は partial=True（部分結果を採用）のときだけ選べる")
        state.partial = (partial or state.partial) if status in ("selected", "adopted") else False
        state.status = status
        state.history.append(self._event("review", status, note, partial=state.partial))
        self._write_review(candidate_id, state)
        return state

    # 途中で止めた候補（§47） ---------------------------------------------------
    def incomplete_actions(self, candidate_id: str) -> list[str]:
        cand = self.load(candidate_id)
        if not cand.incomplete:
            return []
        actions = ["discard"]
        if cand.text.strip():
            actions[:0] = ["adopt_partial", "continue"]
        return actions

    def adopt_partial(self, candidate_id: str, note: str = "") -> ReviewState:
        return self.set_review(candidate_id, "selected", note=note or "部分結果を採用", partial=True)

    def discard(self, candidate_id: str, note: str = "") -> ReviewState:
        return self.set_review(candidate_id, "rejected", note=note or "破棄")

    def continuation_input(self, candidate_id: str) -> tuple[str, OperationInput]:
        """「続きを生成」用の入力。止めた時点までの整形済み本文を元の本文につなげる。

        新しい生成は ``save(..., parent_id=candidate_id)`` で親を記録して保存する（元の候補は上書きしない）。
        """
        cand = self.load(candidate_id)
        if not cand.incomplete:
            raise CandidateError("続きを生成できるのは途中で止めた候補だけ")
        data = input_from_dict(cand.input)
        partial = cand.text
        if isinstance(data, ContinueInput):
            return cand.operation, ContinueInput(data.text + partial, data.target_chars)
        if isinstance(data, DirectedContinueInput):
            return cand.operation, DirectedContinueInput(data.text + partial, data.contract, data.canon_facts,
                                                         data.instruction_multiplier)
        if isinstance(data, ExploreBranchInput):
            return cand.operation, ExploreBranchInput(data.text + partial, data.fixed, data.free, data.end_condition,
                                                      data.target_chars)
        assert isinstance(data, ExpandInsertionInput)
        return cand.operation, ExpandInsertionInput(data.before + partial, data.after, data.target_chars)

    # 内部 -------------------------------------------------------------------
    def _dir(self, candidate_id: str) -> Path:
        # ID は save() が作る形式だけを受け付ける。Windows のドライブ相対（"C:outside"）や絶対パスを通さない
        if not isinstance(candidate_id, str) or not _CANDIDATE_ID.fullmatch(candidate_id):
            raise CandidateError(f"不正な候補 ID: {candidate_id!r}")
        base = (self.root / "candidates").resolve()
        path = (base / candidate_id).resolve()
        if path.parent != base:
            raise CandidateError(f"候補の保存先の外を指す ID: {candidate_id!r}")
        return path

    def _event(self, kind: str, status: str, note: str, **extra: Any) -> dict[str, Any]:
        return {"at": self._clock().isoformat(timespec="seconds"), "event": kind, "status": status, "note": note, **extra}

    def _write_review(self, candidate_id: str, state: ReviewState) -> None:
        atomic_write_text(self._dir(candidate_id) / "review.json", json.dumps(asdict(state), ensure_ascii=False, indent=2))
