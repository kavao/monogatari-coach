"""Minimum Guard（計画書 §20〜23・§59、Phase 1）。生成出力を決定的なコードで検査する（LLM を使わない）。

- Entity Delta: 出力に出た固有名らしい語のうち、元の本文・設定・既知エンティティ辞書にないもの（warning）。
- Numeric Delta: 出力に出た数値（値と単位）のうち、元の本文・設定にないもの（warning）。同じ単位が
  元の本文に別の値で出ていれば、その値を添える（例: 本文は「十時間」、出力は「八時間」）。
- Instruction Leakage: 指示文の見出し・印・文が出力に混ざっていないか（fail）。
- Opening Repetition: 出力の冒頭が元の本文の文をそのまま繰り返していないか（warning）。字数不足の比較実験の
  条件 B で 2/14 件に出た形。元の本文にそのまま含まれる 8 字以上の文だけを数え、言い換え・短い台詞・本文途中の引用は数えない。
  指摘だけで、本文は削らない（削るなら原文と削除範囲を残し、削除後の字数・接続を確かめる）。

どれも「候補」を出すだけで、本文を書き換えたり採否を決めたりしない（§24 の意味検査は Phase 2）。
Original Preservation Guard は Rewrite Expand 専用なので、Rewrite を使わない Phase 1 では実行しない。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal

from metron.repair import split_sentences

from .entities import KnownEntityDictionary, unknown_candidates
from .numerics import extract_numbers
from .prompt_renderer import (
    GAP_MARK,
    SYSTEM,
    ContinueInput,
    DirectedContinueInput,
    ExpandInsertionInput,
    ExploreBranchInput,
    OperationInput,
    RenderedPrompt,
)

GUARD_VERSION = "mg-2"
Severity = Literal["warning", "fail"]
Status = Literal["pass", "warning", "fail"]

# 指示文にだけ出る見出し・言い回し（PromptRenderer nai-r1 の文面から）
LEAK_MARKERS: tuple[str, ...] = (
    GAP_MARK, "この場面の契約", "必ず含める:", "してはいけない:", "終わる位置:", "本文:", "条件:",
    "登場人物と設定は、本文と次の事実に合わせる", "続きの本文だけを出力", "挿入する文だけを出力",
)
_MIN_LEAK_LINE = 10  # 指示文の行がこの字数以上そのまま出たら漏れとみなす


@dataclass(frozen=True)
class GuardFinding:
    check: Literal["entity_delta", "numeric_delta", "instruction_leakage", "opening_repetition"]
    severity: Severity
    text: str
    start: int
    end: int
    detail: str = ""


@dataclass
class GuardReport:
    findings: list[GuardFinding] = field(default_factory=list)
    checks_run: tuple[str, ...] = ("entity_delta", "numeric_delta", "instruction_leakage", "opening_repetition")
    not_run: tuple[str, ...] = ("original_preservation（Rewrite Expand 専用）", "semantic（Phase 2）")
    version: str = GUARD_VERSION

    @property
    def status(self) -> Status:
        if any(f.severity == "fail" for f in self.findings):
            return "fail"
        return "warning" if self.findings else "pass"

    def to_dict(self) -> dict[str, object]:
        return {"status": self.status, "version": self.version, "checks_run": list(self.checks_run),
                "not_run": list(self.not_run), "findings": [asdict(f) for f in self.findings]}


def source_texts(data: OperationInput) -> tuple[str, ...]:
    """操作の入力のうち、出力と突き合わせる「元の情報」（本文・契約・既知の事実）。"""
    if isinstance(data, ContinueInput):
        return (data.text,)
    if isinstance(data, DirectedContinueInput):
        c = data.contract
        return (data.text, c.objective, c.end_condition, *c.must_include, *c.must_not, *data.canon_facts)
    if isinstance(data, ExpandInsertionInput):
        return (data.before, data.after)
    if isinstance(data, ExploreBranchInput):
        return (data.text, *data.fixed, *((data.end_condition,) if data.end_condition else ()))
    raise TypeError(type(data).__name__)


def instruction_lines(rendered: RenderedPrompt, sources: tuple[str, ...]) -> list[str]:
    """要求のうち、元の本文以外の指示文の行（system と user から本文を除いたもの）。"""
    req = rendered.request
    if req.endpoint != "chat":
        return []
    lines: list[str] = []
    for m in req.messages or ():
        content = m.get("content", "")
        for s in sorted(sources, key=len, reverse=True):
            if s:
                content = content.replace(s, "\n")
        lines.extend(line.strip(" -　") for line in content.splitlines())
    return [line for line in lines if len(line) >= _MIN_LEAK_LINE]


def check_leakage(output: str, rendered: RenderedPrompt, sources: tuple[str, ...]) -> list[GuardFinding]:
    findings: list[GuardFinding] = []
    seen: set[int] = set()
    for marker in (*LEAK_MARKERS, SYSTEM):
        start = output.find(marker)
        if start != -1 and not any(marker in s for s in sources) and start not in seen:
            seen.add(start)
            findings.append(GuardFinding("instruction_leakage", "fail", marker, start, start + len(marker), "指示文の見出し・印"))
    for line in instruction_lines(rendered, sources):
        start = output.find(line)
        if start != -1 and start not in seen:
            seen.add(start)
            findings.append(GuardFinding("instruction_leakage", "fail", line, start, start + len(line), "指示文の一行がそのまま出ている"))
    return findings


OPENING_MIN_CHARS = 8


def _story_text(data: OperationInput) -> str:
    if isinstance(data, ExpandInsertionInput):
        return data.before + data.after
    return data.text


def check_opening_repetition(output: str, data: OperationInput) -> list[GuardFinding]:
    """出力の冒頭から続く、元の本文にそのまま含まれる文の範囲を 1 件の指摘にする。

    元の文の後ろ半分だけを写した形（「カイは身を沈め、牙が…感じた。」→「牙が…感じた。」）も数える。
    """
    story = _story_text(data)
    cursor, end, count = 0, None, 0
    for sentence in split_sentences(output):
        pos = output.find(sentence, cursor)
        if pos == -1 or output[cursor:pos].strip() or len(sentence) < OPENING_MIN_CHARS or sentence not in story:
            break
        cursor = end = pos + len(sentence)
        count += 1
    if end is None:
        return []
    start = len(output) - len(output.lstrip())
    return [GuardFinding("opening_repetition", "warning", output[start:end], start, end,
                         f"冒頭で元の本文の文を {count} 文そのまま繰り返している")]


def check_numbers(output: str, sources: tuple[str, ...]) -> list[GuardFinding]:
    known = [n for s in sources for n in extract_numbers(s)]
    known_keys = {n.key for n in known}
    findings = []
    for n in extract_numbers(output):
        if n.key in known_keys:
            continue
        same_unit = sorted({k.text for k in known if k.unit == n.unit and n.unit})
        detail = f"元の情報では同じ単位が {'・'.join(same_unit)}" if same_unit else "元の情報にない数値"
        findings.append(GuardFinding("numeric_delta", "warning", n.text, n.start, n.end, detail))
    return findings


def check_entities(output: str, known: KnownEntityDictionary, sources: tuple[str, ...]) -> list[GuardFinding]:
    return [GuardFinding("entity_delta", "warning", c.text, c.start, c.end, f"{c.kind}（確度 {c.confidence}）")
            for c in unknown_candidates(output, known=known, sources=sources)]


class MinimumGuard:
    def __init__(self, known: KnownEntityDictionary | None = None) -> None:
        self.known = known or KnownEntityDictionary()

    def check(self, output: str, data: OperationInput, rendered: RenderedPrompt) -> GuardReport:
        sources = source_texts(data)
        findings = (check_leakage(output, rendered, sources) + check_opening_repetition(output, data)
                    + check_entities(output, self.known, sources) + check_numbers(output, sources))
        return GuardReport(findings=sorted(findings, key=lambda f: (f.start, f.check)))
