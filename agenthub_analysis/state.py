from __future__ import annotations

from typing import Annotated, Literal, TypedDict
import operator

AnalysisStatus = Literal[
    "COLLECTED",
    "OUT_OF_SCOPE",
    "COMPLETED",
    "INSUFFICIENT_EVIDENCE",
    "UNCERTAIN",
    "FAILED",
    "NEEDS_REANALYSIS",
    "NEEDS_HUMAN_REVIEW",
]

AgentType = Literal[
    "MCP_SERVER",
    "MCP_CLIENT",
    "SKILL",
    "EVAL_HARNESS",
    "TOOL_USE",
    "AGENT_FRAMEWORK",
    "OBSERVABILITY",
    "GUARDRAIL",
    "OTHER",
    "UNKNOWN",
]

Trigger = Literal[
    "NEW_REPO",
    "REPO_CHANGED",
    "ADMIN_REANALYSIS",
    "USER_REPORT",
]


class AnalysisState(TypedDict, total=False):
    # Run identity
    run_id: str
    repository_id: str
    full_name: str
    github_url: str
    trigger: Trigger

    # Input / collected snapshot
    repository_snapshot: dict
    metadata: dict
    readme: str
    file_tree: list[dict]
    selected_files: list[dict]
    output_path: str

    # Analysis result
    status: AnalysisStatus
    agent_type: AgentType
    relevance_score: float
    classification_reason: str

    # Evidence-first analysis objects
    claims: Annotated[list[dict], operator.add]
    evidence_tasks: list[dict]
    evidence_signals: Annotated[list[dict], operator.add]
    risk_signals: Annotated[list[dict], operator.add]
    followup_actions: list[dict]
    followup_guide: list[dict]

    # Quality / persistence
    quality_warnings: Annotated[list[str], operator.add]
    quality_errors: Annotated[list[str], operator.add]
    persisted_analysis: dict
    retry_count: int
    error_message: str
