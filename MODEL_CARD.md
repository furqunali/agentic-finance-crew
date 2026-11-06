# Model Card — Agentic Finance Crew

A system-level model card for the expense-approval decision system in this
repository. It describes what the system is for, how decisions are made, how
it was evaluated, and where its limits are. Per-decision transparency is
provided by the **decision record** endpoint
(`GET /decisions/{id}/explanation`, JSON or `?format=markdown`).

| | |
|---|---|
| **System** | Agentic Finance Crew — multi-agent expense triage behind a deterministic policy guardrail |
| **Version** | 1.0.0 (`model_version` on every record, e.g. `local@1.0.0`, `crewai:gpt-4o-mini@1.0.0`) |
| **Engines** | `local` (deterministic, default) · `langgraph` (deterministic state graph) · `crewai` (LLM agents, opt-in) |
| **Decision maker** | The deterministic `decide()` guardrail — in every engine |
| **Owner / contact** | Furqan Ali (repository maintainer) |
| **License** | MIT |

## How a decision is made

1. **Intake** validates and normalizes the request (id, employee, amount range, category).
2. **Input guard** screens every free-text field for prompt injection and redacts PII.
3. **Policy Analyst** applies the spend policy: category limit, receipt rule, human-review limit, duplicate check, risk score (0–100).
4. **Approver + guardrail** — `decide()` routes the request:
   - invalid intake → `rejected`;
   - any policy violation, guard finding, risk ≥ 60, or amount over the human-review limit → `needs_human_review`;
   - compliant, low-risk, within the auto-approve limit → `auto_approved`;
   - otherwise → `needs_human_review`.

With the `crewai` engine an LLM writes an explanatory narrative that is
appended to the rationale (prefixed `Crew rationale:`). **The LLM never
changes the outcome** — all three engines produce identical verdicts (a parity
test enforces this).

## Intended use

- Triage of **employee expense / reimbursement requests** in a finance back
  office: auto-approve the small, compliant, low-risk majority and route
  everything else to a human approver with a clear reason.
- Producing an auditable record of each decision (rules fired, agent steps,
  who approved, when) for finance, audit and compliance teams.
- A reference architecture for governed agentic AI: "the model advises,
  policy decides", human-in-the-loop, audit trail, evaluation gate.

Intended users: finance managers (reviewers), auditors (read-only oversight),
employees (submitters), administrators. AI assistants may submit and read via
the MCP server but cannot approve or reject.

## Out-of-scope use

- **Rejecting or penalizing people.** The system only auto-rejects
  structurally invalid requests (e.g. non-positive amount); it must not be
  used to deny legitimate claims without human review.
- **Performance evaluation, disciplinary action, fraud accusations, or any
  employment decision** about an individual (see EU AI Act section below —
  this would change the risk classification).
- Credit, lending, insurance, payroll or tax decisions.
- Unattended use with a real organization's policy **without** reconfiguring
  and re-evaluating `SpendPolicy` (the bundled policy is fictional).
- Treating the LLM narrative (`Crew rationale`) as authoritative.

## Limitations

- **Fictional demo policy.** Limits in `config.SpendPolicy` are illustrative.
- **Currency-agnostic thresholds.** Limits are compared to `amount` as a
  number; there is no FX conversion.
- **Duplicate detection is exact and history-bound**: same employee, amount
  and category, only against the history supplied (earlier items in a batch).
  A single `/approve` call has no history, so cross-request duplicates are
  not detected there.
- **Confidence is not a calibrated probability** — it is a fixed value per
  decision branch (0.95 / 0.9 / 0.85 / 0.8).
- **Input guard is heuristic.** Phrase-level patterns catch common prompt
  injection; novel phrasings can evade it. Its failure mode is bounded: the
  LLM cannot authorize spend, and a flag only costs a human review.
- **The benchmark is synthetic** and measures conformance to the intended
  policy, not real-world fraud detection or LLM narrative quality.
- **LLM narratives** (crewai engine) may be inaccurate or incomplete; they
  are explanatory only.
- Rate limiting is per process; multi-replica deployments need an
  ingress-level limiter for a global budget.

## Human oversight

- Every request that is not small, compliant and low-risk goes to a
  **review queue**; a Finance Manager or Admin approves or rejects it
  (`POST /decisions/{id}/approve|reject`). The approver's identity is taken
  from the JWT, never the request body.
- The machine verdict is **never overwritten**: the record keeps both what
  the AI recommended and what the human decided.
- Suspected prompt-injection attempts are always routed to a human.
- There is **no automated path** (API, agent or MCP tool) that approves a
  review item without a human.
- Auditors have read-only access to all decisions, the global audit log and
  each decision record. Thresholds are configurable so an organization can
  widen human review at any time.

## Data handling

- **Stored per decision:** request id, employee name, requester, category,
  amount, currency, verdict, rules fired, risk, confidence, rationale,
  engine/model version, latency/tokens/cost, status, resolver, timestamps,
  and an append-only audit trail. The free-text **description is not stored**.
- **PII redaction:** emails, phone numbers, payment cards (Luhn), IBANs and
  national-ID-like numbers are redacted from text sent to an LLM and from
  logs; the audit trail records only *which kinds* of PII were redacted.
  Decision records are PII-redacted on export.
- **LLM providers** (crewai engine only) receive the fenced, sanitized
  request summary; flagged fields are withheld entirely. The default engines
  send nothing to any third party.
- **Storage:** SQLite (dev) or PostgreSQL (prod) via `DATABASE_URL`.
  Retention and deletion are the deploying organization's responsibility.
- **Secrets** come only from the environment; nothing is hard-coded.
- **Repository data is fully synthetic** — no real people or financial data.

## Evaluation

Reproducible benchmark (`python run_eval.py --n 1000`, seed 42, engine
`local`): 1,000 synthetic cases, labelled by an **independent policy oracle**
(not the system's own `decide()`).

| Metric | Result |
|--------|--------|
| Decision accuracy | **100.00%** |
| False approvals (auto-approved something policy blocks) | **0** |
| False rejections · over-escalations | 0 · 0 |
| Auto-approved / escalated / rejected | 43.1% / 52.1% / 4.8% |
| Policy-violation detection (P / R / F1) | 1.000 / 1.000 / 1.000 |
| Duplicate detection (P / R / F1) | 1.000 / 1.000 / 1.000 |
| Latency (ms) mean / p95 | ~2.1 / ~3.9 (machine-dependent) |
| LLM tokens / cost | 0 / $0.00 (deterministic engine) |

- **CI safety gate:** every push runs `run_eval.py --n 300 --check`, which
  fails the build on any false approval or accuracy below 0.99.
- **Tests:** the full pytest suite (domain rules, engine parity, API, RBAC,
  audit trail, input guard incl. no-false-positive cases, rate limiting, MCP
  server, decision records) runs on Python 3.10–3.12 with no API keys.
- **Not evaluated:** the quality of LLM narratives from the crewai engine, and
  behaviour on real organizational data.

## Risk classification (EU AI Act, Regulation (EU) 2024/1689)

_This is the maintainer's engineering assessment to support a deployer's own
analysis — not legal advice._

1. **Is it an AI system (Art. 3(1))?** In the default `local` / `langgraph`
   engines the decision logic consists of rules written by people, with no
   learned inference — arguably outside the definition. The `crewai` engine
   uses an LLM, so a deployment with it should be treated as an AI system.
2. **Prohibited practices (Art. 5)?** None apply: no manipulation, social
   scoring, biometric or emotion recognition.
3. **High-risk (Art. 6, Annex III)?** The closest category is Annex III
   point 4(b) — systems making decisions affecting terms of work-related
   relationships or monitoring/evaluating workers' behaviour. As designed,
   the system routes expense claims for an existing reimbursement process; it
   does not evaluate people, and the LLM only explains. Under Art. 6(3) this
   fits the derogations for a **narrow procedural / preparatory task** that
   does not materially influence the outcome (every adverse or uncertain case
   goes to a human). It does not profile natural persons (the risk score is
   per request, not per person). **Assessment: not high-risk in the intended
   use**; a deployer relying on Art. 6(3) should document that assessment
   (Art. 6(4)).
4. **When it would become high-risk:** using outputs, history or risk scores
   to evaluate employees' performance or behaviour, to support disciplinary
   action or termination, or to profile individuals. That moves the system
   into Annex III 4(b) with the full high-risk obligations (risk management,
   data governance, logging, human oversight, accuracy/robustness,
   registration).
5. **Transparency and literacy:** people affected can be given the per-decision
   record (`/decisions/{id}/explanation`); LLM-written text is labelled as
   such (`Crew rationale:`); deployers should ensure staff operating the
   system have adequate AI literacy (Art. 4).

Controls already in place that map to high-risk-style requirements: human
oversight by default, append-only logging (audit trail + model version),
evaluation with a CI safety gate, input robustness (injection guard), data
minimization (no stored descriptions, PII redaction), and RBAC.

## Per-decision transparency

```bash
curl -s http://localhost:8000/decisions/7/explanation -H "Authorization: Bearer $TOKEN"
curl -s "http://localhost:8000/decisions/7/explanation?format=markdown" -H "Authorization: Bearer $TOKEN"
```

Each decision record (`afc.decision-record/v1`) contains: a redacted inputs
summary, the policy rules evaluated and fired, input-guard findings, every
agent step with actor and timestamp, the final decision with engine/model
version, who approved or rejected it and when, and operational data
(latency, tokens, cost). Auditors, Finance Managers and Admins can access it.
