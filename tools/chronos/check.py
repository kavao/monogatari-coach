"""CHRONOS の静的検査。順序循環と、有効時の人物状態。"""

from __future__ import annotations

from .graph import build_order_graph, find_cycles
from .illustration import check_chr012
from .models import Finding, Severity
from .state import findings_from_resolution, resolve_states
from .store import ChronosStore


def check_store(store: ChronosStore) -> list[Finding]:
    findings: list[Finding] = []
    findings.extend(_check_chr001(store))
    resolution = resolve_states(store)
    findings.extend(findings_from_resolution(store, resolution))
    findings.extend(check_chr012(store, resolution))
    return [item for item in findings if item.severity is not Severity.OFF]


def _check_chr001(store: ChronosStore) -> list[Finding]:
    severity = store.config.severity_for("CHR001", Severity.ERROR)
    if severity is Severity.OFF:
        return []
    graph = build_order_graph(store.events)
    findings: list[Finding] = []
    for cycle in find_cycles(graph):
        unique_ids = list(dict.fromkeys(cycle[:-1] if cycle[0] == cycle[-1] else cycle))
        if any(
            "CHR001" in store.by_id[event_id].ignored_rules()
            for event_id in unique_ids
            if event_id in store.by_id
        ):
            continue
        chain = " -> ".join(cycle)
        findings.append(
            Finding(
                rule="CHR001",
                severity=severity,
                message=f"temporal cycle: {chain}",
                events=unique_ids,
            )
        )
    return findings
