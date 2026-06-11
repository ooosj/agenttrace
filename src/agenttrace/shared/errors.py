from __future__ import annotations


class SummaryServiceError(RuntimeError):
    """Base error for summary service failures."""


class MissingSummaryModelError(SummaryServiceError):
    """Raised when an LLM model is required but not configured."""


class SummaryGenerationError(SummaryServiceError):
    """Raised when the LLM summary chain fails."""


class RepoIngestError(SummaryServiceError):
    """Raised when repository ingest data cannot be fetched or normalized."""
