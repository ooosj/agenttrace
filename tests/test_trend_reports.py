from fastapi.testclient import TestClient

from agenttrace.app.dependencies import get_summary_model_factory
from agenttrace.app.main import create_app


class FakeStructuredModel:
    def with_structured_output(self, schema):
        return self

    def invoke(self, prompt):
        from agenttrace.agents.reports import TrendReport

        return TrendReport(
            title="Weekly AI Open Source Radar",
            executive_summary="Agent tooling gained attention this week.",
            featured_repositories=[
                {"repository_id": "repo-1", "reason": "Highest verified star growth."},
                {"repository_id": "invented", "reason": "Must be removed."},
            ],
        )


def test_create_weekly_trend_report_filters_unknown_repository_ids():
    app = create_app()
    app.dependency_overrides[get_summary_model_factory] = lambda: lambda: FakeStructuredModel()
    client = TestClient(app)

    response = client.post(
        "/v1/trend-reports",
        json={
            "period_start": "2026-06-08",
            "period_end": "2026-06-14",
            "repositories": [
                {
                    "repository_id": "repo-1",
                    "full_name": "acme/agent",
                    "stars": 120,
                    "star_delta": 20,
                }
            ],
        },
    )

    assert response.status_code == 200
    assert response.json()["featured_repositories"] == [
        {"repository_id": "repo-1", "reason": "Highest verified star growth."}
    ]
