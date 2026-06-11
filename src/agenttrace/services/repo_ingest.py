from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from agenttrace.agents.summary import RepositorySummaryInput
from agenttrace.config import get_settings
from agenttrace.shared.errors import RepoIngestError

MAX_REPO_INGEST_README_CHARS = 60000


def fetch_repo_digest(full_name: str) -> dict[str, Any]:
    settings = get_settings()
    base_url = settings.repo_ingest_base_url.rstrip("/")
    owner, repo = full_name.split("/", 1)
    url = f"{base_url}/api/{quote(owner)}/{quote(repo)}"
    request = Request(url, headers={"Accept": "application/json"})
    if settings.repo_ingest_host_header:
        request.add_header("Host", settings.repo_ingest_host_header)

    try:
        with urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        raise RepoIngestError(f"Repo ingest API returned HTTP {exc.code}.") from exc
    except URLError as exc:
        raise RepoIngestError(f"Repo ingest API request failed: {exc.reason}") from exc
    except TimeoutError as exc:
        raise RepoIngestError("Repo ingest API request timed out.") from exc

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise RepoIngestError("Repo ingest API returned invalid JSON.") from exc

    if not isinstance(payload, dict):
        raise RepoIngestError("Repo ingest API returned an unsupported payload.")

    return payload


def repo_digest_to_summary_input(
    payload: dict[str, Any],
    fallback_full_name: str,
) -> RepositorySummaryInput:
    repo = _first_mapping(payload, "repository", "repo", "metadata") or payload
    full_name = (
        _string(repo.get("full_name"))
        or _string(payload.get("repo_url"))
        or _string(payload.get("short_repo_url"))
        or fallback_full_name
    )
    github_url = (
        _string(repo.get("html_url"))
        or _string(repo.get("github_url"))
        or _string(repo.get("url"))
        or f"https://github.com/{full_name}"
    )

    return RepositorySummaryInput(
        repository_id=_string(repo.get("id")) or full_name,
        full_name=full_name,
        github_url=github_url,
        description=(
            _string(repo.get("description"))
            or _string(payload.get("description"))
            or _string(payload.get("summary"))
        ),
        topics=_string_list(repo.get("topics") or payload.get("topics")),
        primary_language=(
            _string(repo.get("primary_language"))
            or _string(repo.get("language"))
            or _string(payload.get("primary_language"))
            or _string(payload.get("language"))
        ),
        readme=_truncate_readme(
            _string(payload.get("readme"))
            or _string(payload.get("readme_content"))
            or _string(payload.get("README"))
            or _string(payload.get("content"))
        ),
        file_tree=_file_tree(payload.get("file_tree") or payload.get("files") or payload.get("tree")),
    )


def _first_mapping(payload: dict[str, Any], *keys: str) -> dict[str, Any] | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, dict):
            return value
    return None


def _string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [text for item in value if (text := _string(item))]


def _file_tree(value: Any) -> list[str]:
    if isinstance(value, str):
        return _tree_lines(value)

    if not isinstance(value, list):
        return []

    paths: list[str] = []
    for item in value:
        if isinstance(item, str):
            path = _string(item)
        elif isinstance(item, dict):
            path = _string(item.get("path")) or _string(item.get("name"))
        else:
            path = None

        if path:
            paths.append(path)

    return paths


def _tree_lines(value: str) -> list[str]:
    paths: list[str] = []
    for line in value.splitlines():
        cleaned = (
            line.strip()
            .replace("├──", "")
            .replace("└──", "")
            .replace("│", "")
            .strip()
        )
        if cleaned and cleaned != "Directory structure:":
            paths.append(cleaned)
    return paths


def _truncate_readme(value: str | None) -> str | None:
    if value is None or len(value) <= MAX_REPO_INGEST_README_CHARS:
        return value
    return (
        value[:MAX_REPO_INGEST_README_CHARS]
        + "\n\n[Truncated by AgentTrace before summary generation.]"
    )
