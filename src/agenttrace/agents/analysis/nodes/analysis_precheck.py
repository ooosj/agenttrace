from __future__ import annotations

from agenttrace.agents.analysis.state import AnalysisState


def analysis_precheck(state: AnalysisState) -> AnalysisState:
    has_readme = bool((state.get("readme") or "").strip())
    has_file_tree = bool(state.get("file_tree"))
    has_repo_map = bool(state.get("repo_map_render") or state.get("definition_ranks"))
    missing_inputs = list(state.get("missing_inputs", []))
    can_analyze = has_readme or has_file_tree
    analysis_mode = "normal" if has_repo_map else "limited"
    limitations = {
        "missing_inputs": missing_inputs,
        "truncated_inputs": [],
        "notes": [],
    }
    if analysis_mode == "limited":
        limitations["notes"].append("README and file tree based limited analysis.")

    return {
        "precheck_result": {
            "can_analyze": can_analyze,
            "has_readme": has_readme,
            "has_file_tree": has_file_tree,
            "has_repo_map": has_repo_map,
        },
        "analysis_mode": analysis_mode,
        "analysis_limitations": limitations,
        "status": "COLLECTED" if can_analyze else "FAILED",
        "error_message": None if can_analyze else "No README or file tree available.",
    }