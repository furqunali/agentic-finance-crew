# Changelog

All notable changes to this project are documented here. The format is based
on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
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
