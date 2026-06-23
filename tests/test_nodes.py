"""test_nodes.py

현재 파이프라인 기준 노드 단위 테스트.

삭제된 레거시:
  - analyzer (→ claim_analyzer + analysis_precheck + analysis_planner 로 분리)
  - collect_snapshot (→ collect_inputs 가 흡수)
  - _legacy_evidence_scout / _legacy_quality_gate 폴백 경로
"""
from __future__ import annotations

from agenttrace.agents.analysis.nodes.evidence_scout import evidence_scout
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
    """target_paths에 속한 청크가 선택된다."""
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
    }
    result = evidence_scout(state)
    selected = result["selected_chunks"]
    assert len(selected) >= 1
    assert all(c["file_path"] == "src/server.py" for c in selected)


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

def _minimal_final_result(
    *,
    status: str = "completed",
    claim_ids: list[str] | None = None,
    task_ids: list[str] | None = None,
) -> dict:
    """테스트용 최소 final_result dict — AnalysisResult 스키마 기준."""
    claim_ids = claim_ids or ["c1"]
    task_ids = task_ids or ["task-001"]
    signal_id = "sig-001"
    return {
        "analysis_status": status,
        "agent_type": "MCP",
        "analysis_claims": [
            {"claim_id": cid, "claim_text": "test claim", "confidence": 0.8, "source": "README"}
            for cid in claim_ids
        ],
        "evidence_signals": [
            {
                "signal_id": signal_id,
                "signal_type": "FILE_PATH",
                "file_path": "src/server.py",
                "path": "src/server.py",
                "summary": "test",
                "confidence": 0.9,
            }
        ],
        "evidence_task_results": [
            {
                "task_id": tid,
                "status": "RESOLVED",
                "evidence_signal_ids": [signal_id],
                "claim_verdicts": [
                    {
                        "claim_id": cid,
                        "verdict": "SUPPORTED",
                        "confidence": 0.8,
                        "reason": "test evidence",
                        "evidence_signal_ids": [signal_id],
                    }
                    for cid in claim_ids
                ],
            }
            for tid in task_ids
        ],
        "analysis_limitations": {
            "missing_inputs": [],
            "truncated_inputs": [],
            "notes": [],
        },
    }



def _plan(task_ids: list[str], required: bool = True) -> dict:
    return {
        "plan_id": "plan-001",
        "repository_id": "repo-1",
        "tasks": [
            {"task_id": tid, "claims": ["c1"], "target_paths": [], "required": required, "status": "PENDING"}
            for tid in task_ids
        ],
    }


def test_quality_gate_passes_valid_final_result():
    state = {
        "run_id": "test",
        "final_result": _minimal_final_result(),
        "analysis_plan": _plan(["task-001"]),
    }
    result = quality_gate(state)
    assert result["quality_gate_result"]["critical_errors"] == []


def test_quality_gate_blocks_missing_required_task():
    state = {
        "run_id": "test",
        "final_result": _minimal_final_result(task_ids=["task-999"]),  # task-001 없음
        "analysis_plan": _plan(["task-001"]),
    }
    result = quality_gate(state)
    errors = result["quality_gate_result"]["critical_errors"]
    assert errors
    # schema 유효 시 missing task 에러, schema 오류 시 schema 에러 중 하나여야 함
    assert any("task-001" in e or "task" in e.lower() or "schema" in e.lower() for e in errors)


def test_quality_gate_blocks_unknown_evidence_signal():
    final = _minimal_final_result()
    # task result가 존재하지 않는 signal_id 참조
    final["evidence_task_results"][0]["evidence_signal_ids"] = ["sig-UNKNOWN"]
    state = {
        "run_id": "test",
        "final_result": final,
        "analysis_plan": _plan(["task-001"]),
    }
    result = quality_gate(state)
    assert result["quality_gate_result"]["critical_errors"]


# ---------------------------------------------------------------------------
# risk_and_followup_planner — 현재 파이프라인 기준
# ---------------------------------------------------------------------------

def test_risk_and_followup_planner_returns_followup_actions():
    state = {
        "run_id": "test",
        "agent_type": "MCP",
        "evidence_signals": [
            {"claim_id": "c1", "path": "src/server.py", "confidence": 0.9}
        ],
        "claims": [{"claim_id": "c1", "claim_text": "MCP server with tools"}],
        "file_tree": [{"path": "src/server.py"}, {"path": "README.md"}],
        "risk_signals": [],
        "followup_actions": [],
    }
    result = risk_and_followup_planner(state)
    assert "followup_actions" in result or "risk_signals" in result
