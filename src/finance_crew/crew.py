"""The real multi-agent CrewAI crew (opt-in engine).

Three specialist agents run sequentially — Intake Officer, Policy Analyst and
Approving Manager — each backed by an LLM and the shared deterministic tools.

Design guarantee: the LLM crew produces the *analysis narrative and routing
recommendation*, but the final decision is still passed through the same
`decide()` guardrail used by the local engine. An LLM can never override
company policy — it can only explain and enrich it. This is what makes the
system safe to run unattended.

This module is imported lazily (only when USE_CREWAI=true and a key is set),
so `crewai` is an optional dependency and CI never needs it.
"""
from __future__ import annotations

from .config import Settings
from .decision import decide
from .models import ApprovalResult, ExpenseRequest
from .tools import analyze, run_intake


def _build_llm(settings: Settings):
    """Construct a CrewAI LLM for the configured provider."""
    from crewai import LLM  # imported here so the dep stays optional

    if settings.llm_provider == "gemini":
        return LLM(model=f"gemini/{settings.model}", api_key=settings.api_key)
    return LLM(model=settings.model, api_key=settings.api_key)


def _build_agents(llm):
    from crewai import Agent

    intake_officer = Agent(
        role="Expense Intake Officer",
        goal="Validate and normalize incoming expense requests before analysis.",
        backstory=(
            "A meticulous back-office specialist who catches malformed or "
            "incomplete requests early so downstream agents work on clean data."
        ),
        llm=llm, verbose=False, allow_delegation=False,
    )
    policy_analyst = Agent(
        role="Policy Analyst",
        goal="Assess each request against company spend policy and quantify risk.",
        backstory=(
            "A finance controls analyst who knows the spend policy cold and "
            "flags limit breaches, missing receipts and likely duplicates."
        ),
        llm=llm, verbose=False, allow_delegation=False,
    )
    approving_manager = Agent(
        role="Approving Manager",
        goal="Recommend a clear routing decision with a concise, auditable rationale.",
        backstory=(
            "A pragmatic manager who auto-approves the small and compliant, and "
            "escalates anything risky to a human — never rubber-stamps."
        ),
        llm=llm, verbose=False, allow_delegation=False,
    )
    return intake_officer, policy_analyst, approving_manager


def _build_tasks(request: ExpenseRequest, intake, analysis, agents):
    from crewai import Task

    intake_officer, policy_analyst, approving_manager = agents
    facts = (
        f"Request {request.id}: {request.employee} claims ${request.amount:,.2f} "
        f"for '{request.category}' — {request.description!r}. "
        f"Receipt attached: {request.has_receipt}."
    )
    t_intake = Task(
        description=f"{facts}\nDeterministic intake result: {intake}. "
                    "Summarize the request and note any data-quality issues.",
        expected_output="A one-paragraph summary of the request and its data quality.",
        agent=intake_officer,
    )
    t_analysis = Task(
        description=f"{facts}\nDeterministic policy analysis: {analysis}. "
                    "Explain the policy position: which limits apply, any violations, "
                    "the risk level and why.",
        expected_output="A concise policy assessment referencing the concrete violations and risk.",
        agent=policy_analyst,
    )
    t_decision = Task(
        description="Given the intake summary and policy assessment, recommend one of "
                    "AUTO_APPROVED / NEEDS_HUMAN_REVIEW / REJECTED and justify it in 2-3 sentences.",
        expected_output="A recommended decision with a short, auditable rationale.",
        agent=approving_manager,
    )
    return [t_intake, t_analysis, t_decision]


class CrewAIOrchestrator:
    """Runs the real CrewAI crew, then applies the policy guardrail."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def process(self, request: ExpenseRequest,
                history: list[ExpenseRequest] | None = None) -> ApprovalResult:
        from crewai import Crew, Process

        policy = self.settings.policy
        # Pre-compute the deterministic facts the agents reason over.
        intake = run_intake(request)
        analysis = analyze(request, intake.normalized_category, policy, history)

        llm = _build_llm(self.settings)
        agents = _build_agents(llm)
        tasks = _build_tasks(request, intake, analysis, agents)
        crew = Crew(agents=list(agents), tasks=tasks, process=Process.sequential, verbose=False)
        crew_output = crew.kickoff()

        # The crew explains; the guardrail decides.
        result = decide(request, intake, analysis, policy, engine="crewai")
        narrative = str(getattr(crew_output, "raw", crew_output)).strip()
        if narrative:
            result.rationale = f"{result.rationale}\n\nCrew rationale: {narrative}"
        return result
