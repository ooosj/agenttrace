from __future__ import annotations

from typing import Literal

from langgraph.graph import END, START, StateGraph

from agenttrace.agents.analysis.nodes.analysis_precheck import analysis_precheck
from agenttrace.agents.analysis.nodes.build_file_catalog import build_file_catalog
from agenttrace.agents.analysis.nodes.build_repo_map import build_repo_map_node
from agenttrace.agents.analysis.nodes.area_explorer import area_explorer
from agenttrace.agents.analysis.nodes.collect_inputs import collect_inputs
from agenttrace.agents.analysis.nodes.critical_error_handler import critical_error_handler
from agenttrace.agents.analysis.nodes.extract_mentions import extract_mentions
from agenttrace.agents.analysis.nodes.finalize_analysis import finalize_analysis
from agenttrace.agents.analysis.nodes.persist_analysis import persist_analysis
from agenttrace.agents.analysis.nodes.quality_gate import quality_gate
from agenttrace.agents.analysis.nodes.risk_and_followup import risk_and_followup
from agenttrace.agents.analysis.state import AnalysisState


def route_after_precheck(state: AnalysisState) -> Literal["area_explorer", "critical_error_handler"]:
    if state.get("precheck_result", {}).get("can_analyze"):
        return "area_explorer"
    return "critical_error_handler"


def route_after_quality(state: AnalysisState) -> Literal["critical_error_handler", "persist_analysis"]:
    if state.get("quality_gate_result", {}).get("critical_errors"):
        return "critical_error_handler"
    return "persist_analysis"


def build_graph(*, content_index_store=None, embedding_service=None, embedding_store=None):
    builder = StateGraph(AnalysisState)

    builder.add_node("collect_inputs", collect_inputs)
    builder.add_node("extract_mentions", extract_mentions)
    builder.add_node("build_file_catalog", build_file_catalog)
    builder.add_node("build_repo_map", build_repo_map_node)
    builder.add_node("analysis_precheck", analysis_precheck)
    builder.add_node("area_explorer", area_explorer)
    builder.add_node("risk_and_followup", risk_and_followup)
    builder.add_node("finalize_analysis", finalize_analysis)
    builder.add_node("quality_gate", quality_gate)
    builder.add_node("critical_error_handler", critical_error_handler)
    builder.add_node("persist_analysis", persist_analysis)

    builder.add_edge(START, "collect_inputs")
    builder.add_edge("collect_inputs", "extract_mentions")
    builder.add_edge("extract_mentions", "build_file_catalog")
    builder.add_edge("build_file_catalog", "build_repo_map")
    builder.add_edge("build_repo_map", "analysis_precheck")
    builder.add_conditional_edges(
        "analysis_precheck",
        route_after_precheck,
        {
            "area_explorer": "area_explorer",
            "critical_error_handler": "critical_error_handler",
        },
    )
    builder.add_edge("area_explorer", "risk_and_followup")
    builder.add_edge("risk_and_followup", "finalize_analysis")
    builder.add_edge("finalize_analysis", "quality_gate")
    builder.add_conditional_edges(
        "quality_gate",
        route_after_quality,
        {
            "critical_error_handler": "critical_error_handler",
            "persist_analysis": "persist_analysis",
        },
    )
    builder.add_edge("critical_error_handler", END)
    builder.add_edge("persist_analysis", END)

    return builder.compile()


graph = build_graph()