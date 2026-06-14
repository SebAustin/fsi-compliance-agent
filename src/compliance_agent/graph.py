"""LangGraph StateGraph wiring for the compliance review pipeline.

triage -> rule_retrieval -> determination -> abstain -> {human_review | approval_gate | close}
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from langgraph.graph import END, START, StateGraph

from compliance_agent.nodes import (
    abstain_node,
    approval_gate_node,
    close_node,
    determination_node,
    rule_retrieval_node,
    triage_node,
)
from compliance_agent.state import CaseState

if TYPE_CHECKING:
    from langgraph.graph.state import CompiledStateGraph


def _route_after_abstain(state: CaseState) -> str:
    """Route to human review, the approval gate, or auto-close."""
    if state.get("abstained"):
        return "human_review"
    determination = state["determination"]
    if state.get("risk_tier") == "high" and determination.decision == "flag":
        return "approval_gate"
    return "close"


def build_graph() -> CompiledStateGraph[CaseState, Any, Any, Any]:
    """Construct and compile the compliance review graph."""
    graph: StateGraph[CaseState, Any, Any, Any] = StateGraph(CaseState)

    graph.add_node("triage", triage_node)
    graph.add_node("rule_retrieval", rule_retrieval_node)
    graph.add_node("determination", determination_node)
    graph.add_node("abstain", abstain_node)
    graph.add_node("approval_gate", approval_gate_node)
    graph.add_node("close", close_node)

    graph.add_edge(START, "triage")
    graph.add_edge("triage", "rule_retrieval")
    graph.add_edge("rule_retrieval", "determination")
    graph.add_edge("determination", "abstain")
    graph.add_conditional_edges(
        "abstain",
        _route_after_abstain,
        {"human_review": END, "approval_gate": "approval_gate", "close": "close"},
    )
    graph.add_edge("approval_gate", "close")
    graph.add_edge("close", END)

    return graph.compile()
