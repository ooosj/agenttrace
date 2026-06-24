from __future__ import annotations

from typing import Any

from agenttrace.config import get_settings
from agenttrace.shared.errors import MissingAnalysisModelError, MissingSummaryModelError


def build_openai_summary_model() -> Any:
    settings = get_settings()

    if not settings.openai_api_key:
        raise MissingSummaryModelError("OPENAI_API_KEY is required for summary generation.")

    try:
        from langchain_openai import ChatOpenAI
    except ImportError as exc:
        raise MissingSummaryModelError(
            "langchain-openai is required for OpenAI summary generation."
        ) from exc

    kwargs = {
        "model": settings.summary_model,
        "api_key": settings.openai_api_key,
        "temperature": 0,
    }
    if settings.openai_api_base:
        kwargs["base_url"] = settings.openai_api_base

    return ChatOpenAI(**kwargs)


def build_openai_analysis_model() -> Any:
    settings = get_settings()

    if not settings.openai_api_key:
        raise MissingAnalysisModelError("OPENAI_API_KEY is required for analysis generation.")

    try:
        from langchain_openai import ChatOpenAI
    except ImportError as exc:
        raise MissingAnalysisModelError(
            "langchain-openai is required for OpenAI analysis generation."
        ) from exc

    kwargs = {
        "model": settings.analysis_model,
        "api_key": settings.openai_api_key,
        "temperature": 0,
    }
    if settings.openai_api_base:
        kwargs["base_url"] = settings.openai_api_base

    return ChatOpenAI(**kwargs)


def build_openai_finalize_model() -> Any:
    """finalize_analysis 전용 모델. evidence_evaluator와 timeout/max_tokens 분리."""
    settings = get_settings()
    if not settings.openai_api_key:
        raise MissingAnalysisModelError("OPENAI_API_KEY is required for analysis generation.")
    try:
        from langchain_openai import ChatOpenAI
    except ImportError as exc:
        raise MissingAnalysisModelError(
            "langchain-openai is required for OpenAI analysis generation."
        ) from exc
    kwargs = {
        "model": settings.analysis_model,
        "api_key": settings.openai_api_key,
        "temperature": 0,
        "timeout": settings.finalize_model_timeout,
        "max_tokens": settings.finalize_model_max_tokens,
        "max_retries": 1,
    }
    if settings.openai_api_base:
        kwargs["base_url"] = settings.openai_api_base
    return ChatOpenAI(**kwargs)
