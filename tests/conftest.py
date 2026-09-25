"""Shared test configuration.

Forces the whole suite onto a throwaway in-memory SQLite database so tests
never touch a real file or a developer's Postgres, and each run starts clean.
Also seeds one user per role and exposes :func:`bearer` so tests can call the
now-authenticated endpoints. Set at import time (before ``app`` is imported).
"""
from __future__ import annotations

import os

# In-memory DB (shared via the StaticPool wired up in db.py) + a fixed JWT
# secret so tokens minted here verify inside the app.
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["JWT_SECRET"] = "test-secret-not-for-production-0123456789"  # >=32 bytes

from finance_crew import repository  # noqa: E402
from finance_crew.auth import Role, create_access_token  # noqa: E402
from finance_crew.db import init_db, reset_engine_for_tests, session_scope  # noqa: E402

reset_engine_for_tests()
init_db()

# username -> role, one seeded user per RBAC role.
USERS = {
    "admin": Role.ADMIN,
    "manager": Role.FINANCE_MANAGER,
    "auditor": Role.AUDITOR,
    "employee": Role.EMPLOYEE,
}

with session_scope() as _s:
    for _uname, _role in USERS.items():
        if repository.get_user_by_username(_s, _uname) is None:
            repository.create_user(
                _s, username=_uname, password=f"pw-{_uname}", role=_role,
                full_name=_uname.title(),
            )


def bearer(username: str = "admin") -> dict[str, str]:
    """Authorization header for a seeded user (username == role shorthand)."""
    token = create_access_token(username, USERS[username])
    return {"Authorization": f"Bearer {token}"}
