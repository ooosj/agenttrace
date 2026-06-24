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
    file_catalog: list[dict]        # build_file_catalog 노드 출력
    critical_config_paths: list[str]  # 항상 포함 보장 경로 목록
    mentioned_fnames: list[str]     # algorithm.md §4.3 사용자 언급 파일
    mentioned_idents: list[str]     # algorithm.md §4.4 사용자 언급 식별자
    chat_file_paths: list[str]      # algorithm.md §4.1 현재 작업 파일
    repo_map: dict
    definition_ranks: dict          # algorithm.md §10 (file::symbol) → score
    symbol_tags: list[dict]         # algorithm.md §23 SymbolTag 목록
    repo_map_render: str            # algorithm.md §13 토큰 예산 맞춘 렌더링
    deferred_file_paths: list[str]  # 지연 fetch 대상 파일 경로 목록
    selected_files: list[dict]
    output_path: str
    analysis_request: dict
    source_files: list[dict]
    missing_inputs: list[str]
    input_manifest: dict
    analysis_mode: str
    precheck_result: dict
    analysis_limitations: dict
    synthesis: dict

    # Area-based analysis output (area_explorer → finalize_analysis)
    area_findings: list[dict]          # area_explorer가 생성한 8개 AreaFinding
    evidence_refs: list[dict]          # area_explorer가 생성한 EvidenceRef 목록
    evidence_signals: list[dict]        # area_explorer가 수집한 코드 근거 신호
    agent_type: str                    # area_explorer가 판별한 agent_type

    # Analysis result
    status: AnalysisStatus
    classification_reason: str

    # Risk & followup (risk_and_followup 노드 출력)
    risk_signals: list[dict]
    followup_actions: list[dict]
    followup_guide: list[dict]
    follow_up_guide: dict

    # Quality / persistence
    report_sections: list[dict]
    quality_warnings: Annotated[list[str], operator.add]
    quality_errors: Annotated[list[str], operator.add]
    quality_gate_result: dict
    final_result: dict
    callback_payload: dict
    retry_count: int
    error_message: str
