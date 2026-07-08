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


def _confirmation_candle_ok(snapshot: dict, direction: str, price_level: dict) -> bool:
    """
    Phase 5F.3 — Mechanical trigger confirmation.

    A trigger upgrades from confirmation_needed to confirmed when the last
    closed candle on the confirmation timeframe (1m, fallback 3m) is a
    directional candle closing beyond the zone midpoint in the intended
    direction — the mechanical equivalent of the plain-English confirmation
    conditions in _confirmation_list().

    Returns False on any missing data — confirmation is never assumed.
    """
    try:
        mid = price_level.get("midpoint")
        if mid is None:
            return False
        mid = float(mid)

        tfs = snapshot.get("timeframes", {}) or {}
        last = None
        for tf in ("1m", "3m"):
            lc = (tfs.get(tf) or {}).get("last_candle")
            if lc and lc.get("close") is not None and lc.get("open") is not None:
                last = lc
                break
        if last is None:
            return False

        o  = float(last["open"])
        cl = float(last["close"])

        if direction == "bullish":
            return cl > o and cl > mid
        return cl < o and cl < mid
    except (TypeError, ValueError):
        return False


def _confirmation_detail(snapshot: dict, direction: str, price_level: dict) -> dict:
    """TRIGGER-AUDIT (2026-07-08) — WHY confirmation did/didn't complete this scan.

    The 10-intent candle trial proved the confirmation RULE is legitimate (only
    1/10 intents had a discretionary confirmation the rule refused — below the
    overbuilt threshold). But 0/10 confirmed LIVE while 4/10 had a code-
    confirming candle in replay: the confirming candle (close beyond midpoint)
    closes past the zone edge, flipping price_relation to above/below_zone, and
    upstream setup/qualification/toolbox flicker vanishes the setup on the very
    scan the candle closes. This block makes that failure transparent and
    measurable — it changes NO behavior (the trigger verdict is unchanged); it
    only records the exact failed condition so the true owner (flicker + zone-
    exit geometry) is visible to the next session. Never raises.
    """
    detail = {"confirmation_candle_met": False, "failed_condition": None,
              "last_candle_tf": None}
    try:
        mid = price_level.get("midpoint")
        if mid is None:
            detail["failed_condition"] = "no_midpoint"
            return detail
        mid = float(mid)
        tfs = snapshot.get("timeframes", {}) or {}
        last = None
        for tf in ("1m", "3m"):
            lc = (tfs.get(tf) or {}).get("last_candle")
            if lc and lc.get("close") is not None and lc.get("open") is not None:
                last, detail["last_candle_tf"] = lc, tf
                break
        if last is None:
            detail["failed_condition"] = "no_candle_data"
            return detail
        o, cl = float(last["open"]), float(last["close"])
        directional = (cl > o) if direction == "bullish" else (cl < o)
        beyond_mid = (cl > mid) if direction == "bullish" else (cl < mid)
        if directional and beyond_mid:
            detail["confirmation_candle_met"] = True
        elif not directional:
            detail["failed_condition"] = "candle_not_directional"
        else:  # directional but not beyond midpoint (the wick-rejection axis)
            detail["failed_condition"] = "directional_but_not_beyond_midpoint"
        return detail
    except (TypeError, ValueError) as exc:
        detail["failed_condition"] = f"error:{exc}"
        return detail


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

    # Phase 5F.3 — upgrade to confirmed when the mechanical confirmation
    # candle condition is met. confirmation_needed and confirmed are now
    # distinct states; regime permission matrix decides which is required.
    if raw_ts == "confirmation_needed" and _confirmation_candle_ok(
        snapshot, direction, price_level
    ):
        raw_ts = "confirmed"

    # TRIGGER-AUDIT — observability only; does not change raw_ts/eff_ts above.
    # Recorded on every scan where a zone exists so the next session can measure
    # how often confirmation is missed and WHY (the trial proved the rule sound;
    # the loss is upstream flicker + zone-exit geometry, not rule strictness).
    conf_detail = _confirmation_detail(snapshot, direction, price_level)

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
        # TRIGGER-AUDIT (2026-07-08) — confirmation transparency (observe-only)
        "confirmation_candle_met":     conf_detail["confirmation_candle_met"],
        "confirmation_failed_condition": conf_detail["failed_condition"],
        "confirmation_candle_tf":      conf_detail["last_candle_tf"],
    }
