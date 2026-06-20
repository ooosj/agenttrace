from __future__ import annotations

import re
import logging
from pydantic import BaseModel, Field
from agenttrace.agents.analysis.criteria.agent_type_keywords import AGENT_TYPE_KEYWORDS
from agenttrace.agents.analysis.state import AnalysisState
from agenttrace.models import build_openai_summary_model
from langchain_core.prompts import ChatPromptTemplate
from agenttrace.config import get_settings

logger = logging.getLogger(__name__)


class ExtractedClaim(BaseModel):
    claim_text: str = Field(description="A specific capability or feature claimed by the repository README.")
    confidence: float = Field(description="Confidence score between 0.0 and 1.0 of this claim's importance or feasibility.")


class ClaimsExtractionResult(BaseModel):
    claims: list[ExtractedClaim] = Field(description="List of key claims extracted from the README.")


def _score_keywords(text: str, keywords: list[str]) -> float:
    lower = text.lower()
    hits = sum(1 for keyword in keywords if keyword.lower() in lower)
    return hits / max(len(keywords), 1)


def _detect_agent_type(readme: str, file_tree: list[dict]) -> tuple[str, float, str]:
    paths = [item.get("path", "") for item in file_tree]
    paths_text = "\n".join(paths)
    lower_paths = [path.lower() for path in paths]

    scores: dict[str, float] = {}
    for agent_type, keywords in AGENT_TYPE_KEYWORDS.items():
        readme_score = _score_keywords(readme, keywords)
        path_score = _score_keywords(paths_text, keywords)
        scores[agent_type] = (readme_score * 0.65) + (path_score * 0.35)

    has_skill_path = any(
        "skills/" in path or path.endswith("skill.md")
        for path in lower_paths
    )
    if has_skill_path:
        best_score = max(scores.values(), default=0.0)
        skill_score = max(scores.get("SKILL", 0.0), 0.5)
        return (
            "SKILL",
            min(max(skill_score, best_score) * 3, 1.0),
            "SKILL 관련 파일 경로 신호가 확인되었습니다.",
        )

    best_type, best_score = max(scores.items(), key=lambda item: item[1])

    if best_score <= 0:
        return "OTHER", 0.0, "README와 file tree에서 AgentHub 대상 신호를 찾지 못했습니다."

    if best_score < 0.12:
        return "UNKNOWN", best_score, "일부 관련 신호는 있으나 유형 분류 신뢰도가 낮습니다."

    return best_type, min(best_score * 3, 1.0), f"{best_type} 관련 README 키워드와 파일 경로 신호가 확인되었습니다."


def _strip_markdown(text: str) -> str:
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r'[`*_#>]', "", text)
    return re.sub(r"\s+", " ", text).strip(" -\t")


def _extract_claims(readme: str, agent_type: str) -> list[dict]:
    """Extract README claims conservatively.

    LLM 없이 동작하는 MVP용 백업 문장 단위 휴리스틱 매칭입니다.
    """
    claim_markers = [
        "support", "supports", "provide", "provides", "include", "includes",
        "implement", "implements", "server", "client", "tool", "resource",
        "prompt", "eval", "benchmark", "skill", "skills", "plugin",
        "workflow", "workflows", "coding agents", "methodology", "verify",
        "지원", "제공", "구현", "도구", "서버", "클라이언트", "평가", "벤치마크",
    ]
    skipped_headings = {"superpowers", "quickstart", "installation", "documentation"}

    sentences = re.split(r"(?<=[.!?。])\s+|\n+", readme.strip())
    claims: list[dict] = []

    for sentence in sentences:
        clean = _strip_markdown(sentence)
        lower = clean.lower()
        heading_prefix = lower.split(":", 1)[0].strip()
        if len(clean) < 24 or lower in skipped_headings or heading_prefix in skipped_headings:
            continue
        if any(marker in lower for marker in claim_markers):
            claims.append({
                "id": f"claim-{len(claims) + 1}",
                "claim_text": clean[:500],
                "claim_type": agent_type,
                "source": "README.md",
                "confidence": 0.62,
            })

    if not claims and agent_type not in {"OTHER", "UNKNOWN"}:
        claims.append({
            "id": "claim-1",
            "claim_text": f"README와 파일 구조가 {agent_type} 유형의 agent 관련 프로젝트임을 암시합니다.",
            "claim_type": agent_type,
            "source": "README.md + file_tree",
            "confidence": 0.4,
        })

    return claims[:8]


def analyzer(state: AnalysisState) -> AnalysisState:
    if state.get("status") == "INSUFFICIENT_EVIDENCE":
        return {}

    readme = state.get("readme", "")
    file_tree = state.get("file_tree", [])
    full_name = state.get("full_name", "unknown/unknown")

    agent_type, relevance_score, reason = _detect_agent_type(readme, file_tree)

    if agent_type == "OTHER":
        return {
            "status": "OUT_OF_SCOPE",
            "agent_type": "OTHER",
            "relevance_score": relevance_score,
            "classification_reason": reason,
            "claims": [],
        }

    status = "UNCERTAIN" if agent_type == "UNKNOWN" else "COLLECTED"
    
    claims = []
    settings = get_settings()
    if settings.openai_api_key:
        try:
            model = build_openai_summary_model()
            structured_model = model.with_structured_output(ClaimsExtractionResult)
            
            prompt = ChatPromptTemplate.from_messages([
                ("system", "You are an expert AI software analyst. Your task is to analyze the README of a repository and extract key functional capabilities, features, or design claims made by the project.\nFocus only on key developer-facing or user-facing features, client/server interfaces, framework plugins, automation workflows, or testing capabilities.\nDo not extract trivial meta-information, badges, or simple installation commands.\nProvide a confidence score for each claim indicating how concrete or significant the claim is."),
                ("human", "Repository Name: {full_name}\nAgent Type: {agent_type}\n\nREADME Content:\n{readme}")
            ])
            
            prompt_value = prompt.invoke({
                "full_name": full_name,
                "agent_type": agent_type,
                "readme": readme[:30000]
            })
            
            result = structured_model.invoke(prompt_value)
            for idx, c in enumerate(result.claims):
                claims.append({
                    "id": f"claim-{idx + 1}",
                    "claim_text": c.claim_text[:500],
                    "claim_type": agent_type,
                    "source": "README.md",
                    "confidence": c.confidence,
                })
        except Exception as exc:
            logger.warning(f"LLM claims extraction failed, falling back to heuristic: {exc}")
            claims = []

    if not claims:
        claims = _extract_claims(readme, agent_type)

    return {
        "status": status,
        "agent_type": agent_type,
        "relevance_score": relevance_score,
        "classification_reason": reason,
        "claims": claims,
    }
