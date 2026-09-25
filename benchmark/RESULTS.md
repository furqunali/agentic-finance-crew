# Evaluation Benchmark — Results

_Synthetic benchmark of **300 cases** (seed 42), engine `local`. Ground truth from an independent policy oracle._

## Headline

- **Decision accuracy:** 100.00%
- **Safety:** ✅ **0 false approvals** (never auto-approved anything the policy would block)
- **False rejections:** 0  ·  **Over-escalations:** 0

## Decision mix

| Outcome | Rate |
|---------|------|
| Auto-approved | 42.3% |
| Escalated to human | 50.0% |
| Rejected (invalid) | 7.7% |

## Detection quality

| Signal | Precision | Recall | F1 |
|--------|-----------|--------|----|
| Policy violations | 1.000 | 1.000 | 1.000 |
| Duplicates | 1.000 | 1.000 | 1.000 |

## Performance & cost

- **Latency (ms):** mean 0.598 · p50 0.588 · p95 1.143 · max 2.193
- **Tokens:** 0  ·  **Cost:** $0.000000 _(the deterministic engine uses no LLM; the real crew reports actual usage here)_

> No decision mismatches: the system's guardrail matched the independent policy oracle on every case.
