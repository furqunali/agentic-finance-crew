"""High-level entrypoint used by the CLI, the API and the tests."""
from __future__ import annotations

from typing import Any

from .config import Settings
from .models import ApprovalResult, ExpenseRequest
from .orchestrator import build_orchestrator


def process_request(payload: dict[str, Any],
                    history: list[dict[str, Any]] | None = None,
                    settings: Settings | None = None) -> ApprovalResult:
    """Process one expense payload end-to-end and return the verdict."""
    request = ExpenseRequest.from_dict(payload)
    hist = [ExpenseRequest.from_dict(h) for h in (history or [])]
    orchestrator = build_orchestrator(settings)
    return orchestrator.process(request, hist)


def process_batch(payloads: list[dict[str, Any]],
                  settings: Settings | None = None) -> list[ApprovalResult]:
    """Process a batch, treating earlier items as history for duplicate detection."""
    orchestrator = build_orchestrator(settings)
    results: list[ApprovalResult] = []
    seen: list[ExpenseRequest] = []
    for payload in payloads:
        request = ExpenseRequest.from_dict(payload)
        results.append(orchestrator.process(request, list(seen)))
        seen.append(request)
    return results
