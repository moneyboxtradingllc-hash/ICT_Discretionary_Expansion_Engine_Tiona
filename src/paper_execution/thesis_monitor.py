"""
Phase 5T.2 — Thesis-Failure Monitor (shadow).
Phase FC-2 — Live thesis exits (June 11 promotion of TFX-001).

Detects, while a position is open, that the thesis which justified the entry
is no longer valid.

Thesis-death triggers (policy-gated by the trade's locked profile):
  lifecycle_invalidated — setup lifecycle declared the setup dead
  setup_invalidated     — state-transition engine invalidated the setup
  delivery_collapse     — (TREND profile only) measured delivery broke while
                          holding a continuation-thesis position

MODES (FC-2):
  THESIS_EXIT_MODE=shadow (default) — 5T.2 behavior: signal + ledger only.
  THESIS_EXIT_MODE=live — submit a market exit when the thesis dies.
    June 11 evidence (TFX-001): signal fired at -0.06R, 2 minutes after
    entry; the position was carried to the broker stop at -1.34R.
  THESIS_EXIT_CONFIRM_SCANS (default 1) — consecutive death detections
    required before acting (>1 protects against one-scan context flicker
    at the cost of exit price; June 11's signal was correct on scan one).

CONSTITUTION (FC-2 revision):
  - One signal per trade (first thesis death wins); persisted to the journal
    so restarts do not re-signal or re-exit.
  - Live exits cancel the broker stop FIRST (a stop + market exit both live
    would double-fill into a reverse position), then market-exit the full
    position. A failed exit submission falls back to shadow signaling —
    the broker stop is resubmitted-safe via stop_enforcer/position paths.
  - Counterfactual: the ledger event carries r_at_signal; when the trade
    closes, 5H.3 resolution attaches realized_r. saved_r = r_at_signal -
    realized_r is computed at scoring time (positive = exit would have saved).
  - Never raises.
Rollback: THESIS_EXIT_MODE=shadow.
"""
import os
from datetime import datetime

import pytz

from paper_execution.management_policies import get_policy
from paper_execution.paper_broker import cancel_order, submit_paper_exit_order
from paper_execution.trade_journal import (
    find_any_active_trade,
    mark_exit_submitted,
    update_trade_management,
)

_EASTERN = pytz.timezone("America/New_York")

_RULE_ID = "TFX-001"


def _enabled() -> bool:
    return os.getenv("THESIS_MONITOR_ENABLED", "true").lower().strip() == "true"


def _exit_mode() -> str:
    """FC-2 — 'live' submits real exits; 'shadow' (default) signals only."""
    mode = os.getenv("THESIS_EXIT_MODE", "shadow").lower().strip()
    return mode if mode in ("shadow", "live") else "shadow"


def _confirm_scans() -> int:
    try:
        return max(1, int(os.getenv("THESIS_EXIT_CONFIRM_SCANS", "1")))
    except (TypeError, ValueError):
        return 1


def _calc_r(current_price, entry_price, risk_per_share, side) -> "float | None":
    try:
        rps = float(risk_per_share)
        if rps <= 0:
            return None
        cp, ep = float(current_price), float(entry_price)
        return (cp - ep) / rps if side == "long" else (ep - cp) / rps
    except (TypeError, ValueError):
        return None


def _detect_thesis_death(snapshot: dict, profile: str) -> "tuple[str, str] | None":
    """Returns (reason_code, detail) or None. Policy-gated by profile."""
    sl = snapshot.get("setup_lifecycle", {}) or {}
    if sl.get("active") and (sl.get("current_phase") or "").lower() == "invalidated":
        return "lifecycle_invalidated", sl.get("reason") or "setup lifecycle invalidated"

    st = snapshot.get("state_transition", {}) or {}
    if st.get("invalidated"):
        return "setup_invalidated", "state transition invalidated the setup"

    if profile == "trend":
        ctx = snapshot.get("shared_context", {}) or {}
        state  = (ctx.get("delivery_state") or "unknown").lower()
        intact = ctx.get("continuation_intact") is True
        conf   = int(ctx.get("delivery_confidence", 0) or 0)
        # Measured collapse only — missing data never signals
        if state not in ("unknown", "") and not intact and conf < 40:
            return "delivery_collapse", (
                f"delivery broke while holding (state={state}, confidence={conf})"
            )

    return None


def monitor_thesis(snapshot: dict, symbol: str) -> dict:
    """
    Phase 5T.2 — Evaluate thesis validity for the open position.
    SHADOW ONLY: returns a result dict (+ ledger events for scan_loop to
    persist). Never exits, never raises.
    """
    try:
        return _monitor(snapshot or {}, symbol)
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "would_exit": False, "events": [],
                "reason": f"thesis monitor error: {exc}"}


def _monitor(snapshot: dict, symbol: str) -> dict:
    if not _enabled():
        return {"status": "disabled", "would_exit": False, "events": []}

    pm = snapshot.get("position_monitor", {}) or {}
    if not pm.get("has_open_position"):
        return {"status": "no_position", "would_exit": False, "events": []}
    if pm.get("exit_already_submitted"):
        return {"status": "exit_already_submitted", "would_exit": False, "events": []}

    trade_record, _ = find_any_active_trade(symbol)
    if trade_record is None:
        return {"status": "no_journal_trade", "would_exit": False, "events": []}

    # One signal per trade
    if trade_record.get("thesis_exit_signaled"):
        return {
            "status":     "already_signaled",
            "would_exit": False,
            "events":     [],
            "reason":     trade_record.get("thesis_exit_reason"),
        }

    profile = (trade_record.get("management_profile") or "defensive").lower()
    policy  = get_policy(profile)
    if policy.get("thesis_exit") not in ("shadow", "live"):
        return {"status": "off_by_policy", "would_exit": False, "events": []}

    death = _detect_thesis_death(snapshot, profile)
    if death is None:
        # FC-2: a recovered thesis resets the confirmation counter.
        if trade_record.get("thesis_exit_pending_count"):
            update_trade_management(
                trade_record.get("trade_id"),
                {"thesis_exit_pending_count": 0}, symbol,
            )
        return {"status": "thesis_intact", "would_exit": False, "events": []}

    reason_code, detail = death
    trade_id = trade_record.get("trade_id")

    # ── FC-2: consecutive-scan confirmation ───────────────────────────────────
    pending = int(trade_record.get("thesis_exit_pending_count") or 0) + 1
    if pending < _confirm_scans():
        update_trade_management(
            trade_id, {"thesis_exit_pending_count": pending}, symbol,
        )
        return {
            "status":     "confirming",
            "would_exit": False,
            "reason":     reason_code,
            "pending":    pending,
            "required":   _confirm_scans(),
            "events":     [],
        }

    current_price = pm.get("current_price")
    side          = pm.get("side")
    entry_price   = pm.get("avg_entry_price")
    r_at_signal   = _calc_r(current_price, entry_price,
                            trade_record.get("risk_per_share"), side)

    now_str = datetime.now(_EASTERN).strftime("%Y%m%dT%H%M%S")

    update_trade_management(trade_id, {
        "thesis_exit_signaled":    True,
        "thesis_exit_signaled_at": now_str,
        "thesis_exit_reason":      reason_code,
        "thesis_exit_r_at_signal": round(r_at_signal, 4) if r_at_signal is not None else None,
        "thesis_exit_pending_count": pending,
    }, symbol)

    # ── FC-2: live exit path ──────────────────────────────────────────────────
    live          = _exit_mode() == "live"
    exit_result   = None
    if live:
        exit_result = _execute_live_exit(
            trade_record, pm, symbol, reason_code, now_str,
        )
        live = bool(exit_result.get("exit_submitted"))   # fallback to shadow on failure

    event = {
        "event_id":          f"EV_{symbol}_{now_str}_{_RULE_ID}",
        "event_type":        "thesis_exit_live" if live else "thesis_exit_shadow",
        "rule_id":           _RULE_ID,
        "predicate_version": "thesis_monitor_v1",
        "symbol":            symbol,
        "timestamp":         now_str,
        "fired":             True,
        "fire_reason":       f"{reason_code}: {detail}",
        "opportunity":       True,
        "executed":          True,            # real position — counterfactual is its real outcome
        "trade_id":          trade_id,
        "intent_id":         trade_record.get("intent_id"),
        "r_at_signal":       round(r_at_signal, 4) if r_at_signal is not None else None,
        "price_at_signal":   current_price,
        "management_profile": profile,
        "context_digest":    dict(snapshot.get("shared_context", {}) or {}),
        "council_digest":    [],
        "resolution":        {"state": "pending"},
    }

    result = {
        "status":       "exit_submitted" if live else "would_exit",
        "would_exit":   True,
        "exit_live":    live,
        "reason":       reason_code,
        "detail":       detail,
        "r_at_signal":  event["r_at_signal"],
        "price":        current_price,
        "trade_id":     trade_id,
        "profile":      profile,
        "events":       [event],
    }
    if exit_result is not None:
        result["exit_order_id"]       = exit_result.get("exit_order_id")
        result["broker_stop_cancelled"] = exit_result.get("broker_stop_cancelled")
        if exit_result.get("warning"):
            result["warning"] = exit_result["warning"]
    return result


def _execute_live_exit(
    trade_record: dict,
    pm: dict,
    symbol: str,
    reason_code: str,
    now_str: str,
) -> dict:
    """
    Phase FC-2 — market-exit the full position on thesis death.

    Order of operations: cancel broker stop FIRST (stop + exit both live
    would double-fill into a reverse position), then submit the exit.
    The protection gap is sub-second (market exits fill immediately on
    paper) and strictly smaller than June 11's 13-minute stop gap.
    Never raises; failure returns exit_submitted=False (shadow fallback).
    """
    try:
        qty = pm.get("qty") or trade_record.get("filled_qty") or trade_record.get("qty")
        qty = int(float(qty))
        if qty <= 0:
            return {"exit_submitted": False, "warning": f"invalid exit qty {qty}"}

        side      = (pm.get("side") or "").lower()
        exit_side = "sell" if side == "long" else "buy"
        trade_id  = trade_record.get("trade_id")

        broker_stop_cancelled = False
        broker_stop_id = trade_record.get("broker_stop_order_id")
        if broker_stop_id:
            cancel_result = cancel_order(broker_stop_id)
            broker_stop_cancelled = bool(cancel_result.get("canceled", False))

        try:
            submission = submit_paper_exit_order(symbol, qty, exit_side)
        except RuntimeError as exc:
            return {
                "exit_submitted":        False,
                "broker_stop_cancelled": broker_stop_cancelled,
                "warning": f"thesis exit order failed (shadow fallback): {exc}",
            }

        order_id = submission.get("alpaca_order_id")
        mark_exit_submitted(
            trade_id             = trade_id,
            exit_order_id        = order_id,
            exit_price_reference = pm.get("current_price"),
            reason               = f"thesis_exit_{reason_code}",
            symbol               = symbol,
        )
        update_trade_management(trade_id, {
            "thesis_exit_executed":    True,
            "thesis_exit_executed_at": now_str,
            "thesis_exit_order_id":    order_id,
        }, symbol)

        return {
            "exit_submitted":        True,
            "exit_order_id":         order_id,
            "broker_stop_cancelled": broker_stop_cancelled,
        }
    except Exception as exc:  # noqa: BLE001
        return {"exit_submitted": False,
                "warning": f"live exit error (shadow fallback): {exc}"}
