"""Void one trade mission as an INFRASTRUCTURE_ABORT. Places nothing.

Read-only against the venue: authenticates, pins, and reads position/order
state to prove nothing was placed. It never submits, modifies or cancels.

The mission file is NOT edited. A separate ledger records the excuse, and the
next mission opens in the next free slot beside it.

    python tools/topstepx_void_mission.py --session PROD-20260810 --mission 1 \
        --reason "..." --phrase "VOID THIS MISSION AS INFRASTRUCTURE ABORT"
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))

from dotenv import find_dotenv, load_dotenv  # noqa: E402

load_dotenv(find_dotenv(usecwd=True))

from broker import topstepx_mission_recovery as RECOVERY  # noqa: E402
from broker import topstepx_mission_state as MS  # noqa: E402
from broker.topstepx_live_session import TopstepXLiveSession  # noqa: E402
from broker.topstepx_redaction import redacted_account_label  # noqa: E402

STORE_DIR = os.path.join("data", "integration", "topstepx")


def venue_evidence(symbol: str = "MNQ") -> dict:
    session = TopstepXLiveSession()
    session.authenticate()
    session.pin(account_id=int(os.environ["TOPSTEPX_ACCOUNT_ID"]),
                expected_fingerprint=os.environ.get(
                    "TOPSTEPX_ACCOUNT_FINGERPRINT", ""))
    contract = session.resolve_contract(symbol)   # the session reads nothing unpinned
    positions = session.open_positions()
    orders = session.open_orders()
    print(f"  account          : {redacted_account_label(session.account)}")
    print(f"  open positions   : {len(positions)}")
    print(f"  working orders   : {len(orders)}")
    return {"open_positions": len(positions), "working_orders": len(orders),
            "read_only": True, "checked_symbol": symbol,
            "contract_id": contract.id}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", required=True)
    ap.add_argument("--mission", type=int, required=True)
    ap.add_argument("--reason", required=True)
    ap.add_argument("--phrase", required=True)
    ap.add_argument("--fills-today", type=int, default=None)
    ap.add_argument("--store-dir", default=STORE_DIR)
    args = ap.parse_args()

    path = os.path.join(args.store_dir,
                        f"trade_mission_{args.session}_{args.mission}.json")
    mission = MS.load(path)
    if mission is None:
        print(f"REFUSED: no mission record at {path}")
        return 2

    print("MISSION VOID -- READ-ONLY VENUE CHECK")
    # This tool used to call `never_reached_venue(mission)` with no submission
    # evidence at all, so it refused everything on LEDGER_NOT_CONSULTED. That
    # looked like caution and was actually a gap: it never consulted the ledger
    # the v5 hardening built, and on PROD-20260811-V13 the accidental refusal
    # was the only thing standing between a real filled trade and a void.
    evidence = RECOVERY.submission_evidence_for(
        args.store_dir, args.session, mission.mission_id,
        token_id=getattr(mission, "token_id", "") or "")
    print(f"  ledger rows      : {evidence.get('submission_count')} "
          f"(venue_may_have_seen={evidence.get('venue_may_have_seen')})")
    ok, reasons = RECOVERY.never_reached_venue(
        mission, submission_evidence=evidence)
    print(f"  mission          : {mission.mission_id} ({mission.state})")
    print(f"  never reached venue : {ok}")
    for r in reasons:
        print(f"    - {r}")
    if not ok:
        print("REFUSED: this mission may have reached the venue.")
        return 3

    evidence = venue_evidence()
    if args.fills_today is not None:
        evidence["fills_today"] = args.fills_today

    try:
        entry = RECOVERY.record_void(
            store_dir=args.store_dir, session_id=args.session,
            mission_index=args.mission, mission=mission, phrase=args.phrase,
            reason=args.reason, venue_evidence=evidence)
    except RECOVERY.VoidRefused as exc:
        print(f"REFUSED: {exc}")
        return 4

    print(f"  VOIDED           : {entry['mission_id']} -> {entry['void_class']}")
    print(f"  ledger           : "
          f"{RECOVERY.void_ledger_path(args.store_dir, args.session)}")
    print(f"  mission file     : PRESERVED UNEDITED ({path})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
