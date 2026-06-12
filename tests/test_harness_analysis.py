import json
from pathlib import Path

from agenttrace.agents.analysis.nodes.harness_analyzer import harness_analyzer
from agenttrace.agents.analysis.nodes.quality_gate import quality_gate
from agenttrace.agents.analysis.graph import build_graph


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "data" / "fixtures"


def _load_fixture(name: str) -> dict:
    with (FIXTURE_DIR / name).open() as fixture:
        return json.load(fixture)


def test_harness_analyzer_detects_high_relevance_from_static_structure():
    state = {
        "readme": "This repository provides a coding agent harness with tools, sandbox, permissions, and memory.",
        "file_tree": [
            {"path": "src/agent_loop.py", "type": "file"},
            {"path": "src/tools/registry.py", "type": "file"},
            {"path": "src/workspace/sandbox.py", "type": "file"},
            {"path": "src/permissions/policy.py", "type": "file"},
            {"path": "src/memory/context.py", "type": "file"},
            {"path": "tests/test_tool_execution.py", "type": "file"},
        ],
        "selected_files": [
            {
                "path": "src/agent_loop.py",
                "content": "while step < max_iterations:\n    next_action = planner.run_step(state)\n    invoke_tool(next_action)",
            }
        ],
        "evidence_signals": [
            {
                "id": "evidence-1",
                "signal_type": "FILE_PATH",
                "path": "src/tools/registry.py",
                "summary": "Tool registry path is present.",
                "confidence": 0.8,
            }
        ],
    }

    result = harness_analyzer(state)

    assert result["harness_relevance"]["level"] == "high"
    assert result["harness_capabilities"]["agent_loop"]["present"] is True
    assert result["harness_capabilities"]["tool_system"]["present"] is True
    assert result["harness_capabilities"]["sandbox_or_workspace"]["present"] is True
    assert result["harness_capabilities"]["permission_control"]["present"] is True
    assert result["harness_relevance"]["evidence"]


def test_harness_analyzer_keeps_readme_only_claim_low_confidence():
    state = {
        "readme": "This is a powerful AI agent platform for autonomous work.",
        "file_tree": [{"path": "README.md", "type": "file"}, {"path": "docs/overview.md", "type": "file"}],
        "selected_files": [],
        "evidence_signals": [],
    }

    result = harness_analyzer(state)

    assert result["harness_relevance"]["level"] in {"low", "none"}
    assert result["harness_relevance"]["confidence"] in {"low", "medium"}
    assert result["harness_capabilities"]["agent_loop"]["present"] is False
    assert result["negative_evidence"]
    assert result["followup_questions"]


def test_harness_analyzer_detects_medium_skill_or_tool_surface():
    state = {
        "readme": "This repository ships an MCP server and reusable agent skills.",
        "file_tree": [
            {"path": "server.py", "type": "file"},
            {"path": "tools/weather.py", "type": "file"},
            {"path": "skills/weather/SKILL.md", "type": "file"},
            {"path": "mcp.json", "type": "file"},
        ],
        "selected_files": [],
        "evidence_signals": [],
    }

    result = harness_analyzer(state)

    assert result["harness_relevance"]["level"] == "medium"
    assert result["harness_capabilities"]["tool_system"]["present"] is True
    assert result["harness_capabilities"]["skill_system"]["present"] is True
    assert result["harness_capabilities"]["agent_loop"]["present"] is False


def test_analysis_graph_persists_harness_fields():
    graph = build_graph()
    result = graph.invoke(
        {
            "run_id": "run-1",
            "repository_id": "repo-1",
            "full_name": "acme/harness",
            "github_url": "https://github.com/acme/harness",
            "trigger": "MANUAL",
            "repository_snapshot": {
                "repository_id": "repo-1",
                "full_name": "acme/harness",
                "github_url": "https://github.com/acme/harness",
                "metadata": {},
                "readme": "Coding agent harness with tools and sandbox.",
                "file_tree": [
                    {"path": "src/agent_loop.py", "type": "file"},
                    {"path": "src/tools/registry.py", "type": "file"},
                    {"path": "src/workspace/sandbox.py", "type": "file"},
                ],
            },
        }
    )

    persisted = result["persisted_analysis"]
    assert persisted["harness_relevance"]["level"] in {"medium", "high"}
    assert persisted["harness_capabilities"]["agent_loop"]["present"] is True
    assert "followup_questions" in persisted


def test_analysis_graph_uses_snapshot_selected_files_for_source_evidence():
    graph = build_graph()
    result = graph.invoke(
        {
            "run_id": "run-selected-files",
            "repository_id": "repo-selected-files",
            "full_name": "acme/source-snippets",
            "github_url": "https://github.com/acme/source-snippets",
            "trigger": "MANUAL",
            "repository_snapshot": {
                "repository_id": "repo-selected-files",
                "full_name": "acme/source-snippets",
                "github_url": "https://github.com/acme/source-snippets",
                "metadata": {},
                "readme": "Minimal repo with source snippets.",
                "file_tree": [{"path": "README.md", "type": "file"}],
                "selected_files": [
                    {
                        "path": "src/agent_loop.py",
                        "content": (
                            "while step < max_iterations:\n"
                            "    next_action = planner.run_step(state)\n"
                            "    invoke_tool(next_action)"
                        ),
                    }
                ],
            },
        }
    )

    persisted = result["persisted_analysis"]
    assert persisted["harness_capabilities"]["agent_loop"]["present"] is True
    assert any(
        item["type"] == "source_code" and "agent_loop" in item["supports"]
        for item in persisted["harness_relevance"]["evidence"]
    )


def test_harness_analyzer_does_not_mark_generic_path_only_layout_high():
    state = {
        "readme": "Generic automation utilities.",
        "file_tree": [
            {"path": "workflow/graph.py", "type": "file"},
            {"path": "tools/reporting.py", "type": "file"},
            {"path": "workspace/models.py", "type": "file"},
            {"path": "policy/rules.py", "type": "file"},
        ],
        "selected_files": [],
        "evidence_signals": [],
    }

    result = harness_analyzer(state)

    assert result["harness_relevance"]["level"] != "high"


def test_harness_analyzer_does_not_mark_generic_path_only_layout_high_even_with_harness_readme():
    result = harness_analyzer(
        {
            "readme": "Coding agent harness for autonomous work.",
            "file_tree": [
                {"path": "workflow/graph.py", "type": "file"},
                {"path": "tools/reporting.py", "type": "file"},
                {"path": "workspace/models.py", "type": "file"},
                {"path": "policy/rules.py", "type": "file"},
            ],
            "selected_files": [],
            "evidence_signals": [],
        }
    )

    assert result["harness_relevance"]["level"] != "high"


def test_harness_analyzer_does_not_mark_generic_config_path_only_layout_high():
    result = harness_analyzer(
        {
            "readme": "Coding agent harness for autonomous work.",
            "file_tree": [
                {"path": "src/runner.py", "type": "file"},
                {"path": "src/tools/api.py", "type": "file"},
                {"path": "config/workspace.yaml", "type": "file"},
                {"path": "config/policy.yaml", "type": "file"},
            ],
            "selected_files": [],
            "evidence_signals": [],
        }
    )

    assert result["harness_relevance"]["level"] != "high"


def test_high_harness_fixture_expected_output():
    result = harness_analyzer(_load_fixture("high_harness_repo.json"))

    assert result["harness_relevance"]["level"] == "high"
    assert result["harness_capabilities"]["agent_loop"]["present"] is True
    assert result["harness_capabilities"]["tool_system"]["present"] is True
    assert result["harness_capabilities"]["permission_control"]["present"] is True
    assert result["harness_capabilities"]["sandbox_or_workspace"]["present"] is True


def test_medium_skill_or_mcp_fixture_expected_output():
    result = harness_analyzer(_load_fixture("medium_skill_or_mcp_repo.json"))

    assert result["harness_relevance"]["level"] == "medium"
    assert result["harness_capabilities"]["tool_system"]["present"] is True
    assert result["harness_capabilities"]["skill_system"]["present"] is True
    assert result["harness_capabilities"]["agent_loop"]["present"] is False


def test_low_readme_only_fixture_expected_output():
    result = harness_analyzer(_load_fixture("low_readme_only_agent_repo.json"))

    assert result["harness_relevance"]["level"] in {"low", "none"}
    assert result["harness_capabilities"]["agent_loop"]["present"] is False
    assert result["harness_capabilities"]["tool_system"]["present"] is False
    assert result["negative_evidence"]


def test_quality_gate_errors_when_high_harness_relevance_has_no_evidence():
    state = {
        "status": "COMPLETED",
        "claims": [],
        "evidence_signals": [
            {
                "id": "evidence-1",
                "path": "src/tools/registry.py",
                "claim_id": None,
            }
        ],
        "risk_signals": [],
        "followup_actions": [{"action": "READ_NOW", "reason": "Static evidence exists."}],
        "harness_relevance": {
            "level": "high",
            "reason": "High harness relevance.",
            "confidence": "high",
            "evidence": [],
            "negative_evidence": [],
        },
    }

    result = quality_gate(state)

    assert result["status"] == "NEEDS_HUMAN_REVIEW"
    assert any("harness_relevance" in item for item in result["quality_errors"])
