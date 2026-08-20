"""Deterministic domain tools — the single source of truth for policy logic.

Both the LocalOrchestrator and the real CrewAI agents call these exact
functions, so the crew's *reasoning inputs* are identical whether or not an
LLM is in the loop. Keeping the hard rules here (not in prompts) is a
deliberate design choice: policy must be auditable and testable, not left to
a model's discretion.
"""
from __future__ import annotations

from .config import SpendPolicy
from .models import ExpenseRequest, IntakeResult, PolicyAnalysis

VALID_CATEGORIES = {"travel", "meals", "software", "equipment", "other"}


def normalize_category(category: str) -> str:
    """Map free-text categories onto the known policy buckets."""
    c = (category or "").strip().lower()
    aliases = {
        "flight": "travel", "hotel": "travel", "taxi": "travel", "uber": "travel",
        "food": "meals", "lunch": "meals", "dinner": "meals", "restaurant": "meals",
        "saas": "software", "subscription": "software", "license": "software",
        "hardware": "equipment", "laptop": "equipment", "device": "equipment",
    }
    c = aliases.get(c, c)
    return c if c in VALID_CATEGORIES else "other"


def run_intake(request: ExpenseRequest) -> IntakeResult:
    """Validate and normalize an incoming request (the Intake agent's job)."""
    issues: list[str] = []
    if not request.employee:
        issues.append("missing employee")
    if not request.id:
        issues.append("missing request id")
    if request.amount <= 0:
        issues.append("amount must be positive")
    if request.amount > 100_000:
        issues.append("amount implausibly large")
    normalized = normalize_category(request.category)
    if normalized == "other" and request.category and request.category.lower() not in VALID_CATEGORIES:
        issues.append(f"unknown category '{request.category}' mapped to 'other'")
    valid = not any(
        i.startswith(("missing", "amount")) for i in issues
    )
    return IntakeResult(valid=valid, normalized_category=normalized, issues=issues)


def check_policy(request: ExpenseRequest, category: str, policy: SpendPolicy) -> list[str]:
    """Return the list of policy violations for a request."""
    violations: list[str] = []
    limit = policy.limit_for(category)
    if request.amount > limit:
        violations.append(
            f"amount ${request.amount:,.2f} exceeds {category} limit ${limit:,.2f}"
        )
    if request.amount > policy.receipt_required_above and not request.has_receipt:
        violations.append(
            f"receipt required for amounts over ${policy.receipt_required_above:,.2f}"
        )
    if request.amount > policy.human_review_limit:
        violations.append(
            f"amount over ${policy.human_review_limit:,.2f} always needs human sign-off"
        )
    return violations


def compute_risk(request: ExpenseRequest, category: str, violations: list[str], policy: SpendPolicy) -> int:
    """Score 0 (safe) .. 100 (high risk) from amount ratio + violations."""
    limit = policy.limit_for(category)
    ratio = min(request.amount / limit, 2.0) if limit else 1.0
    score = int(ratio * 30)                       # up to 60 from how close to / over limit
    score += 20 * len(violations)                 # each violation adds risk
    if not request.has_receipt and request.amount > policy.receipt_required_above:
        score += 10
    return max(0, min(score, 100))


def detect_duplicate(request: ExpenseRequest, history: list[ExpenseRequest]) -> bool:
    """Flag a likely duplicate: same employee, amount and category already seen."""
    for h in history:
        if (
            h.id != request.id
            and h.employee == request.employee
            and abs(h.amount - request.amount) < 0.01
            and normalize_category(h.category) == normalize_category(request.category)
        ):
            return True
    return False


def analyze(request: ExpenseRequest, category: str, policy: SpendPolicy,
            history: list[ExpenseRequest] | None = None) -> PolicyAnalysis:
    """Full policy analysis (the Analyst agent's job)."""
    violations = check_policy(request, category, policy)
    risk = compute_risk(request, category, violations, policy)
    dup = detect_duplicate(request, history or [])
    if dup:
        violations = violations + ["possible duplicate of an earlier request"]
        risk = min(risk + 15, 100)
    return PolicyAnalysis(violations=violations, risk_score=risk, is_possible_duplicate=dup)
