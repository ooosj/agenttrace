# AgentHub Analysis Prototype Design

## Goal

Build a CLI-only prototype that analyzes one fixed AI-agent-related open source repository snapshot and produces a JSON result that helps a user decide what to inspect next.

The prototype is not a security audit, runtime verification system, benchmark runner, or popularity ranking. It is a static follow-up decision aid.

Initial fixed repository: `https://github.com/obra/superpowers`.

## User Outcome

After running the CLI, the user can open `out/superpowers_analysis.json` and see:

- what the README claims
- what file or directory signals support those claims
- what agent technology type the repository appears to be
- what risks or uncertainty remain
- what action to take next
- which paths to inspect first

## Approach

Keep the current six-node LangGraph MVP:

```text
collect_snapshot
  -> analyzer
  -> evidence_scout
  -> risk_and_followup_planner
  -> quality_gate
  -> persist_analysis
```

Do not split the graph into the full final architecture yet. Instead, improve the internal behavior and output quality around the current graph:

- better fixed snapshot for `obra/superpowers`
- better `SKILL` and `AGENT_FRAMEWORK` detection
- README claim extraction that avoids weak heading-only claims
- claim-to-evidence matching instead of assigning all evidence to the first claim
- follow-up action labels that match the product goal
- quality checks that prevent `COMPLETED` when evidence is missing

## Input

Add a fixed snapshot file:

```text
data/superpowers_repo.json
```

The snapshot contains:

- `repository_id`
- `full_name`
- `github_url`
- `metadata`
- `readme`
- `file_tree`

The file tree should include high-signal paths from the repo:

- `README.md`
- `skills/*/SKILL.md`
- `.codex-plugin/plugin.json`
- `.claude-plugin/plugin.json`
- `.cursor-plugin`
- `.opencode`
- `hooks`
- `scripts`
- `tests`
- `package.json`
- `LICENSE`

## Configuration And Secrets

The fixed-snapshot prototype does not require an API key.

If later iterations add live GitHub collection, LLM calls, or other external APIs, secrets must be loaded from `.env` and never hardcoded in source, snapshot files, docs, tests, or generated output.

Expected future secret handling:

- keep real values in `.env`
- commit only `.env.example`
- ignore `.env`
- read values through environment variables
- fail with a clear message when a required key is missing

## Output

The CLI writes JSON only:

```bash
python -m agenthub_analysis.cli data/superpowers_repo.json --out out/superpowers_analysis.json
```

Expected result shape remains compatible with the current prototype:

- `status`
- `agent_type`
- `relevance_score`
- `classification_reason`
- `claims`
- `evidence_signals`
- `risk_signals`
- `followup_actions`
- `followup_guide`
- `quality_warnings`
- `quality_errors`

Follow-up action values should use user-facing labels:

- `READ_NOW`
- `INSPECT_STRUCTURE`
- `TRY_EXAMPLE`
- `READ_WITH_CAUTION`
- `DEPRIORITIZE`
- `NEEDS_REANALYSIS`

## Node Changes

### `analyzer`

Keep one node, but improve behavior:

- classify `obra/superpowers` as `SKILL` if `SKILL.md`, `skills/`, plugin manifests, or reusable instruction language appears
- allow `AGENT_FRAMEWORK` signals to contribute to relevance without overriding the stronger `SKILL` classification
- extract meaningful README claims from descriptive paragraphs and numbered workflow lines
- skip short headings such as `Superpowers`, `Quickstart`, and `Installation`

### `evidence_scout`

Improve static evidence signals:

- match evidence to each claim using claim keywords and path hints
- create `signal_type` values such as `FILE_PATH`, `DIRECTORY`, `CONFIG`, `TEST`, `DOC`, and `DEPENDENCY`
- include confidence based on signal strength
- avoid putting every evidence signal under `claim-1`

### `risk_and_followup_planner`

Make output action-oriented:

- produce `READ_NOW` when relevance and evidence are strong
- produce `INSPECT_STRUCTURE` for core directories and manifests
- produce `TRY_EXAMPLE` when examples, scripts, or install paths are visible
- produce `READ_WITH_CAUTION` when static evidence cannot prove runtime behavior
- include low-severity uncertainty risk explaining that static analysis confirms structure, not runtime reliability

### `quality_gate`

Strengthen state checks:

- each claim should have at least one linked evidence signal when status is `COMPLETED`
- `COMPLETED` requires at least one evidence signal
- `INSUFFICIENT_EVIDENCE` should include a warning or risk
- follow-up actions must exist for in-scope repositories
- output should not use overconfident language such as "verified", "safe", or "guaranteed"

## Acceptance Criteria

Running:

```bash
python -m agenthub_analysis.cli data/superpowers_repo.json --out out/superpowers_analysis.json
```

must produce JSON where:

- `status` is `COMPLETED` or `UNCERTAIN`, not `OUT_OF_SCOPE`
- `agent_type` is `SKILL` unless the classifier has a clear reason to choose `AGENT_FRAMEWORK`
- at least three README claims are extracted
- evidence signals link to more than one claim
- evidence paths include `skills/` and at least one plugin/config path
- follow-up actions include `READ_NOW` and `INSPECT_STRUCTURE`
- risk signals include static-analysis uncertainty
- output is written to `out/superpowers_analysis.json`

## Verification

Primary verification is a CLI smoke run because `pytest` is not installed in the current environment:

```bash
python -m agenthub_analysis.cli data/superpowers_repo.json --out out/superpowers_analysis.json
```

If test dependencies become available, add or run focused tests for:

- `analyzer` classifies the fixed snapshot as `SKILL`
- `evidence_scout` links evidence to multiple claims
- `quality_gate` blocks `COMPLETED` with missing evidence

## Out Of Scope

- live GitHub API collector
- database persistence
- web UI or HTML report
- runtime execution
- security audit
- benchmark execution
- full AST analysis
- human review UI

