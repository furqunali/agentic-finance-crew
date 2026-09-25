"""Authentication + RBAC tests: login, token validation, and per-role gating."""
from __future__ import annotations

import pytest

pytest.importorskip("jwt")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient

from app import app
from conftest import bearer

noauth = TestClient(app)
admin = TestClient(app, headers=bearer("admin"))
manager = TestClient(app, headers=bearer("manager"))
auditor = TestClient(app, headers=bearer("auditor"))
employee = TestClient(app, headers=bearer("employee"))

REVIEW = {"id": "AUTH-REV", "employee": "x", "category": "software",
          "amount": 1450, "has_receipt": True}  # -> needs human review


# --- public + login ---------------------------------------------------------
def test_health_is_public():
    assert noauth.get("/health").status_code == 200


def test_protected_endpoint_requires_token():
    assert noauth.get("/auth/me").status_code == 401
    assert noauth.post("/approve", json={"id": "x", "employee": "e",
                                         "category": "software", "amount": 10}).status_code == 401


def test_login_success_and_failure():
    ok = noauth.post("/auth/login", data={"username": "admin", "password": "pw-admin"})
    assert ok.status_code == 200
    body = ok.json()
    assert body["token_type"] == "bearer" and body["role"] == "admin" and body["access_token"]

    bad = noauth.post("/auth/login", data={"username": "admin", "password": "wrong"})
    assert bad.status_code == 401


def test_login_token_authorizes_requests():
    token = noauth.post("/auth/login", data={"username": "manager",
                                             "password": "pw-manager"}).json()["access_token"]
    me = noauth.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["role"] == "finance_manager"


def test_garbage_token_rejected():
    assert noauth.get("/auth/me", headers={"Authorization": "Bearer not.a.jwt"}).status_code == 401


# --- role gating -------------------------------------------------------------
def test_employee_can_submit_but_not_review_or_audit():
    assert employee.post("/approve", json={"id": "E1", "employee": "e",
                                           "category": "software", "amount": 10,
                                           "has_receipt": True}).status_code == 200
    assert employee.get("/decisions").status_code == 403       # audit-only
    assert employee.get("/review-queue").status_code == 403     # review-only
    assert employee.get("/auth/users").status_code == 403       # admin-only


def test_auditor_can_read_but_not_approve():
    assert auditor.get("/decisions").status_code == 200
    assert auditor.get("/audit").status_code == 200
    rid = admin.post("/approve", json={**REVIEW, "id": "AUTH-AUD"}).json()["record_id"]
    assert auditor.post(f"/decisions/{rid}/approve", json={}).status_code == 403


def test_manager_can_review_but_not_manage_users():
    rid = admin.post("/approve", json={**REVIEW, "id": "AUTH-MGR"}).json()["record_id"]
    resp = manager.post(f"/decisions/{rid}/approve", json={"note": "ok by manager"})
    assert resp.status_code == 200
    assert resp.json()["resolved_by"] == "manager"
    assert manager.get("/auth/users").status_code == 403  # admin-only


def test_admin_can_manage_users():
    # list
    assert admin.get("/auth/users").status_code == 200
    # create
    created = admin.post("/auth/register", json={
        "username": "new.analyst", "password": "s3cret-pw", "role": "auditor",
        "full_name": "New Analyst"})
    assert created.status_code == 201
    assert created.json()["role"] == "auditor"
    # duplicate -> 409
    dup = admin.post("/auth/register", json={"username": "new.analyst",
                                             "password": "s3cret-pw", "role": "auditor"})
    assert dup.status_code == 409
    # unknown role -> 422
    bad = admin.post("/auth/register", json={"username": "who", "password": "s3cret-pw",
                                             "role": "wizard"})
    assert bad.status_code == 422


def test_non_admin_cannot_register_users():
    resp = manager.post("/auth/register", json={"username": "sneaky",
                                                "password": "s3cret-pw", "role": "admin"})
    assert resp.status_code == 403
