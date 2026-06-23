import uuid

from agenttrace.services.content_indices import PostgresContentIndexSql
from agenttrace.services.content_indices import PostgresContentIndexStore
from agenttrace.services.content_indices import PostgresAnalysisReportSql
from agenttrace.services.content_indices import PostgresRepositoryAnalysisSql
from agenttrace.services.content_indices import PostgresSourceChunkSql
from agenttrace.services.content_indices import PostgresAnalysisPersistenceStore


def test_content_indices_table_contract_matches_spec_key_and_statuses():
    sql = PostgresContentIndexSql.table_contract()

    assert "CREATE TABLE content_indices" in sql
    assert "chunking_version" in sql
    assert "embedding_model" in sql
    assert "embedding_dimension" in sql
    assert "index_version" in sql
    assert "PENDING" in sql
    assert "BUILDING" in sql
    assert "COMPLETED" in sql
    assert "FAILED" in sql
    assert "UNIQUE (snapshot_id, chunking_version, embedding_model, embedding_dimension, index_version)" in sql


def test_content_index_request_keeps_existing_completed_index_while_building_new_one():
    statements = PostgresContentIndexSql.request_index()

    assert list(statements) == ["find_completed", "find_active_build", "insert_pending"]
    assert "status = 'COMPLETED'" in statements["find_completed"]
    assert "status IN ('PENDING', 'BUILDING')" in statements["find_active_build"]
    assert "INSERT INTO content_indices" in statements["insert_pending"]
    assert "'PENDING'" in statements["insert_pending"]


def test_content_index_claim_build_uses_skip_locked():
    sql = PostgresContentIndexSql.claim_next_build()

    assert "status = 'PENDING'" in sql
    assert "FOR UPDATE SKIP LOCKED" in sql
    assert "status = 'BUILDING'" in sql


class RecordingConnection:
    def __init__(self):
        self.calls = []

    def execute(self, sql, params=None):
        self.calls.append((sql, params or {}))
        return [{"index_id": "idx-1", "status": "BUILDING"}]


def test_postgres_content_index_store_claims_next_build():
    conn = RecordingConnection()
    store = PostgresContentIndexStore(conn)

    result = store.claim_next_build()

    assert result == {"index_id": "idx-1", "status": "BUILDING"}
    assert "FOR UPDATE SKIP LOCKED" in conn.calls[0][0]


def test_postgres_content_index_store_requests_index_with_version_key():
    conn = RecordingConnection()
    store = PostgresContentIndexStore(conn)
    snapshot_id = str(uuid.uuid4())

    store.request_index(
        snapshot_id=snapshot_id,
        chunking_version="chunking-v1",
        embedding_model="text-embedding-3-small",
        embedding_dimension=1536,
        index_version="hnsw-v1",
    )

    assert conn.calls[0][1]["snapshot_id"] == snapshot_id
    assert conn.calls[0][1]["embedding_dimension"] == 1536


def test_analysis_reports_table_contract_and_upsert():
    table_sql = PostgresAnalysisReportSql.table_contract()
    upsert_sql = PostgresAnalysisReportSql.upsert_report()

    assert "CREATE TABLE analysis_reports" in table_sql
    assert "analysis_id" in table_sql
    assert "lang" in table_sql
    assert "body_markdown" in table_sql
    assert "UNIQUE (analysis_id, lang)" in table_sql
    assert "INSERT INTO analysis_reports" in upsert_sql
    assert "ON CONFLICT (analysis_id, lang)" in upsert_sql


def test_repository_analyses_table_contract_and_upsert():
    table_sql = PostgresRepositoryAnalysisSql.table_contract()
    upsert_sql = PostgresRepositoryAnalysisSql.upsert_analysis()

    assert "CREATE TABLE repository_analyses" in table_sql
    assert "result_json jsonb NOT NULL" in table_sql
    assert "completed_with_limitations" in table_sql
    assert "UNIQUE (repository_id, snapshot_id, analysis_version)" in table_sql
    assert "INSERT INTO repository_analyses" in upsert_sql
    assert "ON CONFLICT (repository_id, snapshot_id, analysis_version)" in upsert_sql


def test_source_chunks_upsert_contract_includes_symbol_and_embedding_column():
    table_sql = PostgresSourceChunkSql.table_contract()
    upsert_sql = PostgresSourceChunkSql.upsert_chunks()

    assert "CREATE TABLE source_chunks" in table_sql
    assert "symbol text" in table_sql
    assert "embedding vector(1536)" in table_sql
    assert "INSERT INTO source_chunks" in upsert_sql
    assert "ON CONFLICT (chunk_id)" in upsert_sql


def test_analysis_persistence_store_writes_analysis_then_report():
    conn = RecordingConnection()
    store = PostgresAnalysisPersistenceStore(conn)

    store.persist_analysis(
        analysis={
            "repository_id": str(uuid.uuid4()),
            "snapshot_id": str(uuid.uuid4()),
            "analysis_version": "analysis-v2",
            "status": "completed_with_limitations",
            "agent_type": "Unknown",
            "result_json": {"analysis_status": "completed_with_limitations"},
            "model_name": None,
            "prompt_version": None,
        },
        report={
            "analysis_id": str(uuid.uuid4()),
            "lang": "ko",
            "title": "AgentTrace 기술 분석 보고서",
            "body_markdown": "# report",
        },
    )

    assert "INSERT INTO repository_analyses" in conn.calls[0][0]
    assert "INSERT INTO analysis_reports" in conn.calls[1][0]
