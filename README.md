# 💼 Agentic Finance Crew

*A multi-agent **CrewAI** system that triages finance/ops expense requests — Intake → Policy Analyst → Approving Manager — with a deterministic policy guardrail and human-in-the-loop escalation.*

### 🔗 [**Live interactive demo »**](https://agentic-finance-crew-deploy.vercel.app)  ·  [🤗 Hugging Face Space](https://huggingface.co/spaces/FurqanAli12345/agentic-finance-crew)  ·  [Source](https://github.com/furqunali/agentic-finance-crew)

<p>
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
  <img src="https://img.shields.io/badge/UI-web%20console-1c3d5a?style=flat-square" alt="web console">
  <img src="https://img.shields.io/badge/tests-68%20passing-2ea44f?style=flat-square" alt="tests">
  <img src="https://img.shields.io/badge/license-MIT-blue?style=flat-square" alt="MIT">
</p>

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
    Crew --> G[[decide&#40;&#41; — policy guardrail]]
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
- **Durable system-of-record** — every decision is persisted via SQLAlchemy with Alembic migrations; runs on zero-config **SQLite** in dev and **PostgreSQL** in production by flipping one env var.
- **Immutable audit trail** — each decision logs the full lifecycle (who requested it → what the AI recommended → which rules fired → who approved it → timestamps, reason, model/version). The machine verdict is never overwritten by a human resolution.
- **Auth & RBAC** — JWT bearer tokens with four roles (**Employee / Finance Manager / Auditor / Admin**); the approver's identity comes from the token, not the request body.
- **Observability** — Prometheus metrics at `/metrics` (decisions, latency, HTTP, failures, LLM tokens/cost), structured JSON logging, and per-decision latency / token / cost stored on every record.
- **Evaluated, not just built** — a reproducible benchmark of **1,000 synthetic cases** scored against an independent policy oracle: **100% accuracy, 0 false approvals**, violation & duplicate F1 = 1.0. A CI safety gate fails the build on any false approval.
- **Web console (UI)** at `/ui` — a professional single-page app: login, role-aware nav, submit, **bulk CSV upload**, review queue (approve/reject), decisions with filters + **CSV export**, audit-trail timeline, users admin, an overview with charts, dark mode, and a 🔊 **Listen** (read-aloud) option.
- **Runs with zero secrets** via the local engine — great for demos, CI and offline dev.
- **FastAPI service** (`/auth/*`, `/approve`, `/approve/batch`, `/decisions`, `/review-queue`, `/audit`, `/metrics`, `/health`) with OpenAPI docs at `/docs` and a web console at `/ui`.
- **Fully containerized** (multi-stage, non-root, healthcheck) and **Kubernetes-ready**.
- **CI on every push** — tests across Python 3.10–3.12 + a Docker build/health check.

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
pytest -q                   # 68 tests, all green
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

## 🖥️ Web console (UI)

A self-contained single-page app is served at **`/ui`** (the bare host `/`
redirects there). It talks to the API with the JWT from `/auth/login` and
adapts to the signed-in user's role.

```bash
uvicorn app:app --port 8000     # then open http://localhost:8000/  ->  /ui
```

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
  -d '{"username":"m.khan","password":"change-me","role":"finance_manager","full_name":"Mustafa Khan"}'
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
Every decision therefore carries an **append-only audit trail** and a
human-in-the-loop workflow:

- **What's recorded per decision** — who requested it, what the AI
  **recommended**, which **rules fired**, the risk score, the **final action**,
  who resolved it, timestamps, the reason, and the **model/version** that
  decided (`engine@app-version`, e.g. `local@1.0.0`).
- **Lifecycle** mirrors the pipeline as ordered audit events:
  `request_received → ai_reasoning → policy_evaluation → decision`
  (→ `human_review → final_action` for review items).
- **Immutability** — a human approve/reject is layered on via `status` /
  `resolved_by` / `resolved_at`; the original machine verdict
  (`decision`, `ai_recommendation`) is **never overwritten**, so the record
  always shows *what the AI said* vs *what the human decided*.

```bash
# The review queue — decisions awaiting a human (oldest first)
curl -s http://localhost:8000/review-queue

# A Finance Manager approves item #7
curl -s -X POST http://localhost:8000/decisions/7/approve \
  -H "Content-Type: application/json" \
  -d '{"actor":"m.khan (Finance Manager)","note":"Receipt verified with vendor."}'
#   -> 200; status "human_approved", final_action "approved"
#   Approving an auto-decided item returns 409 (it isn't awaiting review).

# The full audit trail for one decision …
curl -s http://localhost:8000/decisions/7/audit
# … and the global append-only log across all decisions
curl -s "http://localhost:8000/audit?step=final_action&limit=50"
```

## 🧪 Testing

```bash
pip install -e ".[dev]"      # pytest + httpx + langgraph
pytest -q                    # 68 tests: domain logic, API, engines, persistence, audit, auth/RBAC, observability, evaluation, UI, error paths
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

Latest published run — **1,000 cases** (`benchmark/RESULTS.md`, [`results.json`](benchmark/results.json)):

| Metric | Result |
|--------|--------|
| **Decision accuracy** | **100.00%** |
| **False approvals** (auto-approved something policy blocks) | **0** ✅ |
| False rejections · over-escalations | 0 · 0 |
| Auto-approved / escalated / rejected | 43.1% / 52.1% / 4.8% |
| Policy-violation detection (P / R / F1) | 1.000 / 1.000 / 1.000 |
| Duplicate detection (P / R / F1) | 1.000 / 1.000 / 1.000 |
| Latency (ms): mean / p95 | ~2.1 / ~4.1 |
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

## 🚢 Deployment

| Target | How | Notes |
|--------|-----|-------|
| **Live demo** | [agentic-finance-crew-deploy.vercel.app](https://agentic-finance-crew-deploy.vercel.app) | Runs key-free in local-engine mode. |
| **Docker Compose** | `docker compose up --build` | API on `http://localhost:8000`; healthcheck built in. |
| **Docker** | `docker build -t agentic-finance-crew . && docker run -p 8000:8000 agentic-finance-crew` | Slim multi-stage, non-root image. |
| **Kubernetes** | `kubectl apply -f k8s/` | Deployment (2 replicas, liveness/readiness probes, non-root) + Service. Keys come from a `Secret`, never plain values. |

## 🔒 Security & Data

- **No secrets in code or images** — every key is read from the environment; `.env` is gitignored, only `.env.example` (placeholders) is tracked. K8s manifests reference a `Secret`, not plain values.
- **Auth by default** — protected routes require a JWT; RBAC restricts who can approve, audit and manage users. `JWT_SECRET` is env-supplied; passwords are salted **PBKDF2** hashes and are never serialized.
- **Runs as a non-root container user**; image is a slim multi-stage build.
- **Fully synthetic data** — `sample_data/expenses.json` contains fictional employees and amounts only. No real financial data.

## 🗺️ Roadmap

- ✅ **LangGraph** orchestrator as a third interchangeable engine (stateful graph) — *done*.
- ✅ **Persist decisions to a database** (SQLAlchemy + Alembic; SQLite dev / Postgres prod) as a system-of-record — *done*.
- ✅ **Immutable audit trail + human-review queue** (who approved, rules fired, model/version; approve/reject workflow) — *done*.
- ✅ **Authentication & RBAC** (JWT; Employee / Finance Manager / Auditor / Admin) gating every action — *done*.
- ✅ **Observability** — Prometheus metrics, structured logs, per-decision latency / token / cost / failure-rate — *done*.
- ✅ **Evaluation benchmark** — 1,000 synthetic cases scoring accuracy, violation/duplicate detection, false approve/reject, escalation, latency & cost; published + CI safety gate — *done*.
- Receipt/invoice ingestion (CSV/Excel batch upload; PDF/image OCR) and Slack/email approval actions.
- Add **eval cases** scoring the crew's rationale quality against the deterministic ground truth.
- Slack / email approval actions for the human-in-the-loop step.
- Deploy the FastAPI service (runs key-free in local mode) as a public live demo.

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

<sub>A <b>governed, evaluated enterprise AI decision system</b> — multi-agent reasoning behind a policy guardrail, with auth/RBAC, a persisted audit trail, observability, and a published benchmark. Built by <b>Furqan Ali</b> — Senior AI Engineer. Architecture, agent design and DevOps by the author. Data is fully synthetic.</sub>
