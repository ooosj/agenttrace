import pytest
from unittest.mock import MagicMock, patch

from agenttrace.agents.analysis.nodes.area_explorer import area_explorer, _sanitize_ref, _build_mock_result
from agenttrace.agents.analysis.schemas.result import (
    AreaExplorationResult,
    AreaFinding,
    EvidenceRef,
    COMMON_ANALYSIS_AREAS,
)


@pytest.fixture(autouse=True)
def disable_openai_api_key(monkeypatch):
    import agenttrace.config
    original_get_settings = agenttrace.config.get_settings

    def mocked_get_settings():
        settings = original_get_settings()
        from dataclasses import replace
        return replace(settings, openai_api_key=None)

    monkeypatch.setattr(agenttrace.config, "get_settings", mocked_get_settings)
    import agenttrace.agents.analysis.nodes.area_explorer as ae_module
    monkeypatch.setattr(ae_module, "get_settings", mocked_get_settings)


def test_area_explorer_returns_mock_without_api_key():
    state = {
        "run_id": "test-run",
        "readme": "# Test\nA test repo.",
        "file_tree": [{"path": "src/main.py"}],
    }
    result = area_explorer(state)

    assert len(result["area_findings"]) == 8
    assert result["agent_type"] == "Unknown"
    assert result["evidence_refs"] == []
    assert result["synthesis"]["analysis_status"] == "completed_with_limitations"


def test_mock_result_covers_all_8_areas():
    state = {"readme": "# Test"}
    result = _build_mock_result(state)

    area_ids = {af["area_id"] for af in result["area_findings"]}
    required_ids = {aid for aid, _ in COMMON_ANALYSIS_AREAS}
    assert area_ids == required_ids


def test_mock_result_uses_repo_map_and_source_files_as_evidence(tmp_path):
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "server.ts").write_text(
        "export function createMcpServer() { return { tool: 'search' }; }\n",
        encoding="utf-8",
    )
    (repo / "package.json").write_text(
        "{\"dependencies\":{\"@modelcontextprotocol/sdk\":\"latest\"}}\n",
        encoding="utf-8",
    )
    state = {
        "local_repo_dir": str(repo),
        "metadata": {"primary_language": "TypeScript", "topics": ["mcp", "docs"]},
        "repo_map": {
            "files": {
                "src/server.ts": {
                    "definitions": ["createMcpServer"],
                    "references": ["tool", "search"],
                    "category": "source",
                },
                "package.json": {
                    "definitions": [],
                    "references": ["@modelcontextprotocol/sdk"],
                    "category": "critical_config",
                },
            }
        },
        "file_catalog": [
            {"path": "src/server.ts", "category": "source"},
            {"path": "package.json", "category": "critical_config"},
        ],
    }

    result = _build_mock_result(state)

    assert result["evidence_refs"]
    assert result["evidence_refs"][0]["path"] == "src/server.ts"
    assert result["evidence_refs"][0]["source_type"] == "code"
    assert result["agent_type"] == "MCP"
    assert any(
        af["status"] in {"confirmed", "partially_confirmed"}
        and af["findings"][0]["evidence_refs"]
        for af in result["area_findings"]
    )


def test_mock_result_prioritizes_implementation_over_tests(tmp_path):
    repo = tmp_path / "repo"
    (repo / "src" / "__tests__").mkdir(parents=True)
    (repo / "src" / "server.ts").write_text("export function serve() {}\n", encoding="utf-8")
    (repo / "src" / "__tests__" / "server.test.ts").write_text(
        "import { serve } from '../server'; test('serve', () => serve());\n",
        encoding="utf-8",
    )
    state = {
        "local_repo_dir": str(repo),
        "repo_map": {
            "files": {
                "src/__tests__/server.test.ts": {
                    "definitions": ["serveTest"],
                    "references": ["test", "server", "tool", "mcp"],
                    "category": "test",
                },
                "src/server.ts": {
                    "definitions": ["serve"],
                    "references": ["server", "tool", "mcp"],
                    "category": "source",
                },
            }
        },
        "file_catalog": [
            {"path": "src/__tests__/server.test.ts", "category": "test"},
            {"path": "src/server.ts", "category": "source"},
        ],
    }

    result = _build_mock_result(state)

    assert result["evidence_refs"][0]["path"] == "src/server.ts"


def test_sanitize_ref_fixes_invalid_line_numbers():
    ref = {"line_start": 0, "line_end": -1}
    result = _sanitize_ref(ref)
    assert result["line_start"] is None
    assert result["line_end"] is None


def test_sanitize_ref_swaps_inverted_lines():
    ref = {"line_start": 10, "line_end": 5}
    result = _sanitize_ref(ref)
    assert result["line_start"] == 5
    assert result["line_end"] == 10


def test_sanitize_ref_keeps_valid_lines():
    ref = {"line_start": 3, "line_end": 8}
    result = _sanitize_ref(ref)
    assert result["line_start"] == 3
    assert result["line_end"] == 8


def test_area_explorer_with_mock_agent(monkeypatch):
    """Mock create_agent to return structured AreaExplorationResult."""
    import agenttrace.agents.analysis.nodes.area_explorer as ae_module

    mock_area_findings = [
        AreaFinding(
            area_id=aid, area_name=aname,
            status="confirmed", summary=f"{aname} 요약",
            findings=[], limitations=[], unresolved_questions=[],
        )
        for aid, aname in COMMON_ANALYSIS_AREAS
    ]
    mock_evidence_refs = [
        EvidenceRef(id="ref-1", source_type="code", path="src/main.py", description="main file"),
        EvidenceRef(id="ref-2", source_type="doc", path="README.md", description="readme"),
    ]
    mock_structured = AreaExplorationResult(
        area_findings=mock_area_findings,
        evidence_refs=mock_evidence_refs,
        agent_type="ToolUse",
    )

    mock_result = {"structured_response": mock_structured, "messages": []}

    mock_compiled = MagicMock()
    mock_compiled.invoke.return_value = mock_result

    mock_agent_builder = MagicMock()
    mock_agent_builder.return_value = mock_compiled

    monkeypatch.setattr(ae_module, "build_openai_analysis_model", lambda: MagicMock())
    monkeypatch.setattr(ae_module, "get_settings", lambda: MagicMock(openai_api_key="fake-key"))

    import langchain.agents
    monkeypatch.setattr(langchain.agents, "create_agent", mock_agent_builder)

    state = {
        "run_id": "test-run",
        "readme": "# Test Repo\nA test repo.",
        "file_tree": [{"path": "src/main.py"}],
        "repo_map": {"files": {}},
        "file_catalog": [],
    }

    result = area_explorer(state)

    assert len(result["area_findings"]) == 8
    assert result["agent_type"] == "ToolUse"
    assert len(result["evidence_refs"]) == 2
    assert result["evidence_refs"][0]["id"] == "ref-1"
    assert len(result["evidence_signals"]) == 2
    assert result["synthesis"]["analysis_status"] == "completed"


def test_area_explorer_can_skip_agent_and_use_fallback(monkeypatch, tmp_path):
    import agenttrace.agents.analysis.nodes.area_explorer as ae_module

    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "server.ts").write_text(
        "export function createMcpServer() { return { tool: 'search' }; }\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AGENTTRACE_SKIP_AREA_AGENT", "1")
    monkeypatch.setattr(ae_module, "get_settings", lambda: MagicMock(openai_api_key="fake-key"))

    called = {"create_agent": False}

    def fail_create_agent(*args, **kwargs):
        called["create_agent"] = True
        raise AssertionError("create_agent should not be called")

    import langchain.agents
    monkeypatch.setattr(langchain.agents, "create_agent", fail_create_agent)

    result = area_explorer({
        "run_id": "test-run",
        "local_repo_dir": str(repo),
        "repo_map": {
            "files": {
                "src/server.ts": {
                    "definitions": ["createMcpServer"],
                    "references": ["tool", "search", "mcp"],
                    "category": "source",
                }
            }
        },
        "file_catalog": [{"path": "src/server.ts", "category": "source"}],
    })

    assert result["evidence_refs"]
    assert result["agent_type"] == "MCP"
    assert called["create_agent"] is False
