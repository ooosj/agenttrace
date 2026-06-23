from __future__ import annotations

import concurrent.futures
import json
import re
import time

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from agenttrace.agents.analysis.schemas.result import (
    AnalysisResult,
    AreaFinding,
    COMMON_ANALYSIS_AREAS,
    EvidenceRef,
    ReportSection,
    MERMAID_STARTERS,
)
from agenttrace.agents.analysis.state import AnalysisState
from agenttrace.config import get_settings
from agenttrace.logging_config import get_logger
from agenttrace.models import build_openai_analysis_model

logger = get_logger(__name__)


class BatchAnalysisResult(BaseModel):
    area_findings: list[AreaFinding] = Field(default_factory=list)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)


class ReportSynthesisResult(BaseModel):
    report_sections: list[ReportSection] = Field(default_factory=list)


def validate_mermaid_syntax(mermaid_code: str) -> bool:
    lines = [
        line.strip() 
        for line in mermaid_code.strip().split("\n") 
        if line.strip() and not line.strip().startswith("%%")
    ]
    if not lines:
        return False
    
    header = lines[0]
    valid_headers = [
        r"^graph\s+(TD|LR|TB|BT|RL)$",
        r"^flowchart\s+(TD|LR|TB|BT|RL)$",
        r"^sequenceDiagram$",
        r"^classDiagram$",
        r"^stateDiagram-v2$",
        r"^erDiagram$"
    ]
    if not any(re.match(h, header, re.IGNORECASE) for h in valid_headers):
        return False
    
    for line in lines[1:]:
        if re.search(r"[-=]{4,}>", line):
            return False
        for open_b, close_b in [("[", "]"), ("(", ")"), ("{", "}")]:
            if line.count(open_b) != line.count(close_b):
                return False
    return True



REPORT_SECTION_NAMES = (
    "핵심 요약과 추천 독자",
    "프로젝트가 해결하는 문제",
    "핵심 기능과 대표 사용 사례",
    "전체 동작 방식",
    "아키텍처와 주요 컴포넌트",
    "사용된 Agent 기술과 설계 패턴",
    "중요한 코드와 문서",
    "설치·실행·사용 방법",
    "다른 프로젝트에 적용하는 방법",
    "주의사항과 분석 한계",
    "다음 탐색 가이드",
)


def finalize_analysis(state: AnalysisState) -> AnalysisState:
    _t = time.perf_counter()
    run_id = state.get("run_id", "-")
    log = logger.bind(node="finalize_analysis", run_id=run_id)
    log.info("시작")
    synthesis = state.get("synthesis", {})

    evidence_refs = state.get("evidence_refs") or _build_evidence_refs(state)
    _batch_start = time.perf_counter()
    area_findings = state.get("area_findings") or _build_area_findings(state, evidence_refs)
    batch_wall_ms = int((time.perf_counter() - _batch_start) * 1000)
    report_sections = state.get("report_sections") or _build_report_sections(state, area_findings, evidence_refs)
    
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

    log.info(
        "완료",
        sections=len(result.report_sections),
        area_findings=len(result.area_findings),
        evidence_refs=len(result.evidence_refs),
        status=result.analysis_status,
        batch_wall_ms=batch_wall_ms,
        duration_ms=int((time.perf_counter() - _t) * 1000),
    )
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


def _build_mock_area_findings(evidence_refs: list[dict]) -> list[dict]:
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


def _build_area_findings(state: AnalysisState, evidence_refs: list[dict]) -> list[dict]:
    try:
        settings = get_settings()
        if not settings.openai_api_key:
            return _build_mock_area_findings(evidence_refs)

        readme = state.get("readme") or ""
        file_tree = state.get("file_tree") or []
        content_chunks = state.get("content_chunks") or []

        file_tree_str = json.dumps(file_tree, indent=2, ensure_ascii=False)

        formatted_chunks = []
        for chunk in content_chunks:
            path = chunk.get("file_path") or chunk.get("path") or "unknown"
            content = chunk.get("content") or ""
            line_start = chunk.get("line_start") or chunk.get("start_line") or 1
            line_end = chunk.get("line_end") or chunk.get("end_line") or 1
            chunk_id = chunk.get("chunk_id") or "unknown"
            formatted_chunks.append(
                f"--- File: {path} (Lines {line_start}-{line_end}) [Chunk ID: {chunk_id}] ---\n"
                f"{content}\n"
            )
        chunks_text = "\n".join(formatted_chunks)
        if len(chunks_text) > 100000:
            chunks_text = chunks_text[:100000] + "\n... [TRUNCATED] ..."

        batches_definition = [
            {
                "name": "Batch 1 (프로젝트 이해 묶음)",
                "areas": [
                    ("project-purpose", "프로젝트 목적과 주요 기능"),
                    ("examples-and-tests", "예제·테스트·확장 지점"),
                ],
            },
            {
                "name": "Batch 2 (핵심 내부 구조 묶음)",
                "areas": [
                    ("execution-flow", "진입점과 핵심 실행 흐름"),
                    ("architecture-and-modules", "아키텍처와 모듈 관계"),
                    ("agent-and-llm", "Agent·LLM 핵심 로직"),
                    ("tools-and-integrations", "Tool·외부 서비스 연동"),
                    ("state-and-storage", "상태·메모리·데이터 저장"),
                ],
            },
            {
                "name": "Batch 3 (실행과 적용 묶음)",
                "areas": [
                    ("configuration-and-deployment", "설정·실행·배포 방법"),
                ],
            }
        ]

        all_area_findings = []
        all_evidence_refs = []

        model = build_openai_analysis_model()
        structured_model = model.with_structured_output(BatchAnalysisResult)

        system_prompt = (
            "You are an expert AI software analyst. Your task is to analyze a repository based on its README, file tree, "
            "and source code chunks, and output analysis for specific areas in a structured format.\n"
            "CRITICAL RULES:\n"
            "1. You must only analyze the requested areas: {areas_list_text}.\n"
            "2. Do not include findings or analyze any areas other than the requested ones in this batch.\n"
            "3. For each analyzed area, produce an 'AreaFinding' object containing the status, summary, list of findings, "
            "limitations, and unresolved questions.\n"
            "   - The status must be one of: 'confirmed', 'partially_confirmed', 'unconfirmed', 'not_applicable'.\n"
            "   - For each finding in findings, the finding 'type' must be either 'fact' or 'inference'.\n"
            "   - Each finding must reference one or more unique evidence IDs from the 'evidence_refs' list in the 'evidence_refs' field.\n"
            "4. In the 'evidence_refs' list, output the concrete source code/config/doc files that support your findings. "
            "Ensure every EvidenceRef has a unique ID (e.g. 'ref-purpose-1', 'ref-exec-2'), clear path, and description.\n"
            "   - IMPORTANT: If you include line numbers (line_start or line_end) in EvidenceRef, they must be 1-based integers (>= 1). Do not use 0 or negative numbers. If line numbers are not available or not applicable, omit them or set them to null/None.\n"
            "5. The output must be a single structured JSON matching the BatchAnalysisResult schema."
        )

        human_prompt = (
            "Requested areas to analyze in this batch:\n"
            "{areas_detail_text}\n\n"
            "Repository README:\n"
            "{readme}\n\n"
            "Repository File Tree:\n"
            "{file_tree}\n\n"
            "Source Code Chunks:\n"
            "{chunks_text}\n"
        )

        # executor 진입 전 prompt 1회 생성 (기존 for 루프에서 매번 생성하던 부분)
        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("human", human_prompt),
        ])

        def _invoke_single_batch(batch_def: dict) -> tuple[list, list]:
            areas_list_text = ", ".join(
                [f"'{area_id}' ({area_name})" for area_id, area_name in batch_def["areas"]]
            )
            areas_detail_text = "\n".join(
                [f"- {area_id}: {area_name}" for area_id, area_name in batch_def["areas"]]
            )
            prompt_value = prompt.invoke({
                "areas_list_text": areas_list_text,
                "areas_detail_text": areas_detail_text,
                "readme": readme[:30000],
                "file_tree": file_tree_str[:20000],
                "chunks_text": chunks_text,
            })
            batch_res = structured_model.invoke(prompt_value)
            return batch_res.area_findings, batch_res.evidence_refs

        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            futures = [executor.submit(_invoke_single_batch, b) for b in batches_definition]
            for future in concurrent.futures.as_completed(futures):
                findings, refs = future.result()
                all_area_findings.extend(findings)
                all_evidence_refs.extend(refs)

        # De-duplicate evidence_refs by ID and normalize/sanitize line numbers
        unique_refs_dict = {}
        for ref in all_evidence_refs:
            ref_dict = ref.model_dump() if hasattr(ref, "model_dump") else dict(ref)
            ref_id = ref_dict.get("id")
            if not ref_id:
                continue

            # Sanitize line numbers just in case LLM outputs <= 0
            for field in ["line_start", "line_end"]:
                val = ref_dict.get(field)
                if val is not None and (not isinstance(val, int) or val < 1):
                    ref_dict[field] = None

            # Ensure line_start <= line_end
            start = ref_dict.get("line_start")
            end = ref_dict.get("line_end")
            if start is not None and end is not None and start > end:
                ref_dict["line_start"] = end

            if ref_id not in unique_refs_dict:
                unique_refs_dict[ref_id] = ref_dict

        # Collect and merge area findings
        findings_dict = {}
        for af in all_area_findings:
            af_dict = af.model_dump() if hasattr(af, "model_dump") else dict(af)
            findings_dict[af_dict["area_id"]] = af_dict

        # Build final findings and ensure references exist, create fallbacks for missing ones
        final_findings = []
        for area_id, area_name in COMMON_ANALYSIS_AREAS:
            if area_id in findings_dict:
                af_dict = findings_dict[area_id]
                # Validate and heal evidence references
                for finding in af_dict.get("findings", []):
                    valid_refs = []
                    for ref_id in finding.get("evidence_refs", []):
                        if ref_id not in unique_refs_dict:
                            # Create fallback EvidenceRef to prevent schema validation failure
                            unique_refs_dict[ref_id] = {
                                "id": ref_id,
                                "source_type": "other",
                                "path": "unknown",
                                "description": f"자동 생성된 {area_name} 분석 근거 참조",
                                "symbol": None,
                                "chunk_id": None,
                                "line_start": None,
                                "line_end": None,
                                "content_excerpt": None,
                                "content_hash": None,
                            }
                        valid_refs.append(ref_id)
                    finding["evidence_refs"] = valid_refs
                final_findings.append(af_dict)
            else:
                final_findings.append({
                    "area_id": area_id,
                    "area_name": area_name,
                    "status": "unconfirmed",
                    "summary": "분석 중 누락됨",
                    "findings": [],
                    "limitations": ["LLM 분석 출력 누락"],
                    "unresolved_questions": [],
                })

        # Update evidence_refs in place
        evidence_refs.clear()
        evidence_refs.extend(list(unique_refs_dict.values()))

        return final_findings

    except Exception as exc:
        logger.warning(f"LLM 3-batch analysis failed, falling back to mock: {exc}")
        return _build_mock_area_findings(evidence_refs)


def _build_mock_report_sections(area_findings: list[dict]) -> list[dict]:
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


def _build_report_sections(state: AnalysisState, area_findings: list[dict], evidence_refs: list[dict]) -> list[dict]:
    try:
        settings = get_settings()
        if not settings.openai_api_key:
            return _build_mock_report_sections(area_findings)

        readme = state.get("readme") or ""
        area_findings_str = json.dumps(area_findings, indent=2, ensure_ascii=False)
        evidence_refs_str = json.dumps(evidence_refs, indent=2, ensure_ascii=False)

        model = build_openai_analysis_model()
        structured_model = model.with_structured_output(ReportSynthesisResult)

        system_prompt = (
            "You are an expert AI software analyst. Your task is to synthesize a structured technical report with exactly 11 sections "
            "based on the repository README, verified Area Findings, and Evidence References.\n\n"
            "Here is the list of the 11 V2 report sections you MUST generate, in this exact order:\n"
            "1. 핵심 요약과 추천 독자\n"
            "2. 프로젝트가 해결하는 문제\n"
            "3. 핵심 기능과 대표 사용 사례\n"
            "4. 전체 동작 방식\n"
            "5. 아키텍처와 주요 컴포넌트\n"
            "6. 사용된 Agent 기술과 설계 패턴\n"
            "7. 중요한 코드와 문서\n"
            "8. 설치·실행·사용 방법\n"
            "9. 다른 프로젝트에 적용하는 방법\n"
            "10. 주의사항과 분석 한계\n"
            "11. 다음 탐색 가이드\n\n"
            "CRITICAL RULES:\n"
            "1. Generate exactly 11 sections. Each section must map to section_id 1 to 11 respectively.\n"
            "2. For section 4 ('전체 동작 방식') and section 5 ('아키텍처와 주요 컴포넌트'), you MUST generate a valid Mermaid diagram in `mermaid_diagram` field. "
            "For other sections, `mermaid_diagram` must be null/None.\n"
            "3. Any generated Mermaid diagram MUST start with one of the standard headers: graph TD/LR, flowchart TD/LR, sequenceDiagram, classDiagram, stateDiagram-v2, erDiagram. Do NOT wrap it in markdown code blocks like ```mermaid. Output the raw mermaid syntax directly.\n"
            "4. Ensure correct bracket matching and valid arrow patterns (no more than 3 hyphens/equals like --->). Special characters or spaces in node labels must be double-quoted (e.g. A[\"Label\"]).\n"
            "5. Every section must have a `status` which is one of: 'confirmed', 'partially_confirmed', 'unconfirmed', 'not_applicable'.\n"
            "6. Do not make up facts. Adhere strictly to the findings and evidence provided. If information is missing, prefix the section body with '[확인 불가]' or '[해당 없음]' and explain briefly."
        )

        human_prompt = (
            "Repository README:\n"
            "{readme}\n\n"
            "Verified Area Findings:\n"
            "{area_findings}\n\n"
            "Evidence References:\n"
            "{evidence_refs}\n"
        )

        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("human", human_prompt),
        ])

        prompt_value = prompt.invoke({
            "readme": readme[:30000],
            "area_findings": area_findings_str,
            "evidence_refs": evidence_refs_str,
        })

        res = structured_model.invoke(prompt_value)
        sections = [s.model_dump() if hasattr(s, "model_dump") else dict(s) for s in res.report_sections]

        # 1-time Retry loop for Mermaid syntax validation
        retry_needed = False
        retry_feedback = []

        for section in sections:
            m_code = section.get("mermaid_diagram")
            if m_code:
                if "```" in m_code:
                    m_code = re.sub(r"```(mermaid)?", "", m_code).strip()
                    section["mermaid_diagram"] = m_code

                if not validate_mermaid_syntax(m_code):
                    retry_needed = True
                    retry_feedback.append(
                        f"Section {section.get('section_id')} ('{section.get('section_name')}') has an invalid Mermaid diagram:\n"
                        f"```\n{m_code}\n```\n"
                        f"Please fix the syntax (e.g. check mismatched brackets, arrow formats, or double quotes for labels with special characters)."
                    )

        if retry_needed:
            retry_prompt = ChatPromptTemplate.from_messages([
                ("system", system_prompt),
                ("human", human_prompt),
                ("ai", "{previous_sections}"),
                ("human", "We found syntax errors in the Mermaid diagrams you generated:\n\n"
                          "{feedback}\n\n"
                          "Please regenerate the list of 11 report sections, ensuring that all Mermaid diagrams are syntactically valid according to the rules."),
            ])

            retry_prompt_value = retry_prompt.invoke({
                "readme": readme[:30000],
                "area_findings": area_findings_str,
                "evidence_refs": evidence_refs_str,
                "previous_sections": json.dumps(sections, ensure_ascii=False),
                "feedback": "\n".join(retry_feedback),
            })

            try:
                res_retry = structured_model.invoke(retry_prompt_value)
                sections = [s.model_dump() if hasattr(s, "model_dump") else dict(s) for s in res_retry.report_sections]
            except Exception as retry_exc:
                logger.warning(f"Mermaid retry synthesis failed: {retry_exc}. Keeping original sections.")

        # Final pass and cleanups
        for section in sections:
            m_code = section.get("mermaid_diagram")
            if m_code:
                if "```" in m_code:
                    m_code = re.sub(r"```(mermaid)?", "", m_code).strip()
                    section["mermaid_diagram"] = m_code

                is_valid_starter = any(m_code.strip().startswith(s) for s in MERMAID_STARTERS)
                if not is_valid_starter or not validate_mermaid_syntax(m_code):
                    logger.warning(f"Section {section.get('section_id')} mermaid diagram invalid after retry. Removing diagram.")
                    section["mermaid_diagram"] = None

        sections_by_id = {s.get("section_id"): s for s in sections if s.get("section_id") is not None}
        final_sections = []
        for sid in range(1, 12):
            sec_name = REPORT_SECTION_NAMES[sid - 1]
            if sid in sections_by_id:
                sec = sections_by_id[sid]
                sec["section_name"] = sec_name
                sec["section_id"] = sid
                if "title" not in sec or not sec["title"]:
                    sec["title"] = f"{sid}. {sec_name}"
                if "status" not in sec or sec["status"] not in ["confirmed", "partially_confirmed", "unconfirmed", "not_applicable"]:
                    sec["status"] = "unconfirmed"
                if "body_markdown" not in sec or not sec["body_markdown"]:
                    sec["body_markdown"] = f"[확인 불가] {sec_name} 섹션에 대한 분석 정보가 수집되지 않았습니다."
                final_sections.append(sec)
            else:
                final_sections.append({
                    "section_id": sid,
                    "section_name": sec_name,
                    "status": "unconfirmed",
                    "title": f"{sid}. {sec_name}",
                    "body_markdown": f"[확인 불가] {sec_name} 섹션에 대한 분석 정보가 수집되지 않았습니다.",
                    "mermaid_diagram": None,
                })

        return final_sections

    except Exception as exc:
        logger.warning(f"LLM synthesis for report sections failed: {exc}. Falling back to mock sections.")
        return _build_mock_report_sections(area_findings)


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
