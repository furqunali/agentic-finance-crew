"""Database core — engine, session factory and transaction handling.

The whole persistence layer is driven by a single ``DATABASE_URL`` environment
variable so the *same* code runs against:

* **SQLite** (the default) — zero-config, file-based, perfect for local dev,
  the demo and CI. An in-memory URL (``sqlite://``) is used by the tests.
* **PostgreSQL** — the production system-of-record, selected simply by setting
  ``DATABASE_URL=postgresql+psycopg://user:pass@host/db`` (see ``.env.example``).

No engine-specific code leaks into the app: callers only ever touch
:func:`session_scope` (a transactional unit of work) or the FastAPI
:func:`get_session` dependency.
"""
from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

DEFAULT_DATABASE_URL = "sqlite:///./finance_crew.db"


class Base(DeclarativeBase):
    """Declarative base for every ORM model in the package."""


def database_url() -> str:
    """The active database URL (``DATABASE_URL`` env or the SQLite default)."""
    return os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)


def _engine_kwargs(url: str) -> dict:
    """SQLite needs a couple of flags to behave under FastAPI's threadpool and
    to keep an in-memory database alive across connections in the tests."""
    if url.startswith("sqlite"):
        kwargs: dict = {"connect_args": {"check_same_thread": False}}
        # A bare in-memory URL ("sqlite://") must share one connection or every
        # session would see a fresh, empty database.
        if url in ("sqlite://", "sqlite:///:memory:"):
            kwargs["poolclass"] = StaticPool
        return kwargs
    # Real databases: recycle stale connections and validate before use.
    return {"pool_pre_ping": True, "pool_recycle": 1800}


_engine: Engine | None = None
_SessionFactory: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    """Lazily create (once) and return the process-wide SQLAlchemy engine."""
    global _engine, _SessionFactory
    if _engine is None:
        url = database_url()
        _engine = create_engine(url, future=True, **_engine_kwargs(url))
        _SessionFactory = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
    return _engine


def _session_factory() -> sessionmaker[Session]:
    if _SessionFactory is None:
        get_engine()
    assert _SessionFactory is not None  # for type-checkers
    return _SessionFactory


def init_db() -> None:
    """Create any missing tables.

    Convenient for SQLite/dev/CI and idempotent (``checkfirst`` is on by
    default). Production on Postgres should instead run the Alembic migrations
    (``alembic upgrade head``) so schema changes are versioned — but calling
    this there is harmless.
    """
    # Import for the side effect of registering the models on ``Base.metadata``.
    from . import records  # noqa: F401

    Base.metadata.create_all(bind=get_engine())


@contextmanager
def session_scope() -> Iterator[Session]:
    """Provide a transactional scope around a series of operations.

    Commits on success, rolls back on any exception, and always closes the
    session — the standard SQLAlchemy unit-of-work pattern, so callers never
    have to remember to commit or clean up.
    """
    session = _session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session() -> Iterator[Session]:
    """FastAPI dependency: yield a session and commit/rollback around the
    request. Mirrors :func:`session_scope` but as a generator dependency."""
    with session_scope() as session:
        yield session


def reset_engine_for_tests() -> None:
    """Drop the cached engine so the next call re-reads ``DATABASE_URL``.

    Only used by the test-suite fixtures to point at a throwaway database.
    """
    global _engine, _SessionFactory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionFactory = None
