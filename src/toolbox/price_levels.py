"""
Price Level Detector — Phase 1L.
Identifies the price zone connected to each tool candidate using available candle data.
No execution, no order routing, no indicator recalculation.
All inputs are pre-computed snapshot dicts (timeframes, structure, liquidity).
"""

_TFS = ["15m", "5m", "3m", "1m"]

# Preferred source timeframe per tool family (first TF with usable candles wins)
_FAMILY_TF_PRIORITY: dict[str, list] = {
    "fvg":                 ["5m",  "15m", "3m",  "1m"],
    "ifvg":                ["3m",  "1m",  "5m",  "15m"],
    "order_block":         ["15m", "5m",  "3m",  "1m"],
    "breaker":             ["5m",  "15m", "3m",  "1m"],
    "rejection_block":     ["15m", "5m",  "3m",  "1m"],
    "ote_retracement":     ["15m", "5m",  "3m",  "1m"],
    "mss_retest":          ["5m",  "3m",  "1m",  "15m"],
    "ote_after_reclaim":   ["3m",  "1m",  "5m",  "15m"],
    "opening_fvg":         ["1m",  "3m",  "5m",  "15m"],
    "opening_order_block": ["1m",  "3m",  "5m",  "15m"],
    "range_break_retest":  ["15m", "5m",  "3m",  "1m"],
}

# Fibonacci OTE pocket bounds
_OTE_LOW_PCT  = 0.62
_OTE_HIGH_PCT = 0.79

# Price within this many points of a zone edge is classified "touching_zone"
_TOUCH_TOLERANCE = 1.5


# ── Helpers ───────────────────────────────────────────────────────────────────

def _family(tool: str) -> str:
    for p in ("bullish_", "bearish_"):
        if tool.startswith(p):
            return tool[len(p):]
    return tool


def _current_price(snapshot: dict) -> float | None:
    """Return most granular available last close price."""
    tfs = snapshot.get("timeframes", {})
    for tf in ["1m", "3m", "5m", "15m"]:
        lc = tfs.get(tf, {}).get("last_candle")
        if lc and lc.get("close") is not None:
            return round(float(lc["close"]), 2)
    return None


def _avg_range(candles: list) -> float:
    """Average candle range over recent candles — used as a zone tolerance proxy."""
    vals = [c.get("range", 0) for c in candles[-5:] if c.get("range", 0) > 0]
    return round(sum(vals) / len(vals), 4) if vals else 2.0


def _price_relation(current: float | None, zl: float, zh: float) -> str:
    if current is None:
        return "unknown"
    if zl <= current <= zh:
        return "inside_zone"
    if zl - _TOUCH_TOLERANCE <= current < zl:
        return "touching_zone"
    if zh < current <= zh + _TOUCH_TOLERANCE:
        return "touching_zone"
    return "below_zone" if current < zl else "above_zone"


def _distance(current: float | None, zl: float, zh: float) -> float | None:
    if current is None:
        return None
    if zl <= current <= zh:
        return 0.0
    return round(zl - current if current < zl else current - zh, 2)


def _is_invalidated(direction: str, current: float | None, inv_level: float | None) -> bool:
    if current is None or inv_level is None:
        return False
    return current < inv_level if direction == "bullish" else current > inv_level


def _make_zone(level_type: str, direction: str, zl: float, zh: float,
               inv_level: float | None, current: float | None, source_tf: str) -> dict:
    zl = round(zl, 2)
    zh = round(zh, 2)
    if zl > zh:
        zl, zh = zh, zl  # guard inverted zone

    relation  = _price_relation(current, zl, zh)
    dist      = _distance(current, zl, zh)
    entered   = relation in ("inside_zone", "touching_zone")
    inval     = _is_invalidated(direction, current, inv_level)

    return {
        "level_type":         level_type,
        "direction":          direction,
        "zone_low":           zl,
        "zone_high":          zh,
        "midpoint":           round((zl + zh) / 2, 3),
        "current_price":      current,
        "distance_to_zone":   dist,
        "price_relation":     relation,
        "entered_zone":       entered,
        "invalidated":        inval,
        "invalidation_level": round(inv_level, 2) if inv_level is not None else None,
        "source_tf":          source_tf,
    }


def _no_zone(direction: str, current: float | None) -> dict:
    return {
        "level_type":         "no_zone",
        "direction":          direction,
        "zone_low":           None,
        "zone_high":          None,
        "midpoint":           None,
        "current_price":      current,
        "distance_to_zone":   None,
        "price_relation":     "unknown",
        "entered_zone":       False,
        "invalidated":        False,
        "invalidation_level": None,
        "source_tf":          None,
    }


# ── Zone finders ──────────────────────────────────────────────────────────────

def _find_fvg(candles: list, direction: str) -> tuple | None:
    """
    Scan recent candles for a 3-candle imbalance gap.
    Bullish FVG: candle[i].high < candle[i+2].low
    Bearish FVG: candle[i].low  > candle[i+2].high
    Returns (zone_low, zone_high) of the most recent gap, or None.
    """
    if len(candles) < 3:
        return None
    for i in range(len(candles) - 3, -1, -1):
        c1, c3 = candles[i], candles[i + 2]
        if direction == "bullish" and c1["high"] < c3["low"]:
            return c1["high"], c3["low"]
        if direction == "bearish" and c1["low"] > c3["high"]:
            return c3["high"], c1["low"]
    return None


def _find_ob(candles: list, direction: str) -> tuple | None:
    """
    Most recent opposite-direction candle body as order block.
    Returns (zone_low, zone_high, invalidation_level) or None.
    Invalidation = the whole candle's extreme (low for bullish OB, high for bearish OB).
    """
    if len(candles) < 2:
        return None
    opp = "bearish" if direction == "bullish" else "bullish"
    for c in reversed(candles[:-1]):
        if c["direction"] == opp:
            body_lo = round(min(c["open"], c["close"]), 2)
            body_hi = round(max(c["open"], c["close"]), 2)
            if body_hi <= body_lo:
                continue  # skip neutral/doji candles
            inv = c["low"] if direction == "bullish" else c["high"]
            return body_lo, body_hi, inv
    return None


def _find_ote(struct: dict, direction: str) -> tuple | None:
    """
    OTE retracement zone from structure swing high/low.
    Bullish: 62–79% pullback from swing high.
    Bearish: 62–79% bounce from swing low.
    Returns (zone_low, zone_high, invalidation_level) or None.
    """
    sh = struct.get("last_swing_high")
    sl = struct.get("last_swing_low")
    if sh is None or sl is None:
        return None
    rng = sh - sl
    if rng <= 0:
        return None
    if direction == "bullish":
        return sh - rng * _OTE_HIGH_PCT, sh - rng * _OTE_LOW_PCT, sl
    return sl + rng * _OTE_LOW_PCT, sl + rng * _OTE_HIGH_PCT, sh


def _find_swing_zone(struct: dict, candles: list, direction: str) -> tuple | None:
    """
    Small zone around the swept swing level.
    Used as fallback for breaker and primary for range_break_retest.
    Bullish → zone around last_swing_LOW (the swept low).
    Bearish → zone around last_swing_HIGH (the swept high).
    Returns (zone_low, zone_high, invalidation_level) or None.
    """
    sh  = struct.get("last_swing_high")
    sl  = struct.get("last_swing_low")
    tol = _avg_range(candles) * 0.35

    if direction == "bullish" and sl is not None:
        return sl - tol, sl + tol, sl - tol * 2.5
    if direction == "bearish" and sh is not None:
        return sh - tol, sh + tol, sh + tol * 2.5
    return None


def _find_breaker_zone(candles: list, struct: dict, direction: str) -> tuple | None:
    """
    Breaker zone: body of the reversal/failure candle (same direction as intended trade).
    For bullish breaker: most recent bullish candle body (the reversal after the sweep).
    For bearish breaker: most recent bearish candle body.
    Falls back to swept swing level zone if no same-direction candle found.
    Returns (zone_low, zone_high, invalidation_level) or None.
    """
    # Primary: same-direction reversal candle body (the failure/reclaim candle)
    for c in reversed(candles[:-1]):
        if c["direction"] == direction:
            body_lo = round(min(c["open"], c["close"]), 2)
            body_hi = round(max(c["open"], c["close"]), 2)
            if body_hi <= body_lo:
                continue
            inv = c["low"] if direction == "bullish" else c["high"]
            return body_lo, body_hi, inv
    # Fallback: swept swing level zone
    return _find_swing_zone(struct, candles, direction)


def _find_mss_level_zone(struct: dict, candles: list, direction: str) -> tuple | None:
    """
    MSS Retest zone: built around the BROKEN structure level.
    Bullish: price broke ABOVE last_swing_HIGH → retest that broken high from above.
    Bearish: price broke BELOW last_swing_LOW  → retest that broken low from below.
    Distinct from breaker: uses structural breakout level, not a candle body.
    Returns (zone_low, zone_high, invalidation_level) or None.
    """
    sh  = struct.get("last_swing_high")
    sl  = struct.get("last_swing_low")
    tol = _avg_range(candles) * 0.35

    if direction == "bullish" and sh is not None:
        # Bullish BOS broke above swing_high — retest that level as new support
        return sh - tol, sh + tol, sh - tol * 2.5
    if direction == "bearish" and sl is not None:
        # Bearish BOS broke below swing_low — retest that level as new resistance
        return sl - tol, sl + tol, sl + tol * 2.5
    return None


def _find_rejection_zone(struct: dict, candles: list, direction: str) -> tuple | None:
    """
    Rejection block zone built from the largest-wick candle in recent data.
    Zone = body of that candle; invalidation = wick extreme + small buffer.
    Returns (zone_low, zone_high, invalidation_level) or None.
    """
    recent = candles[-5:] if candles else []
    if not recent:
        return None

    if direction == "bullish":
        rej    = max(recent, key=lambda c: c.get("lower_wick", 0))
        body_lo = round(min(rej["open"], rej["close"]), 2)
        body_hi = round(max(rej["open"], rej["close"]), 2)
        inv     = round(rej["low"] - _avg_range(recent) * 0.1, 2)
    else:
        rej    = max(recent, key=lambda c: c.get("upper_wick", 0))
        body_lo = round(min(rej["open"], rej["close"]), 2)
        body_hi = round(max(rej["open"], rej["close"]), 2)
        inv     = round(rej["high"] + _avg_range(recent) * 0.1, 2)

    if body_hi <= body_lo:
        return None
    return body_lo, body_hi, inv


# ── Zone dispatcher ───────────────────────────────────────────────────────────

def _build_zone_for_family(
    fam: str, direction: str,
    struct: dict, liq: dict, candles: list,
    source_tf: str, current: float | None
) -> dict:

    if fam in ("fvg", "ifvg", "opening_fvg"):
        result = _find_fvg(candles, direction)
        if result:
            zl, zh = result
            inv = zl if direction == "bullish" else zh
            return _make_zone(f"{fam}_zone", direction, zl, zh, inv, current, source_tf)

    if fam in ("order_block", "opening_order_block"):
        result = _find_ob(candles, direction)
        if result:
            zl, zh, inv = result
            return _make_zone(f"{fam}_zone", direction, zl, zh, inv, current, source_tf)

    if fam == "breaker":
        result = _find_breaker_zone(candles, struct, direction)
        if result:
            zl, zh, inv = result
            return _make_zone("breaker_zone", direction, zl, zh, inv, current, source_tf)

    if fam == "rejection_block":
        result = _find_rejection_zone(struct, candles, direction)
        if result:
            zl, zh, inv = result
            return _make_zone("rejection_block_zone", direction, zl, zh, inv, current, source_tf)

    if fam in ("ote_retracement", "ote_after_reclaim"):
        result = _find_ote(struct, direction)
        if result:
            zl, zh, inv = result
            return _make_zone("ote_zone", direction, zl, zh, inv, current, source_tf)

    if fam == "mss_retest":
        result = _find_mss_level_zone(struct, candles, direction)
        if result:
            zl, zh, inv = result
            return _make_zone("mss_retest_zone", direction, zl, zh, inv, current, source_tf)

    if fam == "range_break_retest":
        buy_side  = liq.get("nearest_buy_side_liquidity")
        sell_side = liq.get("nearest_sell_side_liquidity")
        ref       = buy_side if direction == "bullish" else sell_side
        if ref is not None:
            tol = _avg_range(candles) * 0.35
            zl  = ref - tol
            zh  = ref + tol
            inv = (ref - tol * 2.5) if direction == "bullish" else (ref + tol * 2.5)
            return _make_zone("range_break_retest_zone", direction, zl, zh, inv, current, source_tf)
        # Fallback to swing zone if no liquidity level available
        result = _find_swing_zone(struct, candles, direction)
        if result:
            zl, zh, inv = result
            return _make_zone("range_break_retest_zone", direction, zl, zh, inv, current, source_tf)

    return _no_zone(direction, current)


# ── Public entry point ────────────────────────────────────────────────────────

def build_price_level(tool: str, snapshot: dict) -> dict:
    """
    Phase 1L — Price Level Detector.
    Returns the price zone and current-price relationship for the given tool.
    """
    fam       = _family(tool)
    direction = "bullish" if tool.startswith("bullish_") else "bearish"
    current   = _current_price(snapshot)
    session   = snapshot.get("session", "")

    # Opening tools are session-gated — no zone outside ny_open
    if fam in ("opening_fvg", "opening_order_block") and session != "ny_open":
        return _no_zone(direction, current)

    tfs        = snapshot.get("timeframes", {})
    struct_all = snapshot.get("structure",  {})
    liq_all    = snapshot.get("liquidity",  {})

    for tf in _FAMILY_TF_PRIORITY.get(fam, ["15m", "5m", "3m", "1m"]):
        candles = tfs.get(tf, {}).get("recent_candles", [])
        if not candles:
            continue
        struct = struct_all.get(tf, {})
        liq    = liq_all.get(tf, {})
        result = _build_zone_for_family(fam, direction, struct, liq, candles, tf, current)
        if result.get("level_type") != "no_zone":
            return result

    return _no_zone(direction, current)
