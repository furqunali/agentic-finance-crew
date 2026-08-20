"""Error-handling and edge-case tests for the domain layer."""
import pytest

from finance_crew.config import Settings
from finance_crew.errors import ConfigurationError, ValidationError
from finance_crew.models import ExpenseRequest
from finance_crew.orchestrator import build_orchestrator


def test_crewai_engine_without_key_raises_configuration_error():
    settings = Settings(engine="crewai", use_crewai=True, api_key=None)
    with pytest.raises(ConfigurationError) as exc:
        build_orchestrator(settings)
    assert "OPENAI_API_KEY" in str(exc.value)


def test_crewai_engine_gemini_without_key_names_the_right_env():
    settings = Settings(engine="crewai", llm_provider="gemini", api_key=None)
    with pytest.raises(ConfigurationError) as exc:
        build_orchestrator(settings)
    assert "GEMINI_API_KEY" in str(exc.value)


def test_from_dict_rejects_non_dict_payload():
    with pytest.raises(ValidationError):
        ExpenseRequest.from_dict(["not", "a", "dict"])  # type: ignore[arg-type]


def test_from_dict_rejects_non_numeric_amount():
    with pytest.raises(ValidationError) as exc:
        ExpenseRequest.from_dict({"id": "X", "employee": "E", "amount": "abc"})
    assert "amount" in str(exc.value)


def test_from_dict_tolerates_missing_optional_fields():
    # Missing amount/category default cleanly rather than raising.
    r = ExpenseRequest.from_dict({"id": "X", "employee": "E"})
    assert r.amount == 0.0
    assert r.category == "other"
