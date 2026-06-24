from uuid import uuid4

from agenttrace.agents.analysis.graph import build_graph
from agenttrace.agents.analysis.schemas.result import COMMON_ANALYSIS_AREAS


def _area_findings(status: str = "confirmed"):
    return [
        {
            "area_id": area_id,
            "area_name": area_name,
            "status": status,
            "summary": f"{area_name} summary",
            "findings": [],
            "limitations": [],
            "unresolved_questions": [],
        }
        for area_id, area_name in COMMON_ANALYSIS_AREAS
    ]


def _patch_deterministic_analysis(monkeypatch):
    import agenttrace.agents.analysis.graph as graph_module
    import agenttrace.agents.analysis.nodes.finalize_analysis as finalize_module
    import agenttrace.config

    def fake_area_explorer(state):
        return {
            "area_findings": _area_findings(),
            "evidence_refs": [
                {
                    "id": "ref-1",
                    "source_type": "code",
                    "path": "src/server.py",
                    "description": "server implementation",
                }
            ],
            "evidence_signals": [],
            "agent_type": "ToolUse",
            "synthesis": {
                "analysis_status": "completed",
                "agent_type": "ToolUse",
                "tech_stack_summary": {"ko": "Python", "en": "Python"},
            },
        }

    monkeypatch.setattr(graph_module, "area_explorer", fake_area_explorer)

    original_get_settings = agenttrace.config.get_settings

    def mocked_get_settings():
        from dataclasses import replace

        return replace(original_get_settings(), openai_api_key=None)

    monkeypatch.setattr(finalize_module, "get_settings", mocked_get_settings)


class RecordingContentIndexStore:
    def __init__(self):
        self.requests = []

    def request_index(self, **kwargs):
        self.requests.append(kwargs)
        return {"index_id": "idx-1", "status": "COMPLETED"}


class RecordingEmbeddingService:
    def __init__(self):
        self.texts = []

    def embed_texts(self, texts):
        self.texts.extend(texts)
        return [[0.1] * 1536 for _ in texts]


class RecordingEmbeddingStore:
    def __init__(self):
        self.rows = []

    def update_embeddings(self, rows):
        self.rows.extend(rows)
        return [{"chunk_id": row["chunk_id"]} for row in rows]


def test_analysis_v2_graph_limited_path_completes_with_insufficient_evidence(monkeypatch):
    _patch_deterministic_analysis(monkeypatch)
    graph = build_graph()
    result = graph.invoke(
        {
            "analysis_request": {
                "analysis_id": str(uuid4()),
                "repository": {"full_name": "owner/repo", "github_url": "https://github.com/owner/repo"},
                "snapshot": {"snapshot_id": "snap-1"},
                "readme_text": "# Repo\nProvides an MCP server.",
                "file_tree": ["README.md", "src/server.py"],
                "external_ingest": {"enabled": False, "provider": "gitingest"},
            },
            "evidence_signals": [],
            "risk_signals": [],
            "quality_warnings": [],
            "quality_errors": [],
        }
    )

    assert result["final_result"]["analysis_status"] in {"completed", "completed_with_limitations"}
    assert result["callback_payload"]["analysis_result"]["analysis_limitations"]["missing_inputs"]


def test_analysis_v2_graph_runs_area_pipeline_with_source_files(monkeypatch):
    _patch_deterministic_analysis(monkeypatch)
    graph = build_graph()

    result = graph.invoke(
        {
            "analysis_request": {
                "analysis_id": str(uuid4()),
                "repository": {"full_name": "owner/repo", "github_url": "https://github.com/owner/repo"},
                "snapshot": {"snapshot_id": "snap-1"},
                "readme_text": "# Repo\nProvides an MCP server.",
                "file_tree": ["README.md", "src/server.py"],
                "source_files": [{"path": "src/server.py", "content": "def register_tool(): pass"}],
                "external_ingest": {"enabled": False, "provider": "gitingest"},
            },
            "evidence_signals": [],
            "risk_signals": [],
            "quality_warnings": [],
            "quality_errors": [],
        }
    )

    assert result["agent_type"] == "ToolUse"
    assert len(result["area_findings"]) == 8
    assert result["evidence_refs"][0]["path"] == "src/server.py"
    assert result["final_result"]["analysis_status"] == "completed"
