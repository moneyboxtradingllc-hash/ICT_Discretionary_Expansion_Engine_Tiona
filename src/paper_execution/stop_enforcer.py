"""
Phase 2B — Paper Stop Enforcer.

Receives the position_monitor result and evaluates whether the stop level
has been breached.  When PAPER_EXIT_ON_STOP=true AND breach is detected AND
no exit is already in flight, submits a market exit order via paper_broker.

Safety constraints:
  - Never submits if PAPER_EXIT_ON_STOP != "true"
  - Never double-submits (exit_already_submitted check from monitor)
  - Never submits if monitor says disabled / no_position / error
  - All broker calls wrapped in try/except — never crashes the scan loop
  - Paper endpoint validated before every submission
"""
import os
from datetime import datetime

import pytz

from paper_execution.paper_broker  import is_paper_account_safe, submit_paper_exit_order
from paper_execution.trade_journal import mark_exit_submitted

_EASTERN = pytz.timezone("America/New_York")


# ── Result constructors ───────────────────────────────────────────────────────

def _base() -> dict:
    return {
        "enabled":          False,
        "stop_evaluated":   False,
        "stop_breached":    False,
        "breach_reason":    None,
        "exit_submitted":   False,
        "exit_order_id":    None,
        "exit_reason":      None,
        "action_taken":     "disabled",
        "warnings":         [],
    }


def _no_action(action: str = "monitoring", warnings: list | None = None) -> dict:
    r = _base()
    r.update({
        "enabled":        True,
        "stop_evaluated": True,
        "action_taken":   action,
        "warnings":       warnings or [],
    })
    return r


# ── Stop breach evaluation ────────────────────────────────────────────────────

def _is_breached(side: str, current_price: float, stop_reference: float) -> tuple[bool, str | None]:
    """Return (breached, reason) for the given side."""
    if side == "long":
        if current_price <= stop_reference:
            return True, f"price {current_price} <= stop {stop_reference} (long stop hit)"
        return False, None
    else:  # short
        if current_price >= stop_reference:
            return True, f"price {current_price} >= stop {stop_reference} (short stop hit)"
        return False, None


# ── Public entry point ────────────────────────────────────────────────────────

def enforce_stop(snapshot: dict, symbol: str, monitor_result: dict) -> dict:
    """
    Phase 2B — Paper Stop Enforcer entry point.
    Never raises — errors return a safe warning result.
    """
    try:
        return _enforce(snapshot, symbol, monitor_result)
    except Exception as exc:
        r = _no_action("error", [f"enforcer error: {exc}"])
        return r


def _enforce(snapshot: dict, symbol: str, monitor_result: dict) -> dict:

    # ── Feature flag ──────────────────────────────────────────────────────────
    if os.getenv("PAPER_STOP_MONITOR_ENABLED", "true").lower().strip() != "true":
        return _base()

    # ── Monitor must have an open position ────────────────────────────────────
    if not monitor_result.get("enabled"):
        return _base()

    monitor_status = monitor_result.get("status", "")
    if monitor_status != "monitoring":
        return _no_action("no_position")

    if not monitor_result.get("has_open_position"):
        return _no_action("no_position")

    # ── Extract fields from monitor ───────────────────────────────────────────
    side            = monitor_result.get("side")
    current_price   = monitor_result.get("current_price")
    stop_reference  = monitor_result.get("stop_reference")
    qty             = monitor_result.get("qty", 0)
    linked_trade_id = monitor_result.get("linked_trade_id")
    exit_already    = monitor_result.get("exit_already_submitted", False)
    warnings        = []

    if not side or current_price is None:
        return _no_action("monitoring", ["side or current_price unavailable"])

    if stop_reference is None:
        return _no_action("monitoring", ["no stop_reference — cannot evaluate breach"])

    # ── Evaluate breach ───────────────────────────────────────────────────────
    breached, breach_reason = _is_breached(side, float(current_price), float(stop_reference))

    result = {
        "enabled":          True,
        "stop_evaluated":   True,
        "stop_breached":    breached,
        "breach_reason":    breach_reason,
        "exit_submitted":   False,
        "exit_order_id":    None,
        "exit_reason":      None,
        "action_taken":     "monitoring",
        "warnings":         warnings,
    }

    if not breached:
        return result

    # ── Stop is breached — check whether to act ───────────────────────────────
    paper_exit_on = os.getenv("PAPER_EXIT_ON_STOP", "false").lower().strip()

    if exit_already:
        result.update({
            "action_taken": "exit_already_submitted",
            "warnings":     warnings + ["stop breached but exit already in flight — skipping"],
        })
        return result

    if paper_exit_on != "true":
        result.update({
            "action_taken": "stop_breached_no_action",
            "warnings":     warnings + ["PAPER_EXIT_ON_STOP=false — breach detected, no order submitted"],
        })
        return result

    # ── Paper safety check ────────────────────────────────────────────────────
    ep_safe, ep_reason = is_paper_account_safe()
    if not ep_safe:
        result.update({
            "action_taken": "stop_breached_no_action",
            "warnings":     warnings + [f"paper safety failed: {ep_reason}"],
        })
        return result

    # ── Submit exit order ─────────────────────────────────────────────────────
    exit_side = "sell" if side == "long" else "buy"
    exit_reason = f"stop_breached: {breach_reason}"

    try:
        order = submit_paper_exit_order(symbol, int(qty), exit_side)
        exit_order_id = order.get("alpaca_order_id")

        # Update journal if we have a linked trade
        if linked_trade_id:
            mark_exit_submitted(
                linked_trade_id,
                exit_order_id,
                float(stop_reference),
                exit_reason,
                symbol,
            )

        result.update({
            "exit_submitted":   True,
            "exit_order_id":    exit_order_id,
            "exit_reason":      exit_reason,
            "action_taken":     "exit_submitted",
        })

    except RuntimeError as exc:
        result.update({
            "action_taken": "exit_failed",
            "warnings":     warnings + [f"exit order failed: {exc}"],
        })

    return result
