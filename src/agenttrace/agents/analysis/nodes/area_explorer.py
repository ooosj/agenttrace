"""Area-based exploration node using ReAct agent.

algorithm.md §22.5: 영역 기반 발견 패러다임 — 단일 ReAct 에이전트가 8개 영역을
직접 탐색하며 Finding과 EvidenceRef를 생성한다.
"""
from __future__ import annotations

import time
import os
from pathlib import Path
from typing import Any

from agenttrace.agents.analysis.react_tools import create_react_tools
from agenttrace.agents.analysis.schemas.result import (
    AreaExplorationResult,
    AreaFinding,
    COMMON_ANALYSIS_AREAS,
    EvidenceRef,
    EvidenceSignal,
)
from agenttrace.agents.analysis.state import AnalysisState
from agenttrace.config import get_settings
from agenttrace.logging_config import get_logger
from agenttrace.models import build_openai_analysis_model

logger = get_logger(__name__)


def _build_area_prompt(area_id: str, area_name: str) -> str:
    return f"  - {area_id}: {area_name}"


def _build_system_prompt() -> str:
    areas_text = "\n".join(
        _build_area_prompt(aid, aname) for aid, aname in COMMON_ANALYSIS_AREAS
    )
    return (
        "You are an expert AI software analyst. Your task is to explore a repository "
        "using tools and produce findings for 8 analysis areas.\n\n"
        "ANALYSIS AREAS (you MUST cover ALL of these):\n"
        f"{areas_text}\n\n"
        "EXPLORATION STRATEGY (follow this order):\n"
        "1. Call get_structure_map to see all files and their ranked symbols\n"
        "2. For each area, identify keywords and use search_code to find relevant code\n"
        "3. Use list_symbols on promising files to check their contents\n"
        "4. Use read_file to read the FULL content of source files that contain relevant code\n"
        "5. Read at least 5-10 source code files across different areas before producing findings\n\n"
        "CRITICAL RULES:\n"
        "- You MUST read actual source code files (.ts, .py, .go, .js, .rs, .java), "
        "NOT just README or .mdx docs.\n"
        "- For each AreaFinding, provide concrete findings with evidence_refs pointing to "
        "EvidenceRef IDs you create.\n"
        "- Each EvidenceRef must have a unique ID (e.g. 'ref-purpose-1', 'ref-exec-2'), "
        "clear path, and description.\n"
        "- If you include line numbers (line_start or line_end), they must be 1-based integers (>= 1). "
        "If line numbers are not available, set them to null.\n"
        "- The status for each AreaFinding must be one of: "
        "'confirmed', 'partially_confirmed', 'unconfirmed', 'not_applicable'.\n"
        "- Each finding's type must be either 'fact' or 'inference'.\n"
        "- agent_type must be one of: 'MCP', 'Skill', 'Eval', 'ToolUse', 'Framework', 'Other', 'Unknown'.\n"
    )


def _build_user_prompt(state: AnalysisState) -> str:
    readme = (state.get("readme") or "")[:20000]
    repo_map_render = state.get("repo_map_render") or ""
    file_tree = state.get("file_tree") or []

    file_tree_str = ""
    if file_tree:
        paths = []
        for item in file_tree[:200]:
            if isinstance(item, dict):
                paths.append(item.get("path", ""))
            else:
                paths.append(str(item))
        file_tree_str = "\n".join(paths)

    return (
        f"Repository README:\n{readme}\n\n"
        f"Repository File Tree (first 200):\n{file_tree_str}\n\n"
        f"Pre-rendered structure map:\n{repo_map_render[:30000]}\n\n"
        "IMPORTANT: You MUST explore the codebase using tools before producing findings.\n"
        "Do NOT just rely on the README or structure map above. You MUST:\n"
        "1. Call get_structure_map first\n"
        "2. Search for keywords relevant to each area using search_code\n"
        "3. Read the actual source files (read_file) to verify implementation\n"
        "4. Only then provide your final findings for all 8 areas\n\n"
        "Produce exactly 8 AreaFinding objects (one per area) and all EvidenceRef objects "
        "they reference. Also determine the agent_type for this repository.\n"
    )


def _build_mock_result(state: AnalysisState) -> dict:
    evidence_refs = _build_fallback_evidence_refs(state)
    agent_type = _infer_fallback_agent_type(state, evidence_refs)
    evidence_ids_by_area = _fallback_evidence_ids_by_area(evidence_refs)
    area_findings = []
    for area_id, area_name in COMMON_ANALYSIS_AREAS:
        refs = evidence_ids_by_area.get(area_id, [])[:3]
        status = "partially_confirmed" if refs else "unconfirmed"
        area_findings.append({
            "area_id": area_id,
            "area_name": area_name,
            "status": status,
            "summary": f"{area_name} 분석은 repo map과 수집된 파일 근거 기준으로 제한적으로 구성되었습니다.",
            "findings": [
                {
                    "content": (
                        f"{area_name}은 {', '.join(refs)} 근거를 기준으로 제한적으로 확인되었습니다."
                        if refs
                        else f"{area_name}은 수집된 파일 근거만으로는 추가 확인이 필요합니다."
                    ),
                    "type": "fact" if refs else "inference",
                    "evidence_refs": refs,
                }
            ],
            "limitations": ["정적 분석은 런타임 동작을 보장하지 않습니다."],
            "unresolved_questions": ["실행 환경에서 동일 흐름이 재현되는지 확인이 필요합니다."],
        })

    evidence_signals = _build_evidence_signals(evidence_refs)
    return {
        "area_findings": area_findings,
        "evidence_refs": evidence_refs,
        "agent_type": agent_type,
        "tech_stack_summary": None,
        "synthesis": {
            "analysis_status": "completed_with_limitations",
            "agent_type": agent_type,
            "tech_stack_summary": _fallback_tech_stack(state),
        },
        "evidence_signals": evidence_signals,
    }


def _build_fallback_evidence_refs(state: AnalysisState) -> list[dict]:
    repo_map = state.get("repo_map", {}) or {}
    files = repo_map.get("files", {}) or {}
    catalog = {
        item.get("path"): item
        for item in state.get("file_catalog", [])
        if isinstance(item, dict) and item.get("path")
    }
    candidate_paths = list(files.keys())
    if not candidate_paths:
        candidate_paths = [
            item.get("path")
            for item in state.get("selected_files", []) or state.get("source_files", [])
            if isinstance(item, dict) and item.get("path")
        ]

    def score(path: str) -> tuple[int, str]:
        lower = path.lower()
        data = files.get(path, {}) or {}
        refs = " ".join([
            path,
            " ".join(data.get("definitions", [])),
            " ".join(data.get("references", [])),
            catalog.get(path, {}).get("category", ""),
        ]).lower()
        val = 0
        if lower.endswith((".ts", ".tsx", ".js", ".jsx", ".py", ".go", ".rs", ".java")):
            val += 50
        if any(token in refs for token in ("mcp", "server", "tool", "agent", "sdk", "client", "api", "search", "context", "resolve")):
            val += 30
        if lower.endswith(("package.json", "pyproject.toml", ".yml", ".yaml", "dockerfile")):
            val += 20
        if lower.endswith((".md", ".mdx")):
            val += 10
        if "__tests__" in lower or lower.endswith((".test.ts", ".test.tsx", ".spec.ts", ".spec.tsx", "_test.py")):
            val -= 60
        elif "test" in lower or "example" in lower:
            val -= 20
        return (-val, path)

    refs: list[dict] = []
    local_repo_dir = Path(state["local_repo_dir"]) if state.get("local_repo_dir") else None
    for idx, path in enumerate(sorted(candidate_paths, key=score)[:12], start=1):
        data = files.get(path, {}) or {}
        category = catalog.get(path, {}).get("category") or data.get("category") or ""
        source_type = _source_type_for_path(path, category)
        excerpt = _read_excerpt(local_repo_dir, path)
        symbols = data.get("definitions", [])[:3]
        refs.append({
            "id": f"fallback-ref-{idx:03d}",
            "source_type": source_type,
            "path": path,
            "symbol": symbols[0] if symbols else None,
            "description": _fallback_description(path, data, category),
            "chunk_id": None,
            "line_start": 1 if excerpt else None,
            "line_end": min(20, len(excerpt.splitlines())) if excerpt else None,
            "content_excerpt": excerpt,
            "content_hash": None,
        })
    return refs


def _source_type_for_path(path: str, category: str) -> str:
    lower = path.lower()
    if category == "critical_config" or lower.endswith((".json", ".toml", ".yml", ".yaml", "dockerfile")):
        return "config"
    if lower.endswith((".md", ".mdx", ".txt")):
        return "doc"
    if lower.endswith((".ts", ".tsx", ".js", ".jsx", ".py", ".go", ".rs", ".java")):
        return "code"
    return "other"


def _read_excerpt(local_repo_dir: Path | None, rel_path: str) -> str | None:
    if not local_repo_dir:
        return None
    try:
        path = (local_repo_dir / rel_path).resolve()
        if not path.is_file() or not path.is_relative_to(local_repo_dir.resolve()):
            return None
        return "\n".join(path.read_text(encoding="utf-8", errors="ignore").splitlines()[:20])
    except Exception:
        return None


def _fallback_description(path: str, data: dict, category: str) -> str:
    symbols = data.get("definitions", [])[:3]
    refs = data.get("references", [])[:5]
    bits = []
    if category:
        bits.append(f"category={category}")
    if symbols:
        bits.append(f"definitions={', '.join(symbols)}")
    if refs:
        bits.append(f"references={', '.join(refs)}")
    return f"{path} ({'; '.join(bits)})" if bits else path


def _fallback_evidence_ids_by_area(evidence_refs: list[dict]) -> dict[str, list[str]]:
    keywords = {
        "project-purpose": ("readme", "package", "docs", "index"),
        "execution-flow": ("server", "index", "cli", "main", "run"),
        "architecture-and-modules": ("src/", "packages/", "lib/", "index"),
        "agent-and-llm": ("agent", "mcp", "model", "prompt", "context"),
        "tools-and-integrations": ("tool", "api", "client", "sdk", "redis", "search", "resolve"),
        "state-and-storage": ("redis", "cache", "store", "db", "state"),
        "configuration-and-deployment": ("package.json", ".yml", ".yaml", "docker", "config", "toml"),
        "examples-and-tests": ("test", "example", "readme", "docs/"),
    }
    result: dict[str, list[str]] = {}
    for area_id, terms in keywords.items():
        refs = []
        for ref in evidence_refs:
            haystack = f"{ref.get('path', '')} {ref.get('description', '')}".lower()
            if any(term in haystack for term in terms):
                refs.append(ref["id"])
        if not refs and evidence_refs:
            refs = [evidence_refs[0]["id"]]
        result[area_id] = refs
    return result


def _infer_fallback_agent_type(state: AnalysisState, evidence_refs: list[dict]) -> str:
    text = " ".join([
        state.get("readme", ""),
        str(state.get("metadata", {})),
        " ".join(ref.get("path", "") for ref in evidence_refs),
        " ".join(ref.get("description", "") for ref in evidence_refs),
    ]).lower()
    if "mcp" in text or "modelcontextprotocol" in text:
        return "MCP"
    if "skill" in text:
        return "Skill"
    if "eval" in text or "benchmark" in text:
        return "Eval"
    if "agent" in text:
        return "Framework"
    if "tool" in text or "api" in text:
        return "ToolUse"
    return "Unknown"


def _fallback_tech_stack(state: AnalysisState) -> dict:
    metadata = state.get("metadata", {}) or {}
    language = metadata.get("primary_language") or "Unknown"
    topics = metadata.get("topics") or []
    return {
        "primary_language": language,
        "frameworks": [topic for topic in topics if topic in {"langchain", "mcp", "sdk"}],
        "dependencies": [],
    }


def _build_evidence_signals(evidence_refs: list[dict]) -> list[dict]:
    signals = []
    for idx, ref in enumerate(evidence_refs, start=1):
        path = ref.get("path") or "unknown"
        signals.append({
            "signal_id": f"signal-{idx:04d}",
            "signal_type": _infer_signal_type(path),
            "path": path,
            "chunk_id": ref.get("chunk_id") or "",
            "line_start": ref.get("line_start"),
            "line_end": ref.get("line_end"),
            "content_excerpt": ref.get("content_excerpt") or "",
            "content_hash": ref.get("content_hash") or "",
            "summary": ref.get("description") or "",
            "confidence": 0.6,
        })
    return signals


def area_explorer(state: AnalysisState) -> AnalysisState:
    _t = time.perf_counter()
    run_id = state.get("run_id", "-")
    log = logger.bind(node="area_explorer", run_id=run_id)
    log.info("시작")

    settings = get_settings()
    if os.getenv("AGENTTRACE_SKIP_AREA_AGENT") in {"1", "true", "TRUE", "yes"}:
        log.warning("AGENTTRACE_SKIP_AREA_AGENT 설정됨, fallback 결과 반환")
        result = _build_mock_result(state)
        log.info(
            "완료(fallback)",
            area_findings=len(result["area_findings"]),
            evidence_refs=len(result["evidence_refs"]),
            duration_ms=int((time.perf_counter() - _t) * 1000),
        )
        return result

    if not settings.openai_api_key:
        log.warning("OPENAI_API_KEY 없음, mock 결과 반환")
        result = _build_mock_result(state)
        log.info(
            "완료(mock)",
            area_findings=len(result["area_findings"]),
            duration_ms=int((time.perf_counter() - _t) * 1000),
        )
        return result

    local_repo_dir_str = state.get("local_repo_dir")
    local_repo_dir = Path(local_repo_dir_str) if local_repo_dir_str else None
    repo_map = state.get("repo_map", {}) or {}
    file_catalog = state.get("file_catalog", []) or []

    try:
        from langchain.agents import create_agent

        model = build_openai_analysis_model()
        tools = create_react_tools(local_repo_dir, repo_map, file_catalog)

        system_prompt = _build_system_prompt()
        user_prompt = _build_user_prompt(state)

        agent = create_agent(
            model=model,
            tools=tools,
            system_prompt=system_prompt,
            response_format=AreaExplorationResult,
        )

        result = agent.invoke(
            {"messages": [{"role": "user", "content": user_prompt}]},
            config={"recursion_limit": 50},
        )

        structured_response = result.get("structured_response")
        if structured_response is None:
            log.warning("structured_response 없음, mock fallback")
            mock = _build_mock_result(state)
            log.info(
                "완료(mock-fallback)",
                area_findings=len(mock["area_findings"]),
                duration_ms=int((time.perf_counter() - _t) * 1000),
            )
            return mock

        area_findings = [af.model_dump() for af in structured_response.area_findings]
        evidence_refs = [
            _sanitize_ref(er.model_dump()) if hasattr(er, "model_dump") else _sanitize_ref(er)
            for er in structured_response.evidence_refs
        ]
        agent_type = structured_response.agent_type or "Unknown"
        tech_stack = None
        if structured_response.tech_stack_summary:
            tech_stack = structured_response.tech_stack_summary
            if hasattr(tech_stack, "model_dump"):
                tech_stack = tech_stack.model_dump()

        evidence_ids = {ref.get("id") for ref in evidence_refs}
        for af in area_findings:
            for finding in af.get("findings", []):
                finding["evidence_refs"] = [
                    rid for rid in finding.get("evidence_refs", []) if rid in evidence_ids
                ]

        all_area_ids = {aid for aid, _ in COMMON_ANALYSIS_AREAS}
        present_area_ids = {af.get("area_id") for af in area_findings}
        for area_id, area_name in COMMON_ANALYSIS_AREAS:
            if area_id not in present_area_ids:
                area_findings.append({
                    "area_id": area_id,
                    "area_name": area_name,
                    "status": "unconfirmed",
                    "summary": "분석 중 누락됨",
                    "findings": [],
                    "limitations": ["area_explorer 출력 누락"],
                    "unresolved_questions": [],
                })

        evidence_signals: list[dict] = []
        for idx, ref in enumerate(evidence_refs, start=1):
            path = ref.get("path") or "unknown"
            sig_type = _infer_signal_type(path)
            evidence_signals.append({
                "signal_id": f"signal-{idx:04d}",
                "signal_type": sig_type,
                "path": path,
                "chunk_id": ref.get("chunk_id") or "",
                "line_start": ref.get("line_start"),
                "line_end": ref.get("line_end"),
                "content_excerpt": ref.get("content_excerpt") or "",
                "content_hash": ref.get("content_hash") or "",
                "summary": ref.get("description") or "",
                "confidence": 0.8,
            })

        significant_areas = sum(
            1 for af in area_findings
            if af.get("status") == "confirmed"
        )
        analysis_status = "completed" if significant_areas >= 5 else "completed_with_limitations"

        log.info(
            "완료",
            area_findings=len(area_findings),
            evidence_refs=len(evidence_refs),
            agent_type=agent_type,
            duration_ms=int((time.perf_counter() - _t) * 1000),
        )

        return {
            "area_findings": area_findings,
            "evidence_refs": evidence_refs,
            "agent_type": agent_type,
            "tech_stack_summary": tech_stack,
            "evidence_signals": evidence_signals,
            "synthesis": {
                "analysis_status": analysis_status,
                "agent_type": agent_type,
                "tech_stack_summary": tech_stack or {"ko": "미확인", "en": "Unknown"},
            },
        }

    except Exception as exc:
        log.warning(f"area_explorer failed, falling back to mock: {exc}")
        result = _build_mock_result(state)
        log.info(
            "완료(mock-error)",
            area_findings=len(result["area_findings"]),
            duration_ms=int((time.perf_counter() - _t) * 1000),
        )
        return result


def _sanitize_ref(ref: dict) -> dict:
    for field in ["line_start", "line_end"]:
        val = ref.get(field)
        if val is not None and (not isinstance(val, int) or val < 1):
            ref[field] = None
    start = ref.get("line_start")
    end = ref.get("line_end")
    if start is not None and end is not None and start > end:
        ref["line_start"] = end
        ref["line_end"] = start
    return ref


def _infer_signal_type(file_path: str) -> str:
    lower_path = file_path.lower()
    if lower_path.endswith((".md", ".mdx", ".txt")):
        return "DOCUMENTATION_CORROBORATION"
    if lower_path.endswith((".yml", ".yaml", ".json", ".toml", "dockerfile")) or "docker-compose" in lower_path:
        return "CONFIGURATION_EVIDENCE"
    if lower_path.endswith((".ts", ".tsx", ".js", ".jsx", ".py", ".go", ".sh", ".rs", ".java", ".c", ".cpp", ".h")):
        return "IMPLEMENTATION_EVIDENCE"
    return "METADATA_SIGNAL"
