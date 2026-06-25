from __future__ import annotations

import time

from pydantic import ValidationError

from agenttrace.agents.analysis.schemas.result import AnalysisResult
from agenttrace.agents.analysis.source_inventory import SourceInventory
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

    warnings.extend(_validate_confirmed_evidence(state, result))

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


def _validate_confirmed_evidence(state: AnalysisState, result: AnalysisResult) -> list[str]:
    warnings: list[str] = []
    refs_by_id = {ref.id: ref.model_dump() for ref in result.evidence_refs}
    inventory = SourceInventory.from_state(state)

    confirmed_ref_ids: set[str] = set()
    for area in result.area_findings:
        if area.status != "confirmed":
            continue
        for finding in area.findings:
            confirmed_ref_ids.update(finding.evidence_refs)

    for ref_id in sorted(confirmed_ref_ids):
        ref = refs_by_id.get(ref_id)
        if ref is None:
            warnings.append(f"confirmed finding references unknown evidence ref: {ref_id}")
            continue

        for field in ("content_excerpt", "content_hash", "line_start", "line_end"):
            if ref.get(field) in (None, ""):
                warnings.append(f"confirmed evidence ref missing {field}")

        if inventory.records and ref.get("path") in inventory.records:
            warnings.extend(inventory.validate_evidence_ref(ref))

    return warnings
