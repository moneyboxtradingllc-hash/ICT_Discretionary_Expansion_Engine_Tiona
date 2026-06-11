"""
Phase 5T.2 — Thesis-Failure Monitor (SHADOW ONLY).

Detects, while a position is open, that the thesis which justified the entry
is no longer valid — and logs what an exit WOULD have done. It never exits.

Thesis-death triggers (policy-gated by the trade's locked profile):
  lifecycle_invalidated — setup lifecycle declared the setup dead
  setup_invalidated     — state-transition engine invalidated the setup
  delivery_collapse     — (TREND profile only) measured delivery broke while
                          holding a continuation-thesis position

CONSTITUTION:
  - SHADOW ONLY. No exit orders. No stop changes. No coupling to execution.
  - Going live requires promoted evidence through the registry (TFX-001) —
    a human-reviewed code change, exactly like a 5H blocking rule.
  - One signal per trade (first thesis death wins); persisted to the journal
    so restarts do not re-signal.
  - Counterfactual: the ledger event carries r_at_signal; when the trade
    closes, 5H.3 resolution attaches realized_r. saved_r = r_at_signal -
    realized_r is computed at scoring time (positive = exit would have saved).
  - Never raises.
"""
import os
from datetime import datetime

import pytz

from paper_execution.management_policies import get_policy
from paper_execution.trade_journal import find_any_active_trade, update_trade_management

_EASTERN = pytz.timezone("America/New_York")

_RULE_ID = "TFX-001"


def _enabled() -> bool:
    return os.getenv("THESIS_MONITOR_ENABLED", "true").lower().strip() == "true"


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
    if policy.get("thesis_exit") not in ("shadow",):
        return {"status": "off_by_policy", "would_exit": False, "events": []}

    death = _detect_thesis_death(snapshot, profile)
    if death is None:
        return {"status": "thesis_intact", "would_exit": False, "events": []}

    reason_code, detail = death

    current_price = pm.get("current_price")
    side          = pm.get("side")
    entry_price   = pm.get("avg_entry_price")
    r_at_signal   = _calc_r(current_price, entry_price,
                            trade_record.get("risk_per_share"), side)

    now_str  = datetime.now(_EASTERN).strftime("%Y%m%dT%H%M%S")
    trade_id = trade_record.get("trade_id")

    update_trade_management(trade_id, {
        "thesis_exit_signaled":    True,
        "thesis_exit_signaled_at": now_str,
        "thesis_exit_reason":      reason_code,
        "thesis_exit_r_at_signal": round(r_at_signal, 4) if r_at_signal is not None else None,
    }, symbol)

    event = {
        "event_id":          f"EV_{symbol}_{now_str}_{_RULE_ID}",
        "event_type":        "thesis_exit_shadow",
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

    return {
        "status":       "would_exit",
        "would_exit":   True,
        "reason":       reason_code,
        "detail":       detail,
        "r_at_signal":  event["r_at_signal"],
        "price":        current_price,
        "trade_id":     trade_id,
        "profile":      profile,
        "events":       [event],
    }
