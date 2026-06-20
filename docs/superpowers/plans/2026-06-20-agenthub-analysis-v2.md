# AgentHub Analysis V2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the document-defined AgentHub Analysis Agent workflow with provider-based input collection, transient gitingest support, chunked evidence tasks, traceable results, limited-analysis behavior, and Backend callback contract alignment.

**Architecture:** Spring Backend owns repository data and run persistence. AgentTrace accepts Backend input, optionally fills missing source content through a temporary gitingest provider, transforms content into chunks, runs the analysis graph, and returns a `RepositoryAnalysisRecord`-style callback payload. Graph nodes are split by the contract in `AI_ANALYSIS_SPEC.md`, with deterministic implementations first and LLM calls isolated in evaluator/repair nodes.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic, LangGraph, httpx, pytest, existing `agenttrace` package layout.

---

## File Structure

- Create: `src/agenttrace/agents/analysis/schemas/input.py`
  - API/internal input models: repository metadata, snapshot, source files, external ingest settings, assembled input.
- Create: `src/agenttrace/agents/analysis/schemas/content.py`
  - `ContentChunk`, `ChunkIndexEntry`, `ChunkIndex`, and chunk helper result models.
- Create: `src/agenttrace/agents/analysis/schemas/result.py`
  - `AnalysisResult`, `AnalysisClaim`, `EvidenceSignal`, `ClaimVerdict`, `EvidenceTaskResult`, `RiskSignal`, limitations, localized text.
- Create: `src/agenttrace/agents/analysis/schemas/trace.py`
  - run trace, task trace, search attempt trace, quality gate trace.
- Create: `src/agenttrace/agents/analysis/input_providers.py`
  - `ProvidedInputProvider`, `GitingestInputProvider`, `AnalysisInputAssembler`.
- Create: `src/agenttrace/agents/analysis/gitingest.py`
  - gitingest URL construction and raw-output parsing into source files.
- Create: `src/agenttrace/agents/analysis/chunking.py`
  - file-preserving chunking and keyword index construction.
- Create: `src/agenttrace/agents/analysis/nodes/collect_inputs.py`
  - replaces prototype input collection and calls the input assembler.
- Create: `src/agenttrace/agents/analysis/nodes/content_preprocessor.py`
  - builds chunks and chunk index.
- Create: `src/agenttrace/agents/analysis/nodes/analysis_precheck.py`
  - decides analyzability, limited mode, non-target status.
- Create: `src/agenttrace/agents/analysis/nodes/claim_analyzer.py`
  - moves claim extraction from `nodes/analyzer.py` into document-named node.
- Create: `src/agenttrace/agents/analysis/nodes/analysis_planner.py`
  - groups claims into required/optional evidence tasks.
- Create: `src/agenttrace/agents/analysis/nodes/request_builder.py`
  - splits selected chunks into 30k-character task parts.
- Create: `src/agenttrace/agents/analysis/nodes/evidence_evaluator.py`
  - evaluates task parts and produces evidence/verdict drafts.
- Create: `src/agenttrace/agents/analysis/nodes/task_result_merge.py`
  - merges task-part outputs into task results.
- Create: `src/agenttrace/agents/analysis/nodes/finalize_task.py`
  - finalizes task status and updates trace.
- Create: `src/agenttrace/agents/analysis/nodes/select_next_task.py`
  - selects next incomplete task.
- Create: `src/agenttrace/agents/analysis/nodes/repository_synthesizer.py`
  - synthesizes final status, tech stack, and agent type.
- Create: `src/agenttrace/agents/analysis/nodes/finalize_analysis.py`
  - builds `AnalysisResult`.
- Create: `src/agenttrace/agents/analysis/nodes/result_repair.py`
  - repairs warning-level shape issues.
- Create: `src/agenttrace/agents/analysis/nodes/targeted_evidence_repair.py`
  - retries one weak optional task within repair limit.
- Create: `src/agenttrace/agents/analysis/nodes/critical_error_handler.py`
  - builds failure payload for critical quality errors.
- Modify: `src/agenttrace/agents/analysis/nodes/evidence_scout.py`
  - consume task/chunk index and emit selected/excluded chunk trace.
- Modify: `src/agenttrace/agents/analysis/nodes/risk_and_followup.py`
  - output document-shaped `RiskSignal[]` and localized guide.
- Modify: `src/agenttrace/agents/analysis/nodes/quality_gate.py`
  - validate `AnalysisResult` and distinguish warning vs critical errors.
- Modify: `src/agenttrace/agents/analysis/nodes/persist_analysis.py`
  - build callback payload without storing full source content.
- Modify: `src/agenttrace/agents/analysis/state.py`
  - add document-level state fields.
- Modify: `src/agenttrace/agents/analysis/graph.py`
  - replace prototype graph with document-defined nodes and routing.
- Modify: `src/agenttrace/api/analysis.py`
  - accept expanded request model and preserve old request compatibility where tests require it.
- Create: `tests/fixtures/gitingest_superpowers.txt`
  - deterministic raw gitingest-like fixture.
- Create: `tests/test_analysis_input_providers.py`
- Create: `tests/test_gitingest_parser.py`
- Create: `tests/test_analysis_chunking.py`
- Create: `tests/test_analysis_v2_nodes.py`
- Create: `tests/test_analysis_v2_graph.py`
- Modify: `tests/test_api_analysis.py`
- Modify: `tests/test_harness_analysis.py`

---

### Task 1: Define Analysis V2 Schemas

**Files:**
- Create: `src/agenttrace/agents/analysis/schemas/input.py`
- Create: `src/agenttrace/agents/analysis/schemas/content.py`
- Create: `src/agenttrace/agents/analysis/schemas/result.py`
- Create: `src/agenttrace/agents/analysis/schemas/trace.py`
- Test: `tests/test_analysis_v2_schemas.py`

- [ ] **Step 1: Write failing schema tests**

```python
from agenttrace.agents.analysis.schemas.input import AnalysisInputRequest, SourceFile
from agenttrace.agents.analysis.schemas.content import ContentChunk
from agenttrace.agents.analysis.schemas.result import AnalysisResult, ClaimVerdict


def test_analysis_input_accepts_backend_payload_without_source_files():
    req = AnalysisInputRequest.model_validate(
        {
            "analysis_id": "00000000-0000-0000-0000-000000000001",
            "repository": {
                "repository_id": "repo-1",
                "full_name": "owner/repo",
                "github_url": "https://github.com/owner/repo",
                "description": "Agent repo",
            },
            "snapshot": {"snapshot_id": "snap-1", "commit_sha": "abc", "captured_at": "2026-06-20T00:00:00Z"},
            "readme_text": "# Repo\nProvides an MCP server.",
            "file_tree": ["README.md", "src/server.py"],
            "summary_result": {"summary_status": "completed"},
            "external_ingest": {"enabled": False, "provider": "gitingest"},
        }
    )

    assert req.source_files == []
    assert req.external_ingest.enabled is False


def test_source_file_hash_is_computed_when_missing():
    src = SourceFile(path="src/server.py", content="print('hi')")
    assert src.content_hash.startswith("sha256:")


def test_analysis_result_requires_evidence_task_results():
    result = AnalysisResult.model_validate(
        {
            "analysis_status": "insufficient_evidence",
            "agent_type": "MCP",
            "tech_stack_summary": {"ko": "Python 기반", "en": "Python based"},
            "analysis_claims": [],
            "evidence_signals": [],
            "evidence_task_results": [],
            "risk_signals": [],
            "follow_up_guide": {"ko": "README와 src를 확인하세요.", "en": "Check README and src."},
            "analysis_limitations": {"missing_inputs": ["source_files"], "notes": ["limited analysis"]},
        }
    )
    assert result.analysis_status == "insufficient_evidence"


def test_claim_verdict_enum_matches_contract():
    verdict = ClaimVerdict(
        claim_id="claim-1",
        verdict="INSUFFICIENT_EVIDENCE",
        reason="Source content unavailable.",
        evidence_signal_ids=[],
        limitations=["gitingest failed"],
    )
    assert verdict.verdict == "INSUFFICIENT_EVIDENCE"
```

- [ ] **Step 2: Run schema tests and verify failure**

Run: `pytest tests/test_analysis_v2_schemas.py -v`

Expected: FAIL with `ModuleNotFoundError` for new schema modules.

- [ ] **Step 3: Implement schema modules**

Create Pydantic models with these exact public names:

```python
# src/agenttrace/agents/analysis/schemas/input.py
from __future__ import annotations

import hashlib
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class RepositoryInput(BaseModel):
    repository_id: str | None = None
    full_name: str
    github_url: str | None = None
    description: str | None = None
    primary_language: str | None = None
    topics: list[str] = Field(default_factory=list)


class SnapshotInput(BaseModel):
    snapshot_id: str | None = None
    commit_sha: str | None = None
    captured_at: str | None = None
    stars: int | None = None
    forks: int | None = None
    pushed_at: str | None = None


class SourceFile(BaseModel):
    path: str
    content: str
    content_hash: str | None = None

    @field_validator("content_hash", mode="before")
    @classmethod
    def default_hash(cls, value: str | None, info):
        if value:
            return value
        content = info.data.get("content", "")
        return "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()


class ExternalIngestConfig(BaseModel):
    enabled: bool = False
    provider: str = "gitingest"


class AnalysisInputRequest(BaseModel):
    analysis_id: UUID
    repository: RepositoryInput
    snapshot: SnapshotInput | None = None
    readme_text: str | None = None
    file_tree: list[str] = Field(default_factory=list)
    summary_result: dict[str, Any] = Field(default_factory=dict)
    source_files: list[SourceFile] = Field(default_factory=list)
    external_ingest: ExternalIngestConfig = Field(default_factory=ExternalIngestConfig)


class AssembledAnalysisInput(BaseModel):
    request: AnalysisInputRequest
    source_files: list[SourceFile]
    analysis_mode: str
    missing_inputs: list[str] = Field(default_factory=list)
    input_manifest: dict[str, Any] = Field(default_factory=dict)
```

```python
# src/agenttrace/agents/analysis/schemas/content.py
from __future__ import annotations

from pydantic import BaseModel, Field


class ContentChunk(BaseModel):
    chunk_id: str
    file_path: str
    content: str
    start_byte: int
    end_byte: int
    line_start: int
    line_end: int
    is_partial: bool
    content_hash: str


class ChunkIndexEntry(BaseModel):
    file_path: str
    chunk_ids: list[str]
    keywords: list[str] = Field(default_factory=list)
    chunk_count: int


class ChunkIndex(BaseModel):
    entries: list[ChunkIndexEntry] = Field(default_factory=list)
    chunks_by_id: dict[str, ContentChunk] = Field(default_factory=dict)
```

```python
# src/agenttrace/agents/analysis/schemas/result.py
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class LocalizedText(BaseModel):
    ko: str
    en: str


class AnalysisLimitations(BaseModel):
    missing_inputs: list[str] = Field(default_factory=list)
    truncated_inputs: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class AnalysisClaim(BaseModel):
    claim_id: str
    claim_text: str
    source_path: str = "README.md"
    source_section: str | None = None
    confidence: float = 0.5
    evidence_signal_ids: list[str] = Field(default_factory=list)


class EvidenceSignal(BaseModel):
    signal_id: str
    signal_type: str
    path: str
    chunk_id: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    content_excerpt: str | None = None
    content_hash: str | None = None
    summary: str
    confidence: float = 0.5


class ClaimVerdict(BaseModel):
    claim_id: str
    verdict: Literal["SUPPORTED", "PARTIALLY_SUPPORTED", "CONTRADICTED", "NOT_FOUND", "INSUFFICIENT_EVIDENCE"]
    reason: str
    evidence_signal_ids: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class EvidenceTaskResult(BaseModel):
    task_id: str
    status: Literal["RESOLVED", "INSUFFICIENT_EVIDENCE"]
    claim_verdicts: list[ClaimVerdict]
    evidence_signal_ids: list[str] = Field(default_factory=list)
    search_limit_reached: bool = False
    limitations: list[str] = Field(default_factory=list)


class RiskSignal(BaseModel):
    risk_type: str
    summary: str
    severity: Literal["low", "medium", "high"] = "low"


class AnalysisResult(BaseModel):
    analysis_status: Literal["completed", "completed_with_limitations", "insufficient_evidence", "uncertain_classification"]
    agent_type: Literal["MCP", "Skill", "Eval", "ToolUse", "Framework", "Other", "Unknown"] | None = None
    tech_stack_summary: LocalizedText | None = None
    analysis_claims: list[AnalysisClaim]
    evidence_signals: list[EvidenceSignal]
    evidence_task_results: list[EvidenceTaskResult]
    risk_signals: list[RiskSignal]
    follow_up_guide: LocalizedText | None = None
    analysis_limitations: AnalysisLimitations
```

```python
# src/agenttrace/agents/analysis/schemas/trace.py
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SearchAttemptTrace(BaseModel):
    attempt: int
    queries: list[str] = Field(default_factory=list)
    candidate_chunk_ids: list[str] = Field(default_factory=list)
    selected_chunk_ids: list[str] = Field(default_factory=list)
    excluded_chunk_ids: list[str] = Field(default_factory=list)
    exclusion_reasons: dict[str, str] = Field(default_factory=dict)


class TaskTrace(BaseModel):
    task_id: str
    required: bool
    search_attempts: list[SearchAttemptTrace] = Field(default_factory=list)
    task_parts: list[dict[str, Any]] = Field(default_factory=list)
    task_result: dict[str, Any] = Field(default_factory=dict)


class AnalysisRunTrace(BaseModel):
    run_id: str
    analysis_version: str = "analysis-v2"
    prompt_versions: dict[str, str] = Field(default_factory=dict)
    model_info: dict[str, Any] = Field(default_factory=dict)
    input_manifest: dict[str, Any] = Field(default_factory=dict)
    precheck_result: dict[str, Any] = Field(default_factory=dict)
    claims: list[dict[str, Any]] = Field(default_factory=list)
    analysis_plan: dict[str, Any] = Field(default_factory=dict)
    task_traces: list[TaskTrace] = Field(default_factory=list)
    final_result: dict[str, Any] = Field(default_factory=dict)
    quality_gate_result: dict[str, Any] = Field(default_factory=dict)
    timing: dict[str, Any] = Field(default_factory=dict)
    usage: dict[str, Any] = Field(default_factory=dict)
```

- [ ] **Step 4: Run schema tests**

Run: `pytest tests/test_analysis_v2_schemas.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/agenttrace/agents/analysis/schemas/input.py src/agenttrace/agents/analysis/schemas/content.py src/agenttrace/agents/analysis/schemas/result.py src/agenttrace/agents/analysis/schemas/trace.py tests/test_analysis_v2_schemas.py
git commit -m "feat: add analysis v2 schemas"
```

### Task 2: Add gitingest Parser and Input Providers

**Files:**
- Create: `tests/fixtures/gitingest_superpowers.txt`
- Create: `tests/test_gitingest_parser.py`
- Create: `tests/test_analysis_input_providers.py`
- Create: `src/agenttrace/agents/analysis/gitingest.py`
- Create: `src/agenttrace/agents/analysis/input_providers.py`

- [ ] **Step 1: Write gitingest fixture**

Create `tests/fixtures/gitingest_superpowers.txt`:

```text
Repository: owner/repo

Files:
README.md
pyproject.toml
src/server.py

================================================
FILE: README.md
================================================
# Repo
Provides an MCP server and tool registration.

================================================
FILE: pyproject.toml
================================================
[project]
name = "repo"

================================================
FILE: src/server.py
================================================
class Server:
    def register_tool(self, name):
        return name
```

- [ ] **Step 2: Write failing parser tests**

```python
from pathlib import Path

from agenttrace.agents.analysis.gitingest import parse_gitingest_output


def test_parse_gitingest_output_extracts_source_files():
    raw = Path("tests/fixtures/gitingest_superpowers.txt").read_text()
    files = parse_gitingest_output(raw)

    assert [f.path for f in files] == ["README.md", "pyproject.toml", "src/server.py"]
    assert "register_tool" in files[2].content
    assert files[2].content_hash.startswith("sha256:")
```

- [ ] **Step 3: Write failing provider tests**

```python
from uuid import UUID

import pytest

from agenttrace.agents.analysis.input_providers import AnalysisInputAssembler, GitingestInputProvider, ProvidedInputProvider
from agenttrace.agents.analysis.schemas.input import AnalysisInputRequest


def _request(source_files=None, external_enabled=False):
    return AnalysisInputRequest.model_validate(
        {
            "analysis_id": "00000000-0000-0000-0000-000000000001",
            "repository": {"full_name": "owner/repo", "github_url": "https://github.com/owner/repo"},
            "snapshot": {"snapshot_id": "snap-1"},
            "readme_text": "# Repo",
            "file_tree": ["README.md", "src/server.py"],
            "source_files": source_files or [],
            "external_ingest": {"enabled": external_enabled, "provider": "gitingest"},
        }
    )


def test_assembler_prefers_provided_source_files():
    req = _request(source_files=[{"path": "src/server.py", "content": "print('x')"}], external_enabled=True)
    assembled = AnalysisInputAssembler(ProvidedInputProvider(), GitingestInputProvider(fetch_text=lambda _: pytest.fail("not called"))).assemble(req)

    assert assembled.analysis_mode == "normal"
    assert assembled.source_files[0].path == "src/server.py"


def test_assembler_records_limited_mode_when_gitingest_fails():
    req = _request(external_enabled=True)
    assembled = AnalysisInputAssembler(
        ProvidedInputProvider(),
        GitingestInputProvider(fetch_text=lambda _: (_ for _ in ()).throw(RuntimeError("boom"))),
    ).assemble(req)

    assert assembled.analysis_mode == "limited"
    assert "gitingest_file_content" in assembled.missing_inputs
```

- [ ] **Step 4: Run provider tests and verify failure**

Run: `pytest tests/test_gitingest_parser.py tests/test_analysis_input_providers.py -v`

Expected: FAIL with missing modules.

- [ ] **Step 5: Implement parser and providers**

```python
# src/agenttrace/agents/analysis/gitingest.py
from __future__ import annotations

import re
from collections.abc import Callable

import httpx

from agenttrace.agents.analysis.schemas.input import SourceFile

FILE_RE = re.compile(r"=+\nFILE: (?P<path>[^\n]+)\n=+\n(?P<content>.*?)(?=\n=+\nFILE: |\Z)", re.DOTALL)


def parse_gitingest_output(raw: str) -> list[SourceFile]:
    files: list[SourceFile] = []
    for match in FILE_RE.finditer(raw):
        path = match.group("path").strip()
        content = match.group("content").strip("\n")
        if path and content:
            files.append(SourceFile(path=path, content=content))
    return files


def build_gitingest_url(github_url: str, base_url: str = "https://gitingest.com") -> str:
    return f"{base_url.rstrip('/')}/{github_url.rstrip('/')}"


def fetch_gitingest_text(url: str) -> str:
    response = httpx.get(url, timeout=30.0)
    response.raise_for_status()
    return response.text
```

```python
# src/agenttrace/agents/analysis/input_providers.py
from __future__ import annotations

from collections.abc import Callable

from agenttrace.agents.analysis.gitingest import build_gitingest_url, fetch_gitingest_text, parse_gitingest_output
from agenttrace.agents.analysis.schemas.input import AnalysisInputRequest, AssembledAnalysisInput, SourceFile


class ProvidedInputProvider:
    def load(self, request: AnalysisInputRequest) -> list[SourceFile]:
        return request.source_files


class GitingestInputProvider:
    def __init__(self, fetch_text: Callable[[str], str] = fetch_gitingest_text):
        self._fetch_text = fetch_text

    def load(self, request: AnalysisInputRequest) -> list[SourceFile]:
        if not request.repository.github_url:
            return []
        url = build_gitingest_url(request.repository.github_url)
        return parse_gitingest_output(self._fetch_text(url))


class AnalysisInputAssembler:
    def __init__(self, provided: ProvidedInputProvider | None = None, gitingest: GitingestInputProvider | None = None):
        self.provided = provided or ProvidedInputProvider()
        self.gitingest = gitingest or GitingestInputProvider()

    def assemble(self, request: AnalysisInputRequest) -> AssembledAnalysisInput:
        missing_inputs: list[str] = []
        source_files = self.provided.load(request)

        if not source_files and request.external_ingest.enabled:
            try:
                source_files = self.gitingest.load(request)
            except Exception:
                source_files = []
                missing_inputs.append("gitingest_file_content")

        if not source_files:
            missing_inputs.append("source_files")

        return AssembledAnalysisInput(
            request=request,
            source_files=source_files,
            analysis_mode="normal" if source_files else "limited",
            missing_inputs=sorted(set(missing_inputs)),
            input_manifest={
                "repository_full_name": request.repository.full_name,
                "source_file_count": len(source_files),
                "file_tree_count": len(request.file_tree),
                "has_readme": bool(request.readme_text),
                "external_ingest_enabled": request.external_ingest.enabled,
            },
        )
```

- [ ] **Step 6: Run provider tests**

Run: `pytest tests/test_gitingest_parser.py tests/test_analysis_input_providers.py -v`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/agenttrace/agents/analysis/gitingest.py src/agenttrace/agents/analysis/input_providers.py tests/fixtures/gitingest_superpowers.txt tests/test_gitingest_parser.py tests/test_analysis_input_providers.py
git commit -m "feat: add analysis input providers"
```

### Task 3: Add Chunking and Chunk Index

**Files:**
- Create: `src/agenttrace/agents/analysis/chunking.py`
- Create: `tests/test_analysis_chunking.py`

- [ ] **Step 1: Write failing chunking tests**

```python
from agenttrace.agents.analysis.chunking import build_chunk_index, chunk_source_files
from agenttrace.agents.analysis.schemas.input import SourceFile


def test_chunk_source_files_preserves_file_boundary_and_line_numbers():
    files = [SourceFile(path="src/server.py", content="line1\nline2\nline3")]
    chunks = chunk_source_files(files, target_size=100, overlap=0)

    assert len(chunks) == 1
    assert chunks[0].file_path == "src/server.py"
    assert chunks[0].line_start == 1
    assert chunks[0].line_end == 3
    assert chunks[0].is_partial is False


def test_build_chunk_index_extracts_path_keywords():
    files = [SourceFile(path="src/mcp/server.py", content="def register_tool(): pass")]
    chunks = chunk_source_files(files, target_size=100, overlap=0)
    index = build_chunk_index(chunks)

    entry = index.entries[0]
    assert entry.file_path == "src/mcp/server.py"
    assert "mcp" in entry.keywords
    assert "register_tool" in entry.keywords
    assert chunks[0].chunk_id in index.chunks_by_id
```

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest tests/test_analysis_chunking.py -v`

Expected: FAIL with missing `chunking` module.

- [ ] **Step 3: Implement chunking**

```python
from __future__ import annotations

import re

from agenttrace.agents.analysis.schemas.content import ChunkIndex, ChunkIndexEntry, ContentChunk
from agenttrace.agents.analysis.schemas.input import SourceFile

WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")


def _line_for_offset(content: str, offset: int) -> int:
    return content[:offset].count("\n") + 1


def _keywords(path: str, content: str) -> list[str]:
    path_words = re.split(r"[^A-Za-z0-9_]+", path)
    content_words = WORD_RE.findall(content[:4000])
    seen: set[str] = set()
    result: list[str] = []
    for word in path_words + content_words:
        lower = word.lower()
        if len(lower) >= 3 and lower not in seen:
            seen.add(lower)
            result.append(lower)
    return result[:80]


def chunk_source_files(files: list[SourceFile], target_size: int = 12000, overlap: int = 500) -> list[ContentChunk]:
    chunks: list[ContentChunk] = []
    counter = 1
    for source in files:
        content = source.content
        if not content:
            continue
        start = 0
        while start < len(content):
            end = min(len(content), start + target_size)
            chunk_text = content[start:end]
            chunks.append(
                ContentChunk(
                    chunk_id=f"chunk-{counter:04d}",
                    file_path=source.path,
                    content=chunk_text,
                    start_byte=start,
                    end_byte=end,
                    line_start=_line_for_offset(content, start),
                    line_end=_line_for_offset(content, end),
                    is_partial=len(content) > target_size,
                    content_hash=source.content_hash or "",
                )
            )
            counter += 1
            if end == len(content):
                break
            start = max(end - overlap, start + 1)
    return chunks


def build_chunk_index(chunks: list[ContentChunk]) -> ChunkIndex:
    by_path: dict[str, list[ContentChunk]] = {}
    for chunk in chunks:
        by_path.setdefault(chunk.file_path, []).append(chunk)

    entries = [
        ChunkIndexEntry(
            file_path=path,
            chunk_ids=[chunk.chunk_id for chunk in path_chunks],
            keywords=_keywords(path, "\n".join(chunk.content for chunk in path_chunks)),
            chunk_count=len(path_chunks),
        )
        for path, path_chunks in sorted(by_path.items())
    ]
    return ChunkIndex(entries=entries, chunks_by_id={chunk.chunk_id: chunk for chunk in chunks})
```

- [ ] **Step 4: Run chunking tests**

Run: `pytest tests/test_analysis_chunking.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/agenttrace/agents/analysis/chunking.py tests/test_analysis_chunking.py
git commit -m "feat: add analysis chunk index"
```

### Task 4: Add State Fields and Input/Preprocess Nodes

**Files:**
- Modify: `src/agenttrace/agents/analysis/state.py`
- Create: `src/agenttrace/agents/analysis/nodes/collect_inputs.py`
- Create: `src/agenttrace/agents/analysis/nodes/content_preprocessor.py`
- Create: `src/agenttrace/agents/analysis/nodes/analysis_precheck.py`
- Test: `tests/test_analysis_v2_nodes.py`

- [ ] **Step 1: Write failing node tests**

```python
from agenttrace.agents.analysis.nodes.analysis_precheck import analysis_precheck
from agenttrace.agents.analysis.nodes.content_preprocessor import content_preprocessor


def test_content_preprocessor_builds_chunks_from_source_files():
    state = {
        "source_files": [{"path": "src/server.py", "content": "def register_tool(): pass"}],
        "missing_inputs": [],
    }
    result = content_preprocessor(state)

    assert result["content_chunks"]
    assert result["chunk_index"]["entries"][0]["file_path"] == "src/server.py"


def test_analysis_precheck_allows_limited_readme_file_tree_analysis():
    state = {
        "readme": "# Repo\nProvides MCP tools.",
        "file_tree": [{"path": "src/server.py"}],
        "missing_inputs": ["source_files"],
        "content_chunks": [],
    }
    result = analysis_precheck(state)

    assert result["precheck_result"]["can_analyze"] is True
    assert result["analysis_mode"] == "limited"
    assert "source_files" in result["analysis_limitations"]["missing_inputs"]
```

- [ ] **Step 2: Run node tests and verify failure**

Run: `pytest tests/test_analysis_v2_nodes.py::test_content_preprocessor_builds_chunks_from_source_files tests/test_analysis_v2_nodes.py::test_analysis_precheck_allows_limited_readme_file_tree_analysis -v`

Expected: FAIL with missing nodes or fields.

- [ ] **Step 3: Extend `AnalysisState`**

Add these keys to `src/agenttrace/agents/analysis/state.py`:

```python
    analysis_request: dict
    source_files: list[dict]
    missing_inputs: list[str]
    input_manifest: dict
    analysis_mode: str
    content_chunks: list[dict]
    chunk_index: dict
    precheck_result: dict
    analysis_limitations: dict
    analysis_plan: dict
    current_task_id: str | None
    next_task_id: str | None
    task_results: list[dict]
    task_traces: list[dict]
    final_result: dict
    quality_gate_result: dict
    callback_payload: dict
```

- [ ] **Step 4: Implement input/precheck nodes**

```python
# collect_inputs.py
from __future__ import annotations

from agenttrace.agents.analysis.input_providers import AnalysisInputAssembler
from agenttrace.agents.analysis.schemas.input import AnalysisInputRequest


def collect_inputs(state: dict) -> dict:
    request = AnalysisInputRequest.model_validate(state["analysis_request"])
    assembled = AnalysisInputAssembler().assemble(request)
    return {
        "run_id": str(request.analysis_id),
        "full_name": request.repository.full_name,
        "github_url": request.repository.github_url,
        "metadata": request.repository.model_dump(),
        "repository_snapshot": request.snapshot.model_dump() if request.snapshot else {},
        "readme": request.readme_text or "",
        "file_tree": [{"path": path} for path in request.file_tree],
        "source_files": [file.model_dump() for file in assembled.source_files],
        "missing_inputs": assembled.missing_inputs,
        "input_manifest": assembled.input_manifest,
        "analysis_mode": assembled.analysis_mode,
    }
```

```python
# content_preprocessor.py
from __future__ import annotations

from agenttrace.agents.analysis.chunking import build_chunk_index, chunk_source_files
from agenttrace.agents.analysis.schemas.input import SourceFile


def content_preprocessor(state: dict) -> dict:
    source_files = [SourceFile.model_validate(item) for item in state.get("source_files", [])]
    chunks = chunk_source_files(source_files)
    index = build_chunk_index(chunks)
    return {
        "content_chunks": [chunk.model_dump() for chunk in chunks],
        "chunk_index": index.model_dump(),
    }
```

```python
# analysis_precheck.py
from __future__ import annotations


def analysis_precheck(state: dict) -> dict:
    has_readme = bool(state.get("readme"))
    has_file_tree = bool(state.get("file_tree"))
    has_chunks = bool(state.get("content_chunks"))
    missing_inputs = list(state.get("missing_inputs", []))
    can_analyze = has_readme or has_file_tree
    mode = "normal" if has_chunks else "limited"
    limitations = {"missing_inputs": missing_inputs, "truncated_inputs": [], "notes": []}
    if mode == "limited":
        limitations["notes"].append("README and file tree based limited analysis.")
    return {
        "precheck_result": {"can_analyze": can_analyze, "has_readme": has_readme, "has_file_tree": has_file_tree, "has_source_chunks": has_chunks},
        "analysis_mode": mode,
        "analysis_limitations": limitations,
        "status": "running" if can_analyze else "failed",
        "error_message": None if can_analyze else "No README or file tree available.",
    }
```

- [ ] **Step 5: Run focused tests**

Run: `pytest tests/test_analysis_v2_nodes.py -v`

Expected: PASS for new tests. Existing tests may still fail until graph wiring is updated.

- [ ] **Step 6: Commit**

```bash
git add src/agenttrace/agents/analysis/state.py src/agenttrace/agents/analysis/nodes/collect_inputs.py src/agenttrace/agents/analysis/nodes/content_preprocessor.py src/agenttrace/agents/analysis/nodes/analysis_precheck.py tests/test_analysis_v2_nodes.py
git commit -m "feat: add analysis v2 input nodes"
```

### Task 5: Rename and Extend Claim Analyzer and Planner

**Files:**
- Create: `src/agenttrace/agents/analysis/nodes/claim_analyzer.py`
- Create: `src/agenttrace/agents/analysis/nodes/analysis_planner.py`
- Modify: `tests/test_analysis_v2_nodes.py`

- [ ] **Step 1: Write failing tests**

```python
from agenttrace.agents.analysis.nodes.analysis_planner import analysis_planner
from agenttrace.agents.analysis.nodes.claim_analyzer import claim_analyzer


def test_claim_analyzer_extracts_readme_claims_without_summary_regeneration():
    result = claim_analyzer({"readme": "# Repo\nProvides an MCP server.\nSupports tool registration."})

    assert [claim["claim_id"] for claim in result["claims"]] == ["claim-1", "claim-2"]
    assert "MCP server" in result["claims"][0]["claim_text"]


def test_analysis_planner_groups_claims_into_required_tasks():
    result = analysis_planner(
        {
            "metadata": {"repository_id": "repo-1"},
            "claims": [
                {"claim_id": "claim-1", "claim_text": "Provides an MCP server.", "source_path": "README.md"},
                {"claim_id": "claim-2", "claim_text": "Supports tool registration.", "source_path": "README.md"},
            ],
            "file_tree": [{"path": "src/server.py"}, {"path": "README.md"}],
        }
    )

    task = result["analysis_plan"]["tasks"][0]
    assert task["required"] is True
    assert task["status"] == "PENDING"
    assert "claim-1" in task["claims"]
```

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest tests/test_analysis_v2_nodes.py::test_claim_analyzer_extracts_readme_claims_without_summary_regeneration tests/test_analysis_v2_nodes.py::test_analysis_planner_groups_claims_into_required_tasks -v`

Expected: FAIL with missing nodes.

- [ ] **Step 3: Implement claim analyzer and planner**

Use current extraction logic from `nodes/analyzer.py` as reference. Keep deterministic fallback. Return `AnalysisClaim`-shaped dicts.

Planner rule:
- create one required task when any claim mentions `mcp`, `server`, `tool`, `agent`, `skill`, `eval`, or `framework`;
- create one optional task for other claims;
- target paths are file-tree entries matching claim keywords plus common source directories.

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_analysis_v2_nodes.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/agenttrace/agents/analysis/nodes/claim_analyzer.py src/agenttrace/agents/analysis/nodes/analysis_planner.py tests/test_analysis_v2_nodes.py
git commit -m "feat: add claim planning nodes"
```

### Task 6: Implement Evidence Task Loop Nodes

**Files:**
- Modify: `src/agenttrace/agents/analysis/nodes/evidence_scout.py`
- Create: `src/agenttrace/agents/analysis/nodes/request_builder.py`
- Create: `src/agenttrace/agents/analysis/nodes/evidence_evaluator.py`
- Create: `src/agenttrace/agents/analysis/nodes/task_result_merge.py`
- Create: `src/agenttrace/agents/analysis/nodes/finalize_task.py`
- Create: `src/agenttrace/agents/analysis/nodes/select_next_task.py`
- Modify: `tests/test_analysis_v2_nodes.py`

- [ ] **Step 1: Write failing evidence loop tests**

```python
from agenttrace.agents.analysis.nodes.evidence_evaluator import evidence_evaluator
from agenttrace.agents.analysis.nodes.evidence_scout import evidence_scout
from agenttrace.agents.analysis.nodes.finalize_task import finalize_task
from agenttrace.agents.analysis.nodes.request_builder import request_builder
from agenttrace.agents.analysis.nodes.task_result_merge import task_result_merge


def _state_with_task_and_chunk():
    return {
        "current_task_id": "task-1",
        "analysis_plan": {"tasks": [{"task_id": "task-1", "claims": ["claim-1"], "target_paths": ["src/server.py"], "required": True, "status": "PENDING"}]},
        "claims": [{"claim_id": "claim-1", "claim_text": "Provides an MCP server."}],
        "chunk_index": {
            "entries": [{"file_path": "src/server.py", "chunk_ids": ["chunk-0001"], "keywords": ["server", "mcp"], "chunk_count": 1}],
            "chunks_by_id": {
                "chunk-0001": {
                    "chunk_id": "chunk-0001",
                    "file_path": "src/server.py",
                    "content": "class McpServer: pass",
                    "start_byte": 0,
                    "end_byte": 21,
                    "line_start": 1,
                    "line_end": 1,
                    "is_partial": False,
                    "content_hash": "sha256:x",
                }
            },
        },
        "task_traces": [],
    }


def test_evidence_task_loop_resolves_supported_claim():
    state = _state_with_task_and_chunk()
    state.update(evidence_scout(state))
    state.update(request_builder(state))
    state.update(evidence_evaluator(state))
    state.update(task_result_merge(state))
    result = finalize_task(state)

    task_result = result["task_results"][0]
    assert task_result["status"] == "RESOLVED"
    assert task_result["claim_verdicts"][0]["verdict"] in {"SUPPORTED", "PARTIALLY_SUPPORTED"}
```

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest tests/test_analysis_v2_nodes.py::test_evidence_task_loop_resolves_supported_claim -v`

Expected: FAIL with missing nodes or old evidence scout shape.

- [ ] **Step 3: Implement evidence loop**

Implementation rules:
- `evidence_scout` selects chunks by target path and keyword overlap.
- If no chunks exist but file tree target paths exist, emit low-confidence `PATH_HINT`.
- `request_builder` packs selected chunks into parts under 30000 characters.
- `evidence_evaluator` uses deterministic matching first: matching source chunks produce `SUPPORTED` or `PARTIALLY_SUPPORTED`; path-only hints produce `INSUFFICIENT_EVIDENCE`.
- `task_result_merge` merges part drafts by claim id.
- `finalize_task` appends `EvidenceTaskResult` and task trace.
- `select_next_task` picks first `PENDING` task.

- [ ] **Step 4: Run evidence tests**

Run: `pytest tests/test_analysis_v2_nodes.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/agenttrace/agents/analysis/nodes/evidence_scout.py src/agenttrace/agents/analysis/nodes/request_builder.py src/agenttrace/agents/analysis/nodes/evidence_evaluator.py src/agenttrace/agents/analysis/nodes/task_result_merge.py src/agenttrace/agents/analysis/nodes/finalize_task.py src/agenttrace/agents/analysis/nodes/select_next_task.py tests/test_analysis_v2_nodes.py
git commit -m "feat: add evidence task loop"
```

### Task 7: Add Synthesis, Finalize, Quality, and Persistence Contract

**Files:**
- Create: `src/agenttrace/agents/analysis/nodes/repository_synthesizer.py`
- Create: `src/agenttrace/agents/analysis/nodes/finalize_analysis.py`
- Create: `src/agenttrace/agents/analysis/nodes/result_repair.py`
- Create: `src/agenttrace/agents/analysis/nodes/targeted_evidence_repair.py`
- Create: `src/agenttrace/agents/analysis/nodes/critical_error_handler.py`
- Modify: `src/agenttrace/agents/analysis/nodes/risk_and_followup.py`
- Modify: `src/agenttrace/agents/analysis/nodes/quality_gate.py`
- Modify: `src/agenttrace/agents/analysis/nodes/persist_analysis.py`
- Modify: `tests/test_analysis_v2_nodes.py`

- [ ] **Step 1: Write failing finalization tests**

```python
from agenttrace.agents.analysis.nodes.finalize_analysis import finalize_analysis
from agenttrace.agents.analysis.nodes.quality_gate import quality_gate
from agenttrace.agents.analysis.nodes.repository_synthesizer import repository_synthesizer


def test_repository_synthesizer_marks_required_task_insufficient():
    state = {
        "analysis_plan": {"tasks": [{"task_id": "task-1", "required": True}]},
        "task_results": [{"task_id": "task-1", "status": "INSUFFICIENT_EVIDENCE", "claim_verdicts": [], "evidence_signal_ids": [], "limitations": ["no source"]}],
        "analysis_limitations": {"missing_inputs": ["source_files"], "truncated_inputs": [], "notes": []},
    }
    result = repository_synthesizer(state)

    assert result["synthesis"]["analysis_status"] == "insufficient_evidence"


def test_finalize_analysis_builds_schema_valid_result():
    state = {
        "synthesis": {"analysis_status": "insufficient_evidence", "agent_type": "Unknown", "tech_stack_summary": {"ko": "미확인", "en": "Unknown"}},
        "claims": [],
        "evidence_signals": [],
        "task_results": [],
        "risk_signals": [],
        "follow_up_guide": {"ko": "README를 확인하세요.", "en": "Check README."},
        "analysis_limitations": {"missing_inputs": ["source_files"], "truncated_inputs": [], "notes": ["limited"]},
    }
    result = finalize_analysis(state)

    assert result["final_result"]["analysis_status"] == "insufficient_evidence"
    assert quality_gate({**state, **result})["quality_gate_result"]["critical_errors"] == []
```

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest tests/test_analysis_v2_nodes.py::test_repository_synthesizer_marks_required_task_insufficient tests/test_analysis_v2_nodes.py::test_finalize_analysis_builds_schema_valid_result -v`

Expected: FAIL with missing nodes.

- [ ] **Step 3: Implement synthesis/finalization**

Rules:
- any required task with `INSUFFICIENT_EVIDENCE` gives `insufficient_evidence`;
- all required tasks resolved with optional limitations gives `completed_with_limitations`;
- all tasks resolved gives `completed`;
- no claims but analyzable input gives `uncertain_classification`;
- quality critical errors include invalid schema, nonexistent claim ids, nonexistent evidence ids, missing required task result, and completed status with insufficient required task.

- [ ] **Step 4: Run finalization tests**

Run: `pytest tests/test_analysis_v2_nodes.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/agenttrace/agents/analysis/nodes/repository_synthesizer.py src/agenttrace/agents/analysis/nodes/finalize_analysis.py src/agenttrace/agents/analysis/nodes/result_repair.py src/agenttrace/agents/analysis/nodes/targeted_evidence_repair.py src/agenttrace/agents/analysis/nodes/critical_error_handler.py src/agenttrace/agents/analysis/nodes/risk_and_followup.py src/agenttrace/agents/analysis/nodes/quality_gate.py src/agenttrace/agents/analysis/nodes/persist_analysis.py tests/test_analysis_v2_nodes.py
git commit -m "feat: add analysis finalization contract"
```

### Task 8: Wire LangGraph and API Contract

**Files:**
- Modify: `src/agenttrace/agents/analysis/graph.py`
- Modify: `src/agenttrace/api/analysis.py`
- Create: `tests/test_analysis_v2_graph.py`
- Modify: `tests/test_api_analysis.py`

- [ ] **Step 1: Write failing graph test**

```python
from uuid import uuid4

from agenttrace.agents.analysis.graph import build_graph


def test_analysis_v2_graph_limited_path_completes_with_insufficient_evidence():
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
            }
        }
    )

    assert result["final_result"]["analysis_status"] in {"insufficient_evidence", "completed_with_limitations"}
    assert result["callback_payload"]["analysis_result"]["analysis_limitations"]["missing_inputs"]
```

- [ ] **Step 2: Write failing API contract test**

```python
from uuid import uuid4

from fastapi.testclient import TestClient

from agenttrace.app import create_app


def test_analysis_api_accepts_v2_backend_payload(monkeypatch):
    captured = {}

    async def fake_run(req):
        captured["req"] = req

    monkeypatch.setattr("agenttrace.api.analysis.run_pipeline_async", fake_run)
    client = TestClient(create_app())

    response = client.post(
        "/api/v1/analysis",
        json={
            "analysis_id": str(uuid4()),
            "repository": {"full_name": "owner/repo", "github_url": "https://github.com/owner/repo"},
            "snapshot": {"snapshot_id": "snap-1"},
            "readme_text": "# Repo",
            "file_tree": ["README.md"],
            "external_ingest": {"enabled": False, "provider": "gitingest"},
        },
    )

    assert response.status_code == 202
    assert captured["req"].repository.full_name == "owner/repo"
```

- [ ] **Step 3: Run graph/API tests and verify failure**

Run: `pytest tests/test_analysis_v2_graph.py tests/test_api_analysis.py -v`

Expected: FAIL until graph and API are rewired.

- [ ] **Step 4: Wire graph**

Graph routing:
- `START -> collect_inputs -> content_preprocessor -> analysis_precheck`
- if `can_analyze=false`: `critical_error_handler -> persist_failure -> END`
- if analyzable: `claim_analyzer -> analysis_planner -> select_next_task`
- loop while `current_task_id` exists through evidence nodes and `finalize_task`
- when no next task: `repository_synthesizer -> risk_and_followup -> finalize_analysis -> quality_gate`
- critical quality error: `critical_error_handler -> persist_failure`
- otherwise: `persist_analysis -> END`

- [ ] **Step 5: Update API**

Use `AnalysisInputRequest` as request model. Keep backwards compatibility by converting old payloads that include `repo_url` or `ingest_api_url` into the new request shape before graph invocation.

- [ ] **Step 6: Run graph/API tests**

Run: `pytest tests/test_analysis_v2_graph.py tests/test_api_analysis.py -v`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/agenttrace/agents/analysis/graph.py src/agenttrace/api/analysis.py tests/test_analysis_v2_graph.py tests/test_api_analysis.py
git commit -m "feat: wire analysis v2 graph"
```

### Task 9: Preserve Existing Harness/Summary Tests and Run Full Verification

**Files:**
- Modify: `tests/test_harness_analysis.py`
- Modify: `tests/test_nodes.py` if old node names need compatibility wrappers
- Modify: `src/agenttrace/agents/analysis/nodes/analyzer.py` only if keeping a compatibility import is simpler

- [ ] **Step 1: Run impacted existing tests**

Run:

```bash
pytest tests/test_harness_analysis.py tests/test_nodes.py tests/test_summary_service.py tests/test_summary_api.py -v
```

Expected: failures only where old analysis graph or node shapes changed.

- [ ] **Step 2: Add compatibility wrappers or update tests**

If existing imports require old names, keep wrappers:

```python
# src/agenttrace/agents/analysis/nodes/analyzer.py
from agenttrace.agents.analysis.nodes.claim_analyzer import claim_analyzer as analyzer
```

Update expected persisted payloads to use `analysis_result`, `evidence_task_results`, and limitations.

- [ ] **Step 3: Run focused test set**

Run:

```bash
pytest tests/test_analysis_v2_schemas.py tests/test_analysis_input_providers.py tests/test_gitingest_parser.py tests/test_analysis_chunking.py tests/test_analysis_v2_nodes.py tests/test_analysis_v2_graph.py tests/test_api_analysis.py tests/test_harness_analysis.py -v
```

Expected: PASS.

- [ ] **Step 4: Run full test suite**

Run: `pytest -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/agenttrace/agents/analysis tests
git commit -m "test: align analysis v2 compatibility"
```

## Self-Review Checklist

- Spec coverage: provider input, gitingest fallback, limited results, chunks, task loop, quality gate, callback payload, trace, migration path covered.
- Test-first coverage: every new unit has a failing-test step before implementation.
- No full source persistence: output contract stores excerpt/hash/path/chunk id only.
- Backend boundary: repository persistence remains outside AgentTrace.
- Deterministic tests: gitingest fixture replaces live network calls.
- Status separation: Backend `failed` is not used for normal evidence shortage.
