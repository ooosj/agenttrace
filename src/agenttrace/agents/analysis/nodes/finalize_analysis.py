from __future__ import annotations

from agenttrace.agents.analysis.schemas.result import AnalysisResult, COMMON_ANALYSIS_AREAS
from agenttrace.agents.analysis.state import AnalysisState


REPORT_SECTION_NAMES = (
    "핵심 요약과 추천 독자",
    "학습 이정표",
    "프로젝트 목적과 주요 기능",
    "전체 동작 방식",
    "핵심 컴포넌트와 파일",
    "Agent·LLM 설계 패턴",
    "도구와 외부 연동",
    "데이터·상태·메모리 관리",
    "실행·설정·배포 방법",
    "이식·재사용 가이드",
    "정적 분석 한계와 추가 확인 질문",
)


def finalize_analysis(state: AnalysisState) -> AnalysisState:
    synthesis = state.get("synthesis", {})
    evidence_refs = state.get("evidence_refs") or _build_evidence_refs(state)
    area_findings = state.get("area_findings") or _build_area_findings(evidence_refs)
    report_sections = state.get("report_sections") or _build_report_sections(area_findings)
    
    # Map claim_id to evidence_signal_ids from task results
    claim_signals = {}
    for task_res in state.get("task_results", []):
        for verdict in task_res.get("claim_verdicts", []):
            cid = verdict.get("claim_id")
            sids = verdict.get("evidence_signal_ids", [])
            if cid and sids:
                if cid not in claim_signals:
                    claim_signals[cid] = []
                for sid in sids:
                    if sid not in claim_signals[cid]:
                        claim_signals[cid].append(sid)
                        
    updated_claims = []
    for claim in state.get("claims", []):
        cid = claim.get("claim_id") or claim.get("id")
        claim_copy = dict(claim)
        if cid in claim_signals:
            claim_copy["evidence_signal_ids"] = claim_signals[cid]
        updated_claims.append(claim_copy)

    result = AnalysisResult.model_validate({
        "analysis_status": synthesis.get("analysis_status", "insufficient_evidence"),
        "agent_type": synthesis.get("agent_type", "Unknown"),
        "tech_stack_summary": synthesis.get("tech_stack_summary"),
        "area_findings": area_findings,
        "evidence_refs": evidence_refs,
        "report_sections": report_sections,
        "analysis_claims": updated_claims,
        "evidence_signals": state.get("evidence_signals", []),
        "evidence_task_results": state.get("task_results", []),
        "risk_signals": state.get("risk_signals", []),
        "follow_up_guide": state.get("follow_up_guide") or {
            "ko": "README와 근거 경로를 순서대로 확인하세요.",
            "en": "Review the README and evidence paths in order.",
        },
        "analysis_limitations": state.get("analysis_limitations") or {
            "missing_inputs": [],
            "truncated_inputs": [],
            "notes": [],
        },
    })

    import shutil
    from pathlib import Path
    local_repo_dir_str = state.get("local_repo_dir")
    if local_repo_dir_str:
        local_repo_dir = Path(local_repo_dir_str)
        if local_repo_dir.exists():
            shutil.rmtree(local_repo_dir, ignore_errors=True)

    return {"final_result": result.model_dump()}


def _build_evidence_refs(state: AnalysisState) -> list[dict]:
    refs: list[dict] = []
    for idx, chunk in enumerate(state.get("content_chunks", [])[:5], start=1):
        path = chunk.get("file_path") or chunk.get("path") or "unknown"
        content = chunk.get("content") or ""
        excerpt = content.strip().splitlines()[0] if content.strip() else None
        refs.append(
            {
                "id": f"ref-{idx}",
                "source_type": _source_type(path),
                "path": path,
                "symbol": chunk.get("symbol"),
                "description": f"{path}에서 확인한 정적 분석 근거",
                "chunk_id": chunk.get("chunk_id"),
                "line_start": chunk.get("line_start") or chunk.get("start_line"),
                "line_end": chunk.get("line_end") or chunk.get("end_line"),
                "content_excerpt": excerpt,
                "content_hash": chunk.get("content_hash"),
            }
        )
    if refs:
        return refs
    return [
        {
            "id": "ref-limited-1",
            "source_type": "doc",
            "path": "README.md",
            "symbol": None,
            "description": "소스 본문이 부족하여 README와 파일 목록 중심으로 제한 분석함",
            "chunk_id": None,
            "line_start": None,
            "line_end": None,
            "content_excerpt": None,
            "content_hash": None,
        }
    ]


def _build_area_findings(evidence_refs: list[dict]) -> list[dict]:
    ref_id = evidence_refs[0]["id"] if evidence_refs else "ref-limited-1"
    return [
        {
            "area_id": area_id,
            "area_name": area_name,
            "status": "partially_confirmed",
            "summary": f"{area_name}은 정적 근거를 기준으로 추가 확인이 필요합니다.",
            "findings": [
                {
                    "content": f"{area_name} 분석은 수집된 파일 근거를 기준으로 제한적으로 구성되었습니다.",
                    "type": "inference",
                    "evidence_refs": [ref_id],
                }
            ],
            "limitations": ["정적 분석은 런타임 동작, 성능, 운영 안정성을 보장하지 않습니다."],
            "unresolved_questions": ["실행 환경에서 동일 흐름이 재현되는지 확인이 필요합니다."],
        }
        for area_id, area_name in COMMON_ANALYSIS_AREAS
    ]


def _build_report_sections(area_findings: list[dict]) -> list[dict]:
    statuses = {area["area_id"]: area["status"] for area in area_findings}
    default_status = "partially_confirmed" if area_findings else "unconfirmed"
    sections = []
    for idx, section_name in enumerate(REPORT_SECTION_NAMES, start=1):
        body = (
            f"{section_name} 섹션은 AreaFinding과 EvidenceRef를 기반으로 생성됩니다. "
            "구체 근거 경로와 한계는 구조화 JSON의 evidenceRefs 및 analysisLimitations를 확인하세요."
        )
        sections.append(
            {
                "section_id": idx,
                "section_name": section_name,
                "status": statuses.get("execution-flow", default_status) if idx == 4 else default_status,
                "title": f"{idx}. {section_name}",
                "body_markdown": body,
                "mermaid_diagram": _default_mermaid() if idx == 4 else None,
            }
        )
    return sections


def _default_mermaid() -> str:
    return "\n".join(
        [
            "flowchart TD",
            "  A[Repository Snapshot] --> B[Semantic Chunks]",
            "  B --> C[Area Findings]",
            "  C --> D[Evidence-backed Report]",
        ]
    )


def _source_type(path: str) -> str:
    lowered = path.lower()
    if lowered.endswith((".md", ".rst", ".txt")):
        return "doc"
    if lowered.endswith((".json", ".yaml", ".yml", ".toml", ".ini", ".xml")):
        return "config"
    if lowered.endswith((".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".go", ".rs")):
        return "code"
    return "other"
