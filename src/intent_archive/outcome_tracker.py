"""Phase 1X — Outcome Tracker. Pure outcome calculation for archived intents."""


def _preferred_candidate(snapshot: dict) -> dict:
    tb    = snapshot.get("toolbox", {})
    pref  = tb.get("preferred_tool", "") or ""
    cands = tb.get("tool_candidates", [])
    return next((c for c in cands if c.get("tool") == pref), {}) if cands else {}


def calculate_outcome(snapshot: dict, record: dict) -> dict:
    """
    Calculate outcome metrics for one archived record against the current snapshot.
    Returns mfe_candidate, mae_candidate, zone_touched_this_scan,
    trigger_ready_this_scan, current_price, distance_from_midpoint.
    """
    ez        = record.get("entry_zone") or {}
    midpoint  = ez.get("midpoint")
    zone_low  = ez.get("zone_low")
    zone_high = ez.get("zone_high")
    direction = (record.get("direction") or "bullish").lower()

    pref_c         = _preferred_candidate(snapshot)
    pl             = pref_c.get("price_level", {})
    tp             = pref_c.get("trigger_prep", {})
    current_price  = pl.get("current_price")
    price_relation = (pl.get("price_relation") or "").lower().replace(" ", "_")

    if current_price is None or midpoint is None:
        return {
            "mfe_candidate":          0.0,
            "mae_candidate":          0.0,
            "zone_touched_this_scan": False,
            "trigger_ready_this_scan": False,
            "current_price":          None,
            "distance_from_midpoint": None,
        }

    cp  = float(current_price)
    mid = float(midpoint)

    if direction == "bullish":
        mfe_candidate = max(0.0, round(cp - mid, 4))
        mae_candidate = max(0.0, round(mid - cp, 4))
    else:
        mfe_candidate = max(0.0, round(mid - cp, 4))
        mae_candidate = max(0.0, round(cp - mid, 4))

    zone_touched = price_relation in (
        "inside_zone", "touching_zone", "at_zone",
    )

    raw_trig      = (tp.get("raw_trigger_status") or "n/a").lower()
    trigger_ready = raw_trig in ("confirmed", "execution_ready")

    return {
        "mfe_candidate":          mfe_candidate,
        "mae_candidate":          mae_candidate,
        "zone_touched_this_scan": zone_touched,
        "trigger_ready_this_scan": trigger_ready,
        "current_price":          current_price,
        "distance_from_midpoint": round(abs(cp - mid), 4),
    }


def should_expire(record: dict, snapshot: dict, outcome: dict) -> tuple[bool, str]:
    """
    Check expiration conditions for an open record.
    Returns (should_expire: bool, reason: str).
    """
    bars = record.get("bars_since_creation", 0)

    if bars > 30:
        return True, "age_exceeded_30_bars"

    sl = snapshot.get("setup_lifecycle", {})
    if sl.get("invalidated"):
        return True, "setup_invalidated"

    pref_c   = _preferred_candidate(snapshot)
    tp       = pref_c.get("trigger_prep", {})
    raw_trig = (tp.get("raw_trigger_status") or "").lower()
    if raw_trig == "invalidated":
        return True, "trigger_invalidated"

    if bars >= 5 and not sl.get("active"):
        return True, "setup_gone"

    ez        = record.get("entry_zone") or {}
    zone_low  = ez.get("zone_low")
    zone_high = ez.get("zone_high")
    cur_price = outcome.get("current_price")
    dist      = outcome.get("distance_from_midpoint")
    direction = (record.get("direction") or "bullish").lower()

    if (
        zone_low  is not None and zone_high is not None
        and cur_price is not None and dist is not None
    ):
        zone_width = max(abs(float(zone_high) - float(zone_low)), 0.01)
        if direction == "bullish" and float(cur_price) < float(zone_low):
            if dist > 3 * zone_width:
                return True, "price_too_far_adverse"
        elif direction == "bearish" and float(cur_price) > float(zone_high):
            if dist > 3 * zone_width:
                return True, "price_too_far_adverse"

    return False, ""
