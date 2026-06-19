from __future__ import annotations

import asyncio
import uuid

from fastapi.testclient import TestClient

from agenttrace.api.analysis import active_analyses
from agenttrace.app.main import create_app


def test_trigger_analysis_concurrency(monkeypatch) -> None:
    # Ensure active_analyses is empty at start
    active_analyses.clear()

    # Let's mock background tasks to not execute automatically
    captured_tasks = []

    def mock_add_task(self, func, *args, **kwargs) -> None:
        captured_tasks.append((func, args, kwargs))

    monkeypatch.setattr("fastapi.BackgroundTasks.add_task", mock_add_task)

    client = TestClient(create_app())

    analysis_id = uuid.uuid4()
    req_payload = {
        "analysis_id": str(analysis_id),
        "repository_id": str(uuid.uuid4()),
        "snapshot_id": str(uuid.uuid4()),
        "commit_sha": "abcdef123456",
        "github_url": "https://github.com/example/repo",
    }

    # 1. Trigger analysis -> Should succeed with 202
    response1 = client.post("/api/v1/analysis", json=req_payload)
    assert response1.status_code == 202
    assert response1.json() == {
        "status": "queued",
        "message": "Analysis started asynchronously.",
    }

    # Verify that analysis_id is now in active_analyses
    assert str(analysis_id) in active_analyses

    # 2. Trigger again with same analysis_id -> Should fail with 409 Conflict
    response2 = client.post("/api/v1/analysis", json=req_payload)
    assert response2.status_code == 409
    assert response2.json()["detail"] == "Analysis already in progress for this analysis_id."

    # 3. Verify task is in captured_tasks
    assert len(captured_tasks) == 1
    func, args, kwargs = captured_tasks[0]

    # Let's run the background task (which is run_pipeline_async)
    asyncio.run(func(*args, **kwargs))

    # 4. Verify analysis_id has been removed from active_analyses after execution
    assert str(analysis_id) not in active_analyses


def test_trigger_analysis_e2e() -> None:
    active_analyses.clear()
    client = TestClient(create_app())
    analysis_id = uuid.uuid4()
    req_payload = {
        "analysis_id": str(analysis_id),
        "repository_id": str(uuid.uuid4()),
        "snapshot_id": str(uuid.uuid4()),
        "commit_sha": "abcdef123456",
        "github_url": "https://github.com/example/repo",
    }
    response = client.post("/api/v1/analysis", json=req_payload)
    assert response.status_code == 202
    assert response.json() == {
        "status": "queued",
        "message": "Analysis started asynchronously.",
    }
    # Under normal TestClient, background tasks run synchronously before response is returned,
    # so active_analyses should already be cleared here.
    assert str(analysis_id) not in active_analyses
