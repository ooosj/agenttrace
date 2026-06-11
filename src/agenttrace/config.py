from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    service_name: str = "agenttrace-ai"
    summary_model: str = "gpt-4o-mini"
    repo_ingest_base_url: str = "http://100.91.255.31:8010"
    repo_ingest_host_header: str | None = "localhost:8010"
    openai_api_key: str | None = None
    openai_api_base: str | None = None
    langsmith_tracing: str | None = None
    langsmith_api_key: str | None = None
    langsmith_project: str | None = None
    langsmith_endpoint: str | None = None


def get_settings() -> Settings:
    env_values = _load_dotenv(Path(".env"))
    return Settings(
        service_name=_get_env("AGENTTRACE_SERVICE_NAME", env_values, "agenttrace-ai"),
        summary_model=_get_env("AGENTTRACE_SUMMARY_MODEL", env_values, "gpt-4o-mini"),
        repo_ingest_base_url=_get_env(
            "AGENTTRACE_REPO_INGEST_BASE_URL",
            env_values,
            "http://100.91.255.31:8010",
        )
        or "http://100.91.255.31:8010",
        repo_ingest_host_header=_get_env(
            "AGENTTRACE_REPO_INGEST_HOST_HEADER",
            env_values,
            "localhost:8010",
        ),
        openai_api_key=_get_env("OPENAI_API_KEY", env_values),
        openai_api_base=(
            _get_env("OPENAI_API_BASE", env_values)
            or _get_env("OPENAI_BASE_URL", env_values)
        ),
        langsmith_tracing=_get_env("LANGSMITH_TRACING", env_values),
        langsmith_api_key=_get_env("LANGSMITH_API_KEY", env_values),
        langsmith_project=_get_env("LANGSMITH_PROJECT", env_values),
        langsmith_endpoint=_get_env("LANGSMITH_ENDPOINT", env_values),
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
