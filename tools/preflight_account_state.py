"""Read-only account safety preflight. Places nothing, changes nothing.

Authenticates, pins with the enforced fingerprint, resolves the contract and
reads position/order state. No market hub, no scan loop, no order path.

Lives in `tools/` because `load_dotenv()` resolves `.env` by walking up from the
calling file. Prints a redacted label only -- never a full account id or
fingerprint.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from broker.topstepx_live_session import TopstepXLiveSession  # noqa: E402
from broker.topstepx_redaction import redacted_account_label  # noqa: E402


def main(symbol: str = "MNQ") -> int:
    session = TopstepXLiveSession()
    session.authenticate()
    session.pin(account_id=int(os.environ["TOPSTEPX_ACCOUNT_ID"]),
                expected_fingerprint=os.environ.get(
                    "TOPSTEPX_ACCOUNT_FINGERPRINT", ""))
    contract = session.resolve_contract(symbol)
    acct = session.account
    positions = session.open_positions()
    orders = session.open_orders()

    print("PHASE 2 -- ACCOUNT READ-ONLY PREFLIGHT")
    print(f"  account            : {redacted_account_label(acct)}")
    print(f"  account mode       : "
          f"{'COMBINE_SIMULATED' if getattr(acct, 'simulated', True) else 'COMBINE_LIVE'}")
    print(f"  can trade          : {getattr(acct, 'canTrade', None)}")
    print(f"  is visible         : {getattr(acct, 'isVisible', None)}")
    print(f"  balance USD        : {getattr(acct, 'balance', None)}")
    print(f"  open positions     : {len(positions)}")
    print(f"  working orders     : {len(orders)}")
    print(f"  resolved contract  : {contract.id}")
    flat = (len(positions) == 0 and len(orders) == 0)
    print(f"  FLAT               : {flat}")
    return 0 if flat else 1


if __name__ == "__main__":
    raise SystemExit(main())
