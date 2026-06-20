# AgentHub Analysis V2 Design

## Context

AgentTrace will implement the Analysis Agent contract described in `finalyongoh/docs:artifacts/current/AI_ANALYSIS_SPEC.md`. The Spring Backend remains the source of truth for repository records, snapshots, summaries, run status, and persistence. AgentTrace is responsible only for AI analysis orchestration and result construction.

Current AgentTrace analysis code is a prototype built around README claim extraction, path-based evidence scouting, harness heuristics, a quality gate, and callback persistence. The target design keeps useful pieces, but reorganizes the workflow around the document-defined nodes, schemas, task traces, and limited-analysis behavior.

## Goals

- Implement the full Analysis Agent node structure from `AI_ANALYSIS_SPEC.md`.
- Separate Backend-managed run status from LLM/agent-produced `AnalysisResult`.
- Use Backend-provided repository metadata, snapshot, README, file tree, and summary whenever available.
- Temporarily let AgentTrace call gitingest only to obtain transient source file content that Backend does not store yet.
- Preserve migration path so Spring Backend can later call gitingest and pass source files directly.
- Save limited analysis results when source content cannot be collected.
- Make tests deterministic without network access by using gitingest fixtures.

## Non-Goals

- Do not move repository storage or snapshot ownership into AgentTrace.
- Do not persist full gitingest source content in AgentTrace or require Backend to persist it now.
- Do not claim runtime correctness, benchmark results, security guarantees, or performance guarantees.
- Do not mix community signals into analysis output.

## Input Contract

The Analysis API accepts Backend-owned data plus optional source files:

```json
{
  "analysis_id": "uuid",
  "repository": {
    "repository_id": "repo-id",
    "full_name": "owner/name",
    "github_url": "https://github.com/owner/name",
    "description": "..."
  },
  "snapshot": {
    "snapshot_id": "snapshot-id",
    "commit_sha": "...",
    "captured_at": "2026-06-20T00:00:00Z"
  },
  "readme_text": "...",
  "file_tree": ["README.md", "pyproject.toml", "src/main.py"],
  "summary_result": {},
  "source_files": [
    {
      "path": "src/main.py",
      "content": "...",
      "content_hash": "sha256:..."
    }
  ],
  "external_ingest": {
    "enabled": true,
    "provider": "gitingest"
  }
}
```

If `source_files` is present, AgentTrace uses it directly. If it is missing and `external_ingest.enabled` is true, AgentTrace may call gitingest as a temporary provider. If gitingest fails, AgentTrace continues with README and file tree only and records missing source content in limitations.

## Provider Boundary

Input collection is hidden behind provider-style units:

- `ProvidedInputProvider`: normalizes request payload into internal input structures.
- `GitingestInputProvider`: fills missing source content from gitingest when allowed.
- `AnalysisInputAssembler`: merges Backend input and provider output, produces an input manifest, and marks analysis mode as `normal` or `limited`.

The analysis graph consumes the assembled input only. It does not care whether source content came from Backend, gitingest, or a test fixture.

## Content Model

Source content is transformed into file-boundary-preserving chunks:

- `ContentChunk`: `chunk_id`, `file_path`, `content`, `start_byte`, `end_byte`, `line_start`, `line_end`, `is_partial`, `content_hash`.
- `ChunkIndexEntry`: `file_path`, `chunk_ids`, `keywords`, `chunk_count`.
- `ChunkIndex`: lookup by path, keyword, and chunk id.

When no source content is available, file tree paths can still produce low-confidence `PATH_HINT` evidence, but claim verdicts that require source content become `INSUFFICIENT_EVIDENCE`.

## Graph Design

The graph follows the document-defined stages:

1. `collect_inputs`
2. `content_preprocessor`
3. `analysis_precheck`
4. `claim_analyzer`
5. `analysis_planner`
6. Task loop:
   - `select_next_task`
   - `evidence_scout`
   - `request_builder`
   - `evidence_evaluator`
   - `task_result_merge`
   - `finalize_task`
7. `repository_synthesizer`
8. `risk_and_followup`
9. `finalize_analysis`
10. `quality_gate`
11. Repair or persistence:
   - `result_repair`
   - `targeted_evidence_repair`
   - `critical_error_handler`
   - `persist_analysis`
   - `persist_failure`

The first implementation can keep deterministic heuristics for planning and evidence selection, while preserving node boundaries and state fields for later LLM improvements.

## Status Rules

Backend/Orchestrator status is separate from `AnalysisResult.analysis_status`.

Backend statuses include `queued`, `running`, `failed`, and `reanalysis_needed`.

Analysis statuses include:

- `completed`: all required tasks resolved.
- `completed_with_limitations`: required tasks resolved, but optional tasks or extra claims have limitations.
- `insufficient_evidence`: at least one required task cannot be judged because evidence is unavailable or too weak.
- `uncertain_classification`: agent type cannot be classified reliably.

Gitingest failure is not automatically a system failure. If README or file tree is available, AgentTrace stores a limited result with limitations. `failed` is reserved for repository identification failure, no analyzable input, unrecoverable schema errors, callback contract errors, or graph execution failure.

## Output Contract

AgentTrace returns/callbacks a `RepositoryAnalysisRecord`-style payload containing Backend run metadata plus `analysis_result` on success:

```json
{
  "analysis_id": "uuid",
  "status": "COMPLETED",
  "analysis_started_at": "2026-06-20T00:00:00Z",
  "analysis_completed_at": "2026-06-20T00:01:00Z",
  "error_message": null,
  "analysis_result": {
    "analysis_status": "completed_with_limitations",
    "agent_type": "MCP",
    "tech_stack_summary": {"ko": "...", "en": "..."},
    "analysis_claims": [],
    "evidence_signals": [],
    "evidence_task_results": [],
    "risk_signals": [],
    "follow_up_guide": {"ko": "...", "en": "..."},
    "analysis_limitations": {}
  },
  "trace": {}
}
```

Full source content is not returned. Evidence can include path, chunk id, line range, short excerpt, and content hash.

## Trace Contract

Each run records:

- `run_id`
- `analysis_version`
- `prompt_versions`
- `model_info`
- `input_manifest`
- `precheck_result`
- `claims`
- `analysis_plan`
- `task_traces`
- `final_result`
- `quality_gate_result`
- `timing`
- `usage`

Task traces include search attempts, candidate chunk ids, selected chunk ids, excluded chunk ids, exclusion reasons, task parts, and final task result.

## Testing Strategy

Tests must not depend on live gitingest. Add fixtures for gitingest raw output and expected parsed source files.

Required test groups:

- input normalization and provider fallback
- gitingest parser fixture conversion
- chunking and index lookup
- precheck status decisions
- claim extraction from README
- analysis plan and required task selection
- evidence scout selection and exclusion trace
- request builder 30k character limit
- task result merge verdicts
- limited analysis when gitingest fails
- quality gate warning and critical error paths
- API callback payload contract
- graph happy path

## Migration Path

When Spring Backend later owns gitingest collection, it will pass `source_files` directly and set `external_ingest.enabled=false`. AgentTrace will continue using the same `ProvidedInputProvider` and graph. `GitingestInputProvider` can then be disabled or removed without touching core analysis nodes.

## Open Defaults

Use these initial defaults unless product requirements change:

- `task_search_attempt_limit`: `2`
- `quality_repair_attempt_limit`: `1`
- request builder maximum input size: `30000` characters
- source excerpt maximum: `500` characters
- chunk target size: `12000` characters
- chunk overlap: `500` characters

## Approval

Approved in conversation on 2026-06-20. Key decisions:

- Follow the implementation design document unless it conflicts with current code constraints.
- AgentTrace handles AI analysis only.
- AgentTrace temporarily calls gitingest because source content is not stored in Backend.
- Save limited analysis results when gitingest fails.
- Implement the full document-level workflow, not only a small provider layer.
