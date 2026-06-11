from __future__ import annotations

import os
import sys
import types

import pytest

from agenttrace.agents.summary import (
    AgentRelevanceLevel,
    ConfidenceLevel,
    RepositorySummaryInput,
    SummaryStatus,
    summarize_repository,
)
from agenttrace.agents.summary.service import (
    MissingSummaryModelError,
    load_summary_prompt,
)
from agenttrace.config import get_settings
from agenttrace.models import build_openai_summary_model


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
            full_name="acme/weather-agent",
            github_url="https://github.com/acme/weather-agent",
            one_line_summary="Weather Agent appears to provide weather automation tools.",
            readme_summary="Weather Agent is presented as an MCP-style weather automation project.",
            project_purpose="Provide weather automation helpers for agent workflows.",
            apparent_target_users=["agent developers", "MCP users"],
            readme_claims=[
                "README says the project provides forecast lookup.",
                "README says it includes integration examples.",
            ],
            readme_described_features=["forecast lookup", "weather alerts"],
            possible_agent_relevance={
                "level": "medium",
                "reason": "README mentions agent workflows, but implementation evidence was not validated.",
            },
            followup_hints={
                "readme_sections": ["Usage"],
                "files": ["examples/client.py"],
                "directories": ["src/weather_agent"],
                "questions": ["Does the example run with a real API key?"],
            },
            summary_basis={
                "used_readme": True,
                "used_description": True,
                "used_topics": True,
                "used_primary_language": True,
                "used_file_tree": True,
            },
            input_gaps=[],
            missing_details=["Runtime behavior was not checked."],
            summary_limitations=[
                "Implementation evidence was not validated in this summary step."
            ],
            confidence="medium",
            summary_status="completed",
            summary_status_reason="README and metadata provide enough detail for a useful summary.",
        )


def test_repository_summary_input_defaults_optional_fields():
    summary_input = RepositorySummaryInput(
        repository_id="repo-1",
        full_name="acme/weather-agent",
        github_url="https://github.com/acme/weather-agent",
    )

    assert summary_input.description is None
    assert summary_input.topics == []
    assert summary_input.primary_language is None
    assert summary_input.readme is None
    assert summary_input.file_tree == []


def test_summarize_repository_uses_llm_model_with_readme_and_metadata():
    summary_input = RepositorySummaryInput(
        repository_id="repo-1",
        full_name="acme/weather-agent",
        github_url="https://github.com/acme/weather-agent",
        description="Weather automation assistant",
        topics=["weather", "agent", "mcp"],
        primary_language="Python",
        readme="""
        # Weather Agent

        Weather Agent is an MCP server for weather automation.

        It provides forecast lookup, weather alerts, and tool calling examples.
        It includes a local CLI and integration examples.
        """,
        file_tree=[
            "README.md",
            "src/weather_agent/server.py",
            "examples/client.py",
            "tests/test_server.py",
        ],
    )
    model = FakeStructuredSummaryModel()

    result = summarize_repository(summary_input, model=model)

    assert result.summary_status == SummaryStatus.COMPLETED
    assert result.one_line_summary == (
        "Weather Agent appears to provide weather automation tools."
    )
    assert result.apparent_target_users == ["agent developers", "MCP users"]
    assert result.possible_agent_relevance.level == AgentRelevanceLevel.MEDIUM
    assert result.confidence == ConfidenceLevel.MEDIUM
    assert result.project_purpose
    assert any("forecast lookup" in feature for feature in result.readme_described_features)
    assert "examples/client.py" in result.followup_hints.files
    prompt_text = "\n".join(message.content for message in model.last_payload.to_messages())
    assert "acme/weather-agent" in prompt_text
    assert "Weather Agent is an MCP server" in prompt_text


def test_summarize_repository_requires_model_when_context_is_sufficient():
    summary_input = RepositorySummaryInput(
        repository_id="repo-1",
        full_name="acme/weather-agent",
        github_url="https://github.com/acme/weather-agent",
        description="Weather automation assistant",
        readme="# Weather Agent\n\nProvides weather automation helpers.",
    )

    with pytest.raises(MissingSummaryModelError):
        summarize_repository(summary_input)


def test_summarize_repository_reports_insufficient_context_without_readme_or_description():
    summary_input = RepositorySummaryInput(
        repository_id="repo-2",
        full_name="acme/empty",
        github_url="https://github.com/acme/empty",
    )

    result = summarize_repository(summary_input)

    assert result.summary_status == SummaryStatus.INSUFFICIENT_CONTEXT
    assert result.one_line_summary == "acme/empty has insufficient summary context."
    assert result.readme_claims == []
    assert result.readme_described_features == []
    assert result.apparent_target_users == []
    assert result.possible_agent_relevance.level == AgentRelevanceLevel.UNKNOWN
    assert result.followup_hints.files == []
    assert result.input_gaps
    assert result.summary_status_reason
    assert any("README content was not provided." in item for item in result.summary_limitations)


def test_summarize_repository_removes_followup_paths_outside_input_file_tree():
    class FakeModelWithInvalidHints(FakeStructuredSummaryModel):
        def invoke(self, payload):
            result = super().invoke(payload)
            result.followup_hints.files.append("invented.py")
            result.followup_hints.directories.append("missing_dir")
            return result

    summary_input = RepositorySummaryInput(
        repository_id="repo-1",
        full_name="acme/weather-agent",
        github_url="https://github.com/acme/weather-agent",
        description="Weather automation assistant",
        readme="# Weather Agent\n\nProvides weather automation helpers.",
        file_tree=["README.md", "examples/client.py", "src/weather_agent/server.py"],
    )

    result = summarize_repository(summary_input, model=FakeModelWithInvalidHints())

    assert result.followup_hints.files == ["examples/client.py"]
    assert result.followup_hints.directories == ["src/weather_agent"]
    assert "Removed follow-up files not present in file_tree: invented.py" in (
        result.summary_limitations
    )


def test_summarize_repository_allows_limited_summary_status():
    class FakeLimitedModel(FakeStructuredSummaryModel):
        def invoke(self, payload):
            result = super().invoke(payload)
            result.summary_status = "limited"
            result.summary_status_reason = "README is too thin for a complete summary."
            result.input_gaps = ["README lacks usage examples."]
            result.confidence = "low"
            return result

    summary_input = RepositorySummaryInput(
        repository_id="repo-1",
        full_name="acme/weather-agent",
        github_url="https://github.com/acme/weather-agent",
        description="Weather automation assistant",
        readme="# Weather Agent",
    )

    result = summarize_repository(summary_input, model=FakeLimitedModel())

    assert result.summary_status == SummaryStatus.LIMITED
    assert result.confidence == ConfidenceLevel.LOW
    assert result.input_gaps == ["README lacks usage examples."]


def test_load_summary_prompt_reads_prompt_asset():
    prompt = load_summary_prompt()

    assert "What does this repository appear to be" in prompt
    assert "Do not infer implementation evidence" in prompt


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


def test_repository_summary_includes_possible_harness_relevance_hint():
    summary_input = RepositorySummaryInput(
        repository_id="repo-1",
        full_name="acme/harness",
        github_url="https://github.com/acme/harness",
    )

    result = summarize_repository(summary_input)

    assert result.possible_harness_relevance.level == AgentRelevanceLevel.UNKNOWN
    assert result.possible_harness_relevance.confidence == ConfidenceLevel.UNKNOWN
    assert "[확인 필요]" in result.possible_harness_relevance.reason


def test_summary_prompt_mentions_harness_relevance_rules():
    prompt = load_summary_prompt()

    assert "possible harness relevance" in prompt.lower()
    assert "README claims alone must not produce high confidence" in prompt
    assert "Do not claim source-code confirmation" in prompt
