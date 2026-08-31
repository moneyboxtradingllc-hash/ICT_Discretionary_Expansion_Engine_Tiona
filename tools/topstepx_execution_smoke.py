"""Bounded TopstepX execution-lifecycle smoke. ONE MNQ, one attempt, flatten now.

Proves the plumbing only:

    authorization -> submit -> ack -> fill -> protection -> reconcile
    -> controlled flatten -> residual cleanup -> verified flat

This is NOT a trade thesis. The direction is the smoke convention (long), the
10-point protective distance is an emergency bound on a lifecycle that lasts
seconds, and the position is flattened as soon as the chain is proven. Realized
P&L is reported accurately and means nothing.

The one-attempt allowance is persisted BEFORE the request can leave, so a crash
mid-flight cannot hand back a second attempt.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from dotenv import load_dotenv

load_dotenv()

from broker import topstepx_mission_state as MS
from broker import topstepx_session_ledger as LG
from broker.topstepx_client import ORDER_SIDE, ORDER_TYPE, TopstepXError
from broker.topstepx_live_session import TopstepXLiveSession
from broker.topstepx_hard_flatten import hard_flatten
from broker import topstepx_order_discovery as DISC
from broker.topstepx_redaction import account_fingerprint, assert_clean, redacted_account_label

ET = timezone(timedelta(hours=-4))
STATE_DIR = os.path.join("data", "integration", "topstepx")
# Each authorized attempt gets its OWN durable record. A new mission never
# overwrites a previous one — the rejected 20260805 mission stays terminal on
# disk as evidence that its attempt was spent.
MISSION_ID = os.getenv("SMOKE_MISSION_ID", f"exec-smoke-{datetime.now(ET):%Y%m%d}")
STATE_PATH = os.path.join(STATE_DIR, f"smoke_mission_{MISSION_ID}.json")
EVIDENCE = os.path.join(STATE_DIR,
                        f"execution_smoke_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json")

# BRACKETLESS MODE (2026-08-05). The account has Position Brackets enabled and
# the venue refuses order-attached brackets alongside them:
#   errorCode=2 "Brackets cannot be used with Position Brackets."
# So the entry is submitted bare and the account's own bracket engine supplies
# protection. This is strictly weaker than attaching protection at submit —
# there is a real window between fill and protection appearing — which is why
# the window is polled tightly and an unprotected fill is flattened at once
# rather than waited on.
BRACKETLESS = os.getenv("SMOKE_BRACKETLESS", "1") not in ("0", "false", "off")

SMOKE_DIRECTION = "buy"          # smoke convention; NOT a market prediction
SMOKE_SIZE = 1
PROTECT_POINTS = 10.0            # emergency bound only  -> 40 ticks
TARGET_TICKS = int(os.getenv("SMOKE_TARGET_TICKS", "80"))   # 20.0 pts
FILL_DEADLINE = 20.0
PROTECT_DEADLINE = 15.0


def _reference_price(contract) -> float:
    """Latest CLOSED Topstep 1m close — the bot's own data, not a UI value."""
    cache = os.path.join("data", "market_data", "topstepx",
                         contract.id.replace(".", "_") + ".jsonl")
    last = None
    with open(cache, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    last = json.loads(line)
                except Exception:  # noqa: BLE001
                    continue
    if not last:
        raise RuntimeError("no Topstep candle available for a reference price")
    px = float(last["close"])
    return round(px / contract.tick_size) * contract.tick_size


def log(msg):
    print(f"[{datetime.now(ET):%H:%M:%S} ET] {msg}", flush=True)


def main() -> int:
    ev = {"mission": "TOPSTEPX EXECUTION-LIFECYCLE SMOKE", "steps": [],
          "started_utc": datetime.now(timezone.utc).isoformat()}

    def step(name, **kw):
        ev["steps"].append({"step": name, "at": datetime.now(timezone.utc).isoformat(), **kw})
        return kw

    session = TopstepXLiveSession()
    session.authenticate()
    acct = session.pin(account_id=os.getenv("TOPSTEPX_ACCOUNT_ID"),
                       expected_fingerprint=os.getenv("TOPSTEPX_ACCOUNT_FINGERPRINT", ""))
    contract = session.resolve_contract(os.getenv("TOPSTEPX_CONTRACT") or "MNQ")
    fp = account_fingerprint(acct.id, acct.name)

    log("=" * 66)
    log("EXECUTION-LIFECYCLE SMOKE — 1 MNQ, one attempt, immediate flatten")
    log(f"account {fp}  contract {contract.id} tick={contract.tick_size}")
    ev["account"] = {"fingerprint": fp, "label": redacted_account_label(acct.name),
                     "can_trade": acct.can_trade, "is_visible": acct.is_visible,
                     "balance_before": acct.balance}
    ev["contract"] = {"id": contract.id, "name": contract.name,
                      "tick_size": contract.tick_size, "tick_value": contract.tick_value}

    # ── 1. pre-entry reconciliation ───────────────────────────────────────────
    positions, orders = session.open_positions(), session.open_orders()
    step("pre_entry", positions=len(positions), working_orders=len(orders))
    if positions or orders:
        log(f"ABORT: not flat ({len(positions)} pos, {len(orders)} orders)")
        return finish(ev, session, 1)
    log(f"pre-entry: FLAT, 0 working orders")

    ledger = LG.SessionLedger.load_or_new(fp, datetime.now(ET).strftime("%Y%m%d"), STATE_DIR)
    ledger.reconcile_trades(session.recent_trades())
    if ledger.requires_pause():
        log(f"ABORT: {ledger.requires_pause()}")
        return finish(ev, session, 1)

    mission = MS.open_mission(path=STATE_PATH,
                              mission_id=MISSION_ID,
                              account_fingerprint=fp, contract_id=contract.id,
                              authorization_fingerprint="exec-lifecycle-smoke-1mnq",
                              max_attempts=1)
    allowed, why = mission.may_attempt_entry()
    step("durable_state", state=mission.state, attempt_count=mission.attempt_count,
         allowed=allowed, reason=why)
    if not allowed:
        log(f"ABORT: durable state refuses a new attempt — {why}")
        return finish(ev, session, 1)
    log(f"durable state: {mission.state} attempts={mission.attempt_count}/1")

    # ── 2. build the entry THROUGH BracketGeometry ────────────────────────────
    # The payload is produced by the same code production will use, so the
    # signed-tick convention is proven where it actually lives — not re-derived
    # here. Hand-signing the payload would validate the script, not the bot.
    stop_ticks = int(round(PROTECT_POINTS / contract.tick_size))     # 40
    ref_price = _reference_price(contract)
    geo = None
    if not BRACKETLESS:
        from broker.topstepx_combine_risk import build_bracket
        direction = "bullish" if SMOKE_DIRECTION == "buy" else "bearish"
        sign = -1 if direction == "bullish" else 1
        geo = build_bracket(
            direction=direction, entry_price=ref_price,
            invalidation_level=ref_price + sign * PROTECT_POINTS,
            target_price=ref_price - sign * (TARGET_TICKS * contract.tick_size),
            contract=contract, size=SMOKE_SIZE)
        payload = geo.as_order_payload(acct.id, contract.id)
        log(f"geometry: entry~{ref_price} stop={geo.stop_price} target={geo.target_price} "
            f"signed_ticks stop={geo.signed_stop_ticks()} target={geo.signed_target_ticks()} "
            f"risk=${geo.risk_usd:.2f} R={geo.reward_usd / geo.risk_usd:.2f}")
    else:
        payload = {
            "accountId": acct.id, "contractId": contract.id,
            "type": ORDER_TYPE["market"], "side": ORDER_SIDE[SMOKE_DIRECTION],
            "size": SMOKE_SIZE,
            "limitPrice": None, "stopPrice": None, "trailPrice": None,
            "customTag": None,
            "stopLossBracket": None, "takeProfitBracket": None,
        }
    token_id = f"execsmoke-{datetime.now(timezone.utc):%H%M%S}"
    payload["customTag"] = LG.bot_tag(token_id)
    ledger.record_token(token_id)
    if BRACKETLESS:
        log(f"entry: {SMOKE_DIRECTION.upper()} {SMOKE_SIZE} {contract.name} MARKET, "
            f"BRACKETLESS — account Position Brackets must supply protection; "
            f"unprotected fill is flattened immediately")
    else:
        log(f"entry: {SMOKE_DIRECTION.upper()} {SMOKE_SIZE} {contract.name} MARKET, "
            f"ATTACHED stop {stop_ticks} ticks ({PROTECT_POINTS} pts, "
            f"${stop_ticks * contract.tick_value:.2f} risk) + target {TARGET_TICKS} ticks")
    step("entry_plan", direction=SMOKE_DIRECTION, size=SMOKE_SIZE,
         stop_ticks=stop_ticks, protect_points=PROTECT_POINTS,
         bracketless=BRACKETLESS,
         planned_risk_usd=stop_ticks * contract.tick_value,
         request_digest={**payload, "accountId": "[REDACTED]"})

    # ── 3. PERSIST THE ATTEMPT BEFORE THE REQUEST CAN LEAVE ───────────────────
    mission.consume_attempt(candidate_fingerprint="exec-smoke-deterministic",
                            token_id=token_id)
    ledger.save()
    log(f"ATTEMPT PERSISTED (durable) — state={mission.state} count={mission.attempt_count}")
    step("attempt_consumed", state=mission.state, attempt_count=mission.attempt_count,
         token_id=token_id)

    # ── 4. ONE submission ─────────────────────────────────────────────────────
    t0 = time.time()
    try:
        result = session.place_order(payload)
        ack_ms = int((time.time() - t0) * 1000)
        order_id = result.get("order_id")
        log(f"ACK order_id={order_id} in {ack_ms}ms")
        step("submit", accepted=True, order_id=order_id, ack_ms=ack_ms)
    except Exception as exc:  # noqa: BLE001
        log(f"SUBMIT UNCERTAIN/REJECTED: {type(exc).__name__}: {str(exc)[:200]}")
        mission.transition(MS.SUBMIT_UNKNOWN, f"{type(exc).__name__}")
        step("submit", accepted=False, error=f"{type(exc).__name__}: {str(exc)[:200]}")
        return reconcile_unknown(ev, session, mission, ledger, contract)

    mission.order_id = order_id
    mission.transition(MS.POSITION_OPEN, f"order {order_id}")

    # ── 5. fill + protection ──────────────────────────────────────────────────
    pos, prot, deadline = None, [], time.time() + FILL_DEADLINE
    while time.time() < deadline:
        time.sleep(1.0)
        pos_rows = session.open_positions()
        if pos_rows:
            pos = pos_rows[0]
            break
    if pos is None:
        log("NO FILL OBSERVED within deadline — reconciling")
        return reconcile_unknown(ev, session, mission, ledger, contract)

    entry_px = float(pos.get("avg_price") or 0)
    log(f"FILLED {pos.get('side')} {pos.get('size')} @ {entry_px}")
    step("fill", side=pos.get("side"), size=pos.get("size"), avg_price=entry_px,
         position_id=pos.get("id"))

    deadline = time.time() + PROTECT_DEADLINE
    while time.time() < deadline:
        prot = [o for o in session.open_orders() if o.get("contract_id") == contract.id]
        if prot:
            break
        time.sleep(0.5)          # tight poll: the position is live and bare

    stop_orders = [o for o in prot if int(o.get("type") or 0) == 4]
    target_orders = [o for o in prot if int(o.get("type") or 0) == 1]
    tick = contract.tick_size

    def px_of(rows, key):
        if not rows:
            return None
        v = rows[0].get(key)
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    stop_px = px_of(stop_orders, "stop_price")
    target_px = px_of(target_orders, "limit_price")
    checks = {
        "position_qty_is_1": int(pos.get("size") or 0) == SMOKE_SIZE,
        "stop_exists": len(stop_orders) == 1,
        "target_exists": len(target_orders) == 1,
        "stop_qty_is_1": bool(stop_orders) and int(stop_orders[0].get("size") or 0) == 1,
        "target_qty_is_1": bool(target_orders) and int(target_orders[0].get("size") or 0) == 1,
        "stop_correct_side": stop_px is not None and stop_px < entry_px,
        "target_correct_side": target_px is not None and target_px > entry_px,
        "stop_distance_40_ticks": (stop_px is not None
                                   and abs(round((entry_px - stop_px) / tick) - stop_ticks) <= 1),
        "target_distance_80_ticks": (target_px is not None
                                     and abs(round((target_px - entry_px) / tick) - TARGET_TICKS) <= 1),
        "no_duplicate_protection": len(stop_orders) <= 1 and len(target_orders) <= 1,
    }
    stop_dist = None if stop_px is None else round((entry_px - stop_px) / tick)
    tgt_dist = None if target_px is None else round((target_px - entry_px) / tick)
    log(f"protection: stop={stop_px} ({stop_dist} ticks)  target={target_px} ({tgt_dist} ticks)")
    for k, v in checks.items():
        log(f"   {'PASS' if v else 'FAIL'}  {k}")
    step("protection", stop_price=stop_px, target_price=target_px,
         stop_ticks_observed=stop_dist, target_ticks_observed=tgt_dist,
         stop_orders=len(stop_orders), target_orders=len(target_orders),
         all_working=len(prot), checks=checks,
         stop_order=stop_orders[0] if stop_orders else None,
         target_order=target_orders[0] if target_orders else None)

    protection_ok = all(checks.values())
    if not protection_ok:
        log("PROTECTION UNVERIFIED — EMERGENCY FLATTEN NOW (position is bare)")

    # ── 6. controlled flatten (always) ────────────────────────────────────────
    return flatten_and_finish(ev, session, mission, ledger, contract, acct,
                              entry_px, protection_ok)


def flatten_and_finish(ev, session, mission, ledger, contract, acct,
                       entry_px, protection_ok) -> int:
    log("FLATTEN (controlled, immediate — not held for a target)")
    # THROUGH THE CERTIFIED CONVERGENCE AUTHORITY, NOT A LOCAL SEQUENCE.
    #
    # This tool used to call `close_position` and then, two seconds later,
    # cancel whatever `searchOpen` happened to show. That is the ordering
    # `TOPSTEP-EMERGENCY-FLATTEN-ATOMICITY-1` removed from production after a
    # surviving stop reversed a flat account 86ms after the close -- and it ran
    # here against the SAME account, on a bracket this tool had just placed.
    #
    # Being an operator tool is not an authority. `hard_flatten` neutralises the
    # bracket BEFORE the close, proves terminality, closes only measured
    # exposure and refuses to claim the account is clear on an incomplete order
    # view. The session ledger carries this tool's own token, which is what lets
    # the shared ownership contract positively attribute the children it placed
    # -- and what stops it claiming anything it did not.
    fr = hard_flatten(session, contract, ledger=ledger)
    for line in (f"orders cancelled: {fr['cancelled']}",
                 f"position closed : {fr['closed']}",
                 f"authority       : {fr.get('authority')} "
                 f"({fr.get('attribution')})",
                 f"FLAT AND CLEAR  : {fr['flat']}"):
        log(f"  {line}")
    ev["steps"].append({"step": "flatten", "accepted": bool(fr["flat"]),
                        "report": fr})
    if fr["errors"]:
        for e in fr["errors"]:
            log(f"  ERROR: {e}")
    if not fr["flat"]:
        log("FLATTEN DID NOT PROVE FLAT AND CLEAR")
        mission.transition(MS.EXIT_PENDING_RECONCILIATION, "flatten unproven")
        return finish(ev, session, 1, mission=mission, ledger=ledger)

    time.sleep(2.0)
    positions = session.open_positions()
    orders = [o for o in session.open_orders() if o.get("contract_id") == contract.id]
    log(f"final: positions={len(positions)} working_orders={len(orders)}")

    trades = session.recent_trades()
    ledger.reconcile_trades(trades)
    bot_tagged = [t for t in trades if str(t.get("customTag") or "").startswith(LG.BOT_TAG_PREFIX)]
    realized = sum(float(t.get("profitAndLoss") or 0) for t in bot_tagged)
    fees = sum(float(t.get("fees") or 0) for t in bot_tagged)
    log(f"bot trades={len(bot_tagged)} realized=${realized:.2f} fees=${fees:.2f} "
        f"net=${realized - fees:.2f}")

    clean = not positions and not orders
    mission.position_state = "flat" if clean else "unreconciled"
    mission.completion_state = "COMPLETE" if clean else "EXIT_PENDING_RECONCILIATION"
    mission.transition(MS.COMPLETE if clean else MS.EXIT_PENDING_RECONCILIATION,
                       "smoke finished")
    ledger.save()

    ev["result"] = {
        "protection_verified": protection_ok,
        "entry_price": entry_px,
        "final_positions": len(positions), "final_working_orders": len(orders),
        "bot_trades": len(bot_tagged), "realized_gross": round(realized, 2),
        "fees": round(fees, 2), "realized_net": round(realized - fees, 2),
        "attempt_count": mission.attempt_count,
        "durable_state": mission.state,
        "clean": clean,
        "trades": [{k: t.get(k) for k in
                    ("id", "side", "size", "price", "profitAndLoss", "fees",
                     "customTag", "creationTimestamp")} for t in bot_tagged],
    }
    return finish(ev, session, 0 if clean else 1, mission=mission, ledger=ledger)


def reconcile_unknown(ev, session, mission, ledger, contract) -> int:
    log("RECONCILING UNCERTAIN SUBMIT — querying venue; NOT retrying")
    positions = session.open_positions()
    # CANONICAL DISCOVERY, not `searchOpen`. This decides whether an uncertain
    # submit landed, and `searchOpen` omits Suspended bracket children by venue
    # contract -- so its silence would read as "the entry did not land" while a
    # staged child rested at the venue.
    found = DISC.discover_orders(session, contract_id=contract.id)
    orders = found["working"] or []
    ev["steps"].append({"step": "reconcile_unknown", "positions": len(positions),
                        "orders": len(orders), "discovery": found["source"]})
    if positions:
        log("position exists — flattening")
        return flatten_and_finish(ev, session, mission, ledger, contract, None,
                                  float(positions[0].get("avg_price") or 0), False)
    # BY LINEAGE, NEVER BY INSTRUMENT. Same contract alone is UNPROVEN: an
    # operator order on MNQ is indistinguishable from ours by side and size, and
    # cancelling someone else's working order is unrecoverable. The ledger holds
    # the token this run stamped on its own submission, which is the only thing
    # that can tell them apart.
    known = set(getattr(ledger, "known_token_ids", None) or ())
    left_alone = []
    for o in orders:
        if LG.classify(o, known) != LG.EXPANSION_BOT:
            left_alone.append(o.get("id"))
            continue
        try:
            session.cancel_order(o.get("id"))
        except TopstepXError:
            pass
    if left_alone:
        log(f"NOT OURS, left alone: {left_alone}")
        ev["steps"].append({"step": "unattributed_orders", "order_ids": left_alone})
    mission.transition(MS.TERMINAL_REFUSAL, "no position or order after uncertainty")
    ledger.save()
    log("no position, no order — entry did not land. Attempt remains spent.")
    return finish(ev, session, 1, mission=mission, ledger=ledger)


def finish(ev, session, code, mission=None, ledger=None) -> int:
    ev["ended_utc"] = datetime.now(timezone.utc).isoformat()
    ev["write_proof"] = session.write_proof()
    if mission is not None:
        ev["durable_state"] = mission.as_dict()
    os.makedirs(os.path.dirname(EVIDENCE), exist_ok=True)
    with open(EVIDENCE, "w", encoding="utf-8") as fh:
        fh.write(assert_clean(json.dumps(ev, indent=2, default=str), "smoke evidence"))
    log(f"evidence: {EVIDENCE}")
    session.close()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
