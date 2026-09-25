"""Run the evaluation benchmark and publish the results.

    python run_eval.py                     # 1000 cases, writes benchmark/
    python run_eval.py --n 500 --seed 7
    python run_eval.py --check             # non-zero exit if unsafe / inaccurate

Runs key-free on the deterministic local engine (set USE_CREWAI=true + a key to
benchmark the real crew instead). Writes `benchmark/results.json` and
`benchmark/RESULTS.md`.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # pragma: no cover
    pass

from finance_crew.evaluation import evaluate, render_markdown


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Agentic Finance Crew — evaluation benchmark")
    ap.add_argument("--n", type=int, default=1000, help="number of synthetic cases")
    ap.add_argument("--seed", type=int, default=42, help="random seed (reproducible)")
    ap.add_argument("--out", default="benchmark", help="output directory")
    ap.add_argument("--check", action="store_true",
                    help="exit non-zero if any false approvals or accuracy < 0.99")
    args = ap.parse_args(argv[1:])

    report = evaluate(n=args.n, seed=args.seed)
    m = report.metrics

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.json").write_text(json.dumps(m, indent=2), encoding="utf-8")
    (out / "RESULTS.md").write_text(render_markdown(report), encoding="utf-8")

    print(f"\n  Benchmark: {m['total_cases']} cases · engine {m['engine']}")
    print("  " + "-" * 60)
    print(f"  accuracy            {m['accuracy'] * 100:6.2f}%")
    print(f"  false approvals     {m['false_approvals']:>6}   (safety-critical)")
    print(f"  false rejections    {m['false_rejections']:>6}")
    print(f"  auto-approved       {m['auto_approval_rate'] * 100:6.2f}%")
    print(f"  escalated to human  {m['escalation_rate'] * 100:6.2f}%")
    print(f"  violation F1        {m['violation_detection']['f1']:6.3f}")
    print(f"  duplicate F1        {m['duplicate_detection']['f1']:6.3f}")
    print(f"  latency p95 (ms)    {m['latency_ms']['p95']:6.3f}")
    print("  " + "-" * 60)
    print(f"  wrote {out/'results.json'} and {out/'RESULTS.md'}\n")

    if args.check:
        if m["false_approvals"] > 0 or m["accuracy"] < 0.99:
            print("  CHECK FAILED: unsafe or inaccurate benchmark result", file=sys.stderr)
            return 1
        print("  CHECK PASSED: 0 false approvals, accuracy >= 0.99")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
