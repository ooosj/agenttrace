from __future__ import annotations

from agenttrace.agents.analysis.state import AnalysisState

MAX_TASK_PART_CHARS = 30000


def request_builder(state: AnalysisState) -> AnalysisState:
    """ReAct 모드에서는 pass-through. 구조 지도는 search_attempt에 이미 있다."""
    task_id = state.get("current_task_id")

    # ReAct 모드: selected_chunks가 비어있으면 단일 파트 생성
    selected_chunks = state.get("selected_chunks", [])
    if not selected_chunks:
        return {
            "task_parts": [{
                "part_id": f"{task_id}-part-001",
                "task_id": task_id,
                "chunks": [],
                "char_count": 0,
            }]
        }

    # 기존 모드: 청크가 있으면 분할 (하위 호환성)
    parts: list[dict] = []
    current_chunks: list[dict] = []
    current_count = 0

    for chunk in selected_chunks:
        content_len = chunk.get("end_byte", 0) - chunk.get("start_byte", 0)
        if content_len <= 0:
            content_len = len(chunk.get("content", "") or "")

        if current_chunks and current_count + content_len > MAX_TASK_PART_CHARS:
            parts.append({
                "part_id": f"{task_id}-part-{len(parts) + 1:03d}",
                "task_id": task_id,
                "chunks": [item["chunk_id"] for item in current_chunks],
                "char_count": current_count,
            })
            current_chunks = []
            current_count = 0
        current_chunks.append(chunk)
        current_count += content_len

    if current_chunks:
        parts.append({
            "part_id": f"{task_id}-part-{len(parts) + 1:03d}",
            "task_id": task_id,
            "chunks": [item["chunk_id"] for item in current_chunks],
            "char_count": current_count,
        })

    return {"task_parts": parts}
