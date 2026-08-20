"""End-to-end tests over the local engine (default, no key required)."""
import json
from pathlib import Path

from finance_crew.models import Decision
from finance_crew.pipeline import process_batch, process_request


def decide_one(**payload):
    return process_request(payload)


def test_small_compliant_auto_approved():
    r = decide_one(id="A1", employee="E", category="software", amount=149, has_receipt=True)
    assert r.decision is Decision.AUTO_APPROVED
    assert r.engine == "local"


def test_over_human_limit_needs_review():
    r = decide_one(id="A2", employee="E", category="equipment", amount=2500, has_receipt=True)
    assert r.decision is Decision.NEEDS_HUMAN_REVIEW


def test_category_over_limit_needs_review():
    r = decide_one(id="A3", employee="E", category="meals", amount=180, has_receipt=False)
    assert r.decision is Decision.NEEDS_HUMAN_REVIEW
    assert r.analysis.violations


def test_invalid_amount_rejected():
    r = decide_one(id="A4", employee="E", category="software", amount=-5)
    assert r.decision is Decision.REJECTED


def test_compliant_but_above_auto_limit_needs_review():
    # travel $1450 is within the $1500 travel limit but above the $200 auto-approve line.
    r = decide_one(id="A5", employee="E", category="travel", amount=1450, has_receipt=True)
    assert r.decision is Decision.NEEDS_HUMAN_REVIEW


def test_missing_receipt_small_amount_ok():
    # $40 is under the $50 receipt threshold, so no receipt is fine.
    r = decide_one(id="A6", employee="E", category="meals", amount=40, has_receipt=False)
    assert r.decision is Decision.AUTO_APPROVED


def test_batch_flags_duplicate():
    payloads = [
        {"id": "D1", "employee": "Same", "category": "software", "amount": 149, "has_receipt": True},
        {"id": "D2", "employee": "Same", "category": "software", "amount": 149, "has_receipt": True},
    ]
    results = process_batch(payloads)
    assert results[1].analysis.is_possible_duplicate is True
    assert results[1].decision is Decision.NEEDS_HUMAN_REVIEW


def test_sample_data_runs_end_to_end():
    path = Path(__file__).resolve().parents[1] / "sample_data" / "expenses.json"
    results = process_batch(json.loads(path.read_text(encoding="utf-8")))
    assert len(results) == 8
    kinds = {r.decision for r in results}
    # the fixture is designed to exercise every branch
    assert Decision.AUTO_APPROVED in kinds
    assert Decision.NEEDS_HUMAN_REVIEW in kinds
    assert Decision.REJECTED in kinds
