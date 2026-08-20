"""Typed domain models shared by every orchestrator.

These are plain dataclasses (no third-party deps) so the whole domain layer
imports and tests cleanly without CrewAI, an LLM, or any API key present.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any


class Decision(str, Enum):
    """Final routing decision for an expense request."""

    AUTO_APPROVED = "auto_approved"
    NEEDS_HUMAN_REVIEW = "needs_human_review"
    REJECTED = "rejected"


@dataclass
class ExpenseRequest:
    """A single expense/reimbursement request entering the crew."""

    id: str
    employee: str
    category: str
    amount: float
    description: str = ""
    currency: str = "USD"
    has_receipt: bool = False
    date: str = ""

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ExpenseRequest":
        known = {f: d.get(f) for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        # sensible defaults for anything missing
        known["amount"] = float(known.get("amount") or 0.0)
        known["has_receipt"] = bool(known.get("has_receipt"))
        known["category"] = (known.get("category") or "other")
        return cls(**{k: v for k, v in known.items() if v is not None})


@dataclass
class IntakeResult:
    """Output of the Intake agent: normalized + validated request."""

    valid: bool
    normalized_category: str
    issues: list[str] = field(default_factory=list)


@dataclass
class PolicyAnalysis:
    """Output of the Policy Analyst agent."""

    violations: list[str] = field(default_factory=list)
    risk_score: int = 0  # 0 (safe) .. 100 (high risk)
    is_possible_duplicate: bool = False


@dataclass
class ApprovalResult:
    """The crew's end-to-end verdict for one request."""

    request_id: str
    decision: Decision
    rationale: str
    risk_score: int
    confidence: float
    intake: IntakeResult
    analysis: PolicyAnalysis
    engine: str = "local"  # "crewai" or "local"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["decision"] = self.decision.value
        return d
