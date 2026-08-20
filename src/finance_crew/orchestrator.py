"""Orchestrator strategy interface + factory.

Three interchangeable engines implement the same `process()` contract:

* LocalOrchestrator     — deterministic, zero-dependency, no API key. Powers the
  demo, the tests and CI.
* LangGraphOrchestrator — the same workflow as a stateful LangGraph state graph
  (no LLM required, so also fully testable).
* CrewAIOrchestrator    — the real multi-agent CrewAI crew (opt-in, needs a key).

Selecting between them is a runtime decision, never a code change — the
classic Strategy pattern. Callers depend only on this module.
"""
from __future__ import annotations

from typing import Protocol

from .config import Settings
from .models import ApprovalResult, ExpenseRequest


class Orchestrator(Protocol):
    """Anything that can turn a request (+ history) into an ApprovalResult."""

    def process(self, request: ExpenseRequest,
                history: list[ExpenseRequest] | None = None) -> ApprovalResult: ...


def build_orchestrator(settings: Settings | None = None) -> Orchestrator:
    """Pick an engine from settings.engine (all heavy deps imported lazily).

    * "langgraph"      -> LangGraphOrchestrator (no key needed)
    * "crewai"         -> CrewAIOrchestrator    (needs a key)
    * "local"          -> LocalOrchestrator
    * "auto" (default) -> the real crew if opted-in and keyed, else local
    """
    settings = settings or Settings.from_env()
    engine = settings.engine

    if engine == "langgraph":
        from .langgraph_orchestrator import LangGraphOrchestrator

        return LangGraphOrchestrator(settings)

    if engine == "crewai" or (engine == "auto" and settings.can_run_crewai):
        # Imported lazily so the package (and CI) never require crewai/an LLM.
        from .crew import CrewAIOrchestrator

        return CrewAIOrchestrator(settings)

    from .local_orchestrator import LocalOrchestrator

    return LocalOrchestrator(settings)
