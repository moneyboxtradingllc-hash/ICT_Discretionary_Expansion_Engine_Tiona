"""
Phase 5E.5 — Pending Entry Order Lifecycle Cancellation.

When a setup dies (invalidated, dormant, expired, no_trade), any pending
unfilled LIMIT entry order at Alpaca is cancelled immediately.

This prevents stale fills: an entry order placed during a live setup
surviving beyond the setup's invalidation and filling in a dead context.

Safety constraints (never violated):
  - Never cancels filled / partially_filled / closed orders
  - Never cancels when position is open at Alpaca
  - Never cancels when exit_submitted is True
  - Never cancels when setup is still active or maturing
  - Position API failure conservatively prevents cancel
  - Never raises — all errors return safe warning results
"""
from datetime import datetime

import pytz

from paper_execution.paper_broker  import cancel_order, get_position, is_paper_account_safe
from paper_execution.trade_journal import find_pending_entry_order, update_trade_status

_EASTERN = pytz.timezone("America/New_York")

# Setup lifecycle strings that indicate the setup has died
_DEAD_LIFECYCLE_PHASES = frozenset({"invalidated", "expired", "dormant"})
_DEAD_QUAL_STATUSES    = frozenset({"no_trade", "invalidated", "decay"})


# ── Public entry point ────────────────────────────────────────────────────────

def cancel_pending_entry_order_if_setup_dead(snapshot: dict, symbol: str) -> dict:
    """
    Phase 5E.5 — Cancel pending entry order when setup has died.

    Called every scan after trade reconciliation.
    Returns a compact result dict stored as snapshot['pending_entry_order'].
    Never raises.
    """
    try:
        return _cancel_if_dead(snapshot, symbol)
    except Exception as exc:
        return {
            "checked":             True,
            "status":              "error",
            "cancelled":           False,
            "trade_id":            None,
            "alpaca_order_id":     None,
            "order_status_before": None,
            "reason":              None,
            "journal_updated":     False,
            "warnings":            [f"pending_order_lifecycle error: {exc}"],
        }


# ── Core logic ────────────────────────────────────────────────────────────────

def _cancel_if_dead(snapshot: dict, symbol: str) -> dict:

    # Fail fast on misconfigured endpoint (config-only, no network call)
    ep_safe, ep_reason = is_paper_account_safe()
    if not ep_safe:
        return _no_order(warnings=[f"paper safety check failed: {ep_reason}"])

    # Find pending entry order in the journal
    trade = find_pending_entry_order(symbol)
    if trade is None:
        return _no_order()

    trade_id        = trade.get("trade_id") or ""
    alpaca_order_id = trade.get("alpaca_order_id") or ""
    order_status    = trade.get("order_status") or ""

    # Safety: never cancel an already-filled or closed order
    if order_status in ("filled", "partially_filled", "closed"):
        return _live_result(trade_id, alpaca_order_id, order_status,
                            "order already filled or closed — not cancelling")

    # Safety: never cancel when exit is already submitted (position likely open)
    if trade.get("exit_submitted", False):
        return _live_result(trade_id, alpaca_order_id, order_status,
                            "exit_submitted=true — position likely open")

    # Safety: never cancel when position is open at Alpaca
    position = get_position(symbol)
    if position is not None:
        if "error" in position:
            # Can't verify position state — conservatively skip cancel
            return _no_order(
                warnings=[
                    f"position check error: {position['error']}"
                    " — skipping cancel as safe default"
                ]
            )
        return _live_result(trade_id, alpaca_order_id, order_status,
                            "open position exists — not cancelling entry")

    # Is the setup dead?
    if not _is_setup_dead(snapshot):
        return _live_result(trade_id, alpaca_order_id, order_status,
                            "setup still active")

    # Cancel the pending entry order at Alpaca
    lifecycle_label = _current_lifecycle_label(snapshot)
    now_str         = datetime.now(_EASTERN).strftime("%Y%m%dT%H%M%S")
    warnings: list[str] = []

    cancel_result = cancel_order(alpaca_order_id)
    if not cancel_result.get("canceled"):
        cancel_warn = cancel_result.get("reason") or "cancel returned no confirmation"
        warnings.append(f"cancel_order did not confirm: {cancel_warn}")
        return {
            "checked":             True,
            "status":              "cancel_failed",
            "cancelled":           False,
            "trade_id":            trade_id,
            "alpaca_order_id":     alpaca_order_id,
            "order_status_before": order_status,
            "reason":              "setup_lifecycle_dead",
            "journal_updated":     False,
            "warnings":            warnings,
        }

    # Update journal: mark as cancelled with Phase 5E.5 fields
    journal_updated = update_trade_status(
        trade_id,
        "canceled",
        {
            "cancel_reason":             "setup_lifecycle_dead",
            "cancelled_at":              now_str,
            "setup_lifecycle_at_cancel": lifecycle_label,
            "pending_order_cancelled":   True,
        },
        symbol,
    )

    return {
        "checked":             True,
        "status":              "cancelled",
        "cancelled":           True,
        "trade_id":            trade_id,
        "alpaca_order_id":     alpaca_order_id,
        "order_status_before": order_status,
        "reason":              "setup_lifecycle_dead",
        "journal_updated":     journal_updated,
        "warnings":            warnings,
    }


# ── Setup death detection ─────────────────────────────────────────────────────

def _is_setup_dead(snapshot: dict) -> bool:
    """
    Return True if the setup has transitioned to a dead state.

    Conditions (any one is sufficient):
    1. setup_lifecycle["invalidated"] is True
    2. setup_lifecycle["current_phase"] in (invalidated, expired, dormant)
    3. state_transition["setup_lifecycle"] in (invalidated, expired, dormant)
    4. qualification.status in (no_trade, invalidated, decay)
    """
    sl   = snapshot.get("setup_lifecycle") or {}
    st   = snapshot.get("state_transition") or {}
    qual = ((snapshot.get("qualification") or {}).get("status") or "no_trade").lower()

    if sl.get("invalidated", False):
        return True
    phase = (sl.get("current_phase") or "").lower()
    if phase in _DEAD_LIFECYCLE_PHASES:
        return True
    st_lc = (st.get("setup_lifecycle") or "").lower()
    if st_lc in _DEAD_LIFECYCLE_PHASES:
        return True
    if qual in _DEAD_QUAL_STATUSES:
        return True
    return False


def _current_lifecycle_label(snapshot: dict) -> str:
    """Return the most descriptive lifecycle label for the journal cancel record."""
    sl = snapshot.get("setup_lifecycle") or {}
    if sl.get("invalidated"):
        return "invalidated"
    phase = (sl.get("current_phase") or "").lower()
    if phase:
        return phase
    st = snapshot.get("state_transition") or {}
    return (st.get("setup_lifecycle") or "dormant").lower()


# ── Result helpers ────────────────────────────────────────────────────────────

def _no_order(warnings: list | None = None) -> dict:
    return {
        "checked":             True,
        "status":              "none",
        "cancelled":           False,
        "trade_id":            None,
        "alpaca_order_id":     None,
        "order_status_before": None,
        "reason":              None,
        "journal_updated":     False,
        "warnings":            warnings or [],
    }


def _live_result(
    trade_id: str,
    alpaca_order_id: str,
    order_status: str,
    reason: str,
) -> dict:
    return {
        "checked":             True,
        "status":              "live",
        "cancelled":           False,
        "trade_id":            trade_id,
        "alpaca_order_id":     alpaca_order_id,
        "order_status_before": order_status,
        "reason":              reason,
        "journal_updated":     False,
        "warnings":            [],
    }
