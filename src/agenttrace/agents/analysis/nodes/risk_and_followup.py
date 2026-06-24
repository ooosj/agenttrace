import time
from pathlib import PurePosixPath

from agenttrace.agents.analysis.criteria.agent_type_keywords import RISKY_README_WORDS
from agenttrace.agents.analysis.state import AnalysisState
from agenttrace.logging_config import get_logger

logger = get_logger(__name__)


CONFIG_FILENAMES = {
    "package.json",
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "requirements.txt",
    "plugin.json",
    "manifest.json",
    "Dockerfile",
}


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _structure_targets(paths: list[str]) -> list[str]:
    targets: list[str] = []
    for path in paths:
        parts = PurePosixPath(path).parts
        if not parts:
            continue
        name = parts[-1]
        if name in CONFIG_FILENAMES or name.endswith((".toml", ".json", ".yaml", ".yml")):
            targets.append(path)
        else:
            targets.append(parts[0])
    return _dedupe(targets)


def _tryable_targets(state: AnalysisState, target_paths: list[str]) -> list[str]:
    file_tree = state.get("file_tree", [])
    file_paths = [item.get("path", "") for item in file_tree if isinstance(item, dict)]
    candidates = [*file_paths, *target_paths]
    targets: list[str] = []

    for path in candidates:
        lower_path = path.lower()
        name = PurePosixPath(path).name
        if (
            "examples" in lower_path
            or "scripts" in lower_path
            or "install" in lower_path
            or name == "package.json"
        ):
            targets.append(path)

    return _dedupe(targets)


def _has_tryable_example(state: AnalysisState, target_paths: list[str]) -> bool:
    file_tree = state.get("file_tree", [])
    file_paths = [item.get("path", "") for item in file_tree if isinstance(item, dict)]
    searchable = "\n".join([state.get("readme", ""), *target_paths, *file_paths]).lower()
    return any(marker in searchable for marker in ("examples", "scripts", "install", "package.json"))


def risk_and_followup_planner(state: AnalysisState) -> AnalysisState:
    metadata = state.get("metadata", {})
    readme = state.get("readme", "")
    area_findings = state.get("area_findings", [])
    evidence_refs = state.get("evidence_refs", [])

    risks: list[dict] = [{
        "risk_type": "ANALYSIS_UNCERTAIN",
        "severity": "low",
        "summary": "정적 분석만으로 판단했으므로 실행/원문 확인 전에는 불확실성이 남아 있습니다.",
    }]

    if metadata.get("archived") is True:
        risks.append({
            "risk_type": "ARCHIVED_REPOSITORY",
            "severity": "high",
            "summary": "GitHub repository가 archived 상태입니다.",
        })

    confirmed_areas = [af for af in area_findings if af.get("status") == "confirmed"]
    if area_findings and not evidence_refs:
        risks.append({
            "risk_type": "NO_EVIDENCE_REFS",
            "severity": "high",
            "summary": "영역 분석이 수행되었으나 구현 근거 파일을 찾지 못했습니다.",
        })

    if area_findings and not confirmed_areas:
        risks.append({
            "risk_type": "NO_CONFIRMED_AREAS",
            "severity": "medium",
            "summary": "확인된(confirmed) 영역이 없어 분석 신뢰도가 낮습니다.",
        })

    lower_readme = readme.lower()
    risky_words = [word for word in RISKY_README_WORDS if word in lower_readme]
    if risky_words:
        risks.append({
            "risk_type": "OVERCONFIDENT_README_LANGUAGE",
            "severity": "medium",
            "summary": f"README에 과장 가능성이 있는 표현이 포함되어 있습니다: {', '.join(risky_words)}",
        })

    stars = int(metadata.get("stars", 0) or 0)
    if stars < 5:
        risks.append({
            "risk_type": "LOW_ADOPTION_SIGNAL",
            "severity": "low",
            "summary": "stars가 낮아 커뮤니티 검증 신호가 약합니다.",
        })

    target_paths = [ref.get("path") for ref in evidence_refs if ref.get("path")]
    followup_actions: list[dict] = []

    if target_paths:
        followup_actions.append({
            "action": "READ_NOW",
            "reason": "README와 구현 근거가 함께 있으므로 우선 원문을 확인합니다.",
            "target_paths": ["README.md"],
        })

    structure_targets = _structure_targets(target_paths)
    if structure_targets:
        followup_actions.append({
            "action": "INSPECT_STRUCTURE",
            "reason": "상위 evidence 디렉터리와 설정 파일을 확인해 repo 구조를 검증합니다.",
            "target_paths": structure_targets[:8],
        })

    if _has_tryable_example(state, target_paths):
        tryable_targets = _tryable_targets(state, target_paths)
        followup_actions.append({
            "action": "TRY_EXAMPLE",
            "reason": "예제, 스크립트, 설치 안내, package.json 중 하나가 보여 직접 실행 가능성을 확인합니다.",
            "target_paths": tryable_targets[:8] or structure_targets[:8] or target_paths[:8] or ["README.md"],
        })

    if any(risk["severity"] == "high" for risk in risks) or not target_paths:
        followup_actions.append({
            "action": "READ_WITH_CAUTION",
            "reason": "높은 위험 신호가 있거나 evidence가 부족해 자동 추천/노출 전에 원본 repo 검토가 필요합니다.",
            "target_paths": target_paths[:8] or ["README.md"],
        })

    return {
        "risk_signals": risks,
        "followup_actions": followup_actions,
        "followup_guide": [
            {"step": 1, "label": "README 확인", "target": "README.md"},
            {"step": 2, "label": "구현 근거 경로 확인", "target": "evidence_refs[].path"},
            {"step": 3, "label": "위험 신호 확인", "target": "risk_signals"},
        ],
        "follow_up_guide": {
            "ko": "README, evidence path, risk signal 순서로 확인하세요.",
            "en": "Review README, evidence paths, and risk signals in order.",
        },
    }


def risk_and_followup(state: AnalysisState) -> AnalysisState:
    _t = time.perf_counter()
    run_id = state.get("run_id", "-")
    log = logger.bind(node="risk_and_followup", run_id=run_id)
    log.info("시작")
    res = risk_and_followup_planner(state)
    log.info(
        "완료",
        risks=len(res.get("risk_signals", [])),
        followup_actions=len(res.get("followup_actions", [])),
        duration_ms=int((time.perf_counter() - _t) * 1000),
    )
    return res