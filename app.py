"""FastAPI service exposing the finance crew.

Runs in local (no-key) mode by default, so the container is fully functional
out of the box. Set USE_CREWAI=true + an API key to switch to the real crew.

Error handling is deliberately explicit: pydantic returns a clean 422 for
malformed payloads, and the orchestration itself is wrapped so any unexpected
failure surfaces as a structured 500 payload rather than a bare stack trace.
The CrewAI path fails fast with a clear message when opted-in but unkeyed.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from finance_crew.config import Settings
from finance_crew.errors import ConfigurationError, ValidationError
from finance_crew.pipeline import process_batch, process_request

logger = logging.getLogger("finance_crew.api")

app = FastAPI(
    title="Agentic Finance Crew",
    version="1.0.0",
    description="Multi-agent expense-approval crew (CrewAI) with a policy guardrail.",
)

# Guard against unbounded batches turning into a denial-of-service.
MAX_BATCH_SIZE = 500


class ExpenseIn(BaseModel):
    id: str = Field(..., min_length=1, examples=["EXP-1001"])
    employee: str = Field(..., min_length=1, examples=["A. Rivera"])
    category: str = Field(..., examples=["software"])
    amount: float = Field(..., examples=[149.0])
    description: str = ""
    currency: str = "USD"
    has_receipt: bool = False
    date: str = ""


def _error_payload(status: int, message: str, detail: str | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"error": {"status": status, "message": message}}
    if detail:
        body["error"]["detail"] = detail
    return body


@app.exception_handler(ConfigurationError)
def _handle_configuration_error(_request: Any, exc: ConfigurationError) -> JSONResponse:
    """A misconfigured engine (e.g. USE_CREWAI without a key) is the caller's
    fault to fix, so surface it as a clear 400 rather than a 500."""
    logger.warning("configuration error: %s", exc)
    return JSONResponse(status_code=400, content=_error_payload(400, str(exc)))


@app.exception_handler(ValidationError)
def _handle_validation_error(_request: Any, exc: ValidationError) -> JSONResponse:
    """A payload that survives pydantic but fails domain validation -> 422."""
    logger.info("validation error: %s", exc)
    return JSONResponse(status_code=422, content=_error_payload(422, str(exc)))


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "engine": Settings.from_env().active_engine}


@app.post("/approve")
def approve(expense: ExpenseIn) -> dict[str, Any]:
    try:
        return process_request(expense.model_dump()).to_dict()
    except (ConfigurationError, ValidationError):
        raise  # handled by the dedicated exception handlers above
    except Exception as exc:  # pragma: no cover - defensive last line
        logger.exception("failed to process request %s", expense.id)
        raise HTTPException(
            status_code=500,
            detail=_error_payload(500, "failed to process expense request", str(exc))["error"],
        ) from exc


@app.post("/approve/batch")
def approve_batch(expenses: list[ExpenseIn]) -> list[dict[str, Any]]:
    if not expenses:
        raise HTTPException(
            status_code=422,
            detail=_error_payload(422, "batch must contain at least one expense")["error"],
        )
    if len(expenses) > MAX_BATCH_SIZE:
        raise HTTPException(
            status_code=422,
            detail=_error_payload(
                422, f"batch too large: {len(expenses)} exceeds the {MAX_BATCH_SIZE}-item limit"
            )["error"],
        )
    try:
        return [r.to_dict() for r in process_batch([e.model_dump() for e in expenses])]
    except ConfigurationError:
        raise
    except Exception as exc:  # pragma: no cover - defensive last line
        logger.exception("failed to process batch of %d", len(expenses))
        raise HTTPException(
            status_code=500,
            detail=_error_payload(500, "failed to process expense batch", str(exc))["error"],
        ) from exc
