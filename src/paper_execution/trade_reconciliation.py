"""
Phase 4A — Trade Reconciliation Engine.

Closes the paper trade lifecycle by polling Alpaca order and position state
after entry/exit execution and writing final closure records to the journal.

Lifecycle closure path:
  submitted → accepted → filled → position_open → position_closed → reconciled → closed

PAPER TRADING ONLY. No order submission. Read-only broker queries only.
Journal writes: update_trade_status, mark_closed.

Never modifies: decision_authority, execution_gate, paper_execution,
                AI layer, experience weighting, risk parameters.
"""
from datetime import datetime
import pytz

from paper_execution.paper_broker import (
    is_paper_account_safe, get_order, get_position,
    get_recent_closed_orders_for_symbol,
)
from paper_execution.trade_journal import (
    find_any_active_trade, update_trade_status, mark_closed,
)
from paper_execution.protective_stop import cancel_protective_stop_if_position_closed
from ai_feedback.ai_outcome_scorer import score_ai_outcome

_EASTERN = pytz.timezone("America/New_York")

# Entry order statuses that mean no position was taken
_TERMINAL_NO_FILL = frozenset({
    "canceled", "cancelled", "rejected", "expired", "done_for_day", "stopped",
})

# Entry order statuses that mean a position exists (or partially exists)
_FILLED_STATUSES = frozenset({"filled", "partially_filled"})

# Exit order statuses
_EXIT_FILLED   = frozenset({"filled"})
_EXIT_TERMINAL = frozenset({"canceled", "cancelled", "rejected", "expired"})


def reconcile_trade(symbol: str) -> dict:
    """
    Phase 4A entry point — close the trade lifecycle.

    Steps:
    1. Find most recent non-terminal trade in journal
    2. Sync entry order state with Alpaca (if still pending)
    3. If entry order terminal with no fill → return terminal status
    4. If exit order submitted → check for fill → compute closure metrics → mark_closed
    5. If position is gone with no tracked exit → detect externally closed
    6. Otherwise → trade still open, no action

    Never raises. Returns safe default on any error.
    PAPER TRADING ONLY. No order submission.
    """
    try:
        return _reconcile(symbol)
    except Exception as exc:
        return {
            "trade_found":      False,
            "status":           "error",
            "realized_pnl":     None,
            "realized_r":       None,
            "holding_minutes":  None,
            "journal_updated":  False,
            "warnings":         [f"reconciliation error: {exc}"],
        }


def _reconcile(symbol: str) -> dict:

    # ── Paper safety guard ────────────────────────────────────────────────────
    ep_safe, ep_reason = is_paper_account_safe()
    if not ep_safe:
        return _open_result(warnings=[f"paper safety check failed: {ep_reason}"])

    # ── 1. Find most recent non-terminal trade ────────────────────────────────
    trade, _fp = find_any_active_trade(symbol)
    if trade is None:
        return {
            "trade_found":      False,
            "status":           "no_active_trade",
            "realized_pnl":     None,
            "realized_r":       None,
            "holding_minutes":  None,
            "journal_updated":  False,
            "warnings":         [],
        }

    trade_id        = trade.get("trade_id", "")
    alpaca_order_id = trade.get("alpaca_order_id")
    order_status    = trade.get("order_status", "")
    exit_submitted  = bool(trade.get("exit_submitted", False))
    exit_order_id   = trade.get("exit_order_id")
    warnings: list[str] = []

    # ── 2. Sync entry order if still pending ─────────────────────────────────
    # OPS-1 hotfix: include "new" — Alpaca's accepted-state label — or the
    # fill-sync deadlocks (see 2026-06-11 unprotected-position incident).
    if order_status in ("submitted", "accepted", "pending_new", "new") and alpaca_order_id:
        order_info = get_order(alpaca_order_id)
        if order_info and "error" not in order_info:
            new_status = order_info.get("status", "")
            if new_status and new_status != order_status:
                extra: dict = {}
                if new_status in _FILLED_STATUSES:
                    extra["avg_fill_price"] = order_info.get("filled_avg_price")
                    extra["filled_qty"]      = order_info.get("filled_qty")
                    extra["entry_price"]     = order_info.get("filled_avg_price")
                    # FC-0B: fill-truth risk — every downstream R denominator
                    # (trade_manager, thesis_monitor, realized_r) reads the
                    # journal's risk_per_share; correct it to the actual fill.
                    extra.update(_fill_truth_risk(trade, order_info))
                update_trade_status(trade_id, new_status, extra, symbol)
                order_status = new_status
                trade = {**trade, "order_status": new_status, **extra}
        elif order_info and "error" in order_info:
            warnings.append(f"entry order query error: {order_info['error']}")

    # ── 3. Terminal entry orders (never filled — no position) ─────────────────
    if order_status in _TERMINAL_NO_FILL:
        return {
            "trade_found":      True,
            "status":           order_status,
            "trade_id":         trade_id,
            "realized_pnl":     None,
            "realized_r":       None,
            "holding_minutes":  None,
            "journal_updated":  False,
            "warnings":         warnings,
        }

    # ── 4. Exit order fill check ──────────────────────────────────────────────
    if exit_submitted and exit_order_id:
        exit_info = get_order(exit_order_id)
        if exit_info and "error" not in exit_info:
            exit_status = exit_info.get("status", "")
            if exit_status in _EXIT_FILLED:
                return _close_from_exit(
                    trade, exit_info, "stop_exit_filled", symbol, warnings,
                )
            if exit_status in _EXIT_TERMINAL:
                warnings.append(
                    f"exit order {exit_status} — position may be unprotected; "
                    "re-examine manually"
                )
                return _open_result(warnings=warnings)
        elif exit_info and "error" in exit_info:
            warnings.append(f"exit order query error: {exit_info['error']}")

    # ── 4b. Broker stop order fill check ──────────────────────────────────────
    broker_stop_order_id = trade.get("broker_stop_order_id")
    if (not exit_submitted and broker_stop_order_id
            and order_status in _FILLED_STATUSES):
        stop_info = get_order(broker_stop_order_id)
        if stop_info and "error" not in stop_info:
            if stop_info.get("status", "") in _EXIT_FILLED:
                return _close_from_exit(
                    trade, stop_info, "broker_stop_triggered", symbol, warnings,
                )
        elif stop_info and "error" in stop_info:
            warnings.append(f"broker stop order query error: {stop_info['error']}")

    # ── 5. Position-gone detection (no exit tracked) ──────────────────────────
    if order_status in _FILLED_STATUSES:
        position = get_position(symbol)
        if position is None:
            return _handle_externally_closed(trade, symbol, warnings)
        if "error" in position:
            warnings.append(f"position query error: {position['error']}")

    # ── 6. Trade still open — nothing to close ────────────────────────────────
    return _open_result(warnings=warnings)


# ── Closure helpers ───────────────────────────────────────────────────────────

def _close_from_exit(
    trade: dict,
    exit_info: dict,
    reason: str,
    symbol: str,
    warnings: list[str],
) -> dict:
    """Compute closure metrics from a known filled exit order and call mark_closed."""
    now_str = datetime.now(_EASTERN).strftime("%Y%m%dT%H%M%S")

    exit_avg_price  = _to_float(exit_info.get("filled_avg_price"))
    entry_avg_price = _to_float(
        trade.get("avg_fill_price") or trade.get("entry_price") or trade.get("entry_reference")
    )
    qty  = int(_to_float(trade.get("filled_qty") or trade.get("qty"), default=0))
    side = (trade.get("side") or "buy").lower()

    realized_pnl = None
    if exit_avg_price is not None and entry_avg_price is not None and qty > 0:
        if side == "buy":    # long
            realized_pnl = round((exit_avg_price - entry_avg_price) * qty, 2)
        else:                # short
            realized_pnl = round((entry_avg_price - exit_avg_price) * qty, 2)

    risk_dollars = _to_float(trade.get("risk_dollars"), default=0.0)
    realized_r   = None
    if realized_pnl is not None and risk_dollars and risk_dollars > 0:
        realized_r = round(realized_pnl / risk_dollars, 4)

    holding_minutes = _compute_holding_minutes(trade.get("timestamp"), now_str)

    journal_updated = mark_closed(
        trade_id        = trade["trade_id"],
        realized_pnl    = realized_pnl if realized_pnl is not None else 0.0,
        closed_at       = now_str,
        reason          = reason,
        symbol          = symbol,
        realized_r      = realized_r,
        holding_minutes = holding_minutes,
        entry_price     = entry_avg_price,
        exit_price      = exit_avg_price,
        final_status    = "closed",
    )

    # Phase 5B: score AI outcome after closure (non-blocking)
    if journal_updated:
        _score_and_persist_ai_outcome(trade, realized_r, symbol, warnings)

    if reason != "broker_stop_triggered":
        _cancel_stop_after_close(trade, symbol)

    return {
        "trade_found":      True,
        "status":           "closed",
        "trade_id":         trade.get("trade_id"),
        "realized_pnl":     realized_pnl,
        "realized_r":       realized_r,
        "holding_minutes":  holding_minutes,
        "entry_price":      entry_avg_price,
        "exit_price":       exit_avg_price,
        "close_reason":     reason,
        "journal_updated":  journal_updated,
        "warnings":         warnings,
    }


def _handle_externally_closed(
    trade: dict,
    symbol: str,
    warnings: list[str],
) -> dict:
    """
    Position is gone but no tracked exit order.
    Search recent Alpaca closed orders for a matching exit fill.
    If found: compute P&L normally.
    If not found: mark closed with realized_pnl=None (unknown).
    """
    trade_id    = trade.get("trade_id", "")
    entry_ts    = trade.get("timestamp", "")
    side        = (trade.get("side") or "buy").lower()
    exit_side   = "sell" if side == "buy" else "buy"

    # Search recent closed orders for an exit fill on the opposite side
    recent = get_recent_closed_orders_for_symbol(symbol, limit=10)
    exit_info = None
    for o in recent:
        if "error" in o:
            warnings.append(f"closed orders query error: {o['error']}")
            break
        o_side   = str(o.get("side", "")).lower()
        o_status = str(o.get("status", "")).lower()
        o_subm    = str(o.get("submitted_at", ""))
        o_subm_dt = _parse_alpaca_ts(o_subm)
        entry_dt  = _parse_ts(entry_ts)
        ts_ok     = (o_subm_dt is not None and entry_dt is not None
                     and o_subm_dt >= entry_dt)
        if (exit_side in o_side and o_status == "filled" and ts_ok):
            exit_info = o
            break

    if exit_info:
        return _close_from_exit(trade, exit_info, "externally_closed", symbol, warnings)

    # Can't determine exact P&L
    now_str = datetime.now(_EASTERN).strftime("%Y%m%dT%H%M%S")
    entry_price = _to_float(
        trade.get("avg_fill_price") or trade.get("entry_price") or trade.get("entry_reference")
    )
    holding_minutes = _compute_holding_minutes(trade.get("timestamp"), now_str)

    journal_updated = mark_closed(
        trade_id        = trade_id,
        realized_pnl    = 0.0,
        closed_at       = now_str,
        reason          = "externally_closed_no_fill_data",
        symbol          = symbol,
        realized_r      = None,
        holding_minutes = holding_minutes,
        entry_price     = entry_price,
        exit_price      = None,
        final_status    = "externally_closed",
    )
    # Phase 5B: score AI outcome (realized_r=None → will produce 'unknown' score)
    if journal_updated:
        _score_and_persist_ai_outcome(trade, None, symbol, warnings)

    _cancel_stop_after_close(trade, symbol)
    warnings.append("position gone without tracked exit — realized_pnl unknown")

    return {
        "trade_found":      True,
        "status":           "externally_closed",
        "trade_id":         trade_id,
        "realized_pnl":     None,
        "realized_r":       None,
        "holding_minutes":  holding_minutes,
        "entry_price":      entry_price,
        "exit_price":       None,
        "close_reason":     "externally_closed_no_fill_data",
        "journal_updated":  journal_updated,
        "warnings":         warnings,
    }


def _score_and_persist_ai_outcome(
    trade: dict,
    realized_r: "float | None",
    symbol: str,
    warnings: list[str],
) -> None:
    """
    Phase 5B — Score AI outcome after closure and persist to journal.
    Non-blocking: any error adds a warning but does not interrupt reconciliation.
    """
    try:
        scored_trade = {
            **trade,
            "order_status": "closed",
            "realized_r":   realized_r,
        }
        outcome = score_ai_outcome(scored_trade)
        if outcome.get("scored"):
            update_trade_status(
                trade["trade_id"],
                "closed",
                {
                    "ai_outcome_scored":            True,
                    "ai_was_directionally_correct": outcome.get("ai_was_directionally_correct"),
                    "ai_agreement_outcome":         outcome.get("ai_agreement_outcome", "unknown"),
                    "ai_confidence_quality":        outcome.get("ai_confidence_quality", "unknown"),
                    "ai_value_label":               outcome.get("ai_value_label", "unknown"),
                    "ai_outcome_reason":            outcome.get("reason"),
                },
                symbol,
            )
    except Exception as exc:
        warnings.append(f"ai outcome scoring failed (non-blocking): {exc}")


def _open_result(warnings: list[str] | None = None) -> dict:
    return {
        "trade_found":      True,
        "status":           "open",
        "realized_pnl":     None,
        "realized_r":       None,
        "holding_minutes":  None,
        "journal_updated":  False,
        "warnings":         warnings or [],
    }


# ── Internal helpers ──────────────────────────────────────────────────────────

def _to_float(value, default=None):
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_ts(ts: str):
    if not ts or len(ts) < 15:
        return None
    try:
        dt = datetime.strptime(ts[:15], "%Y%m%dT%H%M%S")
        return _EASTERN.localize(dt)
    except Exception:
        return None


def _compute_holding_minutes(entry_ts: str | None, exit_ts: str | None) -> float | None:
    t1 = _parse_ts(entry_ts)
    t2 = _parse_ts(exit_ts)
    if t1 is None or t2 is None:
        return None
    diff = (t2 - t1).total_seconds() / 60.0
    return round(diff, 2) if diff >= 0 else None


def _parse_alpaca_ts(ts_str: str):
    """Parse Alpaca ISO format timestamp (hyphens, tz offset) to aware datetime, or None."""
    if not ts_str or len(ts_str) < 10:
        return None
    try:
        dt = datetime.fromisoformat(ts_str)
        if dt.tzinfo is None:
            dt = _EASTERN.localize(dt)
        return dt
    except (ValueError, TypeError):
        return None


def _fill_truth_risk(trade: dict, order_info: dict) -> dict:
    """
    Phase FC-0B — recompute risk from the actual fill (market-order doctrine).

    Pre-FC, risk_per_share was the order-build estimate (zone midpoint vs
    stop) and never corrected: June 11's journal carried 0.35 while the
    fill-to-stop risk was 0.33. With market entries the estimate/fill gap is
    slippage-sized and must not distort R math. The build-time values are
    preserved as planned_*; entry_slippage is signed (positive = adverse).

    Never raises — returns {} on any missing/invalid input.
    """
    out: dict = {}
    try:
        fill = order_info.get("filled_avg_price")
        stop = trade.get("stop_reference")
        if fill is None or stop is None:
            return out
        fill = float(fill)
        rps  = abs(fill - float(stop))
        if rps <= 0:
            return out
        qty = int(float(order_info.get("filled_qty") or trade.get("qty") or 0))
        out["planned_risk_per_share"] = trade.get("risk_per_share")
        out["planned_risk_dollars"]   = trade.get("risk_dollars")
        out["risk_per_share"]         = round(rps, 4)
        out["risk_dollars"]           = round(rps * qty, 2) if qty > 0 else trade.get("risk_dollars")
        decision_price = trade.get("decision_price")
        if decision_price is not None:
            side = (trade.get("side") or "buy").lower()
            slip = (fill - float(decision_price)) if side == "buy" else (float(decision_price) - fill)
            out["entry_slippage"] = round(slip, 4)
    except (TypeError, ValueError):
        return {}
    return out


def _cancel_stop_after_close(trade: dict, symbol: str) -> None:
    """Cancel orphaned broker stop when position is closed by non-broker-stop means."""
    broker_stop_id = trade.get("broker_stop_order_id")
    if broker_stop_id:
        cancel_protective_stop_if_position_closed(
            trade.get("trade_id", ""), symbol, broker_stop_id
        )
