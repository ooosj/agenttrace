import uuid

from agenttrace.services.analysis_jobs import InMemoryAnalysisJobStore
from agenttrace.services.analysis_jobs import DurableAnalysisWorker
from agenttrace.services.analysis_jobs import PostgresAnalysisJobSql
from agenttrace.services.analysis_jobs import PostgresAnalysisJobStore


def test_job_store_reuses_running_job_for_same_snapshot_and_version():
    store = InMemoryAnalysisJobStore()
    repository_id = str(uuid.uuid4())
    snapshot_id = str(uuid.uuid4())

    first = store.request_analysis(
        repository_id=repository_id,
        snapshot_id=snapshot_id,
        analysis_version="analysis-v2",
    )
    second = store.request_analysis(
        repository_id=repository_id,
        snapshot_id=snapshot_id,
        analysis_version="analysis-v2",
    )

    assert first.job_id == second.job_id
    assert second.is_cached is False
    assert second.analysis_id is None


def test_job_store_reuses_completed_analysis_for_same_snapshot_and_version():
    store = InMemoryAnalysisJobStore()
    repository_id = str(uuid.uuid4())
    snapshot_id = str(uuid.uuid4())
    requested = store.request_analysis(
        repository_id=repository_id,
        snapshot_id=snapshot_id,
        analysis_version="analysis-v2",
    )
    analysis_id = str(uuid.uuid4())

    store.mark_completed(requested.job_id, analysis_id=analysis_id, status="completed")
    cached = store.request_analysis(
        repository_id=repository_id,
        snapshot_id=snapshot_id,
        analysis_version="analysis-v2",
    )

    assert cached.job_id is None
    assert cached.analysis_id == analysis_id
    assert cached.status == "completed"
    assert cached.is_cached is True


def test_job_store_status_and_report_use_camel_case_contract_data():
    store = InMemoryAnalysisJobStore()
    repository_id = str(uuid.uuid4())
    snapshot_id = str(uuid.uuid4())
    requested = store.request_analysis(
        repository_id=repository_id,
        snapshot_id=snapshot_id,
        analysis_version="analysis-v2",
    )

    status = store.get_status(repository_id=repository_id, job_id=requested.job_id)
    report = store.get_report(repository_id=repository_id, analysis_id=requested.job_id, lang="ko")

    assert status["jobId"] == requested.job_id
    assert status["analysisId"] is None
    assert status["status"] == "queued"
    assert report["analysisId"]
    assert report["bodyMarkdown"].startswith("# 1.")


def test_postgres_sql_claim_next_job_uses_skip_locked_contract():
    sql = PostgresAnalysisJobSql.claim_next_job()

    assert "FOR UPDATE SKIP LOCKED" in sql
    assert "status = 'QUEUED'" in sql
    assert "heartbeat_at" in sql
    assert "status = 'RUNNING'" in sql


def test_postgres_sql_request_analysis_checks_completed_before_running_jobs():
    statements = PostgresAnalysisJobSql.request_analysis()

    assert list(statements) == ["find_completed", "find_running", "insert_job"]
    assert "repository_analyses" in statements["find_completed"]
    assert "status IN ('completed', 'completed_with_limitations')" in statements["find_completed"]
    assert "analysis_jobs" in statements["find_running"]
    assert "status IN ('QUEUED', 'RUNNING')" in statements["find_running"]
    assert "INSERT INTO analysis_jobs" in statements["insert_job"]


def test_postgres_sql_marks_failed_jobs_stale_after_heartbeat_timeout():
    sql = PostgresAnalysisJobSql.fail_stale_running_jobs()

    assert "status = 'RUNNING'" in sql
    assert "heartbeat_at <" in sql
    assert "status = 'FAILED'" in sql
    assert "5 minutes" in sql


class RecordingConnection:
    def __init__(self):
        self.calls = []
        self.responses = []

    def execute(self, sql, params=None):
        self.calls.append((sql, params or {}))
        if self.responses:
            return self.responses.pop(0)
        return [{"job_id": "job-1", "status": "RUNNING"}]


def test_postgres_store_claim_next_job_executes_skip_locked_sql():
    conn = RecordingConnection()
    store = PostgresAnalysisJobStore(conn)

    result = store.claim_next_job()

    assert result == {"job_id": "job-1", "status": "RUNNING"}
    assert "FOR UPDATE SKIP LOCKED" in conn.calls[0][0]


def test_postgres_store_complete_and_fail_execute_job_status_sql():
    conn = RecordingConnection()
    conn.responses = [
        [{"job_id": "job-1", "analysis_id": "analysis-1", "status": "COMPLETED"}],
        [{"job_id": "job-2", "status": "FAILED", "error_message": "boom"}],
    ]
    store = PostgresAnalysisJobStore(conn)

    completed = store.complete_job(job_id="job-1", analysis_id="analysis-1")
    failed = store.fail_job(job_id="job-2", error_message="boom")

    assert completed["analysis_id"] == "analysis-1"
    assert failed["status"] == "FAILED"
    assert "SET status = %(status)s" in conn.calls[0][0]
    assert conn.calls[0][1]["status"] == "COMPLETED"
    assert "SET status = 'FAILED'" in conn.calls[1][0]


def test_durable_worker_claims_runs_and_completes_one_job():
    conn = RecordingConnection()
    conn.responses = [
        [{"job_id": "job-1", "status": "RUNNING"}],
        [{"job_id": "job-1", "analysis_id": "analysis-1", "status": "COMPLETED"}],
    ]
    store = PostgresAnalysisJobStore(conn)
    worker = DurableAnalysisWorker(
        store,
        runner=lambda job: {"analysis_id": "analysis-1", "status": "COMPLETED", "job": job},
    )

    result = worker.run_once()

    assert result["status"] == "completed"
    assert result["job"]["analysis_id"] == "analysis-1"
    assert "FOR UPDATE SKIP LOCKED" in conn.calls[0][0]
    assert "analysis_id = %(analysis_id)s" in conn.calls[1][0]


def test_durable_worker_marks_claimed_job_failed_when_runner_raises():
    conn = RecordingConnection()
    conn.responses = [
        [{"job_id": "job-1", "status": "RUNNING"}],
        [{"job_id": "job-1", "status": "FAILED", "error_message": "boom"}],
    ]
    store = PostgresAnalysisJobStore(conn)

    def raise_error(job):
        raise RuntimeError("boom")

    worker = DurableAnalysisWorker(store, runner=raise_error)

    result = worker.run_once()

    assert result["status"] == "failed"
    assert result["error_message"] == "boom"
    assert "SET status = 'FAILED'" in conn.calls[1][0]
