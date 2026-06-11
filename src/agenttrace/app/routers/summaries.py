from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from agenttrace.agents.summary import RepositorySummary, RepositorySummaryInput
from agenttrace.agents.summary.service import requires_llm_summary, summarize_repository
from agenttrace.app.dependencies import get_summary_model_factory
from agenttrace.app.errors import summary_service_exception_to_http
from agenttrace.services.repo_ingest import fetch_repo_digest, repo_digest_to_summary_input

router = APIRouter(tags=["summaries"])


class GithubUrlSummaryRequest(BaseModel):
    github_url: str


@router.post("/repository-summaries", response_model=RepositorySummary)
def create_repository_summary(
    summary_input: RepositorySummaryInput,
    summary_model_factory: Annotated[Callable[[], Any], Depends(get_summary_model_factory)],
) -> RepositorySummary:
    try:
        model = summary_model_factory() if requires_llm_summary(summary_input) else None
        return summarize_repository(summary_input, model=model)
    except Exception as exc:
        raise summary_service_exception_to_http(exc) from exc


@router.post("/repository-summaries/from-github-url", response_model=RepositorySummary)
def create_repository_summary_from_github_url(
    request: GithubUrlSummaryRequest,
    summary_model_factory: Annotated[Callable[[], Any], Depends(get_summary_model_factory)],
) -> RepositorySummary:
    full_name = _parse_github_full_name(request.github_url)

    try:
        digest = fetch_repo_digest(full_name)
        summary_input = repo_digest_to_summary_input(digest, fallback_full_name=full_name)
        model = summary_model_factory() if requires_llm_summary(summary_input) else None
        return summarize_repository(summary_input, model=model)
    except Exception as exc:
        raise summary_service_exception_to_http(exc) from exc


def _parse_github_full_name(github_url: str) -> str:
    parsed = urlparse(github_url)
    if parsed.scheme not in {"http", "https"} or parsed.netloc.lower() != "github.com":
        raise HTTPException(
            status_code=422,
            detail={
                "error": "invalid_github_url",
                "message": "github_url must be a GitHub repository URL.",
            },
        )

    parts = [part for part in parsed.path.strip("/").split("/") if part]
    if len(parts) < 2:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "invalid_github_url",
                "message": "github_url must include owner and repository.",
            },
        )

    return f"{parts[0]}/{parts[1].removesuffix('.git')}"
