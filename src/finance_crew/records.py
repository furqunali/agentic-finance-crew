"""ORM models — the persisted system-of-record and its audit trail.

Kept deliberately separate from the domain ``models.py`` dataclasses: those are
pure, dependency-free value objects used by the orchestration engines, while
these are the storage representation.

Two tables:

* :class:`DecisionRecord` — one row per expense decision. The AI/guardrail
  fields (``decision``, ``ai_recommendation``, ``rules_fired``, ``risk_score``,
  ``model_version`` …) are written once and never mutated. A human resolution
  of a review item is layered on via the ``status`` / ``resolved_*`` fields,
  so the original machine verdict is always preserved.
* :class:`AuditEvent` — an append-only log of every step in a decision's
  lifecycle (request → reasoning → policy → decision → human review → final
  action), each with an actor and timestamp. This is the immutable audit trail.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base
from .models import ApprovalResult, Decision, ExpenseRequest


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# --- Lifecycle status values -------------------------------------------------
class Status:
    """Lifecycle of a decision. Machine outcomes are terminal; ``PENDING_REVIEW``
    is the only state a human can transition out of."""

    AUTO_APPROVED = "auto_approved"
    AUTO_REJECTED = "auto_rejected"
    PENDING_REVIEW = "pending_review"
    HUMAN_APPROVED = "human_approved"
    HUMAN_REJECTED = "human_rejected"


# --- Audit trail step names --------------------------------------------------
class Step:
    """The stages every decision passes through, mirroring the pipeline."""

    REQUEST_RECEIVED = "request_received"
    AI_REASONING = "ai_reasoning"
    POLICY_EVALUATION = "policy_evaluation"
    DECISION = "decision"
    HUMAN_REVIEW = "human_review"
    FINAL_ACTION = "final_action"


_DECISION_TO_STATUS = {
    Decision.AUTO_APPROVED.value: Status.AUTO_APPROVED,
    Decision.REJECTED.value: Status.AUTO_REJECTED,
    Decision.NEEDS_HUMAN_REVIEW.value: Status.PENDING_REVIEW,
}

_FINAL_ACTION = {
    Status.AUTO_APPROVED: "approved",
    Status.HUMAN_APPROVED: "approved",
    Status.AUTO_REJECTED: "rejected",
    Status.HUMAN_REJECTED: "rejected",
    Status.PENDING_REVIEW: "pending",
}


class DecisionRecord(Base):
    """One persisted expense decision — the durable output of the crew, plus
    the audit fields the doc calls for (who requested it, what the AI
    recommended, which rules fired, who approved it, timestamps, model/version)."""

    __tablename__ = "decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(String(64), index=True)
    employee: Mapped[str] = mapped_column(String(120), index=True)
    category: Mapped[str] = mapped_column(String(40))
    amount: Mapped[float] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(8), default="USD")

    # Machine verdict (write-once, never mutated).
    decision: Mapped[str] = mapped_column(String(32), index=True)
    ai_recommendation: Mapped[str] = mapped_column(String(32), default="")
    rules_fired: Mapped[str] = mapped_column(Text, default="[]")  # JSON list
    risk_score: Mapped[int] = mapped_column(Integer, default=0)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    rationale: Mapped[str] = mapped_column(Text, default="")
    engine: Mapped[str] = mapped_column(String(20), default="local")
    model_version: Mapped[str] = mapped_column(String(64), default="")

    # Who asked, and the lifecycle overlay a human can advance.
    requested_by: Mapped[str] = mapped_column(String(120), default="")
    status: Mapped[str] = mapped_column(String(24), index=True, default=Status.PENDING_REVIEW)
    resolved_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), default=_utcnow
    )

    events: Mapped[list["AuditEvent"]] = relationship(
        back_populates="decision_row",
        cascade="all, delete-orphan",
        order_by="AuditEvent.id",
    )

    @classmethod
    def from_result(
        cls,
        request: ExpenseRequest,
        result: ApprovalResult,
        *,
        requested_by: str | None = None,
        model_version: str = "",
    ) -> "DecisionRecord":
        """Build a storable record from a domain request + its verdict."""
        return cls(
            request_id=result.request_id,
            employee=request.employee,
            category=result.intake.normalized_category or request.category,
            amount=request.amount,
            currency=request.currency,
            decision=result.decision.value,
            ai_recommendation=result.decision.value,
            rules_fired=json.dumps(list(result.analysis.violations)),
            risk_score=result.risk_score,
            confidence=result.confidence,
            rationale=result.rationale,
            engine=result.engine,
            model_version=model_version or result.engine,
            requested_by=requested_by or request.employee,
            status=_DECISION_TO_STATUS.get(result.decision.value, Status.PENDING_REVIEW),
        )

    @property
    def rules(self) -> list[str]:
        try:
            return list(json.loads(self.rules_fired or "[]"))
        except (ValueError, TypeError):
            return []

    @property
    def final_action(self) -> str:
        return _FINAL_ACTION.get(self.status, "pending")

    @property
    def is_pending_review(self) -> bool:
        return self.status == Status.PENDING_REVIEW

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "request_id": self.request_id,
            "employee": self.employee,
            "requested_by": self.requested_by,
            "category": self.category,
            "amount": self.amount,
            "currency": self.currency,
            "decision": self.decision,
            "ai_recommendation": self.ai_recommendation,
            "rules_fired": self.rules,
            "risk_score": self.risk_score,
            "confidence": self.confidence,
            "rationale": self.rationale,
            "engine": self.engine,
            "model_version": self.model_version,
            "status": self.status,
            "final_action": self.final_action,
            "resolved_by": self.resolved_by,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "resolution_note": self.resolution_note,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class User(Base):
    """An authenticated principal with an RBAC role."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(24), default="employee", index=True)
    full_name: Mapped[str] = mapped_column(String(120), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), default=_utcnow
    )

    def to_dict(self) -> dict[str, Any]:
        # Never serialize the password hash.
        return {
            "id": self.id,
            "username": self.username,
            "role": self.role,
            "full_name": self.full_name,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class AuditEvent(Base):
    """One immutable, append-only entry in a decision's audit trail."""

    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    decision_id: Mapped[int] = mapped_column(
        ForeignKey("decisions.id", ondelete="CASCADE"), index=True
    )
    step: Mapped[str] = mapped_column(String(32), index=True)
    actor: Mapped[str] = mapped_column(String(120), default="system")
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), default=_utcnow
    )

    decision_row: Mapped["DecisionRecord"] = relationship(back_populates="events")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "decision_id": self.decision_id,
            "step": self.step,
            "actor": self.actor,
            "detail": self.detail,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
