from __future__ import annotations

import re
import time

from agenttrace.agents.analysis.state import AnalysisState
from agenttrace.logging_config import get_logger

logger = get_logger(__name__)



def _current_task(state: AnalysisState) -> dict | None:
    current_task_id = state.get("current_task_id")
    for task in state.get("analysis_plan", {}).get("tasks", []):
        if task.get("task_id") == current_task_id:
            return task
    return None


def _claim_texts(state: AnalysisState, task: dict) -> list[str]:
    wanted = set(task.get("claims", []))
    return [
        claim.get("claim_text", "")
        for claim in state.get("claims", [])
        if claim.get("claim_id") in wanted
    ]


def _tokens(text: str) -> set[str]:
    return {token.lower() for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", text)}


def evidence_scout(state: AnalysisState) -> AnalysisState:
    _t = time.perf_counter()
    run_id = state.get("run_id", "-")
    task_id = state.get("current_task_id", "-")
    log = logger.bind(node="evidence_scout", run_id=run_id, task_id=task_id)
    log.info("시작")
    task = _current_task(state)

    if not task:
        log.warning("현재 태스크 없음 — analysis_plan이 올바르게 생성됐는지 확인하세요",
                    duration_ms=int((time.perf_counter() - _t) * 1000))
        return {"selected_chunks": [], "search_attempt": {}}

    chunk_index = state.get("chunk_index", {})
    target_paths = {path.lower() for path in task.get("target_paths", [])}
    query_tokens = set()
    for text in _claim_texts(state, task):
        query_tokens.update(_tokens(text))

    chunks_by_id = chunk_index.get("chunks_by_id", {})
    
    # Filter chunks that belong to the target paths
    selected_chunks = []
    selected_ids = []
    for cid, chunk in chunks_by_id.items():
        if chunk.get("file_path", "").lower() in target_paths:
            selected_chunks.append(chunk)
            selected_ids.append(cid)
            
    # Fallback 1: if no chunks matched the target paths, select chunks that match query tokens
    if not selected_chunks:
        for cid, chunk in chunks_by_id.items():
            # Build simple text representation of chunk (e.g. file path + keywords or content)
            chunk_tokens = _tokens(f"{chunk.get('file_path', '')} {chunk.get('content_hash', '')}")
            if query_tokens & chunk_tokens:
                selected_chunks.append(chunk)
                selected_ids.append(cid)

    # Fallback 2: if still empty, select first 20 chunks to prevent empty analysis
    if not selected_chunks:
        first_keys = list(chunks_by_id.keys())[:20]
        selected_chunks = [chunks_by_id[k] for k in first_keys]
        selected_ids = first_keys

    attempt = {
        "attempt": 1,
        "queries": sorted(query_tokens)[:20],
        "candidate_chunk_ids": list(chunks_by_id.keys()),
        "selected_chunk_ids": selected_ids,
        "excluded_chunk_ids": [cid for cid in chunks_by_id if cid not in selected_ids],
        "exclusion_reasons": {},
    }

    log.info("완료", selected_chunks=len(selected_chunks), duration_ms=int((time.perf_counter() - _t) * 1000))
    return {
        "selected_chunks": selected_chunks,
        "search_attempt": attempt,
    }


