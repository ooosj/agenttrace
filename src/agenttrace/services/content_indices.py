from __future__ import annotations

from typing import Any, Protocol


class SqlConnection(Protocol):
    def execute(self, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        ...


class PostgresContentIndexSql:
    @staticmethod
    def table_contract() -> str:
        return """
            CREATE TABLE content_indices (
                index_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
                snapshot_id uuid NOT NULL REFERENCES repository_snapshots(snapshot_id) ON DELETE CASCADE,
                chunking_version varchar(50) NOT NULL,
                embedding_model varchar(100) NOT NULL,
                embedding_dimension integer NOT NULL,
                index_version varchar(50) NOT NULL,
                status varchar(30) NOT NULL DEFAULT 'PENDING',
                error_message text,
                created_at timestamptz NOT NULL DEFAULT now(),
                updated_at timestamptz NOT NULL DEFAULT now(),
                UNIQUE (snapshot_id, chunking_version, embedding_model, embedding_dimension, index_version),
                CONSTRAINT chk_content_indices_status CHECK (status IN ('PENDING', 'BUILDING', 'COMPLETED', 'FAILED'))
            )
        """.strip()

    @staticmethod
    def request_index() -> dict[str, str]:
        version_filter = """
            snapshot_id = %(snapshot_id)s
            AND chunking_version = %(chunking_version)s
            AND embedding_model = %(embedding_model)s
            AND embedding_dimension = %(embedding_dimension)s
            AND index_version = %(index_version)s
        """.strip()
        return {
            "find_completed": f"""
                SELECT index_id, status
                FROM content_indices
                WHERE {version_filter}
                  AND status = 'COMPLETED'
                ORDER BY updated_at DESC
                LIMIT 1
            """.strip(),
            "find_active_build": f"""
                SELECT index_id, status
                FROM content_indices
                WHERE {version_filter}
                  AND status IN ('PENDING', 'BUILDING')
                ORDER BY created_at ASC
                LIMIT 1
            """.strip(),
            "insert_pending": """
                INSERT INTO content_indices (
                    snapshot_id,
                    chunking_version,
                    embedding_model,
                    embedding_dimension,
                    index_version,
                    status,
                    created_at,
                    updated_at
                )
                VALUES (
                    %(snapshot_id)s,
                    %(chunking_version)s,
                    %(embedding_model)s,
                    %(embedding_dimension)s,
                    %(index_version)s,
                    'PENDING',
                    now(),
                    now()
                )
                ON CONFLICT (snapshot_id, chunking_version, embedding_model, embedding_dimension, index_version)
                DO UPDATE SET updated_at = content_indices.updated_at
                RETURNING index_id, status
            """.strip(),
        }

    @staticmethod
    def claim_next_build() -> str:
        return """
            WITH next_index AS (
                SELECT index_id
                FROM content_indices
                WHERE status = 'PENDING'
                ORDER BY created_at ASC
                FOR UPDATE SKIP LOCKED
                LIMIT 1
            )
            UPDATE content_indices
            SET status = 'BUILDING',
                updated_at = now()
            FROM next_index
            WHERE content_indices.index_id = next_index.index_id
            RETURNING content_indices.*
        """.strip()

    @staticmethod
    def mark_completed() -> str:
        return """
            UPDATE content_indices
            SET status = 'COMPLETED',
                error_message = NULL,
                updated_at = now()
            WHERE index_id = %(index_id)s
              AND status = 'BUILDING'
            RETURNING index_id, status, updated_at
        """.strip()

    @staticmethod
    def mark_failed() -> str:
        return """
            UPDATE content_indices
            SET status = 'FAILED',
                error_message = %(error_message)s,
                updated_at = now()
            WHERE index_id = %(index_id)s
            RETURNING index_id, status, error_message, updated_at
        """.strip()


class PostgresContentIndexStore:
    def __init__(self, connection: SqlConnection) -> None:
        self._connection = connection

    def request_index(
        self,
        *,
        snapshot_id: str,
        chunking_version: str,
        embedding_model: str,
        embedding_dimension: int,
        index_version: str,
    ) -> dict[str, Any] | None:
        params = {
            "snapshot_id": snapshot_id,
            "chunking_version": chunking_version,
            "embedding_model": embedding_model,
            "embedding_dimension": embedding_dimension,
            "index_version": index_version,
        }
        statements = PostgresContentIndexSql.request_index()
        for statement in (
            statements["find_completed"],
            statements["find_active_build"],
            statements["insert_pending"],
        ):
            rows = self._connection.execute(statement, params)
            if rows:
                return rows[0]
        return None

    def claim_next_build(self) -> dict[str, Any] | None:
        rows = self._connection.execute(PostgresContentIndexSql.claim_next_build())
        return rows[0] if rows else None

    def upsert_chunks(self, snapshot_id: str, chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not chunks:
            return []
        import json
        params = {
            "snapshot_id": snapshot_id,
            "chunks": json.dumps(chunks),
        }
        return self._connection.execute(PostgresSourceChunkSql.upsert_chunks(), params)


class PostgresAnalysisReportSql:
    @staticmethod
    def table_contract() -> str:
        return """
            CREATE TABLE analysis_reports (
                report_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
                analysis_id uuid NOT NULL REFERENCES agenttrace_repository_analyses(analysis_id) ON DELETE CASCADE,
                lang varchar(10) NOT NULL,
                title varchar(255) NOT NULL,
                body_markdown text NOT NULL,
                created_at timestamptz NOT NULL DEFAULT now(),
                updated_at timestamptz NOT NULL DEFAULT now(),
                UNIQUE (analysis_id, lang)
            )
        """.strip()

    @staticmethod
    def upsert_report() -> str:
        return """
            INSERT INTO analysis_reports (
                analysis_id,
                lang,
                title,
                body_markdown,
                created_at,
                updated_at
            )
            VALUES (
                %(analysis_id)s,
                %(lang)s,
                %(title)s,
                %(body_markdown)s,
                now(),
                now()
            )
            ON CONFLICT (analysis_id, lang)
            DO UPDATE SET
                title = EXCLUDED.title,
                body_markdown = EXCLUDED.body_markdown,
                updated_at = now()
            RETURNING report_id, analysis_id, lang, title, body_markdown, updated_at
        """.strip()


class PostgresRepositoryAnalysisSql:
    @staticmethod
    def table_contract() -> str:
        return """
            CREATE TABLE agenttrace_repository_analyses (
                analysis_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
                repository_id uuid NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
                snapshot_id uuid NOT NULL REFERENCES repository_snapshots(snapshot_id) ON DELETE CASCADE,
                analysis_version varchar(50) NOT NULL,
                status varchar(40) NOT NULL,
                agent_type varchar(30) NOT NULL DEFAULT 'Unknown',
                result_json jsonb NOT NULL,
                model_name varchar(120),
                prompt_version varchar(80),
                analysis_completed_at timestamptz,
                created_at timestamptz NOT NULL DEFAULT now(),
                updated_at timestamptz NOT NULL DEFAULT now(),
                UNIQUE (repository_id, snapshot_id, analysis_version),
                CONSTRAINT chk_agenttrace_repository_analyses_status CHECK (status IN ('completed', 'completed_with_limitations')),
                CONSTRAINT chk_agenttrace_repository_analyses_agent_type CHECK (
                    agent_type IN ('MCP', 'Skill', 'Eval', 'ToolUse', 'Framework', 'Other', 'Unknown')
                )
            )
        """.strip()

    @staticmethod
    def upsert_analysis() -> str:
        return """
            INSERT INTO agenttrace_repository_analyses (
                analysis_id,
                repository_id,
                snapshot_id,
                analysis_version,
                status,
                agent_type,
                result_json,
                model_name,
                prompt_version,
                analysis_completed_at,
                created_at,
                updated_at
            )
            VALUES (
                %(analysis_id)s,
                %(repository_id)s,
                %(snapshot_id)s,
                %(analysis_version)s,
                %(status)s,
                %(agent_type)s,
                %(result_json)s::jsonb,
                %(model_name)s,
                %(prompt_version)s,
                now(),
                now(),
                now()
            )
            ON CONFLICT (repository_id, snapshot_id, analysis_version)
            DO UPDATE SET
                status = EXCLUDED.status,
                agent_type = EXCLUDED.agent_type,
                result_json = EXCLUDED.result_json,
                model_name = EXCLUDED.model_name,
                prompt_version = EXCLUDED.prompt_version,
                analysis_completed_at = now(),
                updated_at = now()
            RETURNING analysis_id, repository_id, snapshot_id, analysis_version, status
        """.strip()


class PostgresSourceChunkSql:
    @staticmethod
    def table_contract() -> str:
        return """
            CREATE TABLE source_chunks (
                chunk_id varchar(64) PRIMARY KEY,
                snapshot_id uuid NOT NULL REFERENCES repository_snapshots(snapshot_id) ON DELETE CASCADE,
                file_path text NOT NULL,
                content text NOT NULL,
                start_line integer,
                end_line integer,
                symbol text,
                content_hash varchar(120) NOT NULL,
                chunk_type varchar(30) NOT NULL DEFAULT 'code',
                embedding vector(1536),
                created_at timestamptz NOT NULL DEFAULT now(),
                CONSTRAINT chk_source_chunks_type CHECK (chunk_type IN ('code', 'doc', 'config', 'other'))
            )
        """.strip()

    @staticmethod
    def upsert_chunks() -> str:
        return """
            INSERT INTO source_chunks (
                chunk_id,
                snapshot_id,
                file_path,
                content,
                start_line,
                end_line,
                symbol,
                content_hash,
                chunk_type,
                created_at
            )
            SELECT
                data.chunk_id,
                %(snapshot_id)s,
                data.file_path,
                data.content,
                data.start_line,
                data.end_line,
                data.symbol,
                data.content_hash,
                data.chunk_type,
                now()
            FROM jsonb_to_recordset(%(chunks)s::jsonb)
                AS data(
                    chunk_id text,
                    file_path text,
                    content text,
                    start_line integer,
                    end_line integer,
                    symbol text,
                    content_hash text,
                    chunk_type text
                )
            ON CONFLICT (chunk_id)
            DO UPDATE SET
                file_path = EXCLUDED.file_path,
                content = EXCLUDED.content,
                start_line = EXCLUDED.start_line,
                end_line = EXCLUDED.end_line,
                symbol = EXCLUDED.symbol,
                content_hash = EXCLUDED.content_hash,
                chunk_type = EXCLUDED.chunk_type
            RETURNING chunk_id
        """.strip()


class PostgresAnalysisPersistenceStore:
    def __init__(self, connection: SqlConnection) -> None:
        self._connection = connection

    def persist_analysis(self, *, analysis: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
        import json
        analysis_params = dict(analysis)
        if "result_json" in analysis_params and isinstance(analysis_params["result_json"], dict):
            analysis_params["result_json"] = json.dumps(analysis_params["result_json"])
            
        analysis_rows = self._connection.execute(
            PostgresRepositoryAnalysisSql.upsert_analysis(),
            analysis_params,
        )
        analysis_id = (
            analysis_rows[0].get("analysis_id")
            if analysis_rows
            else report.get("analysis_id")
        )
        report_params = dict(report)
        report_params["analysis_id"] = str(analysis_id)
        report_rows = self._connection.execute(PostgresAnalysisReportSql.upsert_report(), report_params)
        return {
            "analysis": analysis_rows[0] if analysis_rows else None,
            "report": report_rows[0] if report_rows else None,
        }
