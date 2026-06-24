from __future__ import annotations

import time

from agenttrace.agents.analysis.state import AnalysisState
from agenttrace.logging_config import get_logger

logger = get_logger(__name__)



REQUIRED_KEYWORDS = {
    "agent", "mcp", "server", "client", "tool", "skill", "eval",
    "benchmark", "framework", "workflow", "plugin",
}

CLAIM_AREA_MAP: dict[str, str] = {
    "mcp": "agent-and-llm",
    "model context protocol": "agent-and-llm",
    "agent": "agent-and-llm",
    "prompt": "agent-and-llm",
    "tool": "tools-and-integrations",
    "skill": "agent-and-llm",
    "eval": "examples-and-tests",
    "benchmark": "examples-and-tests",
    "docker": "configuration-and-deployment",
    "kubernetes": "configuration-and-deployment",
    "deploy": "configuration-and-deployment",
    "workflow": "configuration-and-deployment",
    "database": "state-and-storage",
    "storage": "state-and-storage",
    "cache": "state-and-storage",
    "memory": "state-and-storage",
    "api": "tools-and-integrations",
    "integration": "tools-and-integrations",
    "service": "architecture-and-modules",
    "module": "architecture-and-modules",
    "entry": "execution-flow",
    "cli": "execution-flow",
    "server": "execution-flow",
    "main": "execution-flow",
}


def _infer_area_id(claim_text: str) -> str:
    """claim 텍스트에서 키워드 매칭으로 area_id 추론."""
    lower = claim_text.lower()
    for keyword, area_id in CLAIM_AREA_MAP.items():
        if keyword in lower:
            return area_id
    return "project-purpose"


def _claim_tokens(claim_text: str) -> set[str]:
    return {
        token.strip(".,:;()[]{}").lower()
        for token in claim_text.split()
        if len(token.strip(".,:;()[]{}")) >= 3
    }


def _target_paths(
    claims: list[dict],
    file_tree: list[dict],
    file_catalog: list[dict],
    critical_config_paths: list[str],
) -> list[str]:
    """claim 킠큰 매칭 + 소스 카타로그 우선순위로 target_paths를 선정한다.

    선정 우선순위:
    1. claim 킠큰과 경로명이 일치하는 source 파일
    2. source 카테고리 전체 (src/, lib/ 등 접두어 없어도 포함)
    3. file_catalog 없으면 기존 file_tree 기반 휴리스틱 폴백
    critical_config_paths는 호출측에서 빌드하여 매 task마다 주입한다.
    """
    tokens: set[str] = set()
    for claim in claims:
        tokens.update(_claim_tokens(claim.get("claim_text", "")))

    if file_catalog:
        # file_catalog 있음: source 카테고리 중심으로 선정
        source_paths = [
            e["path"] for e in file_catalog
            if e.get("category") == "source"
        ]
        # 토큰 매칭된 소스 파일 먼저
        matched = [
            p for p in source_paths
            if any(token in p.lower() for token in tokens)
        ]
        # 나머지 소스 파일 (matched 없으면 source_paths 전체에서 보완)
        rest = [p for p in source_paths if p not in matched]
        candidates = list(dict.fromkeys([*matched, *rest]))
    else:
        # 휴리스틱 폴백: 기존 file_tree 기반
        paths = [item.get("path", "") for item in file_tree if isinstance(item, dict)]
        matched = [
            p for p in paths
            if any(token in p.lower() for token in tokens)
        ]
        defaults = [
            p for p in paths
            if p.startswith(("src/", "lib/", "app/", "packages/"))
        ]
        candidates = list(dict.fromkeys([*matched, *defaults, *paths[:5]]))

    # critical_config_paths는 호출측에서 주입하므로 여기서는 포함하지 않음
    return candidates[:12]


def analysis_planner(state: AnalysisState) -> AnalysisState:
    _t = time.perf_counter()
    run_id = state.get("run_id", "-")
    log = logger.bind(node="analysis_planner", run_id=run_id)
    log.info("시작")
    claims = list(state.get("claims", []))

    file_tree = list(state.get("file_tree", []))
    file_catalog = list(state.get("file_catalog", []))
    critical_config_paths = list(state.get("critical_config_paths", []))
    repository_id = state.get("metadata", {}).get("repository_id") or state.get("repository_id")

    required_claims = [
        claim for claim in claims
        if _claim_tokens(claim.get("claim_text", "")) & REQUIRED_KEYWORDS
    ]
    optional_claims = [claim for claim in claims if claim not in required_claims]

    def _build_target_paths(claim_subset: list[dict]) -> list[str]:
        """claim 기반 target_paths 생성 + critical_config 항상 포함."""
        paths = _target_paths(claim_subset, file_tree, file_catalog, critical_config_paths)
        # critical_config_paths는 구조와 무관하게 모든 task에 포함 보장
        combined = list(dict.fromkeys([*critical_config_paths, *paths]))
        return combined

    tasks: list[dict] = []
    if required_claims:
        tasks.append({
            "task_id": "task-001",
            "claims": [claim["claim_id"] for claim in required_claims],
            "area_id": _infer_area_id(" ".join(c["claim_text"] for c in required_claims)),
            "target_paths": _build_target_paths(required_claims),
            "required": True,
            "status": "PENDING",
            "result": None,
        })
    if optional_claims:
        tasks.append({
            "task_id": f"task-{len(tasks) + 1:03d}",
            "claims": [claim["claim_id"] for claim in optional_claims],
            "area_id": _infer_area_id(" ".join(c["claim_text"] for c in optional_claims)),
            "target_paths": _build_target_paths(optional_claims),
            "required": False,
            "status": "PENDING",
            "result": None,
        })

    plan = {
        "plan_id": "plan-001",
        "repository_id": repository_id,
        "tasks": tasks,
    }
    log.info("완료", tasks=len(tasks), duration_ms=int((time.perf_counter() - _t) * 1000))
    return {"analysis_plan": plan, "evidence_tasks": tasks}

