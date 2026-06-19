from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx
from fastapi import APIRouter, BackgroundTasks, HTTPException, status
from pydantic import BaseModel, UUID4

from agenttrace.agents.analysis.graph import build_graph
from agenttrace.config import get_settings
from agenttrace.services.repo_ingest import (
    fetch_repo_digest,
    repo_digest_to_summary_request,
    _github_full_name,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/analysis", tags=["analysis"])
active_analyses = set()


class AnalysisRequest(BaseModel):
    analysis_id: UUID4
    repository_id: UUID4
    snapshot_id: UUID4
    commit_sha: str
    github_url: str


async def run_pipeline_async(req: AnalysisRequest) -> None:
    try:
        logger.info(f"Starting async analysis pipeline for run_id={req.analysis_id}")
        
        full_name = _github_full_name(req.github_url)
        digest = await asyncio.to_thread(fetch_repo_digest, full_name)
        summary_req = repo_digest_to_summary_request(digest, fallback_full_name=full_name)
        
        file_tree_list = []
        for p in summary_req.shallow_file_tree:
            is_dir = p.endswith("/")
            clean_p = p.rstrip("/")
            if clean_p:
                file_tree_list.append({
                    "path": clean_p,
                    "type": "directory" if is_dir else "file"
                })
                
        snapshot = {
            "repository_id": str(req.repository_id),
            "full_name": summary_req.repository.full_name,
            "github_url": summary_req.repository.github_url,
            "metadata": summary_req.repository.model_dump(),
            "readme": summary_req.readme_text,
            "file_tree": file_tree_list,
            "selected_files": [],
        }
        
        graph = build_graph()
        initial_state = {
            "run_id": str(req.analysis_id),
            "repository_id": str(req.repository_id),
            "full_name": summary_req.repository.full_name,
            "github_url": req.github_url,
            "commit_sha": req.commit_sha,
            "trigger": "NEW_REPO",
            "repository_snapshot": snapshot,
            "claims": [],
            "evidence_signals": [],
            "risk_signals": [],
            "quality_warnings": [],
            "quality_errors": [],
            "retry_count": 0,
        }
        
        await asyncio.to_thread(graph.invoke, initial_state)
        logger.info(f"Successfully completed analysis pipeline for run_id={req.analysis_id}")
        
    except Exception as exc:
        logger.error(f"Analysis pipeline failed for run_id={req.analysis_id}: {exc}", exc_info=True)
        
        settings = get_settings()
        callback_url = settings.agents_callback_url
        
        default_result_json = {
            "agent_type": "UNKNOWN",
            "tech_stack_summary": {},
            "claims": [],
            "limitations": [],
            "missing_evidence": [],
            "followup_questions": []
        }
        
        payload = {
            "analysis_id": str(req.analysis_id),
            "status": "FAILED",
            "result_json": default_result_json,
            "error_message": str(exc),
        }
        
        try:
            await asyncio.to_thread(httpx.post, callback_url, json=payload, timeout=10.0)
        except Exception as callback_exc:
            logger.error(f"Failed to send failure callback: {callback_exc}")
            
        raise
        
    finally:
        active_analyses.discard(str(req.analysis_id))


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
