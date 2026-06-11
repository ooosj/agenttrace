from __future__ import annotations

from agenttrace.agents.analysis.state import AnalysisState


def collect_snapshot(state: AnalysisState) -> AnalysisState:
    """Normalize repository input into the graph state.

    MVP에서는 GitHub API를 직접 호출하지 않고, CLI가 넘겨준 JSON snapshot을 사용합니다.
    나중에 이 함수만 GitHub collector 또는 DB/cache 조회로 바꾸면 됩니다.
    """
    snapshot = state.get("repository_snapshot", {})

    metadata = snapshot.get("metadata", {}) or {}
    readme = snapshot.get("readme", "") or ""
    file_tree = snapshot.get("file_tree", []) or []
    selected_files = snapshot.get("selected_files", []) or []

    selected_file_tree_entries = [
        {"path": item.get("path"), "type": "file"}
        for item in selected_files
        if isinstance(item, dict) and item.get("path")
    ]
    existing_paths = {
        item.get("path")
        for item in file_tree
        if isinstance(item, dict) and item.get("path")
    }
    file_tree = [
        *file_tree,
        *[
            item
            for item in selected_file_tree_entries
            if item["path"] not in existing_paths
        ],
    ]

    if not readme.strip():
        return {
            "metadata": metadata,
            "readme": readme,
            "file_tree": file_tree,
            "selected_files": selected_files,
            "status": "INSUFFICIENT_EVIDENCE",
            "quality_warnings": ["README가 없어 기본 분석 근거가 부족합니다."],
        }

    if not file_tree:
        return {
            "metadata": metadata,
            "readme": readme,
            "file_tree": file_tree,
            "selected_files": selected_files,
            "status": "INSUFFICIENT_EVIDENCE",
            "quality_warnings": ["파일 구조가 없어 구현 근거를 확인할 수 없습니다."],
        }

    return {
        "repository_id": snapshot.get("repository_id", state.get("repository_id", "unknown")),
        "full_name": snapshot.get("full_name", state.get("full_name", "unknown/unknown")),
        "github_url": snapshot.get("github_url", state.get("github_url", "")),
        "metadata": metadata,
        "readme": readme,
        "file_tree": file_tree,
        "selected_files": selected_files,
        "status": "COLLECTED",
    }
