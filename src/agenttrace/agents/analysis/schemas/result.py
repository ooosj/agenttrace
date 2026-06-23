from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


COMMON_ANALYSIS_AREAS: tuple[tuple[str, str], ...] = (
    ("project-purpose", "프로젝트 목적과 주요 기능"),
    ("execution-flow", "진입점과 핵심 실행 흐름"),
    ("architecture-components", "아키텍처와 컴포넌트 구조"),
    ("agent-patterns", "Agent·LLM 기술과 설계 패턴"),
    ("tool-integrations", "도구와 외부 연동"),
    ("data-state-memory", "데이터·상태·메모리 관리"),
    ("configuration-runtime", "설정·실행·배포 방식"),
    ("tests-evaluation-limitations", "테스트·평가·정적 분석 한계"),
)

MERMAID_STARTERS = (
    "flowchart ",
    "graph ",
    "sequenceDiagram",
    "classDiagram",
    "stateDiagram",
    "stateDiagram-v2",
    "erDiagram",
    "journey",
    "gantt",
    "timeline",
)


class LocalizedText(BaseModel):
    ko: str
    en: str


class AnalysisLimitations(BaseModel):
    missing_inputs: list[str] = Field(default_factory=list)
    truncated_inputs: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class TechStackSummary(BaseModel):
    primary_language: str | None = None
    frameworks: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)


class Finding(BaseModel):
    content: str
    type: Literal["fact", "inference"]
    evidence_refs: list[str]


class AreaFinding(BaseModel):
    area_id: str
    area_name: str
    status: Literal["confirmed", "partially_confirmed", "unconfirmed", "not_applicable"]
    summary: str
    findings: list[Finding]
    limitations: list[str] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)


class EvidenceRef(BaseModel):
    id: str
    source_type: Literal["code", "doc", "config", "other"]
    path: str
    symbol: str | None = None
    description: str
    chunk_id: str | None = None
    line_start: int | None = Field(default=None, ge=1)
    line_end: int | None = Field(default=None, ge=1)
    content_excerpt: str | None = None
    content_hash: str | None = None

    @model_validator(mode="after")
    def validate_line_range(self) -> "EvidenceRef":
        if self.line_start is not None and self.line_end is not None and self.line_start > self.line_end:
            raise ValueError("line_start must be less than or equal to line_end")
        return self


class ReportSection(BaseModel):
    section_id: int = Field(ge=1)
    section_name: str
    status: Literal["confirmed", "partially_confirmed", "unconfirmed", "not_applicable"]
    title: str
    body_markdown: str
    mermaid_diagram: str | None = None

    @model_validator(mode="after")
    def validate_mermaid(self) -> "ReportSection":
        if self.mermaid_diagram is None:
            return self
        diagram = self.mermaid_diagram.strip()
        if not diagram.startswith(MERMAID_STARTERS):
            raise ValueError("Invalid Mermaid diagram")
        if "```" in diagram:
            raise ValueError("Invalid Mermaid diagram")
        return self


class AnalysisClaim(BaseModel):
    claim_id: str
    claim_text: str
    source_path: str = "README.md"
    source_section: str | None = None
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    evidence_signal_ids: list[str] = Field(default_factory=list)


class EvidenceSignal(BaseModel):
    signal_id: str
    signal_type: str
    path: str
    chunk_id: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    content_excerpt: str | None = None
    content_hash: str | None = None
    summary: str
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class ClaimVerdict(BaseModel):
    claim_id: str
    verdict: Literal["SUPPORTED", "PARTIALLY_SUPPORTED", "CONTRADICTED", "NOT_FOUND", "INSUFFICIENT_EVIDENCE", "DOCUMENTED"]
    reason: str
    evidence_signal_ids: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class EvidenceTaskResult(BaseModel):
    task_id: str
    status: Literal["RESOLVED", "INSUFFICIENT_EVIDENCE"]
    claim_verdicts: list[ClaimVerdict]
    evidence_signal_ids: list[str] = Field(default_factory=list)
    search_limit_reached: bool = False
    limitations: list[str] = Field(default_factory=list)


class RiskSignal(BaseModel):
    risk_type: str
    summary: str
    severity: Literal["low", "medium", "high"] = "low"


class AnalysisResult(BaseModel):
    analysis_status: Literal["completed", "completed_with_limitations", "insufficient_evidence", "uncertain_classification"]
    agent_type: Literal["MCP", "Skill", "Eval", "ToolUse", "Framework", "Other", "Unknown"] | None = None
    tech_stack_summary: TechStackSummary | LocalizedText | None = None
    area_findings: list[AreaFinding] = Field(default_factory=list)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    report_sections: list[ReportSection] = Field(default_factory=list)
    analysis_claims: list[AnalysisClaim] = Field(default_factory=list)
    evidence_signals: list[EvidenceSignal] = Field(default_factory=list)
    evidence_task_results: list[EvidenceTaskResult] = Field(default_factory=list)
    risk_signals: list[RiskSignal] = Field(default_factory=list)
    follow_up_guide: LocalizedText | None = None
    analysis_limitations: AnalysisLimitations

    @model_validator(mode="after")
    def validate_document_contract(self) -> "AnalysisResult":
        if self.area_findings:
            required_area_ids = {area_id for area_id, _ in COMMON_ANALYSIS_AREAS}
            present_area_ids = {finding.area_id for finding in self.area_findings}
            missing_area_ids = sorted(required_area_ids - present_area_ids)
            if missing_area_ids:
                raise ValueError(f"Missing common analysis areas: {', '.join(missing_area_ids)}")

            evidence_ids = {ref.id for ref in self.evidence_refs}
            for area in self.area_findings:
                for finding in area.findings:
                    for ref_id in finding.evidence_refs:
                        if ref_id not in evidence_ids:
                            raise ValueError(f"Unknown evidence ref referenced: {ref_id}")

        if self.report_sections:
            section_ids = [section.section_id for section in self.report_sections]
            if section_ids != list(range(1, 12)):
                raise ValueError("Report sections must contain section_id 1 through 11 in order")

        return self
