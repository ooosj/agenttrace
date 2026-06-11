from __future__ import annotations

import json
from importlib import resources
from typing import Any

from langchain_core.prompts import ChatPromptTemplate

from agenttrace.agents.summary.schemas import (
    AgentRelevanceHint,
    AgentRelevanceLevel,
    ConfidenceLevel,
    FollowupHints,
    HarnessRelevanceHint,
    RepositorySummary,
    RepositorySummaryInput,
    SummaryBasis,
    SummaryStatus,
)
from agenttrace.shared.errors import (
    MissingSummaryModelError,
    SummaryGenerationError,
    SummaryServiceError,
)


SUMMARY_LIMITATION = "Based only on provided README and repository metadata."


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


def summarize_repository(
    summary_input: RepositorySummaryInput,
    *,
    model: Any | None = None,
) -> RepositorySummary:
    limitations = _base_limitations(summary_input)

    if _has_insufficient_context(summary_input):
        return RepositorySummary(
            repository_id=summary_input.repository_id,
            full_name=summary_input.full_name,
            github_url=summary_input.github_url,
            one_line_summary=(
                f"{summary_input.full_name} has insufficient summary context."
            ),
            readme_summary="",
            project_purpose=None,
            apparent_target_users=[],
            readme_claims=[],
            readme_described_features=[],
            possible_agent_relevance=AgentRelevanceHint(
                level=AgentRelevanceLevel.UNKNOWN,
                reason="AgentHub relevance was not assessed because README and description were missing.",
            ),
            possible_harness_relevance=HarnessRelevanceHint(
                level=AgentRelevanceLevel.UNKNOWN,
                reason="[확인 필요] README and file tree were not available for a harness relevance hint.",
                confidence=ConfidenceLevel.UNKNOWN,
            ),
            followup_hints=FollowupHints(),
            summary_basis=_summary_basis(summary_input),
            input_gaps=_input_gaps(summary_input),
            missing_details=[],
            summary_limitations=limitations,
            confidence=ConfidenceLevel.UNKNOWN,
            summary_status=SummaryStatus.INSUFFICIENT_CONTEXT,
            summary_status_reason="README and description were not provided.",
        )

    if model is None:
        raise MissingSummaryModelError("A summary LLM model is required.")
    structured_model = model.with_structured_output(RepositorySummary)

    prompt_value = build_summary_prompt_template().invoke(_summary_payload(summary_input))

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

    return _constrain_followup_hints(result, summary_input)


def requires_llm_summary(summary_input: RepositorySummaryInput) -> bool:
    return not _has_insufficient_context(summary_input)


def _has_insufficient_context(summary_input: RepositorySummaryInput) -> bool:
    return not (summary_input.readme or summary_input.description)


def _base_limitations(summary_input: RepositorySummaryInput) -> list[str]:
    limitations = [SUMMARY_LIMITATION]
    if not summary_input.readme:
        limitations.append("README content was not provided.")
    if not summary_input.file_tree:
        limitations.append("File tree was not provided.")
    limitations.append("Implementation evidence was not validated in this summary step.")
    return limitations


def _input_gaps(summary_input: RepositorySummaryInput) -> list[str]:
    gaps = []
    if not summary_input.readme:
        gaps.append("README content was not provided.")
    if not summary_input.description:
        gaps.append("Repository description was not provided.")
    if not summary_input.topics:
        gaps.append("Repository topics were not provided.")
    if not summary_input.primary_language:
        gaps.append("Primary language was not provided.")
    if not summary_input.file_tree:
        gaps.append("Shallow file tree was not provided.")
    return gaps


def _summary_basis(summary_input: RepositorySummaryInput) -> SummaryBasis:
    return SummaryBasis(
        used_readme=bool(summary_input.readme),
        used_description=bool(summary_input.description),
        used_topics=bool(summary_input.topics),
        used_primary_language=bool(summary_input.primary_language),
        used_file_tree=bool(summary_input.file_tree),
    )


def _constrain_followup_hints(
    summary: RepositorySummary,
    summary_input: RepositorySummaryInput,
) -> RepositorySummary:
    allowed_files = set(summary_input.file_tree)
    allowed_dirs = _directories_from_file_tree(summary_input.file_tree)

    original_files = list(summary.followup_hints.files)
    original_dirs = list(summary.followup_hints.directories)
    summary.followup_hints.files = [
        path for path in original_files if path in allowed_files
    ]
    summary.followup_hints.directories = [
        path for path in original_dirs if path in allowed_dirs
    ]

    removed_files = [path for path in original_files if path not in allowed_files]
    removed_dirs = [path for path in original_dirs if path not in allowed_dirs]

    if removed_files:
        summary.summary_limitations.append(
            "Removed follow-up files not present in file_tree: "
            + ", ".join(removed_files)
        )
    if removed_dirs:
        summary.summary_limitations.append(
            "Removed follow-up directories not present in file_tree: "
            + ", ".join(removed_dirs)
        )

    return summary


def _directories_from_file_tree(file_tree: list[str]) -> set[str]:
    directories = set()
    for path in file_tree:
        parts = path.split("/")
        for index in range(1, len(parts)):
            directories.add("/".join(parts[:index]))
    return directories


def _summary_payload(summary_input: RepositorySummaryInput) -> dict[str, Any]:
    return {
        "repository_id": summary_input.repository_id,
        "full_name": summary_input.full_name,
        "github_url": summary_input.github_url,
        "description": summary_input.description or "",
        "topics": json.dumps(summary_input.topics, ensure_ascii=False),
        "primary_language": summary_input.primary_language or "",
        "readme": summary_input.readme or "",
        "file_tree": json.dumps(summary_input.file_tree, ensure_ascii=False, indent=2),
    }
