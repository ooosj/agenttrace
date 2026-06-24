from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from agenttrace.agents.analysis.state import AnalysisState


class ChunkEmbeddingStore(Protocol):
    def update_embeddings(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        ...


class TextEmbeddingService(Protocol):
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        ...


def chunk_embedder(
    state: AnalysisState,
    *,
    embedding_service: TextEmbeddingService | None = None,
    store: ChunkEmbeddingStore | None = None,
) -> AnalysisState:
    if embedding_service is None:
        return {"chunk_embedding_result": {"status": "SKIPPED", "reason": "embedding service not configured"}}

    chunks = state.get("content_chunks", [])
    local_repo_dir_str = state.get("local_repo_dir")
    local_repo_dir = Path(local_repo_dir_str) if local_repo_dir_str else None
    rows: list[dict[str, Any]] = []
    texts: list[str] = []
    chunk_ids: list[str] = []
    file_bytes_cache: dict[Path, bytes] = {}

    for chunk in chunks:
        text = _chunk_content(chunk, local_repo_dir, file_bytes_cache)
        if not text.strip():
            continue
        texts.append(text)
        chunk_ids.append(chunk["chunk_id"])

    vectors = embedding_service.embed_texts(texts)
    rows = [
        {"chunk_id": chunk_id, "embedding": vector}
        for chunk_id, vector in zip(chunk_ids, vectors, strict=True)
    ]

    updated = store.update_embeddings(rows) if store is not None else []
    return {
        "chunk_embedding_rows": rows,
        "chunk_embedding_result": {
            "status": "UPDATED" if store is not None else "EMBEDDED",
            "updated_count": len(updated) if store is not None else 0,
            "embedded_count": len(rows),
        },
    }


def _chunk_content(chunk: dict[str, Any], local_repo_dir: Path | None, cache: dict[Path, bytes]) -> str:
    if chunk.get("content"):
        return chunk["content"]
    if local_repo_dir is None:
        return ""
    file_path = chunk.get("file_path")
    if not file_path:
        return ""
    resolved_base = local_repo_dir.resolve()
    resolved_target = (local_repo_dir / file_path).resolve()
    if not resolved_target.is_relative_to(resolved_base):
        raise ValueError(f"Path traversal detected: {file_path}")
    if resolved_target not in cache:
        cache[resolved_target] = resolved_target.read_bytes()
    start_byte = chunk.get("start_byte", 0)
    end_byte = chunk.get("end_byte", 0)
    return cache[resolved_target][start_byte:end_byte].decode("utf-8", errors="ignore")
