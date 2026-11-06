"""Rate-limiter tests: token-bucket maths (with a fake clock), client
identification, env config, and the API's 429 + Retry-After path with the
Prometheus counter."""

from __future__ import annotations

import pytest

pytest.importorskip("httpx")

from conftest import bearer
from fastapi.testclient import TestClient

from app import app
from finance_crew.ratelimit import RateLimiter, client_key


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


# --- Token bucket ----------------------------------------------------------------
def test_burst_then_refuse_then_refill():
    clock = FakeClock()
    rl = RateLimiter(per_minute=60, burst=3, clock=clock)  # 1 token/second
    assert [rl.check("c").allowed for _ in range(3)] == [True, True, True]
    refused = rl.check("c")
    assert not refused.allowed
    assert refused.retry_after == 1
    assert refused.remaining == 0

    clock.now += 1.0  # one token refilled
    assert rl.check("c").allowed
    assert not rl.check("c").allowed


def test_refill_is_capped_at_burst():
    clock = FakeClock()
    rl = RateLimiter(per_minute=60, burst=2, clock=clock)
    rl.check("c")
    clock.now += 3600  # an hour idle never banks more than the burst
    assert [rl.check("c").allowed for _ in range(3)] == [True, True, False]


def test_retry_after_reflects_slow_rates():
    clock = FakeClock()
    rl = RateLimiter(per_minute=2, burst=1, clock=clock)  # one token per 30s
    assert rl.check("c").allowed
    assert rl.check("c").retry_after == 30
    clock.now += 20
    assert rl.check("c").retry_after == 10


def test_clients_have_independent_buckets():
    rl = RateLimiter(per_minute=60, burst=1, clock=FakeClock())
    assert rl.check("a").allowed
    assert not rl.check("a").allowed
    assert rl.check("b").allowed


def test_lru_eviction_bounds_memory():
    rl = RateLimiter(per_minute=60, burst=1, max_clients=2, clock=FakeClock())
    for client in ("a", "b", "c"):
        rl.check(client)
    assert len(rl._buckets) == 2
    assert "a" not in rl._buckets  # least-recently-seen evicted


def test_disabled_limiter_always_allows():
    rl = RateLimiter(per_minute=60, burst=1, enabled=False, clock=FakeClock())
    assert all(rl.check("c").allowed for _ in range(50))


def test_invalid_configuration_rejected():
    with pytest.raises(ValueError):
        RateLimiter(per_minute=0)
    with pytest.raises(ValueError):
        RateLimiter(burst=0)


def test_from_env(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "120")
    monkeypatch.setenv("RATE_LIMIT_BURST", "7")
    monkeypatch.setenv("RATE_LIMIT_TRUST_PROXY", "1")
    rl = RateLimiter.from_env()
    assert rl.enabled and rl.trust_proxy
    assert rl.capacity == 7 and rl.rate == pytest.approx(2.0)

    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "not-a-number")
    monkeypatch.setenv("RATE_LIMIT_BURST", "-3")
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "off")
    rl = RateLimiter.from_env()
    assert not rl.enabled
    assert rl.capacity == 20 and rl.rate == pytest.approx(1.0)  # safe defaults


# --- Client identification -----------------------------------------------------------
def test_client_key_precedence():
    kw = {"forwarded_for": "203.0.113.9, 10.0.0.1", "client_host": "10.0.0.1", "trust_proxy": False}
    assert client_key(user="ann", api_key="k", **kw) == "user:ann"
    key = client_key(user=None, api_key="secret-key", **kw)
    assert key.startswith("key:") and "secret-key" not in key
    assert client_key(user=None, api_key=None, **kw) == "ip:10.0.0.1"  # XFF ignored by default
    kw["trust_proxy"] = True
    assert client_key(user=None, api_key=None, **kw) == "ip:203.0.113.9"
    assert (
        client_key(user=None, api_key=None, forwarded_for=None, client_host=None, trust_proxy=False)
        == "ip:unknown"
    )


# --- API: 429 path ---------------------------------------------------------------------
EXPENSE = {"id": "RL-1", "employee": "Rita Rate", "category": "software", "amount": 49, "has_receipt": True}


@pytest.fixture()
def limited_app():
    """Swap in an enabled, tight limiter (burst 2, effectively no refill)."""
    original = app.state.rate_limiter
    app.state.rate_limiter = RateLimiter(per_minute=0.06, burst=2)  # 1 token / 1000s
    try:
        yield app
    finally:
        app.state.rate_limiter = original


def test_api_returns_429_with_retry_after(limited_app):
    client = TestClient(limited_app, headers=bearer("employee"))
    ok1 = client.post("/approve", json={**EXPENSE, "id": "RL-1"})
    ok2 = client.post("/approve", json={**EXPENSE, "id": "RL-2"})
    assert ok1.status_code == ok2.status_code == 200
    assert ok1.headers["RateLimit-Limit"] == "2"
    assert ok2.headers["RateLimit-Remaining"] == "0"

    limited = client.post("/approve", json={**EXPENSE, "id": "RL-3"})
    assert limited.status_code == 429
    assert int(limited.headers["Retry-After"]) >= 1
    body = limited.json()
    assert body["error"]["status"] == 429
    assert "rate limit exceeded" in body["error"]["message"]

    metrics = TestClient(limited_app).get("/metrics").text
    assert 'afc_rate_limited_total{method="POST",path="/approve"}' in metrics
    assert 'afc_http_requests_total{method="POST",path="/approve",status="429"}' in metrics


def test_limit_is_per_user(limited_app):
    employee = TestClient(limited_app, headers=bearer("employee"))
    manager = TestClient(limited_app, headers=bearer("manager"))
    for i in range(2):
        assert employee.post("/approve", json={**EXPENSE, "id": f"RL-E{i}"}).status_code == 200
    assert employee.post("/approve", json={**EXPENSE, "id": "RL-E9"}).status_code == 429
    # a different authenticated user has their own bucket
    assert manager.post("/approve", json={**EXPENSE, "id": "RL-M1"}).status_code == 200


def test_reads_and_health_are_not_limited(limited_app):
    client = TestClient(limited_app, headers=bearer("admin"))
    for _ in range(5):
        assert client.get("/health").status_code == 200
        assert client.get("/decisions").status_code == 200
        assert client.get("/metrics").status_code == 200


def test_login_is_limited_by_ip(limited_app):
    anon = TestClient(limited_app)
    codes = [
        anon.post("/auth/login", data={"username": "admin", "password": "wrong"}).status_code
        for _ in range(3)
    ]
    assert codes == [401, 401, 429]  # brute-force attempts are throttled


def test_invalid_token_falls_back_to_ip_bucket(limited_app):
    bogus = TestClient(limited_app, headers={"Authorization": "Bearer not-a-jwt"})
    codes = [bogus.post("/approve", json=EXPENSE).status_code for _ in range(3)]
    assert codes == [401, 401, 429]


def test_disabled_by_test_config():
    # conftest disables the limiter for the rest of the suite
    assert app.state.rate_limiter.enabled is False
