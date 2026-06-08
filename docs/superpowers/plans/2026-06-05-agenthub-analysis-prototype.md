# AgentHub Analysis Prototype Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a CLI-only prototype that analyzes a fixed `obra/superpowers` repository snapshot and writes a JSON result that helps users decide what to inspect next.

**Architecture:** Keep the existing six-node LangGraph MVP. Improve snapshot fixture quality, classification heuristics, claim-to-evidence linking, action-oriented follow-up labels, and quality checks without adding live API calls.

**Tech Stack:** Python 3.10+, LangGraph, argparse CLI, JSON fixtures, pytest-compatible unit tests.

---

## File Structure

- Create `.gitignore`: keep `.env`, `.venv`, caches, generated output, and egg-info out of git.
- Create `.env.example`: document future API key names without real values.
- Create `data/superpowers_repo.json`: fixed `obra/superpowers` snapshot used by the prototype.
- Modify `agenthub_analysis/criteria/agent_type_keywords.py`: add stronger skill/plugin/framework hints and output label constants if needed.
- Modify `agenthub_analysis/nodes/analyzer.py`: improve type detection and README claim extraction.
- Modify `agenthub_analysis/nodes/evidence_scout.py`: link evidence to multiple claims using claim keywords and path signals.
- Modify `agenthub_analysis/nodes/risk_and_followup.py`: emit user-facing follow-up labels and static-analysis risk.
- Modify `agenthub_analysis/nodes/quality_gate.py`: block completed status when claims/evidence/actions are inconsistent.
- Modify `tests/test_nodes.py`: add tests for fixed snapshot classification, evidence linking, and quality blocking.

---

### Task 1: Repository Hygiene And Fixed Snapshot

**Files:**
- Create: `.gitignore`
- Create: `.env.example`
- Create: `data/superpowers_repo.json`

- [ ] **Step 1: Create `.gitignore`**

Write:

```gitignore
.env
.venv/
__pycache__/
*.py[cod]
.pytest_cache/
*.egg-info/
out/*.json
!out/.gitkeep
```

- [ ] **Step 2: Create `.env.example`**

Write:

```dotenv
# Fixed-snapshot prototype does not require secrets.
# Future live collectors or LLM analyzers should read keys from environment variables.
GITHUB_TOKEN=
OPENAI_API_KEY=
```

- [ ] **Step 3: Create fixed snapshot fixture**

Write `data/superpowers_repo.json` with this shape:

```json
{
  "repository_id": "github-obra-superpowers",
  "full_name": "obra/superpowers",
  "github_url": "https://github.com/obra/superpowers",
  "metadata": {
    "stars": 218000,
    "forks": 19400,
    "archived": false,
    "default_branch": "main",
    "language": "JavaScript",
    "license": "MIT"
  },
  "readme": "# Superpowers

Superpowers is a complete software development methodology for your coding agents.

It provides a complete agentic skills framework and methodology that helps coding agents plan, implement, review, and verify software changes.

The repository includes reusable skills, command hooks, plugin manifests, and installable integrations for multiple coding agent environments.

Core workflows include brainstorming, writing plans, test-driven development, systematic debugging, requesting code review, and verification before completion.

Plugins and skill files let different coding agents load the same workflow instructions across supported environments.

## Quickstart

Install the plugin for your coding agent, then use the included skills to guide development workflows.",
  "file_tree": [
    {"path": "README.md", "type": "file"},
    {"path": "skills/using-superpowers/SKILL.md", "type": "file"},
    {"path": "skills/brainstorming/SKILL.md", "type": "file"},
    {"path": "skills/writing-plans/SKILL.md", "type": "file"},
    {"path": "skills/test-driven-development/SKILL.md", "type": "file"},
    {"path": "skills/systematic-debugging/SKILL.md", "type": "file"},
    {"path": "skills/requesting-code-review/SKILL.md", "type": "file"},
    {"path": "skills/verification-before-completion/SKILL.md", "type": "file"},
    {"path": ".codex-plugin/plugin.json", "type": "file"},
    {"path": ".claude-plugin/plugin.json", "type": "file"},
    {"path": ".cursor-plugin", "type": "directory"},
    {"path": ".opencode", "type": "directory"},
    {"path": "hooks", "type": "directory"},
    {"path": "scripts/install.js", "type": "file"},
    {"path": "scripts/check-plugin.js", "type": "file"},
    {"path": "tests", "type": "directory"},
    {"path": "package.json", "type": "file"},
    {"path": "LICENSE", "type": "file"}
  ]
}
```

- [ ] **Step 4: Run fixture parse check**

Run:

```bash
python -m json.tool data/superpowers_repo.json >/tmp/superpowers_repo_check.json
```

Expected: exit code 0.

---

### Task 2: Classification And Claim Extraction

**Files:**
- Modify: `agenthub_analysis/criteria/agent_type_keywords.py`
- Modify: `agenthub_analysis/nodes/analyzer.py`
- Test: `tests/test_nodes.py`

- [ ] **Step 1: Add classification tests**

Append to `tests/test_nodes.py`:

```python
import json
from pathlib import Path


def test_analyzer_classifies_superpowers_as_skill():
    snapshot = json.loads(Path("data/superpowers_repo.json").read_text(encoding="utf-8"))
    state = {
        "status": "COLLECTED",
        "readme": snapshot["readme"],
        "file_tree": snapshot["file_tree"],
        "claims": [],
    }

    result = analyzer(state)

    assert result["agent_type"] == "SKILL"
    assert result["relevance_score"] >= 0.5
    assert len(result["claims"]) >= 3
    assert all(result_claim["claim_text"] != "Superpowers" for result_claim in result["claims"])
```

- [ ] **Step 2: Run test and confirm current failure**

Run:

```bash
python -m pytest tests/test_nodes.py::test_analyzer_classifies_superpowers_as_skill -q
```

Expected before implementation if pytest is installed: FAIL because current classifier may pick another type or weak claims. If pytest is not installed: `No module named pytest`; continue and verify with CLI smoke run later.

- [ ] **Step 3: Update skill and framework keywords**

In `agenthub_analysis/criteria/agent_type_keywords.py`, ensure `SKILL` includes:

```python
"skills/", "skill.md", "agentic skills", "reusable skills", "plugin", "plugin.json", "workflow instructions"
```

Ensure `AGENT_FRAMEWORK` includes:

```python
"coding agents", "methodology", "workflow", "plan", "review", "verify"
```

- [ ] **Step 4: Update analyzer heuristics**

In `agenthub_analysis/nodes/analyzer.py`:

- Score path hits and README hits separately.
- Prefer `SKILL` when `skills/` or `SKILL.md` appears in file paths.
- Skip claim candidates that are shorter than 24 characters after stripping markdown.
- Skip common headings: `Superpowers`, `Quickstart`, `Installation`, `Documentation`.
- Keep max 8 claims.

- [ ] **Step 5: Run classification test again**

Run:

```bash
python -m pytest tests/test_nodes.py::test_analyzer_classifies_superpowers_as_skill -q
```

Expected if pytest is installed: PASS.

---

### Task 3: Claim-To-Evidence Linking

**Files:**
- Modify: `agenthub_analysis/nodes/evidence_scout.py`
- Test: `tests/test_nodes.py`

- [ ] **Step 1: Add evidence linking test**

Append to `tests/test_nodes.py`:

```python

def test_evidence_scout_links_superpowers_evidence_to_multiple_claims():
    snapshot = json.loads(Path("data/superpowers_repo.json").read_text(encoding="utf-8"))
    analyzed = analyzer({
        "status": "COLLECTED",
        "readme": snapshot["readme"],
        "file_tree": snapshot["file_tree"],
        "claims": [],
    })
    result = evidence_scout({
        "agent_type": analyzed["agent_type"],
        "claims": analyzed["claims"],
        "file_tree": snapshot["file_tree"],
        "evidence_signals": [],
        "quality_warnings": [],
    })

    claim_ids = {signal["claim_id"] for signal in result["evidence_signals"] if signal.get("claim_id")}
    paths = {signal["path"] for signal in result["evidence_signals"]}

    assert len(claim_ids) > 1
    assert any(path.startswith("skills/") for path in paths)
    assert any("plugin" in path for path in paths)
```

- [ ] **Step 2: Run test and confirm current failure**

Run:

```bash
python -m pytest tests/test_nodes.py::test_evidence_scout_links_superpowers_evidence_to_multiple_claims -q
```

Expected before implementation if pytest is installed: FAIL because current scout links to the first claim only.

- [ ] **Step 3: Implement matching helpers**

In `agenthub_analysis/nodes/evidence_scout.py`, add helpers:

```python
def _path_signal_type(path: str, file_type: str | None = None) -> str:
    lower = path.lower()
    if file_type == "directory":
        return "DIRECTORY"
    if lower.endswith(("plugin.json", "mcp.json")) or "plugin" in lower:
        return "CONFIG"
    if "test" in lower:
        return "TEST"
    if lower.endswith(("readme.md", ".md")):
        return "DOC"
    if lower.endswith(("package.json", "pyproject.toml", "cargo.toml")):
        return "DEPENDENCY"
    return "FILE_PATH"


def _claim_keywords(claim_text: str) -> set[str]:
    lower = claim_text.lower()
    keywords = set()
    for token in ["skill", "skills", "plugin", "plugins", "hook", "hooks", "script", "scripts", "test", "tests", "workflow", "workflows", "plan", "debug", "review", "verify", "install"]:
        if token in lower:
            keywords.add(token.rstrip("s"))
    return keywords
```

- [ ] **Step 4: Link evidence to each claim**

Replace current first-claim assignment with per-claim matching:

```python
for claim in claims:
    claim_id = claim.get("id")
    claim_terms = _claim_keywords(claim.get("claim_text", ""))
    for file_info in file_tree:
        path = file_info.get("path", "")
        lower_path = path.lower()
        matched_hints = [hint for hint in hints if hint.lower() in lower_path]
        matched_terms = [term for term in claim_terms if term in lower_path]
        if not matched_hints and not matched_terms:
            continue
        evidence_signals.append({
            "claim_id": claim_id,
            "signal_type": _path_signal_type(path, file_info.get("type")),
            "path": path,
            "summary": f"{agent_type} claim과 관련된 정적 repo 신호: {path}",
            "confidence": min(0.45 + 0.1 * len(matched_hints) + 0.1 * len(matched_terms), 0.9),
        })
```

Deduplicate by `(claim_id, path)` and cap to 16 signals.

- [ ] **Step 5: Run evidence test again**

Run:

```bash
python -m pytest tests/test_nodes.py::test_evidence_scout_links_superpowers_evidence_to_multiple_claims -q
```

Expected if pytest is installed: PASS.

---

### Task 4: Action-Oriented Risk And Follow-Up

**Files:**
- Modify: `agenthub_analysis/nodes/risk_and_followup.py`
- Test: `tests/test_nodes.py`

- [ ] **Step 1: Add follow-up action test**

Append to `tests/test_nodes.py`:

```python
from agenthub_analysis.nodes.risk_and_followup import risk_and_followup_planner


def test_superpowers_followup_actions_are_user_action_labels():
    snapshot = json.loads(Path("data/superpowers_repo.json").read_text(encoding="utf-8"))
    analyzed = analyzer({
        "status": "COLLECTED",
        "readme": snapshot["readme"],
        "file_tree": snapshot["file_tree"],
        "claims": [],
    })
    evidence = evidence_scout({
        "agent_type": analyzed["agent_type"],
        "claims": analyzed["claims"],
        "file_tree": snapshot["file_tree"],
        "evidence_signals": [],
        "quality_warnings": [],
    })
    result = risk_and_followup_planner({
        "metadata": snapshot["metadata"],
        "readme": snapshot["readme"],
        "claims": analyzed["claims"],
        "evidence_signals": evidence["evidence_signals"],
        "file_tree": snapshot["file_tree"],
    })

    actions = {action["action"] for action in result["followup_actions"]}
    risk_types = {risk["risk_type"] for risk in result["risk_signals"]}

    assert "READ_NOW" in actions
    assert "INSPECT_STRUCTURE" in actions
    assert "ANALYSIS_UNCERTAIN" in risk_types
```

- [ ] **Step 2: Run test and confirm current failure**

Run:

```bash
python -m pytest tests/test_nodes.py::test_superpowers_followup_actions_are_user_action_labels -q
```

Expected before implementation if pytest is installed: FAIL because current labels are internal labels.

- [ ] **Step 3: Update planner output**

In `agenthub_analysis/nodes/risk_and_followup.py`:

- Always add low severity `ANALYSIS_UNCERTAIN` for static-only analysis.
- Use `READ_NOW` when claims and evidence exist.
- Use `INSPECT_STRUCTURE` for top evidence directories/configs.
- Use `TRY_EXAMPLE` when `examples`, `scripts`, `install`, or `package.json` appears.
- Use `READ_WITH_CAUTION` for high severity risk or no evidence.

- [ ] **Step 4: Run follow-up test again**

Run:

```bash
python -m pytest tests/test_nodes.py::test_superpowers_followup_actions_are_user_action_labels -q
```

Expected if pytest is installed: PASS.

---

### Task 5: Quality Gate Strengthening And CLI Smoke Run

**Files:**
- Modify: `agenthub_analysis/nodes/quality_gate.py`
- Test: `tests/test_nodes.py`
- Generate: `out/superpowers_analysis.json`

- [ ] **Step 1: Add quality blocking test**

Append to `tests/test_nodes.py`:

```python
from agenthub_analysis.nodes.quality_gate import quality_gate


def test_quality_gate_blocks_completed_without_evidence_for_claims():
    result = quality_gate({
        "status": "COLLECTED",
        "agent_type": "SKILL",
        "claims": [{
            "id": "claim-1",
            "claim_text": "This repository provides reusable skills.",
            "source": "README.md",
        }],
        "evidence_signals": [],
        "risk_signals": [],
        "followup_actions": [],
    })

    assert result["status"] == "NEEDS_HUMAN_REVIEW"
    assert result["quality_errors"]
```

- [ ] **Step 2: Run test and confirm current failure**

Run:

```bash
python -m pytest tests/test_nodes.py::test_quality_gate_blocks_completed_without_evidence_for_claims -q
```

Expected before implementation if pytest is installed: FAIL because current gate may mark completed.

- [ ] **Step 3: Update quality gate checks**

In `agenthub_analysis/nodes/quality_gate.py`:

- Build set of claim IDs with evidence.
- If status is not `OUT_OF_SCOPE`, require follow-up actions.
- If status would become `COMPLETED`, require at least one evidence signal.
- If status would become `COMPLETED`, require each claim ID to have linked evidence.
- Return `NEEDS_HUMAN_REVIEW` with errors when requirements fail.

- [ ] **Step 4: Run available tests**

Run:

```bash
python -m pytest -q
```

Expected if pytest is installed: PASS. If pytest is missing, record exact error and continue with CLI smoke run.

- [ ] **Step 5: Run CLI smoke test**

Run:

```bash
python -m agenthub_analysis.cli data/superpowers_repo.json --out out/superpowers_analysis.json
```

Expected:

- exits 0
- writes `out/superpowers_analysis.json`
- printed JSON has `status` `COMPLETED` or `UNCERTAIN`
- printed JSON has `agent_type` `SKILL`
- `followup_actions` include `READ_NOW` and `INSPECT_STRUCTURE`
- `risk_signals` include `ANALYSIS_UNCERTAIN`

- [ ] **Step 6: Inspect generated JSON**

Run:

```bash
python -m json.tool out/superpowers_analysis.json | sed -n '1,220p'
```

Expected: JSON is parseable and includes multiple claims, multiple evidence paths, and user-facing action labels.

---

## Plan Self-Review

- Spec coverage: fixed snapshot, CLI-only output, claim/evidence/action/risk improvements, `.env` policy, and smoke verification are covered.
- Placeholder scan: no TBD/TODO/fill-in-later steps remain.
- Type consistency: uses existing state keys and current snake_case output fields.
- Scope: no live GitHub collector, DB, HTML report, runtime execution, security audit, or AST analysis.
