import json

from agenthub_analysis.nodes.analyzer import analyzer
from agenthub_analysis.nodes.evidence_scout import evidence_scout
from agenthub_analysis.nodes.quality_gate import quality_gate
from agenthub_analysis.nodes.risk_and_followup import risk_and_followup_planner


def test_analyzer_detects_mcp_server():
    state = {
        "status": "COLLECTED",
        "readme": "This project provides an MCP server with tools and resources.",
        "file_tree": [{"path": "src/server.py"}, {"path": "examples/mcp_demo.py"}],
        "claims": [],
    }
    result = analyzer(state)
    assert result["agent_type"] == "MCP_SERVER"
    assert result["claims"]


def test_analyzer_classifies_superpowers_as_skill():
    with open("data/superpowers_repo.json") as fixture:
        state = json.load(fixture)

    result = analyzer(state)

    assert result["agent_type"] == "SKILL"
    assert result["relevance_score"] >= 0.5
    assert len(result["claims"]) >= 3
    assert all(claim["claim_text"] != "Superpowers" for claim in result["claims"])


def test_analyzer_prefers_skill_path_over_readme_keywords():
    state = {
        "status": "COLLECTED",
        "readme": (
            "This project provides an MCP server with tools, resources, prompts, "
            "stdio support, SSE support, and a server.py entrypoint."
        ),
        "file_tree": [{"path": "skills/code-review/SKILL.md"}],
        "claims": [],
    }

    result = analyzer(state)

    assert result["agent_type"] == "SKILL"
    assert result["relevance_score"] >= 0.5


def test_evidence_scout_finds_paths():
    state = {
        "agent_type": "MCP_SERVER",
        "claims": [{"id": "claim-1"}],
        "file_tree": [{"path": "src/weather_mcp/server.py"}, {"path": "docs/index.md"}],
        "evidence_signals": [],
        "quality_warnings": [],
    }
    result = evidence_scout(state)
    assert result["evidence_signals"]
    assert result["evidence_signals"][0]["path"] == "src/weather_mcp/server.py"



def test_evidence_scout_links_superpowers_evidence_to_multiple_claims():
    with open("data/superpowers_repo.json") as fixture:
        state = json.load(fixture)

    analyzed = analyzer(state)
    result = evidence_scout({**state, **analyzed})

    evidence_signals = result["evidence_signals"]
    claim_ids = {signal["claim_id"] for signal in evidence_signals}
    paths = [signal["path"] for signal in evidence_signals]

    assert len(claim_ids) > 1
    assert any(path.startswith("skills/") for path in paths)
    assert any("plugin" in path for path in paths)



def test_superpowers_followup_actions_are_user_action_labels():
    with open("data/superpowers_repo.json") as fixture:
        state = json.load(fixture)

    analyzed = analyzer(state)
    scouted = evidence_scout({**state, **analyzed})
    result = risk_and_followup_planner({**state, **analyzed, **scouted})

    actions = {item["action"] for item in result["followup_actions"]}
    try_example = next(
        item for item in result["followup_actions"] if item["action"] == "TRY_EXAMPLE"
    )
    risk_types = {item["risk_type"] for item in result["risk_signals"]}

    assert "READ_NOW" in actions
    assert "INSPECT_STRUCTURE" in actions
    assert any(
        path in try_example["target_paths"]
        for path in ("scripts/install.js", "package.json")
    )
    assert "ANALYSIS_UNCERTAIN" in risk_types

def test_quality_gate_blocks_completed_without_evidence_for_claims():
    state = {
        "status": "COLLECTED",
        "agent_type": "SKILL",
        "claims": [
            {
                "id": "claim-1",
                "claim_text": "Provides a reusable skill workflow.",
                "source": "README.md",
            }
        ],
        "evidence_signals": [],
        "risk_signals": [],
        "followup_actions": [],
    }

    result = quality_gate(state)

    assert result["status"] == "NEEDS_HUMAN_REVIEW"
    assert result["quality_errors"]

def test_quality_gate_warns_uncertain_with_unlinked_claim_evidence():
    state = {
        "status": "COLLECTED",
        "agent_type": "SKILL",
        "claims": [
            {
                "id": "claim-1",
                "claim_text": "Provides a reusable skill workflow.",
                "source": "README.md",
            },
            {
                "id": "claim-2",
                "claim_text": "Provides verification workflow instructions.",
                "source": "README.md",
            },
        ],
        "evidence_signals": [
            {
                "claim_id": "claim-1",
                "path": "skills/using-superpowers/SKILL.md",
            }
        ],
        "risk_signals": [
            {
                "risk_type": "ANALYSIS_UNCERTAIN",
                "summary": "Static analysis leaves uncertainty.",
            }
        ],
        "followup_actions": [
            {
                "action": "READ_NOW",
                "reason": "Read source evidence.",
                "target_paths": ["README.md"],
            }
        ],
    }

    result = quality_gate(state)

    assert result["status"] == "UNCERTAIN"
    assert result["quality_warnings"]
    assert any("claim-2" in warning for warning in result["quality_warnings"])
    assert "quality_errors" not in result

