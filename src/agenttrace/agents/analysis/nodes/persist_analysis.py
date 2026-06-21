from __future__ import annotations

import json
from pathlib import Path

from agenttrace.agents.analysis.state import AnalysisState


def build_result_json(state: AnalysisState) -> dict:
    return state.get("final_result", {})


def persist_analysis(state: AnalysisState) -> AnalysisState:
    payload = {
        "analysis_id": state.get("run_id"),
        "status": "COMPLETED",
        "analysis_result": state.get("final_result"),
        "harness_relevance": state.get("harness_relevance", {}),
        "harness_capabilities": state.get("harness_capabilities", {}),
        "negative_evidence": state.get("negative_evidence", []),
        "followup_questions": state.get("followup_questions", []),
        "trace": {
            "run_id": state.get("run_id"),
            "analysis_version": "analysis-v2",
            "input_manifest": state.get("input_manifest", {}),
            "precheck_result": state.get("precheck_result", {}),
            "claims": state.get("claims", []),
            "analysis_plan": state.get("analysis_plan", {}),
            "task_traces": state.get("task_traces", []),
            "final_result": state.get("final_result", {}),
            "quality_gate_result": state.get("quality_gate_result", {}),
        },
        "error_message": None,
    }

    output_path = state.get("output_path")
    if output_path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "callback_payload": payload,
        "persisted_analysis": payload,
    }
