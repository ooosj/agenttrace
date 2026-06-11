from __future__ import annotations

from fastapi import HTTPException

from agenttrace.shared.errors import (
    MissingSummaryModelError,
    RepoIngestError,
    SummaryGenerationError,
)


def summary_service_exception_to_http(exc: Exception) -> HTTPException:
    if isinstance(exc, MissingSummaryModelError):
        return HTTPException(
            status_code=500,
            detail={
                "error": "summary_model_not_configured",
                "message": str(exc),
            },
        )

    if isinstance(exc, SummaryGenerationError):
        return HTTPException(
            status_code=502,
            detail={
                "error": "summary_generation_failed",
                "message": str(exc),
            },
        )

    if isinstance(exc, RepoIngestError):
        return HTTPException(
            status_code=502,
            detail={
                "error": "repo_ingest_failed",
                "message": str(exc),
            },
        )

    return HTTPException(
        status_code=500,
        detail={
            "error": "summary_service_error",
            "message": str(exc),
        },
    )
