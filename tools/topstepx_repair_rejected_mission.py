"""Close ONE stranded mission as VENUE_REJECTED_ZERO_FILL, against the venue.

PROD-20260904. The source fix makes the production loop write this transition
itself, from now on. It cannot reach backwards: PROD-20260904-T1 is already on
disk in ATTEMPT_CONSUMED, and the process that could have observed its rejection
is gone. This tool is the operator's one bounded way to finish that mission --
and it is deliberately NOT a second mission system.

    IT PLACES NOTHING. No order endpoint is reachable from this module. It
    authenticates, pins, READS, and then calls the SAME canonical
    `MissionState.venue_rejected_zero_fill` production now calls. There is no
    second law here, and no hand-edited JSON.

WHY NOT `topstepx_void_mission.py`. A void says the request NEVER REACHED THE
VENUE, and correctly refuses this mission -- the ledger proves Topstep saw it.
A rejection says the opposite: the venue saw it and said no. Voiding a rejected
mission would restore an allowance on a false premise.

EVERY FACT IS PROVEN BEFORE ANYTHING IS WRITTEN, in this order:

    1. the mission is loadable, is this account's, and is NOT already terminal
    2. the venue answers, and reports ZERO open positions
    3. working-order discovery answers AND is COMPLETE (v2/query), and finds
       nothing working -- `searchOpen` alone can be silent about a Suspended
       child, and absence from a surface that omits rows is not absence
    4. the flight recorder holds a VENUE_REJECTED row for this mission, no
       fill, and no still-unknown submission  (`zero_fill_rejection`)
    5. the operator types the phrase

Any one of them missing and it refuses and writes nothing.

    python tools/topstepx_repair_rejected_mission.py \\
        --session PROD-20260904 --mission 1 \\
        --phrase "CLOSE THIS MISSION AS VENUE REJECTED ZERO FILL"

Add `--dry-run` to run every proof and stop before the write.
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))

from dotenv import find_dotenv, load_dotenv  # noqa: E402

load_dotenv(find_dotenv(usecwd=True))

from broker import topstepx_mission_state as MS  # noqa: E402
from broker import topstepx_order_discovery as DISC  # noqa: E402
from broker import topstepx_submission_record as SUB  # noqa: E402
from broker.topstepx_live_session import TopstepXLiveSession  # noqa: E402
from broker.topstepx_redaction import (account_fingerprint,  # noqa: E402
                                       redacted_account_label)

STORE_DIR = os.path.join("data", "integration", "topstepx")

#: Typed by the operator, in full. The same discipline the void ledger uses:
#: terminalizing a mission is an authorization-level act, not a keystroke.
REPAIR_PHRASE = "CLOSE THIS MISSION AS VENUE REJECTED ZERO FILL"


def prove_at_the_venue(symbol: str = "MNQ") -> dict:
    """Authenticate, pin, and READ. Raises rather than guessing."""
    session = TopstepXLiveSession()
    session.authenticate()
    session.pin(account_id=int(os.environ["TOPSTEPX_ACCOUNT_ID"]),
                expected_fingerprint=os.environ.get(
                    "TOPSTEPX_ACCOUNT_FINGERPRINT", ""))
    contract = session.resolve_contract(symbol)
    positions = session.open_positions()
    # THE COMPLETE SURFACE, not `searchOpen`. `discover_orders` labels its own
    # trustworthiness, and this tool refuses anything short of COMPLETE.
    found = DISC.discover_orders(session, contract_id=contract.id)
    # The NAME, not the account object. `redacted_account_label` masks trailing
    # digits off a name like "PRACTICEJUL2612345"; handed the dataclass it
    # masked the CLASS name instead and printed "TopstepXAccount[REDACTED]" --
    # safe, but it told the operator nothing about which account was pinned,
    # which is the only reason the line exists. Display only: the identity
    # PROOF is the computed fingerprint below, never this label.
    print(f"  account          : {redacted_account_label(session.account.name)}")
    print(f"  contract         : {contract.id}")
    print(f"  open positions   : {len(positions)}")
    print(f"  order discovery  : {found['source']} "
          f"(answered={found['answered']}, complete={found['complete']})")
    print(f"  working orders   : {len(found['working'] or [])}")
    for err in found["errors"]:
        print(f"    ! {err}")
    return {"positions": len(positions), "found": found,
            "contract_id": contract.id,
            # PROD-20260904 REVIEW FINDING 3. The identity the venue reads
            # actually describe, carried back so `main` can compare it with the
            # mission being repaired. Pinning proves we reached the account the
            # ENVIRONMENT names; it says nothing about whether that is the
            # account whose mission is on the operating table.
            "account_fingerprint": account_fingerprint(session.account.id,
                                                       session.account.name)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", required=True)
    ap.add_argument("--mission", type=int, required=True)
    ap.add_argument("--phrase", default="")
    ap.add_argument("--symbol", default="MNQ")
    ap.add_argument("--store-dir", default=STORE_DIR)
    ap.add_argument("--dry-run", action="store_true",
                    help="run every proof and stop before the write")
    args = ap.parse_args()

    path = os.path.join(args.store_dir,
                        f"trade_mission_{args.session}_{args.mission}.json")
    mission = MS.load(path)
    if mission is None:
        print(f"REFUSED: no mission record at {path}")
        return 2

    print("MISSION REPAIR -- VENUE_REJECTED_ZERO_FILL")
    print(f"  mission          : {mission.mission_id} ({mission.state})")
    print(f"  order id on file : {mission.order_id}")
    print(f"  token spent      : {mission.token_spent}")
    if mission.state in MS.TERMINAL_STATES:
        print(f"REFUSED: mission is already terminal ({mission.state}); "
              f"nothing to repair.")
        return 3
    if mission.attempt_count < 1:
        print("REFUSED: this mission never consumed an attempt, so it has no "
              "submission to attribute a rejection to.")
        return 3

    # ── what the flight recorder holds ───────────────────────────────────────
    evidence = SUB.mission_venue_evidence(
        args.store_dir, args.session, mission.mission_id,
        token_id=getattr(mission, "token_id", "") or "")
    print(f"  ledger rows      : {evidence.get('submission_count')} "
          f"(venue_order_ids={evidence.get('venue_order_ids')})")

    venue = prove_at_the_venue(args.symbol)
    found = venue["found"]

    # ── the venue we just read must BE this mission's venue ──────────────────
    #
    # REVIEW FINDING 3. Without this, the tool would pin whatever account the
    # environment names, read ITS positions and orders, find them flat and
    # empty -- and close a mission belonging to a different account or a
    # different contract on that evidence. Both were reproduced closing the
    # mission with token_spent=true and exit code 0.
    #
    # Flat somewhere else is not flat here.
    if not mission.account_fingerprint or \
            venue["account_fingerprint"] != mission.account_fingerprint:
        print(f"REFUSED: the pinned account is not this mission's account.\n"
              f"    mission : {mission.account_fingerprint}\n"
              f"    pinned  : {venue['account_fingerprint']}\n"
              f"  The venue reads describe a different account; they cannot "
              f"prove anything about this mission.")
        return 8
    if not mission.contract_id or venue["contract_id"] != mission.contract_id:
        print(f"REFUSED: the resolved contract is not this mission's contract.\n"
              f"    mission : {mission.contract_id}\n"
              f"    resolved: {venue['contract_id']}\n"
              f"  Pass --symbol for the contract this mission actually traded.")
        return 8

    if not found["answered"]:
        print("REFUSED: order discovery did not answer. 'we cannot see' is not "
              "'there is nothing there'.")
        return 4
    if not found["complete"]:
        print(f"REFUSED: order discovery is {found['source']}. A surface that "
              f"omits Suspended children cannot prove absence.")
        return 4

    working = len(found["working"] or [])
    ok, why = SUB.zero_fill_rejection(evidence, positions=venue["positions"],
                                      working_orders=working)
    print(f"  zero-fill rejection proven : {ok}")
    for reason in why:
        print(f"    - {reason}")
    if not ok:
        print("REFUSED: this is not a positively confirmed zero-fill rejection.")
        return 5

    if args.phrase != REPAIR_PHRASE:
        print(f'REFUSED: the operator phrase is required, verbatim:\n'
              f'    --phrase "{REPAIR_PHRASE}"')
        return 6

    # The venue's own words, from the recorded rejection row. Never re-derived.
    rejected = (evidence.get("rejected") or [{}])[-1]
    raw = rejected.get("raw_response") or {}
    venue_order_id = (raw.get("orderId") or rejected.get("venue_order_id")
                      or (evidence.get("venue_order_ids") or [None])[0])

    if args.dry_run:
        print("DRY RUN: every proof passed. Nothing was written.")
        print(f"  would write      : VENUE_REJECTED_ZERO_FILL "
              f"(order_id={venue_order_id}, attributed=True)")
        return 0

    # ── the SAME canonical transition production calls ───────────────────────
    out = mission.venue_rejected_zero_fill(
        venue_order_id=venue_order_id,
        error_code=raw.get("errorCode") or rejected.get("error_code"),
        error_message=(raw.get("errorMessage")
                       or rejected.get("error_message") or ""),
        positions=venue["positions"], working_orders=working,
        # The ledger's VENUE_REJECTED row IS the venue's recorded refusal of
        # this submission -- the same positive attribution the live path takes
        # from the exception, read back off disk instead of out of memory.
        venue_attributed=True)
    print(f"  written          : {out['state']} "
          f"(token_spent={out['token_spent']})")

    # ── it is only done if a NEW READ of the file says so ────────────────────
    reread = MS.load(path)
    print(f"  durable reload   : {reread.state} "
          f"(terminal={reread.state in MS.TERMINAL_STATES}, "
          f"attributed={reread.venue_attributed}, "
          f"token_spent={reread.token_spent})")
    if reread.state not in MS.TERMINAL_STATES:
        print("FAILED: the mission did not reload terminal.")
        return 7
    print("  phantom active mission cleared. The SAME session gets no retry: "
          "the attempt and the authorization remain spent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
