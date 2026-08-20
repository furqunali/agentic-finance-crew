# Contributing to Agentic Finance Crew

Thanks for your interest in improving this project! Contributions of all
kinds are welcome — bug reports, docs, tests and features.

## Getting started

```bash
git clone https://github.com/furqunali/agentic-finance-crew.git
cd agentic-finance-crew
pip install -e ".[dev]"     # base + langgraph + pytest + httpx
```

Everything runs with **zero API keys** — the default local engine is fully
deterministic, so you can develop, test and demo offline.

## Running the tests

```bash
pytest -q                   # full suite
python run_demo.py          # smoke-test the CLI over the sample batch
```

CI (`.github/workflows/ci.yml`) runs the same suite on Python 3.10–3.12 and a
Docker build + `/health` check on every push and PR. Please make sure
`pytest -q` is green locally before opening a PR.

## The engine model (important context)

The system has **three interchangeable orchestrators** behind one
`Orchestrator.process()` contract, selected at runtime via `ENGINE`:

| Engine      | Needs a key? | Purpose                                            |
|-------------|--------------|----------------------------------------------------|
| `local`     | No           | Deterministic default — powers the demo, tests, CI |
| `langgraph` | No           | Same workflow as a LangGraph state graph           |
| `crewai`    | Yes          | The real multi-agent CrewAI crew (opt-in)          |

Two rules keep the project safe and testable — **please preserve them**:

1. **Rules live in code, not prompts.** All hard policy logic (spend limits,
   receipt rules, risk, duplicates) lives in `src/finance_crew/tools.py` and
   the `decide()` guardrail in `decision.py`. If you add policy behavior, add
   it here with tests — never rely on an LLM to enforce it.
2. **The model advises; policy decides.** Every engine funnels through the
   same `decide()` function, so all three must produce identical verdicts
   (there is a parity test for this). Don't let an engine branch the outcome.

## Pull request flow

1. Fork and create a topic branch: `git checkout -b feat/short-description`.
2. Make your change, **add or update tests**, and keep `pytest -q` green.
3. Use [Conventional Commits](https://www.conventionalcommits.org/) for commit
   messages (`feat:`, `fix:`, `docs:`, `test:`, `chore:`, `refactor:`).
4. Update `README.md` / `CHANGELOG.md` if you change behavior or config.
5. Open a PR against `main` using the PR template and describe the *why*.

## Style

- Python 3.10+ with type hints; keep the domain layer dependency-free.
- Match the existing docstring/comment tone — explain intent, not mechanics.
- Keep heavy deps (`crewai`, `langgraph`) imported **lazily** so the base
  install and CI stay light.

## Reporting bugs & requesting features

Use the issue templates under **New issue** — they prompt for the details
needed to reproduce and prioritize.

By contributing, you agree that your contributions are licensed under the
project's [MIT License](LICENSE).
