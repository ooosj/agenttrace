from __future__ import annotations

import re
import logging
from pydantic import BaseModel, Field
from agenttrace.agents.analysis.criteria.agent_type_keywords import EVIDENCE_PATH_HINTS
from agenttrace.agents.analysis.state import AnalysisState
from agenttrace.config import get_settings
from agenttrace.models import build_openai_summary_model
from langchain_core.prompts import ChatPromptTemplate

logger = logging.getLogger(__name__)


class EvidenceMapping(BaseModel):
    claim_id: str = Field(description="The ID of the claim (e.g., 'claim-1').")
    path: str = Field(description="The matching file path from the repository that serves as evidence for this claim.")
    reason: str = Field(description="Reasoning explaining why this file is evidence for the claim.")
    confidence: float = Field(description="Confidence score (0.0 to 1.0) of this evidence match.")


class EvidenceScoutResult(BaseModel):
    evidence_signals: list[EvidenceMapping] = Field(description="List of evidence signals matching claims to source file paths.")


CLAIM_KEYWORD_TOKENS = {
    "skill", "skills", "plugin", "plugins", "hook", "hooks",
    "script", "scripts", "test", "tests", "workflow", "workflows",
    "plan", "debug", "review", "verify", "install",
}


def _path_signal_type(path: str, file_type: str | None = None) -> str:
    lower_path = path.lower()
    name = lower_path.rsplit("/", 1)[-1]

    if file_type == "directory":
        return "DIRECTORY"
    if name in {"plugin.json", "mcp.json"} or "plugin" in lower_path:
        return "CONFIG"
    if "test" in lower_path:
        return "TEST"
    if name == "readme.md" or lower_path.endswith(".md"):
        return "DOC"
    if name in {"package.json", "pyproject.toml", "cargo.toml"}:
        return "DEPENDENCY"
    return "FILE_PATH"


def _claim_keywords(claim_text: str) -> set[str]:
    words = set(re.findall(r"[a-z0-9_-]+", claim_text.lower()))
    return {
        token.rstrip("s")
        for token in CLAIM_KEYWORD_TOKENS
        if token in words
    }


def _heuristic_scout(state: AnalysisState) -> list[dict]:
    agent_type = state.get("agent_type", "UNKNOWN")
    file_tree = state.get("file_tree", [])
    claims = state.get("claims", [])
    hints = EVIDENCE_PATH_HINTS.get(agent_type, [])

    evidence_signals: list[dict] = []
    seen = set()

    for claim in claims or [{"id": None, "claim_text": ""}]:
        claim_id = claim.get("id")
        claim_keywords = _claim_keywords(claim.get("claim_text", ""))
        claim_file_tree = file_tree
        if claim_keywords:
            claim_file_tree = sorted(
                file_tree,
                key=lambda file_info: (
                    _path_signal_type(file_info.get("path", ""), file_info.get("type")) != "CONFIG",
                    not any(keyword in file_info.get("path", "").lower() for keyword in claim_keywords),
                ),
            )

        for file_info in claim_file_tree:
            path = file_info.get("path", "")
            lower_path = path.lower()
            matched_hints = [hint for hint in hints if hint.lower() in lower_path]
            matched_keywords = sorted(keyword for keyword in claim_keywords if keyword in lower_path)
            if not matched_hints and not matched_keywords:
                continue

            key = (claim_id, path)
            if key in seen:
                continue
            seen.add(key)

            matched_signals = matched_hints + matched_keywords
            evidence_signals.append({
                "claim_id": claim_id,
                "signal_type": _path_signal_type(path, file_info.get("type")),
                "path": path,
                "summary": f"claim과 연결된 파일 경로 근거: {', '.join(matched_signals)}",
                "confidence": min(0.5 + 0.1 * len(set(matched_signals)), 0.9),
            })
            if len(evidence_signals) >= 16:
                break

        if len(evidence_signals) >= 16:
            break

    return evidence_signals


def evidence_scout(state: AnalysisState) -> AnalysisState:
    agent_type = state.get("agent_type", "UNKNOWN")
    file_tree = state.get("file_tree", [])
    claims = state.get("claims", [])
    hints = EVIDENCE_PATH_HINTS.get(agent_type, [])

    # Pre-filter candidate paths to avoid hitting context limits
    candidate_paths = []
    path_to_file_info = {}
    
    # Gather potential file candidates using keywords or hints
    for file_info in file_tree:
        path = file_info.get("path", "")
        lower_path = path.lower()
        
        # Check if the path contains any general keywords or type specific hints
        has_hint = any(hint.lower() in lower_path for hint in hints)
        has_keyword = any(kw in lower_path for kw in CLAIM_KEYWORD_TOKENS)
        
        if has_hint or has_keyword:
            candidate_paths.append(path)
            path_to_file_info[path] = file_info
            
    # Limit candidate paths to top 60 to prevent prompt bloat
    candidate_paths = candidate_paths[:60]

    evidence_signals = []
    settings = get_settings()

    if settings.openai_api_key and claims and candidate_paths:
        try:
            model = build_openai_summary_model()
            structured_model = model.with_structured_output(EvidenceScoutResult)
            
            claims_text = "\n".join([f"- ID: {c.get('id')} | Claim: {c.get('claim_text')}" for c in claims])
            paths_text = "\n".join([f"- {path}" for path in candidate_paths])
            
            prompt = ChatPromptTemplate.from_messages([
                ("system", "You are an expert AI software analyst. Your task is to match project claims (extracted from the README) with actual source code file paths from the repository file tree.\nFor each claim, select files from the provided list of file path candidates that serve as concrete evidence of implementation for that claim.\nDo not map files if they are not related to the claim.\nOnly select paths from the provided candidate list."),
                ("human", "Claims to match:\n{claims_text}\n\nCandidate File Paths:\n{paths_text}")
            ])
            
            prompt_value = prompt.invoke({
                "claims_text": claims_text,
                "paths_text": paths_text
            })
            
            result = structured_model.invoke(prompt_value)
            
            for ev in result.evidence_signals:
                if ev.path not in path_to_file_info:
                    continue
                file_info = path_to_file_info[ev.path]
                sig_type = _path_signal_type(ev.path, file_info.get("type"))
                
                evidence_signals.append({
                    "claim_id": ev.claim_id,
                    "signal_type": sig_type,
                    "path": ev.path,
                    "summary": f"claim과 연결된 파일 경로 근거: {ev.reason}",
                    "confidence": ev.confidence,
                })
                if len(evidence_signals) >= 16:
                    break
        except Exception as exc:
            logger.warning(f"LLM evidence scouting failed, falling back to heuristic: {exc}")
            evidence_signals = []

    if not evidence_signals:
        evidence_signals = _heuristic_scout(state)

    if not evidence_signals:
        return {
            "status": "INSUFFICIENT_EVIDENCE",
            "evidence_signals": [],
            "quality_warnings": ["README claim을 뒷받침할 파일 경로 근거가 부족합니다."],
        }

    return {
        "status": "COLLECTED",
        "evidence_signals": evidence_signals,
    }
