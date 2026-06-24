import time

from agenttrace.agents.analysis.criteria.harness_capabilities import (
    CORE_HIGH_RELEVANCE_CAPABILITIES,
    HARNESS_CAPABILITY_CRITERIA,
    HARNESS_CAPABILITY_NAMES,
)
from agenttrace.agents.analysis.state import AnalysisState
from agenttrace.logging_config import get_logger

logger = get_logger(__name__)


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
    from pathlib import Path
    local_repo_dir_str = state.get("local_repo_dir")
    local_repo_dir = Path(local_repo_dir_str) if local_repo_dir_str else None

    selected: list[tuple[str, str]] = []
    for item in state.get("selected_files", []):
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "")
        content = str(item.get("content") or item.get("text") or "")
        if not content and local_repo_dir and path:
            try:
                resolved_base = local_repo_dir.resolve()
                resolved_target = (local_repo_dir / path).resolve()
                if not resolved_target.is_relative_to(resolved_base):
                    raise ValueError(f"Path traversal detected: {path}")
                file_path = local_repo_dir / path
                if file_path.exists():
                    content = file_path.read_text(encoding="utf-8", errors="ignore")
            except Exception as exc:
                if "Path traversal detected" in str(exc):
                    raise
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


EXPLICIT_HARNESS_README_PHRASES = [
    "agent harness",
    "coding agent",
    "agent loop",
    "autonomous coding",
    "tool registry",
    "sandboxed workspace",
]


def _strong_harness_path_capabilities(paths: list[str]) -> set[str]:
    strong: set[str] = set()
    for path in paths:
        lowered = path.lower()
        parts = [part for part in lowered.replace("\\", "/").split("/") if part]
        filename = parts[-1] if parts else ""
        parent = parts[-2] if len(parts) > 1 else ""

        if "agent_loop" in parts or filename.startswith("agent_loop."):
            strong.add("agent_loop")
        if "tool_registry" in parts or (parent == "tools" and filename.startswith("registry.")):
            strong.add("tool_system")
        if "sandbox" in parts or filename.startswith("sandbox."):
            strong.add("sandbox_or_workspace")
        if parent == "permissions" and filename.startswith("policy."):
            strong.add("permission_control")
        if parent == "memory" and filename.startswith("context."):
            strong.add("memory_or_context_management")
    return strong


def _level_for(
    present_capabilities: set[str],
    readme_mentions_harness: bool,
    has_source_code_evidence: bool,
    has_explicit_harness_readme: bool,
    strong_path_capabilities: set[str],
) -> tuple[str, str]:
    core_hits = present_capabilities & CORE_HIGH_RELEVANCE_CAPABILITIES
    has_strong_harness_evidence = (
        has_source_code_evidence
        or len(strong_path_capabilities) >= 2
    )
    if (
        {"agent_loop", "tool_system"} <= present_capabilities
        and len(core_hits) >= 3
        and (has_source_code_evidence or has_explicit_harness_readme)
        and has_strong_harness_evidence
    ):
        return "high", "high"
    if "tool_system" in present_capabilities or "skill_system" in present_capabilities:
        return "medium", "medium"
    if present_capabilities or readme_mentions_harness:
        return "low", "low"
    return "none", "medium"


def harness_analyzer(state: AnalysisState) -> AnalysisState:
    _t = time.perf_counter()
    run_id = state.get("run_id", "-")
    log = logger.bind(node="harness_analyzer", run_id=run_id)
    log.info("시작")
    paths = _path_text(state)
    sources = _selected_source_text(state)
    readme = state.get("readme", "")
    readme_lower = readme.lower()
    readme_mentions_harness = any(
        word in readme_lower
        for word in ["agent", "harness", "tool", "sandbox", "permission", "skill", "mcp"]
    )
    has_explicit_harness_readme = any(
        phrase in readme_lower for phrase in EXPLICIT_HARNESS_README_PHRASES
    )

    capabilities: dict[str, dict] = {}
    evidence: list[dict] = []
    present_capabilities: set[str] = set()
    has_source_code_evidence = False
    strong_path_capabilities = _strong_harness_path_capabilities(paths)

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
            evidence_type = _evidence_type(path)
            summary = f"Static path signal supports {name}: {path}"
            evidence.append(
                {
                    "type": evidence_type,
                    "location": path,
                    "summary": summary,
                    "supports": [name],
                }
            )
            capability_evidence.append(summary)
        for path in code_hits[:2]:
            has_source_code_evidence = True
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

    level, confidence = _level_for(
        present_capabilities,
        readme_mentions_harness,
        has_source_code_evidence,
        has_explicit_harness_readme,
        strong_path_capabilities,
    )
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

    log.info("완료", level=level, confidence=confidence, evidence_count=len(evidence), duration_ms=int((time.perf_counter() - _t) * 1000))
    return {
        "harness_relevance": harness_relevance,
        "harness_capabilities": capabilities,
        "negative_evidence": negative_evidence,
        "followup_questions": followup_questions,
    }
