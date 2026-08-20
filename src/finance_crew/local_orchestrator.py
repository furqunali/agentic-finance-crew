"""Deterministic, dependency-free implementation of the crew workflow.

Runs the same three logical stages as the CrewAI crew — Intake → Analyst →
Approver — using the shared tools, but with no LLM. This is what powers the
demo, the unit tests and CI, so the whole system is runnable and verifiable
by anyone with `pip install -e .` and zero secrets.
"""
from __future__ import annotations

from .config import Settings
from .decision import decide
from .models import ApprovalResult, ExpenseRequest
from .tools import analyze, run_intake


class LocalOrchestrator:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()

    def process(self, request: ExpenseRequest,
                history: list[ExpenseRequest] | None = None) -> ApprovalResult:
        policy = self.settings.policy
        # Stage 1 — Intake agent: validate + normalize.
        intake = run_intake(request)
        # Stage 2 — Policy Analyst agent: violations, risk, duplicate check.
        analysis = analyze(request, intake.normalized_category, policy, history)
        # Stage 3 — Approver agent (guard-railed by the shared decision rule).
        return decide(request, intake, analysis, policy, engine="local")
