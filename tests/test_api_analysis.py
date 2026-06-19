from __future__ import annotations

import asyncio
import uuid
import pytest
from fastapi.testclient import TestClient

from agenttrace.api.analysis import active_analyses
from agenttrace.app.main import create_app


def mock_fetch_repo_digest(full_name):
    return {
        "repository": {
            "id": "repo-123",
            "full_name": "acme/harness",
            "html_url": "https://github.com/acme/harness",
            "description": "Coding agent harness with tools and sandbox.",
            "topics": ["agent", "harness"],
            "language": "Python",
            "stars": 15,
            "forks": 2,
            "pushed_at": "2026-06-18T00:00:00Z",
            "updated_at": "2026-06-18T00:00:00Z",
        },
        "readme": "Coding agent harness with tools and sandbox.",
        "file_tree": [
            "README.md",
            "src/agent_loop.py",
            "src/tools/registry.py",
            "src/workspace/sandbox.py",
        ],
    }


def test_trigger_analysis_concurrency(monkeypatch) -> None:
    # Ensure active_analyses is empty at start
    active_analyses.clear()
    
    # Mock network calls
    monkeypatch.setattr("agenttrace.api.analysis.fetch_repo_digest", mock_fetch_repo_digest)
    
    class MockResponse:
        def raise_for_status(self):
            pass
            
    monkeypatch.setattr("httpx.post", lambda *args, **kwargs: MockResponse())

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


def test_trigger_analysis_e2e(monkeypatch) -> None:
    active_analyses.clear()
    monkeypatch.setattr("agenttrace.api.analysis.fetch_repo_digest", mock_fetch_repo_digest)
    
    class MockResponse:
        def raise_for_status(self):
            pass
            
    monkeypatch.setattr("httpx.post", lambda *args, **kwargs: MockResponse())

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


def test_trigger_analysis_callback(monkeypatch) -> None:
    active_analyses.clear()
    monkeypatch.setattr("agenttrace.api.analysis.fetch_repo_digest", mock_fetch_repo_digest)

    captured_callbacks = []
    
    class MockResponse:
        def raise_for_status(self):
            pass
            
    def mock_post(url, *args, **kwargs):
        captured_callbacks.append((url, kwargs.get("json")))
        return MockResponse()

    monkeypatch.setattr("httpx.post", mock_post)

    client = TestClient(create_app())
    analysis_id = uuid.uuid4()
    req_payload = {
        "analysis_id": str(analysis_id),
        "repository_id": str(uuid.uuid4()),
        "snapshot_id": str(uuid.uuid4()),
        "commit_sha": "abcdef123456",
        "github_url": "https://github.com/acme/harness",
    }
    response = client.post("/api/v1/analysis", json=req_payload)
    assert response.status_code == 202
    
    # Assert that the callback was called exactly once with status COMPLETED
    assert len(captured_callbacks) == 1
    url, payload = captured_callbacks[0]
    assert url == "http://localhost:8080/api/v1/internal/analysis/callback"
    assert payload["analysis_id"] == str(analysis_id)
    assert payload["status"] == "COMPLETED"
    assert payload["error_message"] is None
    
    # Assert result_json schema
    result = payload["result_json"]
    assert result["agent_type"] == "EVAL_HARNESS"
    assert "tech_stack_summary" in result
    assert result["tech_stack_summary"]["primary_language"] == "Python"
    assert "claims" in result
    assert len(result["claims"]) > 0
    # Every claim must have keys: claim_text, evidence_status, confidence_level, supporting_evidence, limitation
    for claim in result["claims"]:
        assert "claim_text" in claim
        assert "evidence_status" in claim
        assert "confidence_level" in claim
        assert "supporting_evidence" in claim
        assert "limitation" in claim
    assert "limitations" in result
    assert "missing_evidence" in result
    assert "followup_questions" in result


def test_trigger_analysis_callback_failure(monkeypatch) -> None:
    active_analyses.clear()
    
    # Simulate fetch_repo_digest raising an error
    def mock_fetch_repo_digest_fail(full_name):
        raise ValueError("Simulated repo ingest failure")
        
    monkeypatch.setattr("agenttrace.api.analysis.fetch_repo_digest", mock_fetch_repo_digest_fail)

    captured_callbacks = []
    
    class MockResponse:
        def raise_for_status(self):
            pass
            
    def mock_post(url, *args, **kwargs):
        captured_callbacks.append((url, kwargs.get("json")))
        return MockResponse()

    monkeypatch.setattr("httpx.post", mock_post)

    client = TestClient(create_app())
    analysis_id = uuid.uuid4()
    req_payload = {
        "analysis_id": str(analysis_id),
        "repository_id": str(uuid.uuid4()),
        "snapshot_id": str(uuid.uuid4()),
        "commit_sha": "abcdef123456",
        "github_url": "https://github.com/acme/harness",
    }
    
    # When background task runs synchronously under TestClient, it raises the re-raised ValueError,
    # so we expect client.post to raise it.
    with pytest.raises(ValueError, match="Simulated repo ingest failure"):
        client.post("/api/v1/analysis", json=req_payload)
        
    # Assert that the callback was called exactly once with status FAILED
    assert len(captured_callbacks) == 1
    url, payload = captured_callbacks[0]
    assert url == "http://localhost:8080/api/v1/internal/analysis/callback"
    assert payload["analysis_id"] == str(analysis_id)
    assert payload["status"] == "FAILED"
    assert "Simulated repo ingest failure" in payload["error_message"]
    
    # result_json should be a default dict matching the schema
    result = payload["result_json"]
    assert result["agent_type"] == "UNKNOWN"
    assert result["tech_stack_summary"] == {}
    assert result["claims"] == []
