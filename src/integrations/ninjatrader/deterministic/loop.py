"""DETERMINISTIC_MNQ_SIM_ONLY — the running scan/execution loop.

Reconcile -> build MNQ snapshot -> assemble mechanical facts -> deterministic
author (20-condition gate) -> record evidence -> route a 15-contract bracket to
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
    MODE, AUTHOR, ACCOUNT, INSTRUMENT, TARGET_POINTS, MAX_STOP_POINTS,
    MAX_RISK_DOLLARS, MAX_CONTRACTS, MAX_TRADES_PER_DAY, DAILY_LOSS_CEILING,
    DECISION_WINDOW, TIMEZONE, FLATTEN_AT, FLATTEN_UNTIL,
    AUTO_FLATTEN_ENABLED,
)
from integrations.ninjatrader.deterministic import author as AUTH
from integrations.ninjatrader.deterministic import risk as RISK
from integrations.ninjatrader.deterministic import facts_provider as FP
from integrations.ninjatrader.deterministic import evidence as EV
from integrations.ninjatrader.deterministic.funnel import funnel_console
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


def _in_flatten_window(now=None) -> bool:
    """Inside the forced-flat window before the session close."""
    now = now or _now_et()
    if now.weekday() >= 5:            # futures are shut; nothing to close
        return False
    return FLATTEN_AT <= now.strftime("%H:%M") <= FLATTEN_UNTIL


def force_flat_if_due(client, session, pos, orders, scan_num) -> Optional[dict]:
    """Close any open position before the session close.

    Intraday size cannot be carried overnight: day margin is $100 a contract
    against $4,187.12 initial, so a compounded 83-lot position needs $347,531
    against a $50k account. Entries already stop at 14:00, but nothing closed an
    OPEN position — stop_lane.py does, and it is run by hand.

    Retries every scan across the window, because one failed flatten must not be
    the end of the attempt. A failure here is the most serious event this loop
    can produce, so it is shouted rather than logged quietly.
    """
    if not AUTO_FLATTEN_ENABLED or not _in_flatten_window():
        return None
    if not bool(pos.get("known")):
        print(f"[scan {scan_num}] !! FLATTEN WINDOW but position UNKNOWN — "
              f"cannot confirm flat before the close. CHECK MANUALLY.")
        return {"attempted": False, "reason": "position unknown"}

    qty = int(pos.get("qty", 0) or 0)
    working = int((orders or {}).get("working_order_count", 0) or 0)
    if qty == 0 and working == 0:
        return {"attempted": False, "reason": "already flat, no working orders"}

    print(f"[scan {scan_num}] FLATTEN WINDOW — closing {qty} contracts "
          f"({working} working orders) before the {FLATTEN_UNTIL} cutoff")
    result = client.flatten(INSTRUMENT)
    ok = bool(result.get("ok"))
    if ok:
        session.stop_new_entries(STOPPED_MANUAL)
        print(f"[scan {scan_num}] FLATTENED — {result}")
    else:
        print(f"[scan {scan_num}] !! FLATTEN FAILED: {result.get('reason')!r} — "
              f"{qty} contracts still open. Retrying next scan. FLATTEN MANUALLY "
              f"IF THIS PERSISTS.")
    return {"attempted": True, "ok": ok, "qty_before": qty,
            "working_before": working, "result": result}


def _stop_requested() -> bool:
    return os.path.exists(STOP_FILE)


def route_deterministic_order(client: NinjaTraderBridgeClient, decision) -> dict:
    """Send a 15-contract deterministic bracket. Bridge attaches the structural
    stop + 35pt target with fill-slippage re-check; Python verifies by polling."""
    qty = int(decision.quantity)
    payload = {
        "mode": MODE, "author": AUTHOR, "account": ACCOUNT, "instrument": INSTRUMENT,
        "direction": decision.direction, "quantity": qty,
        "structural_stop_price": decision.structural_stop,
        "target_points": TARGET_POINTS, "max_stop_points": MAX_STOP_POINTS,
    }
    ack = client.deterministic_order(payload)
    if not ack.get("accepted"):
        flat = client.flatten(INSTRUMENT)
        return {"transmitted": False, "reason": ack.get("reason"), "safety_flatten": flat}
    # Poll fill + protection (position qty == +/- sized qty, 2 working orders).
    deadline = time.time() + 12.0
    while time.time() < deadline:
        pos = client.position(INSTRUMENT)
        orders = client.order_summary()
        if pos.get("known") and abs(int(pos.get("qty", 0))) == qty \
                and orders.get("working_order_count") == 2:
            return {"transmitted": True, "fill_price": pos.get("avg_price"),
                    "position": pos, "orders": orders}
        time.sleep(0.5)
    pos = client.position(INSTRUMENT)
    orders = client.order_summary()
    protected = orders.get("working_order_count") == 2
    filled = pos.get("known") and abs(int(pos.get("qty", 0))) == qty
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
    prior_qty = session.active_position_qty          # BEFORE reconcile overwrites it
    session.apply_reconciliation(pos, orders)

    # Detect a CLOSED trade (was positioned, now flat) and record the exact realized
    # P&L from the broker (30s scans can't see the intrabar OCO fill). Delta =
    # broker realized now - baseline captured at open. Updates the daily-loss ceiling.
    if bool(pos.get("known")) and prior_qty != 0 and int(pos.get("qty", 0)) == 0:
        realized_now = float(acct.get("realized_pnl", 0.0) or 0.0)
        delta = round(realized_now - session.open_realized_baseline, 2)
        session.record_trade_closed(delta)
        print(f"[scan {scan_num}] TRADE CLOSED — realized ${delta:+.2f} "
              f"(session realized ${session.realized_pnl:+.2f}, state {session.state})")

    # 1b. Forced flat before the close. Runs BEFORE any entry evaluation so a
    # scan can never open size in the same pass it is meant to be closing.
    flatten_action = force_flat_if_due(client, session, pos, orders, scan_num)
    if flatten_action and flatten_action.get("attempted"):
        pos = client.position(INSTRUMENT)          # re-read; state just changed
        orders = client.order_summary()
        session.apply_reconciliation(pos, orders)

    account_known = bool(acct.get("account") == ACCOUNT)
    armed = env.get("arm_orders") is True
    in_window = _in_decision_window()
    can_enter, can_reason = session.can_enter()

    # 2. Build MNQ snapshot + mechanical facts from the REAL organism authorities.
    # Warm up with ~2000 bars (~1.4 days): 400 starves the higher-timeframe
    # structure/narrative engines so they never detect a setup.
    bars = client.historical_1m(INSTRUMENT, 2000, days_back=10, max_bars=2500)
    quote = client.quote(INSTRUMENT)
    facts = FP.build_facts(bars, quote)

    # 3. Deterministic author (fail-closed 20-gate).
    decision = AUTH.evaluate(
        facts, account_known=account_known,
        position_known=bool(pos.get("known")), orders_known=bool(orders.get("known")),
        reconciliation_ok=session.last_reconcile_ok,
        realized_daily_loss=session.realized_loss(),
        can_enter=can_enter, can_enter_reason=can_reason,
        # Live equity from the bridge — this is what makes risk compound.
        equity=acct.get("cash_value"))

    verdict = "NO_TRADE"
    routed = None
    # 4. Route only if authorized AND admissible AND armed AND in window.
    if decision.authorized and can_enter and armed and in_window:
        routed = route_deterministic_order(client, decision)
        if routed.get("transmitted"):
            session.record_trade_opened(order_ids=[f"det-{scan_num}"], quantity=decision.quantity,
                                        realized_baseline=float(acct.get("realized_pnl", 0.0) or 0.0))
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
        "flatten_action": flatten_action,
        # Compounding audit: the equity sizing was actually based on, and the
        # budget/ceiling it produced. Without this a size change is unexplainable.
        "equity": acct.get("cash_value"),
        "risk_budget": RISK.risk_budget(acct.get("cash_value"))[1],
        "daily_ceiling": RISK.daily_loss_ceiling(acct.get("cash_value"))[1],
        "snapshot": {"bars": len(bars), "last": quote.get("last"),
                     "setup_family": facts.get("setup_family"),
                     "mech_direction": facts.get("direction"),
                     "decision_state": facts.get("_decision_state"),
                     "qual_status": facts.get("_qual_status"),
                     "commander": facts.get("commander_state"),
                     "invalidation": facts.get("entry_invalidation"),
                     # Diagnostics — why a NO_TRADE was a NO_TRADE.
                     # gate_blockers names which authority refused; without it
                     # final_gate_authorizes is a bare False covering six of them.
                     "gate_permissions": facts.get("_gate_permissions"),
                     "gate_blockers": facts.get("_gate_blockers"),
                     "funnel": facts.get("_funnel"),
                     "fc0b_reason": facts.get("_fc0b_reason"),
                     "fc0b_inputs": facts.get("_fc0b_inputs"),
                     "zone": facts.get("_zone"),
                     "swings": facts.get("_swings")},
        "blockers": decision.blockers(),
        "routed": routed,
    }
    EV.record_scan(session.session_id, scan_num, scan_record)
    return scan_record


def run(max_scans: Optional[int] = None):
    session = SessionAuthority.resume_or_new()
    print(f"MODE: {MODE}  AUTHOR: {AUTHOR}  SESSION: {session.session_id}")
    print(f"ACCOUNT: {ACCOUNT}  INSTRUMENT: {INSTRUMENT}  RISK/TRADE: ${MAX_RISK_DOLLARS} "
          f"(size scales to stop, max {MAX_CONTRACTS} contracts)  "
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
                # Name the refusing authority inline. `final_gate_authorizes:False`
                # covers six independent authorities; printing it alone is how a
                # hidden veto stays hidden.
                _gb = (rec.get("snapshot") or {}).get("gate_blockers") or []
                _auth = f" | gate_refused={','.join(_gb)}" if _gb else ""
                print(f"[scan {scan_num}] {rec['verdict']} | window={rec['in_decision_window']} "
                      f"armed={rec['bridge_armed']} trades={rec['trade_count']} "
                      f"pnl=${rec['realized_pnl']} | top_blocker="
                      f"{(rec['blockers'][0] if rec['blockers'] else 'none')}{_auth}")
                # How far the read got before anything refused. A NO_TRADE that
                # died at `authority` and one held a single scan short on setup
                # age are the same word on the line above and nothing alike.
                _fn = (rec.get("snapshot") or {}).get("funnel")
                if _fn:
                    print("        " + funnel_console(_fn).replace("\n", "\n  "))
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
