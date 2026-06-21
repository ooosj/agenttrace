# Design Spec: Separation of Analysis and Summary Models

**Date**: 2026-06-21  
**Status**: APPROVED  
**Author**: Antigravity

---

## 1. Background & Goals
Currently, AgentTrace uses a single environment variable `AGENTTRACE_SUMMARY_MODEL` (configured via `Settings.summary_model`) for both:
1. **Repository Analysis Pipeline** (`agenttrace.agents.analysis` graph)
2. **Repository Summary Generation Pipeline** (`agenttrace.agents.summary`)

To enable users to optimize API credit usage (e.g., using a high-cost/high-fidelity model for complex code analysis, but a low-cost model for summary generation, or vice versa), we must decouple these models. 

This spec details the design for:
- Splitting the model configuration into `AGENTTRACE_ANALYSIS_MODEL` and `AGENTTRACE_SUMMARY_MODEL`.
- Providing independent default values (`gpt-4o-mini`) for both when they are not configured.

---

## 2. Proposed Changes

### A. Settings Layer Extension
File: [config.py](file:///Users/wolyong/workspace/AgentHub/agenttrace/src/agenttrace/config.py)

- Add a new attribute `analysis_model` to the `Settings` class:
  ```python
  analysis_model: str = "gpt-4o-mini"
  ```
- Load `analysis_model` from the `AGENTTRACE_ANALYSIS_MODEL` environment variable. If not found in environment or `.env` file, default to `"gpt-4o-mini"`:
  ```python
  analysis_model=_get_env("AGENTTRACE_ANALYSIS_MODEL", env_values, "gpt-4o-mini")
  ```

### B. Model Factory Addition
File: [models.py](file:///Users/wolyong/workspace/AgentHub/agenttrace/src/agenttrace/models.py)

- Add a new model constructor function `build_openai_analysis_model() -> Any`:
  ```python
  def build_openai_analysis_model() -> Any:
      settings = get_settings()
      if not settings.openai_api_key:
          raise MissingSummaryModelError("OPENAI_API_KEY is required for analysis generation.")
      
      try:
          from langchain_openai import ChatOpenAI
      except ImportError as exc:
          raise MissingSummaryModelError(
              "langchain-openai is required for OpenAI analysis generation."
          ) from exc

      kwargs = {
          "model": settings.analysis_model,
          "api_key": settings.openai_api_key,
          "temperature": 0,
      }
      if settings.openai_api_base:
          kwargs["base_url"] = settings.openai_api_base

      return ChatOpenAI(**kwargs)
  ```

### C. Analysis Graph Nodes Update
Files:
- [analyzer.py](file:///Users/wolyong/workspace/AgentHub/agenttrace/src/agenttrace/agents/analysis/nodes/analyzer.py)
- [evidence_evaluator.py](file:///Users/wolyong/workspace/AgentHub/agenttrace/src/agenttrace/agents/analysis/nodes/evidence_evaluator.py)

- Change the import to:
  ```python
  from agenttrace.models import build_openai_analysis_model
  ```
- Instantiate the model using `build_openai_analysis_model()`:
  ```python
  model = build_openai_analysis_model()
  ```

### D. Environment Setup Configuration
Files:
- [.env](file:///Users/wolyong/workspace/AgentHub/agenttrace/.env)
- [.env.example](file:///Users/wolyong/workspace/AgentHub/agenttrace/.env.example)

- Append the new variable:
  ```env
  AGENTTRACE_ANALYSIS_MODEL=gpt-4o-mini
  ```

---

## 3. Testing & Verification

### Unit/Integration Tests
File: [test_summary_service.py](file:///Users/wolyong/workspace/AgentHub/agenttrace/tests/test_summary_service.py)

- Add a new test case checking that:
  - `AGENTTRACE_ANALYSIS_MODEL` is parsed correctly.
  - `AGENTTRACE_SUMMARY_MODEL` is parsed correctly.
  - `build_openai_analysis_model()` uses the configuration from `Settings.analysis_model`.
  - Changing one does not affect the other.

### CLI/Graph Verification
- Run `uv run pytest` to ensure all existing and new tests pass successfully.
