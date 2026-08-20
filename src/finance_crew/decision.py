"""The approval decision rule — shared by both engines.

The Approver agent (LLM) is asked to *explain* and *route*, but the final
guardrail is this deterministic function so the system can never auto-approve
something the policy forbids, regardless of what a model outputs.
"""
from __future__ import annotations

from .config import SpendPolicy
from .models import ApprovalResult, Decision, ExpenseRequest, IntakeResult, PolicyAnalysis


def decide(
    request: ExpenseRequest,
    intake: IntakeResult,
    analysis: PolicyAnalysis,
    policy: SpendPolicy,
    engine: str = "local",
) -> ApprovalResult:
    """Combine intake + analysis into a final, safe routing decision."""
    # 1) Hard-invalid requests are rejected outright.
    if not intake.valid:
        return ApprovalResult(
            request_id=request.id,
            decision=Decision.REJECTED,
            rationale="Request failed intake validation: " + "; ".join(intake.issues),
            risk_score=analysis.risk_score,
            confidence=0.95,
            intake=intake,
            analysis=analysis,
            engine=engine,
        )

    over_human_limit = request.amount > policy.human_review_limit
    has_violation = bool(analysis.violations)
    high_risk = analysis.risk_score >= 60

    # 2) Anything over the human limit, violating policy, or high-risk -> human.
    if over_human_limit or has_violation or high_risk:
        reasons = analysis.violations[:] or [f"risk score {analysis.risk_score} requires review"]
        return ApprovalResult(
            request_id=request.id,
            decision=Decision.NEEDS_HUMAN_REVIEW,
            rationale="Routed to a human approver — " + "; ".join(reasons),
            risk_score=analysis.risk_score,
            confidence=0.9,
            intake=intake,
            analysis=analysis,
            engine=engine,
        )

    # 3) Small, compliant, low-risk requests auto-approve.
    if request.amount <= policy.auto_approve_limit:
        return ApprovalResult(
            request_id=request.id,
            decision=Decision.AUTO_APPROVED,
            rationale=(
                f"Auto-approved: ${request.amount:,.2f} is within the "
                f"${policy.auto_approve_limit:,.2f} auto-approve limit, compliant, low risk."
            ),
            risk_score=analysis.risk_score,
            confidence=0.85,
            intake=intake,
            analysis=analysis,
            engine=engine,
        )

    # 4) Compliant but above the auto-approve threshold -> human sign-off.
    return ApprovalResult(
        request_id=request.id,
        decision=Decision.NEEDS_HUMAN_REVIEW,
        rationale=(
            f"Compliant but ${request.amount:,.2f} exceeds the "
            f"${policy.auto_approve_limit:,.2f} auto-approve limit — needs sign-off."
        ),
        risk_score=analysis.risk_score,
        confidence=0.8,
        intake=intake,
        analysis=analysis,
        engine=engine,
    )
