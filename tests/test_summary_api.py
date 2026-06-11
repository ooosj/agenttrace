from __future__ import annotations

from fastapi.testclient import TestClient

from agenttrace.agents.summary import RepositorySummary, RepositorySummaryInput
from agenttrace.agents.summary.service import (
    MissingSummaryModelError,
    SummaryGenerationError,
)
from agenttrace.app.main import create_app


class FakeStructuredSummaryModel:
    def with_structured_output(self, schema):
        self.schema = schema
        return self

    def invoke(self, _payload):
        return self.schema(
            repository_id="repo-1",
            full_name="acme/weather-agent",
            github_url="https://github.com/acme/weather-agent",
            one_line_summary="Weather Agent appears to provide weather automation tools.",
            readme_summary="Weather Agent is presented as an MCP-style weather automation project.",
            project_purpose="Provide weather automation helpers for agent workflows.",
            apparent_target_users=["agent developers", "MCP users"],
            readme_claims=["README says the project provides forecast lookup."],
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


def test_health_endpoint_reports_ok():
    client = TestClient(create_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "agenttrace-ai"}


def test_repository_summary_endpoint_returns_summary(monkeypatch):
    monkeypatch.setattr(
        "agenttrace.app.dependencies.build_openai_summary_model",
        lambda: FakeStructuredSummaryModel(),
    )
    client = TestClient(create_app())

    response = client.post(
        "/v1/repository-summaries",
        json={
            "repository_id": "repo-1",
            "full_name": "acme/weather-agent",
            "github_url": "https://github.com/acme/weather-agent",
            "description": "Weather automation helpers",
            "topics": ["agent"],
            "primary_language": "Python",
            "readme": "# Weather Agent",
            "file_tree": ["README.md", "examples/client.py"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["summary_status"] == "completed"
    assert body["possible_agent_relevance"]["level"] == "medium"
    assert body["followup_hints"]["files"] == ["examples/client.py"]
    assert body["apparent_target_users"] == ["agent developers", "MCP users"]


def test_repository_summary_from_github_url_ingests_repo_before_summarizing(monkeypatch):
    monkeypatch.setattr(
        "agenttrace.app.dependencies.build_openai_summary_model",
        lambda: FakeStructuredSummaryModel(),
    )

    captured = {}

    def fake_fetch_repo_digest(full_name):
        captured["full_name"] = full_name
        return {
            "repository": {
                "id": "repo-1",
                "full_name": "acme/weather-agent",
                "html_url": "https://github.com/acme/weather-agent",
                "description": "Weather automation helpers",
                "topics": ["agent"],
                "language": "Python",
            },
            "readme": "# Weather Agent",
            "file_tree": ["README.md", "examples/client.py"],
        }

    def fake_summarize(summary_input, **kwargs):
        captured["summary_input"] = summary_input
        captured["model"] = kwargs["model"]
        return RepositorySummary(
            repository_id=summary_input.repository_id,
            full_name=summary_input.full_name,
            github_url=summary_input.github_url,
            one_line_summary="Weather Agent appears to provide weather automation tools.",
            readme_summary="Weather Agent is presented as an MCP-style weather automation project.",
            summary_status="completed",
            summary_status_reason="README and metadata provide enough detail for a useful summary.",
        )

    monkeypatch.setattr(
        "agenttrace.app.routers.summaries.fetch_repo_digest",
        fake_fetch_repo_digest,
    )
    monkeypatch.setattr(
        "agenttrace.app.routers.summaries.summarize_repository",
        fake_summarize,
    )
    client = TestClient(create_app())

    response = client.post(
        "/v1/repository-summaries/from-github-url",
        json={"github_url": "https://github.com/acme/weather-agent"},
    )

    assert response.status_code == 200
    assert captured["full_name"] == "acme/weather-agent"
    assert captured["model"] is not None
    assert captured["summary_input"] == RepositorySummaryInput(
        repository_id="repo-1",
        full_name="acme/weather-agent",
        github_url="https://github.com/acme/weather-agent",
        description="Weather automation helpers",
        topics=["agent"],
        primary_language="Python",
        readme="# Weather Agent",
        file_tree=["README.md", "examples/client.py"],
    )


def test_repository_summary_from_github_url_rejects_non_github_url():
    client = TestClient(create_app())

    response = client.post(
        "/v1/repository-summaries/from-github-url",
        json={"github_url": "https://example.com/acme/weather-agent"},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["error"] == "invalid_github_url"


def test_repository_summary_endpoint_maps_missing_model_to_500(monkeypatch):
    def fake_build_model():
        raise MissingSummaryModelError("OPENAI_API_KEY is required.")

    monkeypatch.setattr(
        "agenttrace.app.dependencies.build_openai_summary_model",
        fake_build_model,
    )
    client = TestClient(create_app())

    response = client.post(
        "/v1/repository-summaries",
        json={
            "repository_id": "repo-1",
            "full_name": "acme/weather-agent",
            "github_url": "https://github.com/acme/weather-agent",
            "description": "Weather automation helpers",
        },
    )

    assert response.status_code == 500
    assert response.json()["detail"]["error"] == "summary_model_not_configured"


def test_repository_summary_endpoint_maps_llm_failure_to_502(monkeypatch):
    monkeypatch.setattr(
        "agenttrace.app.dependencies.build_openai_summary_model",
        lambda: FakeStructuredSummaryModel(),
    )

    def fake_summarize(_summary_input, **_kwargs):
        raise SummaryGenerationError("Repository summary generation failed.")

    monkeypatch.setattr("agenttrace.app.routers.summaries.summarize_repository", fake_summarize)
    client = TestClient(create_app())

    response = client.post(
        "/v1/repository-summaries",
        json={
            "repository_id": "repo-1",
            "full_name": "acme/weather-agent",
            "github_url": "https://github.com/acme/weather-agent",
            "description": "Weather automation helpers",
        },
    )

    assert response.status_code == 502
    assert response.json()["detail"]["error"] == "summary_generation_failed"
