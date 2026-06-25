from __future__ import annotations

import concurrent.futures
import json
import os
import re
import time
import shutil
from pathlib import Path

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from agenttrace.agents.analysis.schemas.result import (
    AnalysisResult,
    COMMON_ANALYSIS_AREAS,
    ReportSection,
    MERMAID_STARTERS,
)
from agenttrace.agents.analysis.state import AnalysisState
from agenttrace.config import get_settings
from agenttrace.logging_config import get_logger
from agenttrace.models import build_openai_finalize_model

logger = get_logger(__name__)


def _invoke_with_retry(fn, *args, max_retries=3, **kwargs):
    for attempt in range(max_retries):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            exc_str = str(exc).lower()
            if ("rate_limit" in exc_str or "429" in exc_str) and attempt < max_retries - 1:
                wait_time = 20 * (attempt + 1)
                logger.warning(
                    f"Rate limit hit, waiting {wait_time}s before retry {attempt + 1}/{max_retries}",
                    error=str(exc)[:300],
                )
                time.sleep(wait_time)
                continue
            raise
    raise RuntimeError("Max retries exceeded")


class ReportBodySection(BaseModel):
    """Mermaid 없이 body_markdown만 생성하는 synthesis용 스키마."""
    section_id: int
    section_name: str
    status: str
    title: str
    body_markdown: str


class ReportBodyResult(BaseModel):
    report_sections: list[ReportBodySection] = Field(default_factory=list)


class MermaidResult(BaseModel):
    mermaid_code: str = Field(default="")


def _generate_mermaid_for_section(
    section_id: int,
    section_name: str,
    readme: str,
    area_summary: str,
) -> str | None:
    """섭션별 Mermaid 다이어그램을 별도 경량 LLM 호출로 생성. 실패 시 None 반환."""
    try:
        model = build_openai_finalize_model()
        structured_model = model.with_structured_output(MermaidResult)
        prompt = ChatPromptTemplate.from_messages([
            ("system",
             "You are a technical diagram expert. Generate a valid Mermaid diagram. "
             "Output ONLY raw mermaid syntax (no markdown code blocks). "
             "Use: flowchart TD/LR, graph TD/LR, sequenceDiagram, or classDiagram. "
             "Keep it concise (5-15 nodes). Double-quote labels with special characters. "
             "All node labels and diagram text MUST be written in English, even when the report body is Korean."),
            ("human",
             "Section {section_id}: {section_name}\n\nContext:\n{context}\n\n"
             "Generate a Mermaid diagram for this section."),
        ])
        result = _invoke_with_retry(
            structured_model.invoke,
            prompt.invoke({
                "section_id": section_id,
                "section_name": section_name,
                "context": f"README:\n{readme[:5000]}\n\nArea summary:\n{area_summary[:2000]}",
            }),
        )
        code = result.mermaid_code
        if "```" in code:
            code = re.sub(r"```(mermaid)?", "", code).strip()
        if not validate_mermaid_syntax(code):
            retry_result = _invoke_with_retry(
                structured_model.invoke,
                prompt.invoke({
                "section_id": section_id,
                "section_name": section_name,
                "context": (
                    f"README:\n{readme[:5000]}\n\nArea summary:\n{area_summary[:2000]}\n\n"
                    f"Previous attempt was invalid. Fix syntax issues and regenerate."
                ),
            }))
            code = retry_result.mermaid_code
            if "```" in code:
                code = re.sub(r"```(mermaid)?", "", code).strip()
        return code if validate_mermaid_syntax(code) else None
    except Exception as exc:
        logger.warning(f"Mermaid generation for section {section_id} failed: {exc}")
        return None


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

    area_findings = state.get("area_findings", [])
    evidence_refs = state.get("evidence_refs", [])
    evidence_signals = state.get("evidence_signals", [])

    if not area_findings:
        area_findings = _build_fallback_area_findings()

    _synthesis_start = time.perf_counter()
    if state.get("report_sections"):
        report_sections = state.get("report_sections")
        synthesis_ms = 0
        mermaid_ms = 0
    else:
        report_sections, mermaid_ms = _build_report_sections(state, area_findings, evidence_refs)
        synthesis_ms = int((time.perf_counter() - _synthesis_start) * 1000) - mermaid_ms

    _AGENT_TYPE_MAP = {
        "mcp": "MCP", "skill": "Skill", "eval": "Eval",
        "tooluse": "ToolUse", "tool_use": "ToolUse",
        "framework": "Framework", "other": "Other", "unknown": "Unknown",
    }

    def _normalize_agent_type(val: str | None) -> str:
        if not val:
            return "Unknown"
        cleaned = val.strip().rstrip(".").strip()
        return _AGENT_TYPE_MAP.get(cleaned.lower(), cleaned if cleaned in _AGENT_TYPE_MAP.values() else "Unknown")

    result = AnalysisResult.model_validate({
        "analysis_status": synthesis.get("analysis_status", "completed_with_limitations"),
        "agent_type": _normalize_agent_type(state.get("agent_type") or synthesis.get("agent_type", "Unknown")),
        "tech_stack_summary": synthesis.get("tech_stack_summary"),
        "area_findings": area_findings,
        "evidence_refs": evidence_refs,
        "report_sections": report_sections,
        "evidence_signals": evidence_signals,
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

    local_repo_dir_str = state.get("local_repo_dir")
    if local_repo_dir_str and not state.get("preserve_local_repo_dir"):
        local_repo_dir = Path(local_repo_dir_str)
        if local_repo_dir.exists():
            shutil.rmtree(local_repo_dir, ignore_errors=True)

    log.info(
        "완료",
        sections=len(result.report_sections),
        area_findings=len(result.area_findings),
        evidence_refs=len(result.evidence_refs),
        status=result.analysis_status,
        synthesis_ms=synthesis_ms,
        mermaid_ms=mermaid_ms,
        duration_ms=int((time.perf_counter() - _t) * 1000),
    )
    return {"final_result": result.model_dump()}


def _build_fallback_area_findings() -> list[dict]:
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
                    "evidence_refs": [],
                }
            ],
            "limitations": ["정적 분석은 런타임 동작, 성능, 운영 안정성을 보장하지 않습니다."],
            "unresolved_questions": ["실행 환경에서 동일 흐름이 재현되는지 확인이 필요합니다."],
        }
        for area_id, area_name in COMMON_ANALYSIS_AREAS
    ]


def _build_mock_report_sections(
    area_findings: list[dict],
    evidence_refs: list[dict] | None = None,
) -> tuple[list[dict], int]:
    statuses = {area["area_id"]: area["status"] for area in area_findings}
    default_status = "partially_confirmed" if area_findings else "unconfirmed"
    evidence_refs = evidence_refs or []
    areas_by_id = {area.get("area_id"): area for area in area_findings if area.get("area_id")}
    refs_by_id = {ref.get("id"): ref for ref in evidence_refs if ref.get("id")}
    sections = []
    for idx, section_name in enumerate(REPORT_SECTION_NAMES, start=1):
        section_area_ids = _section_area_ids(idx)
        section_areas = [areas_by_id[area_id] for area_id in section_area_ids if area_id in areas_by_id]
        if not section_areas:
            section_areas = area_findings[:2]

        area_lines = [
            f"- {area.get('area_name', area.get('area_id', 'unknown'))}: {area.get('summary', '')}"
            for area in section_areas
        ]
        finding_lines = _format_finding_lines(section_areas)
        section_refs = _section_evidence_refs(section_areas, refs_by_id, evidence_refs)
        evidence_lines = _format_evidence_lines(section_refs)

        body_parts = [f"이 섹션은 {section_name}에 직접 관련된 분석 영역과 근거만 요약합니다."]
        if area_lines:
            body_parts.extend(["", "관련 영역:", *area_lines])
        if finding_lines:
            body_parts.extend(["", "핵심 관찰:", *finding_lines])
        if evidence_lines:
            body_parts.extend(["", "근거:", *evidence_lines])
        body = "\n".join(body_parts)
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
    return sections, 0


def _section_area_ids(section_id: int) -> list[str]:
    mapping = {
        1: ["project-purpose", "architecture-and-modules"],
        2: ["project-purpose"],
        3: ["project-purpose", "tools-and-integrations", "examples-and-tests"],
        4: ["execution-flow"],
        5: ["architecture-and-modules"],
        6: ["agent-and-llm", "tools-and-integrations"],
        7: [
            "execution-flow",
            "architecture-and-modules",
            "tools-and-integrations",
            "configuration-and-deployment",
        ],
        8: ["configuration-and-deployment", "examples-and-tests"],
        9: ["architecture-and-modules", "examples-and-tests"],
        10: ["state-and-storage", "configuration-and-deployment"],
        11: ["examples-and-tests", "project-purpose"],
    }
    return mapping.get(section_id, ["project-purpose"])


def _format_finding_lines(areas: list[dict]) -> list[str]:
    lines: list[str] = []
    for area in areas:
        for finding in area.get("findings", [])[:2]:
            content = str(finding.get("content") or "").strip()
            if content:
                lines.append(f"- {content}")
    return lines[:6]


def _section_evidence_refs(
    areas: list[dict],
    refs_by_id: dict[str, dict],
    fallback_refs: list[dict],
) -> list[dict]:
    refs: list[dict] = []
    seen: set[str] = set()
    for area in areas:
        for finding in area.get("findings", []):
            for ref_id in finding.get("evidence_refs", []) or []:
                if ref_id in refs_by_id and ref_id not in seen:
                    seen.add(ref_id)
                    refs.append(refs_by_id[ref_id])
    if refs:
        return refs
    return fallback_refs[:3]


def _format_evidence_lines(evidence_refs: list[dict]) -> list[str]:
    lines: list[str] = []
    for ref in evidence_refs[:8]:
        path = ref.get("path") or "unknown"
        start = ref.get("line_start")
        end = ref.get("line_end")
        location = f"{path}:{start}-{end}" if start and end else path
        excerpt = (ref.get("content_excerpt") or "").strip().replace("\n", " ")
        if len(excerpt) > 180:
            excerpt = excerpt[:177] + "..."
        description = ref.get("description") or ref.get("source_type") or "evidence"
        if excerpt:
            lines.append(f"- {location} - {description}: `{excerpt}`")
        else:
            lines.append(f"- {location} - {description}")
    return lines


def _build_report_sections(state: AnalysisState, area_findings: list[dict], evidence_refs: list[dict]) -> tuple[list[dict], int]:
    try:
        settings = get_settings()
        if os.getenv("AGENTTRACE_SKIP_FINALIZE_AGENT") in {"1", "true", "TRUE", "yes"}:
            return _build_mock_report_sections(area_findings, evidence_refs)
        if not settings.openai_api_key:
            return _build_mock_report_sections(area_findings, evidence_refs)

        readme = state.get("readme") or ""
        area_findings_str = _compact_area_findings(area_findings)
        evidence_refs_str = _compact_evidence_refs(evidence_refs)

        model = build_openai_finalize_model()
        structured_model = model.with_structured_output(ReportBodyResult)

        system_prompt = (
            "You are an expert AI software analyst writing a detailed technical report in Korean.\n"
            "Your task is to synthesize a structured technical report with exactly 11 sections "
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
            "2. The mermaid_diagram field does not exist in this schema. Mermaid diagrams are generated separately after synthesis.\n"
            "3. Every section must have a `status` which is one of: 'confirmed', 'partially_confirmed', 'unconfirmed', 'not_applicable'.\n"
            "4. Do not make up facts. Adhere strictly to the findings and evidence provided. If information is missing, prefix the section body with '[확인 불가]' or '[해당 없음]' and explain briefly.\n\n"
            "QUALITY RULES (CRITICAL for good output):\n"
            "5. Each section's body_markdown MUST be at least 800 characters (Korean). Write 4-6 paragraphs per section.\n"
            "6. Reference specific file paths, function names, class names, and code locations from the evidence.\n"
            "7. Use markdown formatting: headings (##, ###), bullet points, numbered lists, code blocks for technical terms.\n"
            "8. For section 1 (핵심 요약): Include the project name, what it does, target audience, key technologies, and a brief overview of the architecture.\n"
            "9. For section 3 (핵심 기능): List 4-6 specific features. For each feature, describe what it does, which file/function implements it, and how it works.\n"
            "10. For section 4 (전체 동작 방식): Describe the step-by-step execution flow with specific function/file references. Explain how data flows through the system.\n"
            "11. For section 5 (아키텍처): Describe each major module/package and its responsibility. Explain how modules interact with each other.\n"
            "12. For section 7 (중요한 코드): List 4-6 key files with their full paths and describe what each file does in detail.\n"
            "13. For section 8 (설치·실행): Include specific commands (npm install, npx, docker, etc.), configuration steps, environment variables, and requirements.\n"
            "14. Write in natural, professional Korean. Do NOT write vague or generic statements.\n"
            "15. BAD example: '이 프로젝트는 다양한 기능을 제공합니다.' (too vague, less than 800 chars)\n"
            "16. GOOD example: 'packages/mcp/src/index.ts의 resolve-library-id 도구는 사용자가 입력한 라이브러리 이름을 Context7 API에 전달하여 매칭되는 라이브러리 ID 목록을 반환한다. 이 도구는 MCP 프로토콜을 통해 Claude, Cursor 등의 AI 코딩 어시스턴트에 통합되어...' (specific, detailed)\n"
            "17. If you have enough evidence, write MORE detail, not less. Each section should be comprehensive.\n"
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
            "readme": readme[:40000],
            "area_findings": area_findings_str,
            "evidence_refs": evidence_refs_str,
        })

        res = _invoke_with_retry(structured_model.invoke, prompt_value)
        sections = [s.model_dump() if hasattr(s, "model_dump") else dict(s) for s in res.report_sections]

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
                sec["mermaid_diagram"] = None
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

        area_summary_map = {af.get("area_id"): af.get("summary", "") for af in area_findings}

        _mermaid_t = time.perf_counter()
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            fut4 = executor.submit(
                _generate_mermaid_for_section,
                4, "전체 동작 방식", readme, area_summary_map.get("execution-flow", "")
            )
            fut5 = executor.submit(
                _generate_mermaid_for_section,
                5, "아키텍처와 주요 컴포넌트", readme, area_summary_map.get("architecture-and-modules", "")
            )
            mermaid_results = {4: fut4.result(), 5: fut5.result()}
        mermaid_ms = int((time.perf_counter() - _mermaid_t) * 1000)

        for sec in final_sections:
            sid = sec.get("section_id")
            sec["mermaid_diagram"] = mermaid_results.get(sid)

        return final_sections, mermaid_ms

    except Exception as exc:
        logger.warning(f"LLM synthesis for report sections failed: {exc}. Falling back to mock sections.")
        return _build_mock_report_sections(area_findings, evidence_refs)


def _default_mermaid() -> str:
    return "\n".join(
        [
            "flowchart TD",
            "  A[Repository Snapshot] --> B[Semantic Chunks]",
            "  B --> C[Area Findings]",
            "  C --> D[Evidence-backed Report]",
        ]
    )


def _compact_area_findings(area_findings: list[dict]) -> str:
    """Report synthesis용 compact payload."""
    compact = []
    for af in area_findings:
        compact.append({
            "area_id": af.get("area_id"),
            "area_name": af.get("area_name"),
            "status": af.get("status"),
            "summary": af.get("summary"),
            "findings": [
                {"content": f.get("content"), "type": f.get("type"), "evidence_refs": f.get("evidence_refs", [])}
                for f in af.get("findings", [])[:5]
            ],
            "limitations": af.get("limitations", [])[:3],
            "unresolved_questions": af.get("unresolved_questions", [])[:3],
        })
    return json.dumps(compact, indent=2, ensure_ascii=False)


def _compact_evidence_refs(evidence_refs: list[dict]) -> str:
    """Report synthesis용 compact payload: id/path/description/excerpt 포함."""
    compact = [
        {
            "id": r.get("id"),
            "path": r.get("path"),
            "source_type": r.get("source_type"),
            "description": r.get("description"),
            "line_start": r.get("line_start"),
            "line_end": r.get("line_end"),
            "content_excerpt": (r.get("content_excerpt") or "")[:500],
        }
        for r in evidence_refs
    ]
    return json.dumps(compact, indent=2, ensure_ascii=False)
