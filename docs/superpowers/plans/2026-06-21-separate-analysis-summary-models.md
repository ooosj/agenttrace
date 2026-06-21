# Separate Analysis and Summary Models Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Decouple model configuration into separate `AGENTTRACE_ANALYSIS_MODEL` and `AGENTTRACE_SUMMARY_MODEL` variables, ensuring that both have their own defaults (`gpt-4o-mini`) and are instantiated correctly in their respective pipelines.

**Architecture:** 
1. Update `Settings` to parse and store `analysis_model`.
2. Add `build_openai_analysis_model()` in `models.py`.
3. Update Claim Extraction and Evidence Evaluation nodes to use the new analysis model.
4. Verify via unit tests.

**Tech Stack:** Python, LangChain, Pytest

---

### Task 1: Create failing unit tests for new Settings and Model Factory

**Files:**
- Create: `tests/test_analysis_model.py`

- [ ] **Step 1: Write the failing tests**
  Create the test file `tests/test_analysis_model.py` containing:
  ```python
  import pytest
  from agenttrace.config import get_settings, Settings
  from agenttrace.models import build_openai_analysis_model

  def test_analysis_model_settings_defaults(monkeypatch):
      # Clear env to test defaults
      monkeypatch.delenv("AGENTTRACE_ANALYSIS_MODEL", raising=False)
      monkeypatch.delenv("AGENTTRACE_SUMMARY_MODEL", raising=False)
      
      # Clear settings cache
      get_settings.cache_clear()
      
      settings = get_settings()
      assert settings.analysis_model == "gpt-4o-mini"
      assert settings.summary_model == "gpt-4o-mini"

  def test_analysis_model_settings_explicit(monkeypatch):
      monkeypatch.setenv("AGENTTRACE_ANALYSIS_MODEL", "gpt-4o-analysis-test")
      monkeypatch.setenv("AGENTTRACE_SUMMARY_MODEL", "gpt-4o-summary-test")
      
      get_settings.cache_clear()
      
      settings = get_settings()
      assert settings.analysis_model == "gpt-4o-analysis-test"
      assert settings.summary_model == "gpt-4o-summary-test"

  def test_build_openai_analysis_model(monkeypatch):
      monkeypatch.setenv("OPENAI_API_KEY", "test-api-key")
      monkeypatch.setenv("AGENTTRACE_ANALYSIS_MODEL", "gpt-4o-analysis-build-test")
      
      get_settings.cache_clear()
      
      model = build_openai_analysis_model()
      assert model.model_name == "gpt-4o-analysis-build-test"
  ```

- [ ] **Step 2: Run tests to verify they fail**
  Run: `uv run pytest tests/test_analysis_model.py`
  Expected: FAIL (ImportError for `build_openai_analysis_model` or AttributeError for `analysis_model` in Settings).

- [ ] **Step 3: Commit**
  ```bash
  git add tests/test_analysis_model.py
  git commit -m "test: add unit tests for separate analysis and summary models"
  ```

---

### Task 2: Implement Settings Loading for analysis_model

**Files:**
- Modify: `src/agenttrace/config.py`

- [ ] **Step 1: Add analysis_model to Settings dataclass**
  Modify `src/agenttrace/config.py` to add `analysis_model: str = "gpt-4o-mini"` to the `Settings` class:
  ```python
  @dataclass(frozen=True)
  class Settings:
      service_name: str = "agenttrace-ai"
      summary_model: str = "gpt-4o-mini"
      analysis_model: str = "gpt-4o-mini"
      # ...
  ```

- [ ] **Step 2: Load analysis_model in get_settings()**
  Modify the `get_settings()` function to parse `AGENTTRACE_ANALYSIS_MODEL` with default `gpt-4o-mini`:
  ```python
  @lru_cache()
  def get_settings() -> Settings:
      env_values = _load_dotenv(Path(".env"))
      return Settings(
          service_name=_get_env("AGENTTRACE_SERVICE_NAME", env_values, "agenttrace-ai"),
          summary_model=_get_env("AGENTTRACE_SUMMARY_MODEL", env_values, "gpt-4o-mini"),
          analysis_model=_get_env("AGENTTRACE_ANALYSIS_MODEL", env_values, "gpt-4o-mini"),
          # ...
  ```

- [ ] **Step 3: Run settings tests to verify partial success**
  Run: `uv run pytest tests/test_analysis_model.py -k "settings"`
  Expected: Settings tests should pass; `build_openai_analysis_model` test should still fail.

- [ ] **Step 4: Commit**
  ```bash
  git add src/agenttrace/config.py
  git commit -m "feat: parse AGENTTRACE_ANALYSIS_MODEL in settings"
  ```

---

### Task 3: Implement build_openai_analysis_model Factory

**Files:**
- Modify: `src/agenttrace/models.py`

- [ ] **Step 1: Define build_openai_analysis_model**
  Add the implementation to `src/agenttrace/models.py`:
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

- [ ] **Step 2: Run all Task 1 tests to verify they pass**
  Run: `uv run pytest tests/test_analysis_model.py`
  Expected: PASS

- [ ] **Step 3: Commit**
  ```bash
  git add src/agenttrace/models.py
  git commit -m "feat: implement build_openai_analysis_model factory"
  ```

---

### Task 4: Integrate build_openai_analysis_model into Analysis Nodes

**Files:**
- Modify: `src/agenttrace/agents/analysis/nodes/analyzer.py`
- Modify: `src/agenttrace/agents/analysis/nodes/evidence_evaluator.py`

- [ ] **Step 1: Update analyzer.py**
  Change the model factory import and instantiation in `src/agenttrace/agents/analysis/nodes/analyzer.py`:
  ```python
  # Change line 8 import:
  from agenttrace.models import build_openai_analysis_model
  
  # Change line 164 instantiation:
  model = build_openai_analysis_model()
  ```

- [ ] **Step 2: Update evidence_evaluator.py**
  Change the model factory import and instantiation in `src/agenttrace/agents/analysis/nodes/evidence_evaluator.py`:
  ```python
  # Change line 10 import:
  from agenttrace.models import build_openai_analysis_model
  
  # Change line 209 instantiation:
  model = build_openai_analysis_model()
  ```

- [ ] **Step 3: Run existing analysis tests**
  Run: `uv run pytest tests/test_analysis_v2_nodes.py tests/test_analysis_v2_graph.py`
  Expected: PASS

- [ ] **Step 4: Commit**
  ```bash
  git add src/agenttrace/agents/analysis/nodes/analyzer.py src/agenttrace/agents/analysis/nodes/evidence_evaluator.py
  git commit -m "refactor: use build_openai_analysis_model in analysis nodes"
  ```

---

### Task 5: Update Env Configuration files

**Files:**
- Modify: `.env`
- Modify: `.env.example`

- [ ] **Step 1: Update .env.example**
  Add `AGENTTRACE_ANALYSIS_MODEL=gpt-4o-mini` to `.env.example`:
  ```env
  AGENTTRACE_SERVICE_NAME=agenttrace-ai
  AGENTTRACE_SUMMARY_MODEL=gpt-4o-mini
  AGENTTRACE_ANALYSIS_MODEL=gpt-4o-mini
  ```

- [ ] **Step 2: Update .env**
  Add `AGENTTRACE_ANALYSIS_MODEL=gpt-4o-mini` to `.env`:
  ```env
  AGENTTRACE_SERVICE_NAME=agenttrace-ai
  AGENTTRACE_SUMMARY_MODEL=gpt-4o-mini
  AGENTTRACE_ANALYSIS_MODEL=gpt-4o-mini
  ```

- [ ] **Step 3: Commit**
  ```bash
  git add .env .env.example
  git commit -m "config: add AGENTTRACE_ANALYSIS_MODEL to env templates"
  ```

---

### Task 6: Final Verification

- [ ] **Step 1: Run full pytest suite**
  Run: `uv run pytest`
  Expected: All 112 passed tests.

- [ ] **Step 2: Verify git status is clean**
  Run: `git status`
  Expected: No unstaged or untracked changes (unless ignored).
