"""CLI demo — runs the crew over the bundled fictional expenses.

    python run_demo.py                 # runs sample_data/expenses.json
    python run_demo.py path/to.json    # runs your own batch

Works with zero API keys (local engine). Set USE_CREWAI=true + a key to see
the real multi-agent crew in action.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Make Unicode (e.g. em dashes) print safely on Windows cp1252 consoles.
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # pragma: no cover - non-reconfigurable stream
    pass

from finance_crew.config import Settings
from finance_crew.pipeline import process_batch

DECISION_ICON = {
    "auto_approved": "[APPROVED]",
    "needs_human_review": "[REVIEW]  ",
    "rejected": "[REJECTED]",
}


def main(argv: list[str]) -> int:
    path = Path(argv[1]) if len(argv) > 1 else Path(__file__).parent / "sample_data" / "expenses.json"
    payloads = json.loads(path.read_text(encoding="utf-8"))

    settings = Settings.from_env()
    labels = {
        "crewai": "CrewAI (real multi-agent crew)",
        "langgraph": "LangGraph (stateful graph, no LLM)",
        "local": "local (deterministic, no LLM)",
    }
    engine = labels.get(settings.active_engine, settings.active_engine)
    print(f"\n  Agentic Finance Crew — engine: {engine}")
    print("  " + "-" * 68)

    results = process_batch(payloads, settings)
    approved = review = rejected = 0
    for r in results:
        icon = DECISION_ICON[r.decision.value]
        print(f"  {icon}  {r.request_id:<10} risk={r.risk_score:>3}  {r.rationale.splitlines()[0]}")
        approved += r.decision.value == "auto_approved"
        review += r.decision.value == "needs_human_review"
        rejected += r.decision.value == "rejected"

    print("  " + "-" * 68)
    print(f"  {len(results)} processed  |  {approved} auto-approved  |  "
          f"{review} to human  |  {rejected} rejected\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
