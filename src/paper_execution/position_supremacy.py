"""
Broker Position Supremacy — the exposure-is-truth layer.

Born from the 2026-06-11 incident: Alpaca labeled an order "new", the journal
recorded it, a fill landed four seconds later, and the bot held 571 shares to
a +6.77R peak and back to a loss with no stop and no management — because
bookkeeping said the trade wasn't filled.

NON-NEGOTIABLE STANDARD:
  The broker position is reality. The journal is bookkeeping.
  When they disagree: BROKER WINS. Immediately.
  Protect first. Repair bookkeeping second. Diagnose third.

Runs EVERY SCAN, before the position monitor and before any new-entry
evaluation. Never raises.

Cases:
  1/2  broker position + journal trade in any non-filled status
         -> POSITION_STATE_MISMATCH: force-sync journal to filled from broker
            facts, ensure protective stop, block new entries this scan
  3    broker position + NO journal trade
         -> adopt: create emergency journal record, ensure stop, block
            entries, write incident record. Do not wait for a human.
  4    broker flat + journal says filled/open
         -> hand to trade_reconciliation (externally-closed path)
  5    broker flat + journal pending (new/submitted/...)
         -> pending only if a matching broker order exists; otherwise mark
            the journal trade with the order's terminal status (or expired)
"""
import json
import os
from datetime import datetime

import pytz

from paper_execution.paper_broker import (
    get_position,
    get_order,
    get_open_orders,
    cancel_order,
)
from paper_execution.protective_stop import submit_protective_stop
from paper_execution.trade_journal import (
    find_any_active_trade,
    update_trade_status,
    make_record,
    append_trade,
)

_EASTERN = pytz.timezone("America/New_York")

_FILLED   = ("filled", "partially_filled")
_PENDING  = ("new", "pending_new", "submitted", "accepted")

_EMERGENCY_STOP_PCT = 0.01   # 1% emergency stop when no reference exists


def _now() -> str:
    return datetime.now(_EASTERN).strftime("%Y%m%dT%H%M%S")


def _log_incident(symbol: str, incident: dict) -> None:
    """Append an incident record to data/ops. Never raises."""
    try:
        ops_dir = os.getenv("OPS_DIR", os.path.join("data", "ops"))
        os.makedirs(ops_dir, exist_ok=True)
        path = os.path.join(
            ops_dir, f"incidents_{datetime.now(_EASTERN).strftime('%Y%m%d')}.json")
        try:
            with open(path, encoding="utf-8") as f:
                incidents = json.load(f).get("incidents", [])
        except (OSError, json.JSONDecodeError):
            incidents = []
        incidents.append({**incident, "symbol": symbol, "at": _now()})
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"incidents": incidents}, f, indent=1)
    except OSError:
        pass


# ── Protective stop assurance ─────────────────────────────────────────────────

def _stop_price_for(trade: "dict | None", pos: dict, pos_side: str) -> float:
    """Stop reference from the journal; emergency 1% stop when none exists."""
    if trade:
        for key in ("current_stop_reference", "stop_reference"):
            ref = trade.get(key)
            if ref is not None:
                try:
                    return float(ref)
                except (TypeError, ValueError):
                    pass
    price = float(pos.get("current_price") or pos.get("avg_entry_price") or 0)
    if pos_side == "long":
        return round(price * (1 - _EMERGENCY_STOP_PCT), 2)
    return round(price * (1 + _EMERGENCY_STOP_PCT), 2)


def ensure_protective_stop(symbol: str, pos: dict, trade: "dict | None") -> dict:
    """
    Make the broker stop match broker reality:
      missing            -> submit
      wrong qty or side  -> cancel + resubmit correct
    Returns {"protected": bool, "action": str, "detail": str}.
    Never raises.
    """
    try:
        pos_side  = (pos.get("side") or "long").lower().replace("positionside.", "")
        pos_qty   = abs(int(float(pos.get("qty", 0))))
        stop_side = "sell" if pos_side == "long" else "buy"
        trade_id  = (trade or {}).get("trade_id") or f"EMERG_{symbol}_{_now()}"
        stop_price = _stop_price_for(trade, pos, pos_side)

        # Find ANY open stop for this symbol (side-agnostic scan for audit)
        existing = None
        for o in get_open_orders(symbol):
            o_type = (o.get("order_type") or o.get("type") or "").lower()
            if "stop" in o_type:
                existing = o
                break

        if existing is not None:
            ex_side = (existing.get("side") or "").lower().split(".")[-1]
            ex_qty  = abs(int(float(existing.get("qty", 0))))
            if ex_side == stop_side and ex_qty == pos_qty:
                return {"protected": True, "action": "verified",
                        "detail": f"stop ok ({ex_side} {ex_qty})"}
            # Wrong qty or wrong side — submit correct stop FIRST, then cancel
            # the bad one (never leave the position naked mid-correction).
            result = submit_protective_stop(trade_id, symbol, pos_side,
                                            pos_qty, stop_price)
            if not result.get("stop_submitted"):
                # Could not place the corrected stop — keep the (wrong) one
                # rather than cancel into nakedness.
                return {"protected": False, "action": "emergency_management",
                        "detail": f"stop correction failed: {result.get('reason')}"}
            cancel_order(existing.get("order_id") or existing.get("id"))
            return {"protected": True, "action": "corrected",
                    "detail": (f"stop corrected: was {ex_side} {ex_qty}, "
                               f"now {stop_side} {pos_qty} @ {stop_price}")}

        # No stop at all — submit one
        result = submit_protective_stop(trade_id, symbol, pos_side,
                                        pos_qty, stop_price)
        if result.get("stop_submitted"):
            return {"protected": True, "action": "submitted",
                    "detail": f"stop submitted {stop_side} {pos_qty} @ {stop_price}"}
        if not result.get("enabled", True):
            return {"protected": False, "action": "disabled",
                    "detail": "BROKER_STOP_ENABLED=false (software stop only)"}
        return {"protected": False, "action": "emergency_management",
                "detail": f"stop submission FAILED: {result.get('reason')}"}
    except Exception as exc:  # noqa: BLE001
        return {"protected": False, "action": "emergency_management",
                "detail": f"stop assurance error: {exc}"}


# ── Emergency adoption (Case 3) ───────────────────────────────────────────────

def _adopt_orphan_position(symbol: str, pos: dict) -> dict:
    """Broker position with no journal trade: adopt it. Exposure is truth."""
    pos_side = (pos.get("side") or "long").lower().replace("positionside.", "")
    qty      = abs(int(float(pos.get("qty", 0))))
    entry    = float(pos.get("avg_entry_price") or 0)
    stop     = _stop_price_for(None, pos, pos_side)
    rps      = abs(entry - stop)

    trade_id = f"EMERG_{symbol}_{_now()}"
    record = make_record(
        trade_id        = trade_id,
        symbol          = symbol,
        intent_id       = None,
        intent_type     = "long" if pos_side == "long" else "short",
        side            = "buy" if pos_side == "long" else "sell",
        qty             = qty,
        entry_reference = entry,
        stop_reference  = stop,
        risk_per_share  = round(rps, 4) if rps > 0 else 0.01,
        risk_dollars    = round(rps * qty, 2),
        order_status    = "filled",
        alpaca_order_id = None,
        reason          = "EMERGENCY: orphan broker position adopted by supremacy layer",
    )
    record["avg_fill_price"] = entry
    record["filled_qty"]     = qty
    append_trade(record, symbol)
    return record


# ── Public entry point ────────────────────────────────────────────────────────

def enforce_position_supremacy(symbol: str) -> dict:
    """
    Exposure-is-truth enforcement. Runs every scan, before position monitor
    and before entry evaluation. Never raises.
    """
    try:
        return _enforce(symbol)
    except Exception as exc:  # noqa: BLE001
        # Even the supremacy layer failing must not kill the scan — but it
        # must block entries: we cannot prove we are flat.
        return {
            "status": "error", "mismatch": True, "case": "error",
            "block_entries": True, "forced_sync": False,
            "actions": [f"supremacy error: {exc}"],
        }


def _enforce(symbol: str) -> dict:
    pos      = get_position(symbol)
    trade, _ = find_any_active_trade(symbol)
    actions: list = []

    # ── Broker has a position ────────────────────────────────────────────────
    if pos is not None:
        pos_side = (pos.get("side") or "long").lower().replace("positionside.", "")
        pos_qty  = abs(int(float(pos.get("qty", 0))))

        if trade is not None and trade.get("order_status") in _FILLED:
            # Agreement — verify the stop quietly (Case 0)
            stop = ensure_protective_stop(symbol, pos, trade)
            if stop["action"] not in ("verified", "disabled"):
                actions.append(f"stop_{stop['action']}: {stop['detail']}")
            return {
                "status": "agree", "mismatch": False, "case": "agree",
                "block_entries": False, "forced_sync": False,
                "protected": stop["protected"], "actions": actions,
            }

        if trade is not None:
            # Cases 1/2 — POSITION_STATE_MISMATCH: broker wins, immediately.
            old_status = trade.get("order_status")
            update_trade_status(
                trade.get("trade_id"), "filled",
                {
                    "avg_fill_price": float(pos.get("avg_entry_price") or 0),
                    "filled_qty":     pos_qty,
                    "entry_price":    float(pos.get("avg_entry_price") or 0),
                },
                symbol,
            )
            actions.append(
                f"forced journal sync: {old_status} -> filled "
                f"(broker: {pos_side} x{pos_qty} @ {pos.get('avg_entry_price')})"
            )
            trade = {**trade, "order_status": "filled"}
            stop = ensure_protective_stop(symbol, pos, trade)
            actions.append(f"stop_{stop['action']}: {stop['detail']}")
            _log_incident(symbol, {
                "type": "POSITION_STATE_MISMATCH",
                "old_status": old_status,
                "broker": f"{pos_side} x{pos_qty}",
                "actions": actions,
            })
            return {
                "status": "POSITION_STATE_MISMATCH", "mismatch": True,
                "case": "journal_not_filled", "old_status": old_status,
                "block_entries": True, "forced_sync": True,
                "protected": stop["protected"],
                "emergency": stop["action"] == "emergency_management",
                "actions": actions,
            }

        # Case 3 — orphan position: adopt, protect, block, record.
        record = _adopt_orphan_position(symbol, pos)
        actions.append(f"orphan position adopted as {record['trade_id']}")
        stop = ensure_protective_stop(symbol, pos, record)
        actions.append(f"stop_{stop['action']}: {stop['detail']}")
        _log_incident(symbol, {
            "type": "ORPHAN_POSITION_ADOPTED",
            "trade_id": record["trade_id"],
            "broker": f"{pos_side} x{pos_qty}",
            "actions": actions,
        })
        return {
            "status": "POSITION_STATE_MISMATCH", "mismatch": True,
            "case": "orphan_position", "block_entries": True,
            "forced_sync": True, "protected": stop["protected"],
            "emergency": stop["action"] == "emergency_management",
            "trade_id": record["trade_id"], "actions": actions,
        }

    # ── Broker is flat ───────────────────────────────────────────────────────
    if trade is None:
        return {"status": "flat", "mismatch": False, "case": "flat",
                "block_entries": False, "forced_sync": False, "actions": []}

    status = trade.get("order_status")

    if status in _FILLED and not trade.get("exit_submitted"):
        # Case 4 — journal thinks we're in a trade; broker says flat.
        # The reconciliation engine owns externally-closed bookkeeping.
        from paper_execution.trade_reconciliation import reconcile_trade
        recon = reconcile_trade(symbol)
        actions.append(f"externally_closed reconciliation: {recon.get('status')}")
        return {
            "status": "broker_flat_journal_open", "mismatch": True,
            "case": "externally_closed", "block_entries": True,
            "forced_sync": True, "actions": actions,
        }

    if status in _PENDING:
        # Case 5 — pending is only real if the broker holds a matching order.
        alpaca_id = trade.get("alpaca_order_id")
        open_ids  = {o.get("order_id") or o.get("id") for o in get_open_orders(symbol)}
        if alpaca_id and alpaca_id in open_ids:
            return {"status": "pending_verified", "mismatch": False,
                    "case": "pending", "block_entries": False,
                    "forced_sync": False, "actions": []}
        # No matching broker order: resolve to the order's terminal status.
        terminal = "expired"
        if alpaca_id:
            info = get_order(alpaca_id)
            if info and "error" not in info:
                terminal = info.get("status") or "expired"
                if terminal in _FILLED:
                    # Filled then position closed before we looked — Case 4 path.
                    from paper_execution.trade_reconciliation import reconcile_trade
                    update_trade_status(trade.get("trade_id"), "filled", {
                        "avg_fill_price": info.get("filled_avg_price"),
                        "filled_qty": info.get("filled_qty"),
                    }, symbol)
                    recon = reconcile_trade(symbol)
                    actions.append(f"late fill detected; reconciled: {recon.get('status')}")
                    return {"status": "late_fill_reconciled", "mismatch": True,
                            "case": "late_fill", "block_entries": True,
                            "forced_sync": True, "actions": actions}
        update_trade_status(trade.get("trade_id"), terminal, {}, symbol)
        actions.append(f"stale pending trade marked {terminal} (no broker order)")
        return {"status": "stale_pending_resolved", "mismatch": True,
                "case": "stale_pending", "block_entries": False,
                "forced_sync": True, "actions": actions}

    return {"status": "agree", "mismatch": False, "case": "agree",
            "block_entries": False, "forced_sync": False, "actions": []}
