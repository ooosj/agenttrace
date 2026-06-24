from __future__ import annotations

import time

from agenttrace.agents.analysis.state import AnalysisState
from agenttrace.logging_config import get_logger

logger = get_logger(__name__)


def select_next_task(state: AnalysisState) -> AnalysisState:
    _t = time.perf_counter()
    run_id = state.get("run_id", "-")
    log = logger.bind(node="select_next_task", run_id=run_id)
    log.info("시작")

    completed = {result.get("task_id") for result in state.get("task_results", [])}
    next_task_id = ""

    for task in state.get("analysis_plan", {}).get("tasks", []):
        if task.get("task_id") not in completed:
            next_task_id = task["task_id"]
            break

    duration_ms = int((time.perf_counter() - _t) * 1000)
    if next_task_id:
        log.info("완료", next_task_id=next_task_id, completed_count=len(completed), duration_ms=duration_ms)
        return {
            "current_task_id": next_task_id,
            "next_task_id": next_task_id,
        }

    log.info("완료", next_task_id="", completed_count=len(completed), duration_ms=duration_ms)
    return {
        "current_task_id": "",
        "next_task_id": "",
    }
