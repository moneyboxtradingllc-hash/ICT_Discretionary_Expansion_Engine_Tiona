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

    # Sweep above swing high: wick pierced it but close is back below
    if highs:
        ref_high = highs[-1]
        if last_high > ref_high and last_close < ref_high:
            sweep_detected = True
            sweep_direction = "above_high"
            reclaim_detected = True
        elif len(candles) >= 2:
            prev_close = candles[-2]["close"]
            if prev_close > ref_high and last_close < ref_high:
                failed_breakout = True

    # Sweep below swing low: wick pierced it but close is back above
    if not sweep_detected and lows:
        ref_low = lows[-1]
        if last_low < ref_low and last_close > ref_low:
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
