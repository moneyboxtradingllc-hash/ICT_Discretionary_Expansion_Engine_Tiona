"""Attribute a session's balance movement to BOT / MANUAL / FEE, or refuse.

SEAL-PROD-20260807-SESSION-EVIDENCE (2026-08-07).

PROD-20260807 closed with the account down $13.30 while the bot's own evidence
showed 0 candidates, 0 attempts, 0 orders, 0 fills. The operator reported
trading manually. That report is NOT the proof -- an operator's recollection is
testimony, and this file only accepts venue records.

Attribution joins Trade.orderId -> Order.id and reads the bot's customTag off
the ORDER, because this venue does not carry the tag on trade records
(measured 2026-08-05). If the venue cannot account for the movement, the answer
is BALANCE_CHANGE_ATTRIBUTION_UNRESOLVED, not a plausible story.

READ-ONLY. No order endpoint is reachable from this module.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))

TOLERANCE_USD = 0.01


def reconcile(orders: list, trades: list, *, known_token_ids: set,
              starting_balance: float | None,
              ending_balance: float | None) -> dict:
    """Pure attribution. No I/O, so the law is testable without a venue."""
    from broker.topstepx_session_ledger import (EXPANSION_BOT, classify)

    index = {o.get("id"): {"customTag": o.get("custom_tag")} for o in orders}
    index.update({str(o.get("id")): {"customTag": o.get("custom_tag")}
                  for o in orders})

    bot_orders, other_orders = [], []
    for o in orders:
        origin = classify({"customTag": o.get("custom_tag")},
                          known_token_ids, index)
        (bot_orders if origin == EXPANSION_BOT else other_orders).append(o)

    bot_fills, other_fills = [], []
    realised = fees = 0.0
    for t in trades:
        if t.get("voided"):
            continue
        origin = classify({"orderId": t.get("order_id")}, known_token_ids, index)
        (bot_fills if origin == EXPANSION_BOT else other_fills).append(t)
        realised += float(t.get("pnl") or 0.0)
        fees += float(t.get("fees") or 0.0)

    observed = (None if starting_balance is None or ending_balance is None
                else round(ending_balance - starting_balance, 2))
    explained = round(realised - fees, 2)

    if observed is None:
        status = "BALANCE_CHANGE_ATTRIBUTION_UNRESOLVED"
        detail = "balances not both available"
    elif not trades and abs(observed) > TOLERANCE_USD:
        status = "BALANCE_CHANGE_ATTRIBUTION_UNRESOLVED"
        detail = ("venue returned no trades in the window, so the movement is "
                  "not accounted for by any record this tool can read")
    elif abs(explained - observed) <= TOLERANCE_USD:
        if bot_fills and other_fills:
            status = "MIXED_BOT_AND_EXTERNAL"
        elif bot_fills:
            status = "BOT"
        elif other_fills:
            status = "MANUAL_OR_EXTERNAL"
        else:
            status = "PLATFORM_FEE_OR_ADJUSTMENT"
        detail = f"realised {realised:+.2f} less fees {fees:.2f} = {explained:+.2f}"
    else:
        status = "BALANCE_CHANGE_ATTRIBUTION_UNRESOLVED"
        detail = (f"venue records explain {explained:+.2f} but the balance "
                  f"moved {observed:+.2f}; residual "
                  f"{observed - explained:+.2f} is unattributed")

    # Two questions, two answers. "Did the bot do this?" is answerable from
    # tags alone and does not depend on the balance closing. Conflating them
    # would let an unexplained dollar figure cast doubt on a clean bot record.
    bot_attribution = ("BOT_ACTIVITY_ABSENT" if not bot_orders and not bot_fills
                       else "BOT_ACTIVITY_PRESENT")

    return {
        "bot_attribution": bot_attribution,
        "bot_generated_order_ids": len(bot_orders),
        "bot_fills": len(bot_fills),
        "non_bot_orders": len(other_orders),
        "non_bot_fills": len(other_fills),
        "orders_in_window": len(orders),
        "trades_in_window": len(trades),
        "realised_pnl": round(realised, 2), "fees": round(fees, 2),
        "explained_change": explained, "observed_change": observed,
        "balance_change_classification": status,
        "detail": detail,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--session-id", required=True)
    ap.add_argument("--start-iso", required=True)
    ap.add_argument("--end-iso", required=True)
    ap.add_argument("--starting-balance", type=float)
    ap.add_argument("--ending-balance", type=float)
    ap.add_argument("--offline", action="store_true",
                    help="skip the venue; report UNRESOLVED honestly")
    args = ap.parse_args(argv)

    orders, trades, reachable = [], [], False
    if not args.offline:
        try:
            from dotenv import find_dotenv, load_dotenv
            load_dotenv(find_dotenv())
            from broker.topstepx_client import TopstepXClient
            client = TopstepXClient(os.environ.get("TOPSTEPX_USERNAME", ""),
                                    os.environ.get("TOPSTEPX_API_KEY", ""))
            accounts = client.accounts(only_active=True)
            if not accounts:
                raise RuntimeError("no active account")
            account_id = accounts[0].id
            orders = client.order_history(account_id, args.start_iso, args.end_iso)
            trades = client.trade_history(account_id, args.start_iso, args.end_iso)
            reachable = True
        except Exception as exc:  # noqa: BLE001
            print(f"  venue history UNAVAILABLE: {type(exc).__name__}: {exc}")

    known = set()
    try:
        from broker.topstepx_session_ledger import SessionLedger  # noqa: F401
        known = {str(o.get("custom_tag", "")).split("-")[1]
                 for o in orders if str(o.get("custom_tag") or "").count("-") >= 1}
    except Exception:  # noqa: BLE001
        pass

    result = reconcile(orders, trades, known_token_ids=known,
                       starting_balance=args.starting_balance,
                       ending_balance=args.ending_balance)
    result["venue_history_reachable"] = reachable
    if not reachable:
        result["balance_change_classification"] = \
            "BALANCE_CHANGE_ATTRIBUTION_UNRESOLVED"
        result["detail"] = ("venue order/trade history was not reachable; "
                            "no attribution is asserted")

    print("=" * 78)
    print(f"  ACTIVITY RECONCILIATION -- {args.session_id}")
    print("=" * 78)
    for k, v in result.items():
        print(f"  {k:38}: {v}")
    out = os.path.join("data", "replay_sessions", args.session_id,
                       "activity_reconciliation.json")
    if os.path.isdir(os.path.dirname(out)):
        json.dump(result, open(out, "w", encoding="utf-8"), indent=1)
        print(f"\n  written: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
