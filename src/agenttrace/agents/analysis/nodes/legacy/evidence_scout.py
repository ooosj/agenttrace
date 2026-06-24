from __future__ import annotations

import re
import time

from agenttrace.agents.analysis.bm25 import ChunkBM25Index
from agenttrace.agents.analysis.state import AnalysisState
from agenttrace.logging_config import get_logger

logger = get_logger(__name__)

MAX_SELECTED_CHUNKS = 15

DEFAULT_WEIGHTS = {
    "pagerank": 3.0,
    "bm25": 2.0,
    "embedding": 2.5,
    "path_prior": 1.0,
    "symbol_match": 1.5,
    "artifact_priority": 1.0,
}


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


def _query_tokens(state: AnalysisState, task: dict) -> set[str]:
    query_tokens = set()
    for text in _claim_texts(state, task):
        query_tokens.update(_tokens(text))
    for query in task.get("queries", []):
        query_tokens.update(_tokens(str(query)))
    return query_tokens


def _repo_map_score_inputs(state: AnalysisState, task: dict) -> tuple[dict[str, float], dict[str, dict]]:
    repo_map = state.get("repo_map", {}) or {}
    area_id = task.get("area_id") or ""
    area_ranks = repo_map.get("area_file_ranks", {}).get(area_id, {}) or {}
    files = repo_map.get("files", {}) or {}

    lower_ranks = {path.lower(): float(score) for path, score in area_ranks.items()}
    lower_files = {path.lower(): data for path, data in files.items()}
    return lower_ranks, lower_files


def _chunk_score(
    chunk: dict,
    *,
    query_tokens: set[str],
    target_paths: set[str],
    file_ranks: dict[str, float],
    repo_files: dict[str, dict],
    bm25_scores: dict[str, float] | None = None,
    embedding_scores: dict[str, float] | None = None,
    weights: dict[str, float] | None = None,
) -> float:
    """algorithm.md §22.3: FinalRetrievalScore 혼합 스코어링."""
    path = chunk.get("file_path", "")
    lower_path = path.lower()
    chunk_id = chunk.get("chunk_id", "")
    w = weights or DEFAULT_WEIGHTS
    bm25 = bm25_scores or {}
    emb = embedding_scores or {}

    repo_file = repo_files.get(lower_path, {})
    symbol_tokens = _tokens(
        " ".join([
            *repo_file.get("definitions", []),
            *repo_file.get("references", []),
        ])
    )
    chunk_tokens = _tokens(
        " ".join([
            path,
            str(chunk.get("content", "")),
            str(chunk.get("content_hash", "")),
        ])
    )

    score = 0.0
    score += w["pagerank"] * file_ranks.get(lower_path, 0.0)
    score += w["bm25"] * bm25.get(chunk_id, 0.0)
    score += w["embedding"] * emb.get(chunk_id, 0.0)
    if query_tokens:
        score += 2.0 * len(query_tokens & chunk_tokens)
        score += w["symbol_match"] * len(query_tokens & symbol_tokens)
    if lower_path in target_paths:
        score += w["path_prior"]
    if repo_file.get("category") == "critical_config":
        score += w["artifact_priority"]
    return score


def evidence_scout(state: AnalysisState) -> AnalysisState:
    """구조 지도를 렌더링하고 ReAct 에이전트용 탐색 컨텍스트를 준비한다.

    algorithm.md §22.5: Repository Map으로 후보를 찾은 후 원문 청크를 다시 수집한다.
    기존: 15개 청크를 미리 선택 → LLM에게 전달 (일회성 필터)
    개선: 구조 지도를 렌더링 → LLM이 도구로 능동 탐색 (ReAct 패턴)
    """
    _t = time.perf_counter()
    run_id = state.get("run_id", "-")
    task_id = state.get("current_task_id", "-")
    log = logger.bind(node="evidence_scout", run_id=run_id, task_id=task_id)
    log.info("시작")
    task = _current_task(state)

    if not task:
        log.warning("현재 태스크 없음",
                    duration_ms=int((time.perf_counter() - _t) * 1000))
        return {"selected_chunks": [], "search_attempt": {}}

    repo_map = state.get("repo_map", {}) or {}
    area_id = task.get("area_id") or ""
    query_tokens = _query_tokens(state, task)
    target_paths = {path.lower() for path in task.get("target_paths", [])}
    file_ranks, repo_files = _repo_map_score_inputs(state, task)

    # 구조 지도 렌더링 (algorithm.md §13)
    definition_ranks = repo_map.get("definition_ranks", {})
    files_data = repo_map.get("files", {})

    # 상위 정의를 파일별로 그룹화
    file_symbols: dict[str, list[tuple[str, float]]] = {}
    for key, score in list(definition_ranks.items())[:300]:
        if "::" in key:
            path, symbol = key.rsplit("::", 1)
            if path not in file_symbols:
                file_symbols[path] = []
            file_symbols[path].append((symbol, score))

    # critical_config 파일 추가
    for path, data in files_data.items():
        if data.get("category") == "critical_config" and path not in file_symbols:
            file_symbols[path] = []

    # target_paths 파일이 구조 지도에 없으면 추가
    for tp in target_paths:
        if tp not in file_symbols and tp in files_data:
            file_symbols[tp] = []

    # 구조 지도에 파일이 없으면 빈 search_attempt 반환 (fallback 경로 유도)
    if not file_symbols:
        log.info("완료", mode="react", files_in_map=0,
                 duration_ms=int((time.perf_counter() - _t) * 1000))
        return {
            "selected_chunks": [],
            "search_attempt": {},
        }

    # 구조 지도 텍스트 생성
    structure_lines = [
        f"=== Structure Map for area: {area_id} ===",
        f"Total files in repo: {len(files_data)}",
        f"Files in this map: {len(file_symbols)}",
        f"Claims to verify: {', '.join(task.get('claims', []))}",
        "",
    ]
    def _sort_key(p: str) -> tuple[float, str]:
        syms = file_symbols.get(p, [])
        return (-sum(s for _, s in syms) if syms else 0, p)

    for path in sorted(file_symbols.keys(), key=_sort_key):
        symbols = file_symbols[path]
        category = files_data.get(path, {}).get("category", "")
        rank = file_ranks.get(path.lower(), 0.0)
        if symbols:
            top_symbols = [s for s, _ in sorted(symbols, key=lambda x: -x[1])[:10]]
            structure_lines.append(f"{path} [{category}] (rank={rank:.4f})")
            for s in top_symbols:
                structure_lines.append(f"  - {s}")
        else:
            structure_lines.append(f"{path} [{category}] (rank={rank:.4f}) (config/artifact)")
        structure_lines.append("")

    structure_map_text = "\n".join(structure_lines)

    # claim 텍스트도 포함
    claim_texts = _claim_texts(state, task)
    claims_summary = "\n".join(f"- {ct}" for ct in claim_texts)

    attempt = {
        "attempt": 1,
        "mode": "react",
        "area_id": area_id,
        "queries": sorted(query_tokens)[:20],
        "target_paths": list(target_paths)[:20],
        "structure_map": structure_map_text,
        "claims_summary": claims_summary,
        "candidate_files": list(file_symbols.keys()),
        "selected_chunk_ids": [],
        "excluded_chunk_ids": [],
        "exclusion_reasons": {},
    }

    log.info("완료", mode="react", files_in_map=len(file_symbols),
             duration_ms=int((time.perf_counter() - _t) * 1000))
    return {
        "selected_chunks": [],
        "search_attempt": attempt,
    }

