from __future__ import annotations

from agenttrace.agents.analysis.schemas.result import EvidenceTaskResult
from agenttrace.agents.analysis.state import AnalysisState


def task_result_merge(state: AnalysisState) -> AnalysisState:
    task_id = state.get("current_task_id")
    part_results = state.get("task_part_results", [])
    evidence_signals: list[dict] = []
    claim_verdicts: list[dict] = []

    for result in part_results:
        evidence_signals.extend(result.get("evidence_signals", []))
        claim_verdicts.extend(result.get("claim_verdicts", []))

    status = "RESOLVED" if any(
        verdict.get("verdict") in {"SUPPORTED", "PARTIALLY_SUPPORTED", "CONTRADICTED", "NOT_FOUND", "DOCUMENTED"}
        for verdict in claim_verdicts
    ) else "INSUFFICIENT_EVIDENCE"
    task_result = EvidenceTaskResult(
        task_id=task_id or "unknown-task",
        status=status,
        claim_verdicts=claim_verdicts,
        evidence_signal_ids=[signal["signal_id"] for signal in evidence_signals],
        search_limit_reached=False,
        limitations=[] if status == "RESOLVED" else ["insufficient evidence"],
    )

    return {
        "pending_task_result": task_result.model_dump(),
        "pending_evidence_signals": evidence_signals,
    }
