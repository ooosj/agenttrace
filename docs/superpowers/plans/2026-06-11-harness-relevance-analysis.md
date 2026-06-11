# Harness Relevance Analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add evidence-based harness relevance analysis to AgentTrace without replacing the existing Summary Agent or LangGraph analysis workflow.

**Architecture:** Keep Summary Agent as a low-cost README/metadata hint generator and add canonical harness analysis to the existing Analysis Agent path. Use deterministic capability criteria first, then expose the result through analysis state and persisted JSON.

**Tech Stack:** Python 3.10+, Pydantic v2, LangChain structured output, LangGraph, pytest.

---

## File Structure

- Modify: `src/agenttrace/agents/summary/schemas.py`
  - Add summary-level `possible_harness_relevance`.
- Modify: `src/agenttrace/agents/summary/prompt.md`
  - Tell the Summary Agent how to produce a lightweight harness relevance hint without claiming implementation validation.
- Modify: `src/agenttrace/agents/summary/service.py`
  - Ensure insufficient-context fallback and input guards populate the new summary field.
- Modify: `tests/test_summary_service.py`
  - Cover schema defaults, prompt wording, and fallback behavior.
- Create: `src/agenttrace/agents/analysis/schemas/harness.py`
  - Define Pydantic models and constants for harness relevance output.
- Create: `src/agenttrace/agents/analysis/criteria/harness_capabilities.py`
  - Store deterministic capability criteria and relevance scoring thresholds.
- Create: `src/agenttrace/agents/analysis/nodes/harness_analyzer.py`
  - Convert README/file/source/test/config evidence into `harness_relevance`, `harness_capabilities`, `negative_evidence`, and `followup_questions`.
- Modify: `src/agenttrace/agents/analysis/state.py`
  - Add harness fields to `AnalysisState`.
- Modify: `src/agenttrace/agents/analysis/graph.py`
  - Insert `harness_analyzer` after `evidence_scout`.
- Modify: `src/agenttrace/agents/analysis/nodes/persist_analysis.py`
  - Include harness fields in persisted analysis JSON.
- Create: `data/fixtures/high_harness_repo.json`
- Create: `data/fixtures/medium_skill_or_mcp_repo.json`
- Create: `data/fixtures/low_readme_only_agent_repo.json`
- Create: `tests/test_harness_analysis.py`
  - Cover high, medium, and low/none relevance.

Do not run arbitrary analyzed repository code, lint, dependency install, or tests as part of this feature. Treat file paths, README text, selected source snippets, configs, tests, examples, and docs as static evidence.

---

### Task 1: Summary Harness Hint Schema

**Files:**
- Modify: `src/agenttrace/agents/summary/schemas.py`
- Modify: `src/agenttrace/agents/summary/service.py`
- Modify: `src/agenttrace/agents/summary/prompt.md`
- Test: `tests/test_summary_service.py`

- [ ] **Step 1: Write failing summary schema/fallback tests**

Append these tests to `tests/test_summary_service.py`:

```python
def test_repository_summary_includes_possible_harness_relevance_hint():
    summary_input = RepositorySummaryInput(
        repository_id="repo-1",
        full_name="acme/harness",
        github_url="https://github.com/acme/harness",
    )

    result = summarize_repository(summary_input)

    assert result.possible_harness_relevance.level == AgentRelevanceLevel.UNKNOWN
    assert result.possible_harness_relevance.confidence == ConfidenceLevel.UNKNOWN
    assert "[확인 필요]" in result.possible_harness_relevance.reason


def test_summary_prompt_mentions_harness_relevance_rules():
    prompt = load_summary_prompt()

    assert "possible harness relevance" in prompt.lower()
    assert "README claims alone must not produce high confidence" in prompt
    assert "Do not claim source-code confirmation" in prompt
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run:

```bash
pytest tests/test_summary_service.py::test_repository_summary_includes_possible_harness_relevance_hint tests/test_summary_service.py::test_summary_prompt_mentions_harness_relevance_rules -v
```

Expected: FAIL because `RepositorySummary` has no `possible_harness_relevance` field and the prompt does not mention harness relevance rules.

- [ ] **Step 3: Add the summary schema field**

In `src/agenttrace/agents/summary/schemas.py`, add this model near `AgentRelevanceHint`:

```python
class HarnessRelevanceHint(BaseModel):
    level: AgentRelevanceLevel = AgentRelevanceLevel.UNKNOWN
    reason: str = "[확인 필요] Harness relevance was not analyzed."
    confidence: ConfidenceLevel = ConfidenceLevel.UNKNOWN
```

Then add this field to `RepositorySummary`:

```python
possible_harness_relevance: HarnessRelevanceHint = Field(
    default_factory=HarnessRelevanceHint
)
```

Update `src/agenttrace/agents/summary/__init__.py` exports if it explicitly lists summary schemas.

- [ ] **Step 4: Populate fallback output**

In `src/agenttrace/agents/summary/service.py`, import `HarnessRelevanceHint` from the summary schemas module and add this argument to the insufficient-context `RepositorySummary(...)` construction:

```python
possible_harness_relevance=HarnessRelevanceHint(
    level=AgentRelevanceLevel.UNKNOWN,
    reason="[확인 필요] README and file tree were not available for a harness relevance hint.",
    confidence=ConfidenceLevel.UNKNOWN,
),
```

Do not add source-code validation logic to the Summary Agent.

- [ ] **Step 5: Update the summary prompt**

In `src/agenttrace/agents/summary/prompt.md`, add `possible harness relevance hint` to the structured output list. Add these rules under `Rules:`:

```markdown
- Provide possible harness relevance only as a lightweight README/metadata/file-tree hint.
- README claims alone must not produce high confidence harness relevance.
- Do not claim source-code confirmation, runtime validation, sandbox validation, or permission validation.
- If harness relevance is unclear, include `[확인 필요]` in the reason.
```

- [ ] **Step 6: Run focused summary tests**

Run:

```bash
pytest tests/test_summary_service.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/agenttrace/agents/summary/schemas.py src/agenttrace/agents/summary/service.py src/agenttrace/agents/summary/prompt.md src/agenttrace/agents/summary/__init__.py tests/test_summary_service.py
git commit -m "feat: add summary harness relevance hint"
```

---

### Task 2: Harness Criteria And Analyzer

**Files:**
- Create: `src/agenttrace/agents/analysis/schemas/harness.py`
- Create: `src/agenttrace/agents/analysis/criteria/harness_capabilities.py`
- Create: `src/agenttrace/agents/analysis/nodes/harness_analyzer.py`
- Create: `tests/test_harness_analysis.py`

- [ ] **Step 1: Write failing unit tests for deterministic harness analysis**

Create `tests/test_harness_analysis.py` with:

```python
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
                "content": "while step < max_iterations:\\n    next_action = planner.run_step(state)\\n    invoke_tool(next_action)",
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
```

- [ ] **Step 2: Run tests and verify import failure**

Run:

```bash
pytest tests/test_harness_analysis.py -v
```

Expected: FAIL because `agenttrace.agents.analysis.nodes.harness_analyzer` does not exist.

- [ ] **Step 3: Add harness schemas**

Create `src/agenttrace/agents/analysis/schemas/harness.py`:

```python
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


HarnessCapabilityName = Literal[
    "agent_loop",
    "tool_system",
    "permission_control",
    "sandbox_or_workspace",
    "file_system_abstraction",
    "memory_or_context_management",
    "context_compression",
    "skill_system",
    "sub_agent",
    "planning",
    "execution_monitoring",
    "error_recovery",
    "human_in_the_loop",
    "observability",
    "evaluation",
    "security_boundary",
]


class HarnessEvidence(BaseModel):
    type: Literal["readme", "file_path", "source_code", "config", "test", "docs"]
    location: str
    summary: str
    supports: list[HarnessCapabilityName] = Field(default_factory=list)


class HarnessNegativeEvidence(BaseModel):
    type: Literal["file_path", "source_code", "docs", "test"]
    location: str = ""
    summary: str


class HarnessCapability(BaseModel):
    present: bool = False
    confidence: Literal["high", "medium", "low"] = "low"
    evidence: list[str] = Field(default_factory=list)


class HarnessRelevance(BaseModel):
    level: Literal["high", "medium", "low", "none"] = "none"
    reason: str
    confidence: Literal["high", "medium", "low"] = "low"
    evidence: list[HarnessEvidence] = Field(default_factory=list)
    negative_evidence: list[HarnessNegativeEvidence] = Field(default_factory=list)
```

- [ ] **Step 4: Add capability criteria**

Create `src/agenttrace/agents/analysis/criteria/harness_capabilities.py`:

```python
HARNESS_CAPABILITY_NAMES = [
    "agent_loop",
    "tool_system",
    "permission_control",
    "sandbox_or_workspace",
    "file_system_abstraction",
    "memory_or_context_management",
    "context_compression",
    "skill_system",
    "sub_agent",
    "planning",
    "execution_monitoring",
    "error_recovery",
    "human_in_the_loop",
    "observability",
    "evaluation",
    "security_boundary",
]


HARNESS_CAPABILITY_CRITERIA = {
    "agent_loop": {
        "path_keywords": ["agent_loop", "executor", "runner", "orchestrator", "workflow", "graph"],
        "code_keywords": ["max_iterations", "next_action", "run_step", "invoke_tool"],
    },
    "tool_system": {
        "path_keywords": ["tools", "tool_registry", "function_schema", "tool_call", "mcp"],
        "code_keywords": ["register_tool", "tool_call", "function_call", "invoke_tool"],
    },
    "permission_control": {
        "path_keywords": ["permission", "policy", "approval", "allowlist", "denylist"],
        "code_keywords": ["require_approval", "allowed_commands", "policy_check"],
    },
    "sandbox_or_workspace": {
        "path_keywords": ["sandbox", "workspace", "worktree", "container"],
        "code_keywords": ["sandbox", "workspace", "cwd", "container"],
    },
    "file_system_abstraction": {
        "path_keywords": ["filesystem", "file_system", "workspace", "files"],
        "code_keywords": ["read_file", "write_file", "list_files"],
    },
    "memory_or_context_management": {
        "path_keywords": ["memory", "context", "checkpoint", "state"],
        "code_keywords": ["conversation_memory", "context_window", "checkpoint"],
    },
    "context_compression": {
        "path_keywords": ["compress", "compression", "summarize_context"],
        "code_keywords": ["compress_context", "summarize_context"],
    },
    "skill_system": {
        "path_keywords": ["skill", "SKILL.md", "skills"],
        "code_keywords": ["load_skill", "skill"],
    },
    "sub_agent": {
        "path_keywords": ["subagent", "sub_agent", "multi_agent", "worker"],
        "code_keywords": ["spawn_agent", "delegate", "subagent"],
    },
    "planning": {
        "path_keywords": ["planner", "planning", "plan"],
        "code_keywords": ["create_plan", "planner", "steps"],
    },
    "execution_monitoring": {
        "path_keywords": ["monitor", "run_log", "execution", "trace"],
        "code_keywords": ["status", "run_id", "trace", "span"],
    },
    "error_recovery": {
        "path_keywords": ["retry", "recovery", "fallback", "error"],
        "code_keywords": ["retry", "except", "fallback"],
    },
    "human_in_the_loop": {
        "path_keywords": ["approval", "review", "human", "interrupt"],
        "code_keywords": ["interrupt", "approve", "human_review"],
    },
    "observability": {
        "path_keywords": ["trace", "tracing", "observability", "langsmith", "logs"],
        "code_keywords": ["trace", "span", "logger", "langsmith"],
    },
    "evaluation": {
        "path_keywords": ["eval", "evaluation", "benchmark", "score", "tests"],
        "code_keywords": ["score", "benchmark", "assert"],
    },
    "security_boundary": {
        "path_keywords": ["security", "policy", "sandbox", "permission", "guardrail"],
        "code_keywords": ["validate_policy", "deny", "allowlist", "sandbox"],
    },
}


CORE_HIGH_RELEVANCE_CAPABILITIES = {
    "agent_loop",
    "tool_system",
    "sandbox_or_workspace",
    "permission_control",
}
```

- [ ] **Step 5: Implement harness analyzer**

Create `src/agenttrace/agents/analysis/nodes/harness_analyzer.py`:

```python
from __future__ import annotations

from agenttrace.agents.analysis.criteria.harness_capabilities import (
    CORE_HIGH_RELEVANCE_CAPABILITIES,
    HARNESS_CAPABILITY_CRITERIA,
    HARNESS_CAPABILITY_NAMES,
)
from agenttrace.agents.analysis.state import AnalysisState


def _path_text(state: AnalysisState) -> list[str]:
    paths: list[str] = []
    for item in state.get("file_tree", []):
        path = item.get("path") if isinstance(item, dict) else None
        if path:
            paths.append(path)
    for item in state.get("evidence_signals", []):
        path = item.get("path") if isinstance(item, dict) else None
        if path:
            paths.append(path)
    return paths


def _selected_source_text(state: AnalysisState) -> list[tuple[str, str]]:
    selected: list[tuple[str, str]] = []
    for item in state.get("selected_files", []):
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "")
        content = str(item.get("content") or item.get("text") or "")
        if path or content:
            selected.append((path, content))
    return selected


def _evidence_type(path: str) -> str:
    lowered = path.lower()
    if "test" in lowered:
        return "test"
    if lowered.endswith((".json", ".toml", ".yaml", ".yml")):
        return "config"
    if lowered.endswith((".md", ".mdx", ".rst")):
        return "docs"
    return "file_path"


def _confidence_for(path_hits: int, code_hits: int) -> str:
    if code_hits > 0 and path_hits > 0:
        return "high"
    if path_hits > 0:
        return "medium"
    return "low"


def _level_for(present_capabilities: set[str], readme_mentions_harness: bool) -> tuple[str, str]:
    core_hits = present_capabilities & CORE_HIGH_RELEVANCE_CAPABILITIES
    if {"agent_loop", "tool_system"} <= present_capabilities and len(core_hits) >= 3:
        return "high", "high"
    if "tool_system" in present_capabilities or "skill_system" in present_capabilities:
        return "medium", "medium"
    if present_capabilities or readme_mentions_harness:
        return "low", "low"
    return "none", "medium"


def harness_analyzer(state: AnalysisState) -> AnalysisState:
    paths = _path_text(state)
    sources = _selected_source_text(state)
    readme = state.get("readme", "")
    readme_lower = readme.lower()
    readme_mentions_harness = any(
        word in readme_lower
        for word in ["agent", "harness", "tool", "sandbox", "permission", "skill", "mcp"]
    )

    capabilities: dict[str, dict] = {}
    evidence: list[dict] = []
    present_capabilities: set[str] = set()

    for name in HARNESS_CAPABILITY_NAMES:
        criteria = HARNESS_CAPABILITY_CRITERIA[name]
        path_hits = [
            path
            for path in paths
            if any(keyword.lower() in path.lower() for keyword in criteria["path_keywords"])
        ]
        code_hits = [
            path
            for path, content in sources
            if any(keyword.lower() in content.lower() for keyword in criteria["code_keywords"])
        ]
        present = bool(path_hits or code_hits)
        if present:
            present_capabilities.add(name)

        capability_evidence = []
        for path in path_hits[:3]:
            summary = f"Static path signal supports {name}: {path}"
            evidence.append(
                {
                    "type": _evidence_type(path),
                    "location": path,
                    "summary": summary,
                    "supports": [name],
                }
            )
            capability_evidence.append(summary)
        for path in code_hits[:2]:
            location = path or "selected_files"
            summary = f"Selected source snippet contains code signal for {name}: {location}"
            evidence.append(
                {
                    "type": "source_code",
                    "location": location,
                    "summary": summary,
                    "supports": [name],
                }
            )
            capability_evidence.append(summary)

        capabilities[name] = {
            "present": present,
            "confidence": _confidence_for(len(path_hits), len(code_hits)),
            "evidence": capability_evidence,
        }

    level, confidence = _level_for(present_capabilities, readme_mentions_harness)
    negative_evidence = []
    if readme_mentions_harness and not present_capabilities:
        negative_evidence.append(
            {
                "type": "file_path",
                "location": "file_tree",
                "summary": "README suggests agent or harness relevance, but available file structure does not show harness capability signals.",
            }
        )
    if "agent_loop" not in present_capabilities:
        negative_evidence.append(
            {
                "type": "file_path",
                "location": "file_tree",
                "summary": "No agent loop, executor, runner, workflow, or graph structure was found in available paths.",
            }
        )

    followup_questions = []
    if "agent_loop" not in present_capabilities:
        followup_questions.append("Does the repository include an executor or agent loop outside the captured file tree?")
    if "permission_control" not in present_capabilities:
        followup_questions.append("Does the repository enforce tool permissions, approvals, or command policies?")
    if "sandbox_or_workspace" not in present_capabilities:
        followup_questions.append("Does the repository isolate agent actions in a sandbox, workspace, container, or worktree?")

    reason = (
        f"Harness relevance is {level} based on {len(present_capabilities)} detected capability signals."
    )
    if readme_mentions_harness and not evidence:
        reason += " [확인 필요] README language was not supported by available static evidence."

    harness_relevance = {
        "level": level,
        "reason": reason,
        "confidence": confidence,
        "evidence": evidence,
        "negative_evidence": negative_evidence,
    }

    return {
        "harness_relevance": harness_relevance,
        "harness_capabilities": capabilities,
        "negative_evidence": negative_evidence,
        "followup_questions": followup_questions,
    }
```

- [ ] **Step 6: Run focused harness tests**

Run:

```bash
pytest tests/test_harness_analysis.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/agenttrace/agents/analysis/schemas/harness.py src/agenttrace/agents/analysis/criteria/harness_capabilities.py src/agenttrace/agents/analysis/nodes/harness_analyzer.py tests/test_harness_analysis.py
git commit -m "feat: add deterministic harness analyzer"
```

---

### Task 3: Wire Harness Analysis Into LangGraph Output

**Files:**
- Modify: `src/agenttrace/agents/analysis/state.py`
- Modify: `src/agenttrace/agents/analysis/graph.py`
- Modify: `src/agenttrace/agents/analysis/nodes/persist_analysis.py`
- Modify: `tests/test_nodes.py`
- Test: `tests/test_harness_analysis.py`

- [ ] **Step 1: Write failing graph/persist integration test**

Append to `tests/test_harness_analysis.py`:

```python
from agenttrace.agents.analysis.graph import build_graph


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
```

- [ ] **Step 2: Run the integration test and verify it fails**

Run:

```bash
pytest tests/test_harness_analysis.py::test_analysis_graph_persists_harness_fields -v
```

Expected: FAIL because the graph does not call `harness_analyzer` and persisted analysis does not include harness fields.

- [ ] **Step 3: Extend analysis state**

In `src/agenttrace/agents/analysis/state.py`, add these fields to `AnalysisState`:

```python
harness_relevance: dict
harness_capabilities: dict
negative_evidence: Annotated[list[dict], operator.add]
followup_questions: list[str]
```

If `negative_evidence` list merging causes duplicate entries in graph execution, remove `operator.add` and use a plain `list[dict]`.

- [ ] **Step 4: Wire graph node**

In `src/agenttrace/agents/analysis/graph.py`, import the node:

```python
from agenttrace.agents.analysis.nodes.harness_analyzer import harness_analyzer
```

Add the node:

```python
builder.add_node("harness_analyzer", harness_analyzer)
```

Change the existing edge from:

```python
builder.add_edge("evidence_scout", "risk_and_followup_planner")
```

to:

```python
builder.add_edge("evidence_scout", "harness_analyzer")
builder.add_edge("harness_analyzer", "risk_and_followup_planner")
```

- [ ] **Step 5: Persist harness fields**

In `src/agenttrace/agents/analysis/nodes/persist_analysis.py`, add these keys to `_public_analysis`:

```python
"harness_relevance": state.get("harness_relevance", {}),
"harness_capabilities": state.get("harness_capabilities", {}),
"negative_evidence": state.get("negative_evidence", []),
"followup_questions": state.get("followup_questions", []),
```

- [ ] **Step 6: Run focused graph tests**

Run:

```bash
pytest tests/test_harness_analysis.py tests/test_nodes.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/agenttrace/agents/analysis/state.py src/agenttrace/agents/analysis/graph.py src/agenttrace/agents/analysis/nodes/persist_analysis.py tests/test_harness_analysis.py tests/test_nodes.py
git commit -m "feat: persist harness analysis output"
```

---

### Task 4: Fixture Coverage

**Files:**
- Create: `data/fixtures/high_harness_repo.json`
- Create: `data/fixtures/medium_skill_or_mcp_repo.json`
- Create: `data/fixtures/low_readme_only_agent_repo.json`
- Modify: `tests/test_harness_analysis.py`

- [ ] **Step 1: Create fixture directory and high relevance fixture**

Create `data/fixtures/high_harness_repo.json`:

```json
{
  "repository_id": "fixture-high-harness",
  "full_name": "acme/coding-agent-harness",
  "github_url": "https://github.com/acme/coding-agent-harness",
  "metadata": {
    "description": "Coding agent harness with tools, sandbox, permission policies, and memory."
  },
  "readme": "Coding Agent Harness provides an agent loop, tool registry, sandboxed workspace, permissions, and memory for autonomous coding tasks.",
  "file_tree": [
    {"path": "README.md", "type": "file"},
    {"path": "src/agent_loop.py", "type": "file"},
    {"path": "src/tools/registry.py", "type": "file"},
    {"path": "src/workspace/sandbox.py", "type": "file"},
    {"path": "src/permissions/policy.py", "type": "file"},
    {"path": "src/memory/context.py", "type": "file"},
    {"path": "tests/test_tool_execution.py", "type": "file"}
  ],
  "selected_files": [
    {
      "path": "src/agent_loop.py",
      "content": "while step < max_iterations:\\n    next_action = planner.run_step(state)\\n    invoke_tool(next_action)"
    }
  ]
}
```

- [ ] **Step 2: Create medium relevance fixture**

Create `data/fixtures/medium_skill_or_mcp_repo.json`:

```json
{
  "repository_id": "fixture-medium-mcp-skill",
  "full_name": "acme/weather-mcp-skills",
  "github_url": "https://github.com/acme/weather-mcp-skills",
  "metadata": {
    "description": "MCP server and reusable skill pack for weather tools."
  },
  "readme": "This repository ships an MCP server and reusable agent skills for weather lookup.",
  "file_tree": [
    {"path": "README.md", "type": "file"},
    {"path": "server.py", "type": "file"},
    {"path": "tools/weather.py", "type": "file"},
    {"path": "skills/weather/SKILL.md", "type": "file"},
    {"path": "mcp.json", "type": "file"}
  ],
  "selected_files": []
}
```

- [ ] **Step 3: Create low relevance fixture**

Create `data/fixtures/low_readme_only_agent_repo.json`:

```json
{
  "repository_id": "fixture-low-readme-only",
  "full_name": "acme/agent-marketing-site",
  "github_url": "https://github.com/acme/agent-marketing-site",
  "metadata": {
    "description": "Marketing site that mentions AI agents."
  },
  "readme": "This AI agent platform helps teams think about autonomous work.",
  "file_tree": [
    {"path": "README.md", "type": "file"},
    {"path": "docs/overview.md", "type": "file"},
    {"path": "web/app.py", "type": "file"}
  ],
  "selected_files": []
}
```

- [ ] **Step 4: Add fixture-driven tests**

Append to `tests/test_harness_analysis.py`:

```python
import json
from pathlib import Path


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "data" / "fixtures"


def _load_fixture(name: str) -> dict:
    with (FIXTURE_DIR / name).open() as fixture:
        return json.load(fixture)


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
```

- [ ] **Step 5: Run fixture tests**

Run:

```bash
pytest tests/test_harness_analysis.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add data/fixtures/high_harness_repo.json data/fixtures/medium_skill_or_mcp_repo.json data/fixtures/low_readme_only_agent_repo.json tests/test_harness_analysis.py
git commit -m "test: add harness relevance fixtures"
```

---

### Task 5: Quality Gate And Full Verification

**Files:**
- Modify: `src/agenttrace/agents/analysis/nodes/quality_gate.py`
- Modify: `tests/test_harness_analysis.py`
- Modify: `tests/test_nodes.py`

- [ ] **Step 1: Write failing quality gate test for overconfident harness result**

Append to `tests/test_harness_analysis.py`:

```python
from agenttrace.agents.analysis.nodes.quality_gate import quality_gate


def test_quality_gate_warns_when_high_harness_relevance_has_no_evidence():
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
```

- [ ] **Step 2: Run the quality gate test and verify it fails**

Run:

```bash
pytest tests/test_harness_analysis.py::test_quality_gate_warns_when_high_harness_relevance_has_no_evidence -v
```

Expected: FAIL because `quality_gate` does not validate harness relevance evidence yet.

- [ ] **Step 3: Add quality gate check**

In `src/agenttrace/agents/analysis/nodes/quality_gate.py`, after existing evidence checks, add:

```python
harness_relevance = state.get("harness_relevance", {})
if (
    harness_relevance.get("level") == "high"
    and not harness_relevance.get("evidence")
):
    errors.append("harness_relevance cannot be high without harness evidence.")
```

If `quality_gate` currently stores errors in `quality_errors`, use the same local `errors` list already used by the node.

- [ ] **Step 4: Run focused tests**

Run:

```bash
pytest tests/test_harness_analysis.py tests/test_nodes.py -v
```

Expected: PASS.

- [ ] **Step 5: Run all tests**

Run:

```bash
pytest -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/agenttrace/agents/analysis/nodes/quality_gate.py tests/test_harness_analysis.py tests/test_nodes.py
git commit -m "test: guard harness relevance quality"
```

---

## Final Verification

Run:

```bash
pytest -v
```

Expected: all tests pass.

Then inspect the final diff:

```bash
git status --short
git log --oneline -5
```

Expected:

- Only intended harness analysis files are changed.
- Recent commits include the harness summary hint, deterministic harness analyzer, graph output wiring, fixtures, and quality gate guard.

## Plan Self-Review

Spec coverage:

- Summary Agent remains lightweight and gets only `possible_harness_relevance`.
- Deep Analysis Agent owns canonical `harness_relevance`, `harness_capabilities`, evidence, negative evidence, and follow-up questions.
- README-only high relevance is prevented by analyzer logic and quality gate.
- Fixture coverage includes high, medium, and low/none relevance.
- LangChain remains limited to summary structured output.
- LangGraph is reused without a large workflow rewrite.

Placeholder scan:

- The plan contains no placeholder implementation steps.
- Each code change step includes concrete file paths, code blocks, commands, and expected results.

Type consistency:

- Summary uses existing `AgentRelevanceLevel` and `ConfidenceLevel`.
- Analysis harness fields use dict-based `AnalysisState` additions to match the current node style.
- `harness_analyzer` returns partial `AnalysisState`, matching existing LangGraph node conventions.
