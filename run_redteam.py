"""Run the adversarial red-team suite and publish benchmark/REDTEAM.md.

    python run_redteam.py            # all engines -> benchmark/REDTEAM.md + redteam.json
    python run_redteam.py --check    # non-zero exit on ANY unauthorized approval (CI gate)

    # The same attacks through the REAL CrewAI crew and a real model (needs a key):
    USE_CREWAI=true LLM_PROVIDER=gemini LLM_MODEL=gemini-2.5-flash GEMINI_API_KEY=...         python run_redteam.py --real-llm    # -> benchmark/REDTEAM_LLM.md + redteam_llm.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from finance_crew import redteam  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="fail if any attack gets an unauthorized approval")
    ap.add_argument("--out", default="benchmark", help="output folder (default: benchmark)")
    ap.add_argument("--real-llm", action="store_true", help="run through the real CrewAI crew + LLM (needs a key)")
    ap.add_argument("--limit", type=int, default=None, help="--real-llm: only the first N attacks")
    ap.add_argument("--pause", type=float, default=0.0, help="--real-llm: seconds between attacks (rate limits)")
    args = ap.parse_args()

    if args.real_llm:
        return _real_llm(args)

    rep = redteam.run()
    out = Path(args.out)
    out.mkdir(exist_ok=True)
    (out / "REDTEAM.md").write_text(redteam.render_markdown(rep), encoding="utf-8")
    (out / "redteam.json").write_text(redteam.to_json(rep), encoding="utf-8")

    print(f"\n  Red team: {rep['attacks']} attacks x {len(rep['engines'])} engines = {rep['runs']} runs")
    print("  " + "-" * 60)
    print(f"  unauthorized approvals   {rep['unauthorized_approvals']:>4} / {rep['block_runs']}  (safety-critical)")
    print(f"  injections flagged       {rep['injections_flagged']:>4} / {rep['flag_runs']}")
    print(f"  runs passing             {rep['passed']:>4} / {rep['runs']}")
    for f in rep["failures"]:
        print(f"  MISS {f['id']:<8} {f['engine']:<20} {f['outcome']:<20} {f['title']}")
    print("  " + "-" * 60)
    print(f"  wrote {out / 'REDTEAM.md'} and {out / 'redteam.json'}\n")

    if args.check and rep["unauthorized_approvals"]:
        print("  CHECK FAILED: an attack obtained an unauthorized approval")
        return 1
    if args.check:
        print("  CHECK PASSED: 0 unauthorized approvals")
    return 0


def _real_llm(args: argparse.Namespace) -> int:
    from finance_crew.config import Settings

    settings = Settings.from_env()
    if not settings.can_run_crewai:
        print("  --real-llm needs USE_CREWAI=true and an OPENAI_API_KEY / GEMINI_API_KEY")
        return 2

    def progress(i: int, n: int, row: dict) -> None:
        print(f"  [{i:>2}/{n}] {row['id']:<8} model: {row['model_recommendation']:<22} system: {row['outcome']}")

    rep = redteam.run_real_llm(settings, limit=args.limit, pause_s=args.pause, progress=progress)
    out = Path(args.out)
    out.mkdir(exist_ok=True)
    (out / "REDTEAM_LLM.md").write_text(redteam.render_llm_markdown(rep), encoding="utf-8")
    (out / "redteam_llm.json").write_text(json.dumps(rep, indent=2, default=str), encoding="utf-8")
    print("  " + "-" * 60)
    print(f"  model                         {rep['model']}")
    print(f"  unauthorized approvals        {rep['unauthorized_approvals']} / {rep['block_runs']}  (safety-critical)")
    print(f"  model recommended approval    {rep['model_recommended_approve_on_block']} / {rep['block_runs']}  (overruled by the guardrail)")
    print(f"  provider errors               {rep['errors']}")
    print(f"  wrote {out / 'REDTEAM_LLM.md'}")
    if args.check and rep["unauthorized_approvals"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
