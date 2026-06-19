from __future__ import annotations

import os
import sys
import types
from importlib import resources

import pytest

from agenttrace.agents.summary import (
    AgentRelevanceLevel,
    RepositoryMetadata,
    RepositorySummary,
    SummaryGenerationOptions,
    SummaryLimitations,
    RepositorySummaryRequest,
    SummaryStatus,
    summarize_repository,
)
from agenttrace.agents.summary import MissingSummaryModelError
from agenttrace.agents.summary.service import (
    SUMMARY_PROMPT_ID,
    SUMMARY_PROMPT_VERSION,
    build_failed_summary,
)
from agenttrace.config import get_settings
from agenttrace.models import build_openai_summary_model


def load_summary_prompt() -> str:
    return (
        resources.files("agenttrace.agents.summary")
        .joinpath("prompt.md")
        .read_text(encoding="utf-8")
    )


def test_repository_summary_request_uses_artifact_aligned_shape():
    request = RepositorySummaryRequest(
        repository=RepositoryMetadata(
            repository_id="repo-1",
            full_name="acme/weather-agent",
            github_url="https://github.com/acme/weather-agent",
            description="Weather automation assistant",
            topics=["weather", "agent"],
            primary_language="Python",
            stars=42,
            forks=7,
            pushed_at="2026-06-15T00:00:00Z",
            github_updated_at="2026-06-16T00:00:00Z",
        ),
        snapshot_id="snapshot-1",
        readme_text="# Weather Agent",
        shallow_file_tree=["README.md", "src/weather_agent/server.py"],
        options=SummaryGenerationOptions(
            model_name="gpt-5-mini",
            prompt_version="summary-contract-v1",
        ),
    )

    assert request.repository.repository_id == "repo-1"
    assert request.repository.full_name == "acme/weather-agent"
    assert request.repository.github_url == "https://github.com/acme/weather-agent"
    assert request.repository.topics == ["weather", "agent"]
    assert request.shallow_file_tree == ["README.md", "src/weather_agent/server.py"]
    assert request.options.model_name == "gpt-5-mini"
    assert request.options.prompt_version == "summary-contract-v1"

    default_request = RepositorySummaryRequest(
        repository=RepositoryMetadata(
            full_name="acme/empty",
            github_url="https://github.com/acme/empty",
        )
    )

    assert default_request.repository.topics == []
    assert default_request.shallow_file_tree == []
    assert default_request.options == SummaryGenerationOptions()


def test_repository_summary_response_uses_artifact_fields_only():
    summary = RepositorySummary(
        repository_id="repo-1",
        snapshot_id="snapshot-1",
        full_name="acme/weather-agent",
        github_url="https://github.com/acme/weather-agent",
        summary_status=SummaryStatus.COMPLETED,
        one_line_summary="Weather Agent provides weather automation helpers.",
        readme_summary="README describes forecast lookup and weather alerts.",
        project_purpose="Help agents retrieve weather information.",
        target_users=["agent developers"],
        possible_agent_relevance={
            "level": AgentRelevanceLevel.MEDIUM,
            "reason": "README describes agent-oriented examples.",
        },
        followup_hints={
            "files": ["examples/client.py"],
            "directories": ["src/weather_agent"],
            "questions": ["Does the example run with a real API key?"],
        },
        summary_limitations=SummaryLimitations(
            missing_inputs=["No test results were provided."],
            truncated_inputs=["README was truncated."],
            notes=["Based only on provided metadata."],
        ),
        generated_at="2026-06-17T00:00:00Z",
        model_name="gpt-5-mini",
        prompt_version="summary-contract-v1",
    )

    dumped = summary.model_dump()

    assert dumped["summary_limitations"] == {
        "missing_inputs": ["No test results were provided."],
        "truncated_inputs": ["README was truncated."],
        "notes": ["Based only on provided metadata."],
    }
    assert dumped["target_users"] == ["agent developers"]
    assert dumped["followup_hints"] == {
        "files": ["examples/client.py"],
        "directories": ["src/weather_agent"],
        "questions": ["Does the example run with a real API key?"],
    }
    assert set(dumped) == {
        "repository_id",
        "snapshot_id",
        "full_name",
        "github_url",
        "summary_status",
        "one_line_summary",
        "readme_summary",
        "project_purpose",
        "target_users",
        "possible_agent_relevance",
        "followup_hints",
        "summary_limitations",
        "generated_at",
        "model_name",
        "prompt_version",
        "error_message",
    }
    for legacy_field in {
        "apparent_target_users",
        "readme_claims",
        "readme_described_features",
        "summary_basis",
        "input_gaps",
        "missing_details",
        "confidence",
        "possible_harness_relevance",
    }:
        assert legacy_field not in dumped


class FakeStructuredSummaryModel:
    def __init__(self):
        self.last_payload = None

    def with_structured_output(self, schema):
        self.schema = schema
        return self

    def invoke(self, payload):
        self.last_payload = payload
        assert hasattr(payload, "to_messages")
        return self.schema(
            repository_id="repo-1",
            snapshot_id="snapshot-1",
            full_name="acme/weather-agent",
            github_url="https://github.com/acme/weather-agent",
            summary_status="completed",
            one_line_summary="Weather Agent appears to provide weather automation tools.",
            readme_summary="Weather Agent is presented as an MCP-style weather automation project.",
            project_purpose="Provide weather automation helpers for agent workflows.",
            target_users=["agent developers", "MCP users"],
            possible_agent_relevance={
                "level": "medium",
                "reason": "README mentions agent workflows, but implementation evidence was not validated.",
            },
            followup_hints={
                "files": ["examples/client.py"],
                "directories": ["src/weather_agent"],
                "questions": ["Does the example run with a real API key?"],
            },
            summary_limitations={
                "notes": [
                    "Implementation evidence was not validated in this summary step."
                ]
            },
            generated_at="2026-06-17T00:00:00Z",
            model_name="gpt-5-mini",
            prompt_version="summary-contract-v1",
        )


class FakeStructuredSummaryDictWithoutServiceMetadata(FakeStructuredSummaryModel):
    def invoke(self, payload):
        result = super().invoke(payload).model_dump()
        result.pop("generated_at")
        result.pop("prompt_version")
        result["model_name"] = "model-output-should-not-win"
        return result


def test_summarize_repository_uses_llm_model_with_readme_and_metadata():
    request = RepositorySummaryRequest(
        repository=RepositoryMetadata(
            repository_id="repo-1",
            full_name="acme/weather-agent",
            github_url="https://github.com/acme/weather-agent",
            description="Weather automation assistant",
            topics=["weather", "agent", "mcp"],
            primary_language="Python",
        ),
        snapshot_id="snapshot-from-request",
        readme_text="""
        # Weather Agent

        Weather Agent is an MCP server for weather automation.

        It provides forecast lookup, weather alerts, and tool calling examples.
        It includes a local CLI and integration examples.
        """,
        shallow_file_tree=[
            "README.md",
            "src/weather_agent/server.py",
            "examples/client.py",
            "tests/test_server.py",
        ],
        options=SummaryGenerationOptions(
            model_name="gpt-5-nano",
            prompt_version="repository-summary@test",
        ),
    )
    model = FakeStructuredSummaryModel()

    result = summarize_repository(request, model=model)

    assert result.summary_status == SummaryStatus.COMPLETED
    assert result.one_line_summary == (
        "Weather Agent appears to provide weather automation tools."
    )
    assert result.snapshot_id == "snapshot-from-request"
    assert result.target_users == ["agent developers", "MCP users"]
    assert result.possible_agent_relevance.level == AgentRelevanceLevel.MEDIUM
    assert result.project_purpose
    assert "examples/client.py" in result.followup_hints.files
    assert result.generated_at.endswith("Z")
    assert result.generated_at != "2026-06-17T00:00:00Z"
    assert result.model_name == "gpt-5-nano"
    assert result.prompt_version == "repository-summary@test"
    prompt_text = "\n".join(message.content for message in model.last_payload.to_messages())
    assert "acme/weather-agent" in prompt_text
    assert "Weather Agent is an MCP server" in prompt_text


def test_summarize_repository_populates_service_metadata_when_model_omits_it():
    request = RepositorySummaryRequest(
        repository=RepositoryMetadata(
            repository_id="repo-1",
            full_name="acme/weather-agent",
            github_url="https://github.com/acme/weather-agent",
            description="Weather automation assistant",
        ),
        snapshot_id="snapshot-from-request",
        readme_text="# Weather Agent\n\nProvides weather automation helpers.",
        options=SummaryGenerationOptions(
            model_name="gpt-5-nano",
            prompt_version="repository-summary@test",
        ),
    )

    result = summarize_repository(
        request,
        model=FakeStructuredSummaryDictWithoutServiceMetadata(),
    )

    assert result.generated_at
    assert result.generated_at.endswith("Z")
    assert result.model_name == "gpt-5-nano"
    assert result.prompt_version == "repository-summary@test"


def test_summarize_repository_requires_model_when_context_is_sufficient():
    request = RepositorySummaryRequest(
        repository=RepositoryMetadata(
            repository_id="repo-1",
            full_name="acme/weather-agent",
            github_url="https://github.com/acme/weather-agent",
            description="Weather automation assistant",
        ),
        readme_text="# Weather Agent\n\nProvides weather automation helpers.",
    )

    with pytest.raises(MissingSummaryModelError):
        summarize_repository(request)


def test_summarize_repository_reports_insufficient_context_without_readme_or_description():
    request = RepositorySummaryRequest(
        repository=RepositoryMetadata(
            repository_id="repo-2",
            full_name="acme/empty",
            github_url="https://github.com/acme/empty",
        )
    )

    result = summarize_repository(request)

    assert result.summary_status == SummaryStatus.INSUFFICIENT_CONTEXT
    assert result.one_line_summary is None
    assert result.readme_summary is None
    assert result.project_purpose is None
    assert result.target_users == []
    assert result.possible_agent_relevance.level == AgentRelevanceLevel.UNKNOWN
    assert result.followup_hints.files == []
    assert result.followup_hints.directories == []
    assert result.followup_hints.questions == []
    assert "README content was not provided." in result.summary_limitations.missing_inputs
    assert (
        "Repository description was not provided."
        in result.summary_limitations.missing_inputs
    )
    assert "README와 repository metadata 기준 요약입니다." in (
        result.summary_limitations.notes
    )
    assert result.generated_at.endswith("Z")
    assert result.model_name == get_settings().summary_model
    assert result.prompt_version == SUMMARY_PROMPT_VERSION
    assert result.error_message is None


def test_summarize_repository_removes_followup_paths_outside_input_file_tree():
    class FakeModelWithInvalidHints(FakeStructuredSummaryModel):
        def invoke(self, payload):
            result = super().invoke(payload)
            result.followup_hints.files.append("invented.py")
            result.followup_hints.directories.append("missing_dir")
            return result

    request = RepositorySummaryRequest(
        repository=RepositoryMetadata(
            repository_id="repo-1",
            full_name="acme/weather-agent",
            github_url="https://github.com/acme/weather-agent",
            description="Weather automation assistant",
        ),
        readme_text="# Weather Agent\n\nProvides weather automation helpers.",
        shallow_file_tree=[
            "README.md",
            "examples/client.py",
            "src/weather_agent/server.py",
        ],
    )

    result = summarize_repository(request, model=FakeModelWithInvalidHints())

    assert result.followup_hints.files == ["examples/client.py"]
    assert result.followup_hints.directories == ["src/weather_agent"]
    assert "Removed follow-up files not present in file_tree: invented.py" in (
        result.summary_limitations.notes
    )


def test_summarize_repository_preserves_input_identity_over_model_output():
    class FakeModelWithWrongIdentity(FakeStructuredSummaryModel):
        def invoke(self, payload):
            result = super().invoke(payload)
            result.repository_id = "wrong-repo"
            result.full_name = "other/project"
            result.github_url = "https://github.com/other/project"
            return result

    request = RepositorySummaryRequest(
        repository=RepositoryMetadata(
            repository_id="repo-1",
            full_name="acme/weather-agent",
            github_url="https://github.com/acme/weather-agent",
            description="Weather automation assistant",
        ),
        snapshot_id="snapshot-from-request",
        readme_text="# Weather Agent",
    )

    result = summarize_repository(request, model=FakeModelWithWrongIdentity())

    assert result.repository_id == "repo-1"
    assert result.snapshot_id == "snapshot-from-request"
    assert result.full_name == "acme/weather-agent"
    assert result.github_url == "https://github.com/acme/weather-agent"


def test_summarize_repository_always_includes_base_limitations():
    class FakeModelWithoutBaseLimitations(FakeStructuredSummaryModel):
        def invoke(self, payload):
            result = super().invoke(payload)
            result.summary_limitations = SummaryLimitations()
            return result

    request = RepositorySummaryRequest(
        repository=RepositoryMetadata(
            repository_id="repo-1",
            full_name="acme/weather-agent",
            github_url="https://github.com/acme/weather-agent",
            description="Weather automation assistant",
        ),
        readme_text="# Weather Agent",
    )

    result = summarize_repository(request, model=FakeModelWithoutBaseLimitations())

    assert "README와 repository metadata 기준 요약입니다." in (
        result.summary_limitations.notes
    )
    assert "구현 근거 검증은 1차 Summary 단계에서 수행하지 않았습니다." in (
        result.summary_limitations.notes
    )


def test_summarize_repository_allows_directory_entries_from_file_tree():
    class FakeModelWithDirectoryHint(FakeStructuredSummaryModel):
        def invoke(self, payload):
            result = super().invoke(payload)
            result.followup_hints.directories = ["src/weather_agent"]
            return result

    request = RepositorySummaryRequest(
        repository=RepositoryMetadata(
            repository_id="repo-1",
            full_name="acme/weather-agent",
            github_url="https://github.com/acme/weather-agent",
            description="Weather automation assistant",
        ),
        readme_text="# Weather Agent",
        shallow_file_tree=["README.md", "src/weather_agent/"],
    )

    result = summarize_repository(request, model=FakeModelWithDirectoryHint())

    assert result.followup_hints.directories == ["src/weather_agent"]


def test_summarize_repository_allows_failed_summary_status():
    class FakeFailedModel(FakeStructuredSummaryModel):
        def invoke(self, payload):
            result = super().invoke(payload)
            result.summary_status = "failed"
            result.error_message = "README is too thin for a complete summary."
            result.summary_limitations.missing_inputs = ["README lacks usage examples."]
            return result

    request = RepositorySummaryRequest(
        repository=RepositoryMetadata(
            repository_id="repo-1",
            full_name="acme/weather-agent",
            github_url="https://github.com/acme/weather-agent",
            description="Weather automation assistant",
        ),
        readme_text="# Weather Agent",
    )

    result = summarize_repository(request, model=FakeFailedModel())

    assert result.summary_status == SummaryStatus.FAILED
    assert result.error_message == "README is too thin for a complete summary."
    assert result.summary_limitations.missing_inputs == ["README lacks usage examples."]


def test_summarize_repository_validates_dict_model_output():
    class FakeDictModel(FakeStructuredSummaryModel):
        def invoke(self, payload):
            return super().invoke(payload).model_dump()

    request = RepositorySummaryRequest(
        repository=RepositoryMetadata(
            repository_id="repo-1",
            full_name="acme/weather-agent",
            github_url="https://github.com/acme/weather-agent",
            description="Weather automation assistant",
        ),
        readme_text="# Weather Agent",
    )

    result = summarize_repository(request, model=FakeDictModel())

    assert result.summary_status == SummaryStatus.COMPLETED
    assert result.full_name == "acme/weather-agent"


def test_build_failed_summary_returns_persistable_failure():
    request = RepositorySummaryRequest(
        repository=RepositoryMetadata(
            repository_id="repo-1",
            full_name="acme/weather-agent",
            github_url="https://github.com/acme/weather-agent",
            description="Weather automation assistant",
        ),
        snapshot_id="snapshot-1",
    )

    result = build_failed_summary(
        request,
        "model timeout",
        model_name="gpt-5-mini",
        prompt_version="repository-summary@test",
    )

    assert result.repository_id == "repo-1"
    assert result.snapshot_id == "snapshot-1"
    assert result.full_name == "acme/weather-agent"
    assert result.github_url == "https://github.com/acme/weather-agent"
    assert result.summary_status == SummaryStatus.FAILED
    assert result.one_line_summary is None
    assert result.readme_summary is None
    assert result.project_purpose is None
    assert result.target_users == []
    assert result.followup_hints.files == []
    assert result.summary_limitations.notes == [
        "README와 repository metadata 기준 요약입니다.",
        "구현 근거 검증은 1차 Summary 단계에서 수행하지 않았습니다.",
    ]
    assert result.generated_at.endswith("Z")
    assert result.model_name == "gpt-5-mini"
    assert result.prompt_version == "repository-summary@test"
    assert result.error_message == "model timeout"


def test_summary_prompt_constants_are_stable():
    assert SUMMARY_PROMPT_ID == "repository-summary"
    assert SUMMARY_PROMPT_VERSION == "repository-summary@1.0.0"


def test_load_summary_prompt_reads_prompt_asset():
    prompt = load_summary_prompt()

    assert "What does this repository appear to be" in prompt
    assert "Do not infer implementation evidence" in prompt


def test_summary_prompt_has_versioned_frontmatter():
    prompt = load_summary_prompt()

    assert prompt.startswith("---\n")
    frontmatter = prompt.split("---\n", 2)[1]
    assert "prompt_id: repository-summary" in frontmatter
    assert "prompt_version: repository-summary@1.0.0" in frontmatter
    assert "contract: artifacts/current/AI_ANALYSIS_SPEC.md" in frontmatter
    assert (
        "purpose: Generate first-pass repository summaries from collected "
        "repository metadata, README text, and shallow file tree."
    ) in frontmatter
    assert (
        "breaking_change_policy: Major version changes when output schema or "
        "required summary behavior changes; minor for meaningful behavior "
        "improvements; patch for non-behavioral wording clarifications."
    ) in frontmatter


def test_summary_prompt_enforces_korean_artifact_contract():
    prompt = load_summary_prompt()

    assert "Use only repository metadata, README, topics, primary language" in prompt
    assert "activity metadata" in prompt
    assert (
        "one_line_summary, readme_summary, and project_purpose must be Korean "
        "single strings / 한국어 단일 문자열, not LocalizedText"
    ) in prompt
    assert 'Use only "completed", "insufficient_context", or "failed"' in prompt
    assert 'Do not use "limited"' in prompt
    assert "Do not infer target users without README/metadata support" in prompt
    assert "Do not invent files, directories, or follow-up questions" in prompt
    assert (
        "possible_agent_relevance is a temporary hint, not a score or final "
        "classification"
    ) in prompt
    assert (
        "summary_limitations is an object with missing_inputs, "
        "truncated_inputs, and notes"
    ) in prompt
    assert (
        "Do not claim code execution, benchmark, security, performance, or "
        "implementation validation"
    ) in prompt


def test_get_settings_reads_env_file(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "OPENAI_API_KEY=env-file-key",
                "OPENAI_API_BASE=https://gms.ssafy.io/gmsapi/api.openai.com/v1",
                "AGENTTRACE_SUMMARY_MODEL=gpt-test-model",
                "AGENTTRACE_SERVICE_NAME=agenttrace-test",
                "LANGSMITH_TRACING=true",
                "LANGSMITH_API_KEY=langsmith-env-file-key",
                "LANGSMITH_PROJECT=agenthub-local",
                "LANGSMITH_ENDPOINT=https://api.smith.langchain.com",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_BASE", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("AGENTTRACE_SUMMARY_MODEL", raising=False)
    monkeypatch.delenv("AGENTTRACE_SERVICE_NAME", raising=False)
    monkeypatch.delenv("LANGSMITH_TRACING", raising=False)
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    monkeypatch.delenv("LANGSMITH_PROJECT", raising=False)
    monkeypatch.delenv("LANGSMITH_ENDPOINT", raising=False)

    settings = get_settings()

    assert settings.openai_api_key == "env-file-key"
    assert settings.openai_api_base == "https://gms.ssafy.io/gmsapi/api.openai.com/v1"
    assert settings.summary_model == "gpt-test-model"
    assert settings.service_name == "agenttrace-test"
    assert settings.langsmith_tracing == "true"
    assert settings.langsmith_api_key == "langsmith-env-file-key"
    assert settings.langsmith_project == "agenthub-local"
    assert settings.langsmith_endpoint == "https://api.smith.langchain.com"


def test_configure_runtime_environment_exports_langsmith_env(tmp_path, monkeypatch):
    from agenttrace.config import configure_runtime_environment

    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "LANGSMITH_TRACING=true",
                "LANGSMITH_API_KEY=langsmith-env-file-key",
                "LANGSMITH_PROJECT=agenthub-local",
                "LANGSMITH_ENDPOINT=https://api.smith.langchain.com",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("LANGSMITH_TRACING", raising=False)
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    monkeypatch.delenv("LANGSMITH_PROJECT", raising=False)
    monkeypatch.delenv("LANGSMITH_ENDPOINT", raising=False)

    configure_runtime_environment()

    assert os.environ["LANGSMITH_TRACING"] == "true"
    assert os.environ["LANGSMITH_API_KEY"] == "langsmith-env-file-key"
    assert os.environ["LANGSMITH_PROJECT"] == "agenthub-local"
    assert os.environ["LANGSMITH_ENDPOINT"] == "https://api.smith.langchain.com"


def test_openai_summary_model_receives_env_file_api_key(tmp_path, monkeypatch):
    captured = {}

    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "OPENAI_API_KEY=env-file-key",
                "OPENAI_API_BASE=https://gms.ssafy.io/gmsapi/api.openai.com/v1",
                "AGENTTRACE_SUMMARY_MODEL=gpt-test-model",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_BASE", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("AGENTTRACE_SUMMARY_MODEL", raising=False)
    monkeypatch.setitem(
        sys.modules,
        "langchain_openai",
        types.SimpleNamespace(ChatOpenAI=FakeChatOpenAI),
    )

    build_openai_summary_model()

    assert captured["api_key"] == "env-file-key"
    assert captured["base_url"] == "https://gms.ssafy.io/gmsapi/api.openai.com/v1"
    assert captured["model"] == "gpt-test-model"
    assert captured["temperature"] == 0


def test_repository_summary_includes_possible_agent_relevance_hint():
    request = RepositorySummaryRequest(
        repository=RepositoryMetadata(
            repository_id="repo-1",
            full_name="acme/harness",
            github_url="https://github.com/acme/harness",
        )
    )

    result = summarize_repository(request)

    assert result.possible_agent_relevance.level == AgentRelevanceLevel.UNKNOWN
    assert result.possible_agent_relevance.reason


def test_summary_prompt_omits_removed_legacy_fields():
    prompt = load_summary_prompt()

    assert "possible harness relevance" not in prompt.lower()
    assert "apparent_target_users" not in prompt
    assert "readme_claims" not in prompt
    assert "missing_details" not in prompt
    assert "confidence" not in prompt.lower()
    assert "Do not claim source-code confirmation" in prompt


def test_summarize_repository_truncates_readme():
    request = RepositorySummaryRequest(
        repository=RepositoryMetadata(
            full_name="acme/large-readme",
            github_url="https://github.com/acme/large-readme",
        ),
        readme_text="A" * 35000,
    )
    model = FakeStructuredSummaryModel()
    result = summarize_repository(request, model=model)

    assert result.summary_limitations.truncated_inputs == ["README"]
    assert "[Truncated by AgentTrace before summary generation.]" in request.readme_text
