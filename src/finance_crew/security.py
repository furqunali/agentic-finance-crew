"""Password hashing — stdlib only (PBKDF2-HMAC-SHA256, salted).

Deliberately dependency-free: no bcrypt/argon2 wheels to build, so the image
and CI stay light and portable. PBKDF2 with a per-password random salt and a
high iteration count is a sound, widely-accepted choice for storing passwords.
Hashes are self-describing (`pbkdf2_sha256$iterations$salt$hash`) so the work
factor can be raised later without breaking existing users.
"""
from __future__ import annotations

import hashlib
import hmac
import os
from base64 import b64decode, b64encode

_ALGO = "pbkdf2_sha256"
_ITERATIONS = 240_000
_SALT_BYTES = 16


def hash_password(password: str, *, iterations: int = _ITERATIONS) -> str:
    """Return a self-describing salted PBKDF2 hash of ``password``."""
    if not password:
        raise ValueError("password must not be empty")
    salt = os.urandom(_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"{_ALGO}${iterations}${b64encode(salt).decode()}${b64encode(digest).decode()}"


def verify_password(password: str, encoded: str) -> bool:
    """Constant-time check of ``password`` against a stored hash."""
    try:
        algo, iters, salt_b64, hash_b64 = encoded.split("$")
        if algo != _ALGO:
            return False
        salt = b64decode(salt_b64)
        expected = b64decode(hash_b64)
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iters))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(candidate, expected)
