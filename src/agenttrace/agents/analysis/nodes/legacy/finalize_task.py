from __future__ import annotations

from agenttrace.agents.analysis.state import AnalysisState


def finalize_task(state: AnalysisState) -> AnalysisState:
    task_result = state.get("pending_task_result")
    if not task_result:
        return {}

    task_traces = list(state.get("task_traces", []))
    task_traces.append({
        "task_id": task_result["task_id"],
        "required": _is_required(state, task_result["task_id"]),
        "search_attempts": [state.get("search_attempt", {})],
        "task_parts": state.get("task_parts", []),
        "task_result": task_result,
    })

    return {
        "task_results": [*state.get("task_results", []), task_result],
        "evidence_signals": state.get("pending_evidence_signals", []),
        "task_traces": task_traces,
        "current_task_id": "",
    }


def _is_required(state: AnalysisState, task_id: str) -> bool:
    for task in state.get("analysis_plan", {}).get("tasks", []):
        if task.get("task_id") == task_id:
            return bool(task.get("required"))
    return False
