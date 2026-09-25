"""Evaluation-harness tests — lock the safety guarantee (0 false approvals) in CI."""
from __future__ import annotations

from finance_crew.config import SpendPolicy
from finance_crew.evaluation import (
    AUTO,
    REJECT,
    REVIEW,
    evaluate,
    expected_outcome,
    generate_cases,
)


def test_generation_is_deterministic_and_sized():
    a = generate_cases(200, seed=5)
    b = generate_cases(200, seed=5)
    assert len(a) == 200
    assert [c.payload for c in a] == [c.payload for c in b]           # reproducible
    assert generate_cases(200, seed=6)[0].payload != a[0].payload      # seed matters


def test_independent_oracle_sanity():
    p = SpendPolicy()
    auto = {"id": "x", "employee": "e", "category": "software", "amount": 149, "has_receipt": True}
    over = {"id": "x", "employee": "e", "category": "meals", "amount": 500, "has_receipt": True}
    bad = {"id": "x", "employee": "e", "category": "software", "amount": 0, "has_receipt": True}
    assert expected_outcome(auto, p, False)[0] == AUTO
    assert expected_outcome(over, p, False)[0] == REVIEW      # over meals limit
    assert expected_outcome(bad, p, False)[0] == REJECT
    assert expected_outcome(auto, p, True)[0] == REVIEW       # duplicate -> escalate


def test_benchmark_is_accurate_and_safe():
    report = evaluate(n=400, seed=1)
    m = report.metrics
    assert m["total_cases"] == 400
    assert m["accuracy"] == 1.0                    # matches the independent oracle
    assert m["false_approvals"] == 0               # never auto-approve what policy blocks
    assert m["false_rejections"] == 0
    assert not report.mismatches
    # detection quality
    assert m["violation_detection"]["f1"] == 1.0
    assert m["duplicate_detection"]["recall"] == 1.0
    # sane distribution + perf recorded
    assert 0.0 < m["escalation_rate"] < 1.0
    assert m["auto_approval_rate"] > 0.0
    assert m["latency_ms"]["mean"] >= 0.0
    assert m["tokens_total"] == 0 and m["cost_usd_total"] == 0.0
