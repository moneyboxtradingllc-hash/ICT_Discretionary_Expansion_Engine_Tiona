"""
Phase 4B — Protective Stop Manager.
Phase 5E.7 — Broker stop price validation after fill.

Submits and verifies broker-side protective stop orders for paper positions.
PAPER TRADING ONLY. BROKER_STOP_ENABLED=false (default) disables all actions.

BROKER_STOP_MODE=after_fill   — stop submitted after fill confirmation (default).
BROKER_STOP_MODE=bracket_if_supported — OTO/bracket at entry time if supported;
                                         falls back to after_fill if not.

Phase 5E.7 — stop price validation:
  Before submitting, fetch current_price (and fill_price as fallback) from the
  open position. For a long STOP SELL, stop must be < current_price. For a short
  STOP BUY, stop must be > current_price. When the pre-trade stop_reference
  violates this, adjust by BROKER_STOP_PRICE_BUFFER (default 0.05) away from
  the reference price. If the adjusted price is invalid, return a warning and
  do not submit.

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
    get_position,
)
from paper_execution.trade_journal import update_broker_stop

_EASTERN = pytz.timezone("America/New_York")


def _stop_price_buffer() -> float:
    try:
        return float(os.getenv("BROKER_STOP_PRICE_BUFFER", "0.05"))
    except (TypeError, ValueError):
        return 0.05


def _fetch_reference_price(symbol: str) -> tuple:
    """
    Fetch current_market_price and fill_price for stop validation.
    Returns (current_price, fill_price, source_label).
    Never raises.
    """
    try:
        pos = get_position(symbol)
        if pos and "error" not in pos:
            raw_current = pos.get("current_price")
            raw_fill    = pos.get("avg_entry_price")
            current = float(raw_current) if raw_current is not None else None
            fill    = float(raw_fill)    if raw_fill    is not None else None
            return current, fill, "current_market_price"
    except Exception:
        pass
    return None, None, "unavailable"


def _adjust_stop_price(
    stop_price: float,
    current_price,
    fill_price,
    position_side: str,
    buffer: float,
) -> dict:
    """
    Phase 5E.7 — validate stop_price against market and adjust if needed.

    For long:  stop must be < current_price (STOP SELL triggers on downward move).
    For short: stop must be > current_price (STOP BUY  triggers on upward move).

    Returns:
      {"valid": True, "adjusted_stop": float, "stop_adjusted": bool,
       "adjustment_reason": str, "reference_price_used": float|None,
       "reference_source": str}
    or
      {"valid": False, "reason": str}
    """
    if current_price is not None and current_price > 0:
        ref_price  = current_price
        ref_source = "current_market_price"
    elif fill_price is not None and fill_price > 0:
        ref_price  = fill_price
        ref_source = "fill_price"
    else:
        return {
            "valid":                True,
            "adjusted_stop":        stop_price,
            "stop_adjusted":        False,
            "adjustment_reason":    "no_reference_price_available",
            "reference_price_used": None,
            "reference_source":     "unavailable",
        }

    adjusted_stop     = stop_price
    stop_adjusted     = False
    adjustment_reason = "no_adjustment_needed"

    if position_side == "long":
        if stop_price >= ref_price:
            adjusted_stop     = round(ref_price - buffer, 2)
            stop_adjusted     = True
            adjustment_reason = "long_stop_above_market"
    else:  # short
        if stop_price <= ref_price:
            adjusted_stop     = round(ref_price + buffer, 2)
            stop_adjusted     = True
            adjustment_reason = "short_stop_below_market"

    if adjusted_stop <= 0:
        return {
            "valid":  False,
            "reason": (
                f"adjusted_stop_price={adjusted_stop:.4f} is invalid (<= 0) "
                f"after applying buffer={buffer} to ref={ref_price}"
            ),
        }

    return {
        "valid":                True,
        "adjusted_stop":        adjusted_stop,
        "stop_adjusted":        stop_adjusted,
        "adjustment_reason":    adjustment_reason,
        "reference_price_used": ref_price,
        "reference_source":     ref_source,
    }


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

    stop_side      = stop_build["stop_side"]
    original_price = stop_build["stop_price"]
    clean_qty      = stop_build["qty"]

    # ── Phase 5E.7: validate stop price against current market ───────────────
    current_price, fill_price, ref_source = _fetch_reference_price(symbol)
    adjustment = _adjust_stop_price(
        stop_price    = original_price,
        current_price = current_price,
        fill_price    = fill_price,
        position_side = position_side,
        buffer        = _stop_price_buffer(),
    )

    if not adjustment["valid"]:
        return _error(
            f"stop price invalid after adjustment: {adjustment['reason']}",
            warnings=[adjustment["reason"]],
        )

    clean_price = adjustment["adjusted_stop"]

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
        "enabled":              True,
        "stop_submitted":       True,
        "stop_order_id":        stop_order_id,
        "stop_price":           clean_price,
        "status":               "submitted",
        "reason":               "protective stop submitted after fill",
        "warnings":             [],
        # ── Phase 5E.7 fields ─────────────────────────────────────────────
        "original_stop_price":  original_price,
        "adjusted_stop_price":  clean_price,
        "stop_adjusted":        adjustment["stop_adjusted"],
        "adjustment_reason":    adjustment["adjustment_reason"],
        "reference_price_used": adjustment["reference_price_used"],
        "reference_source":     adjustment["reference_source"],
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
