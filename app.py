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

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from finance_crew import repository
from finance_crew.config import Settings
from finance_crew.db import get_session, init_db
from finance_crew.errors import ConfigurationError, ValidationError
from finance_crew.service import decide_and_store, decide_and_store_batch

logger = logging.getLogger("finance_crew.api")

app = FastAPI(
    title="Agentic Finance Crew",
    version="1.0.0",
    description="Multi-agent expense-approval crew (CrewAI) with a policy guardrail.",
)


@app.on_event("startup")
def _startup() -> None:
    """Ensure the schema exists. Fine for SQLite/dev/CI; production on Postgres
    runs Alembic migrations, and this call is a harmless idempotent no-op there."""
    init_db()

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
def approve(expense: ExpenseIn, session: Session = Depends(get_session)) -> dict[str, Any]:
    try:
        result, record_id = decide_and_store(session, expense.model_dump())
        payload = result.to_dict()
        payload["record_id"] = record_id  # link the verdict to its stored row
        return payload
    except (ConfigurationError, ValidationError):
        raise  # handled by the dedicated exception handlers above
    except Exception as exc:  # pragma: no cover - defensive last line
        logger.exception("failed to process request %s", expense.id)
        raise HTTPException(
            status_code=500,
            detail=_error_payload(500, "failed to process expense request", str(exc))["error"],
        ) from exc


@app.post("/approve/batch")
def approve_batch(
    expenses: list[ExpenseIn], session: Session = Depends(get_session)
) -> list[dict[str, Any]]:
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
        stored = decide_and_store_batch(session, [e.model_dump() for e in expenses])
        out = []
        for result, record_id in stored:
            payload = result.to_dict()
            payload["record_id"] = record_id
            out.append(payload)
        return out
    except ConfigurationError:
        raise
    except Exception as exc:  # pragma: no cover - defensive last line
        logger.exception("failed to process batch of %d", len(expenses))
        raise HTTPException(
            status_code=500,
            detail=_error_payload(500, "failed to process expense batch", str(exc))["error"],
        ) from exc


@app.get("/decisions")
def list_decisions(
    session: Session = Depends(get_session),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    decision: str | None = Query(None, description="Filter by decision value"),
    employee: str | None = Query(None, description="Filter by employee"),
) -> dict[str, Any]:
    """Paginated history of persisted decisions (newest first)."""
    rows = repository.list_decisions(
        session, limit=limit, offset=offset, decision=decision, employee=employee
    )
    return {
        "total": repository.count_decisions(session, decision=decision),
        "count": len(rows),
        "limit": limit,
        "offset": offset,
        "items": [r.to_dict() for r in rows],
    }


@app.get("/decisions/{record_id}")
def get_decision(record_id: int, session: Session = Depends(get_session)) -> dict[str, Any]:
    """Fetch a single persisted decision by its stored id."""
    record = repository.get_decision(session, record_id)
    if record is None:
        raise HTTPException(
            status_code=404,
            detail=_error_payload(404, f"no decision with id {record_id}")["error"],
        )
    return record.to_dict()
