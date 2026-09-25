"""Shared test configuration.

Forces the whole suite onto a throwaway in-memory SQLite database so tests
never touch a real file or a developer's Postgres, and each run starts clean.
Set at import time (before ``app`` is imported) so the app's engine binds to it.
"""
from __future__ import annotations

import os

# In-memory DB, shared across sessions via the StaticPool wired up in db.py.
os.environ["DATABASE_URL"] = "sqlite://"

from finance_crew.db import init_db, reset_engine_for_tests  # noqa: E402

reset_engine_for_tests()
init_db()
