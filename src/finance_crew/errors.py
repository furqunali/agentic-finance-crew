"""Typed exceptions for the finance crew.

Keeping a small, explicit error hierarchy lets the API layer translate domain
failures into clean HTTP responses without leaking stack traces, and lets the
tests assert on behavior rather than on error message strings.
"""
from __future__ import annotations


class FinanceCrewError(Exception):
    """Base class for all errors raised by the finance crew."""


class ConfigurationError(FinanceCrewError):
    """Raised when the runtime is misconfigured — e.g. USE_CREWAI is enabled
    (or ENGINE=crewai) but no API key is available to reach the LLM."""


class ValidationError(FinanceCrewError):
    """Raised when an incoming payload cannot be turned into a valid request."""


class NotFoundError(FinanceCrewError):
    """Raised when a referenced record (e.g. a decision id) does not exist."""


class ConflictError(FinanceCrewError):
    """Raised when an operation is invalid for a record's current state — e.g.
    trying to human-approve a decision that was already auto-resolved or that
    is not awaiting review."""
