"""Observability — Prometheus metrics, structured logging and cost estimation.

Gives the system the operational signals a governed service needs: how many
decisions of each kind, per-decision latency, HTTP throughput/latency, failure
rate, and (when the real LLM crew runs) token usage and model cost.

Metrics are exposed at ``/metrics`` in Prometheus text format. Logging can be
switched to JSON (``LOG_FORMAT=json``) for ingestion by a log platform.
"""
from __future__ import annotations

import json
import logging
import os
import re

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

# --- Metrics ----------------------------------------------------------------
DECISIONS = Counter(
    "afc_decisions_total", "Expense decisions made", ["decision", "engine"]
)
RESOLUTIONS = Counter(
    "afc_resolutions_total", "Human review resolutions", ["action"]
)
FAILURES = Counter(
    "afc_failures_total", "Processing failures", ["kind"]
)
DECISION_LATENCY = Histogram(
    "afc_decision_latency_seconds", "Per-decision processing latency (seconds)"
)
HTTP_REQUESTS = Counter(
    "afc_http_requests_total", "HTTP requests", ["method", "path", "status"]
)
HTTP_LATENCY = Histogram(
    "afc_http_request_latency_seconds", "HTTP request latency (seconds)", ["method", "path"]
)
LLM_TOKENS = Counter(
    "afc_llm_tokens_total", "LLM tokens consumed", ["engine"]
)
LLM_COST = Counter(
    "afc_llm_cost_usd_total", "LLM cost in USD", ["engine"]
)


def metrics_response_body() -> tuple[bytes, str]:
    """Return (body, content_type) for the /metrics endpoint."""
    return generate_latest(), CONTENT_TYPE_LATEST


# --- HTTP path normalization (keep metric cardinality bounded) --------------
_NUM_SEGMENT = re.compile(r"/\d+")


def normalize_path(path: str) -> str:
    """Collapse numeric id segments so /decisions/7/audit -> /decisions/{id}/audit."""
    return _NUM_SEGMENT.sub("/{id}", path) or "/"


# --- Cost estimation --------------------------------------------------------
# Rough $ per 1K tokens (blended). Only used when the real CrewAI engine runs
# and returns usage; the deterministic local/langgraph engines use no LLM, so
# their token count and cost are genuinely zero.
_PRICE_PER_1K = {
    "gpt-4o-mini": 0.0006,
    "gpt-4o": 0.005,
    "gemini-1.5-flash": 0.0004,
}
_DEFAULT_PRICE_PER_1K = 0.001


def estimate_cost(model: str, tokens: int) -> float:
    """Estimate USD cost for a token count under a given model."""
    if not tokens:
        return 0.0
    price = _PRICE_PER_1K.get(model, _DEFAULT_PRICE_PER_1K)
    return round((tokens / 1000.0) * price, 6)


def record_llm_usage(engine: str, tokens: int, cost_usd: float) -> None:
    """Increment the token/cost counters (no-op amounts for key-free engines)."""
    if tokens:
        LLM_TOKENS.labels(engine).inc(tokens)
    if cost_usd:
        LLM_COST.labels(engine).inc(cost_usd)


# --- Structured logging -----------------------------------------------------
class JsonFormatter(logging.Formatter):
    """Minimal JSON log formatter (no third-party dependency)."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # Attach any explicit `extra=` fields that aren't standard LogRecord attrs.
        for key, value in record.__dict__.items():
            if key not in _STD_LOGRECORD_ATTRS and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


_STD_LOGRECORD_ATTRS = set(vars(logging.makeLogRecord({})).keys()) | {"message", "asctime"}

_configured = False


def configure_logging() -> None:
    """Configure root logging once, honoring LOG_LEVEL and LOG_FORMAT (text|json)."""
    global _configured
    if _configured:
        return
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    handler = logging.StreamHandler()
    if os.getenv("LOG_FORMAT", "text").lower() == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s"))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(getattr(logging, level, logging.INFO))
    _configured = True
