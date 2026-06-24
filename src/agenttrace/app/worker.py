from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from agenttrace.config import get_settings
from agenttrace.services.database import PsycopgSqlConnection, init_database
from agenttrace.services.analysis_jobs import PostgresAnalysisJobStore, DurableAnalysisWorker
from agenttrace.agents.analysis.graph import build_graph
from agenttrace.api.analysis import AnalysisRequest, _compat_result_json
from agenttrace.logging_config import setup_logging, get_logger

logger = get_logger(__name__)


async def run_analysis_pipeline(job: dict[str, Any]) -> dict[str, Any]:
    _t = time.perf_counter()
    run_id = str(job["job_id"])
    analysis_id = str(job["analysis_id"]) if job.get("analysis_id") else run_id
    repo_id = str(job.get("repository_id", ""))
    log = logger.bind(run_id=run_id, analysis_id=analysis_id, repository_id=repo_id)
    log.info("잡 처리 시작")

    try:
        settings = get_settings()
        conn = PsycopgSqlConnection(settings.database_url)

        # Defensive insert for repositories and snapshots to prevent foreign key errors in transient worker runs
        try:
            repo_id_db = str(job["repository_id"]) if job.get("repository_id") else None
            snap_id = str(job["snapshot_id"]) if job.get("snapshot_id") else None
            if repo_id_db:
                import hashlib
                github_id = int(hashlib.md5(repo_id_db.encode()).hexdigest()[:15], 16)
                temp_name = f"temp_{repo_id_db}"
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
                        "repo_id": repo_id_db,
                        "github_id": github_id,
                        "full_name": temp_name,
                        "owner": "temp_owner",
                        "name": temp_name
                    }
                )
            if snap_id and repo_id_db:
                conn.execute(
                    """
                    INSERT INTO repository_snapshots (snapshot_id, repository_id, commit_sha, captured_at)
                    VALUES (%(snap_id)s, %(repo_id)s, 'main', now())
                    ON CONFLICT (snapshot_id) DO NOTHING
                    """,
                    {"snap_id": snap_id, "repo_id": repo_id_db}
                )
        except Exception as insert_exc:
            log.warning("Defensive insert of parent records failed in worker", error=str(insert_exc))
        
        # Try fetching repository details from DB
        repo_name = "unknown/repository"
        try:
            repo_rows = conn.execute(
                "SELECT * FROM repositories WHERE id = %(repository_id)s",
                {"repository_id": job["repository_id"]}
            )
            if repo_rows and repo_rows[0].get("full_name"):
                repo_name = repo_rows[0]["full_name"]
        except Exception as exc:
            log.debug("Could not fetch repository from db, fallback to default", error=str(exc))
            
        # Try fetching snapshot details from DB
        commit_sha = "main"
        try:
            snap_rows = conn.execute(
                "SELECT * FROM repository_snapshots WHERE snapshot_id = %(snapshot_id)s",
                {"snapshot_id": job["snapshot_id"]}
            )
            if snap_rows and snap_rows[0].get("commit_sha"):
                commit_sha = snap_rows[0]["commit_sha"]
        except Exception as exc:
            log.debug("Could not fetch snapshot from db, fallback to default", error=str(exc))

        github_url = f"https://github.com/{repo_name}"
        
        # Create request object compatible with API
        request = AnalysisRequest(
            analysis_id=analysis_id,
            repository_id=job["repository_id"],
            snapshot_id=job["snapshot_id"],
            commit_sha=commit_sha,
            github_url=github_url,
            source_files=[],
        )
        
        input_req = await request.to_input_request()
        
        from agenttrace.services.content_indices import PostgresContentIndexStore
        from agenttrace.services.embeddings import PostgresChunkEmbeddingStore, build_openai_embedding_service
        
        content_index_store = PostgresContentIndexStore(conn)
        embedding_store = PostgresChunkEmbeddingStore(conn)
        embedding_service = build_openai_embedding_service(settings)

        graph = build_graph(
            content_index_store=content_index_store,
            embedding_service=embedding_service,
            embedding_store=embedding_store,
        )
        
        log.info("Worker executing analysis graph pipeline")
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
        
        payload = result.get("callback_payload")
        if not payload:
            raise RuntimeError("Pipeline finished but did not return callback_payload")
            
        if payload.get("analysis_result") is not None:
            payload["result_json"] = _compat_result_json(payload["analysis_result"], input_req)
            
        # Persist analysis results to DB
        from agenttrace.services.content_indices import PostgresAnalysisPersistenceStore
        persistence_store = PostgresAnalysisPersistenceStore(conn)
        
        analysis_data = {
            "repository_id": str(job["repository_id"]),
            "snapshot_id": str(job["snapshot_id"]),
            "analysis_version": job["analysis_version"],
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
            "analysis_id": analysis_id,
            "lang": payload.get("analysis_report", {}).get("lang", "ko"),
            "title": payload.get("analysis_report", {}).get("title", "AgentTrace 기술 분석 보고서"),
            "body_markdown": payload.get("analysis_report", {}).get("body_markdown", ""),
        }
        
        persistence_store.persist_analysis(analysis=analysis_data, report=report_data)
        
        duration_ms = int((time.perf_counter() - _t) * 1000)
        log.info("잡 처리 완료", status=payload.get("status", "COMPLETED"), duration_ms=duration_ms)
        
        return {
            "analysis_id": analysis_id,
            "status": payload.get("status", "COMPLETED"),
        }
    except Exception as exc:
        duration_ms = int((time.perf_counter() - _t) * 1000)
        log.error("잡 처리 실패", error=str(exc), duration_ms=duration_ms, exc_info=True)
        raise

def worker_runner(job: dict[str, Any]) -> dict[str, Any]:
    return asyncio.run(run_analysis_pipeline(job))

def main() -> None:
    setup_logging()
    logger.info("Starting AgentTrace Durable Analysis Worker...")

    
    settings = get_settings()
    init_database(settings.database_url)
    
    conn = PsycopgSqlConnection(settings.database_url)
    store = PostgresAnalysisJobStore(conn)
    worker = DurableAnalysisWorker(store, runner=worker_runner)
    
    # 1. Clean up stale jobs once at startup
    try:
        stale_jobs = store.fail_stale_running_jobs()
        if stale_jobs:
            logger.info("Stale running jobs cleaned up: %d jobs affected.", len(stale_jobs))
    except Exception as exc:
        logger.warning("Stale jobs clean up failed: %s", exc)
        
    logger.info("Worker daemon loop active. Awaiting jobs...")
    while True:
        try:
            res = worker.run_once()
            if res["status"] != "idle":
                logger.info("Processed task status: %s", res["status"])
                continue
        except Exception as exc:
            logger.error("Error in worker daemon iteration: %s", exc, exc_info=True)
            
        time.sleep(5)

if __name__ == "__main__":
    main()
