# 💼 Agentic Finance Crew

*A multi-agent **CrewAI** system that triages finance/ops expense requests — Intake → Policy Analyst → Approving Manager — with a deterministic policy guardrail and human-in-the-loop escalation.*

### 🔗 [**Live interactive demo »**](https://agentic-finance-crew-deploy.vercel.app)  ·  [🤗 Hugging Face Space](https://huggingface.co/spaces/FurqanAli12345/agentic-finance-crew)  ·  [Source](https://github.com/furqunali/agentic-finance-crew)

<p>
  <a href="https://github.com/furqunali/agentic-finance-crew/actions/workflows/ci.yml"><img src="https://github.com/furqunali/agentic-finance-crew/actions/workflows/ci.yml/badge.svg" alt="CI — tests"></a>
  <a href="https://agentic-finance-crew-deploy.vercel.app"><img src="https://img.shields.io/badge/🟢_Live_Demo-0d9488?style=flat-square" alt="Live demo"></a>
  <img src="https://img.shields.io/badge/CrewAI-multi--agent-0d9488?style=flat-square" alt="CrewAI">
  <img src="https://img.shields.io/badge/LangGraph-state--graph-1c3d5a?style=flat-square" alt="LangGraph">
  <img src="https://img.shields.io/badge/FastAPI-service-009688?style=flat-square&logo=fastapi&logoColor=white" alt="FastAPI">
  <img src="https://img.shields.io/badge/Docker-containerized-2496ED?style=flat-square&logo=docker&logoColor=white" alt="Docker">
  <img src="https://img.shields.io/badge/Kubernetes-ready-326CE5?style=flat-square&logo=kubernetes&logoColor=white" alt="Kubernetes">
  <img src="https://img.shields.io/badge/PostgreSQL-persisted-336791?style=flat-square&logo=postgresql&logoColor=white" alt="PostgreSQL">
  <img src="https://img.shields.io/badge/Auth-JWT%20%2B%20RBAC-000000?style=flat-square&logo=jsonwebtokens&logoColor=white" alt="JWT + RBAC">
  <img src="https://img.shields.io/badge/Observability-Prometheus-E6522C?style=flat-square&logo=prometheus&logoColor=white" alt="Prometheus">
  <img src="https://img.shields.io/badge/benchmark-1000%20cases%20·%20100%25%20·%200%20false%20approvals-0d9488?style=flat-square" alt="benchmark">
  <img src="https://img.shields.io/badge/red%20team-61%20attacks%20×%203%20engines%20·%200%20unauthorized%20approvals-b91c1c?style=flat-square" alt="red team">
  <img src="https://img.shields.io/badge/UI-web%20console-1c3d5a?style=flat-square" alt="web console">
  <img src="https://img.shields.io/badge/tests-265%20passing-2ea44f?style=flat-square" alt="tests">
  <img src="https://img.shields.io/badge/license-MIT-blue?style=flat-square" alt="MIT">
</p>

---

## 📋 For reviewers — the 2-minute version

| | |
|---|---|
| **What it is** | A multi-agent (CrewAI / LangGraph) system that triages company expense requests: auto-approve the small and compliant, send everything else to a named human. |
| **Safety thesis** | *The model advises; deterministic code decides; a human signs anything that matters.* No LLM output, tool call or API payload can approve spend that policy forbids — and nobody can sign off their own expense. |
| **Strongest evidence** | Adversarial **red-team suite: 61 attacks × 3 engines (including the real CrewAI path driven by a hostile model that always says "approve") → 0 unauthorized approvals / 129**, down from **48** before this hardening. 1,000-case benchmark: **0 false approvals**. **265 tests**. Both safety numbers are **CI gates** — a regression cannot merge. |
| **Read next** | [🛡️ Safety approach](#️-safety-approach) · [🔬 Supporting evidence](#-supporting-evidence) · [⚠️ Limitations](#️-limitations) · [MODEL_CARD.md](MODEL_CARD.md) · [benchmark/REDTEAM.md](benchmark/REDTEAM.md) |

Everything below runs **offline with no API key** (`pip install -e ".[dev]" && pytest -q && python run_redteam.py`).

---

## 🎯 Problem

Finance teams drown in a high-volume, low-judgement task: reviewing expense and reimbursement requests. Most are small and compliant and *should* be auto-approved; a few breach policy, lack receipts, or are duplicates and need a human. Doing this by hand is slow and inconsistent — but handing it entirely to an LLM is unsafe, because **a model must never be the thing that authorizes spend**.

## 💡 Solution

A crew of three specialist AI agents that mirror a real finance back-office, wrapped around a **hard policy guardrail**:

| Agent | Responsibility |
|-------|----------------|
| 🧾 **Intake Officer** | Validates & normalizes each request; catches malformed/incomplete data early |
| 📊 **Policy Analyst** | Checks spend limits, receipt rules & duplicates; quantifies a 0–100 risk score |
| ✅ **Approving Manager** | Recommends `AUTO_APPROVED` / `NEEDS_HUMAN_REVIEW` / `REJECTED` with an auditable rationale |

The agents **explain and enrich** the decision; a deterministic rule engine **makes** it. The LLM can never approve something policy forbids — it can only reason about it. Anything risky is escalated to a human (the classic **human-in-the-loop** pattern).

## 🛡️ Safety approach

**Goal:** an AI system that is useful on the boring majority of requests but **cannot take an unauthorized or irreversible action** on the rest.

### What the system is — and is not — allowed to do

- **It cannot move money.** There is no payment, transfer or ledger-posting code. Its only output is a recorded *decision*.
- **Its only autonomous action** is to mark a request `AUTO_APPROVED`, and only when **all** of these hold (`decision.py`, `tools.py`):
  valid amount and identity · a *recognized* category · within that category's limit · ≤ **$200** (auto-approve limit) ·
  receipt present above $50 · not a duplicate · not part of a same-day split purchase · no prompt-injection finding · risk score < 60.
- **Everything else is routed to a human** (review queue) or rejected outright (invalid input). Above **$2,000** a human *always* decides.
- **A human approval is a deliberate, attributable act:** it needs a JWT with the Finance Manager or Admin role, the approver's identity comes from the token (never the request body), **you cannot approve or reject your own submission** (separation of duties), and **above $5,000 two different reviewers must approve** (dual control). Every step is written to a **hash-chained, tamper-evident** audit trail next to — never over — the machine's verdict.
- **Agents have no write capability.** The LLM agents produce narrative only; the MCP server exposes *submit* and *read* tools but **no approve/reject tool**.

### Threat model → control → proof

| # | Threat | Control | Where | Proof |
|---|---|---|---|---|
| 1 | The LLM hallucinates, or is manipulated into, "approve" | Verdict is computed by the deterministic `decide()` guardrail; the crew's text is only appended as a rationale | `decision.py`, `crew.py` | `tests/test_safety.py::test_hostile_llm_cannot_approve`; red-team engine `crewai+hostile-llm` |
| 2 | Prompt injection in free-text fields (OWASP LLM01) | Input guard flags instruction/role override, exfiltration, tool/verdict smuggling, hidden Unicode → **human review**; flagged text never reaches the prompt | `guard.py`, `tools.analyze` | `tests/test_guard.py`; red team: **54/54 injections flagged** |
| 3 | Excessive agency (OWASP LLM06) — an agent or assistant approves | No approve tool for agents or MCP clients; approval endpoints are human-only behind RBAC | `mcp_server.py`, `app.py` | `tests/test_mcp_server.py`, `tests/test_auth.py` |
| 4 | Unauthorized, self-interested or single-person approval of large spend | JWT + RBAC (4 roles); approver from token; **separation of duties** (403 on self-approval); **dual control** — above $5,000 two *different* reviewers must approve, one reject ends it | `auth.py`, `service.resolve_decision` | `tests/test_safety.py`, `tests/test_controls.py` (dual control), `tests/test_auth.py` |
| 5 | Policy evasion through malformed input — `"false"` receipt flag, `NaN`/boolean amounts, disguised or homoglyph categories | **Fail-closed parsing**: strict booleans, finite numbers only, NFKC + format-char stripping, unknown category → human | `models.py`, `tools.py` | red-team families *numeric*, *receipt-flag*, *category evasion* |
| 6 | Structuring and duplicate resubmission — in one batch **or across separate calls and days** | Same-day split-purchase detection; duplicate check on a normalized identity (case, spacing, Unicode); every new request is also checked against the employee's **stored decisions** (90-day look-back, configurable) | `tools.py`, `service.stored_history` | red-team families *split purchase*, *duplicate evasion*; `tests/test_controls.py` (cross-call) |
| 7 | Tampering / deniability after the fact | **Tamper-evident ledger**: each decision's write-once fields are hashed; every audit event is SHA-256 **hash-chained** to the previous one and anchored to the decision; `GET /audit/verify` re-derives everything and returns a **ledger root** to keep outside the database | `integrity.py`, `repository.add_audit_event` | `tests/test_controls.py` — edits, deleted events, truncation and rewritten approvers are all detected |
| 8 | Smuggled decision fields in the payload (`"decision": "auto_approved"`) | Unknown fields are dropped at the boundary; the verdict is always recomputed | `models.from_dict` | red-team family *field smuggling* |
| 9 | Abuse / brute force | Per-client rate limiting incl. login | `ratelimit.py` | `tests/test_ratelimit.py` |
| 10 | A future change silently weakens safety | **Two CI gates** on every push: benchmark (0 false approvals) and red team (0 unauthorized approvals) | `.github/workflows/ci.yml` | CI run summary |

**Design rule behind all of it: fail closed.** When the system is unsure — unparseable flag, unknown category, injection pattern, high risk — the request goes to a human. The cost of a mistake is one extra review, never an unauthorized approval.

## 🔬 Supporting evidence

All numbers below are reproducible on a laptop with no API key.

| Evidence | Result | Reproduce |
|---|---|---|
| **Red-team suite** — 61 hand-written attacks in 10 families × 3 engines (`local`, `langgraph`, `crewai+hostile-llm`) | **0 / 129 unauthorized approvals**, **54 / 54 injections flagged**, 183 / 183 runs pass, engines agree on every attack. The 129 runs are every **policy-violating** attack across the 3 engines — all 8 such families, **including the 12 "injection + violation" runs** — and are what the unauthorized-approval metric counts. The 54 **injection-only** runs (policy-compliant requests carrying a prompt injection) are excluded from it and measured separately by the 54 / 54 injection-detection metric. 183 = 129 + 54. | `python run_redteam.py --check` → [`benchmark/REDTEAM.md`](benchmark/REDTEAM.md) |
| **Evaluation benchmark** — 1,000 **synthetic** cases on the deterministic engine, ground truth from an independent policy oracle (policy conformance, not real-world accuracy) | **100% accuracy, 0 false approvals**, violation & duplicate F1 = 1.0 | `python run_eval.py --check` → [`benchmark/RESULTS.md`](benchmark/RESULTS.md) |
| **Tamper evidence** | Editing a decision, editing / deleting / truncating audit events, or rewriting who approved — **all detected** | `pytest tests/test_controls.py` · `GET /audit/verify` |
| **Test suite** | **265 tests** — guardrail, engines, API, RBAC, separation of duties, dual control, hash-chained audit, cross-call history checks, input guard, MCP, rate limiting, decision records, hostile-LLM | `pytest -q` |
| **CI** | Python 3.10–3.12, Postgres integration, Docker build, **both safety gates** | [Actions](https://github.com/furqunali/agentic-finance-crew/actions/workflows/ci.yml) |
| **Live demo** | Key-free local engine | [agentic-finance-crew-deploy.vercel.app](https://agentic-finance-crew-deploy.vercel.app) |
| **Transparency** | Model card + per-decision explainable record (`/decisions/{id}/explanation`) | [`MODEL_CARD.md`](MODEL_CARD.md) |

### The red team found real holes — and they are fixed

_Denominators:_ The 129 runs are every **policy-violating** attack across the 3 engines — all 8 such families, **including the 12 "injection + violation" runs** — and are what the unauthorized-approval metric counts. The 54 **injection-only** runs (policy-compliant requests carrying a prompt injection) are excluded from it and measured separately by the 54 / 54 injection-detection metric. 183 = 129 + 54.

The same suite was run against the previous release (`855f5d9`, kept as [`benchmark/redteam-baseline-855f5d9.json`](benchmark/redteam-baseline-855f5d9.json)) before hardening:

| Attack family (runs across 3 engines) | Unauthorized approvals before | After | Fix |
|---|---:|---:|---|
| Receipt-flag tricks — `"false"`, `"no"`, `"0"` read as *true* (21) | 15 | **0** | Strict, fail-closed boolean parsing |
| Category evasion — "Meals & entertainment", Cyrillic `а`, fullwidth `ｍｅａｌｓ` (21) | 12 | **0** | Unknown category → human; NFKC + format-char normalization |
| Split purchase — one purchase as several sub-$200 requests (9) | 9 | **0** | Same-day employee + category total checked against the limit |
| Duplicate evasion — `"d. novak"`, trailing spaces (18) | 9 | **0** | Duplicate check on a normalized identity |
| Numeric tricks — boolean amount `true` became $1.00 (27) | 3 | **0** | Booleans and non-finite numbers refused (`422`) |
| `NaN` amount crashed the request (500) | 6 crashes | **0** | Clean validation error |
| Injection: `"decision": "auto_approved"` not flagged (flag runs) | 3 missed | **0** | Guard pattern covers quoted JSON verdicts |
| **Total** | **48 / 129** | **0 / 129** | |

Plus controls the red team does not cover by itself, each added and tested: **separation of duties** (no self-approval, `403`), **dual control** above $5,000, **cross-call duplicate / split checks** against stored history, and a **tamper-evident, hash-chained audit trail** with `GET /audit/verify`.

## ⚠️ Limitations

Agentic Finance Crew is a prototype for governed expense-decision workflows. Its safety controls reduce risk; they do not eliminate every possible failure. Honest boundaries of what has and hasn't been shown:

- **Synthetic data, fictional policy.** No real financial data, no production deployment. The benchmark measures conformance to the written policy, not real-world fraud detection.
- **The real LLM is not benchmarked in CI.** CI has no API key; the red team drives the real CrewAI code path with a *hostile stand-in model*. That proves the guardrail holds against the worst-case output — it does not measure the quality or honesty of a real model's narrative.
- **Misleading narratives reach humans.** A manipulated model can't approve anything, but its rationale is shown to reviewers and could nudge them (automation bias). Mitigation today: the verdict and rules fired are shown separately from the narrative.
- **The input guard is heuristic.** Pattern- and Unicode-based; novel paraphrases, other languages or encodings (e.g. base64) can slip past it. Impact is bounded — an unflagged injection still can't approve spend — but an unflagged injection does reach the model's prompt.
- **Two approvers at most.** Dual control applies above one threshold ($5,000, configurable); there are no further tiers by amount or role. Reviewers can still rubber-stamp.
- **Depends on reviewer availability.** Routed requests wait in the queue until an authorized reviewer acts; there is no escalation timer or backup approver. The system supports human accountability — it does not replace it.
- **History look-back is bounded.** Duplicates and split purchases are checked against the employee's stored decisions from the last 90 days (configurable). Split detection is same-day and same-category, and only for dated requests; a genuine retry of the same request is treated as a duplicate and sent to a human (fail closed).
- **Static thresholds**; currency-agnostic; the confidence value is per-branch, not calibrated.
- **Deployment hygiene is on the operator:** the bootstrap `admin/admin` account must be changed; `AUTH_DISABLED` (local single-user mode) turns off login **and** separation of duties; JWT is HS256 with a shared secret; no MFA; rate limits are per process.
- **Tamper evidence, not tamper proofing.** Edits, deletions and truncation are detected, but someone with full database write access could recompute every hash. That is caught only by comparing the `ledger_root` from `GET /audit/verify` with a copy kept outside the database — exporting it on a schedule is left to the operator.
- **Auto-approved decisions cannot be reopened** through the API; a clawback/reversal workflow would be needed before connecting this to a payment system.
- **Not a certified financial-control system.** Production use would need organization-specific policy configuration, a security review, integration testing, monitoring and operational sign-off.

Planned next steps are in the [Roadmap](#️-roadmap).

## 🏗️ Architecture

```mermaid
flowchart TD
    A[Expense request<br/>API / CLI / batch] --> P[Pipeline]
    P --> F{Orchestrator factory<br/>Strategy pattern}
    F -->|ENGINE=crewai + key| C[CrewAIOrchestrator]
    F -->|ENGINE=langgraph| LG[LangGraphOrchestrator]
    F -->|default · no key| L[LocalOrchestrator]

    subgraph Crew["Shared 3-stage workflow"]
      S1[🧾 Intake<br/>validate + normalize]
      S2[📊 Policy Analyst<br/>violations · risk · duplicate]
      S3[✅ Approver<br/>recommend + explain]
    end

    C --> Crew
    LG --> Crew
    L --> Crew
    Crew --> G[["decide() — policy guardrail"]]
    G --> R1[Auto-approved]
    G --> R2[Human review queue]
    G --> R3[Rejected]

    R2 --> H{Human reviewer<br/>approve / reject}
    R1 & R3 & H --> DB[(Decision store + audit trail<br/>SQLAlchemy + Alembic<br/>SQLite dev · Postgres prod)]

    T[(Shared deterministic tools<br/>policy · risk · duplicate)] -.-> S1 & S2 & S3
```

**The key design idea:** three interchangeable engines implement one `Orchestrator.process()` contract.

- **`CrewAIOrchestrator`** — the real multi-agent CrewAI crew (opt-in; needs an LLM key).
- **`LangGraphOrchestrator`** — the same workflow modeled as a **LangGraph** stateful graph (`START → intake → analyze → approve → END`); needs no LLM, so it's fully testable.
- **`LocalOrchestrator`** — a deterministic, zero-dependency engine that runs the *same* workflow with no LLM.

All three call the **same shared tools** for the hard rules, and all funnel through the **same `decide()` guardrail** — so they produce identical verdicts (verified by a parity test), differing only in *how* the workflow is orchestrated. Selecting between them is a runtime config choice (`ENGINE=...`), never a code change — so the demo, unit tests and CI run fully **without any API key**, while production can flip to the real crew with one environment variable.

## ✨ Key Features

- **Multi-agent orchestration** with CrewAI (sequential Intake → Analyst → Approver crew).
- **Policy-as-code guardrail** — spend limits, receipt rules, per-category limits and duplicate detection live in tested code, not in prompts.
- **Human-in-the-loop** routing for anything over-limit, non-compliant or high-risk — with a **review queue** and human approve/reject actions.
- **Separation of duties** — nobody can approve or reject their own submission (`403`), on top of role checks.
- **Adversarially tested** — a [red-team suite](benchmark/REDTEAM.md) of 61 attacks runs on every engine (including CrewAI driven by a hostile model) with **0 unauthorized approvals**, enforced as a CI gate.
- **Durable system-of-record** — every decision is persisted via SQLAlchemy with Alembic migrations; runs on zero-config **SQLite** in dev and **PostgreSQL** in production by flipping one env var.
- **Tamper-evident, hash-chained audit trail** — each decision logs the full lifecycle (who requested it → what the AI recommended → which rules fired → who approved it → timestamps, reason, model/version). The machine verdict is never overwritten by a human resolution.
- **Auth & RBAC** — JWT bearer tokens with four roles (**Employee / Finance Manager / Auditor / Admin**); the approver's identity comes from the token, not the request body.
- **Observability** — Prometheus metrics at `/metrics` (decisions, latency, HTTP, failures, LLM tokens/cost), structured JSON logging, and per-decision latency / token / cost stored on every record.
- **Evaluated, not just built** — a reproducible benchmark of **1,000 synthetic cases** scored against an independent policy oracle: **100% accuracy, 0 false approvals**, violation & duplicate F1 = 1.0. A CI safety gate fails the build on any false approval.
- **Web console (UI)** at `/ui` — a professional single-page app: login, role-aware nav, submit, **bulk CSV upload**, review queue (approve/reject), decisions with filters + **CSV export**, audit-trail timeline, users admin, an overview with charts, dark mode, and a 🔊 **Listen** (read-aloud) option.
- **AI transparency pack** — a [`MODEL_CARD.md`](MODEL_CARD.md) (intended / out-of-scope use, limitations, human oversight, data handling, evaluation, EU AI Act risk reasoning) and a per-decision **decision record** at `/decisions/{id}/explanation` (JSON or Markdown).
- **API rate limiting** — per-client token buckets (user / API key / IP) on every mutating endpoint, including login; `429` + `Retry-After`, counted in Prometheus. Stdlib only.
- **Prompt-injection + PII guard** — every free-text field is screened before any LLM sees it: suspected injections are routed to a human (never auto-approved) with the reason in the audit trail; emails, phones, cards, IBANs and national IDs are redacted from prompts and logs (OWASP LLM01 / LLM02).
- **MCP server** — the approval workflow as Model Context Protocol tools (JSON-RPC 2.0 over stdio, no new dependency) so AI assistants can submit expenses and query decisions — but never approve them.
- **Runs with zero secrets** via the local engine — great for demos, CI and offline dev.
- **FastAPI service** (`/auth/*`, `/approve`, `/approve/batch`, `/decisions`, `/decisions/{id}/explanation`, `/review-queue`, `/audit`, `/audit/verify`, `/metrics`, `/health`) with OpenAPI docs at `/docs` and a web console at `/ui`.
- **Fully containerized** (multi-stage, non-root, healthcheck) and **Kubernetes-ready**.
- **CI on every push** — tests across Python 3.10–3.12, a Docker build/health check, and two safety gates (benchmark + red team).

## 🧰 Tech Stack

**Python 3.11** · **CrewAI** (multi-agent) · **LangGraph** (state-graph) · **FastAPI** + **Uvicorn** · **Pydantic** · **JWT (PyJWT) + RBAC** · **SQLAlchemy 2.0** + **Alembic** · **PostgreSQL** / **SQLite** · **Prometheus** metrics · **Docker** (multi-stage) · **Kubernetes** · **GitHub Actions** · **pytest**

## 🧠 AI / Engineering Decisions

- **The model advises; policy decides.** Keeping authorization in a deterministic `decide()` function makes the system auditable and safe to run unattended — a non-negotiable in finance.
- **Strategy pattern for the engine.** The LLM is an *optional, swappable* dependency. This makes the whole system testable and runnable with no key, and avoids vendor lock-in (OpenAI or Gemini via config).
- **Rules in code, not prompts.** Spend limits and receipt policy are unit-tested pure functions, so behavior is reproducible and doesn't drift with model updates.
- **Human-in-the-loop by default** for risk — the crew optimizes throughput on the safe majority without ever silently approving the risky minority.

## 📈 Results (demo run)

Running the bundled fictional batch (`python run_demo.py`) over 8 requests:

```
[APPROVED]  EXP-1001   risk=  4  Auto-approved: $149.00 within $200.00 limit, compliant, low risk.
[APPROVED]  EXP-1002   risk= 25  Auto-approved: $85.00 within $200.00 limit, compliant, low risk.
[REVIEW]    EXP-1003   risk= 29  Compliant but $1,450.00 exceeds the $200.00 auto-approve limit.
[REVIEW]    EXP-1004   risk= 45  amount over $2,000.00 always needs human sign-off.
[REVIEW]    EXP-1005   risk=100  exceeds meals limit; receipt required over $50.00.
[REJECTED]  EXP-1006   risk=  0  failed intake validation: amount must be positive.
[REVIEW]    EXP-1007   risk= 31  receipt required for amounts over $50.00.
[REVIEW]    EXP-1008   risk= 19  possible duplicate of an earlier request.

8 processed | 2 auto-approved | 5 to human | 1 rejected
```

## 🚀 Quickstart

```bash
git clone https://github.com/furqunali/agentic-finance-crew.git
cd agentic-finance-crew
pip install -e ".[dev]"

python run_demo.py          # run the crew over the sample batch (no key needed)
pytest -q                   # 265 tests, all green
uvicorn app:app --reload    # web console at http://localhost:8000/ui · API docs at /docs
```

> Prefer `make`? `make install && make test && make demo` — see [Common tasks](#-common-tasks).

### 🐳 Docker

```bash
docker compose up --build   # API on http://localhost:8000
# or:
docker build -t agentic-finance-crew .
docker run -p 8000:8000 agentic-finance-crew
```

### ☸️ Kubernetes

```bash
kubectl apply -f k8s/        # Deployment (2 replicas, probes, non-root) + Service
```

### 🔀 Choosing an engine

Set `ENGINE` (all produce identical verdicts — they differ only in orchestration):

```bash
ENGINE=local      python run_demo.py     # deterministic, no deps, no key (default)
ENGINE=langgraph  python run_demo.py     # LangGraph state graph (pip install -e ".[langgraph]")
ENGINE=crewai     python run_demo.py     # real CrewAI crew (needs a key, see below)
```

### 🤖 Enable the real CrewAI crew

```bash
cp .env.example .env         # set USE_CREWAI=true and your OPENAI_API_KEY / GEMINI_API_KEY
pip install -e ".[crewai]"
```

## ⚙️ Configuration

Everything is driven by environment variables — the app runs fully with **none
set** (deterministic local engine, no secrets). Set these only to change the
engine or enable the real crew.

| Variable         | Default        | Values / example                          | Description |
|------------------|----------------|-------------------------------------------|-------------|
| `DATABASE_URL`   | `sqlite:///./finance_crew.db` | `postgresql+psycopg://user:pass@host/db` | Where decisions are persisted. SQLite by default; point at Postgres for production (`pip install -e ".[postgres]"`). |
| `JWT_SECRET`     | _(ephemeral)_  | long random string                        | Signing secret for JWT tokens. **Set in production** (unset ⇒ per-process dev secret, tokens don't survive restarts). |
| `JWT_EXPIRE_MINUTES` | `60`       | integer                                   | Access-token lifetime in minutes. |
| `LOG_FORMAT`     | `text`         | `text` · `json`                           | `json` emits structured logs for a log platform. |
| `LOG_LEVEL`      | `INFO`         | `DEBUG` · `INFO` · `WARNING` · …          | Root log level. |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | `admin` / `admin` | any                    | Bootstrap admin created on first run against an empty user table. **Change these.** |
| `AUTH_DISABLED`  | _(off)_        | `1` / `true`                              | Local/demo only: skip login (every request = admin). **Never in production.** `START.cmd` sets it for single-user local use. |
| `RATE_LIMIT_ENABLED` | `true`     | `true` / `false`                          | Per-client rate limiting of mutating endpoints (`POST`/`PUT`/`PATCH`/`DELETE`). |
| `RATE_LIMIT_PER_MINUTE` | `60`    | number                                    | Sustained calls per minute per client (token refill rate). |
| `RATE_LIMIT_BURST` | `20`         | integer                                   | Bucket capacity: calls a client may make back-to-back. |
| `RATE_LIMIT_TRUST_PROXY` | _(off)_ | `1` / `true`                             | Use the first `X-Forwarded-For` hop as the client IP. Only behind a proxy you control. |
| `HISTORY_LOOKBACK_DAYS` | `90` | integer (`0` = off)                      | How far back stored decisions are checked for duplicates and same-day split purchases on new requests. |
| `MCP_ACTOR`      | `mcp-client`   | any                                       | Identity recorded as `requested_by` for submissions made through the MCP server. |
| `ENGINE`         | `auto`         | `auto` · `local` · `langgraph` · `crewai` | Which orchestrator runs. `auto` picks the real crew if opted-in **and** keyed, otherwise `local`. |
| `USE_CREWAI`     | `false`        | `true` / `false`                          | Opt-in flag for the real CrewAI crew (needs a key too). |
| `LLM_PROVIDER`   | `openai`       | `openai` · `gemini`                       | LLM vendor used by the CrewAI engine. |
| `LLM_MODEL`      | `gpt-4o-mini`  | e.g. `gpt-4o-mini`, `gemini-1.5-flash`    | Model name for the chosen provider. |
| `OPENAI_API_KEY` | _(unset)_      | `sk-...`                                  | Required when `LLM_PROVIDER=openai` and the crew is enabled. |
| `GEMINI_API_KEY` | _(unset)_      | `AIza...`                                 | Required when `LLM_PROVIDER=gemini` and the crew is enabled. |

Selecting `ENGINE=crewai` without a matching key fails fast with a clear
`ConfigurationError` (surfaced as a `400` by the API) rather than a silent
fallback. See [`.env.example`](.env.example) for a copy-paste starting point.

## 🌐 API examples

Start the service with `uvicorn app:app --reload` (or `make run`), then:

```bash
# Single request
curl -s http://localhost:8000/approve \
  -H "Content-Type: application/json" \
  -d '{"id":"EXP-1001","employee":"A. Rivera","category":"software","amount":149,"has_receipt":true}'
# -> {"request_id":"EXP-1001","decision":"auto_approved","risk_score":4, ...}

# Batch (earlier items become history, so duplicates are flagged)
curl -s http://localhost:8000/approve/batch \
  -H "Content-Type: application/json" \
  -d '[{"id":"EXP-1","employee":"E","category":"software","amount":149,"has_receipt":true},
       {"id":"EXP-2","employee":"E","category":"meals","amount":180}]'

# Health / active engine
curl -s http://localhost:8000/health   # -> {"status":"ok","engine":"local"}

# Persisted decision history (every /approve is written to the database)
curl -s "http://localhost:8000/decisions?limit=20&decision=needs_human_review"
curl -s http://localhost:8000/decisions/1      # one record by stored id
```

Every `/approve` response now carries a `record_id` pointing at the stored row.
Interactive OpenAPI docs are always at [`/docs`](http://localhost:8000/docs).
Malformed payloads return a clean `422`; an empty or oversized batch is
rejected before any work runs.

## 🧩 MCP server (use it from AI assistants)

The approval workflow is also exposed over the **Model Context Protocol**, so an
MCP client (Claude Desktop, an IDE agent, any MCP-capable assistant) can submit
expenses and query decisions as tools. It is a dependency-free **JSON-RPC 2.0
over stdio** server (`initialize`, `tools/list`, `tools/call`, `ping`, standard
error codes) and runs key-free on the local engine.

| Tool | What it does |
|------|--------------|
| `submit_expense_request` | Runs the crew + `decide()` guardrail, persists the decision and audit trail, returns decision, risk score and reasons (rules fired) |
| `get_decision` | Latest stored decision for a business `request_id` (status, rules, rationale, resolver) |
| `list_pending_approvals` | The human review queue, oldest first |
| `get_policy` | The active spend policy (limits, receipt threshold, per-category limits) |

There is deliberately **no approve/reject tool**: an assistant can submit and
read, but signing off a review item stays a human action behind RBAC.

```bash
python -m finance_crew.mcp_server     # or the installed console script: afc-mcp
```

Claude Desktop (`claude_desktop_config.json`) or any MCP client config:

```json
{
  "mcpServers": {
    "finance-crew": {
      "command": "python",
      "args": ["-m", "finance_crew.mcp_server"],
      "env": {
        "DATABASE_URL": "sqlite:////absolute/path/to/finance_crew.db",
        "MCP_ACTOR": "claude-desktop"
      }
    }
  }
}
```

`MCP_ACTOR` is recorded as `requested_by` in the audit trail (default
`mcp-client`). Point `DATABASE_URL` at the same database as the API to see
MCP submissions in the web console and review queue.

## 🖥️ Web console (UI)

A self-contained single-page app is served at **`/ui`** (the bare host `/`
redirects there). It talks to the API with the JWT from `/auth/login` and
adapts to the signed-in user's role.

```bash
uvicorn app:app --port 8000     # then open http://localhost:8000/  ->  /ui
```

> **Windows one-click:** double-click **`START.cmd`** in the project folder — it
> installs dependencies on first run, starts the server, and opens the console
> in your browser. Log in with `admin` / `admin` on first run. (The UI must be
> served by the app — opening `web/index.html` directly as a file won't work,
> because it needs the backend API.)

- **Login** and a role-aware sidebar (Employee / Finance Manager / Auditor / Admin).
- **Submit** a single expense and see the decision card (risk, rationale, rules fired).
- **Bulk upload (CSV)** — drop or paste a spreadsheet, decide the whole batch, and **export the results** as CSV.
- **Review queue** with one-click **Approve / Reject** + note (managers/admin).
- **Decisions** table with **filters** (outcome, employee) and **CSV export**; click any row for its **audit-trail timeline**.
- **Audit log**, **Users** admin (create accounts/roles), and an **Overview** with KPI tiles + a decision-mix donut chart.
- **Dark mode** toggle and a 🔊 **Listen** button that reads decisions aloud (browser speech synthesis).

It's a static bundle (no build step, inlined CSS/JS), shipped in the Docker
image and served by FastAPI — nothing extra to deploy.

## 🔐 Authentication & RBAC

Protected endpoints require a **JWT bearer token** obtained from `/auth/login`.
Four roles mirror a real finance back-office, and each route is gated by
capability (Admin can do everything):

| Role | Submit expenses | Review queue (approve/reject) | Read decisions & audit | Manage users |
|------|:---:|:---:|:---:|:---:|
| **Employee** | ✅ | — | — | — |
| **Finance Manager** | ✅ | ✅ | ✅ | — |
| **Auditor** | ✅ | — | ✅ (read-only) | — |
| **Admin** | ✅ | ✅ | ✅ | ✅ |

```bash
# 1) Log in (a bootstrap admin is seeded on first run — change the default!)
TOKEN=$(curl -s -X POST http://localhost:8000/auth/login \
  -d "username=admin&password=admin" | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

# 2) Call protected endpoints with the bearer token
curl -s http://localhost:8000/auth/me           -H "Authorization: Bearer $TOKEN"
curl -s http://localhost:8000/approve           -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"id":"EXP-1001","employee":"A. Rivera","category":"software","amount":149,"has_receipt":true}'

# 3) Admins create users with roles
curl -s -X POST http://localhost:8000/auth/register -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"username":"j.lee","password":"change-me","role":"finance_manager","full_name":"Jordan Lee"}'
```

A missing/invalid token returns `401`; a valid token without the required role
returns `403`. Passwords are stored as salted **PBKDF2** hashes (stdlib only —
no bcrypt/argon2 wheels). The approver recorded on a resolution is always taken
from the token, never trusted from the request body.

## 🗄️ Persistence & migrations

Every decision the API serves is written to a durable **system-of-record** so
the history is queryable and auditable — not lost when the process restarts.

- **Dev / CI / demo:** the default `DATABASE_URL` is a local **SQLite** file;
  the schema is auto-created on startup, so there's nothing to set up.
- **Production:** point `DATABASE_URL` at **PostgreSQL** and install the driver:

  ```bash
  pip install -e ".[postgres]"
  export DATABASE_URL="postgresql+psycopg://user:pass@localhost:5432/finance_crew"
  alembic upgrade head          # apply migrations (make migrate)
  uvicorn app:app               # decisions now persist to Postgres
  ```

Schema changes are versioned with **Alembic** (`migrations/`). Generate a new
migration after changing a model with `make migration m="describe change"`.
The persistence layer is engine-agnostic — the same code and tests run on both
SQLite and Postgres (a dedicated CI job proves the Postgres path end-to-end).

## 🧾 Audit trail & human review

Governed spend needs to answer *"who approved this, on what basis, and when?"*
Every decision therefore carries an **append-only, tamper-evident (hash-chained) audit trail** and a
human-in-the-loop workflow:

- **What's recorded per decision** — who requested it, what the AI
  **recommended**, which **rules fired**, the risk score, the **final action**,
  who resolved it, timestamps, the reason, and the **model/version** that
  decided (`engine@app-version`, e.g. `local@1.0.0`).
- **Lifecycle** mirrors the pipeline as ordered audit events:
  `request_received → ai_reasoning → policy_evaluation → decision`
  (→ `human_review → final_action` for review items).
- **Machine verdict preserved** — a human approve/reject is layered on via `status` /
  `resolved_by` / `resolved_at`; the original machine verdict
  (`decision`, `ai_recommendation`) is **never overwritten**, so the record
  always shows *what the AI said* vs *what the human decided*.

```bash
# The review queue — decisions awaiting a human (oldest first)
curl -s http://localhost:8000/review-queue

# A Finance Manager approves item #7. The approver is whoever owns the token —
# the body carries only a note; an "actor" field in the body would be ignored.
curl -s -X POST http://localhost:8000/decisions/7/approve \
  -H "Authorization: Bearer $MANAGER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"note":"Receipt verified with vendor."}'
#   -> 200; status "human_approved", final_action "approved", resolved_by = the token's user
#   409 if the item isn't awaiting review · 403 if the caller submitted it (separation of duties)

# The full audit trail for one decision …
curl -s http://localhost:8000/decisions/7/audit
# … and the global append-only log across all decisions
curl -s "http://localhost:8000/audit?step=final_action&limit=50"
```

## 🧪 Testing

```bash
pip install -e ".[dev]"      # pytest + httpx + langgraph
pytest -q                    # 265 tests: domain logic, API, engines, persistence, audit + hash chain, auth/RBAC, separation of duties, dual control, history checks, observability, evaluation, red team, hostile-LLM, UI, MCP server, input guard, rate limiting, decision records, error paths
python run_redteam.py --check   # adversarial red-team suite (all engines) — 0 unauthorized approvals
python run_demo.py           # end-to-end CLI smoke test over the sample batch
```

The suite covers the deterministic policy tools, the LangGraph↔local **parity**
guarantee, the FastAPI endpoints (happy path + validation/edge cases), and the
engine misconfiguration paths — all key-free. CI runs the same on Python
3.10–3.12 plus a Docker build and `/health` check.

## 📊 Observability

The service is instrumented so it can be run and watched like a real production
system — not just demoed.

- **Prometheus metrics** at `GET /metrics` (unauthenticated scrape target):

  | Metric | Type | What it tracks |
  |--------|------|----------------|
  | `afc_decisions_total{decision,engine}` | counter | Decisions by outcome and engine |
  | `afc_resolutions_total{action}` | counter | Human approve/reject actions |
  | `afc_decision_latency_seconds` | histogram | Per-decision processing latency |
  | `afc_http_requests_total{method,path,status}` | counter | HTTP throughput (paths normalized) |
  | `afc_http_request_latency_seconds{method,path}` | histogram | HTTP latency |
  | `afc_failures_total{kind}` | counter | Failure rate (5xx / unhandled) |
  | `afc_llm_tokens_total{engine}` · `afc_llm_cost_usd_total{engine}` | counter | LLM tokens & cost (real crew) |
  | `afc_rate_limited_total{method,path}` | counter | Requests refused with `429` by the rate limiter |
  | `afc_input_guard_flags_total{category}` | counter | Requests flagged by the input guard, by injection category |

- **Per-decision signals persisted** on every record: `latency_ms`, `tokens`,
  `cost_usd`. Deterministic engines use no LLM, so their tokens/cost are
  genuinely `0`; the real CrewAI engine reports actual usage (priced via a
  small per-model table).
- **Structured logging** — set `LOG_FORMAT=json` for machine-readable logs
  (timestamp, level, logger, message + any structured fields), `LOG_LEVEL` to
  tune verbosity.

```bash
curl -s http://localhost:8000/metrics | grep afc_decisions_total
```

The Kubernetes `Deployment` carries `prometheus.io/scrape` annotations so a
cluster Prometheus picks the endpoint up automatically.

## 🧪 Evaluation benchmark

What turns *"I built an AI finance agent"* into *"I **engineered and evaluated**
a governed decision system."* A reproducible benchmark generates synthetic
expense cases **with ground truth from an independent policy oracle** (not the
system's own `decide()`, so agreement is a real cross-check), runs them through
the pipeline, and scores the outcome.

> **Scope of this result:** 1,000 **synthetic** cases on the **deterministic**
> engine. It shows the system enforces the policy as written, consistently —
> it is **not** a measure of accuracy on real-world financial data and not a
> production validation. Adversarial behaviour is measured separately by the
> [red-team suite](benchmark/REDTEAM.md).

Latest published run — **1,000 cases** (`benchmark/RESULTS.md`, [`results.json`](benchmark/results.json)):

| Metric | Result |
|--------|--------|
| **Decision accuracy** | **100.00%** |
| **False approvals** (auto-approved something policy blocks) | **0** ✅ |
| False rejections · over-escalations | 0 · 0 |
| Auto-approved / escalated / rejected | 43.1% / 52.1% / 4.8% |
| Policy-violation detection (P / R / F1) | 1.000 / 1.000 / 1.000 |
| Duplicate detection (P / R / F1) | 1.000 / 1.000 / 1.000 |
| Latency (ms): mean / p95 | ~4.0 / ~9.0 (machine-dependent) |
| Tokens / cost | 0 / $0.00 (deterministic engine; the real crew reports actual usage) |

```bash
python run_eval.py                 # 1000 cases -> benchmark/RESULTS.md + results.json
python run_eval.py --n 500 --seed 7
python run_eval.py --check         # non-zero exit if any false approval or accuracy < 0.99
```

The `--check` gate runs in **CI on every push**, so a regression that let the
system auto-approve something it shouldn't would fail the build. When the real
CrewAI engine is enabled, the same benchmark scores the crew and surfaces any
divergence from the policy (plus its real token cost and latency).

## 🔄 Working locally & syncing to GitHub

Every push runs the full suite on **GitHub Actions** (Python 3.10–3.12, a Docker
build, a Postgres integration job, and the evaluation safety-gate). The **CI
badge** at the top of this README turns green/red automatically, and each run
posts a **test-results + benchmark summary** on its Actions page — so the test
results are always visible on GitHub, not just on your machine.

**One-click sync (Windows):** double-click **`SYNC.cmd`** in the project folder.
It runs the tests locally, commits your changes, and pushes to GitHub — which
triggers CI and updates the badge in ~1–2 minutes.

```
edit / test locally  →  SYNC.cmd  →  GitHub Actions runs tests  →  badge + summary update
```

## 🚢 Deployment

| Target | How | Notes |
|--------|-----|-------|
| **Live demo** | [agentic-finance-crew-deploy.vercel.app](https://agentic-finance-crew-deploy.vercel.app) | Runs key-free in local-engine mode. |
| **Docker Compose** | `docker compose up --build` | API on `http://localhost:8000`; healthcheck built in. |
| **Docker** | `docker build -t agentic-finance-crew . && docker run -p 8000:8000 agentic-finance-crew` | Slim multi-stage, non-root image. |
| **Kubernetes** | `kubectl apply -f k8s/` | Deployment (2 replicas, liveness/readiness probes, non-root) + Service. Keys come from a `Secret`, never plain values. |

## 🔎 AI transparency (model card + decision records)

- **[`MODEL_CARD.md`](MODEL_CARD.md)** — system-level card: how decisions are
  made, intended and out-of-scope use, limitations, human oversight, data
  handling, evaluation results, and an EU AI Act risk-classification
  assessment (not high-risk in the intended use; what would make it high-risk).
- **Decision record per verdict** — `GET /decisions/{id}/explanation`
  (Auditor / Finance Manager / Admin) returns schema `afc.decision-record/v1`:
  a PII-redacted inputs summary, the policy rules evaluated and fired,
  input-guard findings, each agent step with actor + timestamp, the final
  decision with engine/model version, who approved or rejected it and when,
  and latency/tokens/cost. It is built from the stored record and its
  append-only audit trail, so it always matches the system of record.

```bash
curl -s http://localhost:8000/decisions/7/explanation -H "Authorization: Bearer $TOKEN"
curl -s "http://localhost:8000/decisions/7/explanation?format=markdown" -H "Authorization: Bearer $TOKEN" > decision-7.md
```

## 🚦 Rate limiting

Every **mutating** endpoint (`POST`/`PUT`/`PATCH`/`DELETE` — submit, batch,
approve/reject, user admin and **login**) passes through a per-client
**token-bucket** limiter (`finance_crew.ratelimit`, stdlib only). Each client
may burst `RATE_LIMIT_BURST` calls, refilled at `RATE_LIMIT_PER_MINUTE`.
Reads, `/health` and `/metrics` are never limited.

- **Who is a client?** The authenticated user (JWT `sub`), else an
  `X-API-Key` header (hashed, never stored raw), else the client IP.
  `X-Forwarded-For` is only trusted with `RATE_LIMIT_TRUST_PROXY=true`.
- **When exceeded:** `429 Too Many Requests` with the usual error body and a
  `Retry-After` header (seconds); allowed responses carry `RateLimit-Limit` /
  `RateLimit-Remaining`. Refusals are counted in `afc_rate_limited_total` and
  in `afc_http_requests_total{status="429"}`.
- Login is limited per IP, which throttles password-guessing.
- Buckets live in-process (bounded LRU, 10k clients), so each replica enforces
  its own budget; put a shared limiter at the ingress if you need a global one.

```bash
curl -si -X POST http://localhost:8000/approve -H "Authorization: Bearer $TOKEN"   -H "Content-Type: application/json" -d '{"id":"EXP-9","employee":"E","category":"software","amount":10}'   | grep -iE "^HTTP|ratelimit|retry-after"
```

## 🛡️ Input guard (prompt injection + PII)

Expense descriptions, employee names and other free-text fields are
**untrusted input** that the real CrewAI engine places inside LLM prompts. A
stdlib-only guard (`finance_crew.guard`) screens every request **before** any
model or log sees it — and it runs inside the shared `analyze()` step, so all
three engines get it identically.

| Check | What it catches | What happens |
|-------|-----------------|--------------|
| Instruction override | "ignore previous instructions", "bypass the policy", "new instructions:" | Flagged |
| Role override | "you are now the approver", "act as admin", jailbreak / developer mode, chat-template tokens (`<\|im_start\|>`, `[SYSTEM]`, `system:`) | Flagged |
| System-prompt exfiltration | "reveal your system prompt", "print the api key" | Flagged |
| Tool / command smuggling | `<tool_call>`, `"function_call":`, "decision: approved", "mark this as approved", `$(...)`, `; rm -rf`, `{{...}}`, `<script>` | Flagged |
| Hidden Unicode | zero-width, bidi override/isolate, BOM, Unicode tag characters (text is also NFKC-normalized so look-alikes can't dodge the patterns) | Flagged + stripped |
| PII | emails, phone numbers, payment cards (Luhn), IBANs (country length + mod-97), SSN / CNIC / NINO-style IDs | Redacted to `[REDACTED_<TYPE>]` |

- **Flagged ⇒ human review, never auto-approved.** Findings become policy
  violations (`input guard: possible prompt injection (…)`), so the `decide()`
  guardrail routes the request to the review queue; they appear in
  `rules_fired`, in a dedicated `input_guard` audit-trail event and in the
  `afc_input_guard_flags_total` metric.
- **What the LLM sees.** A flagged field is **withheld** from the prompt
  entirely; clean fields have hidden characters stripped and PII redacted, and
  the whole request is fenced as untrusted data.
- **Logs.** A logging filter redacts PII from every formatted log line (API and
  MCP server). The audit trail records *which kinds* of PII were redacted,
  never the values.
- Patterns are phrase-level, not single keywords; a test suite checks every
  pattern **and** that ordinary expense text ("Uber to client site, approved by
  manager verbally", "tool set for the warehouse") is not flagged.

**OWASP Top 10 for LLM Applications mapping**

| OWASP risk | Control here |
|------------|--------------|
| **LLM01 Prompt Injection** | Pattern + hidden-Unicode detection on all free-text fields; flagged requests go to a human; flagged text never reaches the prompt; untrusted data is fenced; the LLM can't authorize spend anyway (`decide()` is deterministic) |
| **LLM02 Sensitive Information Disclosure** (LLM06 in the 2023 list) | PII redaction before prompts and in logs; audit trail stores PII *kinds* only; no description text is persisted on the decision record |
| LLM06 Excessive Agency (2025 list) | The MCP server and agents have no approve/reject capability — humans resolve review items behind RBAC |

## 🔒 Security & Data

- **No secrets in code or images** — every key is read from the environment; `.env` is gitignored, only `.env.example` (placeholders) is tracked. K8s manifests reference a `Secret`, not plain values.
- **Auth by default** — protected routes require a JWT; RBAC restricts who can approve, audit and manage users. `JWT_SECRET` is env-supplied; passwords are salted **PBKDF2** hashes and are never serialized.
- **Runs as a non-root container user**; image is a slim multi-stage build.
- **Fully synthetic data** — `sample_data/expenses.json` contains fictional employees and amounts only. No real financial data.

## 🗺️ Roadmap

- ✅ **LangGraph** orchestrator as a third interchangeable engine (stateful graph) — *done*.
- ✅ **Persist decisions to a database** (SQLAlchemy + Alembic; SQLite dev / Postgres prod) as a system-of-record — *done*.
- ✅ **Append-only audit trail + human-review queue** (who approved, rules fired, model/version; approve/reject workflow) — *done*.
- ✅ **Authentication & RBAC** (JWT; Employee / Finance Manager / Auditor / Admin) gating every action — *done*.
- ✅ **Observability** — Prometheus metrics, structured logs, per-decision latency / token / cost / failure-rate — *done*.
- ✅ **Evaluation benchmark** — 1,000 synthetic cases; published + CI safety gate — *done*.
- ✅ **Prompt-injection + PII guard, rate limiting, MCP server, model card, decision records** — *done*.
- ✅ **Red-team suite + hardening** (fail-closed parsing, category/split/duplicate evasion, separation of duties) with a CI gate — *done*.
- ✅ **Public live demo** (key-free local engine) — *done*.
- ✅ **Dual control** for high-value items (two distinct approvers above a threshold) — *done*.
- ✅ **History-aware checks** against stored decisions (duplicates / split purchases across calls and days) — *done*.
- ✅ **Tamper-evident audit trail** (hash-chained events, `/audit/verify`, ledger root) — *done*.
- Approval tiers by amount/role, a reversal/clawback workflow, and scheduled export of the ledger root to write-once storage.
- **Real-LLM evaluation** — score a live model's rationale against the deterministic ground truth, and run the red team with a real key in a scheduled job.
- Multilingual / encoded-injection coverage for the input guard.
- Receipt/invoice ingestion (PDF/image OCR) and Slack/email approval actions.

## 🛠️ Common tasks

A [`Makefile`](Makefile) wraps the everyday commands:

| Command | What it does |
|---------|--------------|
| `make install` | `pip install -e ".[dev]"` (base + dev deps) |
| `make test` | Run the full pytest suite |
| `make migrate` | Apply DB migrations (`alembic upgrade head`) |
| `make eval` | Run the evaluation benchmark and publish `benchmark/` |
| `make demo` | Run the CLI demo over the sample batch |
| `make run` | Start the API with autoreload at `:8000` |
| `make docker-build` | Build the Docker image |
| `make docker-up` | `docker compose up --build` |
| `make clean` | Remove caches and build artifacts |

Run `make help` to list them.

---

<sub>A <b>governed, evaluated enterprise AI decision system</b> — multi-agent reasoning behind a policy guardrail, with auth/RBAC, separation of duties, a persisted audit trail, observability, a published benchmark and an adversarial red-team gate. Built by <b>Furqan Ali</b> — Senior AI Engineer. Architecture, agent design and DevOps by the author. Data is fully synthetic.</sub>
