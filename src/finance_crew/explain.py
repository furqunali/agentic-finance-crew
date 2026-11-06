"""Per-decision "decision record" — the transparency export for one verdict.

Answers, for a single stored decision, the questions an auditor, the affected
employee or a regulator would ask of an automated decision: *what went in,
which rules applied, what each agent/step did, what was decided, by whom
(machine or human) and when*. It is assembled entirely from data the system
already persists — the :class:`DecisionRecord` row and its append-only audit
trail — so it can never disagree with the system of record.

Free text is passed through the input guard's PII redaction before export, so
a decision record can be shared without leaking emails, card numbers etc.

Exposed at ``GET /decisions/{id}/explanation`` (JSON, or ``?format=markdown``
for a human-readable export). See ``MODEL_CARD.md`` for the system-level view.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from . import repository
from .config import SpendPolicy
from .errors import NotFoundError
from .guard import redact_pii
from .records import Status, Step

SCHEMA = "afc.decision-record/v1"

# Machine steps of the lifecycle, in pipeline order (human steps follow).
_AGENT_STEP_LABELS = {
    Step.REQUEST_RECEIVED: "Intake: request received",
    Step.INPUT_GUARD: "Input guard: injection / PII screening",
    Step.AI_REASONING: "Policy Analyst: risk assessment",
    Step.POLICY_EVALUATION: "Policy Analyst: policy rules evaluated",
    Step.DECISION: "Approver + guardrail: routing decision",
}
_HUMAN_STEPS = {Step.HUMAN_REVIEW, Step.FINAL_ACTION}


def _redact(text: str | None) -> str | None:
    return None if text is None else redact_pii(text)[0]


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _policy_rules(policy: SpendPolicy, category: str) -> list[dict[str, Any]]:
    """The deterministic rules every request is evaluated against."""
    return [
        {"rule": "intake_validation", "description": "id and employee present; 0 < amount <= 100,000"},
        {
            "rule": "category_limit",
            "description": f"amount must not exceed the {category} limit",
            "threshold": policy.limit_for(category),
        },
        {
            "rule": "receipt_required",
            "description": "a receipt is required above this amount",
            "threshold": policy.receipt_required_above,
        },
        {
            "rule": "human_review_limit",
            "description": "amounts above this always need human sign-off",
            "threshold": policy.human_review_limit,
        },
        {
            "rule": "auto_approve_limit",
            "description": "compliant, low-risk requests up to this amount may auto-approve",
            "threshold": policy.auto_approve_limit,
        },
        {"rule": "risk_threshold", "description": "risk score >= 60 needs human review", "threshold": 60},
        {"rule": "duplicate_check", "description": "same employee, amount and category seen before"},
        {"rule": "input_guard", "description": "suspected prompt injection needs human review"},
    ]


def build_decision_record(
    session: Session, record_id: int, policy: SpendPolicy | None = None
) -> dict[str, Any]:
    """Assemble the decision record for one stored decision.

    Raises :class:`NotFoundError` if the decision does not exist.
    """
    record = repository.get_decision(session, record_id)
    if record is None:
        raise NotFoundError(f"no decision with id {record_id}")
    policy = policy or SpendPolicy()
    events = repository.get_audit_events(session, record_id)

    agent_steps = [
        {
            "step": e.step,
            "label": _AGENT_STEP_LABELS.get(e.step, e.step),
            "actor": e.actor,
            "detail": _redact(e.detail),
            "at": _iso(e.created_at),
        }
        for e in events
        if e.step not in _HUMAN_STEPS
    ]
    human_events = [
        {"step": e.step, "actor": e.actor, "detail": _redact(e.detail), "at": _iso(e.created_at)}
        for e in events
        if e.step in _HUMAN_STEPS
    ]
    guard_events = [e for e in events if e.step == Step.INPUT_GUARD]
    review_required = record.decision == "needs_human_review"
    auto = record.status in (Status.AUTO_APPROVED, Status.AUTO_REJECTED)

    return {
        "schema": SCHEMA,
        "record_id": record.id,
        "request_id": _redact(record.request_id),
        "inputs": {
            "employee": _redact(record.employee),
            "requested_by": _redact(record.requested_by),
            "category": record.category,
            "amount": record.amount,
            "currency": record.currency,
            "note": "Free-text fields are not stored on the decision; values shown are PII-redacted.",
        },
        "policy": {
            "rules_evaluated": _policy_rules(policy, record.category),
            "rules_fired": [_redact(r) for r in record.rules],
            "input_guard": {
                "flagged": any("prompt injection" in (e.detail or "") for e in guard_events),
                "details": [_redact(e.detail) for e in guard_events],
            },
            "policy_version": "current",  # policy is code; pinned by model_version below
        },
        "agent_steps": agent_steps,
        "decision": {
            "outcome": record.decision,
            "ai_recommendation": record.ai_recommendation,
            "risk_score": record.risk_score,
            "confidence": record.confidence,
            "rationale": _redact(record.rationale),
            "decided_by": "deterministic policy guardrail (decide())",
            "engine": record.engine,
            "model_version": record.model_version,
            "decided_at": _iso(record.created_at),
        },
        "human_oversight": {
            "review_required": review_required,
            "status": record.status,
            "final_action": record.final_action,
            "resolved_by": record.resolved_by
            or ("system (auto-resolved, no human review required)" if auto else None),
            "resolved_at": _iso(record.resolved_at),
            "note": _redact(record.resolution_note),
            "events": human_events,
        },
        "timestamps": {
            "received_at": _iso(record.created_at),
            "decided_at": _iso(record.created_at),
            "resolved_at": _iso(record.resolved_at),
        },
        "operational": {
            "latency_ms": record.latency_ms,
            "llm_tokens": record.tokens,
            "llm_cost_usd": record.cost_usd,
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def render_markdown(rec: dict[str, Any]) -> str:
    """Human-readable export of a decision record."""
    d, h, inp = rec["decision"], rec["human_oversight"], rec["inputs"]
    lines = [
        f"# Decision record — {rec['request_id']} (#{rec['record_id']})",
        "",
        f"_Schema `{rec['schema']}` · generated {rec['generated_at']}_",
        "",
        "## Inputs (redacted)",
        f"- Employee: {inp['employee']} · requested by: {inp['requested_by']}",
        f"- Category: {inp['category']} · amount: {inp['amount']:,.2f} {inp['currency']}",
        "",
        "## Decision",
        f"- Outcome: **{d['outcome']}** (AI recommendation: {d['ai_recommendation']})",
        f"- Risk score: {d['risk_score']}/100 · confidence: {d['confidence']:.2f}",
        f"- Decided by: {d['decided_by']} · engine `{d['model_version']}` at {d['decided_at']}",
        f"- Rationale: {d['rationale']}",
        "",
        "## Policy rules fired",
    ]
    fired = rec["policy"]["rules_fired"]
    lines += [f"- {r}" for r in fired] if fired else ["- none"]
    lines += ["", "## Agent steps"]
    lines += [
        f"{i}. **{s['label']}** ({s['actor']}, {s['at']}): {s['detail']}"
        for i, s in enumerate(rec["agent_steps"], 1)
    ]
    lines += [
        "",
        "## Human oversight",
        (
            f"- Review required: {'yes' if h['review_required'] else 'no'} · status: {h['status']}"
            f" · final action: {h['final_action']}"
        ),
        f"- Approved/rejected by: {h['resolved_by'] or 'pending'}"
        + (f" at {h['resolved_at']}" if h["resolved_at"] else ""),
    ]
    if h["note"]:
        lines.append(f"- Note: {h['note']}")
    lines.append("")
    return "\n".join(lines)
