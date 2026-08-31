"""Record that a HUMAN looked at the venue UI and saw who owns protection.

    python tools/record_protection_attestation.py --confirmed-by "Maurice Phillips"

PROTECTION-AUTHORITY-1. The bot cannot see this: `/api/Account/search` publishes
six fields and none of them is a bracket setting. So this file exists only
because someone looked, and it is worth exactly as much as that look.

IT WILL NOT WRITE WITHOUT `--i-have-visually-confirmed`. That flag is not
ceremony -- an attestation created by a script that checked nothing is worse
than no attestation, because it looks like evidence.

BEFORE RUNNING, in the TopstepX UI, confirm ALL of:

    the selected account is   PRAC-V2-FIXTURE-00000000   (id 11111111)
    Position Risk/Profit Brackets   OFF / disabled
    bracket type = Auto-OCO         ON  / order-based

TWO DIFFERENT THINGS, corrected 2026-08-19. POSITION brackets are position-based
and account-level: they would author protection for the position our own order
already protects, so they stay OFF. Order-based AUTO-OCO is the MECHANISM our
attached `stopLossBracket`/`takeProfitBracket` rides on, so it stays ON. v1 of
this tool demanded both off; the venue then rejected the attached-bracket order
outright. The bot still owns the PRICES either way.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from dotenv import load_dotenv

load_dotenv()

from broker import topstepx_protection_authority as PA        # noqa: E402

STORE_DIR = os.path.join("data", "integration", "topstepx")
ET = ZoneInfo("America/New_York")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--confirmed-by", required=True,
                    help="the name of the person who looked at the venue UI")
    ap.add_argument("--session-date", default="",
                    help="ET session date this attests (default: today)")
    ap.add_argument("--account-id", default=os.getenv("TOPSTEPX_ACCOUNT_ID", ""))
    ap.add_argument("--account-fingerprint",
                    default=os.getenv("TOPSTEPX_ACCOUNT_FINGERPRINT", ""))
    ap.add_argument("--i-have-visually-confirmed", action="store_true",
                    help="Position Brackets OFF and Auto-OCO bracket mode ON, seen with your eyes")
    args = ap.parse_args(argv)

    session_date = args.session_date or datetime.now(ET).strftime("%Y-%m-%d")
    print(f"  ACCOUNT                       : {args.account_id}")
    print(f"  FINGERPRINT                   : {args.account_fingerprint}")
    print(f"  SESSION DATE (ET)             : {session_date}")
    print(f"  ATTESTING                     : Position Brackets OFF, "
          f"bracket mode = {PA.AUTO_OCO_ORDER_BASED},")
    print(f"                                  price author = {PA.BOT_ATTACHED_BRACKETS}")

    if not args.i_have_visually_confirmed:
        print("\n  NOT WRITTEN                   : --i-have-visually-confirmed absent.")
        print("  This record is only worth the look behind it. Confirm in the UI first.")
        return 2

    att = PA.build(account_id=args.account_id,
                   account_fingerprint=args.account_fingerprint,
                   session_date=session_date, confirmed_by=args.confirmed_by)
    reasons = PA.verify(att, account_id=args.account_id,
                        account_fingerprint=args.account_fingerprint,
                        session_date=session_date)
    if reasons:
        print("\n  REFUSED                       : the record would not verify")
        for r in reasons:
            print(f"    - {r}")
        return 2

    os.makedirs(STORE_DIR, exist_ok=True)
    path = PA.store_path(STORE_DIR)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(att, fh, indent=2)
    print(f"\n  WRITTEN                       : {path}")
    print(f"  ATTESTATION FINGERPRINT       : {att['attestation_fingerprint']}")
    print(f"  CONFIRMED BY                  : {att['confirmed_by_name']}")
    print("  Valid for this session date only. Venue settings can change overnight.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
