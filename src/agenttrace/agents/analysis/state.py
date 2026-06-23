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
    local_repo_dir: str
    repository_id: str
    full_name: str
    github_url: str
    commit_sha: str
    ingest_api_url: str
    trigger: Trigger

    # Input / collected snapshot
    repository_snapshot: dict
    metadata: dict
    readme: str
    file_tree: list[dict]
    selected_files: list[dict]
    output_path: str
    analysis_request: dict
    source_files: list[dict]
    missing_inputs: list[str]
    input_manifest: dict
    analysis_mode: str
    content_chunks: list[dict]
    chunk_index: dict
    content_index_request: dict
    content_index_result: dict
    embedding_candidates: list[dict]
    chunk_embedding_rows: list[dict]
    chunk_embedding_result: dict
    precheck_result: dict
    analysis_limitations: dict
    synthesis: dict

    # Analysis result
    status: AnalysisStatus
    agent_type: AgentType
    relevance_score: float
    classification_reason: str

    # Evidence-first analysis objects
    claims: Annotated[list[dict], operator.add]
    evidence_tasks: list[dict]
    analysis_plan: dict
    current_task_id: str | None
    next_task_id: str | None
    task_results: list[dict]
    task_traces: list[dict]
    selected_chunks: list[dict]
    search_attempt: dict
    task_parts: list[dict]
    task_part_results: list[dict]
    pending_task_result: dict
    pending_evidence_signals: list[dict]
    evidence_signals: Annotated[list[dict], operator.add]
    risk_signals: Annotated[list[dict], operator.add]
    followup_actions: list[dict]
    followup_guide: list[dict]
    follow_up_guide: dict
    harness_relevance: dict
    harness_capabilities: dict
    negative_evidence: Annotated[list[dict], operator.add]
    followup_questions: list[str]

    # Quality / persistence
    quality_warnings: Annotated[list[str], operator.add]
    quality_errors: Annotated[list[str], operator.add]
    persisted_analysis: dict
    final_result: dict
    quality_gate_result: dict
    callback_payload: dict
    retry_count: int
    error_message: str
