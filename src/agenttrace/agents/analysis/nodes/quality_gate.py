from __future__ import annotations

import time

from pydantic import ValidationError

from agenttrace.agents.analysis.schemas.result import AnalysisResult
from agenttrace.agents.analysis.state import AnalysisState
from agenttrace.logging_config import get_logger

logger = get_logger(__name__)

def quality_gate(state: AnalysisState) -> AnalysisState:
    _t = time.perf_counter()
    run_id = state.get("run_id", "-")
    log = logger.bind(node="quality_gate", run_id=run_id)
    log.info("시작")

    if "final_result" not in state:
        log.warning("final_result 없음 — finalize_analysis가 완료됐는지 확인하세요",
                    duration_ms=int((time.perf_counter() - _t) * 1000))
        return {"quality_gate_result": {"warnings": [], "critical_errors": []}}

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

    log.info("완료", errors=len(critical_errors), warnings=len(warnings), duration_ms=int((time.perf_counter() - _t) * 1000))
    return {
        "quality_gate_result": {
            "warnings": warnings,
            "critical_errors": critical_errors,
        },
        "quality_warnings": warnings,
        "quality_errors": critical_errors,
        "status": "NEEDS_HUMAN_REVIEW" if critical_errors else state.get("status", "COLLECTED"),
    }

