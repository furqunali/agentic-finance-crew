"""ORM models — the persisted system-of-record.

Kept deliberately separate from the domain ``models.py`` dataclasses: those are
pure, dependency-free value objects used by the orchestration engines, while
these are the storage representation. :func:`DecisionRecord.from_result` bridges
the two so the engines never depend on SQLAlchemy.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import DateTime, Float, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base
from .models import ApprovalResult, ExpenseRequest


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class DecisionRecord(Base):
    """One persisted expense decision — the durable output of the crew.

    (The full immutable audit trail — rules fired, human approver, model
    version — is layered on top of this in a later migration.)
    """

    __tablename__ = "decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(String(64), index=True)
    employee: Mapped[str] = mapped_column(String(120), index=True)
    category: Mapped[str] = mapped_column(String(40))
    amount: Mapped[float] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(8), default="USD")

    decision: Mapped[str] = mapped_column(String(32), index=True)
    risk_score: Mapped[int] = mapped_column(Integer, default=0)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    rationale: Mapped[str] = mapped_column(Text, default="")
    engine: Mapped[str] = mapped_column(String(20), default="local")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), default=_utcnow
    )

    @classmethod
    def from_result(cls, request: ExpenseRequest, result: ApprovalResult) -> "DecisionRecord":
        """Build a storable record from a domain request + its verdict."""
        return cls(
            request_id=result.request_id,
            employee=request.employee,
            category=result.intake.normalized_category or request.category,
            amount=request.amount,
            currency=request.currency,
            decision=result.decision.value,
            risk_score=result.risk_score,
            confidence=result.confidence,
            rationale=result.rationale,
            engine=result.engine,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "request_id": self.request_id,
            "employee": self.employee,
            "category": self.category,
            "amount": self.amount,
            "currency": self.currency,
            "decision": self.decision,
            "risk_score": self.risk_score,
            "confidence": self.confidence,
            "rationale": self.rationale,
            "engine": self.engine,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
