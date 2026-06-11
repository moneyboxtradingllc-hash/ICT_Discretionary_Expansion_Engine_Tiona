"""
OPS-1 — End-of-Day Authority.

Removes the overnight ambiguity that already bit once (June 9 test trades
held ~1300 minutes because nothing said otherwise).

Policy (env-configurable, attested at startup):
  EOD_NO_ENTRY_AFTER  default 15:50 ET — entry authority revoked
  EOD_FLATTEN_AT      default 15:55 ET — open position handling executes
  EOD_POLICY          default flatten  — "flatten" | "hold"
                      "hold" is an EXPLICIT overnight attestation, never a default.

Flatten order of operations (learned from the June 10 manual close):
  1. cancel the protective stop FIRST (it holds the shares),
  2. market-close the position,
  3. journal the exit with reason eod_flatten.
Never raises.
"""
import os
from datetime import datetime

import pytz

_EASTERN = pytz.timezone("America/New_York")


def _parse_hhmm(raw: str, default: str) -> tuple:
    try:
        parts = (raw or default).strip().split(":")
        return int(parts[0]), int(parts[1])
    except (ValueError, IndexError, AttributeError):
        parts = default.split(":")
        return int(parts[0]), int(parts[1])


def check_eod_state(now: "datetime | None" = None) -> dict:
    """Where are we relative to the EOD cutoffs? Never raises."""
    now = now or datetime.now(_EASTERN)
    if now.tzinfo is None:
        now = _EASTERN.localize(now)

    ne_h, ne_m = _parse_hhmm(os.getenv("EOD_NO_ENTRY_AFTER"), "15:50")
    fl_h, fl_m = _parse_hhmm(os.getenv("EOD_FLATTEN_AT"), "15:55")
    policy     = (os.getenv("EOD_POLICY") or "flatten").lower().strip()
    if policy not in ("flatten", "hold"):
        policy = "flatten"

    minutes      = now.hour * 60 + now.minute
    past_entry   = minutes >= ne_h * 60 + ne_m
    past_flatten = minutes >= fl_h * 60 + fl_m

    return {
        "entries_allowed": not past_entry,
        "should_flatten":  past_flatten and policy == "flatten",
        "policy":          policy,
        "no_entry_after":  f"{ne_h:02d}:{ne_m:02d}",
        "flatten_at":      f"{fl_h:02d}:{fl_m:02d}",
        "reason": (
            "eod entry cutoff passed" if past_entry else "within session hours"
        ),
    }


def flatten_position_eod(symbol: str) -> dict:
    """Flatten the open position for EOD. Never raises."""
    try:
        from paper_execution.paper_broker import (
            get_position, cancel_order, close_position_market,
        )
        from paper_execution.trade_journal import (
            find_any_active_trade, mark_exit_submitted,
        )

        pos = get_position(symbol)
        if pos is None:
            return {"flattened": False, "reason": "no open position"}

        trade, _ = find_any_active_trade(symbol)
        stop_cancelled = False
        if trade and trade.get("broker_stop_order_id"):
            result = cancel_order(trade["broker_stop_order_id"])
            stop_cancelled = bool(result.get("canceled", False))

        close = close_position_market(symbol)
        order_id = close.get("alpaca_order_id")

        if trade:
            mark_exit_submitted(
                trade_id             = trade.get("trade_id"),
                exit_order_id        = order_id,
                exit_price_reference = pos.get("current_price"),
                reason               = "eod_flatten",
                symbol               = symbol,
            )

        return {
            "flattened":      True,
            "exit_order_id":  order_id,
            "stop_cancelled": stop_cancelled,
            "qty":            pos.get("qty"),
            "reason":         "eod_flatten policy executed",
        }
    except Exception as exc:  # noqa: BLE001
        return {"flattened": False, "reason": f"eod flatten error: {exc}"}
