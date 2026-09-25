"""Application service — runs the crew *and* persists the result.

This is the seam between the pure orchestration pipeline (which knows nothing
about storage) and the durable system-of-record. The API calls these
functions so that every decision served over HTTP is also written to the
database inside a single transaction.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from . import repository
from .config import Settings
from .models import ApprovalResult, ExpenseRequest
from .orchestrator import build_orchestrator


def decide_and_store(
    session: Session,
    payload: dict[str, Any],
    history: list[dict[str, Any]] | None = None,
    settings: Settings | None = None,
) -> tuple[ApprovalResult, int]:
    """Process one request and persist it. Returns (result, stored record id).

    The write happens on the caller's session; the surrounding
    :func:`finance_crew.db.session_scope` (or FastAPI dependency) owns the
    commit/rollback, so a failure to persist rolls the whole unit back.
    """
    request = ExpenseRequest.from_dict(payload)
    hist = [ExpenseRequest.from_dict(h) for h in (history or [])]
    orchestrator = build_orchestrator(settings)
    result = orchestrator.process(request, hist)
    record = repository.save_decision(session, request, result)
    return result, record.id


def decide_and_store_batch(
    session: Session,
    payloads: list[dict[str, Any]],
    settings: Settings | None = None,
) -> list[tuple[ApprovalResult, int]]:
    """Process + persist a batch; earlier items act as history for dup checks."""
    orchestrator = build_orchestrator(settings)
    out: list[tuple[ApprovalResult, int]] = []
    seen: list[ExpenseRequest] = []
    for payload in payloads:
        request = ExpenseRequest.from_dict(payload)
        result = orchestrator.process(request, list(seen))
        record = repository.save_decision(session, request, result)
        out.append((result, record.id))
        seen.append(request)
    return out
