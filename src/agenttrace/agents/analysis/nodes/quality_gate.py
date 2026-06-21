from __future__ import annotations

from pydantic import ValidationError

from agenttrace.agents.analysis.schemas.result import AnalysisResult
from agenttrace.agents.analysis.state import AnalysisState


def quality_gate(state: AnalysisState) -> AnalysisState:
    if "final_result" not in state:
        return _legacy_quality_gate(state)

    critical_errors: list[str] = []
    warnings: list[str] = []
    final_result = state.get("final_result")

    try:
        result = AnalysisResult.model_validate(final_result)
    except ValidationError as exc:
        return {
            "quality_gate_result": {
                "warnings": [],
                "critical_errors": [f"AnalysisResult schema invalid: {exc.errors()[0]['msg']}"],
            },
            "quality_errors": ["AnalysisResult schema invalid"],
        }

    claim_ids = {claim.claim_id for claim in result.analysis_claims}
    evidence_ids = {signal.signal_id for signal in result.evidence_signals}
    task_ids = {task.get("task_id") for task in state.get("analysis_plan", {}).get("tasks", [])}

    for task_result in result.evidence_task_results:
        if task_ids and task_result.task_id not in task_ids:
            critical_errors.append(f"Unknown task_id referenced: {task_result.task_id}")
        for signal_id in task_result.evidence_signal_ids:
            if signal_id not in evidence_ids:
                critical_errors.append(f"Unknown evidence_signal_id referenced: {signal_id}")
        for verdict in task_result.claim_verdicts:
            if verdict.claim_id not in claim_ids:
                critical_errors.append(f"Unknown claim_id referenced: {verdict.claim_id}")
            for signal_id in verdict.evidence_signal_ids:
                if signal_id not in evidence_ids:
                    critical_errors.append(f"Unknown evidence_signal_id referenced: {signal_id}")

    required_ids = {
        task.get("task_id")
        for task in state.get("analysis_plan", {}).get("tasks", [])
        if task.get("required")
    }
    result_by_task = {task.task_id: task for task in result.evidence_task_results}
    missing_required = required_ids - set(result_by_task)
    if missing_required:
        critical_errors.append(f"Missing required task results: {', '.join(sorted(missing_required))}")

    insufficient_required = [
        task_id for task_id in required_ids
        if result_by_task.get(task_id) and result_by_task[task_id].status == "INSUFFICIENT_EVIDENCE"
    ]
    if insufficient_required and result.analysis_status == "completed":
        critical_errors.append("completed status conflicts with insufficient required task")

    if result.analysis_status in {"completed_with_limitations", "insufficient_evidence", "uncertain_classification"}:
        warnings.extend(result.analysis_limitations.notes)

    return {
        "quality_gate_result": {
            "warnings": warnings,
            "critical_errors": critical_errors,
        },
        "quality_warnings": warnings,
        "quality_errors": critical_errors,
        "status": "NEEDS_HUMAN_REVIEW" if critical_errors else state.get("status", "COLLECTED"),
    }


def _legacy_quality_gate(state: AnalysisState) -> AnalysisState:
    errors: list[str] = []
    warnings: list[str] = []
    evidence = state.get("evidence_signals", [])
    linked_claim_ids = {item.get("claim_id") for item in evidence if item.get("claim_id")}
    claims = state.get("claims", [])

    for claim in claims:
        claim_id = claim.get("id") or claim.get("claim_id")
        if claim_id and claim_id not in linked_claim_ids:
            if any(risk.get("risk_type") == "ANALYSIS_UNCERTAIN" for risk in state.get("risk_signals", [])):
                warnings.append(f"{claim_id}에 연결된 EvidenceSignal이 없습니다.")
            else:
                errors.append(f"{claim_id}에 연결된 EvidenceSignal이 없습니다.")

    harness_relevance = state.get("harness_relevance", {})
    if harness_relevance.get("level") == "high" and not harness_relevance.get("evidence"):
        errors.append("harness_relevance cannot be high without harness evidence.")

    if state.get("status") != "OUT_OF_SCOPE" and not state.get("followup_actions"):
        errors.append("OUT_OF_SCOPE이 아닌 분석에는 followup_actions가 필요합니다.")

    if errors:
        return {"status": "NEEDS_HUMAN_REVIEW", "quality_errors": errors, "quality_warnings": warnings}
    if warnings:
        return {"status": "UNCERTAIN", "quality_warnings": warnings}
    return {"status": "COMPLETED", "quality_warnings": warnings}
