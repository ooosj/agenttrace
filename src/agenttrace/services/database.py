from __future__ import annotations

import logging
from typing import Any
import psycopg
from psycopg.rows import dict_row

logger = logging.getLogger(__name__)

class PsycopgSqlConnection:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def execute(self, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        with psycopg.connect(self._database_url, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                try:
                    if cur.description is not None:
                        return cur.fetchall()
                except psycopg.ProgrammingError:
                    pass
                return []

def init_database(database_url: str) -> None:
    """Initialize database schemas and tables."""
    logger.info("Initializing database schema...")
    conn = PsycopgSqlConnection(database_url)

    # 1. pgvector Extension
    try:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        logger.info("Checked/Created pgvector extension.")
    except Exception as exc:
        logger.warning("Failed to create pgvector extension: %s", exc)

    # 2. Base tables (if references exist in DDL)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS repositories (
                id uuid PRIMARY KEY,
                github_id bigint,
                full_name varchar(255),
                owner varchar(120),
                name varchar(120),
                stars integer DEFAULT 0,
                forks integer DEFAULT 0,
                watchers integer DEFAULT 0,
                open_issues integer DEFAULT 0,
                archived boolean DEFAULT false,
                fork boolean DEFAULT false,
                agent_score integer DEFAULT 0,
                is_agent_related boolean DEFAULT false,
                created_at timestamptz DEFAULT now(),
                updated_at timestamptz DEFAULT now(),
                CONSTRAINT uq_repositories_github_id UNIQUE (github_id),
                CONSTRAINT uq_repositories_full_name UNIQUE (full_name)
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS repository_snapshots (
                snapshot_id uuid PRIMARY KEY,
                repository_id uuid NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
                commit_sha varchar(40) NOT NULL,
                stars integer DEFAULT 0,
                forks integer DEFAULT 0,
                open_issues integer DEFAULT 0,
                watchers integer DEFAULT 0,
                captured_at timestamptz NOT NULL DEFAULT now(),
                created_at timestamptz NOT NULL DEFAULT now()
            );
            """
        )
    except Exception as exc:
        logger.warning("Failed to check/create base dummy tables: %s", exc)

    # 3. Import actual contract SQLs
    from agenttrace.services.content_indices import (
        PostgresContentIndexSql,
        PostgresAnalysisReportSql,
        PostgresRepositoryAnalysisSql,
        PostgresSourceChunkSql,
    )

    # Define all contract DDLs with fallback for analysis_jobs
    contract_tables = [
        ("agenttrace_repository_analyses", PostgresRepositoryAnalysisSql.table_contract()),
        ("analysis_jobs", """
            CREATE TABLE IF NOT EXISTS analysis_jobs (
                job_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
                analysis_id uuid,
                repository_id uuid NOT NULL,
                snapshot_id uuid NOT NULL,
                analysis_version varchar(50) NOT NULL,
                status varchar(30) NOT NULL,
                error_message text,
                created_at timestamptz NOT NULL DEFAULT now(),
                updated_at timestamptz NOT NULL DEFAULT now(),
                started_at timestamptz,
                heartbeat_at timestamptz
            )
        """),
        ("content_indices", PostgresContentIndexSql.table_contract()),
        ("analysis_reports", PostgresAnalysisReportSql.table_contract()),
        ("source_chunks", PostgresSourceChunkSql.table_contract()),
    ]

    for name, sql in contract_tables:
        try:
            # Inject 'IF NOT EXISTS' to avoid conflict if tables already exist
            safe_sql = sql
            if "CREATE TABLE" in sql and "IF NOT EXISTS" not in sql:
                safe_sql = sql.replace("CREATE TABLE", "CREATE TABLE IF NOT EXISTS")
            conn.execute(safe_sql)
            logger.info("Table '%s' checked/created successfully.", name)
        except Exception as exc:
            logger.error("Failed to check/create table '%s': %s", name, exc)
            raise

    # 4. Defensive migration to increase content_hash width
    try:
        conn.execute("ALTER TABLE source_chunks ALTER COLUMN content_hash TYPE varchar(120);")
        logger.info("Executed migration to expand content_hash column size.")
    except Exception as exc:
        logger.debug("Defensive alter content_hash column skipped/failed: %s", exc)
