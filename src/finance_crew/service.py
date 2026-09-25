"""Application service — runs the crew, persists the result, and records the
full audit trail.

This is the seam between the pure orchestration pipeline (which knows nothing
about storage) and the durable system-of-record. Every decision served over
HTTP is written to the database *and* accompanied by an append-only trail of
audit events, inside a single transaction owned by the caller's session_scope.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from . import __version__, repository
from .config import Settings
from .errors import ConflictError, NotFoundError, ValidationError
from .models import ApprovalResult, ExpenseRequest
from .orchestrator import build_orchestrator
from .records import DecisionRecord, Status, Step


def _model_version(result: ApprovalResult, settings: Settings) -> str:
    """A stable, auditable identifier for *what decided this* — the engine (and
    LLM model, when the real crew ran) pinned to the app version."""
    if result.engine == "crewai":
        base = f"crewai:{settings.model}"
    else:
        base = result.engine  # deterministic rule engine (local / langgraph)
    return f"{base}@{__version__}"


def _write_initial_trail(session: Session, record: DecisionRecord, result: ApprovalResult) -> None:
    """Record the machine half of the lifecycle: request → reasoning → policy →
    decision (→ final action, when auto-resolved)."""
    actor = record.engine
    repository.add_audit_event(
        session, record.id, Step.REQUEST_RECEIVED, record.requested_by or record.employee,
        f"{record.employee} requested {record.category} ${record.amount:,.2f}",
    )
    repository.add_audit_event(
        session, record.id, Step.AI_REASONING, actor,
        f"risk score {result.risk_score}/100, confidence {result.confidence:.2f}",
    )
    rules = list(result.analysis.violations)
    repository.add_audit_event(
        session, record.id, Step.POLICY_EVALUATION, actor,
        ("rules fired: " + "; ".join(rules)) if rules else "no policy violations",
    )
    repository.add_audit_event(
        session, record.id, Step.DECISION, actor,
        f"AI recommendation: {record.ai_recommendation} — {result.rationale}",
    )
    # Auto-resolved outcomes have no human step; close the trail now.
    if record.status in (Status.AUTO_APPROVED, Status.AUTO_REJECTED):
        repository.add_audit_event(
            session, record.id, Step.FINAL_ACTION, "system",
            f"auto {record.final_action} (no human review required)",
        )


def decide_and_store(
    session: Session,
    payload: dict[str, Any],
    history: list[dict[str, Any]] | None = None,
    settings: Settings | None = None,
    requested_by: str | None = None,
) -> tuple[ApprovalResult, int]:
    """Process one request, persist it, and write its audit trail.

    Returns (result, stored record id). The surrounding session_scope owns the
    commit/rollback, so a failure to persist rolls the whole unit back.
    """
    settings = settings or Settings.from_env()
    request = ExpenseRequest.from_dict(payload)
    hist = [ExpenseRequest.from_dict(h) for h in (history or [])]
    orchestrator = build_orchestrator(settings)
    result = orchestrator.process(request, hist)

    record = DecisionRecord.from_result(
        request, result, requested_by=requested_by,
        model_version=_model_version(result, settings),
    )
    session.add(record)
    session.flush()  # populate record.id
    _write_initial_trail(session, record, result)
    return result, record.id


def decide_and_store_batch(
    session: Session,
    payloads: list[dict[str, Any]],
    settings: Settings | None = None,
    requested_by: str | None = None,
) -> list[tuple[ApprovalResult, int]]:
    """Process + persist a batch; earlier items act as history for dup checks."""
    settings = settings or Settings.from_env()
    orchestrator = build_orchestrator(settings)
    out: list[tuple[ApprovalResult, int]] = []
    seen: list[ExpenseRequest] = []
    for payload in payloads:
        request = ExpenseRequest.from_dict(payload)
        result = orchestrator.process(request, list(seen))
        record = DecisionRecord.from_result(
            request, result, requested_by=requested_by,
            model_version=_model_version(result, settings),
        )
        session.add(record)
        session.flush()
        _write_initial_trail(session, record, result)
        out.append((result, record.id))
        seen.append(request)
    return out


def resolve_decision(
    session: Session, decision_id: int, action: str, actor: str, note: str = ""
) -> DecisionRecord:
    """Apply a human's approve/reject to a decision awaiting review.

    The machine verdict is never mutated — the human outcome is layered on via
    ``status`` / ``resolved_*`` and two new audit events, preserving the full
    who-recommended-what-vs-who-decided-what trail.
    """
    action = (action or "").strip().lower()
    if action not in ("approve", "reject"):
        raise ValidationError(f"action must be 'approve' or 'reject', got {action!r}")

    record = session.get(DecisionRecord, decision_id)
    if record is None:
        raise NotFoundError(f"no decision with id {decision_id}")
    if not record.is_pending_review:
        raise ConflictError(
            f"decision {decision_id} is '{record.status}', not awaiting human review"
        )
    if not actor:
        raise ValidationError("a human approver (actor) is required")

    record.status = Status.HUMAN_APPROVED if action == "approve" else Status.HUMAN_REJECTED
    record.resolved_by = actor
    record.resolved_at = datetime.now(timezone.utc)
    record.resolution_note = note or None

    repository.add_audit_event(
        session, record.id, Step.HUMAN_REVIEW, actor,
        f"{actor} {action}d the request" + (f": {note}" if note else ""),
    )
    repository.add_audit_event(
        session, record.id, Step.FINAL_ACTION, actor,
        f"final action: {record.final_action} by {actor}",
    )
    session.flush()
    return record
