from finance_crew.config import SpendPolicy
from finance_crew.models import ExpenseRequest
from finance_crew.tools import (
    analyze,
    check_policy,
    detect_duplicate,
    normalize_category,
    run_intake,
)

POLICY = SpendPolicy()


def req(**kw):
    base = dict(id="X1", employee="Test", category="software", amount=100.0, has_receipt=True)
    base.update(kw)
    return ExpenseRequest(**base)


def test_normalize_category_aliases():
    assert normalize_category("Uber") == "travel"
    assert normalize_category("SaaS") == "software"
    assert normalize_category("wombat") == "other"


def test_intake_flags_bad_amount():
    r = run_intake(req(amount=-1))
    assert not r.valid
    assert any("amount" in i for i in r.issues)


def test_intake_valid_request():
    r = run_intake(req())
    assert r.valid
    assert r.normalized_category == "software"


def test_check_policy_over_limit():
    v = check_policy(req(category="meals", amount=250), "meals", POLICY)
    assert any("exceeds" in x for x in v)


def test_check_policy_receipt_required():
    v = check_policy(req(amount=120, has_receipt=False), "software", POLICY)
    assert any("receipt" in x for x in v)


def test_duplicate_detection():
    a = req(id="A", amount=149, employee="Same")
    b = req(id="B", amount=149, employee="Same")
    assert detect_duplicate(b, [a]) is True
    assert detect_duplicate(b, []) is False


def test_analyze_risk_monotonic():
    low = analyze(req(amount=50), "software", POLICY)
    high = analyze(req(amount=5000, has_receipt=False), "software", POLICY)
    assert high.risk_score > low.risk_score
