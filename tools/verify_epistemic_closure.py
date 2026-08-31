"""EPISTEMIC-CLOSURE-CERTIFICATION-1 — the release gate, as a command.

    python tools/verify_epistemic_closure.py            full gate, exit 0/1
    python tools/verify_epistemic_closure.py --fast     skip tape predicates
    python tools/verify_epistemic_closure.py --json     machine-readable
    python tools/verify_epistemic_closure.py --payload  the pre-live truth report

WHAT PASSING MEANS. Every fact that reaches Luna's decision surface declares its
owner, its meaning, its lifecycle, its clocks, its consumers and its limits --
and nothing that cannot back those declarations is deciding anything. It does
NOT mean the roadmap is finished; the blocked capabilities and the declared
debts are printed precisely so that is never confused.

WHY IT EXISTS SEPARATELY FROM THE SUITE. The same gate runs inside the
authoritative suite so it cannot be forgotten. This is the fast preflight: one
command, one screen, before a live session or before asking for a release
ruling. Read-only -- no broker, no provider, no network, no order.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from rule_governance.epistemic_closure.closure_verifier import render, verify   # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify epistemic closure of the market-fact surface.")
    parser.add_argument("--fast", action="store_true",
                        help="skip semantic predicates that replay archived "
                             "tape (structure only; NOT a release gate)")
    parser.add_argument("--json", action="store_true",
                        help="emit the raw report as JSON")
    parser.add_argument("--payload", action="store_true",
                        help="print the pre-live mechanics truth report instead")
    args = parser.parse_args()

    if args.payload:
        from rule_governance.epistemic_closure.pre_live_report import render_payload_truth
        print(render_payload_truth())
        return 0

    report = verify(run_predicates=not args.fast)
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(render(report))
        if args.fast:
            print()
            print("  NOTE: --fast skipped the semantic predicates. Structure was "
                  "checked; MEANING was not. This is not a release gate.")
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
