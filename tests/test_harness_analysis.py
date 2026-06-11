from agenttrace.agents.analysis.nodes.harness_analyzer import harness_analyzer


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
