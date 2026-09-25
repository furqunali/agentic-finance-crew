"""Persistence-layer tests: repository round-trips, the /decisions API, and
that the Alembic migrations build the schema from scratch."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient

from app import app
from conftest import bearer
from finance_crew import repository
from finance_crew.db import session_scope
from finance_crew.service import decide_and_store

client = TestClient(app, headers=bearer("admin"))
REPO_ROOT = Path(__file__).resolve().parents[1]


def test_decide_and_store_roundtrip():
    payload = {"id": "DB-1", "employee": "Persist Pat", "category": "software",
               "amount": 149, "has_receipt": True}
    with session_scope() as s:
        result, rid = decide_and_store(s, payload)
        assert rid > 0
        assert result.decision.value == "auto_approved"

    # committed and readable in a fresh session
    with session_scope() as s:
        rec = repository.get_by_request_id(s, "DB-1")
        assert rec is not None
        assert rec.employee == "Persist Pat"
        assert rec.decision == "auto_approved"
        assert rec.created_at is not None


def test_list_and_count_filters():
    emp = "Filter Fiona"
    payloads = [
        {"id": "F1", "employee": emp, "category": "software", "amount": 149, "has_receipt": True},
        {"id": "F2", "employee": emp, "category": "equipment", "amount": 2500, "has_receipt": True},
    ]
    with session_scope() as s:
        for p in payloads:
            decide_and_store(s, p)

    with session_scope() as s:
        rows = repository.list_decisions(s, employee=emp)
        assert len(rows) == 2
        # newest first
        assert rows[0].id > rows[1].id
        approved = repository.list_decisions(s, employee=emp, decision="auto_approved")
        assert approved and all(r.decision == "auto_approved" for r in approved)
        assert repository.count_decisions(s) >= 2


def test_rollback_leaves_no_partial_write():
    """A failure inside the transaction must not persist the row."""
    before = None
    with session_scope() as s:
        before = repository.count_decisions(s)
    try:
        with session_scope() as s:
            decide_and_store(s, {"id": "RB-1", "employee": "Rollback Rita",
                                 "category": "software", "amount": 10, "has_receipt": True})
            raise RuntimeError("boom after write, before commit")
    except RuntimeError:
        pass
    with session_scope() as s:
        assert repository.count_decisions(s) == before
        assert repository.get_by_request_id(s, "RB-1") is None


def test_approve_persists_and_is_listable():
    resp = client.post(
        "/approve",
        json={"id": "API-DB-1", "employee": "Api Amy", "category": "software",
              "amount": 149, "has_receipt": True},
    )
    assert resp.status_code == 200
    rid = resp.json()["record_id"]
    assert isinstance(rid, int) and rid > 0

    got = client.get(f"/decisions/{rid}")
    assert got.status_code == 200
    assert got.json()["request_id"] == "API-DB-1"

    listed = client.get("/decisions", params={"employee": "Api Amy"})
    assert listed.status_code == 200
    body = listed.json()
    assert body["count"] >= 1
    assert any(item["request_id"] == "API-DB-1" for item in body["items"])


def test_batch_persists_every_row():
    resp = client.post(
        "/approve/batch",
        json=[
            {"id": "API-B1", "employee": "Batch Bob", "category": "software", "amount": 149, "has_receipt": True},
            {"id": "API-B2", "employee": "Batch Bob", "category": "meals", "amount": 180},
        ],
    )
    assert resp.status_code == 200
    ids = [row["record_id"] for row in resp.json()]
    assert len(ids) == 2 and all(i > 0 for i in ids)


def test_get_missing_decision_returns_404():
    resp = client.get("/decisions/99999999")
    assert resp.status_code == 404


def test_alembic_upgrade_head_builds_schema(tmp_path):
    """The migration system alone (no create_all) produces the decisions table."""
    pytest.importorskip("alembic")
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, inspect

    db_file = tmp_path / "migrated.db"
    url = f"sqlite:///{db_file}"

    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "migrations"))

    prev = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url  # env.py reads this
    try:
        command.upgrade(cfg, "head")
        engine = create_engine(url)
        try:
            tables = inspect(engine).get_table_names()
        finally:
            engine.dispose()
        assert "decisions" in tables
        assert "audit_events" in tables  # 0002 audit-trail migration applied
    finally:
        if prev is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = prev
