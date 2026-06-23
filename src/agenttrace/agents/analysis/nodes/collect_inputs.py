from pathlib import Path
import time
from uuid import UUID

from agenttrace.agents.analysis.input_providers import AnalysisInputAssembler
from agenttrace.agents.analysis.schemas.input import AnalysisInputRequest
from agenttrace.agents.analysis.state import AnalysisState
from agenttrace.logging_config import get_logger

logger = get_logger(__name__)



def is_safe_path(base_dir: Path, target_path: str | Path) -> bool:
    try:
        resolved_base = base_dir.resolve()
        resolved_target = (base_dir / target_path).resolve()
        return resolved_target.is_relative_to(resolved_base)
    except Exception:
        return False


def collect_inputs(state: AnalysisState) -> AnalysisState:
    _t = time.perf_counter()
    run_id = state.get("run_id", "-")
    log = logger.bind(node="collect_inputs", run_id=run_id)
    log.info("시작")

    if "analysis_request" not in state:
        snapshot = state.get("repository_snapshot", {}) or {}
        file_tree_items = snapshot.get("file_tree", []) or state.get("file_tree", [])
        selected_files = snapshot.get("selected_files", []) or state.get("selected_files", [])
        run_id = state.get("run_id", "00000000-0000-0000-0000-000000000000")
        try:
            UUID(str(run_id))
            analysis_id = run_id
        except ValueError:
            analysis_id = "00000000-0000-0000-0000-000000000000"
        request_payload = {
            "analysis_id": analysis_id,
            "repository": {
                "repository_id": snapshot.get("repository_id") or state.get("repository_id"),
                "full_name": snapshot.get("full_name") or state.get("full_name", "unknown/unknown"),
                "github_url": snapshot.get("github_url") or state.get("github_url"),
                "description": (snapshot.get("metadata") or {}).get("description"),
                "primary_language": (snapshot.get("metadata") or {}).get("primary_language"),
                "topics": (snapshot.get("metadata") or {}).get("topics", []),
            },
            "snapshot": {
                "snapshot_id": snapshot.get("snapshot_id"),
                "commit_sha": snapshot.get("commit_sha") or state.get("commit_sha"),
            },
            "readme_text": snapshot.get("readme") or state.get("readme", ""),
            "file_tree": [
                item.get("path") if isinstance(item, dict) else str(item)
                for item in file_tree_items
                if (item.get("path") if isinstance(item, dict) else item)
            ],
            "source_files": selected_files,
            "external_ingest": snapshot.get("external_ingest", {"enabled": False, "provider": "gitingest"}),
        }
    else:
        request_payload = state["analysis_request"]

    request = AnalysisInputRequest.model_validate(request_payload)
    assembled = AnalysisInputAssembler().assemble(request)

    run_id = state.get("run_id") or str(request.analysis_id)
    local_repo_dir = Path("tmp/agenttrace") / run_id
    local_repo_dir.mkdir(parents=True, exist_ok=True)

    # Save files to local disk
    for source in assembled.source_files:
        if not is_safe_path(local_repo_dir, source.path):
            raise ValueError(f"Path traversal detected: {source.path}")
        dest_file = local_repo_dir / source.path
        dest_file.parent.mkdir(parents=True, exist_ok=True)
        dest_file.write_text(source.content, encoding="utf-8")

    # Strip content from state files to keep state light
    state_source_files = []
    for source in assembled.source_files:
        s_dict = source.model_dump()
        s_dict["content"] = ""
        state_source_files.append(s_dict)

    log.info(
        "완료",
        source_files=len(assembled.source_files),
        mode=assembled.analysis_mode,
        provider=assembled.input_manifest.get("source_provider", "none"),
        missing=assembled.missing_inputs,
        duration_ms=int((time.perf_counter() - _t) * 1000),
    )
    return {

        "run_id": run_id,
        "local_repo_dir": str(local_repo_dir),
        "full_name": request.repository.full_name,
        "github_url": request.repository.github_url or "",
        "metadata": request.repository.model_dump(),
        "repository_snapshot": request.snapshot.model_dump() if request.snapshot else {},
        "readme": request.readme_text or "",
        "file_tree": [{"path": path} for path in request.file_tree],
        "source_files": state_source_files,
        "selected_files": state_source_files,
        "missing_inputs": assembled.missing_inputs,
        "input_manifest": assembled.input_manifest,
        "analysis_mode": assembled.analysis_mode,
    }
