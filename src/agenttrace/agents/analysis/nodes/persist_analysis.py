from __future__ import annotations

import json
import time
from pathlib import Path

from agenttrace.agents.analysis.state import AnalysisState
from agenttrace.services.report_renderer import render_markdown_report
from agenttrace.logging_config import get_logger

logger = get_logger(__name__)


def build_result_json(state: AnalysisState) -> dict:
    return state.get("final_result", {})


def persist_analysis(state: AnalysisState) -> AnalysisState:
    _t = time.perf_counter()
    run_id = state.get("run_id", "-")
    log = logger.bind(node="persist_analysis", run_id=run_id)
    log.info("시작")

    final_result = state.get("final_result", {})
    report_sections = final_result.get("report_sections", [])
    report_markdown = render_markdown_report(report_sections) if report_sections else ""
    payload = {
        "analysis_id": state.get("run_id"),
        "status": "COMPLETED",
        "analysis_result": final_result,
        "analysis_report": {
            "lang": "ko",
            "title": "AgentTrace 기술 분석 보고서",
            "body_markdown": report_markdown,
        },
        "trace": {
            "run_id": state.get("run_id"),
            "analysis_version": "analysis-v2",
            "input_manifest": state.get("input_manifest", {}),
            "precheck_result": state.get("precheck_result", {}),
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

    log.info("완료", duration_ms=int((time.perf_counter() - _t) * 1000))
    return {
        "callback_payload": payload,
    }