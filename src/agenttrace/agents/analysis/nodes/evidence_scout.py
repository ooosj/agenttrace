from __future__ import annotations

import re

from agenttrace.agents.analysis.state import AnalysisState


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
    task = _current_task(state)
    if not task:
        return _legacy_evidence_scout(state)

    chunk_index = state.get("chunk_index", {})
    entries = chunk_index.get("entries", [])
    target_paths = [path.lower() for path in task.get("target_paths", [])]
    query_tokens = set()
    for text in _claim_texts(state, task):
        query_tokens.update(_tokens(text))

    candidate_chunk_ids: list[str] = []
    selected_chunk_ids: list[str] = []
    excluded_chunk_ids: list[str] = []
    exclusion_reasons: dict[str, str] = {}

    for entry in entries:
        path = entry.get("file_path", "")
        path_lower = path.lower()
        chunk_ids = list(entry.get("chunk_ids", []))
        candidate_chunk_ids.extend(chunk_ids)
        path_match = any(target in path_lower for target in target_paths)
        keyword_match = bool(query_tokens & set(entry.get("keywords", [])))
        if path_match or keyword_match:
            selected_chunk_ids.extend(chunk_ids)
        else:
            excluded_chunk_ids.extend(chunk_ids)
            for chunk_id in chunk_ids:
                exclusion_reasons[chunk_id] = "path and keyword mismatch"

    chunks_by_id = chunk_index.get("chunks_by_id", {})
    selected_chunks = [
        chunks_by_id[chunk_id]
        for chunk_id in selected_chunk_ids[:8]
        if chunk_id in chunks_by_id
    ]
    attempt = {
        "attempt": 1,
        "queries": sorted(query_tokens)[:20],
        "candidate_chunk_ids": candidate_chunk_ids,
        "selected_chunk_ids": [chunk["chunk_id"] for chunk in selected_chunks],
        "excluded_chunk_ids": excluded_chunk_ids,
        "exclusion_reasons": exclusion_reasons,
    }

    return {
        "selected_chunks": selected_chunks,
        "search_attempt": attempt,
    }


def _legacy_evidence_scout(state: AnalysisState) -> AnalysisState:
    claims = state.get("claims", [])
    file_tree = state.get("file_tree", [])
    agent_type = state.get("agent_type", "")
    hints = {
        "MCP_SERVER": ["mcp", "server", "tool"],
        "SKILL": ["skill", "plugin", "workflow", "script"],
        "EVAL_HARNESS": ["eval", "harness", "test", "benchmark"],
        "AGENT_FRAMEWORK": ["agent", "workflow", "planner", "memory"],
    }.get(agent_type, ["agent", "tool", "skill", "plugin", "server", "workflow"])
    signals: list[dict] = []
    for claim in claims or [{"id": None, "claim_text": ""}]:
        claim_id = claim.get("id") or claim.get("claim_id")
        claim_tokens = _tokens(claim.get("claim_text", ""))
        per_claim = 0
        for item in file_tree:
            path = item.get("path", "") if isinstance(item, dict) else str(item)
            lower = path.lower()
            if not any(hint in lower for hint in hints) and not (claim_tokens & _tokens(path)):
                continue
            signals.append({
                "claim_id": claim_id,
                "signal_type": "FILE_PATH",
                "path": path,
                "summary": "claim과 연결된 파일 경로 근거",
                "confidence": 0.7,
            })
            per_claim += 1
            if per_claim >= 3:
                break
        if not any("plugin" in signal["path"].lower() for signal in signals if signal["claim_id"] == claim_id):
            for item in file_tree:
                path = item.get("path", "") if isinstance(item, dict) else str(item)
                if "plugin" not in path.lower():
                    continue
                signals.append({
                    "claim_id": claim_id,
                    "signal_type": "FILE_PATH",
                    "path": path,
                    "summary": "claim과 연결된 plugin 파일 경로 근거",
                    "confidence": 0.7,
                })
                break
    if not signals:
        return {
            "status": "INSUFFICIENT_EVIDENCE",
            "evidence_signals": [],
            "quality_warnings": ["README claim을 뒷받침할 파일 경로 근거가 부족합니다."],
        }
    return {"status": "COLLECTED", "evidence_signals": signals}
