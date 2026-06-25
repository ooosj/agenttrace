from agenttrace.agents.analysis.nodes.analysis_precheck import analysis_precheck
from agenttrace.agents.analysis.nodes.collect_inputs import collect_inputs
from agenttrace.agents.analysis.nodes.legacy.analysis_planner import analysis_planner
from agenttrace.agents.analysis.nodes.legacy.claim_analyzer import claim_analyzer
from agenttrace.agents.analysis.nodes.legacy.content_indexer import content_indexer
from agenttrace.agents.analysis.nodes.legacy.chunk_embedder import chunk_embedder
from agenttrace.agents.analysis.nodes.legacy.content_preprocessor import content_preprocessor
from agenttrace.agents.analysis.nodes.legacy.evidence_evaluator import evidence_evaluator
from agenttrace.agents.analysis.nodes.legacy.evidence_scout import evidence_scout
from agenttrace.agents.analysis.nodes.legacy.finalize_task import finalize_task
from agenttrace.agents.analysis.nodes.persist_analysis import persist_analysis
from agenttrace.agents.analysis.nodes.finalize_analysis import (
    finalize_analysis,
    validate_mermaid_syntax,
)
from agenttrace.agents.analysis.nodes.quality_gate import quality_gate
from agenttrace.agents.analysis.schemas.result import COMMON_ANALYSIS_AREAS
from agenttrace.agents.analysis.nodes.legacy.repository_synthesizer import repository_synthesizer
from agenttrace.agents.analysis.nodes.legacy.request_builder import request_builder
import pytest
from agenttrace.agents.analysis.nodes.legacy.task_result_merge import task_result_merge


@pytest.fixture(autouse=True)
def disable_openai_api_key(monkeypatch):
    import agenttrace.config
    import agenttrace.agents.analysis.nodes.finalize_analysis
    original_get_settings = agenttrace.config.get_settings
    def mocked_get_settings():
        settings = original_get_settings()
        from dataclasses import replace
        return replace(settings, openai_api_key=None)
    monkeypatch.setattr(agenttrace.config, "get_settings", mocked_get_settings)
    monkeypatch.setattr(agenttrace.agents.analysis.nodes.finalize_analysis, "get_settings", mocked_get_settings)


def test_content_preprocessor_builds_chunks_from_source_files():
    state = {
        "source_files": [{"path": "src/server.py", "content": "def register_tool(): pass"}],
        "missing_inputs": [],
    }

    result = content_preprocessor(state)

    assert result["content_chunks"]
    assert result["chunk_index"]["entries"][0]["file_path"] == "src/server.py"


def test_collect_inputs_derives_file_tree_from_source_files_when_request_tree_empty(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    state = {
        "run_id": "00000000-0000-0000-0000-000000000101",
        "analysis_request": {
            "analysis_id": "00000000-0000-0000-0000-000000000101",
            "repository": {
                "full_name": "owner/repo",
                "github_url": "https://github.com/owner/repo",
            },
            "snapshot": {"snapshot_id": "snap-1"},
            "readme_text": "# Repo",
            "file_tree": [],
            "source_files": [
                {"path": "README.md", "content": "# Repo\n"},
                {"path": "src/server.ts", "content": "export function serve() {}\n"},
                {"path": "package.json", "content": "{\"type\":\"module\"}\n"},
            ],
            "external_ingest": {"enabled": False, "provider": "gitingest"},
        },
    }

    result = collect_inputs(state)

    assert [item["path"] for item in result["file_tree"]] == [
        "README.md",
        "src/server.ts",
        "package.json",
    ]


def test_content_preprocessor_prepares_index_and_embedding_metadata():
    state = {
        "repository_snapshot": {"snapshot_id": "00000000-0000-0000-0000-000000000001"},
        "source_files": [{"path": "src/server.py", "content": "def register_tool(): pass"}],
        "missing_inputs": [],
    }

    result = content_preprocessor(state)

    assert result["content_index_request"] == {
        "snapshot_id": "00000000-0000-0000-0000-000000000001",
        "chunking_version": "semantic-v1",
        "embedding_model": "text-embedding-3-small",
        "embedding_dimension": 1536,
        "index_version": "pgvector-hnsw-v1",
    }
    assert result["embedding_candidates"][0]["chunk_id"] == result["content_chunks"][0]["chunk_id"]
    assert result["embedding_candidates"][0]["content_hash"] == result["content_chunks"][0]["content_hash"]
    assert "content" not in result["embedding_candidates"][0]


class FakeContentIndexStore:
    def __init__(self):
        self.requests = []

    def request_index(self, **kwargs):
        self.requests.append(kwargs)
        return {"index_id": "idx-1", "status": "PENDING"}


def test_content_indexer_requests_index_from_preprocessor_metadata():
    store = FakeContentIndexStore()
    state = {
        "content_index_request": {
            "snapshot_id": "snap-1",
            "chunking_version": "semantic-v1",
            "embedding_model": "text-embedding-3-small",
            "embedding_dimension": 1536,
            "index_version": "pgvector-hnsw-v1",
        }
    }

    result = content_indexer(state, store=store)

    assert store.requests == [state["content_index_request"]]
    assert result["content_index_result"] == {"index_id": "idx-1", "status": "PENDING"}


class FakeEmbeddingService:
    def __init__(self):
        self.texts = []

    def embed_texts(self, texts):
        self.texts.extend(texts)
        return [[0.1] * 1536 for _ in texts]


class FakeEmbeddingStore:
    def __init__(self):
        self.rows = []

    def update_embeddings(self, rows):
        self.rows.extend(rows)
        return [{"chunk_id": row["chunk_id"]} for row in rows]


def test_chunk_embedder_reads_local_chunk_content_and_updates_store(tmp_path):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "src").mkdir()
    (repo_dir / "src/server.py").write_text("def register_tool(): pass", encoding="utf-8")
    embedding_service = FakeEmbeddingService()
    store = FakeEmbeddingStore()
    state = {
        "local_repo_dir": str(repo_dir),
        "content_chunks": [
            {
                "chunk_id": "chunk-a",
                "file_path": "src/server.py",
                "content": "",
                "start_byte": 0,
                "end_byte": 25,
                "line_start": 1,
                "line_end": 1,
                "is_partial": False,
                "content_hash": "sha256:" + "0" * 64,
            }
        ],
    }

    result = chunk_embedder(state, embedding_service=embedding_service, store=store)

    assert embedding_service.texts == ["def register_tool(): pass"]
    assert store.rows[0]["chunk_id"] == "chunk-a"
    assert result["chunk_embedding_result"]["updated_count"] == 1


def test_analysis_precheck_allows_limited_readme_file_tree_analysis():
    state = {
        "readme": "# Repo\nProvides MCP tools.",
        "file_tree": [{"path": "src/server.py"}],
        "missing_inputs": ["source_files"],
        "content_chunks": [],
    }

    result = analysis_precheck(state)

    assert result["precheck_result"]["can_analyze"] is True
    assert result["analysis_mode"] == "limited"
    assert "source_files" in result["analysis_limitations"]["missing_inputs"]


def test_analysis_precheck_allows_repo_map_only_analysis():
    state = {
        "repo_map": {
            "files": {
                "src/server.ts": {
                    "definitions": ["createServer"],
                    "references": ["tool"],
                }
            }
        },
        "missing_inputs": [],
    }

    result = analysis_precheck(state)

    assert result["precheck_result"]["can_analyze"] is True
    assert result["precheck_result"]["has_repo_map"] is True
    assert result["status"] == "COLLECTED"


def test_claim_analyzer_extracts_readme_claims_without_summary_regeneration():
    result = claim_analyzer(
        {"readme": "# Repo\nProvides an MCP server.\nSupports tool registration."}
    )

    assert [claim["claim_id"] for claim in result["claims"]] == ["claim-1", "claim-2"]
    assert "MCP server" in result["claims"][0]["claim_text"]


def test_analysis_planner_groups_claims_into_required_tasks():
    result = analysis_planner(
        {
            "metadata": {"repository_id": "repo-1"},
            "claims": [
                {"claim_id": "claim-1", "claim_text": "Provides an MCP server.", "source_path": "README.md"},
                {"claim_id": "claim-2", "claim_text": "Supports tool registration.", "source_path": "README.md"},
            ],
            "file_tree": [{"path": "src/server.py"}, {"path": "README.md"}],
        }
    )

    task = result["analysis_plan"]["tasks"][0]
    assert task["required"] is True
    assert task["status"] == "PENDING"
    assert "claim-1" in task["claims"]


def _state_with_task_and_chunk():
    return {
        "current_task_id": "task-1",
        "analysis_plan": {
            "tasks": [
                {
                    "task_id": "task-1",
                    "claims": ["claim-1"],
                    "target_paths": ["src/server.py"],
                    "required": True,
                    "status": "PENDING",
                }
            ]
        },
        "claims": [{"claim_id": "claim-1", "claim_text": "Provides an MCP server."}],
        "chunk_index": {
            "entries": [
                {
                    "file_path": "src/server.py",
                    "chunk_ids": ["chunk-0001"],
                    "keywords": ["server", "mcp"],
                    "chunk_count": 1,
                }
            ],
            "chunks_by_id": {
                "chunk-0001": {
                    "chunk_id": "chunk-0001",
                    "file_path": "src/server.py",
                    "content": "class McpServer: pass",
                    "start_byte": 0,
                    "end_byte": 21,
                    "line_start": 1,
                    "line_end": 1,
                    "is_partial": False,
                    "content_hash": "sha256:"
                    + "0" * 64,
                }
            },
        },
        "task_traces": [],
    }


def test_evidence_task_loop_resolves_supported_claim():
    state = _state_with_task_and_chunk()
    state.update(evidence_scout(state))
    state.update(request_builder(state))
    state.update(evidence_evaluator(state))
    state.update(task_result_merge(state))
    result = finalize_task(state)

    task_result = result["task_results"][0]
    assert task_result["status"] == "RESOLVED"
    assert task_result["claim_verdicts"][0]["verdict"] in {"SUPPORTED", "PARTIALLY_SUPPORTED"}


def test_evidence_scout_generates_structure_map_for_react_mode():
    """ReAct 모드: evidence_scout가 구조 지도를 생성하고 selected_chunks는 빈 리스트."""
    state = {
        "run_id": "run-1",
        "current_task_id": "task-1",
        "analysis_plan": {
            "tasks": [
                {
                    "task_id": "task-1",
                    "area_id": "agent-and-llm",
                    "claims": ["claim-1"],
                    "queries": ["agent tool prompt"],
                    "target_paths": [],
                }
            ]
        },
        "claims": [{"claim_id": "claim-1", "claim_text": "Provides an agent tool prompt."}],
        "chunk_index": {"chunks_by_id": {}},
        "repo_map": {
            "files": {
                "src/core.ts": {"definitions": ["createContextTool"], "references": ["tool", "prompt"], "category": "source"},
            },
            "area_file_ranks": {"agent-and-llm": {"src/core.ts": 1.0}},
            "definition_ranks": {"src/core.ts::createContextTool": 0.9},
        },
    }

    result = evidence_scout(state)

    # ReAct 모드: selected_chunks는 빈 리스트 (LLM이 도구로 탐색)
    assert result["selected_chunks"] == []
    # 구조 지도가 search_attempt에 포함됨
    assert "structure_map" in result["search_attempt"]
    assert "src/core.ts" in result["search_attempt"]["structure_map"]
    assert result["search_attempt"]["mode"] == "react"


def test_repository_synthesizer_marks_required_task_insufficient():
    state = {
        "analysis_plan": {"tasks": [{"task_id": "task-1", "required": True}]},
        "task_results": [
            {
                "task_id": "task-1",
                "status": "INSUFFICIENT_EVIDENCE",
                "claim_verdicts": [],
                "evidence_signal_ids": [],
                "limitations": ["no source"],
            }
        ],
        "analysis_limitations": {"missing_inputs": ["source_files"], "truncated_inputs": [], "notes": []},
    }

    result = repository_synthesizer(state)

    assert result["synthesis"]["analysis_status"] == "insufficient_evidence"


def test_finalize_analysis_builds_schema_valid_result():
    state = {
        "synthesis": {
            "analysis_status": "insufficient_evidence",
            "agent_type": "Unknown",
            "tech_stack_summary": {"ko": "미확인", "en": "Unknown"},
        },
        "claims": [],
        "evidence_signals": [],
        "task_results": [],
        "risk_signals": [],
        "follow_up_guide": {"ko": "README를 확인하세요.", "en": "Check README."},
        "analysis_limitations": {"missing_inputs": ["source_files"], "truncated_inputs": [], "notes": ["limited"]},
    }
    result = finalize_analysis(state)

    assert result["final_result"]["analysis_status"] == "insufficient_evidence"
    assert quality_gate({**state, **result})["quality_gate_result"]["critical_errors"] == []


def test_finalize_analysis_uses_area_explorer_agent_type_when_synthesis_lacks_it():
    state = {
        "synthesis": {"analysis_status": "completed"},
        "agent_type": "ToolUse",
        "area_findings": [
            {
                "area_id": area_id,
                "area_name": area_name,
                "status": "confirmed",
                "summary": "요약",
                "findings": [],
                "limitations": [],
                "unresolved_questions": [],
            }
            for area_id, area_name in [
                ("project-purpose", "프로젝트 목적과 주요 기능"),
                ("execution-flow", "진입점과 핵심 실행 흐름"),
                ("architecture-and-modules", "아키텍처와 모듈 관계"),
                ("agent-and-llm", "Agent·LLM 핵심 로직"),
                ("tools-and-integrations", "Tool·외부 서비스 연동"),
                ("state-and-storage", "상태·메모리·데이터 저장"),
                ("configuration-and-deployment", "설정·실행·배포 방법"),
                ("examples-and-tests", "예제·테스트·확장 지점"),
            ]
        ],
        "evidence_refs": [],
        "evidence_signals": [],
        "risk_signals": [],
        "analysis_limitations": {"missing_inputs": [], "truncated_inputs": [], "notes": []},
    }

    result = finalize_analysis(state)

    assert result["final_result"]["agent_type"] == "ToolUse"


def test_finalize_analysis_builds_document_contract_result():
    state = {
        "synthesis": {
            "analysis_status": "completed_with_limitations",
            "agent_type": "Unknown",
            "tech_stack_summary": {
                "primary_language": "Python",
                "frameworks": ["FastAPI"],
                "dependencies": ["langgraph"],
            },
        },
        "area_findings": [
            {
                "area_id": area_id,
                "area_name": area_name,
                "status": "confirmed",
                "summary": "요약",
                "findings": [],
                "limitations": [],
                "unresolved_questions": [],
            }
            for area_id, area_name in [
                ("project-purpose", "프로젝트 목적과 주요 기능"),
                ("execution-flow", "진입점과 핵심 실행 흐름"),
                ("architecture-and-modules", "아키텍처와 모듈 관계"),
                ("agent-and-llm", "Agent·LLM 핵심 로직"),
                ("tools-and-integrations", "Tool·외부 서비스 연동"),
                ("state-and-storage", "상태·메모리·데이터 저장"),
                ("configuration-and-deployment", "설정·실행·배포 방법"),
                ("examples-and-tests", "예제·테스트·확장 지점"),
            ]
        ],
        "evidence_refs": [
            {
                "id": "ref-1",
                "source_type": "code",
                "path": "src/server.py",
                "description": "server implementation",
                "chunk_id": "chunk-0001",
                "line_start": 1,
                "line_end": 2,
                "content_excerpt": "def create_app():\n    return app\n",
                "content_hash": "sha256:" + "1" * 64,
            }
        ],
        "analysis_limitations": {"missing_inputs": [], "truncated_inputs": [], "notes": ["정적 분석 결과"]},
    }

    result = finalize_analysis(state)
    final_result = result["final_result"]

    assert final_result["analysis_status"] == "completed_with_limitations"
    assert len(final_result["area_findings"]) == 8
    assert len(final_result["report_sections"]) == 11
    assert final_result["evidence_refs"][0]["chunk_id"] == "chunk-0001"
    assert quality_gate({**state, **result})["quality_gate_result"]["critical_errors"] == []


def test_finalize_analysis_fallback_report_mentions_evidence_paths():
    state = {
        "area_findings": [
            {
                "area_id": aid,
                "area_name": aname,
                "status": "partially_confirmed",
                "summary": f"{aname} summary",
                "findings": [
                    {
                        "content": f"{aname} finding",
                        "type": "fact",
                        "evidence_refs": ["ref-1"],
                    }
                ],
                "limitations": [],
                "unresolved_questions": [],
            }
            for aid, aname in COMMON_ANALYSIS_AREAS
        ],
        "evidence_refs": [
            {
                "id": "ref-1",
                "source_type": "code",
                "path": "src/server.py",
                "description": "server implementation",
                "line_start": 1,
                "line_end": 1,
                "content_excerpt": "def create_app(): pass",
                "content_hash": "sha256:" + "1" * 64,
            }
        ],
        "analysis_limitations": {"missing_inputs": [], "truncated_inputs": [], "notes": []},
    }

    result = finalize_analysis(state)
    first_body = result["final_result"]["report_sections"][0]["body_markdown"]

    assert "src/server.py:1-1" in first_body
    assert "def create_app(): pass" in first_body


def test_finalize_analysis_skip_finalize_agent_env_uses_evidence_fallback(monkeypatch):
    monkeypatch.setenv("AGENTTRACE_SKIP_FINALIZE_AGENT", "1")
    state = {
        "area_findings": [
            {
                "area_id": aid,
                "area_name": aname,
                "status": "partially_confirmed",
                "summary": f"{aname} summary",
                "findings": [],
                "limitations": [],
                "unresolved_questions": [],
            }
            for aid, aname in COMMON_ANALYSIS_AREAS
        ],
        "evidence_refs": [
            {
                "id": "ref-1",
                "source_type": "code",
                "path": "src/server.py",
                "description": "server implementation",
                "line_start": 1,
                "line_end": 1,
                "content_excerpt": "def create_app(): pass",
                "content_hash": "sha256:" + "1" * 64,
            }
        ],
        "analysis_limitations": {"missing_inputs": [], "truncated_inputs": [], "notes": []},
    }

    result = finalize_analysis(state)

    assert "src/server.py:1-1" in result["final_result"]["report_sections"][0]["body_markdown"]


def test_finalize_analysis_fallback_report_uses_section_specific_content(monkeypatch):
    monkeypatch.setenv("AGENTTRACE_SKIP_FINALIZE_AGENT", "1")
    area_findings = []
    for aid, aname in COMMON_ANALYSIS_AREAS:
        evidence_id = "ref-exec" if aid == "execution-flow" else "ref-purpose"
        area_findings.append(
            {
                "area_id": aid,
                "area_name": aname,
                "status": "partially_confirmed",
                "summary": f"{aname} summary",
                "findings": [
                    {
                        "content": f"{aname} finding",
                        "type": "fact",
                        "evidence_refs": [evidence_id],
                    }
                ],
                "limitations": [],
                "unresolved_questions": [],
            }
        )
    state = {
        "area_findings": area_findings,
        "evidence_refs": [
            {
                "id": "ref-purpose",
                "source_type": "doc",
                "path": "README.md",
                "description": "project overview",
                "line_start": 1,
                "line_end": 2,
                "content_excerpt": "# Repo\nAgent tool docs",
                "content_hash": "sha256:" + "1" * 64,
            },
            {
                "id": "ref-exec",
                "source_type": "code",
                "path": "src/server.ts",
                "description": "server entrypoint",
                "line_start": 1,
                "line_end": 1,
                "content_excerpt": "export function createServer() {}",
                "content_hash": "sha256:" + "2" * 64,
            },
        ],
        "analysis_limitations": {"missing_inputs": [], "truncated_inputs": [], "notes": []},
    }

    result = finalize_analysis(state)
    bodies = [section["body_markdown"] for section in result["final_result"]["report_sections"]]
    execution_body = result["final_result"]["report_sections"][3]["body_markdown"]

    assert all("수집된 AreaFinding과 EvidenceRef" not in body for body in bodies)
    assert "src/server.ts:1-1" in execution_body
    assert "README.md:1-2" not in execution_body
    assert len(set(bodies)) > 3


def test_quality_gate_rejects_document_contract_reference_break():
    state = {
        "analysis_limitations": {"missing_inputs": [], "truncated_inputs": [], "notes": []},
        "content_chunks": [
            {
                "chunk_id": "chunk-0001",
                "file_path": "src/server.py",
                "content": "def create_app(): pass",
                "line_start": 1,
                "line_end": 1,
                "content_hash": "sha256:" + "1" * 64,
            }
        ],
    }
    result = finalize_analysis(state)
    result["final_result"]["area_findings"][0]["findings"][0]["evidence_refs"] = ["missing-ref"]

    gate = quality_gate({**state, **result})

    assert gate["quality_gate_result"]["critical_errors"]
    assert "AnalysisResult schema invalid" in gate["quality_errors"]


def test_quality_gate_rejects_confirmed_finding_without_hydrated_evidence():
    state = {
        "final_result": {
            "analysis_status": "completed",
            "agent_type": "ToolUse",
            "area_findings": [
                {
                    "area_id": aid,
                    "area_name": aname,
                    "status": "confirmed",
                    "summary": "confirmed summary",
                    "findings": [
                        {
                            "content": "confirmed claim",
                            "type": "fact",
                            "evidence_refs": ["ref-1"],
                        }
                    ],
                    "limitations": [],
                    "unresolved_questions": [],
                }
                for aid, aname in COMMON_ANALYSIS_AREAS
            ],
            "evidence_refs": [
                {
                    "id": "ref-1",
                    "source_type": "code",
                    "path": "src/app.py",
                    "description": "missing hydrated fields",
                }
            ],
            "report_sections": [],
            "evidence_signals": [],
            "risk_signals": [],
            "follow_up_guide": {"ko": "확인", "en": "Check"},
            "analysis_limitations": {"missing_inputs": [], "truncated_inputs": [], "notes": []},
        }
    }

    gate = quality_gate(state)

    assert not gate["quality_gate_result"]["critical_errors"]
    assert "confirmed evidence ref missing content_excerpt" in gate["quality_gate_result"]["warnings"]


def test_quality_gate_rejects_excerpt_mismatch_when_source_available(tmp_path):
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "app.py").write_text("alpha\nbeta\n", encoding="utf-8")
    state = {
        "local_repo_dir": str(repo),
        "final_result": {
            "analysis_status": "completed",
            "agent_type": "ToolUse",
            "area_findings": [
                {
                    "area_id": aid,
                    "area_name": aname,
                    "status": "confirmed",
                    "summary": "confirmed summary",
                    "findings": [
                        {
                            "content": "confirmed claim",
                            "type": "fact",
                            "evidence_refs": ["ref-1"],
                        }
                    ],
                    "limitations": [],
                    "unresolved_questions": [],
                }
                for aid, aname in COMMON_ANALYSIS_AREAS
            ],
            "evidence_refs": [
                {
                    "id": "ref-1",
                    "source_type": "code",
                    "path": "src/app.py",
                    "description": "wrong excerpt",
                    "line_start": 2,
                    "line_end": 2,
                    "content_excerpt": "not beta",
                    "content_hash": "sha256:" + "0" * 64,
                }
            ],
            "report_sections": [],
            "evidence_signals": [],
            "risk_signals": [],
            "follow_up_guide": {"ko": "확인", "en": "Check"},
            "analysis_limitations": {"missing_inputs": [], "truncated_inputs": [], "notes": []},
        },
    }

    gate = quality_gate(state)

    assert not gate["quality_gate_result"]["critical_errors"]
    assert any("excerpt mismatch" in warning for warning in gate["quality_gate_result"]["warnings"])


def test_persist_analysis_renders_report_markdown_from_sections():
    state = {
        "run_id": "run-1",
        "final_result": {
            "report_sections": [
                {
                    "section_id": 1,
                    "section_name": "핵심 요약",
                    "status": "confirmed",
                    "title": "1. 핵심 요약",
                    "body_markdown": "본문",
                    "mermaid_diagram": "flowchart TD\n  A --> B",
                }
            ]
        },
    }

    result = persist_analysis(state)
    payload = result["callback_payload"]

    assert payload["analysis_report"]["body_markdown"].startswith("# 1. 핵심 요약")
    assert "```mermaid" in payload["analysis_report"]["body_markdown"]


def test_persist_analysis_trace_contains_evaluation_artifacts():
    state = {
        "run_id": "run-1",
        "input_manifest": {"source_file_count": 1},
        "precheck_result": {"status": "ok"},
        "evidence_refs": [
            {
                "ref_id": "src-1",
                "path": "src/app.py",
                "line_start": 10,
                "line_end": 12,
                "content_excerpt": "def run():",
                "content_hash": "sha256:abc",
            }
        ],
        "evidence_signals": [{"path": "src/app.py", "signal": "tool_loop"}],
        "analysis_limitations": {"missing_inputs": [], "truncated_inputs": [], "notes": []},
        "quality_gate_result": {"critical_errors": []},
        "final_result": {"status": "COMPLETED", "report_sections": []},
    }

    result = persist_analysis(state)

    trace = result["callback_payload"]["trace"]
    assert trace["input_manifest"] == state["input_manifest"]
    assert trace["precheck_result"] == state["precheck_result"]
    assert trace["evidence_refs"] == state["evidence_refs"]
    assert trace["evidence_signals"] == state["evidence_signals"]
    assert trace["analysis_limitations"] == state["analysis_limitations"]
    assert trace["quality_gate_result"] == state["quality_gate_result"]
    assert trace["final_result"] == state["final_result"]


def test_validate_mermaid_syntax():
    # Valid diagrams
    flowchart_ok = """
    flowchart TD
      A[Start] --> B(Process)
      B --> C{Decision}
      C -->|Yes| D[End]
    """
    assert validate_mermaid_syntax(flowchart_ok) is True

    seq_ok = """
    sequenceDiagram
      Alice->>Bob: Hello Bob, how are you?
      Bob-->>Alice: Jolly good!
    """
    assert validate_mermaid_syntax(seq_ok) is True

    # Invalid header
    invalid_header = """
    invalidDiagram
      A --> B
    """
    assert validate_mermaid_syntax(invalid_header) is False

    # Mismatched bracket
    mismatched_bracket = """
    flowchart TD
      A[Start) --> B
    """
    assert validate_mermaid_syntax(mismatched_bracket) is False

    # Arrow length error (e.g. 4 or more hyphens/equals in arrow)
    arrow_err = """
    flowchart TD
      A ----> B
    """
    assert validate_mermaid_syntax(arrow_err) is False

    # Empty code
    assert validate_mermaid_syntax("") is False
    assert validate_mermaid_syntax("   \n  \n") is False


# ─── test_finalize_analysis_with_llm_success (rewrite) ────────────────────────────

def test_finalize_analysis_with_llm_success(monkeypatch):
    """synthesis가 ReportBodyResult, Mermaid가 MermaidResult로 분리 동작."""
    import agenttrace.agents.analysis.nodes.finalize_analysis as fa_module
    from agenttrace.agents.analysis.nodes.finalize_analysis import (
        ReportBodyResult, ReportBodySection, MermaidResult,
    )
    from agenttrace.agents.analysis.schemas.result import COMMON_ANALYSIS_AREAS

    class FakeBodyModel:
        def invoke(self, prompt_value):
            return ReportBodyResult(report_sections=[
                ReportBodySection(
                    section_id=idx, section_name=f"섭션 {idx}",
                    status="confirmed", title=f"{idx}. 섭션 {idx}",
                    body_markdown=f"내용 {idx}",
                )
                for idx in range(1, 12)
            ])

    class FakeMermaidModel:
        def invoke(self, prompt_value):
            return MermaidResult(mermaid_code="flowchart TD\n  A --> B")

    class FakeModel:
        def with_structured_output(self, schema):
            if schema == ReportBodyResult:
                return FakeBodyModel()
            if schema == MermaidResult:
                return FakeMermaidModel()
            raise ValueError(f"Unknown schema: {schema}")

    monkeypatch.setattr(fa_module, "build_openai_finalize_model", lambda: FakeModel())

    import agenttrace.config
    original_get_settings = agenttrace.config.get_settings
    def mocked_get_settings():
        settings = original_get_settings()
        from dataclasses import replace
        return replace(settings, openai_api_key="fake-key")
    monkeypatch.setattr(agenttrace.config, "get_settings", mocked_get_settings)
    monkeypatch.setattr(fa_module, "get_settings", mocked_get_settings)

    from agenttrace.agents.analysis.nodes.finalize_analysis import finalize_analysis
    state = {
        "readme": "Project Readme",
        "synthesis": {"analysis_status": "completed", "agent_type": "Unknown"},
        "area_findings": [
            {
                "area_id": area_id,
                "area_name": area_name,
                "status": "confirmed",
                "summary": "요약",
                "findings": [],
                "limitations": [],
                "unresolved_questions": [],
            }
            for area_id, area_name in COMMON_ANALYSIS_AREAS
        ],
        "evidence_refs": [],
        "evidence_signals": [],
        "risk_signals": [],
        "analysis_limitations": {"missing_inputs": [], "truncated_inputs": [], "notes": []},
    }

    result = finalize_analysis(state)
    report_sections = result["final_result"]["report_sections"]
    assert len(report_sections) == 11
    # 섭션 4·5에 Mermaid 생성됨
    assert report_sections[3]["mermaid_diagram"] == "flowchart TD\n  A --> B"
    assert report_sections[4]["mermaid_diagram"] == "flowchart TD\n  A --> B"


# ─── test_finalize_analysis_with_llm_mermaid_retry (rewrite) ─────────────────────

def test_finalize_analysis_with_llm_mermaid_retry(monkeypatch):
    """Mermaid 1회 invalid → retry → valid 반환 경로."""
    import agenttrace.agents.analysis.nodes.finalize_analysis as fa_module
    from agenttrace.agents.analysis.nodes.finalize_analysis import (
        ReportBodyResult, ReportBodySection, MermaidResult,
    )
    from agenttrace.agents.analysis.schemas.result import COMMON_ANALYSIS_AREAS

    class FakeBodyModel:
        def invoke(self, prompt_value):
            return ReportBodyResult(report_sections=[
                ReportBodySection(
                    section_id=idx, section_name=f"섭션 {idx}",
                    status="confirmed", title=f"{idx}. 섭션 {idx}",
                    body_markdown=f"내용 {idx}",
                )
                for idx in range(1, 12)
            ])

    class FakeMermaidModel:
        def __init__(self):
            self.call_count = 0

        def invoke(self, prompt_value):
            self.call_count += 1
            # 첫 호출: invalid syntax (괄호 불일치)
            if self.call_count == 1:
                return MermaidResult(mermaid_code="flowchart TD\n  A[Start) --> B")
            # retry: valid
            return MermaidResult(mermaid_code="flowchart TD\n  A --> B")

    fake_mermaid = FakeMermaidModel()

    class FakeModel:
        def with_structured_output(self, schema):
            if schema == ReportBodyResult:
                return FakeBodyModel()
            if schema == MermaidResult:
                return fake_mermaid
            raise ValueError(f"Unknown schema: {schema}")

    monkeypatch.setattr(fa_module, "build_openai_finalize_model", lambda: FakeModel())

    import agenttrace.config
    original_get_settings = agenttrace.config.get_settings
    def mocked_get_settings():
        settings = original_get_settings()
        from dataclasses import replace
        return replace(settings, openai_api_key="fake-key")
    monkeypatch.setattr(agenttrace.config, "get_settings", mocked_get_settings)
    monkeypatch.setattr(fa_module, "get_settings", mocked_get_settings)

    from agenttrace.agents.analysis.nodes.finalize_analysis import finalize_analysis
    state = {
        "readme": "Project Readme",
        "synthesis": {"analysis_status": "completed", "agent_type": "Unknown"},
        "area_findings": [
            {
                "area_id": area_id,
                "area_name": area_name,
                "status": "confirmed",
                "summary": "요약",
                "findings": [],
                "limitations": [],
                "unresolved_questions": [],
            }
            for area_id, area_name in COMMON_ANALYSIS_AREAS
        ],
        "evidence_refs": [],
        "evidence_signals": [],
        "risk_signals": [],
        "analysis_limitations": {"missing_inputs": [], "truncated_inputs": [], "notes": []},
    }

    result = finalize_analysis(state)
    report_sections = result["final_result"]["report_sections"]
    assert len(report_sections) == 11
    # 섭션 4: retry 후 valid Mermaid 반환
    assert report_sections[3]["mermaid_diagram"] == "flowchart TD\n  A --> B"
    # _generate_mermaid_for_section이 섭션 4·5 각각 최대 2회 호출 가능
    assert fake_mermaid.call_count >= 2


# ─── test_finalize_analysis_with_llm_mermaid_fail_after_retry (rewrite) ──────────

def test_finalize_analysis_with_llm_mermaid_fail_after_retry(monkeypatch):
    """Mermaid 2회 모두 invalid → None 반환 (섭션에서 mermaid_diagram=None)."""
    import agenttrace.agents.analysis.nodes.finalize_analysis as fa_module
    from agenttrace.agents.analysis.nodes.finalize_analysis import (
        ReportBodyResult, ReportBodySection, MermaidResult,
    )
    from agenttrace.agents.analysis.schemas.result import COMMON_ANALYSIS_AREAS

    class FakeBodyModel:
        def invoke(self, prompt_value):
            return ReportBodyResult(report_sections=[
                ReportBodySection(
                    section_id=idx, section_name=f"섭션 {idx}",
                    status="confirmed", title=f"{idx}. 섭션 {idx}",
                    body_markdown=f"내용 {idx}",
                )
                for idx in range(1, 12)
            ])

    class FakeMermaidModel:
        def invoke(self, prompt_value):
            # 항상 invalid syntax 반환
            return MermaidResult(mermaid_code="flowchart TD\n  A[Start) --> B")

    class FakeModel:
        def with_structured_output(self, schema):
            if schema == ReportBodyResult:
                return FakeBodyModel()
            if schema == MermaidResult:
                return FakeMermaidModel()
            raise ValueError(f"Unknown schema: {schema}")

    monkeypatch.setattr(fa_module, "build_openai_finalize_model", lambda: FakeModel())

    import agenttrace.config
    original_get_settings = agenttrace.config.get_settings
    def mocked_get_settings():
        settings = original_get_settings()
        from dataclasses import replace
        return replace(settings, openai_api_key="fake-key")
    monkeypatch.setattr(agenttrace.config, "get_settings", mocked_get_settings)
    monkeypatch.setattr(fa_module, "get_settings", mocked_get_settings)

    from agenttrace.agents.analysis.nodes.finalize_analysis import finalize_analysis
    state = {
        "readme": "Project Readme",
        "synthesis": {"analysis_status": "completed", "agent_type": "Unknown"},
        "area_findings": [
            {
                "area_id": area_id,
                "area_name": area_name,
                "status": "confirmed",
                "summary": "요약",
                "findings": [],
                "limitations": [],
                "unresolved_questions": [],
            }
            for area_id, area_name in COMMON_ANALYSIS_AREAS
        ],
        "evidence_refs": [],
        "evidence_signals": [],
        "risk_signals": [],
        "analysis_limitations": {"missing_inputs": [], "truncated_inputs": [], "notes": []},
    }

    result = finalize_analysis(state)
    report_sections = result["final_result"]["report_sections"]
    assert len(report_sections) == 11
    # Mermaid 2회 실패 → None
    assert report_sections[3]["mermaid_diagram"] is None


from agenttrace.agents.analysis.nodes.finalize_analysis import _generate_mermaid_for_section

def test_generate_mermaid_for_section_returns_valid_diagram(monkeypatch):
    """첫 호출에서 valid diagram 반환."""
    import agenttrace.agents.analysis.nodes.finalize_analysis as fa_module
    from agenttrace.agents.analysis.nodes.finalize_analysis import MermaidResult
    from unittest.mock import MagicMock

    mock_model = MagicMock()
    mock_model.with_structured_output.return_value = mock_model
    mock_model.invoke.return_value = MermaidResult(
        mermaid_code="flowchart TD\n  A[Input] --> B[Output]"
    )
    monkeypatch.setattr(fa_module, "build_openai_finalize_model", lambda: mock_model)

    result = _generate_mermaid_for_section(
        section_id=4, section_name="전체 동작 방식",
        readme="# Test Repo", area_summary="흐름 요약"
    )
    assert result == "flowchart TD\n  A[Input] --> B[Output]"
    assert mock_model.invoke.call_count == 1  # retry 불필요


def test_generate_mermaid_for_section_returns_none_on_failure(monkeypatch):
    """예외 발생 시 None 반환 (graceful fallback)."""
    import agenttrace.agents.analysis.nodes.finalize_analysis as fa_module
    from unittest.mock import MagicMock

    mock_model = MagicMock()
    mock_model.with_structured_output.return_value = mock_model
    mock_model.invoke.side_effect = RuntimeError("API error")
    monkeypatch.setattr(fa_module, "build_openai_finalize_model", lambda: mock_model)

    result = _generate_mermaid_for_section(
        section_id=4, section_name="전체 동작 방식",
        readme="# Test", area_summary=""
    )
    assert result is None
from agenttrace.agents.analysis.nodes.finalize_analysis import (
    _compact_area_findings,
    _compact_evidence_refs,
)


def test_compact_area_findings_reduces_size_and_preserves_unresolved():
    findings = [
        {
            "area_id": "project-purpose",
            "area_name": "프로젝트 목적과 주요 기능",
            "status": "confirmed",
            "summary": "이 프로젝트는 X를 합니다.",
            "findings": [
                {"content": f"finding {i}", "type": "fact", "evidence_refs": [f"ref-{i}"]}
                for i in range(1, 8)
            ],
            "limitations": ["한계 1", "한계 2", "한계 3", "한계 4"],
            "unresolved_questions": ["질문 A", "질문 B", "질문 C", "질문 D"],
        }
    ]
    result = _compact_area_findings(findings)
    assert "project-purpose" in result
    assert "confirmed" in result
    assert "area_name" in result
    # top-5 findings만 포함
    assert "finding 5" in result
    assert "finding 6" not in result
    # limitations top-3만 포함
    assert "한계 3" in result
    assert "한계 4" not in result
    # unresolved_questions top-3 보존
    assert "질문 A" in result
    assert "질문 C" in result
    assert "질문 D" not in result


def test_compact_evidence_refs_excludes_content_excerpt():
    refs = [
        {
            "id": "ref-1",
            "path": "src/main.py",
            "description": "설명",
            "content_excerpt": "def main(): ...",
            "symbol": None,
        }
    ]
    result = _compact_evidence_refs(refs)
    assert "ref-1" in result
    assert "src/main.py" in result
    assert "def main():" in result  # content_excerpt 포함 (품질 개선)


def test_finalize_model_config_defaults():
    """build_openai_finalize_model이 timeout=90, max_tokens=8192 기본값을 가지는가."""
    from agenttrace.config import get_settings
    settings = get_settings()
    assert settings.finalize_model_timeout == 90
    assert settings.finalize_model_max_tokens == 8192
