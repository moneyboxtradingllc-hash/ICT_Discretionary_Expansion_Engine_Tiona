"""
Phase 2B — Paper Position Monitor.

Reads the open position from the Alpaca paper account, matches it to the
most recent journal trade, syncs order status, and returns a monitoring
summary including stop_reference and unrealized P&L.

Does NOT submit orders. Does NOT enforce stops.
Paper account only. Never touches live endpoint.
"""
import os

from paper_execution.paper_broker  import is_paper_account_safe, get_position, get_order
from paper_execution.trade_journal import find_active_trade, find_any_active_trade, update_trade_status
from paper_execution.protective_stop import submit_protective_stop, verify_protective_stop_exists


# ── Fallback price from snapshot ──────────────────────────────────────────────

def _price_from_snapshot(snapshot: dict) -> float | None:
    tfs = snapshot.get("timeframes", {})
    for tf in ["1m", "3m", "5m", "15m"]:
        lc = tfs.get(tf, {}).get("last_candle")
        if lc and lc.get("close") is not None:
            return round(float(lc["close"]), 2)
    return None


# ── Result constructors ───────────────────────────────────────────────────────

_BROKER_STOP_DISABLED = {
    "enabled": False, "status": "disabled", "stop_order_id": None, "stop_price": None,
}


def _base() -> dict:
    return {
        "enabled":               False,
        "has_open_position":     False,
        "symbol":                None,
        "qty":                   0,
        "side":                  None,
        "avg_entry_price":       None,
        "current_price":         None,
        "linked_trade_id":       None,
        "stop_reference":        None,
        "stop_distance":         None,
        "unrealized_pnl":        None,
        "exit_already_submitted": False,
        "reconciliation_needed": False,   # Phase 4A
        "broker_stop":           _BROKER_STOP_DISABLED,  # Phase 4B
        "status":                "disabled",
        "warnings":              [],
    }


def _no_pos(warnings: list | None = None) -> dict:
    r = _base()
    r.update({"enabled": True, "status": "no_position", "warnings": warnings or []})
    return r


def _handle_broker_stop(
    linked_trade: dict,
    symbol: str,
    position_side: str,
    qty: int,
    stop_reference,
) -> dict:
    """
    Phase 4B — check / submit broker-side protective stop.
    Called only when BROKER_STOP_ENABLED=true, position is open, and entry is filled.
    """
    if stop_reference is None:
        return {
            "enabled": True, "status": "missing",
            "stop_order_id": None, "stop_price": None,
        }

    trade_id             = linked_trade.get("trade_id", "")
    broker_stop_order_id = linked_trade.get("broker_stop_order_id")

    if broker_stop_order_id:
        # Already have a stop order — verify it still exists at the broker
        result = verify_protective_stop_exists(
            trade_id, symbol, position_side, float(stop_reference)
        )
        return {
            "enabled":       result.get("enabled", True),
            "status":        result.get("status", "missing"),
            "stop_order_id": result.get("stop_order_id"),
            "stop_price":    result.get("stop_price"),
        }

    # No stop yet — submit one
    result = submit_protective_stop(
        trade_id, symbol, position_side, qty, float(stop_reference)
    )
    if not result.get("enabled", True):
        return _BROKER_STOP_DISABLED
    return {
        "enabled":       True,
        "status":        "submitted" if result.get("stop_submitted") else "missing",
        "stop_order_id": result.get("stop_order_id"),
        "stop_price":    result.get("stop_price"),
    }


# ── Public entry point ────────────────────────────────────────────────────────

def monitor_paper_position(snapshot: dict, symbol: str) -> dict:
    """
    Phase 2B — Paper Position Monitor entry point.
    Never raises — errors return a safe warning result.
    """
    try:
        return _monitor(snapshot, symbol)
    except Exception as exc:
        r = _no_pos([f"monitor error: {exc}"])
        r["status"] = "error"
        return r


def _monitor(snapshot: dict, symbol: str) -> dict:

    # ── Check enabled ──────────────────────────────────────────────────────────
    if os.getenv("PAPER_STOP_MONITOR_ENABLED", "true").lower().strip() != "true":
        return _base()   # disabled

    # ── Paper endpoint safety ──────────────────────────────────────────────────
    ep_safe, ep_reason = is_paper_account_safe()
    if not ep_safe:
        return _no_pos([f"paper safety failed: {ep_reason}"])

    # ── Fetch open position ────────────────────────────────────────────────────
    warnings = []
    position = get_position(symbol)

    if position is None:
        # Phase 4A: detect if a trade was open when position vanished
        active_trade, _ = find_any_active_trade(symbol)
        if active_trade:
            r = _no_pos(["position gone from broker while journal trade is active"])
            r["reconciliation_needed"] = True
        else:
            r = _no_pos()
            r["reconciliation_needed"] = False
        return r

    if "error" in position:
        return _no_pos([f"position fetch error: {position['error']}"])

    # ── Parse position fields ──────────────────────────────────────────────────
    qty             = int(float(position["qty"]))
    side            = position["side"]               # "long" or "short"
    avg_entry_price = float(position["avg_entry_price"])

    raw_current = position.get("current_price")
    current_price = (
        float(raw_current)
        if raw_current is not None
        else _price_from_snapshot(snapshot)
    )
    if current_price is None:
        current_price = avg_entry_price   # last resort: assume at entry
        warnings.append("current_price unavailable — using avg_entry as fallback")

    raw_pnl       = position.get("unrealized_pl")
    unrealized_pnl = float(raw_pnl) if raw_pnl is not None else (
        (current_price - avg_entry_price) * qty if side == "long"
        else (avg_entry_price - current_price) * qty
    )

    # ── Find linked journal trade ──────────────────────────────────────────────
    journal_side = "buy" if side == "long" else "sell"
    linked_trade, linked_fp = find_active_trade(symbol, journal_side)

    stop_reference  = None
    linked_trade_id = None
    exit_already    = False

    if linked_trade:
        linked_trade_id = linked_trade.get("trade_id")
        stop_reference  = linked_trade.get("stop_reference")
        exit_already    = bool(linked_trade.get("exit_submitted", False))

        # ── Sync order status from Alpaca ──────────────────────────────────────
        alpaca_id  = linked_trade.get("alpaca_order_id")
        cur_status = linked_trade.get("order_status", "")
        if alpaca_id and cur_status in ("submitted", "accepted"):
            order_info = get_order(alpaca_id)
            if order_info and "error" not in order_info:
                new_status = order_info.get("status", "")
                if new_status and new_status != cur_status:
                    extra = {}
                    if new_status in ("filled", "partially_filled"):
                        extra["avg_fill_price"] = order_info.get("filled_avg_price")
                        extra["filled_qty"]      = order_info.get("filled_qty")
                    update_trade_status(linked_trade_id, new_status, extra, symbol)
            elif order_info and "error" in order_info:
                warnings.append(f"order sync error: {order_info['error']}")
    else:
        warnings.append("no linked journal trade — position may be from a prior session")

    # ── Phase 4B: Broker-side protective stop ──────────────────────────────────
    broker_stop_enabled = os.getenv("BROKER_STOP_ENABLED", "false").lower().strip() == "true"
    if (
        broker_stop_enabled
        and linked_trade
        and linked_trade.get("order_status") in ("filled", "partially_filled")
        and not exit_already
    ):
        broker_stop = _handle_broker_stop(linked_trade, symbol, side, qty, stop_reference)
    else:
        broker_stop = dict(_BROKER_STOP_DISABLED)
        if broker_stop_enabled and not linked_trade:
            broker_stop["enabled"] = True
            broker_stop["status"]  = "missing"

    # ── Calculate stop distance ────────────────────────────────────────────────
    if stop_reference is not None:
        sr = float(stop_reference)
        stop_distance = round(
            current_price - sr if side == "long" else sr - current_price,
            4,
        )
    else:
        stop_distance = None

    return {
        "enabled":               True,
        "has_open_position":     True,
        "symbol":                symbol,
        "qty":                   qty,
        "side":                  side,
        "avg_entry_price":       round(avg_entry_price, 4),
        "current_price":         round(current_price, 4),
        "linked_trade_id":       linked_trade_id,
        "stop_reference":        stop_reference,
        "stop_distance":         stop_distance,
        "unrealized_pnl":        round(unrealized_pnl, 4),
        "exit_already_submitted": exit_already,
        "broker_stop":           broker_stop,   # Phase 4B
        "status":                "monitoring",
        "warnings":              warnings[:5],
    }
