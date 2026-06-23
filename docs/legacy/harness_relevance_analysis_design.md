# Harness Relevance Analysis Design

## 1. Current Codebase Structure

AgentTrace currently has two separate analysis surfaces:

- `src/agenttrace/agents/summary`: README, metadata, topics, primary language, and shallow file tree based repository summary.
- `src/agenttrace/agents/analysis`: LangGraph based static analysis prototype for repository snapshots.
- `src/agenttrace/services`: GitHub repository digest ingestion and conversion to summary input.
- `src/agenttrace/app/routers`: FastAPI endpoints, currently focused on summary generation.
- `tests`: unit tests for summary service, summary API, repo ingest, package structure, and analysis nodes.
- `data`: sample repository snapshot fixtures.

The Summary Agent consists of:

- `src/agenttrace/agents/summary/schemas.py`
- `src/agenttrace/agents/summary/service.py`
- `src/agenttrace/agents/summary/prompt.md`

The Analysis Agent consists of:

- `src/agenttrace/agents/analysis/graph.py`
- `src/agenttrace/agents/analysis/state.py`
- `src/agenttrace/agents/analysis/nodes/analyzer.py`
- `src/agenttrace/agents/analysis/nodes/evidence_scout.py`
- `src/agenttrace/agents/analysis/nodes/risk_and_followup.py`
- `src/agenttrace/agents/analysis/nodes/quality_gate.py`
- `src/agenttrace/agents/analysis/nodes/persist_analysis.py`
- `src/agenttrace/agents/analysis/criteria/agent_type_keywords.py`

The current output already separates README claims from implementation evidence at a coarse level:

- Summary output includes `readme_claims`, `readme_described_features`, `possible_agent_relevance`, `followup_hints`, `summary_basis`, `input_gaps`, `summary_limitations`, `confidence`, and `summary_status`.
- Analysis output includes `agent_type`, `relevance_score`, `classification_reason`, `claims`, `evidence_signals`, `risk_signals`, `followup_actions`, `followup_guide`, and quality gate warnings/errors.

Harness-specific fields do not currently exist. There is no canonical `harness_relevance`, `harness_capabilities`, capability-level evidence map, negative evidence list, or dedicated `followup_questions` list.

## 2. Summary Agent And Analysis Agent Responsibility

The Summary Agent should remain a low-cost first pass. It should use only README, metadata, topics, primary language, and shallow file tree. It should not inspect source code, assert confirmed runtime behavior, or make final harness classification claims.

Recommended Summary Agent output addition:

- `possible_harness_relevance`

This should be a lightweight hint, not the canonical judgment. If evidence is weak, the reason should include `[확인 필요]`.

The Deep Analysis Agent should own the canonical harness result. It should inspect file paths, selected source snippets when available, config files, tests, docs, and examples. It should create capability-level evidence, negative evidence, and follow-up questions.

The current Analysis Agent has a useful MVP graph:

```text
collect_snapshot -> analyzer -> evidence_scout -> risk_and_followup_planner -> quality_gate -> persist_analysis
```

The main responsibility issue is that `analyzer` currently combines relevance/type classification and README claim extraction. That is acceptable for the current MVP, but harness analysis should be added as a small separate stage or post-processing layer rather than expanding `analyzer` further.

## 3. Current Gaps

- No harness-specific schema.
- No capability matrix for agent harness engineering.
- No capability-level link from evidence to fields such as `agent_loop`, `tool_system`, or `sandbox_or_workspace`.
- README-only claims are not explicitly prevented from producing high harness relevance.
- Negative evidence is not modeled.
- `followup_actions` exist, but there is no simple `followup_questions` list for unresolved analysis questions.
- Source-code evidence is limited by what is available in `selected_files`.
- `schemas/claim.py`, `schemas/evidence.py`, `schemas/followup.py`, `schemas/quality.py`, and `schemas/risk.py` are currently placeholders for future strict structured output.

## 4. Recommended Schema

Use additive schema changes so existing summary and analysis flows remain stable.

Summary schema:

```json
{
  "possible_harness_relevance": {
    "level": "high | medium | low | none | unknown",
    "reason": "string",
    "confidence": "high | medium | low | unknown"
  }
}
```

Deep analysis schema:

```json
{
  "harness_relevance": {
    "level": "high | medium | low | none",
    "reason": "string",
    "confidence": "high | medium | low",
    "evidence": [
      {
        "type": "readme | file_path | source_code | config | test | docs",
        "location": "string",
        "summary": "string",
        "supports": ["agent_loop", "tool_system"]
      }
    ],
    "negative_evidence": [
      {
        "type": "file_path | source_code | docs | test",
        "location": "string",
        "summary": "string"
      }
    ]
  },
  "harness_capabilities": {
    "agent_loop": {
      "present": true,
      "confidence": "high | medium | low",
      "evidence": ["string"]
    }
  },
  "followup_questions": ["string"]
}
```

The full capability set should include:

- `agent_loop`
- `tool_system`
- `permission_control`
- `sandbox_or_workspace`
- `file_system_abstraction`
- `memory_or_context_management`
- `context_compression`
- `skill_system`
- `sub_agent`
- `planning`
- `execution_monitoring`
- `error_recovery`
- `human_in_the_loop`
- `observability`
- `evaluation`
- `security_boundary`

Each capability should be represented as an object, not a bare boolean. The object should include `present`, `confidence`, and `evidence`.

## 5. Prompt Changes

Summary prompt changes:

- Add `possible_harness_relevance` to the requested structured output.
- State that README claims alone must not produce high confidence.
- State that the Summary Agent must not claim runtime validation or source-code confirmation.
- Require `[확인 필요]` when file tree or README is too thin.
- Keep existing limitations around implementation evidence.

Deep Analysis prompt or rule changes:

- Separate README claims from file/source/config/test evidence.
- Require concrete evidence before high harness relevance.
- Allow README evidence to support a hypothesis but not confirm a capability by itself.
- Generate negative evidence when README claims are not supported by file structure or selected source.
- Generate follow-up questions for missing source files, unclear executor boundaries, or unconfirmed sandbox/permission behavior.

## 6. Test Fixtures

### High Relevance Repo

Fixture path:

- `data/fixtures/high_harness_repo.json`

Suggested content:

- README describes a coding agent harness.
- File tree includes `src/agent_loop.py`, `src/tools/registry.py`, `src/workspace/sandbox.py`, `src/permissions/policy.py`, `src/memory/context.py`, and `tests/test_tool_execution.py`.

Expected output:

- `harness_relevance.level = "high"`
- `harness_relevance.confidence = "high"` or `"medium"`
- Present capabilities include `agent_loop`, `tool_system`, `permission_control`, `sandbox_or_workspace`, `memory_or_context_management`, and `execution_monitoring`.
- Evidence includes file path and test evidence.

### Medium Relevance Repo

Fixture path:

- `data/fixtures/medium_skill_or_mcp_repo.json`

Suggested content:

- README describes an MCP server or skill pack.
- File tree includes `server.py`, `tools/weather.py`, `skills/foo/SKILL.md`, and `mcp.json`.
- No clear full agent loop, sandbox, workspace, or permission boundary.

Expected output:

- `harness_relevance.level = "medium"`
- `tool_system` or `skill_system` is present.
- `agent_loop`, `sandbox_or_workspace`, and `permission_control` are absent or low confidence.
- Follow-up question asks whether an executor or agent loop exists outside the MCP/skill surface.

### Low Or None Relevance Repo

Fixture path:

- `data/fixtures/low_readme_only_agent_repo.json`

Suggested content:

- README says "AI agent platform".
- File tree includes only `README.md`, `docs/overview.md`, and a generic web app file.
- No tool registry, loop, skill, sandbox, eval, memory, or permission structure.

Expected output:

- `harness_relevance.level = "low"` or `"none"`
- Key capabilities are absent.
- Negative evidence explains that README claims are not supported by available file/source structure.
- Follow-up question asks whether source files were omitted from the snapshot.

## 7. Implementation Plan

### Change 1: Schema Extension

- Target files:
  - `src/agenttrace/agents/summary/schemas.py`
  - `src/agenttrace/agents/analysis/state.py`
  - `src/agenttrace/agents/analysis/schemas/harness.py`
- Change:
  - Add `possible_harness_relevance` to summary output.
  - Add `harness_relevance`, `harness_capabilities`, `negative_evidence`, and `followup_questions` to analysis state.
- Reason:
  - Preserve the current summary/deep-analysis split while adding harness-specific structure.
- Test:
  - Add schema default tests.
  - Add persisted output test.
- Risk:
  - Low. Additive field changes.

### Change 2: Summary Agent Prompt Improvement

- Target files:
  - `src/agenttrace/agents/summary/prompt.md`
  - `tests/test_summary_service.py`
- Change:
  - Add lightweight harness relevance hint rules.
  - Prevent README-only high confidence.
  - Require uncertainty wording when evidence is thin.
- Reason:
  - Summary should provide a cheap first-pass signal without pretending to validate implementation.
- Test:
  - Prompt asset test.
  - Fake structured model test for new field.
- Risk:
  - Low. Existing guard style can be reused.

### Change 3: Deep Analysis Harness Evidence

- Target files:
  - `src/agenttrace/agents/analysis/criteria/harness_capabilities.py`
  - `src/agenttrace/agents/analysis/nodes/evidence_scout.py`
  - `src/agenttrace/agents/analysis/nodes/harness_analyzer.py`
  - `src/agenttrace/agents/analysis/graph.py`
  - `src/agenttrace/agents/analysis/nodes/persist_analysis.py`
- Change:
  - Add deterministic capability mapping from file path, config, source snippet, test, and docs signals.
  - Add `supports` links from evidence to capability names.
  - Add negative evidence and follow-up question generation.
- Reason:
  - Reduce false positives and make harness relevance evidence-based.
- Test:
  - Fixture-based high/medium/low tests.
  - Test that README-only claims cannot produce high relevance.
- Risk:
  - Medium. Classification and quality status may change.

### Change 4: Fixtures And Expected Output

- Target files:
  - `data/fixtures/high_harness_repo.json`
  - `data/fixtures/medium_skill_or_mcp_repo.json`
  - `data/fixtures/low_readme_only_agent_repo.json`
  - `tests/test_harness_analysis.py`
- Change:
  - Add three fixture snapshots and expected output assertions.
- Reason:
  - Capability classification needs regression tests.
- Test:
  - Run focused `pytest tests/test_harness_analysis.py`.
  - Then run full `pytest`.
- Risk:
  - Low.

## 8. LangChain And LangGraph Decision

The Summary Agent should remain a single LangChain structured-output service. It does not need LangGraph because it is a low-cost README/metadata summary step.

The Deep Analysis Agent can keep the existing LangGraph workflow. A new `harness_analyzer` node is reasonable only if capability extraction becomes large enough to keep separate from `evidence_scout`. Otherwise, a small deterministic post-processing function after `evidence_scout` is sufficient for the first implementation.

Do not add external lint/test execution for analyzed repositories in the MVP. Treat test files, config files, examples, and selected source snippets as static evidence. Running arbitrary external repo code should remain out of scope until a stronger sandbox and execution policy exist.

## 9. Open Questions

- Should deep analysis results be exposed through an API now, or remain CLI/output JSON only?
- What source snippets are guaranteed to be available in `selected_files`?
- Is `harness_relevance.level` intended for search filters, repository card badges, ranking, or internal analysis only?
- Should `EVAL_HARNESS` and agent harness engineering share one relevance axis or remain separate?
- Should `followup_questions` be a separate top-level field or folded into existing `followup_actions`?
- What minimum capability combination should be required for `level = "high"`?

## 10. Recommendation

The current structure is not perfect, but it is sufficient for a small, safe first implementation.

Use existing pieces where they fit:

- LangChain structured output for summary.
- Existing LangGraph analysis graph for deep analysis.
- Pydantic for schema expansion.
- Pytest fixtures for regression coverage.
- Existing quality gate and limitation patterns.

Implement only the domain-specific harness layer directly:

- capability taxonomy
- capability evidence mapping
- relevance/confidence rules
- negative evidence
- follow-up questions

This keeps the change small, testable, and aligned with the existing AgentTrace architecture.
