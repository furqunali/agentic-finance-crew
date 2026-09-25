"""Observability tests: /metrics endpoint, per-decision latency, cost estimate."""
from __future__ import annotations

import pytest

pytest.importorskip("prometheus_client")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient

from app import app
from conftest import bearer
from finance_crew.observability import estimate_cost, normalize_path

client = TestClient(app, headers=bearer("admin"))
public = TestClient(app)  # no auth — /metrics is public


def test_metrics_endpoint_is_public_and_prometheus_format():
    resp = public.get("/metrics")
    assert resp.status_code == 200
    assert "text/plain" in resp.headers["content-type"]
    body = resp.text
    assert "afc_decisions_total" in body
    assert "afc_http_requests_total" in body


def test_decision_records_latency_and_usage_fields():
    resp = client.post("/approve", json={"id": "OBS-1", "employee": "Obs Olly",
                                         "category": "software", "amount": 149, "has_receipt": True})
    assert resp.status_code == 200
    rec = resp.json()
    assert isinstance(rec["latency_ms"], (int, float)) and rec["latency_ms"] >= 0
    assert rec["tokens"] == 0            # local engine uses no LLM
    assert rec["cost_usd"] == 0.0


def test_decision_counter_increments():
    before = public.get("/metrics").text
    client.post("/approve", json={"id": "OBS-2", "employee": "Obs Olly",
                                  "category": "software", "amount": 149, "has_receipt": True})
    after = public.get("/metrics").text
    # the auto_approved/local counter line must be present after a decision
    assert 'afc_decisions_total{decision="auto_approved",engine="local"}' in after
    # and the metric family existed before too (process-global registry)
    assert "afc_decisions_total" in before


def test_estimate_cost():
    assert estimate_cost("gpt-4o-mini", 0) == 0.0          # no tokens -> no cost
    assert estimate_cost("gpt-4o-mini", 1000) > 0.0
    assert estimate_cost("unknown-model", 1000) > 0.0      # falls back to default price


def test_normalize_path_bounds_cardinality():
    assert normalize_path("/decisions/7/audit") == "/decisions/{id}/audit"
    assert normalize_path("/decisions/12345") == "/decisions/{id}"
    assert normalize_path("/health") == "/health"
