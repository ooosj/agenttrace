from __future__ import annotations

from collections.abc import Callable

import httpx

from agenttrace.agents.analysis.gitingest import (
    build_gitingest_url,
    fetch_gitingest_text,
    parse_gitingest_output,
)
from agenttrace.agents.analysis.schemas.input import (
    AnalysisInputRequest,
    AssembledAnalysisInput,
    SourceFile,
)


class AnalysisInputProviderError(RuntimeError):
    pass


class ProvidedInputProvider:
    def load(self, request: AnalysisInputRequest) -> list[SourceFile]:
        return request.source_files


class GitingestInputProvider:
    def __init__(self, fetch_text: Callable[[str], str] = fetch_gitingest_text):
        self._fetch_text = fetch_text

    def load(self, request: AnalysisInputRequest) -> list[SourceFile]:
        if not request.repository.github_url:
            return []
        from agenttrace.config import get_settings
        url = build_gitingest_url(
            request.repository.github_url,
            base_url=get_settings().repo_ingest_base_url,
        )
        try:
            return parse_gitingest_output(self._fetch_text(url))
        except (httpx.HTTPError, RuntimeError, ValueError, TypeError) as exc:
            raise AnalysisInputProviderError(str(exc)) from exc


class AnalysisInputAssembler:
    def __init__(
        self,
        provided: ProvidedInputProvider | None = None,
        gitingest: GitingestInputProvider | None = None,
    ):
        self.provided = provided or ProvidedInputProvider()
        self.gitingest = gitingest or GitingestInputProvider()

    def assemble(self, request: AnalysisInputRequest) -> AssembledAnalysisInput:
        missing_inputs: list[str] = []
        input_manifest = {
            "repository_full_name": request.repository.full_name,
            "source_file_count": 0,
            "file_tree_count": len(request.file_tree),
            "has_readme": bool(request.readme_text),
            "external_ingest_enabled": request.external_ingest.enabled,
        }
        source_files = self.provided.load(request)

        # 1순위: GitHub API 직접 수집
        if not source_files and request.repository.github_url:
            from agenttrace.config import get_settings
            from agenttrace.agents.analysis.github_provider import GitHubInputProvider
            settings = get_settings()
            commit_sha = (
                request.snapshot.commit_sha
                if request.snapshot and request.snapshot.commit_sha
                else "HEAD"
            )
            try:
                # GITHUB_TOKEN이 없더라도 public repository 수집 시도를 허용
                token = settings.github_token if settings.github_token else None
                provider = GitHubInputProvider(token=token)
                source_files = provider.load(
                    github_url=request.repository.github_url,
                    commit_sha=commit_sha,
                )
                input_manifest["source_provider"] = "github_api"
            except Exception as exc:
                missing_inputs.append("github_source_files")
                input_manifest["github_error"] = str(exc)

        # 2순위: gitingest fallback
        if not source_files and request.external_ingest.enabled:
            try:
                source_files = self.gitingest.load(request)
                input_manifest["source_provider"] = "gitingest"
            except AnalysisInputProviderError as exc:
                source_files = []
                missing_inputs.append("gitingest_file_content")
                input_manifest["external_ingest_error"] = str(exc)

        if not source_files:
            missing_inputs.append("source_files")

        input_manifest["source_file_count"] = len(source_files)

        return AssembledAnalysisInput(
            request=request,
            source_files=source_files,
            analysis_mode="normal" if source_files else "limited",
            missing_inputs=sorted(set(missing_inputs)),
            input_manifest=input_manifest,
        )

