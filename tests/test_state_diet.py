from __future__ import annotations

import os
import shutil
from pathlib import Path
from uuid import uuid4

import pytest

from agenttrace.agents.analysis.nodes.collect_inputs import collect_inputs
from agenttrace.agents.analysis.nodes.content_preprocessor import content_preprocessor
from agenttrace.agents.analysis.nodes.evidence_evaluator import evidence_evaluator
from agenttrace.agents.analysis.nodes.finalize_analysis import finalize_analysis
from agenttrace.agents.analysis.nodes.critical_error_handler import critical_error_handler
from agenttrace.agents.analysis.nodes.harness_analyzer import harness_analyzer
from agenttrace.agents.analysis.schemas.input import AnalysisInputRequest
from agenttrace.config import get_settings


def test_collect_inputs_saves_to_disk_and_strips_content():
    run_id = f"test-run-{uuid4()}"
    state = {
        "run_id": run_id,
        "analysis_request": {
            "analysis_id": "00000000-0000-0000-0000-000000000001",
            "repository": {
                "repository_id": "00000000-0000-0000-0000-000000000002",
                "full_name": "test/repo",
            },
            "source_files": [
                {"path": "src/main.py", "content": "print('hello')"},
                {"path": "config.json", "content": '{"debug": true}'},
            ],
            "file_tree": ["src/main.py", "config.json"],
        }
    }

    try:
        res = collect_inputs(state)
        
        # Verify run_id and local_repo_dir
        assert res["run_id"] == run_id
        local_repo_dir = Path(res["local_repo_dir"])
        assert local_repo_dir.exists()
        
        # Verify files are written on disk
        assert (local_repo_dir / "src/main.py").read_text(encoding="utf-8") == "print('hello')"
        assert (local_repo_dir / "config.json").read_text(encoding="utf-8") == '{"debug": true}'
        
        # Verify state content is stripped
        for sf in res["source_files"]:
            assert sf["content"] == ""
        for sf in res["selected_files"]:
            assert sf["content"] == ""
            
    finally:
        shutil.rmtree(Path("tmp/agenttrace") / run_id, ignore_errors=True)


def test_content_preprocessor_reads_from_disk_and_strips_chunks():
    run_id = f"test-run-{uuid4()}"
    local_repo_dir = Path("tmp/agenttrace") / run_id
    local_repo_dir.mkdir(parents=True, exist_ok=True)
    
    file_content = "def test_func():\n    return 'test'"
    (local_repo_dir / "src/test.py").parent.mkdir(parents=True, exist_ok=True)
    (local_repo_dir / "src/test.py").write_text(file_content, encoding="utf-8")
    
    import hashlib
    expected_hash = "sha256:" + hashlib.sha256(file_content.encode("utf-8")).hexdigest()
    state = {
        "run_id": run_id,
        "local_repo_dir": str(local_repo_dir),
        "source_files": [
            {"path": "src/test.py", "content": "", "content_hash": expected_hash}
        ]
    }
    
    try:
        res = content_preprocessor(state)
        
        # Verify chunks are created
        assert len(res["content_chunks"]) > 0
        for chunk in res["content_chunks"]:
            assert chunk["content"] == ""
            
        # Verify chunk_index content is also stripped
        idx = res["chunk_index"]
        for c in idx["chunks_by_id"].values():
            assert c["content"] == ""
    finally:
        shutil.rmtree(local_repo_dir, ignore_errors=True)


def test_evidence_evaluator_reads_and_slices_utf8_correctly(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("AGENTTRACE_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    get_settings.cache_clear()
    run_id = f"test-run-{uuid4()}"
    local_repo_dir = Path("tmp/agenttrace") / run_id
    local_repo_dir.mkdir(parents=True, exist_ok=True)
    
    # "Hello 한글 World"
    # UTF-8: b'Hello \xed\x95\x9c\xea\xb8\x80 World'
    # '한글' is at byte offset 6 to 12.
    content_str = "Hello 한글 World"
    (local_repo_dir / "src/lang.py").parent.mkdir(parents=True, exist_ok=True)
    (local_repo_dir / "src/lang.py").write_text(content_str, encoding="utf-8")
    
    state = {
        "run_id": run_id,
        "local_repo_dir": str(local_repo_dir),
        "current_task_id": "task-1",
        "analysis_plan": {
            "tasks": [
                {
                    "task_id": "task-1",
                    "claims": ["claim-1"],
                    "target_paths": ["src/lang.py"],
                    "required": True,
                    "status": "PENDING",
                }
            ]
        },
        "claims": [{"claim_id": "claim-1", "claim_text": "lang support 한글"}],
        "selected_chunks": [
            {
                "chunk_id": "chunk-1",
                "file_path": "src/lang.py",
                "content": "",
                "start_byte": 6,
                "end_byte": 12,
                "line_start": 1,
                "line_end": 1,
                "is_partial": False,
                "content_hash": "sha256:" + "0" * 64,
            }
        ],
        "task_parts": [
            {
                "part_id": "task-1-part-001",
                "task_id": "task-1",
                "chunks": ["chunk-1"],
            }
        ],
    }
    
    try:
        # We need to run the evaluator. Since it might call LLM, we verify the evaluation.
        # But wait, LLM requires OPENAI_API_KEY. If not set, it falls back to keyword matching.
        # Our keyword matching fallback should read from disk and slice bytes correctly.
        # Let's ensure OPENAI_API_KEY is unset or we test the fallback specifically.
        res = evidence_evaluator(state)
        
        # Verify evidence signals contain the correct text excerpt
        signals = res["task_part_results"][0]["evidence_signals"]
        assert len(signals) > 0
        # The sliced content must contain exactly "한글" (the UTF-8 byte slice)
        assert "한글" in signals[0]["content_excerpt"]
    finally:
        shutil.rmtree(local_repo_dir, ignore_errors=True)


def test_path_traversal_prevention():
    run_id = f"test-run-{uuid4()}"
    local_repo_dir = Path("tmp/agenttrace") / run_id
    local_repo_dir.mkdir(parents=True, exist_ok=True)

    state = {
        "run_id": run_id,
        "local_repo_dir": str(local_repo_dir),
        "source_files": [
            {"path": "../../etc/passwd", "content": "dangerous", "content_hash": "h1"}
        ]
    }

    try:
        # Writing should raise ValueError or handle traversal safely (ignoring or raising)
        # Let's test with collect_inputs
        state_collect = {
            "run_id": run_id,
            "analysis_request": {
                "analysis_id": "00000000-0000-0000-0000-000000000001",
                "repository": {"full_name": "test/repo"},
                "source_files": [
                    {"path": "../../etc/passwd", "content": "dangerous"},
                ],
                "file_tree": ["../../etc/passwd"],
            }
        }
        
        with pytest.raises(ValueError, match="[Pp]ath [Tt]raversal"):
            collect_inputs(state_collect)
            
    finally:
        shutil.rmtree(local_repo_dir, ignore_errors=True)


def test_harness_analyzer_reads_from_disk():
    run_id = f"test-run-{uuid4()}"
    local_repo_dir = Path("tmp/agenttrace") / run_id
    local_repo_dir.mkdir(parents=True, exist_ok=True)

    # Write a file containing capability keywords (e.g. "agent loop" for capability "agent_loop")
    (local_repo_dir / "src/loop.py").parent.mkdir(parents=True, exist_ok=True)
    (local_repo_dir / "src/loop.py").write_text("class AgentExecutor:\n    def run_step(self): pass", encoding="utf-8")

    state = {
        "run_id": run_id,
        "local_repo_dir": str(local_repo_dir),
        "file_tree": [{"path": "src/loop.py"}],
        "selected_files": [{"path": "src/loop.py", "content": ""}],
        "readme": "agent loop",
    }

    try:
        res = harness_analyzer(state)
        # If it correctly read from disk, it should identify the capability
        assert res["harness_capabilities"]["agent_loop"]["present"] is True
    finally:
        shutil.rmtree(local_repo_dir, ignore_errors=True)


def test_cleanup_in_finalize_and_critical_handler():
    run_id = f"test-run-{uuid4()}"
    local_repo_dir = Path("tmp/agenttrace") / run_id
    local_repo_dir.mkdir(parents=True, exist_ok=True)

    state = {
        "run_id": run_id,
        "local_repo_dir": str(local_repo_dir),
        "synthesis": {"analysis_status": "completed"},
        "claims": [],
        "evidence_signals": [],
        "task_results": [],
    }

    assert local_repo_dir.exists()
    finalize_analysis(state)
    assert not local_repo_dir.exists()

    # Re-create and test critical_error_handler
    local_repo_dir.mkdir(parents=True, exist_ok=True)
    assert local_repo_dir.exists()
    critical_error_handler(state)
    assert not local_repo_dir.exists()
