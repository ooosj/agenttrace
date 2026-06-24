from __future__ import annotations

from typing import Protocol

from agenttrace.agents.analysis.state import AnalysisState


class ContentIndexStore(Protocol):
    def request_index(self, **kwargs) -> dict | None:
        ...


def content_indexer(state: AnalysisState, *, store: ContentIndexStore | None = None) -> AnalysisState:
    request = state.get("content_index_request")
    if not request:
        return {"content_index_result": {"status": "SKIPPED", "reason": "missing content_index_request"}}

    if store is None:
        return {
            "content_index_result": {
                "status": "PENDING",
                "reason": "content index store not configured",
                "request": request,
            }
        }

    # 1. Upsert source chunks to Postgres before indexing/embedding
    snapshot_id = request.get("snapshot_id")
    chunks = state.get("content_chunks", [])
    
    if hasattr(store, "upsert_chunks") and snapshot_id and chunks:
        from pathlib import Path
        formatted_chunks = []
        for chunk in chunks:
            chunk_type = "code"
            path_lower = (chunk.get("file_path") or "").lower()
            if path_lower.endswith((".md", ".txt", ".pdf")):
                chunk_type = "doc"
            elif path_lower.endswith((".json", ".yaml", ".yml", ".toml", ".ini", ".conf")):
                chunk_type = "config"
            
            content = chunk.get("content") or ""
            if not content and state.get("local_repo_dir") and chunk.get("file_path"):
                try:
                    local_dir = Path(state["local_repo_dir"])
                    from agenttrace.agents.analysis.nodes.legacy.chunk_embedder import _chunk_content
                    content = _chunk_content(chunk, local_dir, {})
                except Exception:
                    content = ""
            
            formatted_chunks.append({
                "chunk_id": chunk.get("chunk_id"),
                "file_path": chunk.get("file_path"),
                "content": content,
                "start_line": chunk.get("line_start"),
                "end_line": chunk.get("line_end"),
                "symbol": chunk.get("symbol"),
                "content_hash": chunk.get("content_hash"),
                "chunk_type": chunk_type,
            })
            
        store.upsert_chunks(snapshot_id, formatted_chunks)

    # 2. Perform request_index as usual
    result = store.request_index(**request)
    return {"content_index_result": result or {"status": "UNKNOWN"}}
