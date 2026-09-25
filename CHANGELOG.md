# Changelog

All notable changes to this project are documented here. The format is based
on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Web console (UI).** A self-contained single-page app served at `/ui`
  (bare `/` redirects there), talking to the API with the login JWT:
  - Login + role-aware navigation (Employee / Finance Manager / Auditor / Admin).
  - Submit a single expense; **bulk CSV upload** (client-side parse → batch)
    with **results CSV export** and a downloadable template.
  - Review queue with one-click approve/reject + note; decisions table with
    filters (outcome/employee) and **CSV export**; per-decision **audit-trail
    timeline** modal; users admin; overview with KPI tiles + donut chart.
  - **Dark mode** and a 🔊 **Listen** (read-aloud) option via browser speech
    synthesis. Static bundle (no build step), shipped in the Docker image.
- **Evaluation benchmark.**
  - `finance_crew.evaluation` + `run_eval.py` generate 500–1,000 deterministic
    synthetic cases **with ground truth from an independent policy oracle** and
    score: accuracy, policy-violation & duplicate detection (P/R/F1), false
    approvals / rejections, over-escalation, escalation rate, latency and cost.
  - Published results in `benchmark/RESULTS.md` + `benchmark/results.json`
    (1,000 cases: 100% accuracy, **0 false approvals**, violation & duplicate
    F1 = 1.0).
  - `run_eval.py --check` is a **CI safety gate** — the build fails on any false
    approval or accuracy < 0.99. `make eval` publishes a fresh report.
- **Observability.**
  - Prometheus metrics at `GET /metrics`: decisions by outcome/engine, human
    resolutions, per-decision latency histogram, HTTP throughput + latency
    (paths normalized), failure counter, and LLM token/cost counters.
  - Per-decision `latency_ms`, `tokens` and `cost_usd` persisted on every record
    (Alembic `0004_observability`); deterministic engines report 0 tokens/cost,
    the real crew reports actual usage (priced via a small per-model table).
  - Structured JSON logging (`LOG_FORMAT=json`) + `LOG_LEVEL`; an HTTP
    middleware records request metrics; K8s `Deployment` gains
    `prometheus.io/scrape` annotations.
- **Authentication & RBAC.**
  - JWT bearer-token auth (`/auth/login`, `/auth/me`) with a `users` table and
    salted **PBKDF2** password hashing (stdlib only — no bcrypt/argon2 wheels).
  - Four roles — **Employee / Finance Manager / Auditor / Admin** — gating every
    action: submit (all), review/approve/reject (manager+admin), read decisions
    & audit (auditor+manager+admin), user management (admin).
  - Admin user management (`POST /auth/register`, `GET /auth/users`) and a
    bootstrap admin seeded on first run (`ADMIN_USERNAME`/`ADMIN_PASSWORD`).
  - The approver on a resolution is taken from the authenticated token, never
    the request body. Missing/invalid token ⇒ `401`; wrong role ⇒ `403`.
  - Alembic migration `0003_users`; app startup modernized to a lifespan handler.
- **Audit trail + human-in-the-loop review workflow.**
  - Every decision now records an immutable, append-only audit trail
    (`request_received → ai_reasoning → policy_evaluation → decision →
    human_review → final_action`) in a new `audit_events` table.
  - `DecisionRecord` enriched with the audit fields the domain calls for:
    `requested_by`, `ai_recommendation`, `rules_fired`, `model_version`,
    lifecycle `status`, and `resolved_by` / `resolved_at` / `resolution_note`.
  - **Review queue + resolution API**: `GET /review-queue`,
    `POST /decisions/{id}/approve`, `POST /decisions/{id}/reject`,
    `GET /decisions/{id}/audit`, and a global `GET /audit` log.
  - Human resolutions are layered on without mutating the machine verdict, so
    the record always preserves *what the AI recommended* vs *what the human
    decided*. Resolving a non-pending item returns `409`; a missing id `404`.
  - Alembic migration `0002_audit_trail` (safe column adds + new table);
    `/approve` responses now return the full stored record.
- **Persistence layer (database).** Every decision served over the API is now
  written to a durable system-of-record:
  - SQLAlchemy 2.0 ORM (`DecisionRecord`) with a repository layer and a
    transactional `session_scope()` unit-of-work (commit on success, rollback
    on error).
  - Single `DATABASE_URL` switch: zero-config **SQLite** for dev/CI/demo,
    **PostgreSQL** (`postgresql+psycopg://…`) for production via the
    `[postgres]` extra — no code changes.
  - **Alembic** migration system (`alembic upgrade head`), an initial
    migration, and a migration-capable Docker image.
  - New read API: `GET /decisions` (paginated, filterable by decision/employee)
    and `GET /decisions/{id}`; `/approve` responses now include the stored
    `record_id`.
  - Tests for repository round-trips, transaction rollback, the new endpoints,
    and an Alembic upgrade; a dedicated **Postgres integration CI job**.
- Hardened error handling across the API and engines: structured JSON error
  payloads, non-empty/`id`/`employee` validation, an empty-batch `422`, a
  batch-size cap, and a clear `ConfigurationError` when `ENGINE=crewai` is set
  without an API key.
- Typed error hierarchy (`FinanceCrewError`, `ConfigurationError`,
  `ValidationError`).
- Community health files: `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, issue and
  pull-request templates, and this changelog.
- Expanded README with Configuration, Testing, Deployment and API-examples
  sections, plus a `Makefile` of common tasks.

## [1.0.0] - 2025-08-20

Initial public release.

### Added
- **Multi-agent CrewAI crew** — Intake Officer → Policy Analyst → Approving
  Manager — running sequentially over shared deterministic tools.
- **Policy-as-code guardrail** (`decide()`): spend limits, per-category
  limits, receipt rules, a 0–100 risk score and duplicate detection, all as
  unit-tested pure functions rather than prompts.
- **Three interchangeable engines** behind one `Orchestrator` contract,
  selected at runtime via `ENGINE`:
  - `LocalOrchestrator` — deterministic, zero-dependency, no key (default).
  - `LangGraphOrchestrator` — the same workflow as a LangGraph state graph.
  - `CrewAIOrchestrator` — the real multi-agent crew (opt-in, needs a key).
- **Human-in-the-loop** routing for anything over-limit, non-compliant or
  high-risk.
- **FastAPI service** — `/approve`, `/approve/batch`, `/health` with OpenAPI
  docs at `/docs`.
- **CLI demo** (`run_demo.py`) over a fully synthetic sample batch.
- **Containerization & orchestration** — multi-stage non-root Dockerfile,
  `docker-compose.yml`, and Kubernetes manifests under `k8s/`.
- **CI** — GitHub Actions running the test suite on Python 3.10–3.12 plus a
  Docker build and `/health` check.
- Provider-agnostic LLM config (OpenAI or Gemini) via environment variables;
  no secrets in code or images.

[Unreleased]: https://github.com/furqunali/agentic-finance-crew/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/furqunali/agentic-finance-crew/releases/tag/v1.0.0
