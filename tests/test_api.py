"""API-level tests over the FastAPI app, focused on happy paths *and* the
error/edge handling added for production robustness.

Uses FastAPI's TestClient (httpx under the hood, installed via the [dev] extra).
"""
import pytest

pytest.importorskip("httpx")

from fastapi.testclient import TestClient

from app import app

client = TestClient(app)


def test_health_reports_engine():
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["engine"] == "local"


def test_approve_happy_path():
    resp = client.post(
        "/approve",
        json={"id": "EXP-1", "employee": "A. Rivera", "category": "software",
              "amount": 149.0, "has_receipt": True},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["decision"] == "auto_approved"
    assert body["engine"] == "local"


def test_approve_rejects_missing_required_field():
    # No employee -> pydantic 422 before any orchestration runs.
    resp = client.post("/approve", json={"id": "EXP-2", "category": "software", "amount": 10})
    assert resp.status_code == 422


def test_approve_rejects_blank_id():
    resp = client.post(
        "/approve",
        json={"id": "", "employee": "E", "category": "software", "amount": 10},
    )
    assert resp.status_code == 422


def test_approve_rejects_non_numeric_amount():
    resp = client.post(
        "/approve",
        json={"id": "EXP-3", "employee": "E", "category": "software", "amount": "not-a-number"},
    )
    assert resp.status_code == 422


def test_batch_happy_path():
    resp = client.post(
        "/approve/batch",
        json=[
            {"id": "B1", "employee": "E", "category": "software", "amount": 149, "has_receipt": True},
            {"id": "B2", "employee": "E", "category": "meals", "amount": 180},
        ],
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 2
    assert body[0]["decision"] == "auto_approved"
    assert body[1]["decision"] == "needs_human_review"


def test_empty_batch_is_rejected():
    resp = client.post("/approve/batch", json=[])
    assert resp.status_code == 422
    assert "at least one" in resp.json()["detail"]["message"]


def test_oversized_batch_is_rejected():
    payload = [
        {"id": f"X{i}", "employee": "E", "category": "software", "amount": 10, "has_receipt": True}
        for i in range(501)
    ]
    resp = client.post("/approve/batch", json=payload)
    assert resp.status_code == 422
    assert "batch too large" in resp.json()["detail"]["message"]
