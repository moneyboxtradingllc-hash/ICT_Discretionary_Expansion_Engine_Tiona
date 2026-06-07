"""
Phase 2A — Paper Order Builder.

Constructs a LIMIT order request from trade_intent + price_level + risk config.
Does NOT submit. Does NOT call Alpaca. Pure construction logic.

Risk sizing:
  risk_per_share = abs(entry_reference - stop_reference)
  qty = floor(RISK_PER_TRADE_DOLLARS / risk_per_share)

Entry: zone midpoint (limit order).
Stop:  invalidation_level from price_level (recorded in journal; no bracket in Phase 2A).
"""
import os
import math


_QUALITY_RANK = {
    "no_intent": 0, "poor": 1, "weak_watch": 2,
    "moderate_watch": 3, "strong_watch": 4, "elite_intent": 5,
}


def quality_rank(quality: str) -> int:
    return _QUALITY_RANK.get((quality or "no_intent").lower(), 0)


def _preferred_candidate(snapshot: dict) -> dict:
    tb    = snapshot.get("toolbox", {})
    pref  = tb.get("preferred_tool", "") or ""
    cands = tb.get("tool_candidates", [])
    return next((c for c in cands if c.get("tool") == pref), {}) if cands else {}


def build_order(snapshot: dict, symbol: str) -> dict:
    """
    Build a LIMIT order request dict from snapshot state.

    Returns:
      {
        "valid": bool,
        "reject_reason": str (if not valid),
        "order_request": LimitOrderRequest (if valid),
        "side": "buy"/"sell",
        "qty": int,
        "entry_reference": float,
        "stop_reference": float | None,
        "risk_per_share": float,
        "risk_dollars": float,
        "intent_type": str,
      }
    """
    from alpaca.trading.requests import LimitOrderRequest
    from alpaca.trading.enums   import OrderSide, TimeInForce

    risk_budget = float(os.getenv("RISK_PER_TRADE_DOLLARS", "500"))

    ti     = snapshot.get("trade_intent", {})
    intent_type = (ti.get("intent_type") or "none").lower()
    direction   = (ti.get("direction")   or "neutral").lower()

    if intent_type not in ("long", "short"):
        return {"valid": False, "reject_reason": f"intent_type '{intent_type}' is not long/short"}

    # Use price_level from the preferred candidate (has invalidation_level)
    pref_c = _preferred_candidate(snapshot)
    pl     = pref_c.get("price_level", {})

    entry_reference = pl.get("midpoint")
    stop_reference  = pl.get("invalidation_level")

    # Fallback: use entry_zone from trade_intent if no midpoint in price_level
    if entry_reference is None:
        ez = ti.get("entry_zone") or {}
        entry_reference = ez.get("midpoint")

    if entry_reference is None:
        return {"valid": False, "reject_reason": "no entry reference available (midpoint is None)"}

    entry_reference = float(entry_reference)

    # Derive stop from invalidation_level; fallback: zone_low (long) or zone_high (short)
    if stop_reference is None:
        ez = ti.get("entry_zone") or {}
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

    qty = math.floor(risk_budget / risk_per_share)
    if qty <= 0:
        return {
            "valid": False,
            "reject_reason": (
                f"qty=0: risk_per_share={risk_per_share:.4f} exceeds "
                f"budget {risk_budget}"
            ),
        }

    side = OrderSide.BUY if intent_type == "long" else OrderSide.SELL

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
        "side":             "buy" if intent_type == "long" else "sell",
        "qty":              qty,
        "entry_reference":  entry_reference,
        "stop_reference":   stop_reference,
        "risk_per_share":   round(risk_per_share, 4),
        "risk_dollars":     round(risk_per_share * qty, 2),
        "intent_type":      intent_type,
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
