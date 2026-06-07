"""
Entry Trigger Prep — Phase 1L.
Reads price_level and readiness to determine trigger status and next-step confirmation.
No execution, no order routing, no broker connections.
"""


def _family(tool: str) -> str:
    for p in ("bullish_", "bearish_"):
        if tool.startswith(p):
            return tool[len(p):]
    return tool


# ── Trigger status ────────────────────────────────────────────────────────────

def _raw_trigger_status(price_level: dict, raw_status: str) -> str:
    """
    Score/price-based trigger status — no risk override applied.
    Answers: what would the trigger be if risk were cleared?
    """
    if price_level.get("level_type") == "no_zone":
        return "no_trigger"

    if price_level.get("invalidated"):
        return "invalidated"

    relation = price_level.get("price_relation", "unknown")

    if relation == "unknown":
        return "no_trigger"

    if relation in ("inside_zone", "touching_zone"):
        return "confirmation_needed" if raw_status == "actionable" else "retest_in_progress"

    return "waiting_for_retest"


def _effective_trigger_status(raw_ts: str, effective_tool_status: str) -> str:
    """
    Apply risk governor override.
    If risk is blocked and the trigger is not already no_trigger or invalidated,
    override to blocked_by_risk.
    """
    if effective_tool_status == "blocked_by_risk" and raw_ts not in ("no_trigger", "invalidated"):
        return "blocked_by_risk"
    return raw_ts


# ── Confirmation needed ───────────────────────────────────────────────────────

def _confirmation_list(fam: str, direction: str, price_level: dict) -> list:
    """Plain-English conditions required before this trigger would be execution-ready."""
    zl   = price_level.get("zone_low")
    zh   = price_level.get("zone_high")
    mid  = price_level.get("midpoint")
    rel  = price_level.get("price_relation", "unknown")
    name = fam.replace("_", " ")
    d    = direction
    opp  = "bearish" if d == "bullish" else "bullish"

    confirms = []

    # Universal first step: price must reach the zone
    if rel not in ("inside_zone", "touching_zone") and zl is not None:
        confirms.append(f"price must trade into the {name} zone ({zl}–{zh})")

    if fam in ("fvg", "ifvg", "opening_fvg"):
        close_side = "above" if d == "bullish" else "below"
        confirms.append(
            f"{d} rejection candle closes {close_side} zone midpoint ({mid})"
        )
        confirms.append(f"no {opp} displacement candle closing through zone")

    elif fam in ("order_block", "opening_order_block"):
        confirms.append(f"price reacts from {name} body — {d} candle initiates off zone")
        confirms.append(f"{d} expansion begins from zone in intended direction")

    elif fam == "breaker":
        confirms.append("price retests broken structure level from the correct side")
        confirms.append(f"{d} momentum candle closes away from zone in {d} direction")

    elif fam == "rejection_block":
        confirms.append(f"wick forms at zone boundary with {d} candle close")
        confirms.append("follow-through candle confirms directional move away from zone")

    elif fam in ("ote_retracement", "ote_after_reclaim"):
        if rel not in ("inside_zone", "touching_zone") and zl is not None:
            confirms.append(f"price pulls back into OTE zone ({zl}–{zh})")
        confirms.append(f"{d} reaction candle from OTE zone before expansion resumes")
        confirms.append(f"no close through OTE zone origin against {d} direction")

    elif fam == "mss_retest":
        confirms.append("price returns to MSS level without closing through it")
        confirms.append(f"{d} follow-through candle off MSS level confirms directional intent")

    elif fam == "range_break_retest":
        side = "above" if d == "bullish" else "below"
        confirms.append(f"price retests range boundary from {side}")
        confirms.append(f"{d} candle closes {side} the broken boundary — breakout confirmed")

    return confirms


# ── Invalidation conditions ───────────────────────────────────────────────────

def _invalidation_list(fam: str, direction: str, price_level: dict) -> list:
    """Plain-English conditions that would invalidate this trigger entirely."""
    inv_level = price_level.get("invalidation_level")
    d         = direction
    opp       = "bearish" if d == "bullish" else "bullish"
    side      = "below" if d == "bullish" else "above"

    invals = []

    if inv_level is not None:
        invals.append(
            f"close {side} {inv_level} — invalidation level violated"
        )

    invals.append(f"{opp} displacement candle closes through zone — zone violated")

    if fam in ("fvg", "ifvg"):
        invals.append("gap fully filled against intended direction — imbalance resolved")

    if fam in ("opening_fvg", "opening_order_block"):
        invals.append("session advances past ny_open without price returning to zone")

    if fam in ("ote_retracement", "ote_after_reclaim"):
        invals.append("swing origin violated — OTE zone no longer a valid retracement level")

    if fam == "mss_retest":
        invals.append("price closes through MSS level — structure shift invalidated")

    if fam == "range_break_retest":
        invals.append("price closes back inside the prior range — breakout failed")

    return invals


# ── Public entry point ────────────────────────────────────────────────────────

def build_trigger_prep(
    tool: str,
    snapshot: dict,
    price_level: dict,
    readiness: dict,
    raw_status: str,
    effective_status: str,
) -> dict:
    """
    Phase 1L — Entry Trigger Prep.
    Determines trigger status and confirmation requirements from price_level and readiness.
    Never places a trade or routes an order.
    execution_ready = True only when all conditions simultaneously hold.
    """
    risk          = snapshot.get("risk", {})
    trade_allowed = risk.get("trade_allowed", False)
    fam           = _family(tool)
    direction     = "bullish" if tool.startswith("bullish_") else "bearish"

    relation    = price_level.get("price_relation", "unknown")
    invalidated = price_level.get("invalidated", False)
    no_zone     = price_level.get("level_type") == "no_zone"
    prereqs_ok  = not readiness.get("prerequisites_missing")

    raw_ts = _raw_trigger_status(price_level, raw_status)
    eff_ts = _effective_trigger_status(raw_ts, effective_status)

    # execution_ready: every condition must be true simultaneously
    execution_ready = (
        raw_status == "actionable"
        and effective_status == "actionable"    # risk governor permits
        and trade_allowed                        # governor flag
        and relation in ("inside_zone", "touching_zone")
        and not invalidated
        and not no_zone
        and prereqs_ok                           # no missing prerequisites
    )

    return {
        "raw_trigger_status":      raw_ts,
        "effective_trigger_status": eff_ts,
        "confirmation_needed":     _confirmation_list(fam, direction, price_level),
        "invalidation_conditions": _invalidation_list(fam, direction, price_level),
        "execution_ready":         execution_ready,
    }
