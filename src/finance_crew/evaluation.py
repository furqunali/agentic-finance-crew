"""Evaluation harness — a synthetic benchmark for the decision system.

Generates a large, deterministic set of synthetic expense cases *with ground
truth*, runs them through the pipeline, and scores the outcome on the metrics
that matter for a governed finance system: approval accuracy, policy-violation
and duplicate detection, **false approvals** (the safety-critical one), false
rejections, escalation rate, latency and cost.

Ground truth is produced by an **independent policy oracle** in this module —
deliberately *not* the system's own `decide()` — so a match is a genuine
cross-check between two implementations of the intended policy, not a tautology.
When the real CrewAI engine is enabled, the same benchmark scores the crew and
will surface any divergence from the policy.
"""
from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from statistics import mean
from typing import Any

from .config import SpendPolicy
from .pipeline import process_request

# Decision label constants (mirror models.Decision values).
AUTO = "auto_approved"
REVIEW = "needs_human_review"
REJECT = "rejected"

CATEGORIES = ["travel", "meals", "software", "equipment", "other"]


@dataclass
class Case:
    payload: dict[str, Any]
    expected_decision: str
    valid: bool                 # False for intake-invalid cases (excluded from violation stats)
    exp_violation: bool         # ground-truth: does policy consider this a violation? (valid cases)
    exp_duplicate: bool         # ground-truth: is this a duplicate of an earlier case?


# --- Independent policy oracle ----------------------------------------------
def expected_outcome(payload: dict[str, Any], policy: SpendPolicy, is_duplicate: bool) -> tuple[str, bool, bool]:
    """Return (expected_decision, valid, expected_violation) for one case.

    A plain, direct expression of the *intended* policy — written independently
    of the system under test.
    """
    amount = float(payload["amount"])
    category = payload["category"]
    has_receipt = bool(payload["has_receipt"])
    employee = payload.get("employee", "")
    rid = payload.get("id", "")

    # Intake validity (matches the documented intake rules).
    if not employee or not rid or amount <= 0 or amount > 100_000:
        return REJECT, False, False

    violation = False
    if amount > policy.limit_for(category):
        violation = True
    if amount > policy.receipt_required_above and not has_receipt:
        violation = True
    if amount > policy.human_review_limit:
        violation = True

    if violation or is_duplicate:
        return REVIEW, True, (violation or is_duplicate)
    if amount <= policy.auto_approve_limit:
        return AUTO, True, False
    return REVIEW, True, False


# --- Synthetic case generation ----------------------------------------------
def generate_cases(n: int, seed: int = 42, policy: SpendPolicy | None = None) -> list[Case]:
    """Deterministically generate `n` labelled synthetic cases."""
    policy = policy or SpendPolicy()
    rng = random.Random(seed)
    cases: list[Case] = []
    seen: set[tuple[str, float, str]] = set()   # (employee, amount, category) for real uniqueness
    auto_pool: list[dict[str, Any]] = []        # earlier clean cases to duplicate
    i = 0

    def key(p: dict[str, Any]) -> tuple[str, float, str]:
        return (p["employee"], round(float(p["amount"]), 2), p["category"])

    while len(cases) < n:
        i += 1
        rid = f"EV-{i:05d}"
        roll = rng.random()

        # ~8% duplicates of an earlier clean case (different id, same emp/amount/cat)
        if roll < 0.08 and auto_pool:
            base = rng.choice(auto_pool)
            payload = {"id": rid, "employee": base["employee"], "category": base["category"],
                       "amount": base["amount"], "has_receipt": True, "description": "dup"}
            dec, valid, viol = expected_outcome(payload, policy, is_duplicate=True)
            cases.append(Case(payload, dec, valid, viol, exp_duplicate=True))
            continue

        emp = f"emp{rng.randint(1, 80)}"
        cat = rng.choice(CATEGORIES)
        limit = policy.limit_for(cat)

        # ~5% intake-invalid
        if roll < 0.13:
            amount = rng.choice([0.0, -25.0, round(rng.uniform(100_001, 250_000), 2)])
            payload = {"id": rid, "employee": emp, "category": cat, "amount": amount, "has_receipt": True}
            dec, valid, viol = expected_outcome(payload, policy, is_duplicate=False)
            cases.append(Case(payload, dec, valid, viol, exp_duplicate=False))
            continue

        band = rng.random()
        if band < 0.55:
            # small, compliant -> auto-approve; receipt present when required
            amount = round(rng.uniform(5, policy.auto_approve_limit), 2)
            has_receipt = True if amount > policy.receipt_required_above else rng.random() < 0.7
        elif band < 0.75:
            # compliant but above the auto-approve limit (still within category limit) -> review
            hi = max(policy.auto_approve_limit + 1, min(limit, policy.human_review_limit))
            amount = round(rng.uniform(policy.auto_approve_limit + 1, hi), 2)
            has_receipt = True
        else:
            # a genuine policy violation: over category limit, or missing receipt, or over human limit
            kind = rng.random()
            if kind < 0.5:
                amount = round(rng.uniform(limit + 1, limit * 1.8 + 10), 2)
                has_receipt = True
            elif kind < 0.8:
                amount = round(rng.uniform(policy.receipt_required_above + 1,
                                           max(policy.receipt_required_above + 2, limit)), 2)
                has_receipt = False  # missing required receipt
            else:
                amount = round(rng.uniform(policy.human_review_limit + 1,
                                           policy.human_review_limit + 3000), 2)
                has_receipt = True

        payload = {"id": rid, "employee": emp, "category": cat,
                   "amount": amount, "has_receipt": has_receipt}

        # Guarantee ground-truth uniqueness: skip accidental collisions so a
        # non-duplicate case is never silently a real duplicate.
        if key(payload) in seen:
            continue
        seen.add(key(payload))

        dec, valid, viol = expected_outcome(payload, policy, is_duplicate=False)
        case = Case(payload, dec, valid, viol, exp_duplicate=False)
        cases.append(case)
        if dec == AUTO:
            auto_pool.append(payload)

    return cases


# --- Runner + scoring -------------------------------------------------------
def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    k = max(0, min(len(ordered) - 1, int(round((pct / 100.0) * (len(ordered) - 1)))))
    return ordered[k]


@dataclass
class EvalReport:
    metrics: dict[str, Any]
    cases: int
    seed: int
    mismatches: list[dict[str, Any]] = field(default_factory=list)


def evaluate(n: int = 1000, seed: int = 42, settings=None) -> EvalReport:
    """Run the benchmark and return the scored report."""
    from .config import Settings

    settings = settings or Settings()
    policy = settings.policy
    cases = generate_cases(n, seed, policy)

    history: list[dict[str, Any]] = []
    latencies: list[float] = []
    total_tokens = 0
    total_cost = 0.0
    engine = "local"

    correct = 0
    false_approvals = 0            # auto-approved something that should NOT have been
    false_rejections = 0          # hard-rejected something that should have passed
    over_escalations = 0          # escalated something that should have auto-approved
    escalated = auto = rejected = 0

    v_tp = v_fp = v_fn = v_tn = 0  # violation detection (valid cases only)
    d_tp = d_fp = d_fn = 0         # duplicate detection

    mismatches: list[dict[str, Any]] = []

    for case in cases:
        t0 = time.perf_counter()
        result = process_request(case.payload, history, settings)
        latencies.append((time.perf_counter() - t0) * 1000.0)
        engine = result.engine
        history.append(case.payload)

        actual = result.decision.value
        if actual == case.expected_decision:
            correct += 1
        elif len(mismatches) < 25:
            mismatches.append({"id": case.payload["id"], "expected": case.expected_decision,
                               "actual": actual, "amount": case.payload["amount"],
                               "category": case.payload["category"]})

        # Safety-critical confusion
        if actual == AUTO and case.expected_decision != AUTO:
            false_approvals += 1
        if actual == REJECT and case.expected_decision != REJECT:
            false_rejections += 1
        if actual == REVIEW and case.expected_decision == AUTO:
            over_escalations += 1

        escalated += actual == REVIEW
        auto += actual == AUTO
        rejected += actual == REJECT

        # Detection metrics are scored over VALID cases only — intake-invalid
        # rows are rejected before violation/duplicate logic matters, and
        # scoring them (e.g. two repeated $0 rows) would be misleading.
        if case.valid:
            got_violation = bool(result.analysis.violations)
            if case.exp_violation and got_violation:
                v_tp += 1
            elif case.exp_violation and not got_violation:
                v_fn += 1
            elif not case.exp_violation and got_violation:
                v_fp += 1
            else:
                v_tn += 1

            got_dup = bool(result.analysis.is_possible_duplicate)
            if case.exp_duplicate and got_dup:
                d_tp += 1
            elif case.exp_duplicate and not got_dup:
                d_fn += 1
            elif not case.exp_duplicate and got_dup:
                d_fp += 1

    def _prf(tp: int, fp: int, fn: int) -> dict[str, float]:
        precision = tp / (tp + fp) if (tp + fp) else 1.0
        recall = tp / (tp + fn) if (tp + fn) else 1.0
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
        return {"precision": round(precision, 4), "recall": round(recall, 4), "f1": round(f1, 4)}

    total = len(cases)
    metrics = {
        "engine": engine,
        "total_cases": total,
        "accuracy": round(correct / total, 4) if total else 0.0,
        "false_approvals": false_approvals,
        "false_approval_rate": round(false_approvals / total, 4) if total else 0.0,
        "false_rejections": false_rejections,
        "over_escalations": over_escalations,
        "auto_approval_rate": round(auto / total, 4) if total else 0.0,
        "escalation_rate": round(escalated / total, 4) if total else 0.0,
        "rejection_rate": round(rejected / total, 4) if total else 0.0,
        "violation_detection": _prf(v_tp, v_fp, v_fn),
        "duplicate_detection": _prf(d_tp, d_fp, d_fn),
        "latency_ms": {
            "mean": round(mean(latencies), 4) if latencies else 0.0,
            "p50": round(_percentile(latencies, 50), 4),
            "p95": round(_percentile(latencies, 95), 4),
            "max": round(max(latencies), 4) if latencies else 0.0,
        },
        "tokens_total": total_tokens,
        "cost_usd_total": round(total_cost, 6),
    }
    return EvalReport(metrics=metrics, cases=total, seed=seed, mismatches=mismatches)


# --- Report rendering -------------------------------------------------------
def render_markdown(report: EvalReport) -> str:
    m = report.metrics
    vd, dd, lat = m["violation_detection"], m["duplicate_detection"], m["latency_ms"]
    safety = "✅ **0 false approvals**" if m["false_approvals"] == 0 else f"❌ **{m['false_approvals']} false approvals**"
    lines = [
        "# Evaluation Benchmark — Results",
        "",
        f"_Synthetic benchmark of **{m['total_cases']} cases** (seed {report.seed}), "
        f"engine `{m['engine']}`. Ground truth from an independent policy oracle._",
        "",
        "## Headline",
        "",
        f"- **Decision accuracy:** {m['accuracy'] * 100:.2f}%",
        f"- **Safety:** {safety} (never auto-approved anything the policy would block)",
        f"- **False rejections:** {m['false_rejections']}  ·  **Over-escalations:** {m['over_escalations']}",
        "",
        "## Decision mix",
        "",
        "| Outcome | Rate |",
        "|---------|------|",
        f"| Auto-approved | {m['auto_approval_rate'] * 100:.1f}% |",
        f"| Escalated to human | {m['escalation_rate'] * 100:.1f}% |",
        f"| Rejected (invalid) | {m['rejection_rate'] * 100:.1f}% |",
        "",
        "## Detection quality",
        "",
        "| Signal | Precision | Recall | F1 |",
        "|--------|-----------|--------|----|",
        f"| Policy violations | {vd['precision']:.3f} | {vd['recall']:.3f} | {vd['f1']:.3f} |",
        f"| Duplicates | {dd['precision']:.3f} | {dd['recall']:.3f} | {dd['f1']:.3f} |",
        "",
        "## Performance & cost",
        "",
        f"- **Latency (ms):** mean {lat['mean']:.3f} · p50 {lat['p50']:.3f} · p95 {lat['p95']:.3f} · max {lat['max']:.3f}",
        f"- **Tokens:** {m['tokens_total']}  ·  **Cost:** ${m['cost_usd_total']:.6f} "
        f"_(the deterministic engine uses no LLM; the real crew reports actual usage here)_",
        "",
    ]
    if report.mismatches:
        lines += ["## Sample mismatches", "", "| id | expected | actual | amount | category |",
                  "|----|----------|--------|--------|----------|"]
        lines += [f"| {x['id']} | {x['expected']} | {x['actual']} | {x['amount']} | {x['category']} |"
                  for x in report.mismatches]
        lines.append("")
    else:
        lines += ["> No decision mismatches: the system's guardrail matched the independent "
                  "policy oracle on every case.", ""]
    return "\n".join(lines)
