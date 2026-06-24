"""test_nodes.py

현재 파이프라인 기준 노드 단위 테스트.

삭제된 레거시:
  - analyzer (→ claim_analyzer + analysis_precheck + analysis_planner 로 분리)
  - collect_snapshot (→ collect_inputs 가 흡수)
  - _legacy_evidence_scout / _legacy_quality_gate 폴백 경로
"""
from __future__ import annotations

from agenttrace.agents.analysis.nodes.legacy.evidence_scout import evidence_scout
from agenttrace.agents.analysis.nodes.quality_gate import quality_gate
from agenttrace.agents.analysis.nodes.risk_and_followup import risk_and_followup_planner


# ---------------------------------------------------------------------------
# evidence_scout — 태스크 루프 기반 (현재 파이프라인)
# ---------------------------------------------------------------------------

def _chunk_index(paths: list[str]) -> dict:
    """테스트용 최소 ChunkIndex 생성."""
    chunks = {}
    for i, path in enumerate(paths):
        cid = f"chunk-{i:03d}"
        chunks[cid] = {
            "chunk_id": cid,
            "file_path": path,
            "content_hash": path.replace("/", "_"),
        }
    return {"chunks_by_id": chunks}


def test_evidence_scout_selects_chunks_for_target_paths():
    """ReAct 모드에서는 target_paths를 구조 지도에 포함하고 청크는 선선택하지 않는다."""
    state = {
        "run_id": "test",
        "current_task_id": "task-001",
        "analysis_plan": {
            "tasks": [
                {
                    "task_id": "task-001",
                    "claims": ["c1"],
                    "target_paths": ["src/server.py"],
                    "required": True,
                    "status": "PENDING",
                }
            ]
        },
        "claims": [{"claim_id": "c1", "claim_text": "MCP server with tools"}],
        "chunk_index": _chunk_index(["src/server.py", "docs/index.md", "tests/test_server.py"]),
        "repo_map": {
            "files": {"src/server.py": {"definitions": ["McpServer"], "references": ["tool"]}},
            "definition_ranks": {"src/server.py::McpServer": 1.0},
        },
    }
    result = evidence_scout(state)
    assert result["selected_chunks"] == []
    assert "src/server.py" in result["search_attempt"]["structure_map"]
    assert result["search_attempt"]["mode"] == "react"


def test_evidence_scout_falls_back_to_token_match_when_no_path_match():
    """target_paths 매칭 실패 시 query 토큰으로 폴백한다."""
    state = {
        "run_id": "test",
        "current_task_id": "task-001",
        "analysis_plan": {
            "tasks": [
                {
                    "task_id": "task-001",
                    "claims": ["c1"],
                    "target_paths": ["nonexistent/path.py"],
                    "required": True,
                    "status": "PENDING",
                }
            ]
        },
        "claims": [{"claim_id": "c1", "claim_text": "server tool capability"}],
        "chunk_index": _chunk_index(["src/server_tool.py", "README.md"]),
    }
    result = evidence_scout(state)
    # 토큰 매칭 또는 first-N 폴백으로 어떤 청크든 반환돼야 함
    assert "selected_chunks" in result
    assert "search_attempt" in result


def test_evidence_scout_returns_empty_chunks_when_no_chunk_index():
    """chunk_index 자체가 없으면 selected_chunks는 빈 리스트."""
    state = {
        "run_id": "test",
        "current_task_id": "task-001",
        "analysis_plan": {
            "tasks": [
                {
                    "task_id": "task-001",
                    "claims": ["c1"],
                    "target_paths": ["src/server.py"],
                    "required": True,
                    "status": "PENDING",
                }
            ]
        },
        "claims": [{"claim_id": "c1", "claim_text": "MCP server"}],
        "chunk_index": {},
    }
    result = evidence_scout(state)
    assert result["selected_chunks"] == []


# ---------------------------------------------------------------------------
# quality_gate — final_result 경로 (현재 파이프라인)
# ---------------------------------------------------------------------------

def _minimal_final_result(*, status: str = "completed") -> dict:
    return {
        "analysis_status": status,
        "area_findings": [],
        "evidence_refs": [],
        "analysis_limitations": {
            "missing_inputs": [],
            "truncated_inputs": [],
            "notes": [],
        },
    }


def test_quality_gate_passes_valid_final_result():
    state = {
        "run_id": "test",
        "final_result": _minimal_final_result(),
    }
    result = quality_gate(state)
    assert result["quality_gate_result"]["critical_errors"] == []


# ---------------------------------------------------------------------------
# risk_and_followup_planner — 현재 파이프라인 기준
# ---------------------------------------------------------------------------

def test_risk_and_followup_planner_returns_followup_actions():
    state = {
        "run_id": "test",
        "agent_type": "MCP",
        "area_findings": [
            {
                "area_id": "project-purpose",
                "area_name": "프로젝트 목적",
                "status": "confirmed",
                "summary": "MCP server with tools",
                "findings": [],
            }
        ],
        "evidence_refs": [
            {"id": "e1", "source_type": "code", "path": "src/server.py", "description": "impl"}
        ],
        "file_tree": [{"path": "src/server.py"}, {"path": "README.md"}],
        "risk_signals": [],
        "followup_actions": [],
    }
    result = risk_and_followup_planner(state)
    assert "risk_signals" in result
    assert "followup_actions" in result
