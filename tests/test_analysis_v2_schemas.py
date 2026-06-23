import pytest
from pydantic import ValidationError

from agenttrace.agents.analysis.schemas.input import AnalysisInputRequest, SourceFile
from agenttrace.agents.analysis.schemas.content import ContentChunk
from agenttrace.agents.analysis.schemas.result import AnalysisResult, ClaimVerdict


def _contract_result(**overrides):
    result = {
        "analysis_status": "completed",
        "agent_type": "Framework",
        "tech_stack_summary": {
            "primary_language": "Python",
            "frameworks": ["FastAPI"],
            "dependencies": ["langgraph"],
        },
        "area_findings": [
            {
                "area_id": area_id,
                "area_name": area_name,
                "status": "confirmed",
                "summary": f"{area_name} 확인됨",
                "findings": [
                    {
                        "content": f"{area_name} 근거 기반 사실",
                        "type": "fact",
                        "evidence_refs": ["ref-1"],
                    }
                ],
                "limitations": [],
                "unresolved_questions": [],
            }
            for area_id, area_name in [
                ("project-purpose", "프로젝트 목적과 주요 기능"),
                ("execution-flow", "진입점과 핵심 실행 흐름"),
                ("architecture-components", "아키텍처와 컴포넌트 구조"),
                ("agent-patterns", "Agent·LLM 기술과 설계 패턴"),
                ("tool-integrations", "도구와 외부 연동"),
                ("data-state-memory", "데이터·상태·메모리 관리"),
                ("configuration-runtime", "설정·실행·배포 방식"),
                ("tests-evaluation-limitations", "테스트·평가·정적 분석 한계"),
            ]
        ],
        "evidence_refs": [
            {
                "id": "ref-1",
                "source_type": "code",
                "path": "src/server.py",
                "symbol": "create_app",
                "description": "FastAPI application factory",
                "chunk_id": "chunk-1",
                "line_start": 1,
                "line_end": 12,
                "content_excerpt": "def create_app():",
                "content_hash": "sha256:" + "a" * 64,
            }
        ],
        "report_sections": [
            {
                "section_id": idx,
                "section_name": f"section-{idx}",
                "status": "confirmed",
                "title": f"{idx}. section",
                "body_markdown": "근거 기반 설명",
                "mermaid_diagram": "flowchart TD\n  A --> B" if idx == 4 else None,
            }
            for idx in range(1, 12)
        ],
        "analysis_limitations": {"missing_inputs": [], "truncated_inputs": [], "notes": []},
    }
    result.update(overrides)
    return result


def test_analysis_result_accepts_document_contract_fields():
    result = AnalysisResult.model_validate(_contract_result())

    assert result.analysis_status == "completed"
    assert len(result.area_findings) == 8
    assert len(result.report_sections) == 11
    assert result.evidence_refs[0].line_start == 1


def test_analysis_result_rejects_unknown_evidence_reference():
    payload = _contract_result()
    payload["area_findings"][0]["findings"][0]["evidence_refs"] = ["missing-ref"]

    with pytest.raises(ValidationError, match="Unknown evidence ref"):
        AnalysisResult.model_validate(payload)


def test_analysis_result_rejects_missing_common_area():
    payload = _contract_result()
    payload["area_findings"] = payload["area_findings"][:-1]

    with pytest.raises(ValidationError, match="Missing common analysis areas"):
        AnalysisResult.model_validate(payload)


def test_analysis_result_rejects_invalid_mermaid_diagram():
    payload = _contract_result()
    payload["report_sections"][3]["mermaid_diagram"] = "not mermaid"

    with pytest.raises(ValidationError, match="Invalid Mermaid diagram"):
        AnalysisResult.model_validate(payload)


def test_analysis_input_accepts_backend_payload_without_source_files():
    req = AnalysisInputRequest.model_validate(
        {
            "analysis_id": "00000000-0000-0000-0000-000000000001",
            "repository": {
                "repository_id": "repo-1",
                "full_name": "owner/repo",
                "github_url": "https://github.com/owner/repo",
                "description": "Agent repo",
            },
            "snapshot": {"snapshot_id": "snap-1", "commit_sha": "abc", "captured_at": "2026-06-20T00:00:00Z"},
            "readme_text": "# Repo\nProvides an MCP server.",
            "file_tree": ["README.md", "src/server.py"],
            "summary_result": {"summary_status": "completed"},
            "external_ingest": {"enabled": False, "provider": "gitingest"},
        }
    )

    assert req.source_files == []
    assert req.external_ingest.enabled is False


def test_source_file_hash_is_computed_when_missing():
    src = SourceFile(path="src/server.py", content="print('hi')")
    assert src.content_hash.startswith("sha256:")


def test_source_file_rejects_invalid_supplied_hash():
    with pytest.raises(ValidationError):
        SourceFile(path="src/server.py", content="print('hi')", content_hash="sha256:bad")


def test_source_file_rejects_hash_that_does_not_match_content():
    with pytest.raises(ValidationError):
        SourceFile(
            path="src/server.py",
            content="print('hi')",
            content_hash="sha256:0000000000000000000000000000000000000000000000000000000000000000",
        )


def test_source_file_normalizes_supplied_hash_to_lowercase():
    src = SourceFile(path="src/server.py", content="print('hi')")
    supplied = "sha256:" + src.content_hash.removeprefix("sha256:").upper()

    validated = SourceFile(path="src/server.py", content="print('hi')", content_hash=supplied)

    assert validated.content_hash == src.content_hash


def test_source_file_accepts_empty_content_with_valid_hash():
    # If content is empty, but a valid hash is provided, it should be accepted (State Diet)
    h = "sha256:" + "a" * 64
    sf = SourceFile(path="src/server.py", content="", content_hash=h)
    assert sf.content == ""
    assert sf.content_hash == h


def test_content_chunk_rejects_invalid_offsets_and_line_ranges():
    valid_chunk = {
        "chunk_id": "chunk-1",
        "file_path": "src/server.py",
        "content": "print('hi')",
        "start_byte": 0,
        "end_byte": 11,
        "line_start": 1,
        "line_end": 1,
        "is_partial": False,
        "content_hash": "sha256:abc",
    }

    invalid_values = [
        {"start_byte": -1},
        {"end_byte": -1},
        {"line_start": 0},
        {"line_end": 0},
        {"start_byte": 12},
        {"line_start": 2},
    ]

    for invalid_value in invalid_values:
        with pytest.raises(ValidationError):
            ContentChunk.model_validate(valid_chunk | invalid_value)


def test_analysis_result_requires_evidence_task_results():
    result = AnalysisResult.model_validate(
        {
            "analysis_status": "insufficient_evidence",
            "agent_type": "MCP",
            "tech_stack_summary": {"ko": "Python 기반", "en": "Python based"},
            "analysis_claims": [],
            "evidence_signals": [],
            "evidence_task_results": [],
            "risk_signals": [],
            "follow_up_guide": {"ko": "README와 src를 확인하세요.", "en": "Check README and src."},
            "analysis_limitations": {"missing_inputs": ["source_files"], "notes": ["limited analysis"]},
        }
    )
    assert result.analysis_status == "insufficient_evidence"


def test_claim_verdict_enum_matches_contract():
    verdict = ClaimVerdict(
        claim_id="claim-1",
        verdict="INSUFFICIENT_EVIDENCE",
        reason="Source content unavailable.",
        evidence_signal_ids=[],
        limitations=["gitingest failed"],
    )
    assert verdict.verdict == "INSUFFICIENT_EVIDENCE"


@pytest.mark.parametrize("confidence", [-0.1, 1.1])
def test_analysis_claim_rejects_confidence_outside_unit_interval(confidence):
    with pytest.raises(ValidationError):
        AnalysisResult.model_validate(
            {
                "analysis_status": "completed",
                "agent_type": "MCP",
                "tech_stack_summary": {"ko": "Python 기반", "en": "Python based"},
                "analysis_claims": [
                    {
                        "claim_id": "claim-1",
                        "claim_text": "Provides an MCP server.",
                        "confidence": confidence,
                    }
                ],
                "evidence_signals": [],
                "evidence_task_results": [],
                "risk_signals": [],
                "follow_up_guide": {"ko": "README를 확인하세요.", "en": "Check README."},
                "analysis_limitations": {"missing_inputs": [], "notes": []},
            }
        )


@pytest.mark.parametrize("confidence", [-0.1, 1.1])
def test_evidence_signal_rejects_confidence_outside_unit_interval(confidence):
    with pytest.raises(ValidationError):
        AnalysisResult.model_validate(
            {
                "analysis_status": "completed",
                "agent_type": "MCP",
                "tech_stack_summary": {"ko": "Python 기반", "en": "Python based"},
                "analysis_claims": [],
                "evidence_signals": [
                    {
                        "signal_id": "signal-1",
                        "signal_type": "source",
                        "path": "src/server.py",
                        "summary": "Server entrypoint.",
                        "confidence": confidence,
                    }
                ],
                "evidence_task_results": [],
                "risk_signals": [],
                "follow_up_guide": {"ko": "README를 확인하세요.", "en": "Check README."},
                "analysis_limitations": {"missing_inputs": [], "notes": []},
            }
        )
