"""Repository layer — the only module that runs queries against the DB.

Isolating persistence here keeps the API and service layers ignorant of
SQLAlchemy details and gives the tests one place to exercise storage.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .integrity import GENESIS, event_digest
from .models import ApprovalResult, ExpenseRequest
from .records import AuditEvent, DecisionRecord, Status, User


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


def list_review_queue(session: Session, *, limit: int = 50, offset: int = 0) -> list[DecisionRecord]:
    """Decisions awaiting a human sign-off, oldest first (FIFO queue)."""
    stmt = (
        select(DecisionRecord)
        .where(DecisionRecord.status == Status.PENDING_REVIEW)
        .order_by(DecisionRecord.id.asc())
        .offset(max(offset, 0))
        .limit(max(1, min(limit, 500)))
    )
    return list(session.scalars(stmt).all())


def recent_decisions_for(session: Session, employee_key: str, *, limit: int = 500) -> list[DecisionRecord]:
    """The latest stored decisions for one (normalized) employee, newest first —
    the history new requests are checked against for duplicates and splits.
    Intake-rejected rows are excluded: they never represented valid spend."""
    stmt = (
        select(DecisionRecord)
        .where(DecisionRecord.employee_key == employee_key)
        .where(DecisionRecord.status != Status.AUTO_REJECTED)
        .order_by(DecisionRecord.id.desc())
        .limit(max(1, limit))
    )
    return list(session.scalars(stmt).all())


# --- Audit trail -------------------------------------------------------------
def add_audit_event(
    session: Session, decision_id: int, step: str, actor: str, detail: str = ""
) -> AuditEvent:
    """Append one immutable, hash-chained entry to a decision's audit trail.

    The event links to the decision's current chain head (or, for the first
    event, to the decision's record digest), and becomes the new head."""
    record = session.get(DecisionRecord, decision_id)
    prev = (record.head_hash or record.record_hash or GENESIS) if record else GENESIS
    event = AuditEvent(decision_id=decision_id, step=step, actor=actor, detail=detail,
                       created_at=datetime.now(timezone.utc), prev_hash=prev)
    event.hash = event_digest(prev, event)
    session.add(event)
    if record is not None:
        record.head_hash = event.hash
    session.flush()
    return event


def get_audit_events(session: Session, decision_id: int) -> list[AuditEvent]:
    """The full, ordered audit trail for one decision."""
    stmt = (
        select(AuditEvent)
        .where(AuditEvent.decision_id == decision_id)
        .order_by(AuditEvent.id.asc())
    )
    return list(session.scalars(stmt).all())


def list_audit_events(
    session: Session, *, limit: int = 100, offset: int = 0, step: str | None = None
) -> list[AuditEvent]:
    """Global audit log across all decisions, newest first."""
    stmt = select(AuditEvent).order_by(AuditEvent.id.desc())
    if step:
        stmt = stmt.where(AuditEvent.step == step)
    stmt = stmt.offset(max(offset, 0)).limit(max(1, min(limit, 1000)))
    return list(session.scalars(stmt).all())


# --- Users -------------------------------------------------------------------
def get_user_by_username(session: Session, username: str) -> User | None:
    stmt = select(User).where(User.username == username)
    return session.scalars(stmt).first()


def count_users(session: Session) -> int:
    from sqlalchemy import func

    return int(session.scalar(select(func.count()).select_from(User)) or 0)


def list_users(session: Session, *, limit: int = 100, offset: int = 0) -> list[User]:
    stmt = select(User).order_by(User.id.asc()).offset(max(offset, 0)).limit(max(1, min(limit, 500)))
    return list(session.scalars(stmt).all())


def create_user(
    session: Session, *, username: str, password: str, role: str, full_name: str = ""
) -> User:
    """Create a user with a securely hashed password. Flushes so id is set."""
    from .security import hash_password

    user = User(
        username=username,
        hashed_password=hash_password(password),
        role=role,
        full_name=full_name,
    )
    session.add(user)
    session.flush()
    return user
