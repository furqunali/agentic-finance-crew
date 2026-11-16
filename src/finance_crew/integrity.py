"""Tamper evidence for the system of record.

Two SHA-256 constructions make silent edits detectable:

* **Record digest** — each decision row stores ``record_hash``, a digest of its
  write-once fields (who, what, how much, the machine verdict, the rules fired,
  the model version). Changing any of them breaks the digest.
* **Hash-chained audit trail** — every audit event stores ``prev_hash`` and
  ``hash = SHA256(prev_hash ‖ event)``. The first event of a decision chains
  from that decision's ``record_hash``, so the trail is anchored to the record.
  The decision row keeps the latest link in ``head_hash``, so deleting events
  from the end (truncation) is caught as well as edits and deletions in the
  middle.

:func:`verify` re-derives everything and reports the first broken link per
decision, plus a **ledger root** — one digest over every decision's head hash.
Exporting that root to storage the database admin can't rewrite (a ticket, an
email, a WORM bucket) is what turns "tamper-evident inside the DB" into
"tamper-evident against the DB admin": anyone who recomputes all hashes would
still produce a different root than the one recorded outside.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

GENESIS = "0" * 64


def norm_ts(value: datetime | None) -> str:
    """A timestamp in one canonical form, whatever the DB driver hands back
    (SQLite returns naive UTC, Postgres aware)."""
    if value is None:
        return ""
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value.isoformat(timespec="microseconds")


def _sha(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def record_digest(record: Any) -> str:
    """Digest of a decision's write-once fields."""
    return _sha({
        "request_id": record.request_id, "employee": record.employee,
        "category": record.category, "amount": round(float(record.amount), 2),
        "currency": record.currency, "decision": record.decision,
        "ai_recommendation": record.ai_recommendation, "rules_fired": record.rules_fired,
        "risk_score": int(record.risk_score), "model_version": record.model_version,
        "requested_by": record.requested_by, "approvals_required": int(record.approvals_required or 1),
    })


def event_digest(prev_hash: str, event: Any) -> str:
    """Link hash for one audit event, chained from the previous link."""
    return _sha({
        "prev": prev_hash, "decision_id": event.decision_id, "step": event.step,
        "actor": event.actor, "detail": event.detail, "at": norm_ts(event.created_at),
    })


def verify(session: Any) -> dict[str, Any]:
    """Re-derive every digest and chain link. Returns a JSON-able report."""
    from sqlalchemy import select

    from .records import AuditEvent, DecisionRecord

    problems: list[dict[str, Any]] = []
    heads: list[str] = []
    n_records = n_events = 0
    for record in session.scalars(select(DecisionRecord).order_by(DecisionRecord.id)):
        n_records += 1
        if record.record_hash != record_digest(record):
            problems.append({"decision_id": record.id, "issue": "decision fields were changed after they were written"})
        expected_prev = record.record_hash or GENESIS
        events = list(session.scalars(
            select(AuditEvent).where(AuditEvent.decision_id == record.id).order_by(AuditEvent.id)))
        for ev in events:
            n_events += 1
            if ev.prev_hash != expected_prev:
                problems.append({"decision_id": record.id, "event_id": ev.id,
                                 "issue": "chain broken before this event (an event was removed or reordered)"})
            if ev.hash != event_digest(ev.prev_hash or "", ev):
                problems.append({"decision_id": record.id, "event_id": ev.id,
                                 "issue": "event content was changed after it was written"})
            expected_prev = ev.hash or ""
        if (record.head_hash or "") != expected_prev:
            problems.append({"decision_id": record.id,
                             "issue": "audit trail is shorter or longer than recorded (events removed or added)"})
        resolved = record.status in ("human_approved", "human_rejected")
        if resolved and not (events and events[-1].step == "final_action" and events[-1].actor == record.resolved_by):
            problems.append({"decision_id": record.id,
                             "issue": "human resolution does not match the audit trail"})
        heads.append(f"{record.id}:{record.head_hash or ''}")
    root = hashlib.sha256("\n".join(heads).encode("utf-8")).hexdigest()
    return {"ok": not problems, "decisions_checked": n_records, "events_checked": n_events,
            "ledger_root": root, "problems": problems}


def backfill(session: Any) -> int:
    """Give rows written before tamper evidence existed their digests and chain
    links (and the identity key used for history lookups). Idempotent: only
    rows still missing a hash are touched. Returns the number of decisions fixed."""
    from sqlalchemy import select

    from .records import AuditEvent, DecisionRecord
    from .tools import person_key

    fixed = 0
    for record in session.scalars(select(DecisionRecord).where(
            (DecisionRecord.record_hash == "") | (DecisionRecord.record_hash.is_(None)))):
        if not record.employee_key:
            record.employee_key = person_key(record.employee)
        if not record.approvals_required:
            record.approvals_required = 1
        record.record_hash = record_digest(record)
        prev = record.record_hash
        for ev in session.scalars(select(AuditEvent).where(
                AuditEvent.decision_id == record.id).order_by(AuditEvent.id)):
            ev.prev_hash = prev
            ev.hash = event_digest(prev, ev)
            prev = ev.hash
        record.head_hash = prev
        fixed += 1
    session.flush()
    return fixed
