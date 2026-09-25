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
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from finance_crew import observability, repository
from finance_crew.auth import (
    CAN_ADMIN,
    CAN_AUDIT,
    CAN_REVIEW,
    CAN_SUBMIT,
    Role,
    authenticate,
    create_access_token,
    ensure_admin_seed,
    get_current_user,
    require_roles,
)
from finance_crew.config import Settings
from finance_crew.db import get_session, init_db, session_scope
from finance_crew.errors import ConfigurationError, ConflictError, NotFoundError, ValidationError
from finance_crew.records import User
from finance_crew.service import decide_and_store, decide_and_store_batch, resolve_decision

logger = logging.getLogger("finance_crew.api")

@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Configure logging, ensure the schema exists and a bootstrap admin is
    present on startup. Fine for SQLite/dev/CI; production on Postgres runs
    Alembic migrations, and these calls are harmless idempotent no-ops there."""
    observability.configure_logging()
    init_db()
    with session_scope() as session:
        ensure_admin_seed(session)
    yield


app = FastAPI(
    title="Agentic Finance Crew",
    version="1.0.0",
    description="Multi-agent expense-approval crew (CrewAI) with a policy guardrail.",
    lifespan=lifespan,
)


@app.middleware("http")
async def _metrics_middleware(request: Request, call_next):
    """Count every HTTP request and record its latency (paths normalized so
    metric cardinality stays bounded); tally 5xx as failures."""
    path = observability.normalize_path(request.url.path)
    start = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        observability.FAILURES.labels("unhandled").inc()
        observability.HTTP_REQUESTS.labels(request.method, path, "500").inc()
        raise
    observability.HTTP_LATENCY.labels(request.method, path).observe(time.perf_counter() - start)
    observability.HTTP_REQUESTS.labels(request.method, path, str(response.status_code)).inc()
    if response.status_code >= 500:
        observability.FAILURES.labels("http_5xx").inc()
    return response


@app.get("/metrics")
def metrics() -> Response:
    """Prometheus metrics (scrape target). Unauthenticated, like /health."""
    body, content_type = observability.metrics_response_body()
    return Response(content=body, media_type=content_type)


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    """Send the bare host to the web console."""
    return RedirectResponse(url="/ui/")


# Serve the self-contained web console (SPA) at /ui. It talks to the API above
# with the JWT from /auth/login. Mounted last so it never shadows API routes.
_WEB_DIR = Path(__file__).parent / "web"
if _WEB_DIR.is_dir():
    app.mount("/ui", StaticFiles(directory=str(_WEB_DIR), html=True), name="ui")

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


class ResolutionIn(BaseModel):
    """A human reviewer's note on an item in the review queue. The approver's
    identity is taken from the authenticated token, never the request body."""

    note: str = Field("", examples=["Verified receipt with vendor; approved."])


class UserCreateIn(BaseModel):
    username: str = Field(..., min_length=1, examples=["m.khan"])
    password: str = Field(..., min_length=6, examples=["change-me-please"])
    role: str = Field(Role.EMPLOYEE, examples=[Role.FINANCE_MANAGER])
    full_name: str = Field("", examples=["Mustafa Khan"])


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


@app.exception_handler(NotFoundError)
def _handle_not_found(_request: Any, exc: NotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content=_error_payload(404, str(exc)))


@app.exception_handler(ConflictError)
def _handle_conflict(_request: Any, exc: ConflictError) -> JSONResponse:
    """Resolving a decision that isn't awaiting review -> 409 Conflict."""
    logger.info("conflict: %s", exc)
    return JSONResponse(status_code=409, content=_error_payload(409, str(exc)))


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "engine": Settings.from_env().active_engine}


# --- Authentication ---------------------------------------------------------
@app.post("/auth/login")
def login(
    form: OAuth2PasswordRequestForm = Depends(), session: Session = Depends(get_session)
) -> dict[str, Any]:
    """Exchange username + password for a JWT bearer token."""
    user = authenticate(session, form.username, form.password)
    if user is None:
        raise HTTPException(
            status_code=401,
            detail=_error_payload(401, "incorrect username or password")["error"],
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = create_access_token(user.username, user.role)
    return {"access_token": token, "token_type": "bearer", "role": user.role}


@app.get("/auth/me")
def me(user: User = Depends(get_current_user)) -> dict[str, Any]:
    """Return the authenticated user's profile."""
    return user.to_dict()


@app.post("/auth/register", status_code=201)
def register_user(
    body: UserCreateIn,
    session: Session = Depends(get_session),
    _admin: User = Depends(require_roles(*CAN_ADMIN)),
) -> dict[str, Any]:
    """Create a user (admin only)."""
    if body.role not in Role.ALL:
        raise HTTPException(
            status_code=422,
            detail=_error_payload(422, f"unknown role '{body.role}'")["error"],
        )
    if repository.get_user_by_username(session, body.username) is not None:
        raise HTTPException(
            status_code=409,
            detail=_error_payload(409, f"username '{body.username}' already exists")["error"],
        )
    user = repository.create_user(
        session, username=body.username, password=body.password,
        role=body.role, full_name=body.full_name,
    )
    return user.to_dict()


@app.get("/auth/users")
def list_all_users(
    session: Session = Depends(get_session),
    _admin: User = Depends(require_roles(*CAN_ADMIN)),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """List all users (admin only)."""
    rows = repository.list_users(session, limit=limit, offset=offset)
    return {"count": len(rows), "items": [u.to_dict() for u in rows]}


def _serialize(session: Session, record_id: int) -> dict[str, Any]:
    """Return the stored record (status, audit fields, model/version …) with a
    convenience ``record_id`` alias alongside its primary key."""
    record = repository.get_decision(session, record_id)
    assert record is not None  # just written in this transaction
    payload = record.to_dict()
    payload["record_id"] = record.id
    return payload


@app.post("/approve")
def approve(
    expense: ExpenseIn,
    session: Session = Depends(get_session),
    user: User = Depends(require_roles(*CAN_SUBMIT)),
) -> dict[str, Any]:
    try:
        _result, record_id = decide_and_store(
            session, expense.model_dump(), requested_by=user.username
        )
        return _serialize(session, record_id)
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
    expenses: list[ExpenseIn],
    session: Session = Depends(get_session),
    user: User = Depends(require_roles(*CAN_SUBMIT)),
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
        stored = decide_and_store_batch(
            session, [e.model_dump() for e in expenses], requested_by=user.username
        )
        return [_serialize(session, record_id) for _result, record_id in stored]
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
    _user: User = Depends(require_roles(*CAN_AUDIT)),
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
def get_decision(
    record_id: int,
    session: Session = Depends(get_session),
    _user: User = Depends(require_roles(*CAN_AUDIT)),
) -> dict[str, Any]:
    """Fetch a single persisted decision by its stored id."""
    record = repository.get_decision(session, record_id)
    if record is None:
        raise HTTPException(
            status_code=404,
            detail=_error_payload(404, f"no decision with id {record_id}")["error"],
        )
    return record.to_dict()


# --- Human-in-the-loop review workflow --------------------------------------
@app.get("/review-queue")
def review_queue(
    session: Session = Depends(get_session),
    _user: User = Depends(require_roles(*CAN_REVIEW)),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """Decisions awaiting a human sign-off (oldest first)."""
    rows = repository.list_review_queue(session, limit=limit, offset=offset)
    return {"count": len(rows), "items": [r.to_dict() for r in rows]}


@app.post("/decisions/{record_id}/approve")
def approve_decision(
    record_id: int,
    body: ResolutionIn,
    session: Session = Depends(get_session),
    user: User = Depends(require_roles(*CAN_REVIEW)),
) -> dict[str, Any]:
    """A human (Finance Manager / Admin) approves an item in the review queue."""
    record = resolve_decision(session, record_id, "approve", user.username, body.note)
    return record.to_dict()


@app.post("/decisions/{record_id}/reject")
def reject_decision(
    record_id: int,
    body: ResolutionIn,
    session: Session = Depends(get_session),
    user: User = Depends(require_roles(*CAN_REVIEW)),
) -> dict[str, Any]:
    """A human (Finance Manager / Admin) rejects an item in the review queue."""
    record = resolve_decision(session, record_id, "reject", user.username, body.note)
    return record.to_dict()


# --- Audit trail ------------------------------------------------------------
@app.get("/decisions/{record_id}/audit")
def decision_audit(
    record_id: int,
    session: Session = Depends(get_session),
    _user: User = Depends(require_roles(*CAN_AUDIT)),
) -> dict[str, Any]:
    """The full, ordered audit trail for one decision."""
    record = repository.get_decision(session, record_id)
    if record is None:
        raise HTTPException(
            status_code=404,
            detail=_error_payload(404, f"no decision with id {record_id}")["error"],
        )
    events = repository.get_audit_events(session, record_id)
    return {"decision": record.to_dict(), "trail": [e.to_dict() for e in events]}


@app.get("/audit")
def audit_log(
    session: Session = Depends(get_session),
    _user: User = Depends(require_roles(*CAN_AUDIT)),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    step: str | None = Query(None, description="Filter by lifecycle step"),
) -> dict[str, Any]:
    """Global append-only audit log across all decisions (newest first)."""
    events = repository.list_audit_events(session, limit=limit, offset=offset, step=step)
    return {"count": len(events), "items": [e.to_dict() for e in events]}
