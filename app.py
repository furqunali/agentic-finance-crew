"""FastAPI service exposing the finance crew.

Runs in local (no-key) mode by default, so the container is fully functional
out of the box. Set USE_CREWAI=true + an API key to switch to the real crew.
"""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, Field

from finance_crew.config import Settings
from finance_crew.pipeline import process_batch, process_request

app = FastAPI(
    title="Agentic Finance Crew",
    version="1.0.0",
    description="Multi-agent expense-approval crew (CrewAI) with a policy guardrail.",
)


class ExpenseIn(BaseModel):
    id: str = Field(..., examples=["EXP-1001"])
    employee: str = Field(..., examples=["A. Rivera"])
    category: str = Field(..., examples=["software"])
    amount: float = Field(..., examples=[149.0])
    description: str = ""
    currency: str = "USD"
    has_receipt: bool = False
    date: str = ""


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "engine": Settings.from_env().active_engine}


@app.post("/approve")
def approve(expense: ExpenseIn) -> dict[str, Any]:
    return process_request(expense.model_dump()).to_dict()


@app.post("/approve/batch")
def approve_batch(expenses: list[ExpenseIn]) -> list[dict[str, Any]]:
    return [r.to_dict() for r in process_batch([e.model_dump() for e in expenses])]
