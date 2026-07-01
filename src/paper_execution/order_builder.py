"""
Phase 2A — Paper Order Builder.
Phase 5E.6 — Buying-power-aware sizing cap.
Phase 5F.1 — Risk multiplier enforcement (governor tier + regime cap).
Phase FC-0B — Market-order execution doctrine (June 11).

Constructs an order request from trade_intent + price_level + risk config.
Does NOT submit. Does NOT call Alpaca. Pure construction logic.

EXECUTION DOCTRINE (FC-0B): decision time = execution time. Market order at
the price that exists when authority is granted — never a resting limit that
fills later in a context that may be dead (June 11: limit filled by the
rejection that falsified the thesis). ENTRY_ORDER_TYPE=limit exists ONLY as
emergency rollback to the pre-FC behavior.

Market-mode guards (the limit price used to do this job implicitly):
  - price_relation must be inside_zone/touching_zone — never chase a price
    that has left the planned entry zone
  - chase cap: live risk_per_share <= MAX_CHASE_RISK_MULT x zone risk

Risk sizing (Phase 5F.1):
  base_risk_budget        = RISK_PER_TRADE_DOLLARS
  risk_multiplier_applied = min(risk.risk_multiplier, regime_permissions.risk_multiplier_cap)
  effective_risk_budget   = base_risk_budget * risk_multiplier_applied
  risk_per_share          = abs(entry_reference - stop_reference)
  risk_qty                = floor(effective_risk_budget / risk_per_share)
  max_affordable          = floor(buying_power / entry_reference)
  qty                     = min(risk_qty, max_affordable)

Entry: market mode -> current price; limit mode (rollback) -> zone midpoint.
Stop:  invalidation_level from price_level (recorded in journal).
"""
import logging
import math
import os

from paper_execution.paper_broker import get_account as _get_account

_log = logging.getLogger(__name__)


_QUALITY_RANK = {
    "no_intent": 0, "poor": 1, "weak_watch": 2,
    "moderate_watch": 3, "strong_watch": 4, "elite_intent": 5,
}


def quality_rank(quality: str) -> int:
    return _QUALITY_RANK.get((quality or "no_intent").lower(), 0)


def _safe_multiplier(raw, default: float = 1.0) -> float:
    """
    Phase 5F.1 — Sanitize a risk multiplier value.
    Missing / non-numeric / NaN -> default. Out-of-range values clamp to [0.0, 1.0].
    """
    if raw is None:
        return default
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return default
    if math.isnan(val):
        return default
    return max(0.0, min(1.0, val))


def _preferred_candidate(snapshot: dict) -> dict:
    tb    = snapshot.get("toolbox", {})
    pref  = tb.get("preferred_tool", "") or ""
    cands = tb.get("tool_candidates", [])
    return next((c for c in cands if c.get("tool") == pref), {}) if cands else {}


def entry_order_type() -> str:
    """FC-0B — execution doctrine. 'market' is doctrine; 'limit' is rollback."""
    mode = os.getenv("ENTRY_ORDER_TYPE", "market").lower().strip()
    return mode if mode in ("market", "limit") else "market"


_IN_ZONE_RELATIONS = frozenset({"inside_zone", "touching_zone"})


def _max_chase_risk_mult() -> float:
    try:
        return float(os.getenv("MAX_CHASE_RISK_MULT", "2.0"))
    except (TypeError, ValueError):
        return 2.0


def build_order(snapshot: dict, symbol: str) -> dict:
    """
    Build an order request dict from snapshot state.
    FC-0B: MarketOrderRequest at current price (doctrine), or
    LimitOrderRequest at zone midpoint (ENTRY_ORDER_TYPE=limit rollback).

    Returns:
      {
        "valid": bool,
        "reject_reason": str (if not valid),
        "order_request": MarketOrderRequest | LimitOrderRequest (if valid),
        "order_type": "market"/"limit",
        "side": "buy"/"sell",
        "qty": int,
        "entry_reference": float,
        "decision_price": float | None,
        "stop_reference": float | None,
        "risk_per_share": float,
        "risk_dollars": float,
        "intent_type": str,
      }
    """
    from alpaca.trading.requests import LimitOrderRequest, MarketOrderRequest
    from alpaca.trading.enums   import OrderSide, TimeInForce

    # ── Phase 5F.1: effective risk budget = base × min(governor multiplier, regime cap)
    base_risk_budget = float(os.getenv("RISK_PER_TRADE_DOLLARS", "500"))

    governor_multiplier = _safe_multiplier(
        snapshot.get("risk", {}).get("risk_multiplier"), default=1.0
    )
    regime_cap = _safe_multiplier(
        (snapshot.get("regime_permissions") or {}).get("risk_multiplier_cap"),
        default=1.0,
    )
    risk_multiplier_applied = min(governor_multiplier, regime_cap)
    effective_risk_budget   = base_risk_budget * risk_multiplier_applied

    if effective_risk_budget <= 0:
        return {
            "valid": False,
            "reject_reason": (
                f"effective risk budget is 0 "
                f"(base={base_risk_budget:.2f} multiplier={risk_multiplier_applied})"
            ),
        }

    risk_budget = effective_risk_budget

    ti     = snapshot.get("trade_intent", {})
    intent_type = (ti.get("intent_type") or "none").lower()
    direction   = (ti.get("direction")   or "neutral").lower()

    if intent_type not in ("long", "short"):
        return {"valid": False, "reject_reason": f"intent_type '{intent_type}' is not long/short"}

    # Use price_level from the preferred candidate (has invalidation_level)
    pref_c = _preferred_candidate(snapshot)
    pl     = pref_c.get("price_level", {})
    ez     = ti.get("entry_zone") or {}

    order_type      = entry_order_type()
    stop_reference  = pl.get("invalidation_level")
    zone_midpoint   = pl.get("midpoint")
    if zone_midpoint is None:
        zone_midpoint = ez.get("midpoint")
    decision_price  = None

    if order_type == "market":
        # ── FC-0B: decision time = execution time ────────────────────────────
        current_price = ez.get("current_price")
        if current_price is None:
            return {
                "valid": False,
                "reject_reason": "market mode: no current_price in entry_zone",
            }
        relation = (ez.get("price_relation") or "unknown").lower()
        if relation not in _IN_ZONE_RELATIONS:
            return {
                "valid": False,
                "reject_reason": (
                    f"market mode: price_relation '{relation}' — "
                    "price has left the planned entry zone"
                ),
            }
        entry_reference = float(current_price)
        decision_price  = entry_reference
    else:
        # Rollback path — pre-FC limit-at-midpoint behavior, bit-for-bit.
        entry_reference = zone_midpoint
        if entry_reference is None:
            return {"valid": False, "reject_reason": "no entry reference available (midpoint is None)"}
        entry_reference = float(entry_reference)

    # Derive stop from invalidation_level; fallback: zone_low (long) or zone_high (short)
    if stop_reference is None:
        if intent_type == "long":
            stop_reference = ez.get("zone_low")
        else:
            stop_reference = ez.get("zone_high")
    if stop_reference is None:
        return {"valid": False, "reject_reason": "no stop reference available (invalidation_level is None)"}

    stop_reference  = float(stop_reference)
    risk_per_share  = abs(entry_reference - stop_reference)

    if risk_per_share <= 0:
        return {"valid": False, "reject_reason": f"risk_per_share <= 0 ({risk_per_share})"}

    # ── FC-0B: chase cap — market entries may not balloon risk vs the plan ────
    if order_type == "market" and zone_midpoint is not None:
        zone_risk = abs(float(zone_midpoint) - stop_reference)
        if zone_risk > 0 and risk_per_share > zone_risk * _max_chase_risk_mult():
            return {
                "valid": False,
                "reject_reason": (
                    f"market mode: chase cap — live risk/share {risk_per_share:.4f} "
                    f"exceeds {_max_chase_risk_mult()}x zone risk {zone_risk:.4f}"
                ),
            }

    risk_qty = math.floor(risk_budget / risk_per_share)
    if risk_qty <= 0:
        return {
            "valid": False,
            "reject_reason": (
                f"qty=0: risk_per_share={risk_per_share:.4f} exceeds "
                f"budget {risk_budget}"
            ),
        }

    # ── Phase 5E.6: buying-power cap ─────────────────────────────────────────
    acct = _get_account()
    if "error" in acct:
        return {
            "valid": False,
            "reject_reason": f"buying_power_lookup_failed: {acct['error']}",
        }

    buying_power  = float(acct.get("buying_power", 0))
    max_affordable = math.floor(buying_power / entry_reference) if entry_reference > 0 else 0

    if max_affordable <= 0:
        return {
            "valid": False,
            "reject_reason": (
                f"insufficient_buying_power: buying_power={buying_power:.2f} "
                f"entry={entry_reference:.2f} affordable_qty=0"
            ),
        }

    qty = min(risk_qty, max_affordable)

    # ── ADAPTIVE-7 — live defensive size overlay (DEFENSIVE_ONLY, downward-only) ──
    # The risk- and buying-power-capped qty above is the HARD ceiling (risk max).
    # The adaptive overlay may ONLY lower it: resolve_final_qty() is min()-capped to
    # this qty, so final_qty <= risk max always, never raises size, never invents.
    # Recorded forensically. Order-build logic is otherwise unchanged.
    from adaptive_learning.adaptive_live_authority import (
        resolve_final_qty, record_live_size_consumption,
    )
    _risk_max_qty = qty
    qty = resolve_final_qty(_risk_max_qty, snapshot)
    if qty != _risk_max_qty:
        record_live_size_consumption(snapshot, _risk_max_qty, qty)

    _log.info(
        "Sizing: risk_qty=%d affordable_qty=%d final_qty=%d "
        "buying_power=%.2f entry_price=%.2f",
        risk_qty, max_affordable, qty, buying_power, entry_reference,
    )

    side = OrderSide.BUY if intent_type == "long" else OrderSide.SELL

    if order_type == "market":
        order_request = MarketOrderRequest(
            symbol         = symbol,
            qty            = qty,
            side           = side,
            time_in_force  = TimeInForce.DAY,
        )
    else:
        order_request = LimitOrderRequest(
            symbol         = symbol,
            qty            = qty,
            side           = side,
            time_in_force  = TimeInForce.DAY,
            limit_price    = round(entry_reference, 2),
        )

    return {
        "valid":            True,
        "reject_reason":    "",
        "order_request":    order_request,
        "order_type":       order_type,
        "decision_price":   decision_price,
        "side":             "buy" if intent_type == "long" else "sell",
        "qty":              qty,
        "entry_reference":  entry_reference,
        "stop_reference":   stop_reference,
        "risk_per_share":   round(risk_per_share, 4),
        "risk_dollars":     round(risk_per_share * qty, 2),
        "intent_type":      intent_type,
        "risk_qty":         risk_qty,
        "affordable_qty":   max_affordable,
        "buying_power":     round(buying_power, 2),
        # Phase 5F.1 — risk multiplier enforcement audit trail
        "risk_multiplier_applied": round(risk_multiplier_applied, 4),
        "governor_multiplier":     round(governor_multiplier, 4),
        "regime_risk_cap":         round(regime_cap, 4),
        "base_risk_budget":        round(base_risk_budget, 2),
        "effective_risk_budget":   round(effective_risk_budget, 2),
    }


def meets_score_threshold(snapshot: dict) -> tuple[bool, str]:
    """
    Check intent_score against MIN_INTENT_GATED_SCORE and MIN_INTENT_QUALITY env vars.
    Returns (meets: bool, reason: str).
    """
    min_score   = int(os.getenv("MIN_INTENT_GATED_SCORE", "70"))
    min_quality = os.getenv("MIN_INTENT_QUALITY", "strong_watch").lower().strip()

    iscr        = snapshot.get("intent_score", {})
    gated_score = iscr.get("gated_score", 0)
    gated_qual  = (iscr.get("gated_quality") or "no_intent").lower()

    if gated_score < min_score:
        return False, f"gated_score {gated_score} < minimum {min_score}"
    if quality_rank(gated_qual) < quality_rank(min_quality):
        return False, f"gated_quality '{gated_qual}' below minimum '{min_quality}'"
    return True, "score thresholds met"
