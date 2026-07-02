"""
Phase 2A — Paper Execution Engine.

Orchestrates the full paper trade attempt:
  1. Check env flags (EXECUTION_ENABLED, PAPER_TRADING_ONLY, ALLOW_PAPER_ORDERS).
  2. Validate execution_gate.allow_execution.
  3. Validate trade_intent and intent_score thresholds.
  4. Build limit order.
  5. Run position_guard checks.
  6. Submit paper order (if all pass).
  7. Record in trade_journal.
  8. Return compact summary.

PAPER TRADING ONLY. No live money. No live endpoint. No execution unless
EXECUTION_ENABLED=true AND PAPER_TRADING_ONLY=true AND ALLOW_PAPER_ORDERS=true.
"""
import os
from datetime import datetime
import pytz

from paper_execution.paper_broker  import is_paper_account_safe, submit_paper_order
from paper_execution.order_builder import build_order, meets_score_threshold
from paper_execution.position_guard import check_all as guard_check_all
from paper_execution.trade_journal  import (
    append_trade, make_record, count_submitted_today, total_risk_today,
)
from ai_feedback.ai_feedback_builder import build_ai_feedback_from_snapshot

_EASTERN = pytz.timezone("America/New_York")


def _make_trade_id(symbol: str) -> str:
    return f"PT_{symbol}_{datetime.now(_EASTERN).strftime('%Y%m%dT%H%M%S')}"


def _regime_from_snapshot(snapshot: dict) -> dict:
    """Extract regime fields for make_record() from snapshot['market_regime']."""
    r = snapshot.get("market_regime") or {}
    return {
        "market_regime_label":  r.get("regime_label",    "unknown"),
        "market_regime_family": r.get("regime_family",   "unknown"),
        "regime_confidence":    r.get("confidence",      0),
        "volatility_state":     r.get("volatility_state", "unknown"),
        "expansion_state":      r.get("expansion_state",  "unknown"),
    }


def _snapshot_summary(snapshot: dict) -> dict:
    """Compact snapshot fields for journal record."""
    ti   = snapshot.get("trade_intent", {})
    iscr = snapshot.get("intent_score", {})
    eg   = snapshot.get("execution_gate", {})
    da   = snapshot.get("decision_authority", {})
    pb   = snapshot.get("playbook", {})
    tb   = snapshot.get("toolbox", {})
    return {
        "decision":      da.get("decision"),
        "intent_type":   ti.get("intent_type"),
        "gated_score":   iscr.get("gated_score"),
        "gated_quality": iscr.get("gated_quality"),
        "gate_status":   eg.get("gate_status"),
        "playbook":      pb.get("selected_playbook"),
        "session":       snapshot.get("session"),
        # DECON-2 — capture the executed tool so the performance tables' tool
        # dimension is written under the real tool key instead of "unknown"
        # (the write/read key mismatch found in the constitutional audit).
        "tool":          tb.get("preferred_tool"),
    }


def _disabled_result(reason: str) -> dict:
    return {
        "status":            "disabled",
        "reason":            reason,
        "order_summary":     "",
        "alpaca_order_id":   None,
        "trade_id":          None,
        "allow_paper_orders": False,
        "execution_enabled": False,
        "position_guard":    {},
    }


def _skipped_result(reason: str, guard: dict | None = None) -> dict:
    return {
        "status":            "skipped",
        "reason":            reason,
        "order_summary":     "",
        "alpaca_order_id":   None,
        "trade_id":          None,
        "allow_paper_orders": True,
        "execution_enabled": True,
        "position_guard":    guard or {},
    }


def attempt_paper_execution(snapshot: dict, symbol: str) -> dict:
    """
    Phase 2A — attempt a paper trade.

    Returns a compact dict that is stored as snapshot['paper_execution'].
    Never raises — all errors result in a skipped/disabled status.
    """
    try:
        return _attempt(snapshot, symbol)
    except Exception as exc:
        return _skipped_result(f"unexpected error: {exc}")


def _attempt(snapshot: dict, symbol: str) -> dict:

    # ── Layer 1: env flag checks (no network, no side effects) ────────────────
    exec_enabled  = os.getenv("EXECUTION_ENABLED",  "false").lower().strip() == "true"
    paper_only    = os.getenv("PAPER_TRADING_ONLY", "false").lower().strip() == "true"
    allow_orders  = os.getenv("ALLOW_PAPER_ORDERS", "false").lower().strip() == "true"

    if not exec_enabled:
        return _disabled_result("EXECUTION_ENABLED=false")
    if not paper_only:
        return _disabled_result("PAPER_TRADING_ONLY is not 'true'")
    if not allow_orders:
        return _disabled_result("ALLOW_PAPER_ORDERS=false")

    # ── Layer 2: endpoint safety ──────────────────────────────────────────────
    ep_safe, ep_reason = is_paper_account_safe()
    if not ep_safe:
        return _skipped_result(f"paper endpoint check failed: {ep_reason}")

    # ── Layer 3: execution gate ───────────────────────────────────────────────
    eg = snapshot.get("execution_gate", {})
    if not eg.get("allow_execution", False):
        gate_status = eg.get("gate_status", "locked")
        return _skipped_result(f"execution gate {gate_status}")
    if not eg.get("would_authorize_if_enabled", False):
        return _skipped_result("execution gate: would_authorize_if_enabled=false")

    # ── Layer 4: decision authority ───────────────────────────────────────────
    # Phase 5F.4: legacy 'trade_authorized_false' normalizes to 'ready_for_execution'
    from decision_authority.decision_engine import normalize_decision
    da       = snapshot.get("decision_authority", {})
    decision = normalize_decision(da.get("decision"))
    if decision != "ready_for_execution":
        return _skipped_result(f"decision authority: {decision} (requires ready_for_execution)")

    # ── Layer 5: trade intent ─────────────────────────────────────────────────
    ti          = snapshot.get("trade_intent", {})
    intent_type = (ti.get("intent_type") or "none").lower()
    intent_id   = snapshot.get("intent_archive", {}).get("active_intent_id")

    if not ti.get("intent_created", False):
        return _skipped_result("intent_created=false")
    if intent_type not in ("long", "short"):
        return _skipped_result(f"intent_type '{intent_type}' not actionable")

    # ── Layer 6: trigger readiness ────────────────────────────────────────────
    tb     = snapshot.get("toolbox", {})
    pref   = tb.get("preferred_tool") or ""
    cands  = tb.get("tool_candidates", [])
    pref_c = next((c for c in cands if c.get("tool") == pref), {})
    tp     = pref_c.get("trigger_prep", {})
    if not tp.get("execution_ready", False):
        return _skipped_result("trigger execution_ready=false")

    # ── Layer 7: intent score thresholds ──────────────────────────────────────
    score_ok, score_reason = meets_score_threshold(snapshot)
    if not score_ok:
        return _skipped_result(f"intent score: {score_reason}")

    # ── Layer 8: build order request ─────────────────────────────────────────
    order_result = build_order(snapshot, symbol)
    if not order_result["valid"]:
        return _skipped_result(f"order build failed: {order_result['reject_reason']}")

    # ── Layer 9: position guard (may call Alpaca for open positions) ──────────
    guard = guard_check_all(snapshot, symbol, intent_id)
    if not guard["allowed"]:
        trade_id = _make_trade_id(symbol)
        record = make_record(
            trade_id        = trade_id,
            symbol          = symbol,
            intent_id       = intent_id,
            intent_type     = intent_type,
            side            = order_result["side"],
            qty             = order_result["qty"],
            entry_reference = order_result["entry_reference"],
            stop_reference  = order_result["stop_reference"],
            risk_per_share  = order_result["risk_per_share"],
            risk_dollars    = order_result["risk_dollars"],
            order_status    = "rejected",
            alpaca_order_id = None,
            reason          = guard["reason"],
            snapshot_summary = _snapshot_summary(snapshot),
            **_regime_from_snapshot(snapshot),
            ai_feedback     = build_ai_feedback_from_snapshot(snapshot),
            # Phase 5F.1 — risk multiplier audit trail
            risk_multiplier_applied = order_result.get("risk_multiplier_applied", 1.0),
            base_risk_budget        = order_result.get("base_risk_budget", 0.0),
            effective_risk_budget   = order_result.get("effective_risk_budget", 0.0),
            # Phase FC-0B — market-order doctrine audit trail
            execution_mode          = order_result.get("order_type", "limit"),
            decision_price          = order_result.get("decision_price"),
            # Phase NA-1 — narrative authority at entry
            narrative               = snapshot.get("narrative_authority"),
        )
        append_trade(record, symbol)
        return _skipped_result(f"position guard: {guard['reason']}", guard)

    # ── Layer 10: submit paper order ──────────────────────────────────────────
    trade_id = _make_trade_id(symbol)
    broker_stop_notes = ""

    # Phase 4B: attempt bracket/OTO if mode configured
    # FC-0B: bracket/OTO requires a limit entry — market doctrine uses
    # after_fill protective stops instead.
    broker_stop_enabled = os.getenv("BROKER_STOP_ENABLED", "false").lower().strip() == "true"
    broker_stop_mode    = os.getenv("BROKER_STOP_MODE", "after_fill").lower().strip()
    order_to_submit     = order_result["order_request"]
    order_type          = order_result.get("order_type", "limit")

    if (broker_stop_enabled and broker_stop_mode == "bracket_if_supported"
            and order_type == "limit"):
        from paper_execution.bracket_builder import build_bracket_order
        bracket = build_bracket_order(
            symbol      = symbol,
            side        = order_result["side"],
            qty         = order_result["qty"],
            limit_price = order_result["entry_reference"],
            stop_price  = order_result["stop_reference"],
        )
        if bracket["supported"]:
            order_to_submit   = bracket["order_request"]
            broker_stop_notes = "bracket_order_used"
        else:
            broker_stop_notes = f"bracket_fallback: {bracket.get('reason','unsupported')}"

    try:
        submission = submit_paper_order(order_to_submit)
        alpaca_id  = submission.get("alpaca_order_id")
        order_status = "submitted"
        side_str = order_result["side"]
        qty      = order_result["qty"]
        entry    = round(order_result["entry_reference"], 2)
        order_summary = f"{side_str} {qty} {symbol} {order_type} {entry}"
        reason = "paper order submitted successfully"
        if broker_stop_notes:
            reason += f" ({broker_stop_notes})"
    except RuntimeError as exc:
        alpaca_id    = None
        order_status = "rejected"
        order_summary = ""
        reason = str(exc)

    # ── Layer 11: journal ─────────────────────────────────────────────────────
    record = make_record(
        trade_id        = trade_id,
        symbol          = symbol,
        intent_id       = intent_id,
        intent_type     = intent_type,
        side            = order_result["side"],
        qty             = order_result["qty"],
        entry_reference = order_result["entry_reference"],
        stop_reference  = order_result["stop_reference"],
        risk_per_share  = order_result["risk_per_share"],
        risk_dollars    = order_result["risk_dollars"],
        order_status    = order_status,
        alpaca_order_id = alpaca_id,
        reason          = reason,
        snapshot_summary = _snapshot_summary(snapshot),
        **_regime_from_snapshot(snapshot),
        ai_feedback     = build_ai_feedback_from_snapshot(snapshot),
        # Phase 5F.1 — risk multiplier audit trail
        risk_multiplier_applied = order_result.get("risk_multiplier_applied", 1.0),
        base_risk_budget        = order_result.get("base_risk_budget", 0.0),
        effective_risk_budget   = order_result.get("effective_risk_budget", 0.0),
    )
    append_trade(record, symbol)

    return {
        "status":            order_status,
        "reason":            reason,
        "order_summary":     order_summary,
        "alpaca_order_id":   alpaca_id,
        "trade_id":          trade_id,
        "allow_paper_orders": True,
        "execution_enabled": True,
        "position_guard":    guard,
        "qty":               order_result["qty"],
        "entry_reference":   order_result["entry_reference"],
        "stop_reference":    order_result["stop_reference"],
        "risk_per_share":    order_result["risk_per_share"],
        "risk_dollars":      order_result["risk_dollars"],
    }
