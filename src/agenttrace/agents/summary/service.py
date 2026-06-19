from __future__ import annotations

import json
from datetime import UTC, datetime
from importlib import resources
from typing import Any

from langchain_core.prompts import ChatPromptTemplate

from agenttrace.agents.summary.schemas import (
    AgentRelevanceHint,
    AgentRelevanceLevel,
    FollowupHints,
    RepositorySummary,
    RepositorySummaryRequest,
    SummaryLimitations,
    SummaryStatus,
)
from agenttrace.config import get_settings
from agenttrace.shared.errors import (
    MissingSummaryModelError,
    SummaryGenerationError,
    SummaryServiceError,
)


SUMMARY_PROMPT_ID = "repository-summary"
SUMMARY_PROMPT_VERSION = "repository-summary@1.0.0"
SUMMARY_BASELINE_NOTES = [
    "README와 repository metadata 기준 요약입니다.",
    "구현 근거 검증은 1차 Summary 단계에서 수행하지 않았습니다.",
]


def load_summary_prompt() -> str:
    return (
        resources.files("agenttrace.agents.summary")
        .joinpath("prompt.md")
        .read_text(encoding="utf-8")
    )


def build_summary_prompt_template() -> ChatPromptTemplate:
    return ChatPromptTemplate.from_messages(
        [
            ("system", load_summary_prompt()),
            (
                "human",
                "\n".join(
                    [
                        "Summarize this repository using only the provided input.",
                        "",
                        "Repository ID: {repository_id}",
                        "Full name: {full_name}",
                        "GitHub URL: {github_url}",
                        "Description: {description}",
                        "Topics: {topics}",
                        "Primary language: {primary_language}",
                        "",
                        "README:",
                        "{readme}",
                        "",
                        "Shallow file tree:",
                        "{file_tree}",
                    ]
                ),
            ),
        ]
    )


MAX_README_CHARS = 30000


def summarize_repository(
    request: RepositorySummaryRequest,
    *,
    model: Any | None = None,
) -> RepositorySummary:
    model_name = request.options.model_name or get_settings().summary_model
    prompt_version = request.options.prompt_version or SUMMARY_PROMPT_VERSION

    is_readme_truncated = False
    if request.readme_text and len(request.readme_text) > MAX_README_CHARS:
        request.readme_text = (
            request.readme_text[:MAX_README_CHARS]
            + "\n\n[Truncated by AgentTrace before summary generation.]"
        )
        is_readme_truncated = True

    if _has_insufficient_context(request):
        return RepositorySummary(
            repository_id=request.repository.repository_id,
            snapshot_id=request.snapshot_id,
            full_name=request.repository.full_name,
            github_url=request.repository.github_url,
            summary_status=SummaryStatus.INSUFFICIENT_CONTEXT,
            one_line_summary=None,
            readme_summary=None,
            project_purpose=None,
            target_users=[],
            possible_agent_relevance=AgentRelevanceHint(
                level=AgentRelevanceLevel.UNKNOWN,
                reason="README and repository description were not available for an AgentHub relevance hint.",
            ),
            followup_hints=FollowupHints(),
            summary_limitations=SummaryLimitations(
                missing_inputs=_missing_inputs(request),
                notes=list(SUMMARY_BASELINE_NOTES),
            ),
            generated_at=_utc_now_iso(),
            model_name=model_name,
            prompt_version=prompt_version,
            error_message=None,
        )

    if model is None:
        raise MissingSummaryModelError("A summary LLM model is required.")
    structured_model = model.with_structured_output(RepositorySummary)

    prompt_value = build_summary_prompt_template().invoke(_summary_payload(request))

    try:
        result = structured_model.invoke(prompt_value)
    except Exception as exc:
        raise SummaryGenerationError(
            f"Repository summary generation failed: {exc}"
        ) from exc

    if not isinstance(result, RepositorySummary):
        try:
            result = RepositorySummary.model_validate(result)
        except Exception as exc:
            raise SummaryGenerationError(
                "Repository summary output did not match the schema."
            ) from exc

    guarded_result = _apply_input_guards(
        result,
        request,
        model_name=model_name,
        prompt_version=prompt_version,
    )
    if is_readme_truncated:
        if "README" not in guarded_result.summary_limitations.truncated_inputs:
            guarded_result.summary_limitations.truncated_inputs.append("README")

    return _constrain_followup_hints(
        guarded_result,
        request,
    )


def build_failed_summary(
    request: RepositorySummaryRequest,
    error_message: str,
    model_name: str | None = None,
    prompt_version: str | None = None,
) -> RepositorySummary:
    return RepositorySummary(
        repository_id=request.repository.repository_id,
        snapshot_id=request.snapshot_id,
        full_name=request.repository.full_name,
        github_url=request.repository.github_url,
        summary_status=SummaryStatus.FAILED,
        one_line_summary=None,
        readme_summary=None,
        project_purpose=None,
        target_users=[],
        possible_agent_relevance=AgentRelevanceHint(),
        followup_hints=FollowupHints(),
        summary_limitations=SummaryLimitations(notes=list(SUMMARY_BASELINE_NOTES)),
        generated_at=_utc_now_iso(),
        model_name=model_name,
        prompt_version=prompt_version or SUMMARY_PROMPT_VERSION,
        error_message=error_message,
    )


def requires_llm_summary(request: RepositorySummaryRequest) -> bool:
    return not _has_insufficient_context(request)


def _has_insufficient_context(request: RepositorySummaryRequest) -> bool:
    return not (_has_text(request.readme_text) or _has_text(request.repository.description))


def _has_text(value: str | None) -> bool:
    return bool(value and value.strip())


def _missing_inputs(request: RepositorySummaryRequest) -> list[str]:
    missing = []
    if not _has_text(request.readme_text):
        missing.append("README content was not provided.")
    if not _has_text(request.repository.description):
        missing.append("Repository description was not provided.")
    return missing


def _apply_input_guards(
    summary: RepositorySummary,
    request: RepositorySummaryRequest,
    *,
    model_name: str | None,
    prompt_version: str,
) -> RepositorySummary:
    summary.repository_id = request.repository.repository_id
    summary.snapshot_id = request.snapshot_id
    summary.full_name = request.repository.full_name
    summary.github_url = request.repository.github_url
    summary.generated_at = _utc_now_iso()
    summary.model_name = model_name
    summary.prompt_version = prompt_version
    if summary.summary_status == SummaryStatus.INSUFFICIENT_CONTEXT:
        summary.one_line_summary = None
        summary.readme_summary = None
        summary.project_purpose = None
    summary.summary_limitations.notes = _merge_unique(
        [*summary.summary_limitations.notes, *SUMMARY_BASELINE_NOTES]
    )
    return summary


def _constrain_followup_hints(
    summary: RepositorySummary,
    request: RepositorySummaryRequest,
) -> RepositorySummary:
    allowed_files = set(request.shallow_file_tree)
    allowed_dirs = _directories_from_file_tree(request.shallow_file_tree)

    original_files = list(summary.followup_hints.files)
    original_dirs = list(summary.followup_hints.directories)
    summary.followup_hints.files = [
        path for path in original_files if path in allowed_files
    ]
    summary.followup_hints.directories = [
        path for path in original_dirs if _normalize_dir(path) in allowed_dirs
    ]

    removed_files = [path for path in original_files if path not in allowed_files]
    removed_dirs = [
        path for path in original_dirs if _normalize_dir(path) not in allowed_dirs
    ]

    if removed_files:
        summary.summary_limitations.notes.append(
            "Removed follow-up files not present in file_tree: "
            + ", ".join(removed_files)
        )
    if removed_dirs:
        summary.summary_limitations.notes.append(
            "Removed follow-up directories not present in file_tree: "
            + ", ".join(removed_dirs)
        )

    return summary


def _directories_from_file_tree(file_tree: list[str]) -> set[str]:
    directories = set()
    for path in file_tree:
        normalized_path = _normalize_dir(path) if _looks_like_directory_path(path) else path
        if _looks_like_directory_path(path):
            directories.add(normalized_path)
        parts = normalized_path.split("/")
        for index in range(1, len(parts)):
            directories.add("/".join(parts[:index]))
    return directories


def _looks_like_directory_path(path: str) -> bool:
    name = path.rstrip("/").rsplit("/", 1)[-1]
    return bool(name) and "." not in name


def _normalize_dir(path: str) -> str:
    return path.rstrip("/")


def _merge_unique(values: list[str]) -> list[str]:
    merged = []
    for value in values:
        if value not in merged:
            merged.append(value)
    return merged


def _summary_payload(request: RepositorySummaryRequest) -> dict[str, Any]:
    return {
        "repository_id": request.repository.repository_id or "",
        "full_name": request.repository.full_name,
        "github_url": request.repository.github_url,
        "description": request.repository.description or "",
        "topics": json.dumps(request.repository.topics, ensure_ascii=False),
        "primary_language": request.repository.primary_language or "",
        "readme": request.readme_text or "",
        "file_tree": json.dumps(
            request.shallow_file_tree,
            ensure_ascii=False,
            indent=2,
        ),
    }


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
