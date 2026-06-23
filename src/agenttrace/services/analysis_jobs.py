from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Callable, Literal, Protocol


AnalysisJobStatus = Literal["queued", "running", "completed", "completed_with_limitations", "failed"]

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


class SqlConnection(Protocol):
    def execute(self, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        ...


@dataclass(frozen=True)
class AnalysisRequestRecord:
    job_id: str | None
    analysis_id: str | None
    status: AnalysisJobStatus
    is_cached: bool
    requested_at: str
    should_start: bool = False


class InMemoryAnalysisJobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, dict[str, Any]] = {}
        self._latest_by_key: dict[tuple[str, str, str], str] = {}

    def request_analysis(
        self,
        *,
        repository_id: str,
        snapshot_id: str,
        analysis_version: str,
    ) -> AnalysisRequestRecord:
        now = _utc_now()
        key = (repository_id, snapshot_id, analysis_version)
        existing_job_id = self._latest_by_key.get(key)
        if existing_job_id:
            existing = self._jobs[existing_job_id]
            if existing["status"] in {"completed", "completed_with_limitations"}:
                return AnalysisRequestRecord(
                    job_id=None,
                    analysis_id=existing["analysisId"],
                    status=existing["status"],
                    is_cached=True,
                    requested_at=now,
                    should_start=False,
                )
            if existing["status"] in {"queued", "running"}:
                return AnalysisRequestRecord(
                    job_id=existing["jobId"],
                    analysis_id=None,
                    status=existing["status"],
                    is_cached=False,
                    requested_at=now,
                    should_start=False,
                )

        job_id = str(uuid.uuid4())
        analysis_id = str(uuid.uuid4())
        self._jobs[job_id] = {
            "jobId": job_id,
            "analysisId": None,
            "pendingAnalysisId": analysis_id,
            "repositoryId": repository_id,
            "snapshotId": snapshot_id,
            "analysisVersion": analysis_version,
            "status": "queued",
            "errorMessage": None,
            "updatedAt": now,
            "report": _default_report(analysis_id=analysis_id, generated_at=now),
        }
        self._latest_by_key[key] = job_id
        return AnalysisRequestRecord(
            job_id=job_id,
            analysis_id=None,
            status="queued",
            is_cached=False,
            requested_at=now,
            should_start=True,
        )

    def get_status(self, *, repository_id: str, job_id: str) -> dict[str, Any] | None:
        job = self._jobs.get(job_id)
        if not job or job["repositoryId"] != repository_id:
            return None
        return {
            "jobId": job["jobId"],
            "analysisId": job["analysisId"],
            "status": job["status"],
            "errorMessage": job["errorMessage"],
            "updatedAt": job["updatedAt"],
        }

    def get_report(self, *, repository_id: str, analysis_id: str | None, lang: str) -> dict[str, Any] | None:
        del analysis_id
        for job in reversed(list(self._jobs.values())):
            if job["repositoryId"] == repository_id:
                report = dict(job["report"])
                report["lang"] = lang
                return report
        return None

    def get_analysis(self, *, repository_id: str, analysis_id: str | None) -> dict[str, Any] | None:
        del analysis_id
        for job in reversed(list(self._jobs.values())):
            if job["repositoryId"] == repository_id:
                return _default_analysis(job)
        return None

    def mark_completed(
        self,
        job_id: str,
        *,
        analysis_id: str | None = None,
        status: Literal["completed", "completed_with_limitations"] = "completed",
    ) -> None:
        job = self._jobs[job_id]
        job["status"] = status
        job["analysisId"] = analysis_id or job["pendingAnalysisId"]
        job["updatedAt"] = _utc_now()

    def mark_failed(self, job_id: str, *, error_message: str) -> None:
        job = self._jobs[job_id]
        job["status"] = "failed"
        job["errorMessage"] = error_message
        job["updatedAt"] = _utc_now()


class PostgresAnalysisJobSql:
    @staticmethod
    def request_analysis() -> dict[str, str]:
        return {
            "find_completed": """
                SELECT analysis_id, status
                FROM agenttrace_repository_analyses
                WHERE repository_id = %(repository_id)s
                  AND snapshot_id = %(snapshot_id)s
                  AND analysis_version = %(analysis_version)s
                  AND status IN ('completed', 'completed_with_limitations')
                ORDER BY analysis_completed_at DESC NULLS LAST, created_at DESC
                LIMIT 1
            """.strip(),
            "find_running": """
                SELECT job_id, analysis_id, status
                FROM analysis_jobs
                WHERE repository_id = %(repository_id)s
                  AND snapshot_id = %(snapshot_id)s
                  AND analysis_version = %(analysis_version)s
                  AND status IN ('QUEUED', 'RUNNING')
                ORDER BY created_at ASC
                LIMIT 1
            """.strip(),
            "insert_job": """
                INSERT INTO analysis_jobs (
                    repository_id,
                    snapshot_id,
                    analysis_version,
                    status,
                    created_at,
                    updated_at
                )
                VALUES (
                    %(repository_id)s,
                    %(snapshot_id)s,
                    %(analysis_version)s,
                    'QUEUED',
                    now(),
                    now()
                )
                RETURNING job_id, analysis_id, status, created_at
            """.strip(),
        }

    @staticmethod
    def claim_next_job() -> str:
        return """
            WITH next_job AS (
                SELECT job_id
                FROM analysis_jobs
                WHERE status = 'QUEUED'
                ORDER BY created_at ASC
                FOR UPDATE SKIP LOCKED
                LIMIT 1
            )
            UPDATE analysis_jobs
            SET status = 'RUNNING',
                started_at = COALESCE(started_at, now()),
                heartbeat_at = now(),
                updated_at = now()
            FROM next_job
            WHERE analysis_jobs.job_id = next_job.job_id
            RETURNING analysis_jobs.*
        """.strip()

    @staticmethod
    def refresh_heartbeat() -> str:
        return """
            UPDATE analysis_jobs
            SET heartbeat_at = now(),
                updated_at = now()
            WHERE job_id = %(job_id)s
              AND status = 'RUNNING'
            RETURNING job_id, heartbeat_at
        """.strip()

    @staticmethod
    def complete_job() -> str:
        return """
            UPDATE analysis_jobs
            SET status = %(status)s,
                analysis_id = %(analysis_id)s,
                updated_at = now()
            WHERE job_id = %(job_id)s
              AND status = 'RUNNING'
            RETURNING job_id, analysis_id, status, updated_at
        """.strip()

    @staticmethod
    def fail_job() -> str:
        return """
            UPDATE analysis_jobs
            SET status = 'FAILED',
                error_message = %(error_message)s,
                updated_at = now()
            WHERE job_id = %(job_id)s
            RETURNING job_id, status, error_message, updated_at
        """.strip()

    @staticmethod
    def fail_stale_running_jobs() -> str:
        return """
            UPDATE analysis_jobs
            SET status = 'FAILED',
                error_message = COALESCE(error_message, 'Analysis worker heartbeat timed out.'),
                updated_at = now()
            WHERE status = 'RUNNING'
              AND heartbeat_at < now() - interval '5 minutes'
            RETURNING job_id, status, error_message, updated_at
        """.strip()


class PostgresAnalysisJobStore:
    def __init__(self, connection: SqlConnection) -> None:
        self._connection = connection

    def request_analysis(
        self,
        *,
        repository_id: str,
        snapshot_id: str,
        analysis_version: str,
    ) -> AnalysisRequestRecord:
        params = {
            "repository_id": repository_id,
            "snapshot_id": snapshot_id,
            "analysis_version": analysis_version,
        }
        sqls = PostgresAnalysisJobSql.request_analysis()
        completed = self._connection.execute(sqls["find_completed"], params)
        if completed:
            return AnalysisRequestRecord(
                job_id=None,
                analysis_id=str(completed[0]["analysis_id"]),
                status=completed[0]["status"],
                is_cached=True,
                requested_at=_utc_now(),
                should_start=False,
            )
        running = self._connection.execute(sqls["find_running"], params)
        if running:
            return AnalysisRequestRecord(
                job_id=str(running[0]["job_id"]),
                analysis_id=None,
                status=running[0]["status"].lower(),
                is_cached=False,
                requested_at=_utc_now(),
                should_start=False,
            )
        new_job = self._connection.execute(sqls["insert_job"], params)
        if new_job:
            return AnalysisRequestRecord(
                job_id=str(new_job[0]["job_id"]),
                analysis_id=None,
                status=new_job[0]["status"].lower(),
                is_cached=False,
                requested_at=_utc_now(),
                should_start=True,
            )
        raise RuntimeError("Failed to request analysis job")

    def get_status(self, *, repository_id: str, job_id: str) -> dict[str, Any] | None:
        sql = """
            SELECT job_id, analysis_id, status, error_message, updated_at
            FROM analysis_jobs
            WHERE repository_id = %(repository_id)s AND job_id = %(job_id)s
        """
        rows = self._connection.execute(sql, {"repository_id": repository_id, "job_id": job_id})
        if not rows:
            return None
        job = rows[0]
        return {
            "jobId": str(job["job_id"]),
            "analysisId": str(job["analysis_id"]) if job["analysis_id"] else None,
            "status": job["status"].lower(),
            "errorMessage": job["error_message"],
            "updatedAt": job["updated_at"].isoformat() if hasattr(job["updated_at"], "isoformat") else str(job["updated_at"]),
        }

    def get_analysis(self, *, repository_id: str, analysis_id: str | None) -> dict[str, Any] | None:
        if analysis_id:
            sql = """
                SELECT * FROM agenttrace_repository_analyses
                WHERE repository_id = %(repository_id)s AND analysis_id = %(analysis_id)s
            """
            params = {"repository_id": repository_id, "analysis_id": analysis_id}
        else:
            sql = """
                SELECT * FROM agenttrace_repository_analyses
                WHERE repository_id = %(repository_id)s
                ORDER BY analysis_completed_at DESC NULLS LAST, created_at DESC
                LIMIT 1
            """
            params = {"repository_id": repository_id}

        rows = self._connection.execute(sql, params)
        if not rows:
            return None
        row = rows[0]
        result = dict(row["result_json"]) if row.get("result_json") else {}
        result.update({
            "analysisId": str(row["analysis_id"]),
            "repositoryId": str(row["repository_id"]),
            "snapshotId": str(row["snapshot_id"]),
            "analysisVersion": row["analysis_version"],
            "status": row["status"],
            "agentType": row["agent_type"],
            "analysisCompletedAt": row["analysis_completed_at"].isoformat() if hasattr(row["analysis_completed_at"], "isoformat") and row["analysis_completed_at"] else str(row["analysis_completed_at"]) if row["analysis_completed_at"] else None,
        })
        return result

    def get_report(self, *, repository_id: str, analysis_id: str | None, lang: str) -> dict[str, Any] | None:
        if analysis_id:
            sql = """
                SELECT r.*, a.analysis_id
                FROM analysis_reports r
                JOIN agenttrace_repository_analyses a ON r.analysis_id = a.analysis_id
                WHERE a.repository_id = %(repository_id)s 
                  AND a.analysis_id = %(analysis_id)s
                  AND r.lang = %(lang)s
            """
            params = {"repository_id": repository_id, "analysis_id": analysis_id, "lang": lang}
        else:
            sql = """
                SELECT r.*, a.analysis_id
                FROM analysis_reports r
                JOIN agenttrace_repository_analyses a ON r.analysis_id = a.analysis_id
                WHERE a.repository_id = %(repository_id)s 
                  AND r.lang = %(lang)s
                ORDER BY r.updated_at DESC, r.created_at DESC
                LIMIT 1
            """
            params = {"repository_id": repository_id, "lang": lang}

        rows = self._connection.execute(sql, params)
        if not rows:
            return None
        row = rows[0]
        return {
            "analysisId": str(row["analysis_id"]),
            "lang": row["lang"],
            "title": row["title"],
            "bodyMarkdown": row["body_markdown"],
            "generatedAt": row["updated_at"].isoformat() if hasattr(row["updated_at"], "isoformat") else str(row["updated_at"]),
        }

    def claim_next_job(self) -> dict[str, Any] | None:
        rows = self._connection.execute(PostgresAnalysisJobSql.claim_next_job())
        return rows[0] if rows else None

    def refresh_heartbeat(self, job_id: str) -> dict[str, Any] | None:
        rows = self._connection.execute(PostgresAnalysisJobSql.refresh_heartbeat(), {"job_id": job_id})
        return rows[0] if rows else None

    def complete_job(
        self,
        *,
        job_id: str,
        analysis_id: str,
        status: Literal["COMPLETED", "COMPLETED_WITH_LIMITATIONS"] = "COMPLETED",
    ) -> dict[str, Any] | None:
        rows = self._connection.execute(
            PostgresAnalysisJobSql.complete_job(),
            {"job_id": job_id, "analysis_id": analysis_id, "status": status},
        )
        return rows[0] if rows else None

    def fail_job(self, *, job_id: str, error_message: str) -> dict[str, Any] | None:
        rows = self._connection.execute(
            PostgresAnalysisJobSql.fail_job(),
            {"job_id": job_id, "error_message": error_message},
        )
        return rows[0] if rows else None

    def fail_stale_running_jobs(self) -> list[dict[str, Any]]:
        return self._connection.execute(PostgresAnalysisJobSql.fail_stale_running_jobs())



AnalysisJobRunner = Callable[[dict[str, Any]], dict[str, Any]]


class DurableAnalysisWorker:
    def __init__(self, store: PostgresAnalysisJobStore, runner: AnalysisJobRunner) -> None:
        self._store = store
        self._runner = runner

    def run_once(self) -> dict[str, Any]:
        job = self._store.claim_next_job()
        if not job:
            return {"status": "idle", "job": None}

        job_id = str(job["job_id"])
        try:
            result = self._runner(job)
            analysis_id = str(result["analysis_id"])
            status = result.get("status", "COMPLETED")
            completed = self._store.complete_job(
                job_id=job_id,
                analysis_id=analysis_id,
                status=status,
            )
            return {"status": "completed", "job": completed or job, "result": result}
        except Exception as exc:
            failed = self._store.fail_job(job_id=job_id, error_message=str(exc))
            return {"status": "failed", "job": failed or job, "error_message": str(exc)}


def _default_report(*, analysis_id: str, generated_at: str) -> dict[str, Any]:
    return {
        "analysisId": analysis_id,
        "lang": "ko",
        "title": "AgentTrace 기술 분석 보고서",
        "bodyMarkdown": "# 1. 핵심 요약과 추천 독자\n\n분석 작업이 접수되었습니다.",
        "generatedAt": generated_at,
    }


def _default_analysis(job: dict[str, Any]) -> dict[str, Any]:
    analysis_id = job["analysisId"] or job["pendingAnalysisId"]
    ref_id = "ref-limited-1"
    return {
        "analysisId": analysis_id,
        "repositoryId": job["repositoryId"],
        "snapshotId": job["snapshotId"],
        "analysisVersion": job["analysisVersion"],
        "status": "completed_with_limitations",
        "agentType": "Unknown",
        "techStackSummary": {
            "primaryLanguage": None,
            "frameworks": [],
            "dependencies": [],
        },
        "areaFindings": [
            {
                "areaId": area_id,
                "areaName": area_name,
                "status": "unconfirmed",
                "summary": f"{area_name}은 아직 저장된 분석 결과가 없어 확인이 필요합니다.",
                "findings": [
                    {
                        "content": "분석 작업은 접수되었지만 구조화 결과는 아직 저장되지 않았습니다.",
                        "type": "inference",
                        "evidenceRefs": [ref_id],
                    }
                ],
                "limitations": ["저장된 구조화 분석 결과가 없습니다."],
                "unresolvedQuestions": ["분석 작업 완료 후 다시 조회해야 합니다."],
            }
            for area_id, area_name in COMMON_ANALYSIS_AREAS
        ],
        "evidenceRefs": [
            {
                "id": ref_id,
                "sourceType": "other",
                "path": "analysis_jobs",
                "symbol": None,
                "description": "분석 작업 접수 상태",
                "chunkId": None,
                "lineStart": None,
                "lineEnd": None,
                "contentExcerpt": None,
                "contentHash": None,
            }
        ],
        "reportSections": [
            {
                "sectionId": idx,
                "sectionName": f"section-{idx}",
                "status": "unconfirmed",
                "title": f"{idx}. 분석 결과 준비 중",
                "bodyMarkdown": "저장된 구조화 분석 결과가 아직 없습니다.",
                "mermaidDiagram": None,
            }
            for idx in range(1, 12)
        ],
        "analysisLimitations": {
            "missingInputs": [],
            "truncatedInputs": [],
            "notes": ["저장된 구조화 분석 결과가 없어 skeleton 응답을 반환합니다."],
        },
        "analysisCompletedAt": job["updatedAt"],
    }


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
