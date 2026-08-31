"""Read-only re-verification of an issued session authorization."""
from __future__ import annotations

import argparse
import os
from datetime import datetime
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from broker import topstepx_session_authorization as SA  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--session-id", required=True)
    ap.add_argument("--date", required=True, help="YYYYMMDD")
    ap.add_argument("--contract", default="CON.F.US.MNQ.U26")
    args = ap.parse_args(argv)

    path = os.path.join("data", "integration", "topstepx",
                        f"session_auth_{args.session_id}.json")
    a = SA.SessionAuthorization.load(path)
    if a is None:
        print("  NO AUTHORIZATION RECORD")
        return 2
    print("AUTHORIZATION RE-VERIFICATION")
    print(f"  session          : {a.session_id}")
    print(f"  session date     : {a.session_date}")
    print(f"  contract         : {a.contract_id}")
    print(f"  window           : {a.decision_window}")
    print(f"  brain model      : {a.brain_model}")
    print(f"  json mode        : {a.json_mode_required}")
    print(f"  retrieval_enabled: {a.retrieval_enabled}")
    print(f"  brain contract   : ...{str(a.brain_contract_fingerprint)[-6:]}")
    print(f"  auth fingerprint : ...{str(a.authorization_fingerprint)[-6:]}")
    # 2026-08-12 — NORMALISE THE DATE THE WAY THE ISSUER DOES.
    # `--date` is taken as YYYY-MM-DD (the issuer's CLI form) but the record
    # stores the compact YYYYMMDD that `parse_date()` produces, and
    # `SessionAuthorization.verify` compares the two as raw strings. Passing
    # `args.date` through unchanged made this tool report
    # "AUTHORIZATION_EXPIRED: issued for 20260812, today is 2026-08-12" against a
    # freshly minted, perfectly valid authorization for the same day.
    #
    # The bug was ONLY here. `topstepx_production_session.py` already passes
    # `now.strftime("%Y%m%d")` (lines 284 and 310), so the live path validated
    # correctly the whole time -- a false alarm in the checker, not a hole in the
    # check. `verify()` itself is deliberately untouched: a date comparison that
    # refuses on mismatch is the correct behaviour, and loosening it to "repair"
    # this would have destroyed the no-rollover guarantee.
    session_date = str(args.date).strip()
    if "-" in session_date:
        session_date = datetime.strptime(session_date, "%Y-%m-%d").strftime("%Y%m%d")
    try:
        a.verify(account_fingerprint=os.environ.get(
                     "TOPSTEPX_ACCOUNT_FINGERPRINT", ""),
                 contract_id=args.contract, session_date=session_date)
        print("  VERIFY           : PASS")
        return 0
    except SA.AuthorizationRefused as exc:
        print(f"  VERIFY           : REFUSED -- {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
