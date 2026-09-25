"""Repository layer — the only module that runs queries against the DB.

Isolating persistence here keeps the API and service layers ignorant of
SQLAlchemy details and gives the tests one place to exercise storage.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import ApprovalResult, ExpenseRequest
from .records import DecisionRecord


def save_decision(session: Session, request: ExpenseRequest, result: ApprovalResult) -> DecisionRecord:
    """Persist one decision and flush so the caller gets its generated id."""
    record = DecisionRecord.from_result(request, result)
    session.add(record)
    session.flush()  # populate record.id within the surrounding transaction
    return record


def get_decision(session: Session, record_id: int) -> DecisionRecord | None:
    return session.get(DecisionRecord, record_id)


def get_by_request_id(session: Session, request_id: str) -> DecisionRecord | None:
    """Most recent decision for a given business request id."""
    stmt = (
        select(DecisionRecord)
        .where(DecisionRecord.request_id == request_id)
        .order_by(DecisionRecord.id.desc())
        .limit(1)
    )
    return session.scalars(stmt).first()


def list_decisions(
    session: Session,
    *,
    limit: int = 50,
    offset: int = 0,
    decision: str | None = None,
    employee: str | None = None,
) -> list[DecisionRecord]:
    """Recent decisions, newest first, with optional filters + pagination."""
    stmt = select(DecisionRecord).order_by(DecisionRecord.id.desc())
    if decision:
        stmt = stmt.where(DecisionRecord.decision == decision)
    if employee:
        stmt = stmt.where(DecisionRecord.employee == employee)
    stmt = stmt.offset(max(offset, 0)).limit(max(1, min(limit, 500)))
    return list(session.scalars(stmt).all())


def count_decisions(session: Session, *, decision: str | None = None) -> int:
    from sqlalchemy import func

    stmt = select(func.count()).select_from(DecisionRecord)
    if decision:
        stmt = stmt.where(DecisionRecord.decision == decision)
    return int(session.scalar(stmt) or 0)
