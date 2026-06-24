from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx
from fastapi import APIRouter, BackgroundTasks, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, UUID4

from agenttrace.agents.analysis.graph import build_graph
from agenttrace.agents.analysis.schemas.input import AnalysisInputRequest
from agenttrace.config import get_settings
from agenttrace.services.analysis_jobs import InMemoryAnalysisJobStore
from agenttrace.services.repo_ingest import (
    _github_full_name,
    fetch_repo_digest,
    repo_digest_to_summary_request,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/analysis", tags=["analysis"])
repository_router = APIRouter(prefix="/api/v1/repositories", tags=["analysis"])
active_analyses = set()
analysis_job_store = InMemoryAnalysisJobStore()


def init_api_stores(database_url: str) -> None:
    global analysis_job_store
    from agenttrace.services.database import PsycopgSqlConnection
    from agenttrace.services.analysis_jobs import PostgresAnalysisJobStore
    conn = PsycopgSqlConnection(database_url)
    analysis_job_store = PostgresAnalysisJobStore(conn)



class AnalysisRequest(BaseModel):
    analysis_id: UUID4
    repository: dict[str, Any] | None = None
    snapshot: dict[str, Any] | None = None
    readme_text: str | None = None
    file_tree: list[str] = Field(default_factory=list)
    summary_result: dict[str, Any] = Field(default_factory=dict)
    source_files: list[dict[str, Any]] = Field(default_factory=list)
    external_ingest: dict[str, Any] = Field(default_factory=lambda: {"enabled": get_settings().external_ingest_enabled, "provider": "gitingest"})

    # Legacy Backend payload
    repository_id: UUID4 | None = None
    snapshot_id: UUID4 | None = None
    commit_sha: str | None = None
    github_url: str | None = None

    async def to_input_request(self) -> AnalysisInputRequest:
        if self.repository:
            return AnalysisInputRequest.model_validate(self.model_dump(mode="json", exclude_none=True))

        if not self.github_url:
            raise ValueError("github_url is required for legacy analysis requests")

        full_name = _github_full_name(self.github_url)
        digest = await asyncio.to_thread(fetch_repo_digest, full_name)
        summary_req = repo_digest_to_summary_request(digest, fallback_full_name=full_name)
        file_tree = [path.rstrip("/") for path in summary_req.shallow_file_tree if path.rstrip("/")]
        return AnalysisInputRequest.model_validate({
            "analysis_id": str(self.analysis_id),
            "repository": {
                "repository_id": str(self.repository_id) if self.repository_id else None,
                "full_name": summary_req.repository.full_name,
                "github_url": summary_req.repository.github_url or self.github_url,
                "description": summary_req.repository.description,
                "primary_language": summary_req.repository.primary_language,
                "topics": summary_req.repository.topics,
            },
            "snapshot": {
                "snapshot_id": str(self.snapshot_id) if self.snapshot_id else None,
                "commit_sha": self.commit_sha,
            },
            "readme_text": summary_req.readme_text,
            "file_tree": file_tree,
            "summary_result": {},
            "source_files": [],
            "external_ingest": {"enabled": get_settings().external_ingest_enabled, "provider": "gitingest"},
        })


class RepositoryAnalysisTriggerRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    snapshot_id: UUID4 = Field(alias="snapshotId")
    commit_sha: str = Field(alias="commitSha")
    github_url: str = Field(alias="githubUrl")
    analysis_version: str = Field(default="analysis-v2", alias="analysisVersion")
    source_files: list[dict[str, Any]] = Field(default_factory=list, alias="sourceFiles")


class AnalysisTriggerResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    job_id: str | None = Field(alias="jobId")
    analysis_id: str | None = Field(alias="analysisId")
    status: str
    is_cached: bool = Field(alias="isCached")
    requested_at: str = Field(alias="requestedAt")


class AnalysisStatusResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    job_id: str = Field(alias="jobId")
    analysis_id: str | None = Field(alias="analysisId")
    status: str
    error_message: str | None = Field(alias="errorMessage")
    updated_at: str = Field(alias="updatedAt")


class AnalysisReportResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    analysis_id: str = Field(alias="analysisId")
    lang: str
    title: str
    body_markdown: str = Field(alias="bodyMarkdown")
    generated_at: str = Field(alias="generatedAt")


def _failure_payload(req: AnalysisRequest, exc: Exception) -> dict[str, Any]:
    return {
        "analysis_id": str(req.analysis_id),
        "status": "FAILED",
        "analysis_result": None,
        "result_json": {
            "agent_type": "UNKNOWN",
            "tech_stack_summary": {},
            "claims": [],
            "limitations": [],
            "missing_evidence": [],
            "followup_questions": [],
        },
        "error_message": str(exc),
    }


def _compat_result_json(analysis_result: dict[str, Any], input_req: AnalysisInputRequest) -> dict[str, Any]:
    agent_type_map = {
        "MCP": "MCP_SERVER",
        "Skill": "SKILL",
        "Eval": "EVAL_HARNESS",
        "ToolUse": "TOOL_USE",
        "Framework": "AGENT_FRAMEWORK",
        "Other": "OTHER",
        "Unknown": "UNKNOWN",
        None: "UNKNOWN",
    }
    evidence_by_id = {
        signal.get("signal_id"): signal
        for signal in analysis_result.get("evidence_signals", [])
    }
    verdict_by_claim = {}
    for task in analysis_result.get("evidence_task_results", []):
        for verdict in task.get("claim_verdicts", []):
            verdict_by_claim[verdict.get("claim_id")] = verdict

    claims = []
    for claim in analysis_result.get("analysis_claims", []):
        verdict = verdict_by_claim.get(claim.get("claim_id"), {})
        evidence_paths = [
            evidence_by_id.get(signal_id, {}).get("path")
            for signal_id in verdict.get("evidence_signal_ids", [])
        ]
        claims.append({
            "claim_text": claim.get("claim_text", ""),
            "evidence_status": verdict.get("verdict", "INSUFFICIENT_EVIDENCE"),
            "confidence_level": str(claim.get("confidence", 0.0)),
            "supporting_evidence": [path for path in evidence_paths if path],
            "limitation": "; ".join(verdict.get("limitations", [])) or None,
        })

    if not claims:
        evidence_paths = [
            ref.get("path")
            for ref in analysis_result.get("evidence_refs", [])
            if ref.get("path")
        ]
        for area in analysis_result.get("area_findings", []):
            area_status = area.get("status", "unconfirmed")
            evidence_status = (
                "SUPPORTED"
                if area_status == "confirmed"
                else "PARTIALLY_SUPPORTED"
                if area_status == "partially_confirmed"
                else "INSUFFICIENT_EVIDENCE"
            )
            claim_text = area.get("summary") or area.get("area_name") or area.get("area_id") or ""
            limitations = area.get("limitations", [])
            claims.append({
                "claim_text": claim_text,
                "evidence_status": evidence_status,
                "confidence_level": "0.8" if area_status == "confirmed" else "0.5",
                "supporting_evidence": evidence_paths,
                "limitation": "; ".join(limitations) or None,
            })

    limitations = analysis_result.get("analysis_limitations", {})
    agent_type = agent_type_map.get(analysis_result.get("agent_type"), "Unknown")
    if agent_type == "UNKNOWN":
        text = " ".join([
            input_req.repository.full_name,
            input_req.repository.description or "",
            " ".join(input_req.repository.topics),
            input_req.readme_text or "",
        ]).lower()
        if "harness" in text or "eval" in text or "benchmark" in text:
            agent_type = "EVAL_HARNESS"
        elif "mcp" in text:
            agent_type = "MCP_SERVER"
        elif "skill" in text:
            agent_type = "SKILL"

    return {
        "agent_type": agent_type,
        "tech_stack_summary": {
            "primary_language": input_req.repository.primary_language,
            "topics": input_req.repository.topics,
            "description": input_req.repository.description,
        },
        "claims": claims,
        "limitations": limitations.get("notes", []) + limitations.get("missing_inputs", []),
        "missing_evidence": [
            claim["claim_text"]
            for claim in claims
            if claim["evidence_status"] == "INSUFFICIENT_EVIDENCE"
        ],
        "followup_questions": [],
    }


async def run_pipeline_async(req: AnalysisRequest) -> None:
    from pathlib import Path
    run_id = str(req.analysis_id)
    local_repo_dir = Path("tmp/agenttrace") / run_id
    try:
        logger.info("Starting async analysis pipeline for run_id=%s", req.analysis_id)
        input_req = await req.to_input_request()

        settings = get_settings()
        from agenttrace.services.database import PsycopgSqlConnection, init_database
        from agenttrace.services.content_indices import PostgresContentIndexStore, PostgresAnalysisPersistenceStore
        from agenttrace.services.embeddings import PostgresChunkEmbeddingStore, build_openai_embedding_service

        init_database(settings.database_url)
        conn = PsycopgSqlConnection(settings.database_url)

        # Defensive insert for repositories and snapshots to prevent foreign key errors in test/transient runs
        try:
            repo_id = str(req.repository_id) if req.repository_id else str(input_req.repository.repository_id) if (input_req.repository and input_req.repository.repository_id) else None
            snap_id = str(req.snapshot_id) if req.snapshot_id else str(input_req.snapshot.snapshot_id) if (input_req.snapshot and input_req.snapshot.snapshot_id) else None
            commit_sha = (input_req.snapshot.commit_sha if input_req.snapshot else None) or req.commit_sha or "main"
            
            if repo_id:
                import hashlib
                github_id = int(hashlib.md5(repo_id.encode()).hexdigest()[:15], 16)
                temp_name = f"temp_{repo_id}"
                conn.execute(
                    """
                    INSERT INTO repositories (
                        id, github_id, full_name, owner, name, 
                        stars, forks, watchers, open_issues, 
                        archived, fork, agent_score, is_agent_related,
                        created_at, updated_at
                    ) VALUES (
                        %(repo_id)s, %(github_id)s, %(full_name)s, %(owner)s, %(name)s,
                        0, 0, 0, 0,
                        false, false, 0, false,
                        now(), now()
                    ) ON CONFLICT DO NOTHING
                    """,
                    {
                        "repo_id": repo_id,
                        "github_id": github_id,
                        "full_name": temp_name,
                        "owner": "temp_owner",
                        "name": temp_name
                    }
                )
            if snap_id and repo_id:
                conn.execute(
                    """
                    INSERT INTO repository_snapshots (snapshot_id, repository_id, commit_sha, captured_at)
                    VALUES (%(snap_id)s, %(repo_id)s, %(commit_sha)s, now())
                    ON CONFLICT (snapshot_id) DO NOTHING
                    """,
                    {"snap_id": snap_id, "repo_id": repo_id, "commit_sha": commit_sha}
                )
        except Exception as insert_exc:
            logger.warning("Defensive insert of parent records failed: %s", insert_exc)

        content_index_store = PostgresContentIndexStore(conn)
        embedding_store = PostgresChunkEmbeddingStore(conn)
        embedding_service = build_openai_embedding_service(settings)

        graph = build_graph(
            content_index_store=content_index_store,
            embedding_service=embedding_service,
            embedding_store=embedding_store,
        )
        result = await asyncio.to_thread(
            graph.invoke,
            {
                "run_id": run_id,
                "analysis_request": input_req.model_dump(mode="json"),
                "evidence_signals": [],
                "risk_signals": [],
                "quality_warnings": [],
                "quality_errors": [],
            },
        )
        print("LANGGRAPH RESULT:", result)
        payload = result.get("callback_payload") or _failure_payload(req, RuntimeError("missing callback payload"))
        if payload.get("analysis_result") is not None:
            payload["result_json"] = _compat_result_json(payload["analysis_result"], input_req)

        # Save actual analysis results to Postgres DB
        try:
            persistence_store = PostgresAnalysisPersistenceStore(conn)
            analysis_data = {
                "analysis_id": run_id,
                "repository_id": str(req.repository_id) if req.repository_id else str(input_req.repository.repository_id) if input_req.repository.repository_id else None,
                "snapshot_id": str(req.snapshot_id) if req.snapshot_id else str(input_req.snapshot.snapshot_id) if input_req.snapshot.snapshot_id else None,
                "analysis_version": "analysis-v2",
                "status": payload.get("status", "COMPLETED").lower(),
                "agent_type": {
                    "MCP_SERVER": "MCP",
                    "SKILL": "Skill",
                    "EVAL_HARNESS": "Eval",
                    "TOOL_USE": "ToolUse",
                    "AGENT_FRAMEWORK": "Framework",
                    "OTHER": "Other",
                    "UNKNOWN": "Unknown"
                }.get(payload.get("result_json", {}).get("agent_type"), "Unknown"),
                "result_json": payload.get("result_json", {}),
                "model_name": settings.analysis_model,
                "prompt_version": "v2",
            }
            report_data = {
                "analysis_id": run_id,
                "lang": payload.get("analysis_report", {}).get("lang", "ko"),
                "title": payload.get("analysis_report", {}).get("title", "AgentTrace 기술 분석 보고서"),
                "body_markdown": payload.get("analysis_report", {}).get("body_markdown", ""),
            }
            persistence_store.persist_analysis(analysis=analysis_data, report=report_data)
            logger.info("Successfully persisted analysis results to DB for run_id=%s", req.analysis_id)
        except Exception as db_exc:
            logger.error("Failed to persist analysis results to DB for run_id=%s: %s", req.analysis_id, db_exc)

        await asyncio.to_thread(httpx.post, settings.agents_callback_url, json=payload, timeout=10.0)
        logger.info("Successfully completed analysis pipeline for run_id=%s", req.analysis_id)
    except Exception as exc:
        logger.error("Analysis pipeline failed for run_id=%s: %s", req.analysis_id, exc, exc_info=True)
        settings = get_settings()
        payload = _failure_payload(req, exc)
        try:
            await asyncio.to_thread(httpx.post, settings.agents_callback_url, json=payload, timeout=10.0)
        except Exception as callback_exc:
            logger.error("Failed to send failure callback: %s", callback_exc)
        raise
    finally:
        import shutil
        if local_repo_dir.exists():
            shutil.rmtree(local_repo_dir, ignore_errors=True)
        active_analyses.discard(str(req.analysis_id))


async def run_repository_pipeline_async(job_id: str, req: AnalysisRequest) -> None:
    try:
        await run_pipeline_async(req)
    except Exception as exc:
        analysis_job_store.mark_failed(job_id, error_message=str(exc))
        raise
    else:
        analysis_job_store.mark_completed(job_id, status="completed")


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def trigger_analysis(
    request: AnalysisRequest,
    background_tasks: BackgroundTasks,
) -> dict[str, str]:
    analysis_id_str = str(request.analysis_id)
    if analysis_id_str in active_analyses:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Analysis already in progress for this analysis_id.",
        )
    active_analyses.add(analysis_id_str)

    background_tasks.add_task(run_pipeline_async, request)
    return {"status": "queued", "message": "Analysis started asynchronously."}


@repository_router.post("/{repository_id}/analysis", status_code=status.HTTP_202_ACCEPTED)
async def trigger_repository_analysis(
    repository_id: UUID4,
    request: RepositoryAnalysisTriggerRequest,
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    requested = analysis_job_store.request_analysis(
        repository_id=str(repository_id),
        snapshot_id=str(request.snapshot_id),
        analysis_version=request.analysis_version,
    )
    if requested.is_cached or requested.job_id is None:
        return AnalysisTriggerResponse(
            job_id=requested.job_id,
            analysis_id=requested.analysis_id,
            status=requested.status,
            is_cached=requested.is_cached,
            requested_at=requested.requested_at,
        ).model_dump(by_alias=True)

    analysis_request = AnalysisRequest(
        analysis_id=requested.job_id,
        repository_id=repository_id,
        snapshot_id=request.snapshot_id,
        commit_sha=request.commit_sha,
        github_url=request.github_url,
        source_files=request.source_files,
        external_ingest={"enabled": get_settings().external_ingest_enabled, "provider": "gitingest"},
    )
    if requested.should_start:
        active_analyses.add(requested.job_id)
        background_tasks.add_task(run_repository_pipeline_async, requested.job_id, analysis_request)
    return AnalysisTriggerResponse(
        job_id=requested.job_id,
        analysis_id=requested.analysis_id,
        status=requested.status,
        is_cached=requested.is_cached,
        requested_at=requested.requested_at,
    ).model_dump(by_alias=True)


@repository_router.get("/{repository_id}/analysis")
async def get_repository_analysis(
    repository_id: UUID4,
    analysisId: UUID4 | None = None,
) -> dict[str, Any]:
    analysis = analysis_job_store.get_analysis(
        repository_id=str(repository_id),
        analysis_id=str(analysisId) if analysisId else None,
    )
    if not analysis:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis result not found.")
    return analysis


@repository_router.get("/{repository_id}/analysis/status")
async def get_repository_analysis_status(repository_id: UUID4, jobId: UUID4) -> dict[str, Any]:
    job = analysis_job_store.get_status(repository_id=str(repository_id), job_id=str(jobId))
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis job not found.")
    return AnalysisStatusResponse(
        job_id=job["jobId"],
        analysis_id=job["analysisId"],
        status=job["status"],
        error_message=job["errorMessage"],
        updated_at=job["updatedAt"],
    ).model_dump(by_alias=True)


@repository_router.get("/{repository_id}/analysis/report")
async def get_repository_analysis_report(
    repository_id: UUID4,
    analysisId: UUID4 | None = None,
    lang: str = "ko",
) -> dict[str, Any]:
    report = analysis_job_store.get_report(
        repository_id=str(repository_id),
        analysis_id=str(analysisId) if analysisId else None,
        lang=lang,
    )
    if not report:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis report not found.")
    return AnalysisReportResponse.model_validate(report).model_dump(by_alias=True)
