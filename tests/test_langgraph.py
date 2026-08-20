"""LangGraph engine tests — proves it produces identical verdicts to the local
engine (same tools + guardrail), just orchestrated as a state graph.

Skips automatically if langgraph isn't installed, so the base test run stays
dependency-light; CI installs the [dev] extra so this actually executes.
"""
import json
from pathlib import Path

import pytest

pytest.importorskip("langgraph")

from finance_crew.config import Settings
from finance_crew.models import Decision
from finance_crew.pipeline import process_batch, process_request

LG = Settings(engine="langgraph")


def test_langgraph_engine_selected():
    r = process_request(
        {"id": "L1", "employee": "E", "category": "software", "amount": 149, "has_receipt": True},
        settings=LG,
    )
    assert r.engine == "langgraph"
    assert r.decision is Decision.AUTO_APPROVED


def test_langgraph_matches_local_on_sample_batch():
    path = Path(__file__).resolve().parents[1] / "sample_data" / "expenses.json"
    payloads = json.loads(path.read_text(encoding="utf-8"))
    local = process_batch(payloads, Settings(engine="local"))
    lg = process_batch(payloads, LG)
    assert [r.decision for r in lg] == [r.decision for r in local]
    assert all(r.engine == "langgraph" for r in lg)


def test_langgraph_flags_violation():
    r = process_request(
        {"id": "L2", "employee": "E", "category": "meals", "amount": 180, "has_receipt": False},
        settings=LG,
    )
    assert r.decision is Decision.NEEDS_HUMAN_REVIEW
    assert r.analysis.violations
