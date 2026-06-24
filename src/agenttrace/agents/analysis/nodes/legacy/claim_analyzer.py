from __future__ import annotations

import re
import time

from agenttrace.agents.analysis.schemas.result import AnalysisClaim
from agenttrace.agents.analysis.state import AnalysisState
from agenttrace.logging_config import get_logger

logger = get_logger(__name__)



CLAIM_MARKERS = [
    "support", "supports", "provide", "provides", "include", "includes",
    "implement", "implements", "server", "client", "tool", "resource",
    "prompt", "eval", "benchmark", "skill", "plugin", "workflow",
    "지원", "제공", "구현", "도구", "서버", "클라이언트", "평가",
]


def _strip_markdown(text: str) -> str:
    # Remove markdown images first (e.g. ![Alt](url))
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    # Replace markdown links with their text
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    # Remove HTML tags (e.g. badges in HTML format)
    text = re.sub(r"<[^>]+>", "", text)
    # Remove markdown formatting characters
    text = re.sub(r"[`*_#>]", "", text)
    return re.sub(r"\s+", " ", text).strip(" -\t")


def claim_analyzer(state: AnalysisState) -> AnalysisState:
    _t = time.perf_counter()
    run_id = state.get("run_id", "-")
    log = logger.bind(node="claim_analyzer", run_id=run_id)
    log.info("시작")
    readme = state.get("readme", "")

    sentences = re.split(r"(?<=[.!?。])\s+|\n+", readme.strip())
    claims: list[dict] = []
    
    skipped_headings = {
        "superpowers", "quickstart", "installation", "documentation", "license",
        "badge", "badges", "install", "mit licensed", "website", "smithery", "npm"
    }

    for sentence in sentences:
        clean = _strip_markdown(sentence)
        lower = clean.lower()
        
        # Skip if too short
        if len(clean) < 15:
            continue
            
        # Skip if it is just a URL or contains raw links
        if lower.startswith(("http://", "https://")) or "http://" in lower or "https://" in lower:
            if re.search(r"https?://\S+", clean):
                continue

        heading_prefix = lower.split(":", 1)[0].strip()
        if any(h in lower for h in skipped_headings) or heading_prefix in skipped_headings:
            continue

        # Skip typical badge keywords or license lines
        if any(x in lower for x in ["badge", "npm install", "yarn add", "pip install", "mit license", "github action"]):
            continue

        if any(marker in lower for marker in CLAIM_MARKERS):
            claim = AnalysisClaim(
                claim_id=f"claim-{len(claims) + 1}",
                claim_text=clean[:500],
                source_path="README.md",
                source_section=None,
                confidence=0.62,
                evidence_signal_ids=[],
            )
            claims.append(claim.model_dump())

    log.info("완료", claims=len(claims), duration_ms=int((time.perf_counter() - _t) * 1000))
    return {"claims": claims[:8]}

