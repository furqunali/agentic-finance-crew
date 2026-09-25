"""Authentication (JWT) and role-based access control.

* **Roles** — Employee, Finance Manager, Auditor, Admin — model a real finance
  back-office: employees submit expenses, finance managers sign off review
  items, auditors have read-only oversight of the full trail, admins manage
  users.
* **JWT bearer tokens** issued at ``/auth/login`` and verified on every
  protected route. The token carries the subject + role, but role is always
  re-read from the database (the source of truth) so a revoked/reassigned user
  can't act on a stale token.

The signing secret comes from ``JWT_SECRET`` — never hard-coded. In dev an
ephemeral secret is generated so the app still runs key-free; a warning is
logged because tokens won't survive a restart until a real secret is set.
"""
from __future__ import annotations

import logging
import os
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from . import repository
from .db import get_session
from .records import User

logger = logging.getLogger("finance_crew.auth")

ALGORITHM = "HS256"
DEFAULT_EXPIRE_MINUTES = 60


class Role:
    """The four RBAC roles. Admin implicitly has every capability."""

    EMPLOYEE = "employee"
    FINANCE_MANAGER = "finance_manager"
    AUDITOR = "auditor"
    ADMIN = "admin"

    ALL = frozenset({EMPLOYEE, FINANCE_MANAGER, AUDITOR, ADMIN})


# Capability groupings used to gate routes (admin is added automatically).
CAN_SUBMIT = frozenset({Role.EMPLOYEE, Role.FINANCE_MANAGER, Role.AUDITOR, Role.ADMIN})
CAN_REVIEW = frozenset({Role.FINANCE_MANAGER, Role.ADMIN})          # approve/reject
CAN_AUDIT = frozenset({Role.AUDITOR, Role.FINANCE_MANAGER, Role.ADMIN})  # read all/audit
CAN_ADMIN = frozenset({Role.ADMIN})

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login", auto_error=False)


def auth_disabled() -> bool:
    """Local/demo convenience: when AUTH_DISABLED is truthy, every request is
    treated as the admin user and no login is required. OFF by default — never
    enable in production (the whole point of the system is governed access)."""
    return os.getenv("AUTH_DISABLED", "").strip().lower() in {"1", "true", "yes", "on"}


def _secret() -> str:
    secret = os.getenv("JWT_SECRET")
    if not secret:
        # Ephemeral dev secret: the app runs key-free, but tokens are per-process.
        secret = _dev_secret()
        logger.warning(
            "JWT_SECRET not set — using an ephemeral dev secret; tokens will not "
            "survive a restart. Set JWT_SECRET in production."
        )
    return secret


_DEV_SECRET: str | None = None


def _dev_secret() -> str:
    global _DEV_SECRET
    if _DEV_SECRET is None:
        _DEV_SECRET = secrets.token_urlsafe(32)
    return _DEV_SECRET


def _expire_minutes() -> int:
    try:
        return int(os.getenv("JWT_EXPIRE_MINUTES", DEFAULT_EXPIRE_MINUTES))
    except ValueError:
        return DEFAULT_EXPIRE_MINUTES


def create_access_token(username: str, role: str, expires_minutes: int | None = None) -> str:
    """Issue a signed JWT for a user."""
    now = datetime.now(timezone.utc)
    exp = now + timedelta(minutes=expires_minutes or _expire_minutes())
    payload = {"sub": username, "role": role, "iat": now, "exp": exp}
    return jwt.encode(payload, _secret(), algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    """Decode + verify a JWT, raising ``jwt.PyJWTError`` on any problem."""
    return jwt.decode(token, _secret(), algorithms=[ALGORITHM])


_CREDENTIALS_EXC = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail={"status": 401, "message": "could not validate credentials"},
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_user(
    token: str | None = Depends(oauth2_scheme), session: Session = Depends(get_session)
) -> User:
    """Resolve the bearer token to an active user (role read from the DB).

    In AUTH_DISABLED mode there is no login: every caller is the admin user."""
    if auth_disabled():
        admin = repository.get_user_by_username(session, "admin")
        if admin is not None:
            return admin
        # No seeded admin yet — return a transient admin principal.
        return User(username="admin", role=Role.ADMIN, full_name="Local Admin",
                    is_active=True, hashed_password="")

    if not token:
        raise _CREDENTIALS_EXC
    try:
        payload = decode_token(token)
        username = payload.get("sub")
        if not username:
            raise _CREDENTIALS_EXC
    except jwt.PyJWTError:
        raise _CREDENTIALS_EXC

    user = repository.get_user_by_username(session, username)
    if user is None or not user.is_active:
        raise _CREDENTIALS_EXC
    return user


def require_roles(*roles: str):
    """Dependency factory: allow only the given roles (Admin always allowed)."""
    allowed = frozenset(roles) | {Role.ADMIN}

    def _dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "status": 403,
                    "message": f"role '{user.role}' is not permitted to perform this action",
                },
            )
        return user

    return _dependency


def authenticate(session: Session, username: str, password: str) -> User | None:
    """Return the user iff the username exists, is active and the password matches."""
    from .security import verify_password

    user = repository.get_user_by_username(session, username)
    if user is None or not user.is_active:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user


def ensure_admin_seed(session: Session) -> None:
    """Create a bootstrap admin on an empty user table so the system is usable.

    Credentials come from ``ADMIN_USERNAME`` / ``ADMIN_PASSWORD`` (default
    ``admin`` / ``admin`` with a loud warning to change them)."""
    if repository.count_users(session) > 0:
        return
    username = os.getenv("ADMIN_USERNAME", "admin")
    password = os.getenv("ADMIN_PASSWORD", "admin")
    repository.create_user(session, username=username, password=password,
                           role=Role.ADMIN, full_name="Bootstrap Admin")
    if password == "admin":
        logger.warning(
            "Seeded a default admin (admin/admin). Set ADMIN_USERNAME/ADMIN_PASSWORD "
            "and change this immediately in any real deployment."
        )
