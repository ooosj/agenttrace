from __future__ import annotations

import json
import logging
from pathlib import Path
import httpx

from agenttrace.agents.analysis.state import AnalysisState
from agenttrace.config import get_settings

logger = logging.getLogger(__name__)


def _public_analysis(state: AnalysisState) -> dict:
    return {
        "run_id": state.get("run_id"),
        "repository_id": state.get("repository_id"),
        "full_name": state.get("full_name"),
        "github_url": state.get("github_url"),
        "status": state.get("status"),
        "agent_type": state.get("agent_type"),
        "relevance_score": state.get("relevance_score"),
        "classification_reason": state.get("classification_reason"),
        "claims": state.get("claims", []),
        "evidence_signals": state.get("evidence_signals", []),
        "risk_signals": state.get("risk_signals", []),
        "followup_actions": state.get("followup_actions", []),
        "followup_guide": state.get("followup_guide", []),
        "harness_relevance": state.get("harness_relevance", {}),
        "harness_capabilities": state.get("harness_capabilities", {}),
        "negative_evidence": state.get("negative_evidence", []),
        "followup_questions": state.get("followup_questions", []),
        "quality_warnings": state.get("quality_warnings", []),
        "quality_errors": state.get("quality_errors", []),
    }


def build_result_json(state: AnalysisState) -> dict:
    agent_type = state.get("agent_type")
    agent_type_str = str(agent_type) if agent_type is not None else "UNKNOWN"

    metadata = state.get("metadata", {}) or {}
    tech_stack_summary = {
        "primary_language": metadata.get("primary_language"),
        "topics": metadata.get("topics", []),
        "description": metadata.get("description"),
        "stars": metadata.get("stars"),
        "forks": metadata.get("forks"),
    }

    evidence_signals = state.get("evidence_signals", []) or []
    linked_claim_ids = {
        ev.get("claim_id")
        for ev in evidence_signals
        if ev.get("claim_id")
    }

    claims_list = []
    for claim in state.get("claims", []) or []:
        claim_id = claim.get("id")
        is_supported = claim_id in linked_claim_ids
        
        supporting_evidence = [
            ev.get("path")
            for ev in evidence_signals
            if ev.get("claim_id") == claim_id and ev.get("path")
        ]
        
        limitation = claim.get("limitation")
        if not limitation and not is_supported:
            limitation = "README claim은 있으나 구현 근거 파일을 찾지 못했습니다."
            
        claims_list.append({
            "claim_text": claim.get("claim_text", ""),
            "evidence_status": "SUPPORTED" if is_supported else "UNSUPPORTED",
            "confidence_level": str(claim.get("confidence", 0.0)),
            "supporting_evidence": supporting_evidence,
            "limitation": limitation
        })

    limitations = list(state.get("quality_warnings", []) or [])
    if state.get("quality_errors"):
        limitations.extend(state.get("quality_errors", []))
    for risk in state.get("risk_signals", []) or []:
        if risk.get("summary"):
            limitations.append(risk["summary"])

    missing_evidence = []
    for claim in state.get("claims", []) or []:
        claim_id = claim.get("id")
        if claim_id not in linked_claim_ids:
            missing_evidence.append(f"구현 근거 없음: {claim.get('claim_text')}")
    for neg in state.get("negative_evidence", []) or []:
        if neg.get("summary"):
            missing_evidence.append(neg["summary"])

    followup_questions = state.get("followup_questions", []) or []

    return {
        "agent_type": agent_type_str,
        "tech_stack_summary": tech_stack_summary,
        "claims": claims_list,
        "limitations": limitations,
        "missing_evidence": missing_evidence,
        "followup_questions": followup_questions,
    }


def persist_analysis(state: AnalysisState) -> AnalysisState:
    """Persist analysis result.

    MVP에서는 JSON 파일로 저장합니다. 운영에서는 이 함수에서 DB에 저장하면 됩니다.
    """
    analysis = _public_analysis(state)

    output_path = state.get("output_path")
    if output_path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8")

    result_json = build_result_json(state)

    settings = get_settings()
    callback_url = settings.agents_callback_url
    analysis_id = state.get("run_id")

    payload = {
        "analysis_id": analysis_id,
        "status": "COMPLETED",
        "result_json": result_json,
        "error_message": None,
    }

    try:
        response = httpx.post(callback_url, json=payload, timeout=10.0)
        response.raise_for_status()
    except Exception as exc:
        logger.error(f"Failed to send completion callback: {exc}")

    return {"persisted_analysis": analysis}
