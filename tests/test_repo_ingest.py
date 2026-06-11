from __future__ import annotations

from agenttrace.services.repo_ingest import (
    MAX_REPO_INGEST_README_CHARS,
    repo_digest_to_summary_input,
)


def test_repo_digest_to_summary_input_truncates_large_content_payload():
    payload = {
        "repo_url": "obra/superpowers",
        "content": "x" * (MAX_REPO_INGEST_README_CHARS + 1),
        "tree": "Directory structure:\n└── README.md",
    }

    summary_input = repo_digest_to_summary_input(
        payload,
        fallback_full_name="obra/superpowers",
    )

    assert summary_input.full_name == "obra/superpowers"
    assert summary_input.readme is not None
    assert len(summary_input.readme) < MAX_REPO_INGEST_README_CHARS + 100
    assert "Truncated by AgentTrace" in summary_input.readme
    assert summary_input.file_tree == ["README.md"]
