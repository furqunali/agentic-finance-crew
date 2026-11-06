"""Per-client API rate limiting — a stdlib token-bucket limiter.

Mutating endpoints (submit, batch, approve/reject, login, user admin) are
protected so one client can't flood the decision pipeline, the review queue or
the login form (credential stuffing). Each client gets its own token bucket:

* ``RATE_LIMIT_BURST`` tokens of capacity (how many calls may arrive at once),
* refilled continuously at ``RATE_LIMIT_PER_MINUTE`` tokens per minute.

A call that finds the bucket empty is refused with ``429 Too Many Requests``
and a ``Retry-After`` header saying when the next token will be available.

Clients are identified, most specific first, by the authenticated user (JWT
``sub``), then an ``X-API-Key`` header (hashed — the raw key is never kept),
then the client IP. ``X-Forwarded-For`` is honored only when
``RATE_LIMIT_TRUST_PROXY`` is on (i.e. behind a proxy you control), otherwise
it would let any caller pick their own bucket.

State is in-process (like the per-process dev JWT secret): with several
replicas each enforces its own budget. That keeps the base install free of a
Redis dependency; a shared store can implement the same ``RateLimiter`` API.
"""

from __future__ import annotations

import hashlib
import math
import os
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass

MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

DEFAULT_PER_MINUTE = 60
DEFAULT_BURST = 20
DEFAULT_MAX_CLIENTS = 10_000


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_number(name: str, default: float, minimum: float) -> float:
    try:
        value = float(os.getenv(name, default))
    except ValueError:
        return default
    return value if value >= minimum else default


@dataclass(frozen=True)
class Decision:
    """Outcome of one rate-limit check."""

    allowed: bool
    limit: int  # bucket capacity (burst)
    remaining: int  # whole tokens left after this call
    retry_after: int = 0  # seconds until a token is available (when refused)


class RateLimiter:
    """Thread-safe token buckets keyed by client id, with LRU eviction so the
    number of tracked clients (and memory) stays bounded."""

    def __init__(
        self,
        *,
        per_minute: float = DEFAULT_PER_MINUTE,
        burst: int = DEFAULT_BURST,
        enabled: bool = True,
        trust_proxy: bool = False,
        max_clients: int = DEFAULT_MAX_CLIENTS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if per_minute <= 0 or burst < 1:
            raise ValueError("per_minute must be > 0 and burst >= 1")
        self.enabled = enabled
        self.trust_proxy = trust_proxy
        self.capacity = int(burst)
        self.rate = per_minute / 60.0  # tokens per second
        self.max_clients = max_clients
        self._clock = clock
        self._lock = threading.Lock()
        # client -> (tokens, last refill timestamp)
        self._buckets: OrderedDict[str, tuple[float, float]] = OrderedDict()

    @classmethod
    def from_env(cls) -> RateLimiter:
        """Build from ``RATE_LIMIT_*`` env vars (enabled by default)."""
        per_minute = _env_number("RATE_LIMIT_PER_MINUTE", DEFAULT_PER_MINUTE, 0.001)
        return cls(
            per_minute=per_minute,
            burst=int(_env_number("RATE_LIMIT_BURST", DEFAULT_BURST, 1)),
            enabled=_env_bool("RATE_LIMIT_ENABLED", True),
            trust_proxy=_env_bool("RATE_LIMIT_TRUST_PROXY", False),
        )

    def check(self, client: str, cost: float = 1.0) -> Decision:
        """Take ``cost`` tokens from ``client``'s bucket if available."""
        if not self.enabled:
            return Decision(True, self.capacity, self.capacity)
        now = self._clock()
        with self._lock:
            tokens, last = self._buckets.pop(client, (float(self.capacity), now))
            tokens = min(self.capacity, tokens + (now - last) * self.rate)
            if tokens >= cost:
                tokens -= cost
                allowed, retry_after = True, 0
            else:
                allowed = False
                # round() first so float noise (10.0000001s) doesn't add a second
                retry_after = max(1, math.ceil(round((cost - tokens) / self.rate, 6)))
            self._buckets[client] = (tokens, now)  # re-insert as most recent
            while len(self._buckets) > self.max_clients:
                self._buckets.popitem(last=False)
        return Decision(allowed, self.capacity, int(tokens), retry_after)

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()


def client_key(
    *,
    user: str | None,
    api_key: str | None,
    forwarded_for: str | None,
    client_host: str | None,
    trust_proxy: bool,
) -> str:
    """Pick the most specific identity available for a caller."""
    if user:
        return f"user:{user}"
    if api_key:
        # Hash so raw keys never sit in memory dumps or debug output.
        return "key:" + hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:16]
    if trust_proxy and forwarded_for:
        first = forwarded_for.split(",")[0].strip()
        if first:
            return f"ip:{first}"
    return f"ip:{client_host or 'unknown'}"
