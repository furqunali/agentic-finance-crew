"""Dual control, tamper-evident audit trail, and history-aware checks."""
from __future__ import annotations

import pytest

pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import app
from conftest import bearer
from finance_crew import integrity
from finance_crew.config import Settings
from finance_crew.db import Base
from finance_crew.errors import ForbiddenError
from finance_crew.records import AuditEvent, DecisionRecord, Status
from finance_crew.service import decide_and_store, resolve_decision

employee = TestClient(app, headers=bearer("employee"))
manager = TestClient(app, headers=bearer("manager"))
admin = TestClient(app, headers=bearer("admin"))
auditor = TestClient(app, headers=bearer("auditor"))

BIG = {"category": "equipment", "amount": 6200, "has_receipt": True}     # > $5,000 -> dual control
MID = {"category": "travel", "amount": 900, "has_receipt": True}         # review, single approver


def _submit(client, payload):
    resp = client.post("/approve", json=payload)
    assert resp.status_code == 200, resp.text
    return resp.json()


# --- Dual control -----------------------------------------------------------
def test_high_value_item_needs_two_different_approvers():
    rec = _submit(employee, {**BIG, "id": "DC-1", "employee": "Dual Dee"})
    assert rec["approvals_required"] == 2 and rec["approvals_received"] == 0
    rid = rec["record_id"]

    first = manager.post(f"/decisions/{rid}/approve", json={"note": "quote checked"}).json()
    assert first["status"] == Status.PENDING_REVIEW          # still waiting
    assert first["approvals_received"] == 1 and first["first_approved_by"] == "manager"
    assert any(i["id"] == rid for i in manager.get("/review-queue").json()["items"])

    again = manager.post(f"/decisions/{rid}/approve", json={})
    assert again.status_code == 403 and "dual control" in again.json()["error"]["message"]

    final = admin.post(f"/decisions/{rid}/approve", json={}).json()
    assert final["status"] == Status.HUMAN_APPROVED and final["resolved_by"] == "admin"
    assert final["approvals_received"] == 2
    steps = [e["detail"] for e in admin.get(f"/decisions/{rid}/audit").json()["trail"]]
    assert any("approval 1 of 2" in d for d in steps) and any("approval 2 of 2" in d for d in steps)


def test_submitter_cannot_be_either_approver():
    rid = _submit(manager, {**BIG, "id": "DC-2", "employee": "Dual Dan"})["record_id"]
    assert manager.post(f"/decisions/{rid}/approve", json={}).status_code == 403


def test_one_reject_ends_a_dual_control_item():
    rid = _submit(employee, {**BIG, "id": "DC-3", "employee": "Dual Dot"})["record_id"]
    manager.post(f"/decisions/{rid}/approve", json={})
    rec = admin.post(f"/decisions/{rid}/reject", json={"note": "no budget"}).json()
    assert rec["status"] == Status.HUMAN_REJECTED and rec["final_action"] == "rejected"


def test_below_threshold_needs_a_single_approver():
    rec = _submit(employee, {**MID, "id": "DC-4", "employee": "Single Sam"})
    assert rec["approvals_required"] == 1
    out = manager.post(f"/decisions/{rec['record_id']}/approve", json={}).json()
    assert out["status"] == Status.HUMAN_APPROVED


# --- Tamper evidence --------------------------------------------------------
@pytest.fixture()
def db():
    """An isolated in-memory database, so tampering never touches the shared one."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        settings = Settings(engine="local")
        _, a = decide_and_store(s, {"id": "T-1", "employee": "Tam", "category": "software",
                                    "amount": 120, "has_receipt": True}, settings=settings, requested_by="emp")
        _, b = decide_and_store(s, {"id": "T-2", "employee": "Tam", "category": "travel",
                                    "amount": 900, "has_receipt": True}, settings=settings, requested_by="emp")
        resolve_decision(s, b, "approve", "manager")
        s.commit()
        yield s, a, b


def test_untouched_ledger_verifies(db):
    s, _, _ = db
    rep = integrity.verify(s)
    assert rep["ok"] and rep["decisions_checked"] == 2 and rep["events_checked"] >= 10
    assert len(rep["ledger_root"]) == 64


def test_editing_a_decision_is_detected(db):
    s, a, _ = db
    s.get(DecisionRecord, a).amount = 99999
    s.flush()
    rep = integrity.verify(s)
    assert not rep["ok"] and rep["problems"][0]["decision_id"] == a


def test_editing_an_audit_event_is_detected(db):
    s, a, _ = db
    ev = s.scalars(select(AuditEvent).where(AuditEvent.decision_id == a)).first()
    ev.detail = "nothing to see here"
    s.flush()
    assert any("content was changed" in p["issue"] for p in integrity.verify(s)["problems"])


def test_deleting_a_middle_event_is_detected(db):
    s, a, _ = db
    events = list(s.scalars(select(AuditEvent).where(AuditEvent.decision_id == a).order_by(AuditEvent.id)))
    s.delete(events[1])
    s.flush()
    assert any("chain broken" in p["issue"] for p in integrity.verify(s)["problems"])


def test_truncating_the_trail_is_detected(db):
    s, _, b = db
    events = list(s.scalars(select(AuditEvent).where(AuditEvent.decision_id == b).order_by(AuditEvent.id)))
    s.delete(events[-1])
    s.flush()
    issues = " ".join(p["issue"] for p in integrity.verify(s)["problems"])
    assert "shorter or longer" in issues


def test_rewriting_who_approved_is_detected(db):
    s, _, b = db
    s.get(DecisionRecord, b).resolved_by = "someone-else"
    s.flush()
    assert any("human resolution" in p["issue"] for p in integrity.verify(s)["problems"])


def test_backfill_gives_legacy_rows_valid_chains(db):
    s, a, _ = db
    rec = s.get(DecisionRecord, a)
    rec.record_hash = ""
    for ev in rec.events:
        ev.prev_hash = ev.hash = ""
    s.flush()
    assert integrity.backfill(s) == 1
    assert integrity.verify(s)["ok"]


def test_verify_endpoint_is_auditor_only():
    body = auditor.get("/audit/verify").json()
    assert body["ok"] is True and body["decisions_checked"] > 0
    assert employee.get("/audit/verify").status_code == 403


# --- History-aware checks ---------------------------------------------------
def test_duplicate_across_separate_calls_is_caught():
    _submit(employee, {"id": "H-1", "employee": "Hist Hal", "category": "software", "amount": 133, "has_receipt": True})
    second = _submit(employee, {"id": "H-2", "employee": "  hist HAL", "category": "saas", "amount": 133, "has_receipt": True})
    assert second["decision"] == "needs_human_review"
    assert "possible duplicate of an earlier request" in second["rules_fired"]


def test_split_purchase_across_separate_calls_is_caught():
    day = "2026-10-05"
    first = _submit(employee, {"id": "H-3", "employee": "Split Sue", "category": "software",
                               "amount": 120, "has_receipt": True, "date": day})
    second = _submit(employee, {"id": "H-4", "employee": "Split Sue", "category": "software",
                                "amount": 110, "has_receipt": True, "date": day})
    assert first["decision"] == "auto_approved"
    assert any("split purchase" in r for r in second["rules_fired"])


def test_lookback_zero_disables_stored_history(db):
    s, _, _ = db
    off = Settings(engine="local", history_lookback_days=0)
    r, _ = decide_and_store(s, {"id": "T-3", "employee": "Tam", "category": "software",
                                "amount": 120, "has_receipt": True}, settings=off)
    assert not r.analysis.is_possible_duplicate


def test_dual_control_same_person_check_respects_single_user_mode(db):
    s, _, _ = db
    _, rid = decide_and_store(s, {"id": "T-4", "employee": "Big Bo", "category": "equipment",
                                  "amount": 7000, "has_receipt": True}, settings=Settings(engine="local"),
                              requested_by="emp")
    resolve_decision(s, rid, "approve", "admin")
    with pytest.raises(ForbiddenError):
        resolve_decision(s, rid, "approve", "admin")
    rec = resolve_decision(s, rid, "approve", "admin", enforce_separation_of_duties=False)
    assert rec.status == Status.HUMAN_APPROVED
