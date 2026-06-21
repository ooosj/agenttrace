from __future__ import annotations

from typing import Literal

from langgraph.graph import END, START, StateGraph

from agenttrace.agents.analysis.nodes.analysis_planner import analysis_planner
from agenttrace.agents.analysis.nodes.analysis_precheck import analysis_precheck
from agenttrace.agents.analysis.nodes.claim_analyzer import claim_analyzer
from agenttrace.agents.analysis.nodes.collect_inputs import collect_inputs
from agenttrace.agents.analysis.nodes.content_preprocessor import content_preprocessor
from agenttrace.agents.analysis.nodes.critical_error_handler import critical_error_handler
from agenttrace.agents.analysis.nodes.evidence_evaluator import evidence_evaluator
from agenttrace.agents.analysis.nodes.evidence_scout import evidence_scout
from agenttrace.agents.analysis.nodes.finalize_analysis import finalize_analysis
from agenttrace.agents.analysis.nodes.finalize_task import finalize_task
from agenttrace.agents.analysis.nodes.harness_analyzer import harness_analyzer
from agenttrace.agents.analysis.nodes.persist_analysis import persist_analysis
from agenttrace.agents.analysis.nodes.quality_gate import quality_gate
from agenttrace.agents.analysis.nodes.repository_synthesizer import repository_synthesizer
from agenttrace.agents.analysis.nodes.request_builder import request_builder
from agenttrace.agents.analysis.nodes.risk_and_followup import risk_and_followup
from agenttrace.agents.analysis.nodes.select_next_task import select_next_task
from agenttrace.agents.analysis.nodes.task_result_merge import task_result_merge
from agenttrace.agents.analysis.state import AnalysisState


def route_after_precheck(state: AnalysisState) -> Literal["claim_analyzer", "critical_error_handler"]:
    if state.get("precheck_result", {}).get("can_analyze"):
        return "claim_analyzer"
    return "critical_error_handler"


def route_after_select_task(state: AnalysisState) -> Literal["evidence_scout", "repository_synthesizer"]:
    if state.get("current_task_id"):
        return "evidence_scout"
    return "repository_synthesizer"


def route_after_quality(state: AnalysisState) -> Literal["critical_error_handler", "persist_analysis"]:
    if state.get("quality_gate_result", {}).get("critical_errors"):
        return "critical_error_handler"
    return "persist_analysis"


def build_graph():
    builder = StateGraph(AnalysisState)

    builder.add_node("collect_inputs", collect_inputs)
    builder.add_node("content_preprocessor", content_preprocessor)
    builder.add_node("analysis_precheck", analysis_precheck)
    builder.add_node("claim_analyzer", claim_analyzer)
    builder.add_node("analysis_planner", analysis_planner)
    builder.add_node("select_next_task", select_next_task)
    builder.add_node("evidence_scout", evidence_scout)
    builder.add_node("request_builder", request_builder)
    builder.add_node("evidence_evaluator", evidence_evaluator)
    builder.add_node("task_result_merge", task_result_merge)
    builder.add_node("finalize_task", finalize_task)
    builder.add_node("repository_synthesizer", repository_synthesizer)
    builder.add_node("harness_analyzer", harness_analyzer)
    builder.add_node("risk_and_followup", risk_and_followup)
    builder.add_node("finalize_analysis", finalize_analysis)
    builder.add_node("quality_gate", quality_gate)
    builder.add_node("critical_error_handler", critical_error_handler)
    builder.add_node("persist_analysis", persist_analysis)

    builder.add_edge(START, "collect_inputs")
    builder.add_edge("collect_inputs", "content_preprocessor")
    builder.add_edge("content_preprocessor", "analysis_precheck")
    builder.add_conditional_edges(
        "analysis_precheck",
        route_after_precheck,
        {
            "claim_analyzer": "claim_analyzer",
            "critical_error_handler": "critical_error_handler",
        },
    )
    builder.add_edge("claim_analyzer", "analysis_planner")
    builder.add_edge("analysis_planner", "select_next_task")
    builder.add_conditional_edges(
        "select_next_task",
        route_after_select_task,
        {
            "evidence_scout": "evidence_scout",
            "repository_synthesizer": "repository_synthesizer",
        },
    )
    builder.add_edge("evidence_scout", "request_builder")
    builder.add_edge("request_builder", "evidence_evaluator")
    builder.add_edge("evidence_evaluator", "task_result_merge")
    builder.add_edge("task_result_merge", "finalize_task")
    builder.add_edge("finalize_task", "select_next_task")
    builder.add_edge("repository_synthesizer", "harness_analyzer")
    builder.add_edge("harness_analyzer", "risk_and_followup")
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
