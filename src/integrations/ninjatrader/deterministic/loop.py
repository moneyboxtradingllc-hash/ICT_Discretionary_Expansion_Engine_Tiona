"""DETERMINISTIC_MNQ_SIM_ONLY — the running scan/execution loop.

Reconcile -> build MNQ snapshot -> assemble mechanical facts -> deterministic
author (20-condition gate) -> record evidence -> route a 5-contract bracket to
the bridge ONLY when authorized and admissible. Fail-closed everywhere.

Runs until the STOP file appears, the daily trade limit or loss ceiling is hit,
EOD, or a safety/reconciliation failure. NEVER calls OpenAI.
"""
from __future__ import annotations

import datetime as _dt
import os
import time
from typing import Optional

from integrations.ninjatrader.bridge_client import NinjaTraderBridgeClient
from integrations.ninjatrader.deterministic import (
    MODE, AUTHOR, ACCOUNT, INSTRUMENT, QUANTITY, TARGET_POINTS, MAX_STOP_POINTS,
    MAX_TRADES_PER_DAY, DAILY_LOSS_CEILING, DECISION_WINDOW, TIMEZONE,
)
from integrations.ninjatrader.deterministic import author as AUTH
from integrations.ninjatrader.deterministic import facts_provider as FP
from integrations.ninjatrader.deterministic import evidence as EV
from integrations.ninjatrader.deterministic.session import SessionAuthority, ACTIVE, STOPPED_MANUAL

STOP_FILE = os.path.join("data", "integration", "ninjatrader", "deterministic", "STOP")
SCAN_INTERVAL_SECONDS = 30
PORT = 36901


def _now_et():
    try:
        from zoneinfo import ZoneInfo
        return _dt.datetime.now(ZoneInfo(TIMEZONE))
    except Exception:
        return _dt.datetime.now()


def _in_decision_window(now=None) -> bool:
    now = now or _now_et()
    hm = now.strftime("%H:%M")
    return DECISION_WINDOW[0] <= hm <= DECISION_WINDOW[1]


def _stop_requested() -> bool:
    return os.path.exists(STOP_FILE)


def route_deterministic_order(client: NinjaTraderBridgeClient, decision) -> dict:
    """Send a 5-contract deterministic bracket. Bridge attaches the structural
    stop + 35pt target with fill-slippage re-check; Python verifies by polling."""
    payload = {
        "mode": MODE, "author": AUTHOR, "account": ACCOUNT, "instrument": INSTRUMENT,
        "direction": decision.direction, "quantity": QUANTITY,
        "structural_stop_price": decision.structural_stop,
        "target_points": TARGET_POINTS, "max_stop_points": MAX_STOP_POINTS,
    }
    ack = client.deterministic_order(payload)
    if not ack.get("accepted"):
        flat = client.flatten(INSTRUMENT)
        return {"transmitted": False, "reason": ack.get("reason"), "safety_flatten": flat}
    # Poll fill + protection (position qty == +/-5, 2 working orders).
    deadline = time.time() + 12.0
    while time.time() < deadline:
        pos = client.position(INSTRUMENT)
        orders = client.order_summary()
        if pos.get("known") and abs(int(pos.get("qty", 0))) == QUANTITY \
                and orders.get("working_order_count") == 2:
            return {"transmitted": True, "fill_price": pos.get("avg_price"),
                    "position": pos, "orders": orders}
        time.sleep(0.5)
    pos = client.position(INSTRUMENT)
    orders = client.order_summary()
    protected = orders.get("working_order_count") == 2
    filled = pos.get("known") and abs(int(pos.get("qty", 0))) == QUANTITY
    if filled and protected:
        return {"transmitted": True, "fill_price": pos.get("avg_price"),
                "position": pos, "orders": orders}
    flat = client.flatten(INSTRUMENT)   # EMERGENCY FLATTEN
    return {"transmitted": False, "reason": "fill/protection incomplete - emergency flatten",
            "filled": filled, "protected": protected, "flatten": flat}


def one_scan(client: NinjaTraderBridgeClient, session: SessionAuthority, scan_num: int) -> dict:
    # 1. Reconcile live state (fail closed if unknown).
    pos = client.position(INSTRUMENT)
    orders = client.order_summary()
    acct = client.account_state()
    env = client.environment_proof()
    session.apply_reconciliation(pos, orders)

    account_known = bool(acct.get("account") == ACCOUNT)
    armed = env.get("arm_orders") is True
    in_window = _in_decision_window()
    can_enter, can_reason = session.can_enter()

    # 2. Build MNQ snapshot + mechanical facts from the REAL organism authorities.
    bars = client.historical_1m(INSTRUMENT, 400)
    quote = client.quote(INSTRUMENT)
    facts = FP.build_facts(bars, quote)

    # 3. Deterministic author (fail-closed 20-gate).
    decision = AUTH.evaluate(
        facts, account_known=account_known,
        position_known=bool(pos.get("known")), orders_known=bool(orders.get("known")),
        reconciliation_ok=session.last_reconcile_ok,
        realized_daily_loss=session.realized_loss(),
        can_enter=can_enter, can_enter_reason=can_reason)

    verdict = "NO_TRADE"
    routed = None
    # 4. Route only if authorized AND admissible AND armed AND in window.
    if decision.authorized and can_enter and armed and in_window:
        routed = route_deterministic_order(client, decision)
        if routed.get("transmitted"):
            session.record_trade_opened(order_ids=[f"det-{scan_num}"])
            verdict = "TRADE_OPENED"
        else:
            verdict = "TRADE_ROUTE_FAILED"
    elif decision.authorized and not (armed and in_window and can_enter):
        verdict = "AUTHORIZED_BUT_BLOCKED"

    scan_record = {
        "verdict": verdict,
        "in_decision_window": in_window, "bridge_armed": armed,
        "account_known": account_known, "reconciliation_ok": session.last_reconcile_ok,
        "can_enter": can_enter, "can_enter_reason": can_reason,
        "position": pos, "orders": orders,
        "trade_count": session.trade_count, "realized_pnl": session.realized_pnl,
        "author": decision.to_dict(),
        "snapshot": {"bars": len(bars), "last": quote.get("last"),
                     "setup_family": facts.get("setup_family"),
                     "mech_direction": facts.get("direction"),
                     "decision_state": facts.get("_decision_state"),
                     "qual_status": facts.get("_qual_status"),
                     "commander": facts.get("commander_state"),
                     "invalidation": facts.get("entry_invalidation")},
        "blockers": decision.blockers(),
        "routed": routed,
    }
    EV.record_scan(session.session_id, scan_num, scan_record)
    return scan_record


def run(max_scans: Optional[int] = None):
    session = SessionAuthority.resume_or_new()
    print(f"MODE: {MODE}  AUTHOR: {AUTHOR}  SESSION: {session.session_id}")
    print(f"ACCOUNT: {ACCOUNT}  INSTRUMENT: {INSTRUMENT}  CONTRACTS: {QUANTITY}  "
          f"TARGET: {TARGET_POINTS}pt  MAX STOP: {MAX_STOP_POINTS}pt  "
          f"MAX TRADES: {MAX_TRADES_PER_DAY}  DAILY LOSS CEILING: ${DAILY_LOSS_CEILING}")
    print("OPENAI CALLS: DISABLED  ATM TEMPLATE: NOT USED  AUTOMATED SIM TRADING: ENABLED")

    scan_num = 0
    while True:
        if _stop_requested():
            session.stop_new_entries(STOPPED_MANUAL)
            print(f"[stop] STOP file present — no new entries; session {session.state}")
            break
        if max_scans is not None and scan_num >= max_scans:
            break
        scan_num += 1
        client = NinjaTraderBridgeClient(port=PORT, timeout=6.0, account=ACCOUNT, instrument=INSTRUMENT)
        if not client.connect():
            EV.record_scan(session.session_id, scan_num,
                           {"verdict": "NO_TRADE", "blockers": ["bridge_not_connected"]})
            print(f"[scan {scan_num}] bridge not connected — NO TRADE")
        else:
            try:
                rec = one_scan(client, session, scan_num)
                print(f"[scan {scan_num}] {rec['verdict']} | window={rec['in_decision_window']} "
                      f"armed={rec['bridge_armed']} trades={rec['trade_count']} "
                      f"pnl=${rec['realized_pnl']} | top_blocker="
                      f"{(rec['blockers'][0] if rec['blockers'] else 'none')}")
            finally:
                client.close()
            if session.state != ACTIVE:
                print(f"[stop] session {session.state} — ending loop")
                break
        if max_scans is None:
            time.sleep(SCAN_INTERVAL_SECONDS)
    print(f"DETERMINISTIC LOOP ENDED — session {session.session_id} state {session.state}")
    return session


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-scans", type=int, default=None)
    a = ap.parse_args()
    run(max_scans=a.max_scans)
