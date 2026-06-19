import json
from pathlib import Path

from agenttrace.agents.analysis.nodes.analyzer import analyzer
from agenttrace.agents.analysis.nodes.collect_snapshot import collect_snapshot
from agenttrace.agents.analysis.nodes.evidence_scout import evidence_scout
from agenttrace.agents.analysis.nodes.quality_gate import quality_gate
from agenttrace.agents.analysis.nodes.risk_and_followup import risk_and_followup_planner


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
    path = Path(__file__).parent.parent / "data" / "superpowers_repo.json"
    with open(path) as fixture:
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
    path = Path(__file__).parent.parent / "data" / "superpowers_repo.json"
    with open(path) as fixture:
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
    path = Path(__file__).parent.parent / "data" / "superpowers_repo.json"
    with open(path) as fixture:
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


def test_collect_snapshot_no_commit_sha():
    state = {
        "repository_snapshot": {
            "full_name": "acme/harness",
            "readme": "Some readme",
            "file_tree": [{"path": "README.md"}],
        }
    }
    result = collect_snapshot(state)
    assert "commit_sha" not in result
    assert "ingest_api_url" not in result
    assert "quality_warnings" not in result


def test_collect_snapshot_with_commit_sha_in_state():
    state = {
        "commit_sha": "abcdef123456",
        "repository_snapshot": {
            "full_name": "acme/harness",
            "readme": "Some readme",
            "file_tree": [{"path": "README.md"}],
        }
    }
    result = collect_snapshot(state)
    assert result["commit_sha"] == "abcdef123456"
    assert result["ingest_api_url"] == "https://gitingest.com/api/acme/harness/commit/abcdef123456"
    assert "스냅샷 생성 시점의 commit_sha와 실시간 분석 코드가 일치하지 않을 수 있습니다." in result["quality_warnings"]


def test_collect_snapshot_with_commit_sha_in_snapshot():
    state = {
        "repository_snapshot": {
            "commit_sha": "7890abcdef",
            "full_name": "acme/harness",
            "readme": "Some readme",
            "file_tree": [{"path": "README.md"}],
        }
    }
    result = collect_snapshot(state)
    assert result["commit_sha"] == "7890abcdef"
    assert result["ingest_api_url"] == "https://gitingest.com/api/acme/harness/commit/7890abcdef"
    assert "스냅샷 생성 시점의 commit_sha와 실시간 분석 코드가 일치하지 않을 수 있습니다." in result["quality_warnings"]


def test_collect_snapshot_with_commit_sha_in_metadata():
    state = {
        "repository_snapshot": {
            "metadata": {"commit_sha": "1234567890"},
            "full_name": "acme/harness",
            "readme": "Some readme",
            "file_tree": [{"path": "README.md"}],
        }
    }
    result = collect_snapshot(state)
    assert result["commit_sha"] == "1234567890"
    assert result["ingest_api_url"] == "https://gitingest.com/api/acme/harness/commit/1234567890"
    assert "스냅샷 생성 시점의 commit_sha와 실시간 분석 코드가 일치하지 않을 수 있습니다." in result["quality_warnings"]


def test_collect_snapshot_github_url_fallback():
    state = {
        "commit_sha": "abcdef123456",
        "repository_snapshot": {
            "github_url": "https://github.com/example-owner/example-repo.git",
            "readme": "Some readme",
            "file_tree": [{"path": "README.md"}],
        }
    }
    result = collect_snapshot(state)
    assert result["commit_sha"] == "abcdef123456"
    assert result["ingest_api_url"] == "https://gitingest.com/api/example-owner/example-repo/commit/abcdef123456"
    assert "스냅샷 생성 시점의 commit_sha와 실시간 분석 코드가 일치하지 않을 수 있습니다." in result["quality_warnings"]


