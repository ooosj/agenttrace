from __future__ import annotations

from typing import Literal

from langgraph.graph import END, START, StateGraph

from agenttrace.agents.analysis.state import AnalysisState
from agenttrace.agents.analysis.nodes.collect_snapshot import collect_snapshot
from agenttrace.agents.analysis.nodes.analyzer import analyzer
from agenttrace.agents.analysis.nodes.evidence_scout import evidence_scout
from agenttrace.agents.analysis.nodes.harness_analyzer import harness_analyzer
from agenttrace.agents.analysis.nodes.risk_and_followup import risk_and_followup_planner
from agenttrace.agents.analysis.nodes.quality_gate import quality_gate
from agenttrace.agents.analysis.nodes.persist_analysis import persist_analysis


def route_after_collect(state: AnalysisState) -> Literal["analyzer", "persist_analysis"]:
    if state.get("status") == "INSUFFICIENT_EVIDENCE":
        return "persist_analysis"
    return "analyzer"


def route_after_analyzer(state: AnalysisState) -> Literal["evidence_scout", "persist_analysis"]:
    if state.get("status") == "OUT_OF_SCOPE" and state.get("selected_files"):
        return "evidence_scout"
    if state.get("status") in {"OUT_OF_SCOPE", "INSUFFICIENT_EVIDENCE"}:
        return "persist_analysis"
    return "evidence_scout"


def build_graph():
    builder = StateGraph(AnalysisState)

    builder.add_node("collect_snapshot", collect_snapshot)
    builder.add_node("analyzer", analyzer)
    builder.add_node("evidence_scout", evidence_scout)
    builder.add_node("harness_analyzer", harness_analyzer)
    builder.add_node("risk_and_followup_planner", risk_and_followup_planner)
    builder.add_node("quality_gate", quality_gate)
    builder.add_node("persist_analysis", persist_analysis)

    builder.add_edge(START, "collect_snapshot")

    builder.add_conditional_edges(
        "collect_snapshot",
        route_after_collect,
        {
            "analyzer": "analyzer",
            "persist_analysis": "persist_analysis",
        },
    )

    builder.add_conditional_edges(
        "analyzer",
        route_after_analyzer,
        {
            "evidence_scout": "evidence_scout",
            "persist_analysis": "persist_analysis",
        },
    )

    builder.add_edge("evidence_scout", "harness_analyzer")
    builder.add_edge("harness_analyzer", "risk_and_followup_planner")
    builder.add_edge("risk_and_followup_planner", "quality_gate")
    builder.add_edge("quality_gate", "persist_analysis")
    builder.add_edge("persist_analysis", END)

    return builder.compile()


graph = build_graph()
