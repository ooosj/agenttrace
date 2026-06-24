from __future__ import annotations

import time

from agenttrace.agents.analysis.state import AnalysisState
from agenttrace.logging_config import get_logger

logger = get_logger(__name__)

AGENT_TYPE_MAP = {
    "MCP_SERVER": "MCP",
    "MCP_CLIENT": "MCP",
    "SKILL": "Skill",
    "EVAL_HARNESS": "Eval",
    "TOOL_USE": "ToolUse",
    "AGENT_FRAMEWORK": "Framework",
    "OTHER": "Other",
    "UNKNOWN": "Unknown",
}


def repository_synthesizer(state: AnalysisState) -> AnalysisState:
    _t = time.perf_counter()
    run_id = state.get("run_id", "-")
    log = logger.bind(node="repository_synthesizer", run_id=run_id)
    log.info("시작")
    tasks = state.get("analysis_plan", {}).get("tasks", [])

    results_by_id = {
        result.get("task_id"): result
        for result in state.get("task_results", [])
    }
    required_tasks = [task for task in tasks if task.get("required")]
    required_results = [results_by_id.get(task.get("task_id")) for task in required_tasks]

    if required_tasks and any(not result for result in required_results):
        analysis_status = "insufficient_evidence"
    elif any(result and result.get("status") == "INSUFFICIENT_EVIDENCE" for result in required_results):
        analysis_status = "insufficient_evidence"
    elif any(result.get("status") == "INSUFFICIENT_EVIDENCE" for result in state.get("task_results", [])):
        analysis_status = "completed_with_limitations"
    elif not state.get("claims"):
        analysis_status = "uncertain_classification"
    else:
        analysis_status = "completed"

    metadata = state.get("metadata", {}) or {}
    primary_language = metadata.get("primary_language") or metadata.get("language") or "Unknown"
    agent_type = AGENT_TYPE_MAP.get(str(state.get("agent_type", "Unknown")), state.get("agent_type") or "Unknown")
    if agent_type in {None, "Unknown"}:
        agent_type = _infer_agent_type(state)

    # Verify agent_type classification against verified evidence
    if agent_type == "MCP":
        has_verified_mcp_claim = False
        claims_by_id = {c.get("claim_id") or c.get("id"): c for c in state.get("claims", [])}
        for task_res in state.get("task_results", []):
            for cv in task_res.get("claim_verdicts", []):
                if cv.get("verdict") in {"SUPPORTED", "PARTIALLY_SUPPORTED", "DOCUMENTED"}:
                    claim = claims_by_id.get(cv.get("claim_id"), {})
                    claim_text = claim.get("claim_text", "").lower()
                    if "mcp" in claim_text or "model context protocol" in claim_text:
                        has_verified_mcp_claim = True
                        break
            if has_verified_mcp_claim:
                break
        if not has_verified_mcp_claim:
            readme_text = state.get("readme", "").lower()
            if "agent" in readme_text or "sandbox" in readme_text or "workflow" in readme_text:
                agent_type = "Framework"
            else:
                agent_type = "Unknown"

    if agent_type not in {"MCP", "Skill", "Eval", "ToolUse", "Framework", "Other", "Unknown"}:
        agent_type = "Unknown"

    # Tech stack summary linkage to actual evidence paths
    evidence_paths = []
    for sig in state.get("evidence_signals", []):
        path = sig.get("path")
        if path and path not in evidence_paths:
            evidence_paths.append(path)

    if evidence_paths:
        paths_str = ", ".join(evidence_paths[:3])
        ko_summary = f"{primary_language} 기반 프로젝트 신호가 확인됩니다. (근거 파일: {paths_str})"
        en_summary = f"Static signals indicate a {primary_language}-based project. (Evidence files: {paths_str})"
    else:
        ko_summary = f"{primary_language} 기반 정적 신호가 확인됩니다."
        en_summary = f"Static signals indicate a {primary_language}-based project."

    # Record analysis limitations notes
    limitations_notes = list(state.get("analysis_limitations", {}).get("notes", []))
    
    evidence_signals = state.get("evidence_signals", [])
    has_implementation_evidence = any(sig.get("signal_type") == "IMPLEMENTATION_EVIDENCE" for sig in evidence_signals)
    has_documentation_evidence = any(sig.get("signal_type") == "DOCUMENTATION_CORROBORATION" for sig in evidence_signals)
    
    if evidence_signals and not has_implementation_evidence:
        if analysis_status == "completed":
            analysis_status = "completed_with_limitations"
        limitations_notes.extend([
            "대부분의 Claim이 구현 코드가 아닌 문서 근거로 검토됨",
        ])
        if agent_type == "MCP":
            limitations_notes.append("일부 기능은 실제 MCP 서버 구현 경로에서 확인되지 않음")
        else:
            limitations_notes.append("일부 기능은 실제 구현 경로에서 확인되지 않음")

    source_files = state.get("source_files", [])
    if len(source_files) == 1:
        limitations_notes.append("분석 대상 소스 파일이 1개로 제한적입니다.")
    elif len(source_files) == 0:
        limitations_notes.append("소스 파일 원문이 수집되지 않아 제한적인 분석만 수행되었습니다.")

    follow_up_guide = {
        "ko": "README 및 탐지된 근거 신호(Evidence Signals) 목록을 참고하여 실제 샌드박스 보안 경계 및 OCI 호환 여부를 소스 코드에서 재차 확인하십시오.",
        "en": "Refer to the README and detected Evidence Signals to manually verify sandbox security boundaries and OCI compatibility within the source code."
    }

    log.info("완료", status=analysis_status, agent_type=agent_type, duration_ms=int((time.perf_counter() - _t) * 1000))
    return {
        "synthesis": {
            "analysis_status": analysis_status,
            "agent_type": agent_type,
            "tech_stack_summary": {
                "ko": ko_summary,
                "en": en_summary,
            },
        },
        "follow_up_guide": follow_up_guide,
        "analysis_limitations": {
            "missing_inputs": state.get("analysis_limitations", {}).get("missing_inputs", []),
            "truncated_inputs": state.get("analysis_limitations", {}).get("truncated_inputs", []),
            "notes": list(dict.fromkeys(limitations_notes)),
        }
    }


def _infer_agent_type(state: AnalysisState) -> str:
    metadata = state.get("metadata", {}) or {}
    text = " ".join([
        str(metadata.get("description", "")),
        " ".join(metadata.get("topics", []) or []),
        state.get("readme", ""),
        " ".join(item.get("path", "") for item in state.get("file_tree", [])),
    ]).lower()
    if "mcp" in text:
        return "MCP"
    if "skill" in text:
        return "Skill"
    if "eval" in text or "benchmark" in text or "harness" in text:
        return "Eval"
    if "tool" in text:
        return "ToolUse"
    if "agent" in text or "workflow" in text:
        return "Framework"
    return "Unknown"
