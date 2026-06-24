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