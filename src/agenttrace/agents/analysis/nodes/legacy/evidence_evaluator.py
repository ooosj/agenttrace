from pathlib import Path
import re
import time
from typing import Literal

from pydantic import BaseModel, Field
from agenttrace.agents.analysis.schemas.result import ClaimVerdict, EvidenceSignal
from agenttrace.agents.analysis.state import AnalysisState
from agenttrace.models import build_openai_analysis_model
from agenttrace.config import get_settings
from langchain_core.prompts import ChatPromptTemplate
from agenttrace.logging_config import get_logger

logger = get_logger(__name__)


def _get_chunk_content(chunk: dict, local_repo_dir: Path | None, file_bytes_cache: dict[Path, bytes] | None = None) -> str:
    if chunk.get("content"):
        return chunk["content"]
    if not local_repo_dir:
        return ""
    file_path_str = chunk.get("file_path")
    if not file_path_str:
        return ""
    try:
        resolved_base = local_repo_dir.resolve()
        resolved_target = (local_repo_dir / file_path_str).resolve()
        if not resolved_target.is_relative_to(resolved_base):
            raise ValueError(f"Path traversal detected: {file_path_str}")

        file_path = local_repo_dir / file_path_str
        if file_path.exists():
            if file_bytes_cache is not None and file_path in file_bytes_cache:
                content_bytes = file_bytes_cache[file_path]
            else:
                content_bytes = file_path.read_bytes()
                if file_bytes_cache is not None:
                    file_bytes_cache[file_path] = content_bytes
            start_byte = chunk.get("start_byte", 0)
            end_byte = chunk.get("end_byte", 0)
            return content_bytes[start_byte:end_byte].decode("utf-8", errors="ignore")
    except Exception as exc:
        if "Path traversal detected" in str(exc):
            raise
        pass
    return ""


class ClaimVerification(BaseModel):
    claim_id: str
    verdict: Literal["SUPPORTED", "PARTIALLY_SUPPORTED", "CONTRADICTED", "NOT_FOUND"] = Field(
        description="Whether the claim is fully supported, partially supported, contradicted, or not found in the code."
    )
    reason: str = Field(description="Detailed explanation of why this verdict was chosen based on the code you examined.")
    file_path: str | None = Field(default=None, description="The path of the file containing the code evidence, or null.")
    line_start: int | None = Field(default=None, description="1-based starting line number of the code evidence, or null.")
    line_end: int | None = Field(default=None, description="1-based ending line number of the code evidence, or null.")
    content_excerpt: str | None = Field(default=None, description="A 2-3 line code snippet showing the evidence, or null.")


class BatchVerificationResult(BaseModel):
    verdicts: list[ClaimVerification] = Field(description="List of verification verdicts for each claim.")


def _current_task(state: AnalysisState) -> dict | None:
    task_id = state.get("current_task_id")
    for task in state.get("analysis_plan", {}).get("tasks", []):
        if task.get("task_id") == task_id:
            return task
    return None


def _tokens(text: str) -> set[str]:
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    spaced = re.sub(r"[_\W]+", " ", spaced)
    return {token.lower() for token in re.findall(r"[A-Za-z0-9]{2,}", spaced)}


def _format_chunk_with_line_numbers(chunk_text: str, start_line: int) -> str:
    lines = chunk_text.splitlines()
    formatted_lines = []
    for i, line in enumerate(lines):
        formatted_lines.append(f"{start_line + i}: {line}")
    return "\n".join(formatted_lines)


def _infer_signal_type(file_path: str) -> str:
    lower_path = file_path.lower()
    if lower_path.endswith((".md", ".mdx", ".txt")):
        return "DOCUMENTATION_CORROBORATION"
    elif lower_path.endswith((".yml", ".yaml", ".json", ".toml", "dockerfile")) or "docker-compose" in lower_path:
        return "CONFIGURATION_EVIDENCE"
    elif lower_path.endswith((".ts", ".tsx", ".js", ".jsx", ".py", ".go", ".sh", ".rs", ".java", ".c", ".cpp", ".h")):
        return "IMPLEMENTATION_EVIDENCE"
    else:
        return "METADATA_SIGNAL"


def _fallback_evaluate(
    claims: list[dict],
    chunks: list[dict],
    evidence_signals: list[dict],
    verdicts: list[dict],
    start_idx: int = 1,
    local_repo_dir: Path | None = None,
    file_bytes_cache: dict[Path, bytes] | None = None,
) -> None:
    for claim in claims:
        claim_tokens = _tokens(claim.get("claim_text", ""))

        best_chunk = None
        best_overlap_len = 0
        best_overlap = set()
        best_chunk_content = ""

        for chunk in chunks:
            chunk_text = _get_chunk_content(chunk, local_repo_dir, file_bytes_cache)
            chunk_content = f"{chunk.get('file_path', '')}\n{chunk_text}"
            chunk_tokens = _tokens(chunk_content)
            overlap = claim_tokens & chunk_tokens
            if len(overlap) > best_overlap_len:
                best_overlap_len = len(overlap)
                best_chunk = chunk
                best_overlap = overlap
                best_chunk_content = chunk_text

        signal_ids: list[str] = []
        if best_chunk and best_overlap_len > 0:
            chunk = best_chunk
            overlap = best_overlap

            sig_type = _infer_signal_type(chunk["file_path"])
            verdict = "SUPPORTED" if len(overlap) >= 2 else "PARTIALLY_SUPPORTED"

            if sig_type == "DOCUMENTATION_CORROBORATION" and verdict == "SUPPORTED":
                verdict = "DOCUMENTED"

            signal = EvidenceSignal(
                signal_id=f"signal-{start_idx + len(evidence_signals):04d}",
                signal_type=sig_type,
                path=chunk["file_path"],
                chunk_id=chunk.get("chunk_id", ""),
                line_start=chunk.get("line_start", 1),
                line_end=chunk.get("line_end", 1),
                content_excerpt=best_chunk_content[:500],
                content_hash=chunk.get("content_hash", ""),
                summary="Source chunk overlaps README claim keywords.",
                confidence=min(0.55 + (0.05 * len(overlap)), 0.9),
            )
            evidence_signals.append(signal.model_dump())
            signal_ids.append(signal.signal_id)
            reason = "Selected source chunk contains terms related to the claim."
            limitations: list[str] = []
        else:
            verdict = "INSUFFICIENT_EVIDENCE"
            reason = "No source chunk was available for this claim."
            limitations = ["source content unavailable or no relevant chunk selected"]

        verdicts.append(ClaimVerdict(
            claim_id=claim["claim_id"],
            verdict=verdict,
            reason=reason,
            evidence_signal_ids=signal_ids,
            limitations=limitations,
        ).model_dump())


def _react_evaluate(
    claims: list[dict],
    structure_map: str,
    claims_summary: str,
    evidence_signals: list[dict],
    verdicts: list[dict],
    start_idx: int,
    local_repo_dir: Path | None,
    repo_map: dict,
    file_catalog: list[dict],
    log,
) -> bool:
    """create_agent 기반 ReAct 에이전트로 claim 검증.

    algorithm.md §22.5: Repository Map으로 후보를 찾은 후 원문 청크를 다시 수집한다.
    LangChain v1 create_agent 사용 (middleware 시스템 활용).
    """
    from agenttrace.agents.analysis.react_tools import create_react_tools
    from langchain.agents import create_agent

    settings = get_settings()
    if not settings.openai_api_key:
        return False

    try:
        model = build_openai_analysis_model()
        tools = create_react_tools(local_repo_dir, repo_map, file_catalog)

        # explored_files 추적용 컨테이너 (도구 클로저에서 공유)
        explored_files: list[str] = []

        system_prompt = (
            "You are an expert AI software analyst verifying technical claims from a project's README.\n\n"
            "You have access to tools for exploring the codebase. You MUST use them to examine ACTUAL SOURCE CODE.\n\n"
            "EXPLORATION STRATEGY (follow this order):\n"
            "1. Call get_structure_map to see all files and their ranked symbols\n"
            "2. For EACH claim, identify keywords and use search_code to find where they appear in source files\n"
            "3. Use list_symbols on promising files to check their contents\n"
            "4. Use read_file to read the FULL content of source files (.ts, .py, .go, .js, etc.) that contain relevant code\n"
            "5. Read at least 3-5 source code files before making verdicts\n\n"
            "CRITICAL RULES:\n"
            "- You MUST read actual source code files (.ts, .py, .go, .js, .rs, .java), NOT just README or .mdx docs.\n"
            "- Do NOT mark a claim as SUPPORTED based only on README or documentation files.\n"
            "- Do NOT mark a claim as SUPPORTED based only on config files (Dockerfile, CI/CD, .yml, .json).\n"
            "- Mark as SUPPORTED only when you have READ the actual implementation code that proves the claim.\n"
            "- Mark as PARTIALLY_SUPPORTED when there is partial implementation evidence or only config/doc evidence.\n"
            "- Mark as NOT_FOUND when you searched the code but could not find relevant implementation.\n"
            "- ALWAYS provide specific file_path and line numbers from the actual code you read.\n"
            "- The content_excerpt must be from the actual source code you examined, not from README.\n"
        )

        claims_json = "\n".join(
            f"- {c['claim_id']}: {c['claim_text']}" for c in claims
        )

        user_prompt = (
            f"Claims to verify:\n{claims_json}\n\n"
            f"Structure map (pre-rendered):\n{structure_map}\n\n"
            f"Claims summary:\n{claims_summary}\n\n"
            "IMPORTANT: You MUST explore the codebase using tools before making verdicts.\n"
            "Do NOT just rely on the structure map above. You MUST:\n"
            "1. Call get_structure_map first\n"
            "2. Search for keywords from each claim using search_code\n"
            "3. Read the actual source files (read_file) to verify implementation\n"
            "4. Only then provide your final verdicts\n\n"
            "For example, if a claim mentions 'MCP server', search for 'MCP' and 'server' in the code,\n"
            "then read the files that contain those terms. Verify the implementation exists.\n"
        )

        # create_agent로 에이전트 구축 (도구 루프 자동 관리)
        agent = create_agent(
            model=model,
            tools=tools,
            system_prompt=system_prompt,
            response_format=BatchVerificationResult,
        )

        # 에이전트 실행
        result = agent.invoke(
            {"messages": [{"role": "user", "content": user_prompt}]},
            config={"recursion_limit": 40},
        )

        # 도구 호출 추적: messages에서 read_file 도구 호출 추출
        messages = result.get("messages", [])
        for msg in messages:
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                for tc in msg.tool_calls:
                    if tc.get("name") == "read_file":
                        fp = tc.get("args", {}).get("file_path", "")
                        if fp and "error" not in fp.lower():
                            explored_files.append(fp)
                    log.info("ReAct 도구 호출", tool=tc.get("name"))

        # 구조화 출력 추출
        batch_result = result.get("structured_response")
        if batch_result is None:
            # fallback: messages에서 AIMessage 찾기
            for msg in reversed(messages):
                if hasattr(msg, "content") and isinstance(msg.content, str):
                    break
            log.warning("structured_response 없음, fallback으로 처리")
            return False

        explored_files_unique = list(dict.fromkeys(explored_files))

        for v in batch_result.verdicts:
            signal_ids = []
            verdict_status = v.verdict
            limitations = []

            # 가짜 경로 필터링: 실제로 읽은 파일 또는 repo_map에 존재하는 파일만 허용
            file_path = v.file_path
            if file_path:
                lower_fp = file_path.lower()
                explored_lower = {f.lower() for f in explored_files_unique}
                repo_files_set = {fp.lower() for fp in (repo_map.get("files", {}) or {}).keys()}
                if lower_fp not in explored_lower and lower_fp not in repo_files_set:
                    log.warning("가짜 경로 감지, 무시", file_path=file_path)
                    file_path = None

            if verdict_status in ["SUPPORTED", "PARTIALLY_SUPPORTED"] and file_path:
                sig_type = _infer_signal_type(file_path)

                if sig_type == "DOCUMENTATION_CORROBORATION" and verdict_status == "SUPPORTED":
                    verdict_status = "DOCUMENTED"

                signal = EvidenceSignal(
                    signal_id=f"signal-{start_idx + len(evidence_signals):04d}",
                    signal_type=sig_type,
                    path=file_path,
                    chunk_id="",
                    line_start=v.line_start or 0,
                    line_end=v.line_end or 0,
                    content_excerpt=v.content_excerpt or "",
                    content_hash="",
                    summary="ReAct agent verified via code exploration tools.",
                    confidence=0.85 if verdict_status in ["SUPPORTED", "DOCUMENTED"] else 0.70,
                )
                evidence_signals.append(signal.model_dump())
                signal_ids.append(signal.signal_id)
            elif verdict_status == "NOT_FOUND":
                verdict_status = "INSUFFICIENT_EVIDENCE"
                limitations = ["ReAct agent could not find evidence after code exploration"]

            verdicts.append(ClaimVerdict(
                claim_id=v.claim_id,
                verdict=verdict_status,
                reason=v.reason,
                evidence_signal_ids=signal_ids,
                limitations=limitations,
            ).model_dump())

        return True

    except Exception as exc:
        log.warning("ReAct 평가 실패 (fallback)", error=str(exc))
        return False


def evidence_evaluator(state: AnalysisState) -> AnalysisState:
    _t = time.perf_counter()
    run_id = state.get("run_id", "-")
    task_id = state.get("current_task_id", "-")
    log = logger.bind(node="evidence_evaluator", run_id=run_id, task_id=task_id)
    log.info("시작")
    task = _current_task(state)
    if not task:
        log.info("완료", results=0, duration_ms=int((time.perf_counter() - _t) * 1000))
        return {"task_part_results": []}

    claims = [
        claim for claim in state.get("claims", [])
        if claim.get("claim_id") in set(task.get("claims", []))
    ]

    task_part_results = []
    start_idx = len(state.get("evidence_signals", [])) + 1

    local_repo_dir_str = state.get("local_repo_dir")
    local_repo_dir = Path(local_repo_dir_str) if local_repo_dir_str else None
    file_bytes_cache: dict[Path, bytes] = {}

    # ReAct 모드 확인: search_attempt에 structure_map이 있으면 ReAct
    search_attempt = state.get("search_attempt", {}) or {}
    structure_map = search_attempt.get("structure_map", "")
    claims_summary = search_attempt.get("claims_summary", "")

    evidence_signals: list[dict] = []
    verdicts: list[dict] = []
    llm_success = False

    if structure_map and claims:
        # ReAct 에이전트 경로
        log.info("ReAct 모드", area_id=search_attempt.get("area_id", ""))
        repo_map = state.get("repo_map", {}) or {}
        file_catalog = state.get("file_catalog", []) or []

        llm_success = _react_evaluate(
            claims,
            structure_map,
            claims_summary,
            evidence_signals,
            verdicts,
            start_idx,
            local_repo_dir,
            repo_map,
            file_catalog,
            log,
        )

    if not llm_success:
        # Fallback: 기존 청크 기반 평가 (하위 호환성)
        all_chunks = state.get("selected_chunks", [])
        # selected_chunks가 비어있으면 chunk_index에서 직접 가져옴
        if not all_chunks:
            chunk_index = state.get("chunk_index", {}) or {}
            all_chunks = list(chunk_index.get("chunks_by_id", {}).values())
        chunks_by_id = {c["chunk_id"]: c for c in all_chunks} if all_chunks else {}

        task_parts = state.get("task_parts", [])
        # task_parts가 비어있거나 chunks가 비어있으면 all_chunks로 직접 구성
        if not task_parts or all(
            not part.get("chunks") for part in task_parts
        ):
            task_parts = [{
                "part_id": f"{task['task_id']}-part-001",
                "task_id": task["task_id"],
                "chunks": [c["chunk_id"] for c in all_chunks]
            }]

        for part in task_parts:
            part_chunk_ids = part.get("chunks", [])
            chunks = [chunks_by_id[cid] for cid in part_chunk_ids if cid in chunks_by_id]

            part_signals: list[dict] = []
            part_verdicts: list[dict] = []
            part_success = False

            settings = get_settings()
            if settings.openai_api_key and chunks and claims:
                try:
                    import json
                    model = build_openai_analysis_model()
                    structured_model = model.with_structured_output(BatchVerificationResult)

                    claims_formatted = json.dumps([
                        {"claim_id": c["claim_id"], "claim_text": c["claim_text"]}
                        for c in claims
                    ], ensure_ascii=False, indent=2)

                    chunks_formatted = ""
                    for idx, chunk in enumerate(chunks):
                        chunk_text = _get_chunk_content(chunk, local_repo_dir, file_bytes_cache)
                        start_line = chunk.get("line_start", 1)
                        formatted_chunk_text = _format_chunk_with_line_numbers(chunk_text, start_line)
                        chunks_formatted += f"--- Chunk {idx + 1} (File: {chunk['file_path']}) ---\n"
                        chunks_formatted += f"{formatted_chunk_text}\n---\n\n"

                    prompt = ChatPromptTemplate.from_messages([
                        ("system", (
                            "You are an expert AI software analyst. Your task is to verify technical claims made in a project's README against the provided source code chunks.\n"
                            "Each line of a source code chunk is prefixed with its absolute line number in the file (e.g. '123: class MyClass:'). "
                            "When returning the verification result, you MUST extract and return the correct absolute line_start and line_end values matching the code evidence.\n"
                            "For each claim, analyze if the chunks support, partially support, contradict, or do not contain information about the claim.\n"
                            "CRITICAL VERDICT RULES:\n"
                            "1. Do NOT mark a claim as fully `SUPPORTED` if the only evidence is a deployment/workflow file (like a GitHub workflow, CI/CD configuration, or Docker Compose), or a metadata setup. Such setup files only prove configuration, not actual logic implementation. Mark them as `PARTIALLY_SUPPORTED` at best.\n"
                            "2. Do NOT mark a claim as fully `SUPPORTED` if the evidence only shows basic variables or environment settings (like checking for an API key environment variable, but not implementing the actual OAuth flow). Mark as `PARTIALLY_SUPPORTED` or `INSUFFICIENT_EVIDENCE`.\n"
                            "3. Purely descriptive text inside documentation (like Markdown, MDX, or text files) should be evaluated, but avoid marking them as fully `SUPPORTED` if they only claim the feature exists without showing source code logic."
                        )),
                        ("human", "Claims to Verify:\n{claims_formatted}\n\nSource Code Chunks:\n{chunks_formatted}")
                    ])

                    prompt_value = prompt.invoke({
                        "claims_formatted": claims_formatted,
                        "chunks_formatted": chunks_formatted
                    })

                    result = structured_model.invoke(prompt_value)

                    for v in result.verdicts:
                        signal_ids = []
                        verdict_status = v.verdict
                        limitations = []

                        if verdict_status in ["SUPPORTED", "PARTIALLY_SUPPORTED"] and v.file_path:
                            matching_chunk = next(
                                (c for c in chunks if c["file_path"].lower() == v.file_path.lower()),
                                chunks[0] if chunks else None
                            )

                            if matching_chunk:
                                sig_type = _infer_signal_type(v.file_path)

                                if sig_type == "DOCUMENTATION_CORROBORATION" and verdict_status == "SUPPORTED":
                                    verdict_status = "DOCUMENTED"

                                chunk_line_start = matching_chunk.get("line_start", 1)
                                chunk_line_end = matching_chunk.get("line_end", 1)

                                line_start = v.line_start
                                line_end = v.line_end

                                if not line_start or line_start < chunk_line_start or line_start > chunk_line_end:
                                    line_start = chunk_line_start
                                if not line_end or line_end < line_start or line_end > chunk_line_end:
                                    line_end = chunk_line_end

                                signal = EvidenceSignal(
                                    signal_id=f"signal-{start_idx + len(part_signals):04d}",
                                    signal_type=sig_type,
                                    path=v.file_path,
                                    chunk_id=matching_chunk["chunk_id"],
                                    line_start=line_start,
                                    line_end=line_end,
                                    content_excerpt=v.content_excerpt or _get_chunk_content(matching_chunk, local_repo_dir, file_bytes_cache)[:500],
                                    content_hash=matching_chunk["content_hash"],
                                    summary="Source code verified by LLM semantic analysis.",
                                    confidence=0.85 if verdict_status in ["SUPPORTED", "DOCUMENTED"] else 0.70,
                                )
                                part_signals.append(signal.model_dump())
                                signal_ids.append(signal.signal_id)
                        else:
                            verdict_status = "INSUFFICIENT_EVIDENCE"
                            limitations = ["LLM semantic analysis could not verify this claim from the code chunks"]

                        part_verdicts.append(ClaimVerdict(
                            claim_id=v.claim_id,
                            verdict=verdict_status,
                            reason=v.reason,
                            evidence_signal_ids=signal_ids,
                            limitations=limitations,
                        ).model_dump())

                    part_success = True
                except Exception as exc:
                    log.warning("LLM 검증 실패 (fallback)", part_id=part['part_id'], error=str(exc))

            if not part_success:
                _fallback_evaluate(
                    claims,
                    chunks,
                    part_signals,
                    part_verdicts,
                    start_idx=start_idx,
                    local_repo_dir=local_repo_dir,
                    file_bytes_cache=file_bytes_cache,
                )

            start_idx += len(part_signals)
            evidence_signals.extend(part_signals)
            verdicts.extend(part_verdicts)

    task_part_results.append({
        "part_id": f"{task['task_id']}-part-001",
        "task_id": task["task_id"],
        "evidence_signals": evidence_signals,
        "claim_verdicts": verdicts,
    })

    total_signals = sum(len(r.get("evidence_signals", [])) for r in task_part_results)
    total_verdicts = sum(len(r.get("claim_verdicts", [])) for r in task_part_results)
    log.info("완료", task_parts=len(task_part_results), signals=total_signals, verdicts=total_verdicts,
             duration_ms=int((time.perf_counter() - _t) * 1000))
    return {
        "task_part_results": task_part_results
    }
