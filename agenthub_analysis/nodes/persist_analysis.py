from __future__ import annotations

import json
from pathlib import Path
from agenthub_analysis.state import AnalysisState


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
        "quality_warnings": state.get("quality_warnings", []),
        "quality_errors": state.get("quality_errors", []),
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

    return {"persisted_analysis": analysis}
