from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    service_name: str = "agenttrace-ai"
    summary_model: str = "gpt-4o-mini"
    analysis_model: str = "gpt-4o-mini"
    embedding_model: str = "text-embedding-3-small"
    embedding_dimension: int = 1536
    repo_ingest_base_url: str = "https://gitingest.com"
    repo_ingest_timeout: int = 1200
    agents_callback_url: str = "http://localhost:8080/api/v1/internal/analysis/callback"
    repo_ingest_host_header: str | None = None
    enable_github_url_summary: bool = False
    openai_api_key: str | None = None
    openai_api_base: str | None = None
    langsmith_tracing: str | None = None
    langsmith_api_key: str | None = None
    langsmith_project: str | None = None
    langsmith_endpoint: str | None = None
    database_url: str = "postgresql://agenthub_user:agenthub_password@localhost:5432/agenthub"
    external_ingest_enabled: bool = False
    github_token: str | None = None
    # finalize_analysis 전용 — evidence_evaluator와 독립
    finalize_model_timeout: int = 90          # 환경변수: AGENTTRACE_FINALIZE_MODEL_TIMEOUT
    finalize_model_max_tokens: int = 16384     # 환경변수: AGENTTRACE_FINALIZE_MODEL_MAX_TOKENS



@lru_cache()
def get_settings() -> Settings:
    env_values = _load_dotenv(Path(".env"))
    return Settings(
        service_name=_get_env("AGENTTRACE_SERVICE_NAME", env_values, "agenttrace-ai"),
        summary_model=_get_env("AGENTTRACE_SUMMARY_MODEL", env_values, "gpt-4o-mini"),
        analysis_model=_get_env("AGENTTRACE_ANALYSIS_MODEL", env_values, "gpt-4o-mini"),
        repo_ingest_base_url=_get_env(
            "AGENTTRACE_REPO_INGEST_BASE_URL",
            env_values,
            "https://gitingest.com",
        )
        or "https://gitingest.com",
        repo_ingest_timeout=int(
            _get_env("AGENTTRACE_REPO_INGEST_TIMEOUT", env_values, "1200")
            or "1200"
        ),
        agents_callback_url=_get_env(
            "AGENTS_CALLBACK_URL",
            env_values,
            "http://localhost:8080/api/v1/internal/analysis/callback",
        )
        or "http://localhost:8080/api/v1/internal/analysis/callback",
        repo_ingest_host_header=_get_env(
            "AGENTTRACE_REPO_INGEST_HOST_HEADER",
            env_values,
            None,
        ),
        enable_github_url_summary=_get_bool_env(
            "AGENTTRACE_ENABLE_GITHUB_URL_SUMMARY",
            env_values,
            False,
        ),
        external_ingest_enabled=_get_bool_env(
            "AGENTTRACE_EXTERNAL_INGEST_ENABLED",
            env_values,
            False,
        ),
        embedding_model=_get_env(
            "AGENTTRACE_EMBEDDING_MODEL",
            env_values,
            "text-embedding-3-small",
        )
        or "text-embedding-3-small",
        embedding_dimension=int(
            _get_env("AGENTTRACE_EMBEDDING_DIMENSION", env_values, "1536")
            or "1536"
        ),
        openai_api_key=(
            _get_env("AGENTTRACE_OPENAI_API_KEY", env_values)
            or _get_env("OPENAI_API_KEY", env_values)
        ),
        openai_api_base=(
            _get_env("AGENTTRACE_OPENAI_API_BASE", env_values)
            or _get_env("OPENAI_API_BASE", env_values)
            or _get_env("OPENAI_BASE_URL", env_values)
        ),
        langsmith_tracing=_get_env("LANGSMITH_TRACING", env_values),
        langsmith_api_key=_get_env("LANGSMITH_API_KEY", env_values),
        langsmith_project=_get_env("LANGSMITH_PROJECT", env_values),
        langsmith_endpoint=_get_env("LANGSMITH_ENDPOINT", env_values),
        database_url=_get_env(
            "DATABASE_URL",
            env_values,
            "postgresql://agenthub_user:agenthub_password@localhost:5432/agenthub",
        )
        or "postgresql://agenthub_user:agenthub_password@localhost:5432/agenthub",
        github_token=_get_env("GITHUB_TOKEN", env_values),
        finalize_model_timeout=int(
            _get_env("AGENTTRACE_FINALIZE_MODEL_TIMEOUT", env_values, "90")
            or "90"
        ),
        finalize_model_max_tokens=int(
            _get_env("AGENTTRACE_FINALIZE_MODEL_MAX_TOKENS", env_values, "8192")
            or "8192"
        ),
    )



def configure_runtime_environment(settings: Settings | None = None) -> Settings:
    settings = settings or get_settings()
    _set_env_if_present("LANGSMITH_TRACING", settings.langsmith_tracing)
    _set_env_if_present("LANGSMITH_API_KEY", settings.langsmith_api_key)
    _set_env_if_present("LANGSMITH_PROJECT", settings.langsmith_project)
    _set_env_if_present("LANGSMITH_ENDPOINT", settings.langsmith_endpoint)
    return settings


def _set_env_if_present(key: str, value: str | None) -> None:
    if value:
        os.environ.setdefault(key, value)


def _get_env(
    key: str,
    env_values: dict[str, str],
    default: str | None = None,
) -> str | None:
    return os.getenv(key) or env_values.get(key) or default


def _get_bool_env(
    key: str,
    env_values: dict[str, str],
    default: bool = False,
) -> bool:
    value = os.getenv(key) or env_values.get(key)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _load_dotenv(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue

        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value

    return values
