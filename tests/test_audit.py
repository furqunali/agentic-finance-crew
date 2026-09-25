"""Audit-trail + human-in-the-loop workflow tests."""
from __future__ import annotations

import pytest

pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient

from app import app
from finance_crew import repository
from finance_crew.db import session_scope
from finance_crew.errors import ConflictError
from finance_crew.records import Status, Step
from finance_crew.service import decide_and_store, resolve_decision

client = TestClient(app)

AUTO = {"id": "AUD-AUTO", "employee": "Auto Ann", "category": "software",
        "amount": 149, "has_receipt": True}
REVIEW = {"id": "AUD-REV", "employee": "Review Ray", "category": "software",
          "amount": 1450, "has_receipt": True}  # over software limit -> needs review


def _create(payload):
    resp = client.post("/approve", json=payload)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_auto_decision_writes_full_machine_trail():
    body = _create(AUTO)
    assert body["decision"] == "auto_approved"
    assert body["status"] == Status.AUTO_APPROVED
    assert body["final_action"] == "approved"
    assert body["ai_recommendation"] == "auto_approved"
    assert body["model_version"].startswith("local@")
    assert body["rules_fired"] == []

    trail = client.get(f"/decisions/{body['record_id']}/audit").json()["trail"]
    steps = [e["step"] for e in trail]
    assert steps == [
        Step.REQUEST_RECEIVED, Step.AI_REASONING,
        Step.POLICY_EVALUATION, Step.DECISION, Step.FINAL_ACTION,
    ]


def test_review_item_is_pending_and_queued():
    body = _create(REVIEW)
    assert body["decision"] == "needs_human_review"
    assert body["status"] == Status.PENDING_REVIEW
    assert body["final_action"] == "pending"
    assert body["rules_fired"]  # at least one rule fired

    queue = client.get("/review-queue").json()
    assert any(item["id"] == body["record_id"] for item in queue["items"])
    # the machine trail stops at DECISION — no final action yet
    trail = client.get(f"/decisions/{body['record_id']}/audit").json()["trail"]
    assert Step.FINAL_ACTION not in [e["step"] for e in trail]


def test_human_approve_resolves_without_mutating_ai_verdict():
    rid = _create({**REVIEW, "id": "AUD-APP"})["record_id"]
    resp = client.post(f"/decisions/{rid}/approve",
                       json={"actor": "m.khan", "note": "receipt verified"})
    assert resp.status_code == 200
    rec = resp.json()
    assert rec["status"] == Status.HUMAN_APPROVED
    assert rec["final_action"] == "approved"
    assert rec["resolved_by"] == "m.khan"
    assert rec["resolved_at"] is not None
    # the ORIGINAL machine verdict is preserved, not overwritten
    assert rec["decision"] == "needs_human_review"
    assert rec["ai_recommendation"] == "needs_human_review"

    trail = client.get(f"/decisions/{rid}/audit").json()["trail"]
    steps = [e["step"] for e in trail]
    assert steps[-2:] == [Step.HUMAN_REVIEW, Step.FINAL_ACTION]
    assert any("m.khan" in e["actor"] for e in trail)


def test_human_reject_path():
    rid = _create({**REVIEW, "id": "AUD-REJ"})["record_id"]
    resp = client.post(f"/decisions/{rid}/reject", json={"actor": "auditor.jo"})
    assert resp.status_code == 200
    assert resp.json()["status"] == Status.HUMAN_REJECTED
    assert resp.json()["final_action"] == "rejected"


def test_cannot_resolve_an_auto_decided_item():
    rid = _create({**AUTO, "id": "AUD-AUTO2"})["record_id"]
    resp = client.post(f"/decisions/{rid}/approve", json={"actor": "m.khan"})
    assert resp.status_code == 409  # ConflictError


def test_resolving_missing_decision_404():
    resp = client.post("/decisions/99999999/approve", json={"actor": "m.khan"})
    assert resp.status_code == 404


def test_resolving_twice_conflicts():
    rid = _create({**REVIEW, "id": "AUD-TWICE"})["record_id"]
    assert client.post(f"/decisions/{rid}/approve", json={"actor": "a"}).status_code == 200
    assert client.post(f"/decisions/{rid}/reject", json={"actor": "b"}).status_code == 409


def test_service_level_conflict_and_immutability():
    payload = {**REVIEW, "id": "AUD-SVC"}
    with session_scope() as s:
        _, rid = decide_and_store(s, payload)
    with session_scope() as s:
        rec = resolve_decision(s, rid, "approve", "manager.mo", "ok")
        assert rec.status == Status.HUMAN_APPROVED
    # second resolution attempt must conflict
    with session_scope() as s:
        with pytest.raises(ConflictError):
            resolve_decision(s, rid, "reject", "someone", "")


def test_global_audit_log_endpoint():
    _create({**AUTO, "id": "AUD-LOG"})
    resp = client.get("/audit", params={"limit": 10})
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] >= 1
    assert {"step", "actor", "detail", "decision_id"} <= set(body["items"][0])
