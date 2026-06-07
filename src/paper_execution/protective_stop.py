"""
Phase 4B — Protective Stop Manager.

Submits and verifies broker-side protective stop orders for paper positions.
PAPER TRADING ONLY. BROKER_STOP_ENABLED=false (default) disables all actions.

BROKER_STOP_MODE=after_fill   — stop submitted after fill confirmation (default).
BROKER_STOP_MODE=bracket_if_supported — OTO/bracket at entry time if supported;
                                         falls back to after_fill if not.

Safety:
  - Paper endpoint validated before every submission.
  - Never submits duplicate stops (caller checks broker_stop_order_id first).
  - Never raises — all errors return a safe result dict.
"""
import os
from datetime import datetime

import pytz

from paper_execution.paper_broker  import (
    is_paper_account_safe,
    submit_protective_stop_order,
    find_open_stop_order,
    cancel_order,
)
from paper_execution.trade_journal import update_broker_stop

_EASTERN = pytz.timezone("America/New_York")


# ── Result helpers ────────────────────────────────────────────────────────────

def _disabled(reason: str = "BROKER_STOP_ENABLED=false") -> dict:
    return {
        "enabled":        False,
        "stop_submitted": False,
        "stop_order_id":  None,
        "stop_price":     None,
        "status":         "disabled",
        "reason":         reason,
        "warnings":       [],
    }


def _error(reason: str, warnings: list | None = None) -> dict:
    return {
        "enabled":        True,
        "stop_submitted": False,
        "stop_order_id":  None,
        "stop_price":     None,
        "status":         "error",
        "reason":         reason,
        "warnings":       warnings or [],
    }


# ── Feature flag ──────────────────────────────────────────────────────────────

def _stop_enabled() -> bool:
    return os.getenv("BROKER_STOP_ENABLED", "false").lower().strip() == "true"


def _stop_mode() -> str:
    return os.getenv("BROKER_STOP_MODE", "after_fill").lower().strip()


# ── Stop order parameter builder ──────────────────────────────────────────────

def build_stop_order(
    symbol: str,
    position_side: str,   # "long" or "short"
    qty: int,
    stop_price: float,
) -> dict:
    """
    Validate stop parameters and derive the broker-facing stop side.

    For long position: stop side = sell (to close the long).
    For short position: stop side = buy (to close the short).

    Returns {"valid": True, "stop_side": str, "stop_price": float, ...}
    or      {"valid": False, "reason": str}.
    """
    if qty <= 0:
        return {"valid": False, "reason": f"qty must be > 0 (got {qty})"}
    if position_side not in ("long", "short"):
        return {"valid": False, "reason": f"invalid position side '{position_side}' — expected long/short"}
    if stop_price is None or float(stop_price) <= 0:
        return {"valid": False, "reason": f"invalid stop_price {stop_price}"}

    stop_side = "sell" if position_side == "long" else "buy"

    return {
        "valid":      True,
        "stop_side":  stop_side,
        "stop_price": round(float(stop_price), 2),
        "qty":        int(qty),
        "symbol":     symbol,
    }


# ── Submit ────────────────────────────────────────────────────────────────────

def submit_protective_stop(
    trade_id: str,
    symbol: str,
    position_side: str,
    qty: int,
    stop_price: float,
) -> dict:
    """
    Submit a broker-side protective stop for an open position.
    Writes broker_stop fields to the journal on success.
    Never raises.
    """
    if not _stop_enabled():
        return _disabled()
    try:
        return _submit(trade_id, symbol, position_side, qty, stop_price)
    except Exception as exc:
        return _error(f"submit_protective_stop unexpected error: {exc}")


def _submit(
    trade_id: str,
    symbol: str,
    position_side: str,
    qty: int,
    stop_price: float,
) -> dict:
    safe, reason = is_paper_account_safe()
    if not safe:
        return _error(f"paper safety check failed: {reason}")

    stop_build = build_stop_order(symbol, position_side, qty, stop_price)
    if not stop_build["valid"]:
        return _error(f"invalid stop parameters: {stop_build['reason']}")

    stop_side   = stop_build["stop_side"]
    clean_price = stop_build["stop_price"]
    clean_qty   = stop_build["qty"]

    submission = submit_protective_stop_order(symbol, clean_qty, stop_side, clean_price)
    if "error" in submission:
        return _error(f"broker stop submission failed: {submission['error']}")

    stop_order_id = submission.get("alpaca_order_id")
    now_str       = datetime.now(_EASTERN).strftime("%Y%m%dT%H%M%S")

    if trade_id:
        update_broker_stop(
            trade_id     = trade_id,
            symbol       = symbol,
            order_id     = stop_order_id,
            stop_price   = clean_price,
            status       = "broker_stop_submitted",
            submitted_at = now_str,
        )

    return {
        "enabled":        True,
        "stop_submitted": True,
        "stop_order_id":  stop_order_id,
        "stop_price":     clean_price,
        "status":         "submitted",
        "reason":         "protective stop submitted after fill",
        "warnings":       [],
    }


# ── Verify ────────────────────────────────────────────────────────────────────

def verify_protective_stop_exists(
    trade_id: str,
    symbol: str,
    position_side: str,
    stop_price: float,
) -> dict:
    """
    Check whether a broker-side stop order still exists for the symbol.
    Returns status: "verified" | "missing" | "disabled" | "error".
    Never raises.
    """
    if not _stop_enabled():
        return _disabled()
    try:
        return _verify(trade_id, symbol, position_side, stop_price)
    except Exception as exc:
        return _error(f"verify_protective_stop_exists unexpected error: {exc}")


def _verify(
    trade_id: str,
    symbol: str,
    position_side: str,
    stop_price: float,
) -> dict:
    safe, reason = is_paper_account_safe()
    if not safe:
        return _error(f"paper safety check failed: {reason}")

    stop_side = "sell" if position_side == "long" else "buy"
    existing  = find_open_stop_order(symbol, stop_side, float(stop_price))

    if existing:
        order_id = existing.get("id")
        if trade_id:
            update_broker_stop(
                trade_id     = trade_id,
                symbol       = symbol,
                order_id     = order_id,
                stop_price   = float(stop_price),
                status       = "broker_stop_verified",
                submitted_at = None,
            )
        return {
            "enabled":        True,
            "stop_submitted": True,
            "stop_order_id":  order_id,
            "stop_price":     round(float(stop_price), 2),
            "status":         "verified",
            "reason":         "broker stop verified",
            "warnings":       [],
        }

    # Not found — mark missing in journal
    if trade_id:
        update_broker_stop(
            trade_id     = trade_id,
            symbol       = symbol,
            order_id     = None,
            stop_price   = float(stop_price),
            status       = "broker_stop_missing",
            submitted_at = None,
        )
    return {
        "enabled":        True,
        "stop_submitted": False,
        "stop_order_id":  None,
        "stop_price":     round(float(stop_price), 2),
        "status":         "missing",
        "reason":         "broker stop not found at broker",
        "warnings":       ["broker stop order not found — may have been triggered or canceled"],
    }


# ── Cancel ────────────────────────────────────────────────────────────────────

def cancel_protective_stop_if_position_closed(
    trade_id: str,
    symbol: str,
    broker_stop_order_id: str | None,
) -> dict:
    """
    Cancel the broker stop order when the position is confirmed closed.
    Safe to call when stop was already triggered/expired. Never raises.
    """
    if not _stop_enabled():
        return _disabled()

    if not broker_stop_order_id:
        return {
            "enabled":  True,
            "canceled": False,
            "reason":   "no stop order ID to cancel",
            "warnings": [],
        }

    try:
        safe, reason = is_paper_account_safe()
        if not safe:
            return _error(f"paper safety check failed: {reason}")

        cancel_result = cancel_order(broker_stop_order_id)
        if cancel_result.get("canceled"):
            if trade_id:
                update_broker_stop(
                    trade_id     = trade_id,
                    symbol       = symbol,
                    order_id     = broker_stop_order_id,
                    stop_price   = None,
                    status       = "broker_stop_canceled",
                    submitted_at = None,
                )
            return {"enabled": True, "canceled": True, "reason": "broker stop canceled", "warnings": []}

        # Not cancelable (already triggered, expired, or filled) — that is acceptable
        cancel_reason = cancel_result.get("reason", "cancel returned no confirmation")
        return {
            "enabled":  True,
            "canceled": False,
            "reason":   cancel_reason,
            "warnings": [],
        }

    except Exception as exc:
        return _error(f"cancel_protective_stop_if_position_closed error: {exc}")
