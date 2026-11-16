"""Run the adversarial red-team suite and publish benchmark/REDTEAM.md.

    python run_redteam.py            # all engines -> benchmark/REDTEAM.md + redteam.json
    python run_redteam.py --check    # non-zero exit on ANY unauthorized approval (CI gate)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from finance_crew import redteam  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="fail if any attack gets an unauthorized approval")
    ap.add_argument("--out", default="benchmark", help="output folder (default: benchmark)")
    args = ap.parse_args()

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


if __name__ == "__main__":
    raise SystemExit(main())
