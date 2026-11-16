"""Deterministic domain tools — the single source of truth for policy logic.

Both the LocalOrchestrator and the real CrewAI agents call these exact
functions, so the crew's *reasoning inputs* are identical whether or not an
LLM is in the loop. Keeping the hard rules here (not in prompts) is a
deliberate design choice: policy must be auditable and testable, not left to
a model's discretion.
"""
from __future__ import annotations

import unicodedata

from .config import SpendPolicy
from .guard import inspect_request
from .models import ExpenseRequest, IntakeResult, PolicyAnalysis

VALID_CATEGORIES = {"travel", "meals", "software", "equipment", "other"}


def normalize_category(category: str) -> str:
    """Map free-text categories onto the known policy buckets."""
    # NFKC folds fullwidth/compatibility forms ("ｍｅａｌｓ" -> "meals") and
    # format characters (zero-width, bidi) are dropped, so a disguised label
    # lands in its real bucket instead of the looser "other" limit.
    c = unicodedata.normalize("NFKC", category or "")
    c = "".join(ch for ch in c if unicodedata.category(ch) != "Cf").strip().lower()
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


def _person(name: str) -> str:
    """Identity key for an employee: NFKC, trimmed, whitespace-collapsed,
    case-folded — so "e3 " or "E3" can't dodge duplicate/split checks."""
    return " ".join(unicodedata.normalize("NFKC", name or "").split()).casefold()


def is_recognized_category(category: str) -> bool:
    """True when the submitted category maps onto a policy bucket. An explicit
    "other" is recognized; anything that only *falls back* to "other" is not."""
    c = unicodedata.normalize("NFKC", category or "")
    c = "".join(ch for ch in c if unicodedata.category(ch) != "Cf").strip().lower()
    return c == "other" or normalize_category(c) != "other"


def detect_duplicate(request: ExpenseRequest, history: list[ExpenseRequest]) -> bool:
    """Flag a likely duplicate: same employee, amount and category already seen."""
    for h in history:
        if (
            h.id != request.id
            and _person(h.employee) == _person(request.employee)
            and abs(h.amount - request.amount) < 0.01
            and normalize_category(h.category) == normalize_category(request.category)
        ):
            return True
    return False


def split_purchase_total(request: ExpenseRequest, history: list[ExpenseRequest]) -> float:
    """Same-day total for this employee + category, including this request.

    Catches "structuring": one purchase split into several requests that are
    each under the auto-approve limit. Only dated requests are compared."""
    if not request.date:
        return request.amount
    cat = normalize_category(request.category)
    total = request.amount
    for h in history:
        if (
            h.id != request.id and h.date == request.date
            and _person(h.employee) == _person(request.employee)
            and normalize_category(h.category) == cat
        ):
            total += h.amount
    return total


def analyze(request: ExpenseRequest, category: str, policy: SpendPolicy,
            history: list[ExpenseRequest] | None = None) -> PolicyAnalysis:
    """Full policy analysis (the Analyst agent's job)."""
    violations = check_policy(request, category, policy)
    # Fail closed on categories we can't classify: a free-text label such as
    # "Meals & entertainment" (or a homoglyph like "softwаre") would otherwise
    # fall back to "other" and escape that category's tighter limit.
    if not is_recognized_category(request.category):
        violations.append(
            f"unrecognized category '{request.category}' — a human must classify it"
        )
    risk = compute_risk(request, category, violations, policy)
    dup = detect_duplicate(request, history or [])
    if dup:
        violations = violations + ["possible duplicate of an earlier request"]
        risk = min(risk + 15, 100)
    same_day = split_purchase_total(request, history or [])
    if not dup and same_day > policy.auto_approve_limit >= request.amount:
        violations = violations + [
            f"possible split purchase: same-day {category} total ${same_day:,.2f} "
            f"exceeds the ${policy.auto_approve_limit:,.2f} auto-approve limit"
        ]
        risk = min(risk + 15, 100)
    # Input guard (OWASP LLM01): a suspected prompt-injection attempt is a
    # policy violation, so decide() can never auto-approve it -> human review.
    guard = inspect_request(request)
    if guard.suspicious:
        violations = violations + guard.as_violations()
        risk = min(risk + 25, 100)
    return PolicyAnalysis(
        violations=violations, risk_score=risk, is_possible_duplicate=dup,
        guard_findings=list(guard.findings), pii_kinds=list(guard.pii_kinds),
    )
