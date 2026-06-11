"""
Phase 5E.8 — Trade Management Layer.

Manages open positions after entry:
  Rule 1 — Break-even at +1R: move stop to entry price.
  Rule 2 — Take profit at +2R: market exit (full position).
  Rule 3 — Structure-based trailing stop after breakeven.

PAPER TRADING ONLY. Never raises — all errors return a safe result dict.

DO NOT CHANGE: AI logic, entry qualification, triggers, playbooks, execution gate,
buying-power cap, broker stop submission logic, entry orders, memory search,
recommendation engine, decision authority.
"""
import os
from datetime import datetime

import pytz

from paper_execution.paper_broker    import is_paper_account_safe, submit_paper_exit_order, cancel_order
from paper_execution.protective_stop import submit_protective_stop
from paper_execution.management_policies import get_policy, resolve_trade_profile
from paper_execution.trade_journal   import (
    find_any_active_trade,
    mark_exit_submitted,
    update_trade_management,
)

_EASTERN = pytz.timezone("America/New_York")


# ── Config ────────────────────────────────────────────────────────────────────

def _tm_enabled() -> bool:
    return os.getenv("TRADE_MANAGEMENT_ENABLED", "true").lower().strip() == "true"

def _be_enabled() -> bool:
    return os.getenv("BREAKEVEN_ENABLED", "true").lower().strip() == "true"

def _be_trigger_r() -> float:
    try:
        return float(os.getenv("BREAKEVEN_TRIGGER_R", "1.0"))
    except (TypeError, ValueError):
        return 1.0

def _tp_enabled() -> bool:
    return os.getenv("TAKE_PROFIT_ENABLED", "true").lower().strip() == "true"

def _tp_r() -> float:
    try:
        return float(os.getenv("TAKE_PROFIT_R", "2.0"))
    except (TypeError, ValueError):
        return 2.0

def _trail_enabled() -> bool:
    return os.getenv("STRUCTURE_TRAIL_ENABLED", "true").lower().strip() == "true"

def _trail_after_be() -> bool:
    return os.getenv("STRUCTURE_TRAIL_AFTER_BREAKEVEN", "true").lower().strip() == "true"


# ── R calculation ─────────────────────────────────────────────────────────────

def _calc_unrealized_r(
    current_price,
    entry_price,
    risk_per_share,
    side: str,
) -> "float | None":
    try:
        r = float(risk_per_share)
        if r <= 0:
            return None
        cp = float(current_price)
        ep = float(entry_price)
        return (cp - ep) / r if side == "long" else (ep - cp) / r
    except (TypeError, ValueError):
        return None


# ── Structure trail reference ─────────────────────────────────────────────────

def _get_structure_trail_stop(
    snapshot: dict,
    side: str,
    current_stop: float,
    entry_price: float,
) -> "tuple[float | None, str]":
    """
    Returns (new_stop_price, reason) from the preferred tool candidate's structure zone.
    Returns (None, reason) when no valid improvement is found.

    For long: uses zone_low of the bullish candidate.
    For short: uses zone_high of the bearish candidate.
    Only accepted when the level improves the stop AND stays at or beyond entry.
    """
    try:
        toolbox    = snapshot.get("toolbox", {})
        candidates = toolbox.get("tool_candidates", [])
        if not candidates:
            return None, "no_tool_candidates"

        target_dir = "bullish" if side == "long" else "bearish"
        preferred  = None
        for c in candidates:
            pl = c.get("price_level", {})
            if pl.get("direction", "").lower() == target_dir:
                preferred = pl
                break

        if preferred is None:
            return None, "no_matching_direction_candidate"

        raw_level = preferred.get("zone_low") if side == "long" else preferred.get("zone_high")
        if raw_level is None:
            return None, "no_structure_level_in_candidate"

        sl = float(raw_level)

        if side == "long":
            if sl <= current_stop:
                return None, "no_improvement_long"
            if sl < entry_price:
                return None, "structure_below_entry_long"
        else:
            if sl >= current_stop:
                return None, "no_improvement_short"
            if sl > entry_price:
                return None, "structure_above_entry_short"

        return round(sl, 4), "structure_trail_improved"

    except Exception as exc:  # noqa: BLE001
        return None, f"structure_trail_error:{exc}"


# ── Broker stop replacement ───────────────────────────────────────────────────

def replace_broker_stop(
    trade_id: str,
    symbol: str,
    position_side: str,
    qty: int,
    new_stop_price: float,
) -> dict:
    """
    Submit new broker stop first, then cancel old one.
    Briefly holding two stops is acceptable and safer than a gap in protection.
    Never raises.
    """
    try:
        # Read old stop_order_id BEFORE submitting new one (submit overwrites journal)
        old_trade, _  = find_any_active_trade(symbol)
        old_stop_id   = old_trade.get("broker_stop_order_id") if old_trade else None

        # Submit new stop (includes Phase 5E.7 price validation)
        new_result = submit_protective_stop(trade_id, symbol, position_side, qty, new_stop_price)

        if not new_result.get("enabled", True):
            return {
                "replaced":          False,
                "reason":            "broker_stop_disabled",
                "new_stop_order_id": None,
                "old_stop_canceled": False,
            }

        if not new_result.get("stop_submitted"):
            return {
                "replaced":          False,
                "reason":            f"new_stop_not_submitted:{new_result.get('reason', 'unknown')}",
                "new_stop_order_id": None,
                "old_stop_canceled": False,
            }

        new_order_id  = new_result.get("stop_order_id")

        # Cancel old stop only when it differs from the newly submitted one
        old_canceled = False
        if old_stop_id and old_stop_id != new_order_id:
            cancel_result = cancel_order(old_stop_id)
            old_canceled  = bool(cancel_result.get("canceled", False))

        return {
            "replaced":          True,
            "new_stop_order_id": new_order_id,
            "old_stop_order_id": old_stop_id,
            "old_stop_canceled": old_canceled,
            "new_stop_price":    new_stop_price,
            "reason":            "broker_stop_replaced",
        }

    except Exception as exc:  # noqa: BLE001
        return {
            "replaced":          False,
            "reason":            f"replace_broker_stop_error:{exc}",
            "new_stop_order_id": None,
            "old_stop_canceled": False,
        }


# ── Action executors ──────────────────────────────────────────────────────────

def _execute_take_profit(
    trade_record: dict,
    symbol: str,
    side: str,
    qty: int,
    unrealized_r: float,
    current_price: float,
    fraction: float = 1.0,
) -> dict:
    trade_id  = trade_record.get("trade_id")
    exit_side = "sell" if side == "long" else "buy"

    safe, reason = is_paper_account_safe()
    if not safe:
        return _error(f"paper safety check failed: {reason}")

    # ── Phase 5T.3: partial take-profit (TREND profile) ───────────────────────
    partial  = 0.0 < fraction < 1.0
    exit_qty = qty
    if partial:
        exit_qty = max(1, int(qty * fraction))
        if exit_qty >= qty:
            partial  = False      # position too small to split — full exit
            exit_qty = qty

    try:
        result = submit_paper_exit_order(symbol, exit_qty, exit_side)
    except RuntimeError as exc:
        return _error(f"take_profit exit order failed: {exc}")

    order_id = result.get("alpaca_order_id")
    now_str  = datetime.now(_EASTERN).strftime("%Y%m%dT%H%M%S")

    if partial:
        remaining = qty - exit_qty

        # Journal: partial fields only — exit NOT marked submitted, so the
        # remainder keeps being managed (trail, uncapped).
        update_trade_management(trade_id, {
            "partial_exit_taken":    True,
            "partial_exit_order_id": order_id,
            "partial_exit_qty":      exit_qty,
            "remaining_qty":         remaining,
            "partial_exit_r":        round(unrealized_r, 4),
            "partial_exit_at":       now_str,
            "stop_management_state": "partial_taken",
        }, symbol)

        # Broker stop must be re-sized for the remainder, or the old full-qty
        # stop would over-sell when triggered.
        broker_replaced = False
        stop_ref = (trade_record.get("current_stop_reference")
                    or trade_record.get("stop_reference"))
        if trade_record.get("broker_stop_order_id") and stop_ref is not None:
            rep = replace_broker_stop(trade_id, symbol, side, remaining, float(stop_ref))
            broker_replaced = bool(rep.get("replaced", False))

        return {
            "action":               "partial_take_profit",
            "unrealized_r":         round(unrealized_r, 4),
            "exit_order_id":        order_id,
            "exit_qty":             exit_qty,
            "remaining_qty":        remaining,
            "broker_stop_replaced": broker_replaced,
            "reason":               f"partial take_profit at {unrealized_r:.2f}R",
            "details": (
                f"exit {exit_qty}/{qty} | remaining={remaining}"
                f" | r={unrealized_r:.2f} | stop_resized={broker_replaced}"
            ),
            "current_price":        current_price,
            "status":               "submitted",
        }

    # ── Full exit (pre-5T behavior) ───────────────────────────────────────────
    mark_exit_submitted(
        trade_id            = trade_id,
        exit_order_id       = order_id,
        exit_price_reference= current_price,
        reason              = "take_profit_2R",
        symbol              = symbol,
    )

    update_trade_management(trade_id, {
        "take_profit_triggered":    True,
        "take_profit_triggered_at": now_str,
        "take_profit_r":            round(unrealized_r, 4),
        "stop_management_state":    "take_profit_exit",
    }, symbol)

    return {
        "action":        "take_profit",
        "unrealized_r":  round(unrealized_r, 4),
        "exit_order_id": order_id,
        "reason":        f"take_profit at {unrealized_r:.2f}R",
        "details":       f"exit_order={order_id} r={unrealized_r:.2f}",
        "current_price": current_price,
        "status":        "submitted",
    }


def _execute_breakeven(
    trade_record: dict,
    symbol: str,
    side: str,
    qty: int,
    entry_price: float,
) -> dict:
    trade_id = trade_record.get("trade_id")
    now_str  = datetime.now(_EASTERN).strftime("%Y%m%dT%H%M%S")

    update_trade_management(trade_id, {
        "stop_reference":          entry_price,
        "current_stop_reference":  entry_price,
        "breakeven_triggered":     True,
        "breakeven_triggered_at":  now_str,
        "stop_moved_to_breakeven": True,
        "stop_management_state":   "breakeven",
    }, symbol)

    broker_stop_id = trade_record.get("broker_stop_order_id")
    replace_result = None
    if broker_stop_id:
        replace_result = replace_broker_stop(trade_id, symbol, side, qty, entry_price)

    broker_replaced = replace_result.get("replaced", False) if replace_result else False

    return {
        "action":               "breakeven",
        "new_stop":             entry_price,
        "broker_stop_replaced": broker_replaced,
        "reason":               "stop moved to entry at +1R",
        "details":              f"stop={entry_price} broker_replaced={broker_replaced}",
        "status":               "executed",
    }


def _execute_trail(
    trade_record: dict,
    symbol: str,
    side: str,
    qty: int,
    trail_stop: float,
    trail_reason: str,
) -> dict:
    trade_id = trade_record.get("trade_id")
    now_str  = datetime.now(_EASTERN).strftime("%Y%m%dT%H%M%S")

    update_trade_management(trade_id, {
        "stop_reference":         trail_stop,
        "current_stop_reference": trail_stop,
        "trail_stop_active":      True,
        "trail_stop_updated_at":  now_str,
        "trail_reason":           trail_reason,
        "stop_management_state":  "trail_stop",
    }, symbol)

    broker_stop_id = trade_record.get("broker_stop_order_id")
    replace_result = None
    if broker_stop_id:
        replace_result = replace_broker_stop(trade_id, symbol, side, qty, trail_stop)

    broker_replaced = replace_result.get("replaced", False) if replace_result else False

    return {
        "action":               "trail_stop",
        "new_stop":             trail_stop,
        "trail_reason":         trail_reason,
        "broker_stop_replaced": broker_replaced,
        "reason":               f"structure trail: {trail_reason}",
        "details":              f"stop={trail_stop} reason={trail_reason}",
        "status":               "executed",
    }


# ── Result helpers ────────────────────────────────────────────────────────────

def _disabled() -> dict:
    return {
        "action":  "none",
        "status":  "disabled",
        "reason":  "TRADE_MANAGEMENT_ENABLED=false",
        "details": "",
    }

def _no_trade(reason: str = "") -> dict:
    return {"action": "no_trade", "status": "no_trade", "reason": reason, "details": ""}

def _no_action(reason: str = "") -> dict:
    return {"action": "none", "status": "no_action", "reason": reason, "details": ""}

def _hold(unrealized_r: float, be_triggered: bool) -> dict:
    return {
        "action":            "hold",
        "status":            "hold",
        "unrealized_r":      round(unrealized_r, 4),
        "reason":            f"hold at {unrealized_r:.2f}R",
        "details":           f"r={unrealized_r:.2f} be_triggered={be_triggered}",
        "breakeven_triggered": be_triggered,
    }

def _error(reason: str) -> dict:
    return {"action": "none", "status": "error", "reason": reason, "details": ""}


# ── Core logic ────────────────────────────────────────────────────────────────

def _manage(snapshot: dict, symbol: str) -> dict:
    pm = snapshot.get("position_monitor", {})

    if not pm.get("has_open_position"):
        return _no_trade("no_open_position")

    if pm.get("exit_already_submitted"):
        return _no_action("exit_already_submitted")

    trade_id        = pm.get("linked_trade_id")
    current_price   = pm.get("current_price")
    side            = pm.get("side")
    qty             = pm.get("qty")
    avg_entry_price = pm.get("avg_entry_price")

    if not trade_id:
        return _no_action("no_linked_trade_id")
    if current_price is None:
        return _no_action("no_current_price")
    if avg_entry_price is None:
        return _no_action("no_entry_price")

    trade_record, _ = find_any_active_trade(symbol)
    if trade_record is None:
        return _no_action("journal_trade_not_found")

    order_status = trade_record.get("order_status", "")
    if order_status not in ("filled", "partially_filled"):
        return _no_action(f"not_filled:{order_status}")

    raw_risk = trade_record.get("risk_per_share")
    if raw_risk is None:
        return _no_action("risk_per_share_missing")

    risk_per_share = float(raw_risk)
    if risk_per_share <= 0:
        return _no_action("risk_per_share_zero")

    entry_price  = float(avg_entry_price)
    unrealized_r = _calc_unrealized_r(current_price, entry_price, risk_per_share, side)
    if unrealized_r is None:
        return _no_action("unrealized_r_calc_failed")

    be_triggered = bool(trade_record.get("breakeven_triggered", False))
    tp_triggered = bool(trade_record.get("take_profit_triggered", False))

    if tp_triggered:
        return _no_action("take_profit_already_triggered")

    # ── Phase 5T.1: profile-driven policy (None values = env defaults) ───────
    profile = resolve_trade_profile(snapshot, trade_record, symbol)
    policy  = get_policy(profile)

    tp_r_eff       = policy["take_profit_r"]         if policy["take_profit_r"]         is not None else _tp_r()
    be_trigger_eff = policy["breakeven_trigger_r"]   if policy["breakeven_trigger_r"]   is not None else _be_trigger_r()
    trail_gate_eff = policy["trail_after_breakeven"] if policy["trail_after_breakeven"] is not None else _trail_after_be()
    fraction_eff   = policy["take_profit_fraction"]  if policy["take_profit_fraction"]  is not None else 1.0
    partial_taken  = bool(trade_record.get("partial_exit_taken", False))

    result = None

    # ── Rule 2: Take profit (highest priority) ────────────────────────────────
    # After a partial, the TP rule retires — the remainder trails uncapped.
    if (_tp_enabled() and unrealized_r >= tp_r_eff
            and not (fraction_eff < 1.0 and partial_taken)):
        result = _execute_take_profit(
            trade_record, symbol, side, qty, unrealized_r, current_price,
            fraction_eff,
        )

    # ── Rule 1: Break-even ────────────────────────────────────────────────────
    elif _be_enabled() and not be_triggered and unrealized_r >= be_trigger_eff:
        result = _execute_breakeven(trade_record, symbol, side, qty, entry_price)

    # ── Rule 3: Structure trail ───────────────────────────────────────────────
    else:
        trail_allowed = (not trail_gate_eff) or be_triggered or partial_taken
        if _trail_enabled() and trail_allowed:
            current_stop = trade_record.get("stop_reference")
            if current_stop is not None:
                trail_stop, trail_reason = _get_structure_trail_stop(
                    snapshot, side, float(current_stop), entry_price,
                )
                if trail_stop is not None:
                    result = _execute_trail(
                        trade_record, symbol, side, qty, trail_stop, trail_reason,
                    )

    if result is None:
        result = _hold(unrealized_r, be_triggered)

    result.setdefault("unrealized_r", round(unrealized_r, 4))
    result["management_profile"] = profile
    return result


# ── Public entry point ────────────────────────────────────────────────────────

def manage_open_trade(snapshot: dict, symbol: str) -> dict:
    """
    Phase 5E.8 — Manage an open trade after entry.
    Evaluates breakeven, take profit, and structure trail on each scan cycle.
    Never raises.
    """
    if not _tm_enabled():
        return _disabled()
    try:
        return _manage(snapshot, symbol)
    except Exception as exc:  # noqa: BLE001
        return _error(f"manage_open_trade unexpected error: {exc}")
