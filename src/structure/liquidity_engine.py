from structure.structure_engine import find_swings

MIN_CANDLES = 4


def analyze_liquidity(candles: list) -> dict:
    empty = {
        "sweep_detected": False,
        "sweep_direction": None,
        "reclaim_detected": False,
        "failed_breakout": False,
        "nearest_buy_side_liquidity": None,
        "nearest_sell_side_liquidity": None,
    }

    if len(candles) < MIN_CANDLES:
        return empty

    highs, lows = find_swings(candles)

    last = candles[-1]
    last_close = last["close"]
    last_high = last["high"]
    last_low = last["low"]

    sweep_detected = False
    sweep_direction = None
    reclaim_detected = False
    failed_breakout = False

    # Which swing is price actually raiding?
    #
    # This used to reference highs[-1] / lows[-1] — the chronologically most
    # recent swing, regardless of where it sits relative to price. That tests a
    # different level than this same function publishes as liquidity below
    # (nearest_buy_side_liquidity correctly filters to swings ABOVE price).
    #
    # The consequence was silent and total on higher timeframes: once the newest
    # swing high sat below price, `last_high > ref_high` was trivially true and
    # `last_close < ref_high` could never be true, so no sweep was reportable —
    # while the pool price was genuinely raiding went untested. Measured on
    # 2026-07-24 RTH: price breached a published 15m level on 23 of 133 scans
    # and sweep_detected was False on all 133, which starved PO3's three
    # direction fields to fallback_none and left directional authority #2 mute
    # for the entire session.
    #
    # A sweep is a pool that was pierced and rejected, so the reference is the
    # highest swing high the bar actually reached above (or the lowest swing low
    # it reached below) — not whichever swing happened to form last.
    # A raid has three parts: the pool was RESTING beyond price, this bar
    # REACHED it, and the close came back. All three are required — filtering on
    # "pierced" alone would mark every close below any nearby lower swing high as
    # a sweep (measured: 105 of 133 scans on 1m, which is noise, not raids).
    prior = candles[-2]["close"] if len(candles) >= 2 else last["open"]
    pierced_highs = [h for h in highs if prior <= h < last_high]
    pierced_lows = [l for l in lows if last_low < l <= prior]

    # Sweep above swing high: wick pierced it but close is back below
    if pierced_highs:
        ref_high = max(pierced_highs)
        if last_close < ref_high:
            sweep_detected = True
            sweep_direction = "above_high"
            reclaim_detected = True
        elif len(candles) >= 2:
            prev_close = candles[-2]["close"]
            if prev_close > ref_high and last_close < ref_high:
                failed_breakout = True

    # Sweep below swing low: wick pierced it but close is back above
    if not sweep_detected and pierced_lows:
        ref_low = min(pierced_lows)
        if last_close > ref_low:
            sweep_detected = True
            sweep_direction = "below_low"
            reclaim_detected = True
        elif not failed_breakout and len(candles) >= 2:
            prev_close = candles[-2]["close"]
            if prev_close < ref_low and last_close > ref_low:
                failed_breakout = True

    # Buy-side liquidity: resting stops above price (at swing highs above current close)
    above = [h for h in highs if h > last_close]
    buy_side = round(min(above), 2) if above else None

    # Sell-side liquidity: resting stops below price (at swing lows below current close)
    below = [l for l in lows if l < last_close]
    sell_side = round(max(below), 2) if below else None

    return {
        "sweep_detected": sweep_detected,
        "sweep_direction": sweep_direction,
        "reclaim_detected": reclaim_detected,
        "failed_breakout": failed_breakout,
        "nearest_buy_side_liquidity": buy_side,
        "nearest_sell_side_liquidity": sell_side,
    }
