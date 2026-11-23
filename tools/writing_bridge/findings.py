"""METRON findings の required / advisory 表示。判定閾値は変えない。"""

from __future__ import annotations

from .models import ItemStatus, ReportDocument, ReportFinding

REQUIRED_METRON_CODES = frozenset({"BeatMissing", "GenerationTruncated", "coverage", "span_order", "unmapped"})
ADVISORY_METRON_CODES = frozenset({
    "TooShort",
    "BeatThin",
    "EndingRush",
    "SummaryCollapse",
})
SAVE_NEXT_ACTION = "必須なし → 保存へ"
# ルールは「自動修復の対象が残れば先に修復する」（workflow-specification.md）。計画 §16.2。
AUTO_REPAIR_NEXT_ACTION = "自動修復の対象あり → 先に repair-begin（auto）で直す"


def partition_findings(
    findings: list[ReportFinding],
) -> tuple[list[ReportFinding], list[ReportFinding], list[ReportFinding]]:
    required: list[ReportFinding] = []
    advisory: list[ReportFinding] = []
    other: list[ReportFinding] = []
    for item in findings:
        if item.code in REQUIRED_METRON_CODES:
            required.append(item)
        elif item.code in ADVISORY_METRON_CODES:
            advisory.append(item)
        else:
            other.append(item)
    return required, advisory, other


def has_required_metron(findings: list[ReportFinding]) -> bool:
    return any(item.code in REQUIRED_METRON_CODES for item in findings)


def finding_codes(items: list[ReportFinding]) -> str:
    seen: list[str] = []
    for item in items:
        if item.code and item.code not in seen:
            seen.append(item.code)
    return ", ".join(seen) if seen else "none"


def next_action_for(
    *,
    floor_met: bool | None,
    findings: list[ReportFinding],
    text_state: ItemStatus,
    blocking: bool,
    repair_active: bool,
    repair_tried: bool = False,
) -> str | None:
    if has_required_metron(findings):
        return None
    if blocking or repair_active:
        return None
    if text_state not in {ItemStatus.SUCCESS, ItemStatus.SKIPPED}:
        return None
    # 同じ run で修復を試し終えた稿（completed / escalated）は、残った対象があっても保存へ進める。
    if not repair_tried and any(item.auto_repair for item in findings):
        return AUTO_REPAIR_NEXT_ACTION
    return SAVE_NEXT_ACTION


def metron_auto_repair_label(report: ReportDocument) -> str | None:
    if report.metron is ItemStatus.SKIPPED:
        return None
    required, _, _ = partition_findings(report.findings)
    flags = [item.auto_repair for item in report.findings if item.auto_repair is not None]
    if required or any(flags):
        return "pending"
    if report.next_action == SAVE_NEXT_ACTION or flags:
        return "none"
    return None
