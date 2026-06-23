from __future__ import annotations

import ast
import hashlib
import re
from collections import defaultdict

from agenttrace.agents.analysis.schemas.content import (
    ChunkIndex,
    ChunkIndexEntry,
    ContentChunk,
)
from agenttrace.agents.analysis.schemas.input import SourceFile

WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")


def _line_for_start_offset(content: str, offset: int) -> int:
    return content[:offset].count("\n") + 1


def _line_for_end_offset(content: str, offset: int) -> int:
    if offset <= 0:
        return 1
    return content[: offset - 1].count("\n") + 1


def _byte_offsets(content: str) -> list[int]:
    offsets = [0]
    total = 0
    for char in content:
        total += len(char.encode("utf-8"))
        offsets.append(total)
    return offsets


def _end_index_for_byte_target(
    byte_offsets: list[int],
    start_index: int,
    target_size: int,
) -> int:
    target_end_byte = byte_offsets[start_index] + target_size
    end_index = start_index + 1
    while (
        end_index + 1 < len(byte_offsets)
        and byte_offsets[end_index + 1] <= target_end_byte
    ):
        end_index += 1
    return end_index


def _start_index_for_byte_offset(byte_offsets: list[int], target_byte: int) -> int:
    for index, byte_offset in enumerate(byte_offsets):
        if byte_offset >= target_byte:
            return index
    return len(byte_offsets) - 1


def _keywords(path: str, content: str) -> list[str]:
    path_words = re.split(r"[^A-Za-z0-9_]+", path)
    content_words = WORD_RE.findall(content[:4000])
    seen: set[str] = set()
    result: list[str] = []
    for word in path_words + content_words:
        lower = word.lower()
        if len(lower) >= 3 and lower not in seen:
            seen.add(lower)
            result.append(lower)
    return result[:80]


def _chunk_id(file_path: str, line_start: int, line_end: int, content_hash: str) -> str:
    raw = f"{file_path}:{line_start}:{line_end}:{content_hash}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _python_symbol_for_range(path: str, content: str, line_start: int, line_end: int) -> str | None:
    if not path.endswith(".py"):
        return None
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return None
    best: tuple[int, str] | None = None
    for node in ast.walk(tree):
        if not isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        node_start = getattr(node, "lineno", None)
        node_end = getattr(node, "end_lineno", None)
        if node_start is None or node_end is None:
            continue
        if node_start >= line_start and node_end <= line_end:
            span = node_end - node_start
            if best is None or span > best[0]:
                best = (span, node.name)
    return best[1] if best else None


def chunk_source_files(
    files: list[SourceFile],
    target_size: int = 12000,
    overlap: int = 500,
) -> list[ContentChunk]:
    if target_size <= 0:
        raise ValueError("target_size must be greater than 0")
    if overlap < 0:
        raise ValueError("overlap must be greater than or equal to 0")
    if overlap >= target_size:
        raise ValueError("overlap must be smaller than target_size")

    chunks: list[ContentChunk] = []
    counter = 1
    for source in files:
        content = source.content
        if not content:
            continue

        byte_offsets = _byte_offsets(content)
        start = 0
        while start < len(content):
            end = _end_index_for_byte_target(byte_offsets, start, target_size)
            chunk_text = content[start:end]
            line_start = _line_for_start_offset(content, start)
            line_end = _line_for_end_offset(content, end)
            chunks.append(
                ContentChunk(
                    chunk_id=_chunk_id(source.path, line_start, line_end, source.content_hash),
                    file_path=source.path,
                    content=chunk_text,
                    symbol=_python_symbol_for_range(source.path, content, line_start, line_end),
                    start_byte=byte_offsets[start],
                    end_byte=byte_offsets[end],
                    line_start=line_start,
                    line_end=line_end,
                    is_partial=start > 0 or end < len(content),
                    content_hash=source.content_hash,
                )
            )
            counter += 1

            if end == len(content):
                break
            next_start_byte = max(0, byte_offsets[end] - overlap)
            start = _start_index_for_byte_offset(byte_offsets, next_start_byte)

    return chunks


def build_chunk_index(chunks: list[ContentChunk]) -> ChunkIndex:
    by_path: dict[str, list[ContentChunk]] = defaultdict(list)
    for chunk in chunks:
        by_path[chunk.file_path].append(chunk)

    entries = [
        ChunkIndexEntry(
            file_path=path,
            chunk_ids=[chunk.chunk_id for chunk in path_chunks],
            keywords=_keywords(path, "\n".join(chunk.content for chunk in path_chunks)),
            chunk_count=len(path_chunks),
        )
        for path, path_chunks in sorted(by_path.items())
    ]
    return ChunkIndex(
        entries=entries,
        chunks_by_id={chunk.chunk_id: chunk for chunk in chunks},
    )


def source_chunk_table_contract_sql() -> str:
    return """
        CREATE TABLE source_chunks (
            chunk_id varchar(64) PRIMARY KEY,
            snapshot_id uuid NOT NULL REFERENCES repository_snapshots(snapshot_id) ON DELETE CASCADE,
            file_path text NOT NULL,
            content text NOT NULL,
            start_line integer,
            end_line integer,
            symbol text,
            content_hash varchar(64) NOT NULL,
            chunk_type varchar(30) NOT NULL DEFAULT 'code',
            embedding vector(1536),
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT chk_source_chunks_type CHECK (chunk_type IN ('code', 'doc', 'config', 'other'))
        )
    """.strip()
