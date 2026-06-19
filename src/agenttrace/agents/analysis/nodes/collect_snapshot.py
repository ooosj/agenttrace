from __future__ import annotations

import urllib.parse
from urllib.parse import urlparse

from agenttrace.agents.analysis.state import AnalysisState
from agenttrace.config import get_settings


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

    # Extract repository metadata upfront
    repository_id = snapshot.get("repository_id", state.get("repository_id", "unknown"))
    full_name = snapshot.get("full_name", state.get("full_name", "unknown/unknown"))
    github_url = snapshot.get("github_url", state.get("github_url", ""))

    # Extract commit_sha
    commit_sha = state.get("commit_sha") or snapshot.get("commit_sha")
    if not commit_sha and isinstance(metadata, dict):
        commit_sha = metadata.get("commit_sha")

    # Construct gitingest API URL and warnings
    ingest_api_url = None
    warnings = []
    if commit_sha:
        owner, repo = None, None
        if full_name and full_name != "unknown/unknown":
            parts = [p for p in full_name.split("/") if p]
            if len(parts) >= 2:
                owner = parts[0]
                repo = "/".join(parts[1:])
        elif github_url:
            try:
                parsed = urlparse(github_url)
                if parsed.netloc.lower() == "github.com" or "github.com" in parsed.netloc.lower():
                    path_parts = [p for p in parsed.path.strip("/").split("/") if p]
                    if len(path_parts) >= 2:
                        owner = path_parts[0]
                        repo = path_parts[1].removesuffix(".git")
            except Exception:
                pass

        if not owner or not repo:
            owner, repo = "unknown", "unknown"

        settings = get_settings()
        base_url = settings.repo_ingest_base_url.rstrip("/")
        quoted_owner = urllib.parse.quote(owner, safe="")
        quoted_repo = urllib.parse.quote(repo, safe="")
        quoted_commit = urllib.parse.quote(commit_sha, safe="")
        ingest_api_url = f"{base_url}/api/{quoted_owner}/{quoted_repo}/commit/{quoted_commit}"

        warnings.append("스냅샷 생성 시점의 commit_sha와 실시간 분석 코드가 일치하지 않을 수 있습니다.")

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
        ret = {
            "repository_id": repository_id,
            "full_name": full_name,
            "github_url": github_url,
            "metadata": metadata,
            "readme": readme,
            "file_tree": file_tree,
            "selected_files": selected_files,
            "status": "INSUFFICIENT_EVIDENCE",
            "quality_warnings": ["README가 없어 기본 분석 근거가 부족합니다."] + warnings,
        }
        if commit_sha:
            ret["commit_sha"] = commit_sha
        if ingest_api_url:
            ret["ingest_api_url"] = ingest_api_url
        return ret

    if not file_tree:
        ret = {
            "repository_id": repository_id,
            "full_name": full_name,
            "github_url": github_url,
            "metadata": metadata,
            "readme": readme,
            "file_tree": file_tree,
            "selected_files": selected_files,
            "status": "INSUFFICIENT_EVIDENCE",
            "quality_warnings": ["파일 구조가 없어 구현 근거를 확인할 수 없습니다."] + warnings,
        }
        if commit_sha:
            ret["commit_sha"] = commit_sha
        if ingest_api_url:
            ret["ingest_api_url"] = ingest_api_url
        return ret

    ret = {
        "repository_id": repository_id,
        "full_name": full_name,
        "github_url": github_url,
        "metadata": metadata,
        "readme": readme,
        "file_tree": file_tree,
        "selected_files": selected_files,
        "status": "COLLECTED",
    }
    if commit_sha:
        ret["commit_sha"] = commit_sha
    if ingest_api_url:
        ret["ingest_api_url"] = ingest_api_url
    if warnings:
        ret["quality_warnings"] = warnings
    return ret
