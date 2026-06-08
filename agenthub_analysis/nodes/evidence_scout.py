from __future__ import annotations

import re

from agenthub_analysis.criteria.agent_type_keywords import EVIDENCE_PATH_HINTS
from agenthub_analysis.state import AnalysisState


CLAIM_KEYWORD_TOKENS = {
    "skill", "skills", "plugin", "plugins", "hook", "hooks",
    "script", "scripts", "test", "tests", "workflow", "workflows",
    "plan", "debug", "review", "verify", "install",
}


def _path_signal_type(path: str, file_type: str | None = None) -> str:
    lower_path = path.lower()
    name = lower_path.rsplit("/", 1)[-1]

    if file_type == "directory":
        return "DIRECTORY"
    if name in {"plugin.json", "mcp.json"} or "plugin" in lower_path:
        return "CONFIG"
    if "test" in lower_path:
        return "TEST"
    if name == "readme.md" or lower_path.endswith(".md"):
        return "DOC"
    if name in {"package.json", "pyproject.toml", "cargo.toml"}:
        return "DEPENDENCY"
    return "FILE_PATH"


def _claim_keywords(claim_text: str) -> set[str]:
    words = set(re.findall(r"[a-z0-9_-]+", claim_text.lower()))
    return {
        token.rstrip("s")
        for token in CLAIM_KEYWORD_TOKENS
        if token in words
    }


def evidence_scout(state: AnalysisState) -> AnalysisState:
    """Find static implementation evidence from file paths.

    MVP는 file tree만 사용합니다. 이후 selected file content까지 읽게 확장하면 됩니다.
    """
    agent_type = state.get("agent_type", "UNKNOWN")
    file_tree = state.get("file_tree", [])
    claims = state.get("claims", [])
    hints = EVIDENCE_PATH_HINTS.get(agent_type, [])

    evidence_signals: list[dict] = []
    seen: set[tuple[str | None, str]] = set()

    for claim in claims or [{"id": None, "claim_text": ""}]:
        claim_id = claim.get("id")
        claim_keywords = _claim_keywords(claim.get("claim_text", ""))
        claim_file_tree = file_tree
        if claim_keywords:
            claim_file_tree = sorted(
                file_tree,
                key=lambda file_info: (
                    _path_signal_type(file_info.get("path", ""), file_info.get("type")) != "CONFIG",
                    not any(keyword in file_info.get("path", "").lower() for keyword in claim_keywords),
                ),
            )

        for file_info in claim_file_tree:
            path = file_info.get("path", "")
            lower_path = path.lower()
            matched_hints = [hint for hint in hints if hint.lower() in lower_path]
            matched_keywords = sorted(keyword for keyword in claim_keywords if keyword in lower_path)
            if not matched_hints and not matched_keywords:
                continue

            key = (claim_id, path)
            if key in seen:
                continue
            seen.add(key)

            matched_signals = matched_hints + matched_keywords
            evidence_signals.append({
                "claim_id": claim_id,
                "signal_type": _path_signal_type(path, file_info.get("type")),
                "path": path,
                "summary": f"claim과 연결된 파일 경로 근거: {', '.join(matched_signals)}",
                "confidence": min(0.5 + 0.1 * len(set(matched_signals)), 0.9),
            })
            if len(evidence_signals) >= 16:
                break

        if len(evidence_signals) >= 16:
            break

    if not evidence_signals:
        return {
            "status": "INSUFFICIENT_EVIDENCE",
            "evidence_signals": [],
            "quality_warnings": ["README claim을 뒷받침할 파일 경로 근거가 부족합니다."],
        }

    return {
        "status": "COLLECTED",
        "evidence_signals": evidence_signals,
    }
