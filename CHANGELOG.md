# Changelog

All notable changes to this project are documented here. The format is based
on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **AI transparency pack.**
  - `MODEL_CARD.md`: intended and out-of-scope use, limitations, human
    oversight, data handling, evaluation results (1,000-case benchmark + CI
    gate) and EU AI Act risk-classification reasoning.
  - Per-decision **decision record** `GET /decisions/{id}/explanation`
    (`finance_crew.explain`, schema `afc.decision-record/v1`; JSON or
    `?format=markdown`): PII-redacted inputs summary, policy rules evaluated
    and fired, input-guard findings, agent steps with actors and timestamps,
    final decision with model version, who approved/rejected and when.
    Built from the existing record + audit trail; Auditor / Finance Manager /
    Admin only. 13 new tests.
- **MCP server** (`finance_crew.mcp_server`, console script `afc-mcp`): exposes
  the approval workflow to AI assistants over the Model Context Protocol —
  dependency-free JSON-RPC 2.0 on stdio (`initialize` with version negotiation,
  `tools/list`, `tools/call`, `ping`; standard `-32700/-32600/-32601/-32602/-32603`
  error codes; tool failures returned as `isError` results).
  - Tools: `submit_expense_request` (same orchestrator, `decide()` guardrail,
    persistence and audit trail as `POST /approve`), `get_decision`,
    `list_pending_approvals`, `get_policy`. Arguments are validated against the
    published JSON Schemas before any work runs.
  - `MCP_ACTOR` env sets the `requested_by` identity recorded in the audit trail.
  - Claude Desktop / MCP client config example in the README; 32 new tests
    (handshake, schemas, each tool, bad input, unknown tool/method, a real
    stdio subprocess round-trip).

### Security
- **Per-client API rate limiting** (`finance_crew.ratelimit`, stdlib token
  bucket) on every mutating endpoint, including `/auth/login` (throttles
  password guessing). Clients are keyed by JWT subject, then hashed `X-API-Key`,
  then IP (`X-Forwarded-For` only with `RATE_LIMIT_TRUST_PROXY`). Over-limit
  calls get `429` + `Retry-After`; allowed calls carry `RateLimit-Limit` /
  `RateLimit-Remaining`. New metric `afc_rate_limited_total{method,path}`.
  Configurable via `RATE_LIMIT_ENABLED` (default on), `RATE_LIMIT_PER_MINUTE`
  (60), `RATE_LIMIT_BURST` (20). The test suite disables it globally and
  exercises it with dedicated tests (15 new).
- **Prompt-injection + PII input guard** (`finance_crew.guard`, OWASP LLM01 /
  LLM02). Every free-text request field is screened before reaching an LLM:
  instruction/role overrides, system-prompt exfiltration, tool/command
  smuggling, chat-template tokens and hidden Unicode (zero-width, bidi, tag
  characters; NFKC-normalized). Suspicious requests become policy violations,
  so the `decide()` guardrail routes them to human review — never
  auto-approved — with the reason in `rules_fired`, a new `input_guard`
  audit-trail step and the `afc_input_guard_flags_total` metric.
- PII (emails, phones, Luhn-valid cards, mod-97-valid IBANs, SSN/CNIC/NINO-style
  IDs) is redacted from text sent to the CrewAI LLM and from logs (a
  `PIIRedactingFilter` on the API and MCP log handlers). Flagged fields are
  withheld from the prompt entirely; the request is fenced as untrusted data.
  The audit trail records only the PII *kinds* redacted, never the values.
- 78 new tests (every pattern, every PII type, checksum validation, no false
  positives on ordinary expense text and the sample batch, local + LangGraph
  routing parity, API audit trail + metric).
- The MCP surface has **no approve/reject tool** by design: an assistant can
  submit and read, but human sign-off of review items stays behind RBAC.

### Fixed
- **Docker image now starts healthy.** The container runs as the non-root
  `appuser`, but the default SQLite database (`./finance_crew.db`) was created
  inside the root-owned `/app`, so startup failed with `unable to open database
  file` and the CI `/health` check never passed. The image now sets
  `DATABASE_URL=sqlite:////app/data/finance_crew.db`, creates `/app/data` owned by
  `appuser` and declares it a volume (data survives container restarts). Set
  `DATABASE_URL` to Postgres for production as before.

### Added
- **Robust error handling.**
  - Backend: a last-resort `Exception` handler turns any *unhandled* error into
    a clean, structured `500` (no leaked stack trace / bare HTML), logs it, and
    counts it in the failure metric — 4xx handlers still take precedence.
  - UI: the API helper detects an unreachable/down server (or a page opened as
    a `file://` instead of served) and shows a clear message pointing to
    `START.cmd`; login distinguishes "wrong password" (401) from "server down";
    global `error` / `unhandledrejection` catchers surface problems as toasts
    instead of failing silently; 5xx responses show a friendly retry message.
- **`START.cmd`** one-click Windows launcher (installs deps on first run, starts
  the server, opens the console) — removes the "opened the HTML directly / server
  not running" confusion. Auto-picks a free port (8000→8001→8002) and waits for
  the server before opening the browser.
- **`AUTH_DISABLED`** opt-in flag (default OFF): local/demo no-login mode where
  every request is the admin user. `START.cmd` sets it for single-user local
  use; the UI auto-detects it and skips the login screen. Never for production.
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
