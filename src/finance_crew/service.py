"""Application service — runs the crew, persists the result, and records the
full audit trail.

This is the seam between the pure orchestration pipeline (which knows nothing
about storage) and the durable system-of-record. Every decision served over
HTTP is written to the database *and* accompanied by an append-only trail of
audit events, inside a single transaction owned by the caller's session_scope.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from . import __version__, observability, repository
from .config import Settings
from .integrity import record_digest
from .errors import ConflictError, ForbiddenError, NotFoundError, ValidationError
from .models import ApprovalResult, ExpenseRequest
from .orchestrator import build_orchestrator
from .records import DecisionRecord, Status, Step
from .tools import person_key


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
    analysis = result.analysis
    if analysis.guard_findings or analysis.pii_kinds:
        parts = []
        if analysis.guard_findings:
            parts.append(
                "possible prompt injection -> routed to human review: "
                + "; ".join(analysis.guard_findings)
            )
        if analysis.pii_kinds:
            parts.append("PII redacted before LLM/logs: " + ", ".join(analysis.pii_kinds))
        repository.add_audit_event(session, record.id, Step.INPUT_GUARD, "input-guard", " | ".join(parts))
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


def _persist(
    session: Session,
    request: ExpenseRequest,
    result: ApprovalResult,
    settings: Settings,
    requested_by: str | None,
    latency_ms: float,
) -> DecisionRecord:
    """Store one decision + its trail and emit the observability metrics.

    Deterministic engines (local/langgraph) use no LLM, so their token count
    and cost are genuinely zero; the real crew would report actual usage here.
    """
    tokens = 0
    cost_usd = observability.estimate_cost(settings.model, tokens)
    dual = request.amount > settings.policy.dual_control_above
    record = DecisionRecord.from_result(
        request, result, requested_by=requested_by,
        model_version=_model_version(result, settings),
        latency_ms=latency_ms, tokens=tokens, cost_usd=cost_usd,
        approvals_required=2 if dual else 1,
    )
    record.record_hash = record_digest(record)
    session.add(record)
    session.flush()
    _write_initial_trail(session, record, result)

    observability.DECISIONS.labels(result.decision.value, result.engine).inc()
    for finding in result.analysis.guard_findings:
        observability.INPUT_GUARD_FLAGS.labels(finding.split(": ", 1)[-1]).inc()
    observability.DECISION_LATENCY.observe(latency_ms / 1000.0)
    observability.record_llm_usage(result.engine, tokens, cost_usd)
    return record


def stored_history(session: Session, request: ExpenseRequest, settings: Settings) -> list[ExpenseRequest]:
    """This employee's earlier stored decisions (within the look-back window) as
    history, so duplicates and same-day split purchases are caught across
    separate API calls and days — not only inside one batch."""
    days = settings.history_lookback_days
    if days <= 0:
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    out: list[ExpenseRequest] = []
    for r in repository.recent_decisions_for(session, person_key(request.employee)):
        created = r.created_at
        if created is not None and created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        if created is not None and created < cutoff:
            continue
        out.append(ExpenseRequest(
            id=f"stored-{r.id}", employee=r.employee, category=r.category,
            amount=r.amount, currency=r.currency, date=r.expense_date or "",
        ))
    return out


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
    hist = stored_history(session, request, settings)
    hist += [ExpenseRequest.from_dict(h) for h in (history or [])]
    orchestrator = build_orchestrator(settings)

    t0 = time.perf_counter()
    result = orchestrator.process(request, hist)
    latency_ms = (time.perf_counter() - t0) * 1000.0

    record = _persist(session, request, result, settings, requested_by, latency_ms)
    return result, record.id


def decide_and_store_batch(
    session: Session,
    payloads: list[dict[str, Any]],
    settings: Settings | None = None,
    requested_by: str | None = None,
) -> list[tuple[ApprovalResult, int]]:
    """Process + persist a batch; earlier items act as history for dup checks.

    With the stored-history look-back on, earlier batch items are already in
    the database (each is flushed as it is stored), so they are found there;
    otherwise the in-memory list of earlier items is used."""
    settings = settings or Settings.from_env()
    orchestrator = build_orchestrator(settings)
    out: list[tuple[ApprovalResult, int]] = []
    seen: list[ExpenseRequest] = []
    for payload in payloads:
        request = ExpenseRequest.from_dict(payload)
        if settings.history_lookback_days > 0:
            hist = stored_history(session, request, settings)
        else:
            hist = list(seen)
        t0 = time.perf_counter()
        result = orchestrator.process(request, hist)
        latency_ms = (time.perf_counter() - t0) * 1000.0
        record = _persist(session, request, result, settings, requested_by, latency_ms)
        out.append((result, record.id))
        seen.append(request)
    return out


def _same_person(actor: str, *owners: str | None) -> bool:
    a = (actor or "").strip().casefold()
    return bool(a) and any(a == (o or "").strip().casefold() for o in owners)


def resolve_decision(
    session: Session, decision_id: int, action: str, actor: str, note: str = "",
    enforce_separation_of_duties: bool = True,
) -> DecisionRecord:
    """Apply a human's approve/reject to a decision awaiting review.

    The machine verdict is never mutated — the human outcome is layered on via
    ``status`` / ``resolved_*`` and two new audit events, preserving the full
    who-recommended-what-vs-who-decided-what trail.

    Dual control: when the record needs two approvals, the first approve is
    recorded (the item stays in the queue) and a *different* reviewer must give
    the second. A reject from any eligible reviewer ends it at once.
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
    # Separation of duties: nobody signs off their own expense. Only disabled
    # in single-user local mode (AUTH_DISABLED), where every caller is "admin".
    if enforce_separation_of_duties and _same_person(actor, record.requested_by, record.employee):
        raise ForbiddenError(
            f"separation of duties: {actor!r} submitted decision {decision_id} "
            "and cannot resolve it — another reviewer must"
        )

    needs_two = int(record.approvals_required or 1) >= 2
    if action == "approve" and needs_two and not record.first_approved_by:
        record.first_approved_by = actor
        record.first_approved_at = datetime.now(timezone.utc)
        repository.add_audit_event(
            session, record.id, Step.HUMAN_REVIEW, actor,
            f"{actor} gave approval 1 of 2 (dual control)" + (f": {note}" if note else ""),
        )
        session.flush()
        observability.RESOLUTIONS.labels("first_approval").inc()
        return record
    if (action == "approve" and needs_two and enforce_separation_of_duties
            and _same_person(actor, record.first_approved_by)):
        raise ForbiddenError(
            f"dual control: {actor!r} already gave the first approval for decision "
            f"{decision_id} — a second, different reviewer must approve"
        )

    record.status = Status.HUMAN_APPROVED if action == "approve" else Status.HUMAN_REJECTED
    record.resolved_by = actor
    record.resolved_at = datetime.now(timezone.utc)
    record.resolution_note = note or None

    step_note = " (approval 2 of 2, dual control)" if action == "approve" and needs_two else ""
    repository.add_audit_event(
        session, record.id, Step.HUMAN_REVIEW, actor,
        f"{actor} {action}d the request{step_note}" + (f": {note}" if note else ""),
    )
    repository.add_audit_event(
        session, record.id, Step.FINAL_ACTION, actor,
        f"final action: {record.final_action} by {actor}",
    )
    session.flush()
    observability.RESOLUTIONS.labels(action).inc()
    return record
