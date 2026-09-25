"""Tests for the last-resort error handling: an unexpected server-side error
becomes a clean, structured 500 (never a leaked stack trace)."""
from __future__ import annotations

import pytest

pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient

from app import app
from conftest import bearer
from finance_crew import repository

# Don't let the test client re-raise server exceptions — we want the HTTP 500.
client = TestClient(app, headers=bearer("admin"), raise_server_exceptions=False)


def test_unexpected_error_becomes_structured_500(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("simulated database blow-up")
    monkeypatch.setattr(repository, "list_decisions", boom)

    resp = client.get("/decisions")
    assert resp.status_code == 500
    body = resp.json()
    # structured shape, and the internal message is NOT leaked
    assert body["error"]["status"] == 500
    assert body["error"]["message"] == "internal server error"
    assert "blow-up" not in resp.text


def test_normal_requests_still_ok_after_error():
    # a valid request after the patched test is restored still works
    r = client.post("/approve", json={"id": "EH-1", "employee": "e",
                                      "category": "software", "amount": 149, "has_receipt": True})
    assert r.status_code == 200
