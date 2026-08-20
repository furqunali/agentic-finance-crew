"""LangGraph engine — the same workflow modeled as an explicit state graph.

This is a third interchangeable implementation of the `Orchestrator` contract.
Where CrewAI models the workflow as a *crew of role-playing agents*, LangGraph
models it as a *stateful directed graph*:

    START -> intake -> analyze -> approve -> END

Each node is a pure function over a shared `GraphState`, calling the same
deterministic tools + guardrail as the other engines. It needs **no LLM and no
API key**, so it runs and is tested in CI exactly like the local engine — while
still demonstrating real LangGraph graph construction, typed state and node
transitions.

`langgraph` is imported lazily, so it stays an optional dependency.
"""
from __future__ import annotations

from typing import Any, TypedDict

from .config import Settings
from .decision import decide
from .models import ApprovalResult, ExpenseRequest, IntakeResult, PolicyAnalysis
from .tools import analyze, run_intake


class GraphState(TypedDict, total=False):
    """State threaded through the graph nodes."""

    request: ExpenseRequest
    history: list[ExpenseRequest]
    intake: IntakeResult
    analysis: PolicyAnalysis
    result: ApprovalResult


class LangGraphOrchestrator:
    """Runs the Intake -> Analyze -> Approve workflow as a compiled LangGraph."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()
        self._app = self._build_graph()

    def _build_graph(self):
        from langgraph.graph import END, START, StateGraph

        policy = self.settings.policy

        def intake_node(state: GraphState) -> dict[str, Any]:
            return {"intake": run_intake(state["request"])}

        def analyze_node(state: GraphState) -> dict[str, Any]:
            cat = state["intake"].normalized_category
            return {"analysis": analyze(state["request"], cat, policy, state.get("history"))}

        def approve_node(state: GraphState) -> dict[str, Any]:
            result = decide(
                state["request"], state["intake"], state["analysis"], policy, engine="langgraph"
            )
            return {"result": result}

        graph = StateGraph(GraphState)
        graph.add_node("intake", intake_node)
        graph.add_node("analyze", analyze_node)
        graph.add_node("approve", approve_node)
        graph.add_edge(START, "intake")
        graph.add_edge("intake", "analyze")
        graph.add_edge("analyze", "approve")
        graph.add_edge("approve", END)
        return graph.compile()

    def process(self, request: ExpenseRequest,
                history: list[ExpenseRequest] | None = None) -> ApprovalResult:
        final = self._app.invoke({"request": request, "history": history or []})
        return final["result"]
